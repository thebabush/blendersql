---
name: assets
description: "The 'everything else' grab-bag — images, sounds, clips, fonts, curves, lights, cameras, armatures/bones, shape keys, vertex groups, palettes, worlds, brushes, masks, text font-curves, custom properties. Use to inspect or edit these datablocks."
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
---

The datablock types that don't get their own dedicated skill. Most are read-only single-table surfaces; the standout writable one is `custom_properties`. As always, an object and its data block have different names — bridge with `JOIN objects o ON o.data = <data>.name`.

---

## Tables

### Linked external data
| Table | Key columns |
|---|---|
| `images` | `name`, `filepath`, `source`, `width`, `height`, `channels`, `depth`, `file_format`, `packed`, `users`, `has_data`, `alpha_mode`, `colorspace_name` |
| `sounds` | `name`, `filepath`, `users`, `use_memory_cache`, `packed` |
| `movieclips` | `name`, `filepath`, `users`, `frame_duration`, `fps`, `size_x`, `size_y` |
| `cache_files` | `name`, `filepath`, `users`, `frame`, `frame_offset`, `override_frame`, `scale`, `forward_axis`, `up_axis` |
| `fonts` | `name`, `filepath`, `users`, `packed` |

### Object data blocks
| Table | Key columns |
|---|---|
| `curves` | `name`, `users`, `dimensions` (`2D`/`3D`), `bevel_depth`, `bevel_mode`, `fill_mode`, `spline_count` |
| `curve_splines` | `curve`, `index`, `type` (`POLY`/`BEZIER`/`NURBS`), `point_count`, `use_cyclic_u`, `resolution_u`, `order_u` |
| `curve_points` | `curve`, `spline`, `index`, `point_type`, `x`, `y`, `z`, `radius`, `tilt`, `weight_softbody`, `handle_left_x/y/z`, `handle_right_x/y/z` |
| `texts` | `name`, `body`, `size`, `align_x`, `align_y`, `font`, `extrude`, `text_boxes_count` (font-curve subtype: a `curves` datablock with text) |
| `lights` | `name`, `type` (`POINT`/`SUN`/`SPOT`/`AREA`), `energy`, `color_r/g/b`, `use_shadow`, `use_nodes`, `diffuse_factor`, `specular_factor`, `params_json` |
| `cameras` | `name`, `type` (`PERSP`/`ORTHO`/`PANO`), `lens`, `sensor_width`, `sensor_height`, `clip_start`, `clip_end`, `ortho_scale`, `dof_focus_distance`, `fstop`, `params_json` |
| `armatures` | `name`, `users`, `bone_count` |
| `bones` | `armature`, `name`, `parent`, `use_deform`, `use_connect`, `envelope_weight`, `head_local_x/y/z`, `tail_local_x/y/z` (rest-pose / edit bones) |
| `pose_bones` | `object`, `name`, `location_x/y/z`, `rotation_quaternion_w/x/y/z`, `rotation_mode`, `scale_x/y/z`, `constraint_count` (the posed bones on an armature *object*) |
| `shape_keys` | `name`, `owner_type`, `owner_name`, `use_relative`, `reference_key`, `key_count` |
| `shape_key_blocks` | `shape_keys`, `name`, `value`, `slider_min`, `slider_max`, `mute`, `relative_key`, `vertex_group` |
| `vertex_groups` | `object`, `name`, `index`, `lock_weight` |

### Misc datablocks
| Table | Key columns |
|---|---|
| `palettes` | `name`, `users`, `color_count` |
| `palette_colors` | `palette`, `idx`, `r`, `g`, `b`, `weight`, `strength` |
| `worlds` | `name`, `users`, `use_nodes`, `color_r/g/b` |
| `brushes` | `name`, `users`, `size`, `strength`, `blend`, `image_brush_type`, `sculpt_brush_type`, `vertex_brush_type`, `weight_brush_type`, `gpencil_brush_type`, `params_json` |
| `masks` | `name`, `users`, `frame_start`, `frame_end`, `layer_count` |
| `linestyles` | `name`, `users`, `color_r/g/b`, `alpha`, `thickness`, `use_chaining`, `chaining`, `use_nodes`, `chain_count` |
| `annotations` | `name`, `users` (the separate annotation-GP container) |

### Custom properties — **writable**
| Table | RW | Key columns |
|---|---|---|
| `custom_properties` | **RW (full CRUD)** | `datablock_type`, `datablock_name`, `key`, `value_json`, `subtype`, `description`, `min`, `max`, `soft_min`, `soft_max`, `step`, `default` |

`index` / `idx` are SQL-keyword-ish — quote `"index"`. Discovery: `PRAGMA table_info(<table>);` · `SELECT name FROM sqlite_master WHERE type='table'` for the full list.

---

## Common Queries

