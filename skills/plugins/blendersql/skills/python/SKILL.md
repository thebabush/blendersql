---
name: python
description: "The escape hatches — bpy_eval (eval an expression → JSON), bpy_exec (run code → {stdout,result,error}), bpy_op (run any bpy.ops.* operator), and the session_log audit table. Use when the vtables and typed verbs don't cover what you need."
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
---

When SQL rows and the 22 typed verbs aren't enough, drop to Python. Three SQL functions give you the full `bpy` API; `session_log` records what's been done.

**Before writing `bpy_exec`, sanity-check:** if your code is shaped like `for x in bpy.data.<kind>: ...` or `[x.foo for x in bpy.data.<kind>]`, you almost certainly want a vtable instead. Every `bpy.data` container has a corresponding SQL table (`bpy.data.meshes` → `meshes`, `bpy.data.lights` → `lights`, …) — a `SELECT name, users, … FROM <kind> WHERE …` is shorter, faster, and avoids the quoting / multi-line / partial-failure pitfalls below. The orphan / audit / heaviness recipes in the `analysis` skill cover the common cases. Reach for `bpy_exec` when you need genuine per-element method calls (`.update()`, `.transform()`, operators), not for reads or filters.

---

## Discovering an unfamiliar API — introspect first, guess never

`bpy` changes meaningfully between major versions (Blender 4 → 5 renamed `scene.node_tree` to `scene.compositing_node_group`, and `CompositorNodeOutputFile` slots are now `file_output_items` instead of dynamic inputs). If you're not 100% sure of a method signature, attribute name, or parameter — **introspect with `bpy_eval` before writing the edit**. One discovery query beats three failing edits.

The pattern, in order:

```sql
-- 1. What attributes does this object have? (filter by hint when there are many)
SELECT bpy_eval('[a for a in dir(bpy.context.scene) if "node" in a.lower() or "comp" in a.lower()]');
-- → ["compositing_node_group","node_tree", ...]

-- 2. What does this method expect? (docstring carries the signature)
SELECT bpy_eval('bpy.types.NodeTree.nodes.new.__doc__');
-- → "Add a node to this node tree :type type: str ..."

-- 3. For typed properties, bl_rna is the source of truth
SELECT bpy_eval('[p.identifier for p in bpy.data.objects["Cube"].modifiers["Subsurf"].bl_rna.properties]');

-- 4. For collections of sub-items, list one and inspect it
SELECT bpy_eval('[(s.name, s.bl_idname) for s in bpy.context.scene.compositing_node_group.nodes["Render Layers"].outputs]');
```

When a `.new(...)` or attribute access errors, don't retry with a different guess — go up one level and `dir()` the parent first. The error message tells you *what* failed; introspection tells you *what's available instead*.

This matters because blendersql currently doesn't ship full Python API docs (see GitHub issue #4); until it does, `dir()` + `.__doc__` + `bl_rna.properties` are your docs.

---

## The functions

### `bpy_eval(expr)` — evaluate one expression, get JSON back
The expression is `eval`'d with `bpy` and `mathutils` in scope; the result is converted to JSON. Use for *quick reads* and probing.

```sql
SELECT bpy_eval('bpy.app.version_string');                       -- "5.1.1"
SELECT bpy_eval('len(bpy.data.objects)');                        -- 28
SELECT bpy_eval('bpy.context.scene.frame_current');             -- 2349
SELECT bpy_eval('[m.name for m in bpy.data.materials]');        -- ["Mat","Glass",...]
SELECT bpy_eval('bpy.data.objects["Cube"].matrix_world');       -- nested arrays
SELECT bpy_eval('[p.identifier for p in bpy.data.objects["Cube"].modifiers["Subsurf"].bl_rna.properties]');
```

Returns a JSON string. On error: `{"error":"<ExcType>: <message>"}` — the outer query is still `ok:true`, so check the cell.

### `bpy_exec(code)` — run a code block, capture stdout + a `result`
Multi-statement code is `exec`'d with `bpy`/`mathutils` in scope. Set a variable named `result` to return a value (JSON-converted); stdout is captured. Use for *edits* and anything multi-step.

