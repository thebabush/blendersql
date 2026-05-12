# BlenderSQL

**Give any AI agent the ability to read and edit a Blender file — over SQL.**

BlenderSQL is a Blender add-on that exposes `bpy.data` as live SQLite virtual tables: 75 tables covering objects, scenes, collections, meshes, grease pencil, materials, node trees, animation, modifiers, constraints, the video sequencer, and every named datablock — plus 29 SQL functions for editing and a `bpy` escape hatch. Drive it headlessly from a coding agent with the bundled `/blendersql` skills, or open Blender's UI and collaborate with your agent in real time. No add-on scripting. No `bpy` boilerplate. Just SQL.

> **Blender version:** BlenderSQL targets **Blender 5.1** for now — the table schemas track 5.1's `bpy` API (layered Actions, Grease Pencil v3, the renamed VSE types, …). Older or newer versions aren't supported yet.

> **Why SQL?** SQL is the lingua franca every AI agent already speaks, and it composes — joins, aggregates, filters — in ways a fixed tool surface doesn't. BlenderSQL is agent-agnostic: Claude, Copilot, Codex, a custom agent, or no agent at all. Anything that can POST a query can inspect and modify a `.blend`.

- **No export, no index.** Blender already has everything in memory. Queries run against the live `bpy.data` via an in-memory SQLite connection wrapping it.
- **Read *and* write.** 11 of the 75 tables accept `INSERT`/`UPDATE`/`DELETE` (objects, materials, modifiers, constraints, keyframes, f-curves, GP layers, GP strokes, custom properties, node inputs, GP material settings). Every write goes through `bpy.ops.ed.undo_push` — it's undoable in the UI.
- **Verbs for the rest.** 25 typed SQL functions cover the things that aren't a row edit: `add_object`, `add_modifier`, `set_keyframe`, `build_node_tree`, `gp_add_stroke`, `render_object`, `purge_orphans`, `save`/`load`, import/export, … Each returns a JSON envelope and is logged to the `session_log` table.
- **Headless, GUI, or both.** Run a `.blend` through the standalone `blendersql` CLI, or enable the add-on in a running Blender and curl its HTTP server, or let your coding agent orchestrate either.
- **No MCP, no SDK.** Any client that can POST a string can drive it. The HTTP `/query` endpoint *is* the protocol.

## How It Works

The add-on registers a set of [SQLite virtual tables](https://www.sqlite.org/vtab.html) (via [apsw](https://rogerbinns.github.io/apsw/)) over `bpy.data`. There's no separate database file — the SQLite connection is in-memory and the tables read straight through to Blender's data on every query, so what you see is always current and what you write lands immediately.

`bpy` is main-thread-only, so the HTTP server runs on a background thread and marshals every query onto Blender's main thread (via a `bpy.app.timers` tick). Under `--background` (the CLI's headless mode) there's no timer loop, so the CLI's in-Blender runner drains the queue itself.

| Mode | How to start | Best for |
|------|-------------|----------|
| **Standalone CLI** | `blendersql -s file.blend -i` | Direct SQL, scripting, pipelines, headless |
| **Add-on in Blender** | Enable the extension — the server starts automatically (toggle in prefs) | SQL against the file you're working on, live |
| **Skill workflow** | `/blendersql:connect` in your coding agent | AI-driven editing — the agent issues SQL on its own |

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
*One command. The live file. No `bpy` script.*

## Quick Start