```sql
-- External files referenced by the .blend (paths, packed?)
SELECT 'image' AS kind, name, filepath, packed FROM images WHERE filepath<>''
UNION ALL SELECT 'sound', name, filepath, packed FROM sounds WHERE filepath<>''
UNION ALL SELECT 'font',  name, filepath, packed FROM fonts WHERE filepath<>''
UNION ALL SELECT 'clip',  name, filepath, 0 FROM movieclips
ORDER BY kind, name;

-- Lights and cameras with their object hosts
SELECT o.name AS object, l.name AS light, l.type, l.energy, l.color_r, l.color_g, l.color_b
FROM lights l JOIN objects o ON o.data=l.name;
SELECT o.name AS object, c.name AS camera, c.type, c.lens, c.clip_start, c.clip_end
FROM cameras c JOIN objects o ON o.data=c.name;

-- Type-specific light/camera params (e.g. spot blend, area size, panoramic type)
SELECT name, json_extract(params_json,'$.spot_blend') AS spot_blend,
       json_extract(params_json,'$.shadow_soft_size') AS soft_size FROM lights WHERE type='SPOT';

-- Curve splines & their point counts
SELECT c.name AS curve, s."index" AS spline, s.type, s.point_count, s.use_cyclic_u
FROM curves c JOIN curve_splines s ON s.curve=c.name ORDER BY c.name, s."index";

-- Bezier curve control points
SELECT spline, "index", x, y, z, handle_left_x, handle_right_x FROM curve_points
WHERE curve='Curve' ORDER BY spline, "index";

-- Text objects and their body
SELECT name, body, size, align_x, align_y, font FROM texts;

-- Armature rest bones (hierarchy via parent)
SELECT name, parent, use_deform, use_connect FROM bones WHERE armature='Rig' ORDER BY name;

-- Posed bones on an armature object (which carry constraints)
SELECT name, constraint_count, rotation_mode FROM pose_bones WHERE object='Rig' AND constraint_count>0;

-- Shape keys on a datablock
SELECT b.name, b.value, b.slider_min, b.slider_max, b.vertex_group
FROM shape_keys k JOIN shape_key_blocks b ON b.shape_keys=k.name WHERE k.owner_name='Mesh';

-- Vertex groups on an object
SELECT "index", name, lock_weight FROM vertex_groups WHERE object='Body' ORDER BY "index";

-- Palette colors
SELECT idx, r, g, b, weight, strength FROM palette_colors WHERE palette='Inks' ORDER BY idx;

-- Worlds and their flat color
SELECT name, use_nodes, color_r, color_g, color_b FROM worlds;

-- Custom properties on a datablock (datablock_type is lowercase singular: object/mesh/material/scene/...)
SELECT key, value_json, subtype, description FROM custom_properties
WHERE datablock_type='object' AND datablock_name='Cube';
```

---

## Writing — `custom_properties` (full CRUD)

`datablock_type` is **lowercase singular** — `object`, `mesh`, `material`, `scene`, `collection`, `light`, `camera`, `armature`, `world`, `curve`, `image`, `action`, … (the reverse of the schema's container names; when in doubt, `SELECT DISTINCT datablock_type FROM custom_properties` or `bpy_eval` it).

```sql
-- Add a custom property (value_json is the value as JSON: number, string, array, …)
INSERT INTO custom_properties(datablock_type, datablock_name, key, value_json)
VALUES ('object', 'Cube', 'health', '100');
INSERT INTO custom_properties(datablock_type, datablock_name, key, value_json, description)
VALUES ('object', 'Cube', 'tags', '["hero","metal"]', 'pipeline tags');

-- Update the value (and optionally the UI metadata: min/max/soft_min/soft_max/step/default/subtype/description)
UPDATE custom_properties SET value_json='75' WHERE datablock_type='object' AND datablock_name='Cube' AND key='health';
UPDATE custom_properties SET value_json='80', min=0, max=100, soft_min=0, soft_max=100, "default"=100
WHERE datablock_type='object' AND datablock_name='Cube' AND key='health';

-- Remove a custom property
DELETE FROM custom_properties WHERE datablock_type='object' AND datablock_name='Cube' AND key='health';
```

### Everything else here

The rest of these tables are read-only. To edit them:
- Light energy/camera lens/etc.: `bpy_exec('bpy.data.lights["Lamp"].energy = 500')`, or animate via `set_keyframe('light', 'Lamp', 'energy', 10, 500)` (the `animation` skill).
- Shape-key values: `bpy_exec('bpy.data.shape_keys["Key"].key_blocks["Stretch"].value = 0.5')` — or `set_keyframe(...)` on the key block's `value` path.
- Vertex-group weights, curve point coords, bone rolls, palette colors: `bpy_exec` on the corresponding bpy collection.
- New datablocks of these types (`bpy.data.images.load(...)`, `bpy.data.curves.new(...)`, …): `bpy_exec`. New scene *objects* with a data block: the `add_object` verb (the `scene`/`modifiers` skills).

---

## Gotchas

- **`bones` vs `pose_bones`.** `bones` is the *armature data* (rest pose, edit bones, keyed by `armature` = the armature datablock name). `pose_bones` is the *armature object's* posed bones (keyed by `object`). Different things — pick the right one.
- **Data name ≠ object name** for curves/lights/cameras/armatures/texts — join on `objects.data`.
- `texts` is a *view over `curves`* (font-curve subtype) — a text object's `objects.data` points at a `curves`/`texts` row.
- `params_json` on `lights`/`cameras`/`brushes` carries the type-specific knobs — `json_extract` to read, `bpy_exec` to write (these tables aren't writable).
- `shape_keys.owner_name` is the *geometry datablock* (mesh/curve/lattice name) that owns the key, not the object.
- A datablock with `users=0` is orphaned (will be purged on save unless fake-user-flagged) — handy for cleanup audits (see the `analysis` skill).
