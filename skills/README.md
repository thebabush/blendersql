# blendersql-skills

Claude Code and Codex plugin packaging for [BlenderSQL](https://github.com/thebabush/blendersql) — a SQL interface to `bpy.data`: a comprehensive SQLite virtual-table surface over `bpy.data`, plus typed verbs and escape-hatch SQL functions, served from a running Blender (the GUI add-on's HTTP server, the `blendersql` headless CLI, or `--http` server mode).

This directory is self-contained — it can be `git subtree`-split into a standalone `blendersql-skills` repo. It is **not** part of the Blender add-on (excluded from the built `.zip` via `blender_manifest.toml`'s `paths_exclude_pattern`).

## Prerequisites

- A running Blender 5.1+ with the BlenderSQL add-on installed, **or** the `blendersql` CLI on your `$PATH` with the add-on discoverable. See the [BlenderSQL repo](https://github.com/thebabush/blendersql) for install.
- Verify: `blendersql -s some.blend -q "SELECT * FROM welcome"` (or `curl -s http://127.0.0.1:8174/status` against the GUI server).

## Installation

### Claude Code

```
/plugin marketplace add thebabush/blendersql-skills
```

Then the skills appear namespaced as `blendersql:connect`, `blendersql:scene`, `blendersql:grease_pencil`, etc. — `/blendersql:scene <prompt>` will resolve once installed.

(Until the repo is published, point Claude Code or Codex at this folder directly, or use the bundled marketplace files for a local install — see below.)

### Codex / agent CLIs

Plugin packaging, not a flat copy into `~/.codex/skills` — the plugin path keeps the `blendersql` namespace so generic names like `scene`, `mesh`, `materials`, `functions` don't collide.

**Home-local install:** clone this repo, `cp -R plugins/blendersql ~/plugins/`, then add to `~/.agents/plugins/marketplace.json`:

```json
{
  "name": "blendersql-tools",
  "interface": { "displayName": "BlenderSQL" },
  "plugins": [
    { "name": "blendersql",
      "source": { "source": "local", "path": "./plugins/blendersql" },
      "policy": { "installation": "AVAILABLE", "authentication": "ON_INSTALL" },
      "category": "Creative Tools" }
  ]
}
```

**Repo-local install:** keep the repo where it is and use the bundled `.agents/plugins/marketplace.json` — it resolves `./plugins/blendersql` relative to the repo root. Restart the agent.

## Layout

```
.claude-plugin/marketplace.json          # Claude Code marketplace manifest
.agents/plugins/marketplace.json         # Codex / agent-CLI marketplace manifest
plugins/blendersql/
  .claude-plugin/plugin.json             # Claude Code plugin manifest
  .codex-plugin/plugin.json              # Codex plugin manifest (+ UI metadata)
  skills/<name>/SKILL.md                 # one skill per directory; YAML frontmatter + Markdown body
```

`SKILL.md` is the canonical skill contract (`name` + `description` frontmatter, then the body).

## Skills

| Skill | Covers | Key tables / functions |
|---|---|---|
| `connect` | The front door: CLI (`-q`/`-f`/`-i`/`--http`), the HTTP server (`POST /query`), the in-Blender Start/Stop operators, the `welcome` orientation table, the routing matrix, and the global contracts (read-first, errors-in-JSON, name-vs-data, `params_json`). | `welcome`, all surfaces |
| `scene` | Scenes, collections, objects, the parent/child hierarchy, transforms. **Writes:** `UPDATE`/`INSERT`/`DELETE objects`. | `scenes`, `collections`, `collection_objects`, `objects` (RW) |
| `grease_pencil` | GP v3: datablocks → layer groups → layers → frames → drawings → strokes → points; the cheap-aggregate trick. **Writes:** `UPDATE gp_layers`, `DELETE gp_strokes`, `gp_add_layer`/`gp_add_frame`/`gp_add_stroke`/`gp_resize_strokes`. | `grease_pencils`, `gp_layer_groups`, `gp_layers` (RW), `gp_frames`, `gp_strokes` (RW), `gp_points`, `gp_drawing_attributes` |
| `mesh` | Meshes, the 5.x attribute system, vertices/edges/polygons/loops/uvs. Read-heavy; the heaviest tables — constrain by `mesh`. | `meshes`, `mesh_attributes`, `mesh_vertices`, `mesh_edges`, `mesh_polygons`, `mesh_loops`, `mesh_uvs` |
| `materials` | Materials, GP material settings, the unified node-tree model. **Writes:** `UPDATE materials`, `UPDATE material_gp_settings`, `UPDATE node_inputs`, `add_node`/`link_nodes`/`build_node_tree`. | `materials` (RW), `material_gp_settings` (RW), `material_slots`, `node_trees`, `nodes`, `node_inputs` (RW), `node_outputs`, `node_links`, `node_tree_interface` |
| `animation` | The 5.1 layered Action tree (actions → slots/layers/strips/channelbags → fcurves → keyframes), `animation_data`, drivers. **Writes:** `keyframes` CRUD, `fcurves` INSERT/DELETE, `set_keyframe`/`ensure_fcurve`. | `actions`, `action_slots`/`action_layers`/`action_strips`/`action_channelbags`, `fcurves` (RW), `keyframes` (RW), `animation_data`, `drivers`/`driver_variables`/`driver_targets` |
| `modifiers` | Modifiers and constraints; `params_json` via `json_extract`. **Writes:** `UPDATE`/`DELETE` on both, `add_modifier`/`add_constraint`. | `modifiers` (RW), `constraints` (RW) |
| `vse` | The Video Sequence Editor: `vse_strips` + per-type side tables. **Writes:** `vse_add_sound`/`movie`/`scene_strip`/`text`/`color`. | `vse_strips`, `vse_strip_sound`/`movie`/`image`/`scene`/`text`/`color` |
| `assets` | The grab-bag: images, sounds, movieclips, cache_files, fonts, curves/splines/points, texts, lights, cameras, armatures/bones/pose_bones, shape keys, vertex groups, palettes, worlds, brushes, masks, annotations, custom properties. **Writes:** `custom_properties` CRUD. | the rest; `custom_properties` (RW) |
| `python` | The escape hatches: `bpy_eval`, `bpy_exec`, `bpy_op`; the `session_log` audit table; when to use these vs. the typed verbs/vtables. | `bpy_eval`/`bpy_exec`/`bpy_op`; `session_log` |
| `functions` | Complete catalog of the SQL functions — signature, args, return shape, an example each. | every function |
| `analysis` | Triage/audit recipes: orientation, name search, reference counts, orphans, heaviest meshes/GP, smell tests, cross-`.blend` comparison. | composes everything |

## License

Mozilla Public License 2.0 — see [LICENSE](LICENSE).