```sql
-- An edit
SELECT bpy_exec('bpy.data.lights["Lamp"].energy = 500');
-- → {"stdout":"","result":null,"error":null}

-- Return a value
SELECT bpy_exec('result = len(bpy.data.objects)');
-- → {"stdout":"","result":28,"error":null}

-- Multi-step: rename, retarget, report (multi-line code lives inside one '...' literal —
-- write strings with " so you never need to escape the surrounding ')
SELECT bpy_exec('
o = bpy.data.objects["Cube"]
o.name = "Hero"
o.modifiers["Subsurf"].levels = 3
print("done")
result = {"name": o.name, "levels": o.modifiers["Subsurf"].levels}
');
-- → {"stdout":"done\n","result":{"name":"Hero","levels":3},"error":null}

-- Direct mesh / attribute edit (no bmesh needed in object mode)
SELECT bpy_exec('m = bpy.data.meshes["Cube"]; m.vertices[0].co.z += 1; m.update()');
```

On error: `{"stdout":"...","result":null,"error":{"type":"<ExcType>","message":"..."}}` — again, outer query stays `ok:true`. SQLite has **no** dollar-quoting (`$$ … $$` is a syntax error); pass code as an ordinary `'…'` literal — newlines inside are fine — and write your Python with `"`-quoted strings so the surrounding `'` never needs escaping (if you must embed a `'`, double it: `''`).

### `bpy_op(operator, params_json?, context_override_json?)` — run any operator
Calls `bpy.ops.<operator>(**params)`, optionally under `context.temp_override(...)`. The override keys `active_object`, `object`, `edit_object`, `selected_objects`, `selected_editable_objects` accept object *names* (resolved for you); anything else (`area`, `region`, `window`, custom keys) is passed verbatim — GUI-bound overrides usually need to be staged via `bpy_exec`.

```sql
-- Add a primitive
SELECT bpy_op('mesh.primitive_uv_sphere_add', '{"radius":1.5}');

-- Apply a modifier (needs an active object)
SELECT bpy_op('object.modifier_apply', '{"modifier":"Subsurf"}', '{"active_object":"Cube"}');

-- Parent with "keep transform"
SELECT bpy_op('object.parent_set', '{"type":"OBJECT","keep_transform":true}',
              '{"active_object":"Rig","selected_objects":["Hand.L","Hand.R"]}');

-- Join meshes
SELECT bpy_op('object.join', '{}', '{"active_object":"Body","selected_editable_objects":["Body","Arm"]}');

-- Set origin to geometry
SELECT bpy_op('object.origin_set', '{"type":"ORIGIN_GEOMETRY"}', '{"active_object":"Cube"}');
```

Returns a `{ok, result, error, ...}` JSON envelope. `bpy.ops` operators register their own undo step, so `bpy_op` doesn't add another. A bad operator name / missing override target / operator failure is reported *inside* the JSON.

---

## When to reach for these vs. the typed surface

Prefer the typed path when it exists — it's terser, validated, and audited:

| You want to… | Use this first | Escape hatch if not covered |
|---|---|---|
| read a property | the relevant vtable; `bpy_eval` for one-offs | `bpy_eval` |
| move/rename/parent/delete an object | `UPDATE`/`DELETE objects` (`scene` skill) | `bpy_exec` / `bpy_op('object.*')` |
| create an object with a data block | `add_object(...)` verb | `bpy_exec` |
| add/edit a modifier or constraint | `add_modifier` / `add_constraint`; `UPDATE modifiers`/`constraints` (`modifiers` skill) | `bpy_op('object.modifier_*')` / `bpy_exec` |
| key a property | `set_keyframe(...)` / `keyframes` CRUD (`animation` skill) | `bpy_exec` (`id.keyframe_insert`) |
| build a node graph | `add_node`/`link_nodes`/`build_node_tree`; `UPDATE node_inputs` (`materials` skill) | `bpy_exec` (`tree.nodes.new` / `tree.links.new`) |
| GP layers/frames/strokes | `gp_add_layer`/`gp_add_frame`/`gp_add_stroke`/`gp_resize_strokes` (`grease_pencil` skill) | `bpy_exec` (`drawing.add_strokes`) |
| add a VSE strip | `vse_add_*` verbs (`vse` skill) | `bpy_op('sequencer.*')` |
| save / load / render / import / export | `save`/`load`/`render`/`import_file`/`export_file` verbs | `bpy_op('wm.*' / 'render.*')` |
| change custom properties | `custom_properties` CRUD (`assets` skill) | `bpy_exec` |
| run an operator with no typed wrapper | — | `bpy_op` |
| anything genuinely off the map | — | `bpy_exec` |

