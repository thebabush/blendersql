---
name: connect
description: "Connect to a Blender .blend file over SQL and bootstrap a session. Use when starting work, choosing CLI vs HTTP vs the in-Blender add-on, or routing to a domain skill."
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
---

BlenderSQL exposes `bpy.data` as ~78 SQLite virtual tables (12 writable) plus 26 SQL functions, served from a running Blender. This skill is the front door: connect, orient, then route.

---

## Quick Start (Do This First)

```bash
# one query, JSON to stdout (same shape as HTTP POST /query)
blendersql -s scene.blend -q "SELECT * FROM welcome"

# run a .sql file (semicolon-separated statements)
blendersql -s scene.blend -f queries.sql

# interactive REPL — .help, .tables, .schema <table>, .q to exit
blendersql -s scene.blend -i

# long-lived HTTP server for iterative work (port optional, default 8174)
blendersql -s scene.blend --http 8174

# persist edits made during the session (otherwise the .blend is untouched on exit)
blendersql -s scene.blend -w -q "INSERT INTO objects(name,type) VALUES('Probe','EMPTY')"
```

Over HTTP, every query is `POST /query` with raw SQL in the body. The server reads the body verbatim — no JSON wrapper, no form encoding, no Content-Type check. Pick the form that avoids shell-quote pain:

```bash
# 1. Short one-liner — fine when the SQL has no quotes you'd have to escape.
curl -s -X POST http://127.0.0.1:8174/query -d "SELECT name,type FROM objects LIMIT 10"

# 2. File body — best for multi-line SQL or anything with embedded ' and ".
#    --data-binary preserves bytes verbatim; plain -d strips CR/LF.
cat > /tmp/q.sql <<'EOF'
SELECT
  "has double "" quote" AS d,
  'has single '' quote' AS s,
  bpy_eval('"GREETING, " + "world!"') AS msg
EOF
curl -s --data-binary @/tmp/q.sql http://127.0.0.1:8174/query

# 3. Heredoc straight into curl — same effect, no temp file. The 'EOF' (quoted)
#    keeps the shell from expanding $vars / backticks inside the SQL.
curl -s --data-binary @- http://127.0.0.1:8174/query <<'EOF'
SELECT bpy_eval('"GREETING, " + "world!"') AS msg
EOF

curl -s http://127.0.0.1:8174/status        # {"status": "ok", "running": true}
curl -s http://127.0.0.1:8174/help          # endpoint list
curl -s -X POST http://127.0.0.1:8174/shutdown
```

Rule of thumb: use form 1 only for trivial selects. The moment you need `bpy_eval('…python…')` or any embedded `'`/`"`, switch to form 2 or 3 — three layers of escaping (shell, SQL, Python) is the route to `chr(71)+chr(82)+…` workarounds. Always `--data-binary`, never plain `-d @file`, when the body has meaningful newlines.

Inside the Blender GUI: open **Edit ▸ Preferences ▸ Add-ons ▸ BlenderSQL** and click **Start BlenderSQL Server** (or set "Start server on load"). It listens on `127.0.0.1:8174`; hit `/query` exactly as above. There is no in-Blender REPL prompt — the add-on only exposes the Start/Stop operators (`blendersql.start_server` / `blendersql.stop_server`).

Guardrails:
- Always pass `-s <file.blend>` on the CLI.
- `-q`/`-f` do **not** save by default — add `-w` to write changes back.
- Reads run on Blender's main thread; keep individual queries cheap (constrain heavy tables — see `mesh`, `analysis`).

---

## Self-Describing Introspection (`bsql_tables` / `bsql_columns`)

Two vtables describe the rest of the surface so you don't have to `PRAGMA table_info` your way around it:

- **`bsql_tables`** — one row per registered vtable: `name, writable, description, agent_hint, column_count, related`. The orienting query.
- **`bsql_columns`** — one row per declared column across every vtable: `"table", name, type, writable, pk, hint`. Filter with `WHERE "table"=?` — `table` is a SQL keyword so it must stay quoted.

```sql
-- Bootstrap query — read this before reaching for sqlite_master:
SELECT name, writable, description FROM bsql_tables ORDER BY name;

-- Zoom into a table's columns + writability + hints:
SELECT name, type, writable, pk, hint FROM bsql_columns WHERE "table"='objects';
```

These subsume most needs that `PRAGMA table_info` previously covered — and add agent-facing `description` / `agent_hint` / `pk` / `writable` that PRAGMA can't surface.

The full catalog, regenerated from the live registry (do not edit by hand — run `python scripts/regen_skills.py --write`):

