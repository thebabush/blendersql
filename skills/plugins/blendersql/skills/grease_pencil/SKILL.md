---
name: grease_pencil
description: "Grease Pencil v3: datablocks → layer groups → layers → frames → drawings → strokes → points. Use to inspect GP, edit layer properties, delete strokes, or build new layers/frames/strokes."
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
---

Blender 5.x Grease Pencil ("GP v3") is a curve-based system. The hierarchy:

```
grease_pencils  (the GreasePencilv3 datablock)
└─ gp_layer_groups          (nestable folders of layers)
   └─ gp_layers             (the drawing layers)        ← WRITABLE
      └─ gp_frames          (one keyframe = one drawing) ← per frame_number
         └─ gp_strokes      (curve strokes on that frame's drawing) ← DELETE
            └─ gp_points     (per-point x/y/z, radius, opacity, …)
```

Plus `gp_drawing_attributes` — the attribute layers on a drawing (always at least a built-in `position`).

A GP datablock is the *data* of an object with `objects.type='GREASEPENCIL'`; bridge with `JOIN objects o ON o.data = gp.name`.

---

## Tables

| Table | RW | Key columns |
|---|---|---|
| `grease_pencils` | R | `name`, `users`, `layer_count`, `layer_group_count`, `stroke_depth_order`, `onion_factor`, `onion_mode`, `use_onion_fade`, `use_onion_loop` |
| `gp_layer_groups` | R | `gp`, `name`, `parent_group`, `hide`, `lock` |
| `gp_layers` | **RW (UPDATE)** | `gp`, `name`, `parent_group`, `opacity`, `blend_mode`, `tint_color_r/g/b`, `tint_factor`, `hide`, `lock`, `use_lights`, `use_masks`, `use_onion_skinning`, `translation_x/y/z`, `rotation_x/y/z`, `scale_x/y/z`, `pass_index`, `frame_count` |
| `gp_frames` | R | `gp`, `layer`, `frame_number`, `keyframe_type`, `stroke_count` |
| `gp_strokes` | **RW (DELETE)** | `gp`, `layer`, `frame`, `index`, `curve_type`, `cyclic`, `material_index`, `fill_color_r/g/b/a`, `fill_opacity`, `softness`, `time_start`, `start_cap`, `end_cap`, `point_count` |
| `gp_points` | R | `gp`, `layer`, `frame`, `stroke`, `index`, `x`, `y`, `z`, `radius`, `opacity`, `rotation`, `vertex_color_r/g/b/a` |
| `gp_drawing_attributes` | R | `gp`, `layer`, `frame`, `name`, `domain`, `data_type` |

`frame` in `gp_strokes`/`gp_points`/etc. is the **frame number** (int), not a row id. Discovery: `PRAGMA table_info(gp_strokes);` · `SELECT sql FROM sqlite_master WHERE name='gp_layers';`

---

## The cheap-aggregate trick

`gp_points` is the heaviest GP table — it has one row per point. When you only need a *count or sum* of points, read the cached `point_count` on `gp_strokes` instead. `SELECT SUM(point_count) FROM gp_strokes WHERE …` is roughly **20× cheaper** than `SELECT COUNT(*) FROM gp_points WHERE …` for the same answer. Same idea for stroke counts: `SELECT SUM(stroke_count) FROM gp_frames` beats counting `gp_strokes`. Only walk `gp_points` when you need actual coordinates.

```sql
-- Cheap: total points in a layer
SELECT SUM(point_count) FROM gp_strokes WHERE gp='GPencil.002' AND layer='top.FILL';

-- Expensive (avoid unless you need the coords): same number, the slow way
SELECT COUNT(*) FROM gp_points WHERE gp='GPencil.002' AND layer='top.FILL';
```

---

## Common Queries

```sql
-- Every GP datablock, fattest first
SELECT name, layer_count, layer_group_count FROM grease_pencils ORDER BY layer_count DESC;

-- Which object hosts each GP datablock?
SELECT o.name AS object, gp.name AS gp_data, gp.layer_count
FROM grease_pencils gp JOIN objects o ON o.data = gp.name;

-- Layers of one GP, with their group and opacity
SELECT name, parent_group, opacity, blend_mode, hide, lock FROM gp_layers WHERE gp='GPencil.002';

-- Layer group tree
SELECT name, parent_group, hide, lock FROM gp_layer_groups WHERE gp='GPencil.002';

-- Frames (keyframes) on a layer
SELECT frame_number, keyframe_type, stroke_count FROM gp_frames
WHERE gp='GPencil.002' AND layer='top.FILL' ORDER BY frame_number;

-- Strokes on a specific frame
SELECT "index", curve_type, cyclic, material_index, point_count, fill_opacity
FROM gp_strokes WHERE gp='GPencil.002' AND layer='top.FILL' AND frame=1 ORDER BY "index";

-- Actual point coordinates of one stroke (only when you need geometry)
SELECT "index", x, y, z, radius, opacity FROM gp_points
WHERE gp='GPencil.002' AND layer='top.FILL' AND frame=1 AND stroke=0 ORDER BY "index";

-- Drawing attributes present on a frame
SELECT name, domain, data_type FROM gp_drawing_attributes
WHERE gp='GPencil.002' AND layer='top.FILL' AND frame=1;
```

