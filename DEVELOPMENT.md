# Developing BlenderSQL

The user-facing overview is in [README.md](README.md). This file is the technical picture: how it works, the full SQL surface, the HTTP API, the command-line tool, building, testing, releasing.

## How it works

The add-on registers a set of [SQLite virtual tables](https://www.sqlite.org/vtab.html) (via [apsw](https://rogerbinns.github.io/apsw/)) over `bpy.data`. There's no separate database file — the SQLite connection is in-memory and the tables read straight through to Blender's data on every query, so what you see is always current and what you write lands immediately.

`bpy` is main-thread-only, so the HTTP server runs on a background thread and marshals every query onto Blender's main thread (via a `bpy.app.timers` tick). Under `--background` (the CLI's headless mode) there's no timer loop, so the CLI's in-Blender runner drains the bridge queue itself.

| Mode | How to start | Best for |
|------|-------------|----------|
| **Add-on in Blender** | Enable the extension — the server auto-starts (toggle / Start / Stop in prefs) | SQL against the file you're working on, live |
| **Standalone CLI** | `blendersql -s file.blend -i` | Direct SQL, scripting, pipelines, headless |
| **Skill workflow** | `/blendersql:connect` in a coding agent | AI-driven editing — the agent issues SQL on its own |

```
You / Agent  -->  natural language or SQL
                        |
                  /blendersql skills (LLM translates intent to SQL)
                        |
                     BlenderSQL  -->  bpy.data (live)
                        |
                     results  -->  LLM summarizes & reasons
```

```
$ blendersql -s shot_01.blend -q "SELECT name, type FROM objects WHERE type='GREASEPENCIL'"
{"ok": true, "columns": ["name", "type"], "rows": [["Toni", "GREASEPENCIL"], ["Strambo", "GREASEPENCIL"]], "row_count": 2, "duration_ms": 3.1}
```

### Blender version

Hard-targeted at **Blender 5.1**. The table schemas track 5.1's `bpy` API — layered Actions (slots/layers/strips/channelbags/fcurves), Grease Pencil v3 (datablock → layer groups → layers → frames → drawing → strokes → points), the renamed VSE types (`Strip`, `strips_all`, …), `scene.compositing_node_group`, `Material.surface_render_method`, and so on. Other versions aren't tested and almost certainly won't load cleanly.

## The SQL surface

### Tables

78 virtual tables. For the live list: `SELECT name FROM sqlite_master WHERE type='table' ORDER BY name`. For a one-line file summary: `SELECT * FROM welcome`. The headline groups:

| Area | Tables (selection) |
|------|--------------------|
| **Overview** | `welcome`, `session_log` |
| **Scene** | `objects` *(CRUD)*, `scenes`, `collections`, `collection_objects` |
| **Datablock links** | `materials` *(CRUD)*, `material_slots`, `modifiers` *(CRUD)*, `constraints` *(CRUD)*, `custom_properties` *(CRUD)* |
| **Grease Pencil (v3)** | `grease_pencils`, `gp_layer_groups`, `gp_layers` *(CRUD)*, `gp_frames`, `gp_strokes` *(CRUD)*, `gp_points`, `gp_drawing_attributes`, `material_gp_settings` *(UPDATE)* |
| **Animation** | `actions`, `action_slots`, `action_layers`, `action_strips`, `action_channelbags`, `fcurves` *(CRUD)*, `keyframes` *(CRUD)*, `animation_data`, `drivers`, `driver_variables`, `driver_targets` |
| **Nodes** | `node_trees`, `nodes`, `node_inputs` *(UPDATE)*, `node_outputs`, `node_links`, `node_tree_interface` |
| **Mesh** | `meshes`, `mesh_attributes`, `mesh_vertices`, `mesh_edges`, `mesh_polygons`, `mesh_loops`, `mesh_uvs` |
| **Other geometry** | `curves`, `curve_splines`, `curve_points`, `texts`, `armatures`, `bones`, `pose_bones`, `shape_keys`, `shape_key_blocks`, `vertex_groups` |
| **VSE** | `vse_strips`, `vse_strip_sound`, `vse_strip_movie`, `vse_strip_image`, `vse_strip_scene`, `vse_strip_text`, `vse_strip_color` |
| **Assets** | `lights`, `cameras`, `images`, `sounds`, `movieclips`, `cache_files`, `fonts`, `palettes`, `palette_colors`, `linestyles`, `worlds`, `brushes`, `masks`, `annotations` |
| **Search** | `grep` — one search table across every named datablock (`pattern`, `name`, `kind`, `parent_name`, `full_name`) |