<!-- BSQL-AUTOGEN:vtables -->
| name | writable | description |
|---|---|---|
| `action_channelbags` |  | Per-strip channelbags: slot-keyed buckets of fcurves. |
| `action_layers` |  | Per-action layers: positional list that holds strips. |
| `action_slots` |  | Per-action slots: target id-type binding, identifier, handle. |
| `action_strips` |  | Per-layer strips: positional, untyped-by-name, host the channelbags. |
| `actions` |  | Action datablocks: frame range, slot/layer counts, user refcount. |
| `animation_data` |  | AnimData blocks across every datablock kind: bound action, slot, NLA state. |
| `annotations` |  | Legacy GP-v2 annotation datablocks (viewport strokes); minimal surface. |
| `armatures` |  | Armature datablocks: name, refcount, bone count. |
| `bones` |  | Rest-pose bones from armature data: hierarchy, deform flags, head/tail in local space. |
| `brushes` |  | Brush datablocks: per-mode tool type, size/strength, blend mode, params blob. |
| `bsql_columns` |  | Per-column metadata across every registered vtable. |
| `bsql_functions` |  | Self-describing catalog of every SQL scalar function + verb. |
| `bsql_related` |  | Long form of bsql_tables.related: one row per (table, related-table) edge. |
| `bsql_tables` |  | Self-describing catalog of every blendersql vtable. |
| `cache_files` |  | CacheFile datablocks: Alembic / USD references with playback offsets. |
| `cameras` |  | Camera datablocks: lens, sensor, clip range, DOF basics, ortho scale. |
| `collection_objects` |  | Direct (non-recursive) (collection, object) membership links. |
| `collections` |  | Collection hierarchy: parent link, visibility, child/object counts. |
| `constraints` | yes | Object and pose-bone constraints: target binding, influence, packed params. |
| `curve_points` |  | Per-spline control points: position, radius/tilt, bezier handles (BEZIER only). |
| `curve_splines` |  | Per-curve splines: type (BEZIER/POLY/NURBS), point count, U-axis settings. |
| `curves` |  | Curve datablocks: dimensions, bevel/fill settings, spline count. |
| `custom_properties` | yes | ID-property key/value pairs across every named datablock, with UI metadata. |
| `driver_targets` |  | Driver variable targets: the actual ID + data_path / transform-source bindings. |
| `driver_variables` |  | Driver input variables: name, type, target count. |
| `drivers` |  | Property drivers on every datablock: expression, variables, remap curve. |
| `fcurves` | yes | Channelbag f-curves: per-property animation curves with keyframes. |
| `fonts` |  | VectorFont datablocks: filepath, refcount, packed state. |
| `gp_drawing_attributes` |  | Generic geometry attributes on each GP drawing: domain (POINT/CURVE) + dtype. |
| `gp_frames` |  | Grease Pencil per-layer frames: frame number, keyframe type, stroke count. |
| `gp_layer_groups` |  | Grease Pencil layer groups: nestable folders that hold gp_layers. |
| `gp_layers` | yes | Grease Pencil layers: per-layer transform, tint, opacity, masking flags. |
| `gp_points` |  | Grease Pencil per-stroke points: position, radius, opacity, vertex color. |
| `gp_strokes` | yes | Grease Pencil strokes inside a drawing: curve geometry, fill, caps, material. |
| `grease_pencils` |  | Grease Pencil v3 datablocks: layer counts, onion-skin settings, depth order. |
| `grep` |  | Full-text-ish search across every named bpy datablock. |
| `images` |  | Image datablocks: filepath, source, dimensions, packed state. |
| `keyframes` | yes | F-curve keyframe points: (frame,value) + interpolation + bezier handles. |
| `lights` |  | Light datablocks: type, energy, color, shadow/nodes flags, type-specific params. |
| `linestyles` |  | FreestyleLineStyle datablocks: base color, thickness, chaining, node usage. |
| `masks` |  | Mask datablocks: 2D bezier masks with playback range and layer count. |
| `material_gp_settings` | yes | Grease Pencil style settings on each GP material: stroke/fill colors, mix, texture, flags. |
| `material_slots` | yes | Per-object material slots: which material is bound at each slot index. |
| `materials` | yes | Material datablocks: nodes flag, GP flag, surface render method. |
| `mesh_attributes` |  | Per-mesh generic attributes: built-ins + user data, with domain + type. |
| `mesh_edges` |  | Per-mesh edges: vertex pair, seam/sharp/loose flags, edit-mode visibility. |
| `mesh_loops` |  | Per-mesh polygon corners (loops): vertex/edge reference and corner normal. |
| `mesh_polygons` |  | Per-mesh polygons (faces): material index, geometry, flags. |
| `mesh_uvs` |  | Per-loop UV coordinates across every UV layer of every mesh. |
| `mesh_vertices` |  | Per-mesh vertices: position, normal, hide/select flags. |
| `meshes` |  | Mesh datablocks: vertex/edge/polygon/loop counts, UV+material counts. |
| `modifiers` | yes | Per-object modifier stack with type and packed parameters. |
| `movieclips` |  | MovieClip datablocks: filepath, duration, fps, resolution. |
| `node_inputs` | yes | Input sockets on every node: identifier, type, default value, link status. |
| `node_links` |  | Edges in every node tree: which output drives which input, mute/valid flags. |
| `node_outputs` |  | Output sockets on every node: identifier, type, default value, link status. |
| `node_tree_interface` |  | Per-node-group interface items: the group's exposed sockets and panels. |
| `node_trees` |  | Every node tree in the file: standalone groups plus embedded trees. |
| `nodes` |  | Nodes across every node tree: identity, type, layout, mute/hide flags. |
| `objects` | yes | Scene objects: identity, type, transform, parent, first collection. |
| `palette_colors` |  | Per-palette color entries: RGB plus weight/strength for paint tools. |
| `palettes` |  | Palette datablocks: name, refcount, color count. |
| `pose_bones` |  | Per-object pose-space bone transforms: location/rotation/scale relative to rest. |
| `scene_objects` |  | Recursively flattened per-scene object list (walks nested collections). |
| `scenes` |  | Scene datablocks: frame range, fps, render engine, camera/world bindings. |
| `session_log` |  | In-memory audit ring of side-effecting calls (bpy_eval/bpy_exec/bpy_op/verbs). |
| `shape_key_blocks` |  | Individual shape-key blocks: per-shape value, slider range, relative-to basis. |
| `shape_keys` |  | Shape-key datablocks (Key): owning geometry, basis, blend mode, block count. |
| `sounds` |  | Sound datablocks: filepath, refcount, cache + packed state. |
| `texts` |  | TextCurve datablocks (3D text): body string, size, alignment, font. |
| `vertex_groups` |  | Per-object vertex groups: name, slot index, lock flag. |
| `vse_strip_color` |  | Color-strip extension: solid RGB fill (no alpha at the strip level). |
| `vse_strip_image` |  | Image-strip extension: source directory, frame offsets into the sequence. |
| `vse_strip_movie` |  | Movie-strip extension: source filepath, stream index, source fps. |
| `vse_strip_scene` |  | Scene-strip extension: rendered source scene, camera override, input mode. |
| `vse_strip_sound` |  | Sound-strip extension: bound sound datablock, volume/pan, pitch correction. |
| `vse_strip_text` |  | Text-strip extension: text, font, size, color, anchor/alignment, outline/shadow. |
| `vse_strips` |  | VSE strips (all kinds): timing, channel, blend, mute/lock, metastrip parent. |
| `welcome` |  | Single-row file summary: Blender version, filepath, active scene, datablock counts. |
| `worlds` |  | World datablocks: nodes flag and base color (background). |
<!-- /BSQL-AUTOGEN:vtables -->