---

## `session_log` — what's been done

Every verb call and every `bpy_eval`/`bpy_exec`/`bpy_op` invocation pushes a row onto an in-memory audit ring:

| Column | Meaning |
|---|---|
| `ts` | monotonic timestamp |
| `op` | function name (`bpy_eval`, `add_modifier`, `set_keyframe`, …) |
| `input` | the (truncated) argument text |
| `success` | 1/0 |
| `duration_ms` | wall time |
| `error_type` | exception class name when it failed, else NULL |

```sql
-- Recent activity
SELECT ts, op, success, duration_ms, error_type, input FROM session_log ORDER BY ts DESC LIMIT 20;

-- What failed this session?
SELECT op, error_type, input FROM session_log WHERE success=0 ORDER BY ts DESC;

-- Op histogram
SELECT op, COUNT(*), SUM(success) AS ok_count FROM session_log GROUP BY op ORDER BY 2 DESC;
```

The ring is per-session and not persisted in the `.blend`.

---

## Gotchas

- **Errors hide in the JSON.** A failing `bpy_eval`/`bpy_exec`/`bpy_op`/verb returns `ok:true` at the query level with the error embedded in the result cell. Always inspect the value (`json_extract(bpy_op(...), '$.error')`).
- `bpy_exec` only returns what you assign to `result`; bare expressions are discarded — assign or `print()`.
- SQLite has no dollar-quoting — pass multi-line `bpy_exec` code as a plain `'…'` literal (newlines OK) and use `"`-quoted strings in the Python so the wrapping `'` never needs escaping; double a literal `'` as `''` if you really need one.
- `bpy_op` runs on Blender's main thread in whatever context the bridge provides — operators that need a specific 3D-viewport/area context will fail unless you stage the override with `bpy_exec` first.
- `bpy_exec`/`bpy_eval` *don't* call `ed.undo_push` for you — if you make an edit you want Ctrl+Z-able, add `bpy.ops.ed.undo_push(message='...')` yourself (the typed verbs and writable vtables already do).
- **Don't loop `bpy.ops.render.render()` (or other heavy, engine-spinning ops) many times inside one `bpy_exec`.** Headless Blender accumulates per-render state (GL/Metal context, depsgraph, engine teardown) with no event-loop tick to clear it between calls; past a handful it *wedges* — the process sits at 0 % CPU stuck inside `render.render`, the bridge stops draining, and there's no graceful recovery (you have to kill it). Render **one thing per `bpy_exec` call** (each is its own bridge round-trip — fine), or, for a big batch, shell out one `blender --background file.blend --python render_one.py` per render (fresh process, fresh context — bulletproof). Same caution for repeated `bpy.ops.wm.*` / sim-bake ops in a tight loop. (Also: scripts that mutate `scene.render.*` / `frame_start`/`frame_end` to drive a render should restore them afterwards unless the session is throwaway — those changes stick and `save()` would persist them.)
- **Writing a still image needs `image_settings.media_type == 'IMAGE'`.** When a scene's output is set to video, `scene.render.image_settings.media_type` is `'VIDEO'` and the `file_format` enum only offers `'FFMPEG'` — assigning `'PNG'` / `'OPEN_EXR'` / etc. raises `enum "PNG" not found in ('FFMPEG')`. Flip `media_type='IMAGE'` first, *then* set `file_format`; restore both afterwards if you want the scene unchanged (the FFmpeg container/codec on `scene.render.ffmpeg.*` survive the toggle, and changing `media_type` coerces `file_format` to a valid value so restore `media_type` before `file_format`). In `--background`, `bpy.ops.render.render(write_still=False)` then reading `bpy.data.images['Render Result']` doesn't work — the result holds no pixel data — so it's `write_still=True` to a path (with `media_type='IMAGE'`), or render in a fresh throwaway scene which defaults to `IMAGE`/`PNG` (what the `render_object` verb does).