*(CRUD)* tables accept `INSERT` / `UPDATE` / `DELETE` (11 of them); everything else is read-only. Every write is wrapped in `bpy.ops.ed.undo_push`, so it's a normal undo step in the UI.

> **Perf note:** the `mesh_*` and `gp_points` tables can be large — constrain them (`WHERE mesh=…` / `WHERE gp=…`) rather than scanning. There's no `BestIndex` push-down yet; SQLite filters post-snapshot. For GP counts, prefer the cached aggregates (`gp_frames.stroke_count`, `gp_strokes.point_count`) over `COUNT(*) FROM gp_points`.

### Functions

29 scalar functions — call them inside any query.

| Function | Description |
|----------|-------------|
| `grep(pattern, limit, offset)` | Search every named datablock; returns JSON (same data as the `grep` table). |
| `bpy_eval(expr)` | Evaluate a `bpy` expression, return its value as JSON. The read escape hatch. |
| `bpy_exec(src)` | Run a `bpy` snippet; returns captured stdout + result. The write escape hatch. |
| `bpy_op(path, params_json, [context_override_json])` | Invoke a `bpy.ops` operator with an optional context override. |
| `add_object`, `add_modifier`, `add_constraint` | Create datablocks that aren't a plain row insert. |
| `set_keyframe`, `ensure_fcurve` | Animation edits. |
| `add_node`, `link_nodes`, `build_node_tree` | Build / modify node graphs. |
| `gp_add_layer`, `gp_add_frame`, `gp_add_stroke`, `gp_resize_strokes` | Grease Pencil authoring. |
| `vse_add_sound`, `vse_add_movie`, `vse_add_scene_strip`, `vse_add_text`, `vse_add_color` | Sequencer strips. |
| `render`, `render_object` | Render the scene, or render one object in isolation to a PNG (auto-framed) — so an agent can *see* what a datablock is. |
| `save`, `load`, `import_file`, `export_file` | File I/O. |
| `purge_orphans`, `remove_unused_material_slots` | Cleanup, mirroring Blender's "purge unused data" / "remove unused slots". |

The 25 verbs (everything except `grep` / `bpy_eval` / `bpy_exec` / `bpy_op`) return `{"ok": …, "result": …, "error": …}` and are appended to `session_log`. The `functions` skill has full signatures.

```sql
-- Most-referenced materials
SELECT name, users FROM materials ORDER BY users DESC LIMIT 10;

-- Everything matching a name pattern, grouped by kind
SELECT kind, COUNT(*) FROM grep WHERE pattern='Probe%' GROUP BY kind;

-- Edit: nudge an object and key it
UPDATE objects SET location_z = location_z + 1 WHERE name = 'Cube';
SELECT set_keyframe('Cube', 'location', 1);

-- Escape hatch
SELECT bpy_eval('[m.name for m in bpy.data.meshes if m.use_fake_user]');

-- Clean up
SELECT purge_orphans();
```

## HTTP API