Writable subset (these accept `UPDATE` / `INSERT` / `DELETE`):

<!-- BSQL-AUTOGEN:writable-tables -->
- `constraints`
- `custom_properties`
- `fcurves`
- `gp_layers`
- `gp_strokes`
- `keyframes`
- `material_gp_settings`
- `material_slots`
- `materials`
- `modifiers`
- `node_inputs`
- `objects`
<!-- /BSQL-AUTOGEN:writable-tables -->

---

## Session Bootstrap Contract

1. Connect (`-q`, `-i`, `--http`, or the GUI add-on).
2. Orient:
   ```sql
   SELECT * FROM welcome;
   ```
   `welcome` is a one-row table: `blender_version, filepath, is_dirty, active_scene, scene_count, object_count, collection_count, material_count, mesh_count, grease_pencil_count, action_count, image_count, sound_count`. This is the closest thing to a `blend_info` table.
3. List the surfaces (prefer `bsql_tables` — it carries descriptions + writability):
   ```sql
   SELECT name, writable, description FROM bsql_tables ORDER BY name;
   ```
4. Introspect a table before authoring complex SQL — column names are not always obvious:
   ```sql
   SELECT name, type, writable, pk, hint FROM bsql_columns WHERE "table"='objects';
   ```
5. Route with the matrix below.

Never skip steps 2–4 when the prompt is broad ("what's in this file?", "clean this up").

---

## Skill Routing Matrix (Intent → Skill)

