---
name: functions
description: "Complete catalog of BlenderSQL's 26 SQL functions — signatures, arguments, return shape, and an example for each. The reference skill; use for signature lookup."
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
---

BlenderSQL registers 29 SQL functions on top of the virtual tables: 1 search table-function, 3 escape hatches, and 25 typed "verbs". This is the reference. (Domain detail and write recipes live in the per-topic skills — `scene`, `materials`, `animation`, `modifiers`, `vse`, `grease_pencil`, `python`, `analysis`.)

`SELECT name FROM pragma_function_list ORDER BY name;` lists everything SQLite knows (built-ins plus these).

---

## Search

### `grep(pattern [, limit [, offset]])` → JSON array
Unified name search across every named datablock. Returns a JSON array of `{name, kind, parent_name, full_name}`. `pattern` is case-insensitive; `%`/`_` are SQL wildcards; `*` is normalized to `%`; plain text becomes a contains-match. Defaults: `limit=50`, `offset=0`.

```sql
SELECT grep('Probe%');
SELECT grep('Cube', 10, 0);
SELECT json_extract(value,'$.name') AS name, json_extract(value,'$.kind') AS kind
FROM json_each(grep('Mat%', 20, 0));
```

There's also a **`grep` virtual table** with the same fields for when you want `WHERE`/`ORDER BY`/`JOIN`: `SELECT name, kind FROM grep WHERE pattern='Probe%' AND kind='material';` (`kind` values include `object`, `mesh`, `material`, `light`, `camera`, `curve`, `armature`, `image`, `action`, `collection`, …). Use the table for filtering/joining, the function for a quick JSON payload.

---

## Escape hatches (see the `python` skill)

| Function | Signature | Returns |
|---|---|---|
| `bpy_eval` | `bpy_eval(expr)` | JSON string of `eval(expr)` (with `bpy`, `mathutils` in scope); `{"error":"<type>: <msg>"}` on failure |
| `bpy_exec` | `bpy_exec(code)` | `{"stdout": ..., "result": <value of a `result` var>, "error": null \| {"type","message"}}` |
| `bpy_op` | `bpy_op(operator [, params_json [, context_override_json]])` | `{ok, result, error, ...}`; runs `bpy.ops.<operator>(**params)` optionally under `context.temp_override(...)` |

```sql
SELECT bpy_eval('bpy.context.scene.frame_current');
SELECT bpy_exec('result = len(bpy.data.objects)');
SELECT bpy_op('mesh.primitive_uv_sphere_add', '{"radius":1.5}');
SELECT bpy_op('object.modifier_apply', '{"modifier":"Subsurf"}', '{"active_object":"Cube"}');
```

---

## Typed verbs

All 22 are variadic scalar functions returning a `{ok, result, error}` JSON envelope and pushing a `session_log` row. **A verb failure is reported inside the JSON, not as a SQL error** — inspect the cell. `*_json` args are JSON literals passed as strings; empty-string args are treated as "not given".

### Scene / objects
| Function | Signature | Example |
|---|---|---|
| `add_object` | `add_object(type, name [, location_json [, collection]])` | `SELECT add_object('MESH','NewCube','[1,2,3]','Scene Collection');` — creates the matching data block (MESH/CURVE/LIGHT/CAMERA/ARMATURE/GREASEPENCIL/…); `EMPTY` → no data. |

### Modifiers / constraints (see `modifiers`)
| Function | Signature | Example |
|---|---|---|
| `add_modifier` | `add_modifier(object, type [, params_json])` | `SELECT add_modifier('Cube','SUBSURF','{"levels":2,"render_levels":3}');` |
| `add_constraint` | `add_constraint(object, type [, target [, params_json]])` | `SELECT add_constraint('Cube','TRACK_TO','Camera','{"track_axis":"TRACK_NEGATIVE_Z"}');` |

### Animation (see `animation`)
| Function | Signature | Example |
|---|---|---|
| `set_keyframe` | `set_keyframe(datablock_type, datablock_name, data_path, frame [, value [, interpolation [, array_index]]])` | `SELECT set_keyframe('object','Cube','location',10,'[1,2,3]');` — `datablock_type` is lowercase-singular (`object`/`camera`/`light`/…); `value` may be a JSON array (whole vector) or a scalar; nested paths like `'data.lens'` work; auto-creates layer/strip/slot/fcurve. |
| `ensure_fcurve` | `ensure_fcurve(datablock_type, datablock_name, data_path [, array_index [, group_name]])` | `SELECT ensure_fcurve('object','Cube','rotation_euler',2,'MyGroup');` — creates an action if the datablock has none. |

### Node trees (see `materials`)
| Function | Signature | Example |
|---|---|---|
| `add_node` | `add_node(tree_owner, node_type [, location_json [, params_json]])` | `SELECT add_node('ProbeMat','ShaderNodeBump','[-300,0]');` — `tree_owner` is the tree's owner name (material name for shader trees, node-group name for geo-node trees). |
| `link_nodes` | `link_nodes(tree_owner, from_node, from_socket, to_node, to_socket)` | `SELECT link_nodes('ProbeMat','Bump','Normal','Principled BSDF','Normal');` — sockets matched by name or identifier; `'#<index>'` disambiguates. |
| `build_node_tree` | `build_node_tree(tree_owner, spec_json)` | `spec_json = {"clear":bool?, "nodes":[{"name","type","location?","params?"}], "links":[{"from_node","from_socket","to_node","to_socket"}]}` |