---

## Writing

### Layer properties — `UPDATE gp_layers`

```sql
-- Dim a layer, change its blend mode
UPDATE gp_layers SET opacity=0.5, blend_mode='MULTIPLY' WHERE gp='GPencil.002' AND name='top.FILL';

-- Hide / lock
UPDATE gp_layers SET hide=1, lock=1 WHERE gp='GPencil.002' AND name='sketch';

-- Tint and per-layer transform
UPDATE gp_layers SET tint_color_r=1, tint_color_g=0, tint_color_b=0, tint_factor=0.3
WHERE gp='GPencil.002' AND name='top.FILL';
UPDATE gp_layers SET translation_x=0.1, rotation_z=0.05, scale_x=1.2
WHERE gp='GPencil.002' AND name='top.FILL';

-- Move a layer into a group / toggle onion skinning, masks, lights
UPDATE gp_layers SET parent_group='Cleanup' WHERE gp='GPencil.002' AND name='sketch';
UPDATE gp_layers SET use_onion_skinning=0, use_masks=1, use_lights=0
WHERE gp='GPencil.002' AND name='sketch';
```

### Delete strokes — `DELETE FROM gp_strokes`

```sql
-- Drop one stroke
DELETE FROM gp_strokes WHERE gp='GPencil.002' AND layer='top.FILL' AND frame=1 AND "index"=2;

-- Clear a whole frame's strokes
DELETE FROM gp_strokes WHERE gp='GPencil.002' AND layer='top.FILL' AND frame=1;
```

Stroke `index` re-packs after a delete — re-read `gp_strokes` before issuing another delete keyed by index.

### Verbs — create layers, frames, strokes

These are SQL functions returning a `{ok, result, error}` JSON envelope (the failure is *in the JSON*, not a SQL error):

```sql
-- New layer (optionally inside a layer group)
SELECT gp_add_layer('GPencil.002', 'inks');
SELECT gp_add_layer('GPencil.002', 'inks', 'Cleanup');

-- New keyframe on a layer (keyframe_type optional: KEYFRAME/BREAKDOWN/MOVING_HOLD/EXTREME/JITTER)
SELECT gp_add_frame('GPencil.002', 'inks', 10);
SELECT gp_add_frame('GPencil.002', 'inks', 10, 'BREAKDOWN');

-- New stroke on an existing frame; points_json is an array of [x,y,z] or {x,y,z,radius?,opacity?}
SELECT gp_add_stroke('GPencil.002', 'inks', 10, '[[0,0,0],[1,0,0],[1,1,0]]');
SELECT gp_add_stroke('GPencil.002', 'inks', 10,
       '[{"x":0,"y":0,"z":0,"radius":0.02},{"x":1,"y":0,"z":0,"radius":0.05}]', 0, 1);  -- material_index 0, cyclic

-- Resize strokes on a frame in bulk (sizes_json must have one entry per existing stroke)
SELECT gp_resize_strokes('GPencil.002', 'inks', 10, '[42, 17, 25]');
```

Re-fetch a stroke slice after any geometry change — old slices go stale (the verbs do this internally). To create a stroke you must first have a frame at that number (`gp_add_frame`).

---

## Gotchas

- Use `point_count` / `stroke_count` for aggregates; only touch `gp_points` for coordinates (the cheap-aggregate trick above).
- `frame` columns are **frame numbers**, not row ids — match the integer.
- `index` (stroke index, point index) is positional and shifts after deletes/inserts.
- The legacy 2.x GP stroke API is gone; there's no `add_point` — build strokes whole via `gp_add_stroke`, or for surgical point edits use `bpy_exec` on `drawing.strokes[i]`.
- GP **material** settings (stroke/fill style, colors) live on the material, not the layer — see the `materials` skill (`material_gp_settings`, writable via `UPDATE`).
- To *see* a GP drawing: `SELECT render_object('<object using this GP>')` — renders the object isolated, auto-picks its busiest keyframe, returns a PNG path you can read. (Borrows the object's scene world, so `use_lights` layers aren't black.)
