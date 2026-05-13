---
name: connect
description: "Connect to a Blender .blend file over SQL and bootstrap a session. Use when starting work, choosing CLI vs HTTP vs the in-Blender add-on, or routing to a domain skill."
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
---

BlenderSQL exposes `bpy.data` as ~75 SQLite virtual tables (10 writable) plus 26 SQL functions, served from a running Blender. This skill is the front door: connect, orient, then route.

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

## Session Bootstrap Contract

1. Connect (`-q`, `-i`, `--http`, or the GUI add-on).
2. Orient:
   ```sql
   SELECT * FROM welcome;
   ```
   `welcome` is a one-row table: `blender_version, filepath, is_dirty, active_scene, scene_count, object_count, collection_count, material_count, mesh_count, grease_pencil_count, action_count, image_count, sound_count`. This is the closest thing to a `blend_info` table.
3. List the surfaces:
   ```sql
   SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;
   ```
4. Introspect a table before authoring complex SQL — column names are not always obvious:
   ```sql
   SELECT sql FROM sqlite_master WHERE name='objects';   -- registration line
   PRAGMA table_info(objects);                            -- columns + types
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