The add-on hosts a small stateless HTTP server (the CLI's `--http` mode does the same):

```bash
blendersql -s file.blend --http 8174
```

```bash
curl http://127.0.0.1:8174/status
curl -X POST http://127.0.0.1:8174/query -d "SELECT name FROM objects LIMIT 5"
```

Endpoints: `POST /query` (raw SQL in the body → JSON), `GET /status`, `GET /help`, `POST /shutdown`. Run separate instances on different ports to work with two files at once.

The query response is `{"ok": true, "columns": [...], "rows": [...], "row_count": N, "duration_ms": X}` on success, or `{"ok": false, "error": "...", "error_type": "...", "duration_ms": X}` on a SQL error.

> `bpy_exec` runs arbitrary Python and the server has no auth, so keep `bind` on `127.0.0.1`. Token auth + an opt-in `allow_exec` flag are the obvious next step before exposing it any wider.

## The CLI

`blendersql` is a stdlib-only command-line tool. It spawns a headless Blender that loads the add-on (so the add-on still has to be installed and discoverable) and talks to it over HTTP.

```bash
uv tool install git+https://github.com/thebabush/blendersql
# or, from a clone:
uv tool install .
```

```
blendersql -s file.blend -q "SELECT ..."     one query, JSON to stdout
blendersql -s file.blend -f queries.sql      each statement, JSON to stdout
blendersql -s file.blend -i                  interactive REPL
blendersql -s file.blend --http [port]       server only — curl it yourself
```

`-s/--source` is optional (without it you get an empty Blender). `-w/--write` saves the file on exit. `--bind` / `--port` override the server address. This is also the path the skills plugin uses when an agent runs Blender "headless" for you.

## The coding-agent skills

`skills/` is a Claude Code / Codex plugin — 12 topic-focused skills, one `SKILL.md` each.

```bash
claude /install-plugin https://github.com/thebabush/blendersql-skills
```

| Skill | Description |
|-------|-------------|
| `connect` | Connect to a Blender: CLI vs HTTP, session bootstrap, skill routing, global contracts. |
| `analysis` | Triage / audit a `.blend`: orientation, references, orphans, heaviest datablocks, name search, cross-file compare. The "where do I start" skill. |
| `scene` | Objects, hierarchy, collections, transforms, parenting, instancing. |
| `grease_pencil` | GP v3 datablocks, layers, frames, strokes, points, materials, isolated renders. |
| `mesh` | Mesh geometry: vertices, edges, polygons, loops, UVs, attributes. |
| `materials` | Materials, slots, shader / compositor node trees, node interfaces. |
| `animation` | Actions (layered), f-curves, keyframes, drivers, NLA. |
| `modifiers` | Modifiers and constraints — stacks, params, targets. |
| `vse` | Video sequencer strips: sound, movie, image, scene, text, color. |
| `assets` | Images, sounds, movie clips, cache files, fonts, curves, lights, cameras, armatures, shape keys, custom props, … |
| `python` | The `bpy_eval` / `bpy_exec` / `bpy_op` escape hatches — when SQL isn't enough. |
| `functions` | The full SQL function reference catalog. |

The folder is self-contained — it can be `git subtree`-split into a standalone `blendersql-skills` repo — and is excluded from the built extension zip via `blender_manifest.toml`'s `paths_exclude_pattern`. See [`skills/README.md`](skills/README.md) for packaging details.

## Building from source

```bash
make wheels   # download the apsw cp313 wheels for all 5 platforms, regenerate the manifest's `wheels` list
make build    # mkdir dist; blender --command extension build --split-platforms --output-dir dist/
```

Requires Blender 5.1+ on `PATH`. `make build` produces one zip per platform (`blendersql-X.Y.Z-{linux_x64,linux_arm64,macos_x64,macos_arm64,windows_x64}.zip`); each bundles only the apsw wheel matching that platform. `make install-dev` symlinks the repo into Blender's extensions dir for live development.

## Development workflow

```bash
make test       # uv run pytest tests/  — headless-Blender harness, 238 tests
make lint       # ruff check + ruff format --check
make typecheck  # mypy
```

`uv` manages the dev environment. `pre-commit` runs ruff (format + `--fix`) and mypy on every commit; CI runs `pre-commit run --all-files`. The test suite boots a real headless Blender subprocess once per session and drives it over HTTP, so Blender 5.1+ must be on `PATH`. Note `tests/pytest.ini` anchors the rootdir at `tests/` — run `pytest tests/`, not `pytest` from the repo root (the root `__init__.py` is the add-on entry point and imports `bpy`).

## Releasing

1. Bump `version` in both `blender_manifest.toml` and `pyproject.toml`.
2. Commit, then tag and push:
   ```bash
   git tag -a vX.Y.Z -m "BlenderSQL vX.Y.Z"
   git push origin main vX.Y.Z
   ```
3. The `Release` workflow (`.github/workflows/release.yml`) installs Blender 5.1.1, runs `scripts/fetch_wheels.py`, builds the split-platform zips, and attaches them to a `vX.Y.Z` GitHub Release.

## Repo layout

```
blendersql/                the addon — everything Blender loads
  __init__.py              add-on entry point — register()/unregister(), autostart
  blender_manifest.toml    Blender extension manifest (wheels, permissions, build excludes)
  preferences.py           add-on preferences (bind / port / autostart)
  operators.py             Start/Stop server operators (UI buttons)
  bridge/                  main-thread marshaling (run_on_main + the timer drain)
  server/http.py           the HTTP server (/query /status /help /shutdown)
  sql/
    engine.py              the apsw connection; execute() -> QueryResult
    result.py              QueryResult dataclass (the wire format)
    vtables/               one module per table group; base.py has the vtable bases
    functions/             grep, bpy_eval/exec/op; verbs/ has the 25 typed verbs
  cli/                     standalone `blendersql` CLI + the in-Blender runner
  wheels/                  vendored apsw wheels (only the dev macOS-arm64 one is committed)
tests/                     headless-Blender pytest harness + fixtures
skills/                    the Claude/Codex skills plugin (not shipped in the zip)
scripts/fetch_wheels.py    download apsw wheels, regenerate the manifest's `wheels`
```

## License

[Mozilla Public License 2.0](LICENSE).