1. Install the add-on (see [Installation](#installation)) and enable it. It starts a localhost HTTP server (default `127.0.0.1:8174`) automatically — untick *Start server on load* in its preferences if you don't want that, or use the Start/Stop buttons there.
2. Install the `/blendersql` skills into your coding agent.
3. In your agent, point it at the open Blender:

   ```
   /blendersql:connect Let's work with the Blender I have open at http://127.0.0.1:8174 — what grease pencil objects are in here?
   ```

4. Chat naturally from there:

   ```
   /blendersql:grease_pencil The guy in the bucket hat — recolor the hat to red.
   /blendersql:analysis Is anything broken or orphaned in this file? Clean it up.
   ```

Or stay headless — let the agent run Blender for you:

```
/blendersql:connect Open ~/shots/shot_01.blend in the background and tell me which meshes are heaviest.
```

The agent starts a headless Blender via the `blendersql` CLI, queries it, and reports back. Ask it to `save` and exit when you're done.

## Installation

### The add-on

Download the zip for your platform from [Releases](https://github.com/thebabush/blendersql/releases) and install it via Blender's *Edit → Preferences → Get Extensions → Install from Disk*. The zip bundles the matching `apsw` wheel — no `pip` needed.

To build from source instead:

```bash
make wheels   # fetch the apsw wheels for all platforms
make build    # blender --command extension build --split-platforms --output-dir dist/
```

(Requires Blender 5.1+ on `PATH`.)

### The standalone CLI

```bash
uv tool install git+https://github.com/thebabush/blendersql
# or, from a clone:
uv tool install .
```

The CLI is stdlib-only — it spawns a headless Blender that loads the add-on (so the add-on still needs to be installed) and talks to it over HTTP.

```
blendersql -s file.blend -q "SELECT ..."     one query, JSON to stdout
blendersql -s file.blend -f queries.sql      each statement, JSON to stdout
blendersql -s file.blend -i                  interactive REPL
blendersql -s file.blend --http [port]       server only — curl it yourself
```

`--source` is optional; without it you get an empty Blender. `--write` saves on exit. `--bind`/`--port` override the server address.

### The coding-agent skills

The `skills/` folder is a Claude Code / Codex plugin — 12 topic-focused skills (`connect`, `scene`, `grease_pencil`, `mesh`, `materials`, `animation`, `modifiers`, `vse`, `assets`, `python`, `functions`, `analysis`).

```bash
claude /install-plugin https://github.com/thebabush/blendersql-skills
```

For Codex, point it at the `Skills/` folder of that repo.

| Skill | Description |
|-------|-------------|
| `connect` | Connect to a Blender: CLI vs HTTP, session bootstrap, skill routing, global contracts. |
| `analysis` | Triage / audit a `.blend`: orientation, references, orphans, heaviest datablocks, name search, cross-file compare. The "where do I start" skill. |
| `scene` | Objects, hierarchy, collections, transforms, parenting, instancing. |
| `grease_pencil` | GP v3 datablocks, layers, frames, strokes, points, materials, isolated renders. |
| `mesh` | Mesh geometry: vertices, edges, polygons, loops, UVs, attributes. |
| `materials` | Materials, slots, shader/compositor node trees, node interfaces. |
| `animation` | Actions (layered), f-curves, keyframes, drivers, NLA. |
| `modifiers` | Modifiers and constraints — stacks, params, targets. |
| `vse` | Video sequencer strips: sound, movie, image, scene, text, color. |
| `assets` | Images, sounds, movie clips, cache files, fonts, curves, lights, cameras, armatures, shape keys, custom props, … |
| `python` | The `bpy_eval` / `bpy_exec` / `bpy_op` escape hatches — when SQL isn't enough. |
| `functions` | The full SQL function reference catalog. |

## Available Tables

75 virtual tables. For the live list run `SELECT name FROM sqlite_master WHERE type='table' ORDER BY name`, and `SELECT * FROM welcome` for a one-line file summary. The headline groups:

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
| **Search** | `grep` — one search table across every named datablock (`pattern`, `name`, `kind`) |

*(CRUD)* tables accept `INSERT`/`UPDATE`/`DELETE`; everything else is read-only. All writes are wrapped in an undo step.

## SQL Functions

29 scalar functions — call them inside any query.

| Function | Description |
|----------|-------------|
| `grep(pattern, limit, offset)` | Search every named datablock; returns JSON (same data as the `grep` table). |
| `bpy_eval(expr)` | Evaluate a `bpy` expression, return its value as JSON. The read escape hatch. |
| `bpy_exec(src)` | Run a `bpy` snippet; returns captured stdout + result. The write escape hatch. |
| `bpy_op(path, params_json, [context_override_json])` | Invoke a `bpy.ops` operator with an optional context override. |
| `add_object`, `add_modifier`, `add_constraint` | Create datablocks that aren't a plain row insert. |
| `set_keyframe`, `ensure_fcurve` | Animation edits. |
| `add_node`, `link_nodes`, `build_node_tree` | Build/modify node graphs. |
| `gp_add_layer`, `gp_add_frame`, `gp_add_stroke`, `gp_resize_strokes` | Grease Pencil authoring. |
| `vse_add_sound`, `vse_add_movie`, `vse_add_scene_strip`, `vse_add_text`, `vse_add_color` | Sequencer strips. |
| `render`, `render_object` | Render the scene, or render one object in isolation to a PNG (auto-framed) — useful so an agent can *see* what a datablock is. |
| `save`, `load`, `import_file`, `export_file` | File I/O. |
| `purge_orphans`, `remove_unused_material_slots` | Cleanup, mirroring Blender's "purge unused data" / "remove unused slots". |

Each verb returns `{"ok": …, "result": …, "error": …}` and is appended to `session_log`. See the `functions` skill for full signatures.

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

## Integration

### HTTP REST API

The add-on hosts a small stateless HTTP server (the CLI's `--http` does the same):

```bash
blendersql -s file.blend --http 8174
```

```bash
curl http://127.0.0.1:8174/status
curl -X POST http://127.0.0.1:8174/query -d "SELECT name FROM objects LIMIT 5"
```

Endpoints: `POST /query` (raw SQL in the body → JSON), `GET /status`, `GET /help`, `POST /shutdown`. Run separate instances on different ports to work with two files at once.

## Development

```bash
make test       # uv run pytest tests/  — headless-Blender harness, 238 tests
make lint       # ruff check + ruff format --check
make typecheck  # mypy
make build      # build the platform extension zips into dist/
```

`uv` manages the dev environment; `pre-commit` runs ruff + mypy on commit. Tests spin up a real headless Blender subprocess, so Blender 5.1+ must be on `PATH`.

## Credits

Heavy inspiration from [**idasql**](https://github.com/allthingsida/idasql) by [Elias Bachaalany (@0xeb)](https://github.com/0xeb) — the project that pioneered exposing a host application's internal data model as live SQL virtual tables so any agent can query and edit it. I'm a heavy idasql user myself and consider it a game-changer for reverse engineering — if that's your space, go look. BlenderSQL applies the same idea to Blender, independently implemented in Python on [apsw](https://rogerbinns.github.io/apsw/). Big thanks to Elias.

## Disclosure

This project is mostly vibecoded, and I mostly use it for my Grease Pencil / 2D Animation, so beware.

## License

[Mozilla Public License 2.0](LICENSE).