| User intent | Skill | Typical first query |
|---|---|---|
| "what's in this .blend?" / triage / audit | `analysis` | `SELECT * FROM welcome;` |
| scenes, collections, objects, hierarchy, selection; move/rename/parent/delete objects | `scene` | `SELECT name,type,parent FROM objects;` |
| grease pencil: layers, frames, drawings, strokes, points | `grease_pencil` | `SELECT name,layer_count FROM grease_pencils;` |
| meshes, vertices/edges/polys/loops/uvs, attributes | `mesh` | `SELECT name,vertex_count,polygon_count FROM meshes;` |
| materials, node trees, sockets, links; recolor BSDF; build a node graph | `materials` | `SELECT name,use_nodes FROM materials;` |
| animation: actions, slots/layers/strips/channelbags, fcurves, keyframes, drivers | `animation` | `SELECT name,is_action_layered FROM actions;` |
| modifiers and constraints; add/edit/delete them | `modifiers` | `SELECT object,type FROM modifiers;` |
| video sequencer: strips and their per-type settings | `vse` | `SELECT scene,name,type FROM vse_strips;` |
| images/sounds/clips/fonts/curves/lights/cameras/armatures/shape keys/vertex groups/custom properties/etc. | `assets` | `SELECT name,filepath FROM images;` |
| run arbitrary Python / any `bpy.ops.*` / audit what was done | `python` | `SELECT bpy_eval('bpy.app.version_string');` |
| "what SQL function does X?" / signature lookup | `functions` | (read the `functions` skill) |

When a prompt spans domains: orient in `connect`, work the primary skill, enrich with adjacent skills (e.g. `scene` → `modifiers` → `materials`).

---

## Global Contracts (apply to every BlenderSQL skill)

**Read-first.** `SELECT` the current state before any `UPDATE`/`INSERT`/`DELETE`. Confirm the target row with a stable key (datablock `name`, the composite keys for nested rows).

**Anti-guessing.** Don't assume columns for long-tail tables. `PRAGMA table_info(<table>)` first.

**Mutation loop.** 1) read current state, 2) apply the write, 3) re-read and verify. For node-tree edits the read tables refresh automatically on the next query.

**Errors come back two ways:**
- A bad *SQL row write* (e.g. `UPDATE objects SET type='MESH' …`) raises a SQL error → the query result is `ok:false` with an `error` string.
- A failure *inside a verb / `bpy_eval` / `bpy_exec` / `bpy_op`* is reported **inside the returned JSON** (`{"ok":false,"error":...}` or `{"error":...}` or `{"error":{"type":...,"message":...}}`). The outer query stays `ok:true` — you must inspect the cell value, not just the query status.

**Quoting.** Several schemas use column names that are SQL keywords (`index`, `select`, `default`). Quote them: `SELECT "index", "select" FROM mesh_vertices WHERE mesh='Cube'`.

**Names: data vs object.** An object and its data block are different things with (often) different names. Bridge with `JOIN objects o ON o.data = m.name` (mesh), `o.data = c.name` (curve), `o.data = a.name` (armature), etc. `objects.data` is the data block's name, `objects.name` is the object's.

**`params_json`.** Tables like `modifiers`, `constraints`, `lights`, `cameras`, `brushes` carry type-specific fields as a JSON blob in `params_json`. Query into it with `json_extract`: `SELECT object, json_extract(params_json,'$.levels') AS subsurf_levels FROM modifiers WHERE type='SUBSURF'`.

**Writes go through the same endpoint.** `INSERT`/`UPDATE`/`DELETE` and verb calls are just SQL — same `/query` POST, same `-q`. Add `-w` (CLI) to persist; over HTTP the file stays in memory unless you `SELECT save('')`.

---

## Cross-Skill Recipes

- **Audit → fix:** `analysis` (find orphaned/heaviest datablocks) → domain skill (edit) → `analysis` (re-check).
- **Object → mesh → material:** `scene` (find the object) → `mesh` (inspect geometry via `o.data`) → `materials` (recolor its node tree).
- **Animate a property:** `scene`/`assets` (find the datablock) → `animation` (`set_keyframe(...)`, then read `fcurves`/`keyframes`).
- **Something not modeled:** `python` — `bpy_exec` for arbitrary edits, `bpy_op` for any operator.

---

## When SQL Isn't Enough

The vtables and 22 typed verbs cover the common paths. For anything else, the `python` skill owns `bpy_eval(expr)` (returns JSON), `bpy_exec(code)` (returns `{stdout, result, error}`), and `bpy_op(operator, params_json, context_override_json)` (any `bpy.ops.*`). Every verb and escape-hatch call is recorded in the `session_log` table — `SELECT * FROM session_log ORDER BY ts DESC` to see what's been done.