### Grease Pencil v3 (see `grease_pencil`)
| Function | Signature | Example |
|---|---|---|
| `gp_add_layer` | `gp_add_layer(gp, name [, layer_group])` | `SELECT gp_add_layer('GPencil.002','inks','Cleanup');` |
| `gp_add_frame` | `gp_add_frame(gp, layer, frame_number [, keyframe_type])` | `SELECT gp_add_frame('GPencil.002','inks',10,'BREAKDOWN');` |
| `gp_add_stroke` | `gp_add_stroke(gp, layer, frame, points_json [, material_index [, cyclic]])` | `points_json` is an array of `[x,y,z]` or `{x,y,z,radius?,opacity?}`: `SELECT gp_add_stroke('GPencil.002','inks',10,'[[0,0,0],[1,0,0],[1,1,0]]');` |
| `gp_resize_strokes` | `gp_resize_strokes(gp, layer, frame, sizes_json)` | `sizes_json` must have one int per existing stroke: `SELECT gp_resize_strokes('GPencil.002','inks',10,'[42,17,25]');` |

### VSE (see `vse`)
| Function | Signature | Example |
|---|---|---|
| `vse_add_sound` | `vse_add_sound(scene, sound_name, channel, frame_start)` | `SELECT vse_add_sound('Edit','voiceover.wav',2,1);` — `sound_name` must be a `bpy.data.sounds` datablock. |
| `vse_add_movie` | `vse_add_movie(scene, filepath, channel, frame_start)` | `SELECT vse_add_movie('Edit','/footage/take01.mp4',1,1);` — takes a file path. |
| `vse_add_scene_strip` | `vse_add_scene_strip(scene, source_scene, channel, frame_start)` | `SELECT vse_add_scene_strip('Edit','Shot_010',3,24);` |
| `vse_add_text` | `vse_add_text(scene, text, channel, frame_start [, frame_end])` | `SELECT vse_add_text('Edit','Title Card',4,1,60);` |
| `vse_add_color` | `vse_add_color(scene, color_json, channel, frame_start [, frame_end])` | `color_json` is `[r,g,b]`: `SELECT vse_add_color('Edit','[0,0,0]',1,1,30);` |

### Files (see `python` for the operator alternatives)
| Function | Signature | Example |
|---|---|---|
| `save` | `save([filepath])` | `SELECT save('');` saves to the current path (errors if never saved); `SELECT save('/tmp/out.blend');` saves a copy and switches to it. |
| `load` | `load(filepath)` | `SELECT load('/projects/shot.blend');` — opens a different file; the file must exist. |
| `render` | `render([scene [, filepath [, frame]]])` | `SELECT render('Main','/tmp/frame.png',24);` — renders a still; uses the active scene if `scene` omitted. |
| `render_object` | `render_object(object [, frame [, filepath [, size]]])` | `SELECT render_object('Strambo');` — renders just that object in a *throwaway scene* (the live scene/camera/frame/config is never touched), auto-framed to its bbox; for a GP object it auto-picks the keyframe with the most strokes if `frame` is omitted. Returns `{path, frame, object}`; default output `<tmpdir>/blendersql_render_<object>.png`. Borrows the object's scene's world so `use_lights` GP layers don't render black. |
| `import_file` | `import_file(filepath [, format])` | `SELECT import_file('/assets/prop.glb');` — format inferred from extension (OBJ/STL/PLY/USD/FBX/GLTF/GLB/X3D) or pass it explicitly; availability of the underlying operator is probed at call time. |
| `export_file` | `export_file(filepath [, format [, selection_json]])` | `SELECT export_file('/out/scene.fbx','FBX','["Cube","Lamp"]');` — `selection_json` is an array of object names to select before export. |

> `render` does a single still. For an *animation* render (a video, or a frame range), or to render through a specific camera, there's no verb yet — drop to `bpy_exec` (`bpy.ops.render.render(animation=True)`), but **one render per `bpy_exec` call**, not a loop: headless Blender wedges after a handful of back-to-back `render.render` calls in one execution (see the `python` skill's gotcha). For many renders, shell out one `blender --background … --python` per render instead.

### Cleanup
| Function | Signature | Example |
|---|---|---|
| `purge_orphans` | `purge_orphans([recursive])` | `SELECT purge_orphans();` — Blender's Orphan Data "Purge": removes datablocks with 0 real users (fake-user'd ones survive); pass a truthy `recursive` to also purge ones that become orphaned in the process. Returns `{removed: {<datablock_type>: count, …}, total}`. |
| `remove_unused_material_slots` | `remove_unused_material_slots([object])` | `SELECT remove_unused_material_slots('Cube');` for one object, or `SELECT remove_unused_material_slots();` for every object — drops material slots no face/stroke/spline references and remaps the geometry's `material_index` values. Returns `{objects: {<name>: count, …}, total}`. |

---

## Quick reference: which skill owns the detail

- `add_object` → `scene` (and `modifiers`)
- `add_modifier`, `add_constraint` → `modifiers`
- `set_keyframe`, `ensure_fcurve` → `animation`
- `add_node`, `link_nodes`, `build_node_tree` → `materials`
- `gp_add_layer`, `gp_add_frame`, `gp_add_stroke`, `gp_resize_strokes` → `grease_pencil`
- `vse_add_*` → `vse`
- `save`, `load`, `render`, `import_file`, `export_file` → `python` (file ops) / `connect`
- `bpy_eval`, `bpy_exec`, `bpy_op` → `python`
- `grep` (function + table) → `analysis` and the `connect` routing matrix
