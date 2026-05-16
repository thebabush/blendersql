---
name: animation
description: "The 5.1 layered Action tree (actions → slots/layers/strips/channelbags → fcurves → keyframes), animation_data, and drivers. Use to inspect or edit keyframes, fcurves, and drivers."
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
---

Blender 4.4+ replaced single-fcurve-list actions with a *layered* model. An `Action` holds **slots** (one per animated ID) and **layers**; each layer has **strips**; each strip has **channelbags** (one per slot); a channelbag holds **fcurves**; each fcurve holds **keyframes**. `animation_data` ties an ID to an action + slot. `drivers` are a separate per-ID mechanism.

```
actions
├─ action_slots         (action, identifier, name_display, target_id_type, handle, users)
├─ action_layers        (action, …)
│  └─ action_strips     (action, layer, strip_index, …)
│     └─ action_channelbags  (action, layer, strip_index, slot_handle, slot_identifier, fcurve_count, group_count)
│        └─ fcurves     (action, layer, strip_index, channelbag, fcurve_index, data_path, array_index, …)  ← WRITABLE
│           └─ keyframes (action, layer, strip_index, channelbag, fcurve_index, index, frame, value, …)    ← WRITABLE
animation_data           (owner_type, owner_id, action, action_slot, …)
drivers / driver_variables / driver_targets
```

The composite key that threads through `fcurves`/`keyframes` is `(action, layer, strip_index, channelbag, fcurve_index)` — and for a keyframe also its own `index`.

---

## Tables

| Table | RW | Key columns |
|---|---|---|
| `actions` | R | `name`, `is_action_layered`, `is_action_legacy`, `frame_start`, `frame_end`, `use_cyclic`, `use_frame_range`, `users`, `slot_count`, `layer_count` |
| `action_slots` | R | `action`, `identifier`, `name_display`, `target_id_type`, `handle`, `users` |
| `action_layers` | R | `action`, layer fields |
| `action_strips` | R | `action`, `layer`, `strip_index`, … |
| `action_channelbags` | R | `action`, `layer`, `strip_index`, `slot_handle`, `slot_identifier`, `fcurve_count`, `group_count` |
| `fcurves` | **RW (INSERT/DELETE)** | `action`, `layer`, `strip_index`, `channelbag`, `fcurve_index`, `data_path`, `array_index`, `extrapolation`, `keyframe_count`, `mute`, `hide`, `lock`, `group`, `has_driver`, `is_empty`, `is_valid` |
| `keyframes` | **RW (full CRUD)** | `action`, `layer`, `strip_index`, `channelbag`, `fcurve_index`, `index`, `frame`, `value`, `interpolation`, `easing`, `handle_left_x/y`, `handle_right_x/y`, `handle_left_type`, `handle_right_type`, `type` |
| `animation_data` | R | `owner_type`, `owner_id`, `action`, `action_slot`, `action_slot_handle`, `use_nla`, `use_pin`, `use_tweak_mode`, `action_blend_type`, `action_extrapolation`, `action_influence`, `last_slot_identifier`, `driver_count` |
| `drivers` | R | `owner_type`, `owner_id`, `data_path`, `array_index`, `type`, `expression`, `use_self`, `is_valid`, `is_simple_expression`, `mute`, `hide`, `lock`, `extrapolation`, `keyframe_count`, `variable_count` |
| `driver_variables` | R | `owner_type`, `owner_id`, `data_path`, `array_index`, `name`, `type`, `is_name_valid`, `target_count` |
| `driver_targets` | R | `owner_type`, `owner_id`, `data_path`, `array_index`, `variable`, `index`, `id_type`, `id`, `target_data_path`, `transform_type`, `transform_space`, `rotation_mode`, `bone_target` |

`index` is a SQL keyword in `keyframes` — quote it (`"index"`). Discovery: `PRAGMA table_info(keyframes);` · `SELECT sql FROM sqlite_master WHERE name='fcurves';`

Canonical writability + one-line descriptions kept in sync by `scripts/regen_skills.py`:

<!-- BSQL-AUTOGEN:vtables-domain=animation -->
| name | writable | description |
|---|---|---|
| `action_channelbags` |  | Per-strip channelbags: slot-keyed buckets of fcurves. |
| `action_layers` |  | Per-action layers: positional list that holds strips. |
| `action_slots` |  | Per-action slots: target id-type binding, identifier, handle. |
| `action_strips` |  | Per-layer strips: positional, untyped-by-name, host the channelbags. |
| `actions` |  | Action datablocks: frame range, slot/layer counts, user refcount. |
| `animation_data` |  | AnimData blocks across every datablock kind: bound action, slot, NLA state. |
| `driver_targets` |  | Driver variable targets: the actual ID + data_path / transform-source bindings. |
| `driver_variables` |  | Driver input variables: name, type, target count. |
| `drivers` |  | Property drivers on every datablock: expression, variables, remap curve. |
| `fcurves` | yes | Channelbag f-curves: per-property animation curves with keyframes. |
| `keyframes` | yes | F-curve keyframe points: (frame,value) + interpolation + bezier handles. |
<!-- /BSQL-AUTOGEN:vtables-domain=animation -->

---

## Common Queries

```sql
-- Actions overview
SELECT name, is_action_layered, frame_start, frame_end, slot_count, layer_count, users FROM actions;

-- Slots of an action (one per animated datablock)
SELECT identifier, name_display, target_id_type, handle, users FROM action_slots WHERE action='RigAction';

-- Which datablock uses which action + slot
SELECT owner_type, owner_id, action, action_slot, use_nla FROM animation_data ORDER BY owner_id;

-- Channelbags and their fcurve counts (the composite key spine)
SELECT layer, strip_index, channelbag, slot_identifier, fcurve_count FROM action_channelbags WHERE action='RigAction';

-- F-curves in an action, with keyframe counts
SELECT layer, strip_index, channelbag, fcurve_index, data_path, array_index, keyframe_count, mute, has_driver
FROM fcurves WHERE action='RigAction' ORDER BY data_path, array_index;

-- Keyframes of one fcurve (find the fcurve key first, then filter all five parts)
SELECT "index", frame, value, interpolation, easing FROM keyframes
WHERE action='RigAction' AND layer=0 AND strip_index=0 AND channelbag=0 AND fcurve_index=2 ORDER BY frame;

-- Frame range actually keyed (vs the action's declared frame_start/frame_end)
SELECT MIN(frame), MAX(frame) FROM keyframes WHERE action='RigAction';

-- Drivers on a datablock, with their variables and targets
SELECT d.data_path, d.array_index, d.expression, v.name AS var, t.transform_type, t.id AS target
FROM drivers d
JOIN driver_variables v ON v.owner_id=d.owner_id AND v.data_path=d.data_path AND v.array_index=d.array_index
JOIN driver_targets t   ON t.owner_id=d.owner_id AND t.data_path=d.data_path AND t.array_index=d.array_index AND t.variable=v.name
WHERE d.owner_id='Cube';
```

---

## Writing

### `keyframes` — full CRUD

```sql
-- Move a keyframe / change its value or interpolation
UPDATE keyframes SET frame=24, value=3.0, interpolation='BEZIER'
WHERE action='RigAction' AND layer=0 AND strip_index=0 AND channelbag=0 AND fcurve_index=2 AND "index"=1;

-- Add a keyframe to an existing fcurve (frame + value required)
INSERT INTO keyframes(action, layer, strip_index, channelbag, fcurve_index, frame, value)
VALUES ('RigAction', 0, 0, 0, 2, 48, 5.0);

-- Delete a keyframe
DELETE FROM keyframes
WHERE action='RigAction' AND layer=0 AND strip_index=0 AND channelbag=0 AND fcurve_index=2 AND "index"=3;
```

Keyframe `index` is positional within the fcurve and re-packs after insert/delete — re-read `keyframes` before the next index-keyed write.

### `fcurves` — `INSERT` / `DELETE`

```sql
-- Delete an empty/unwanted fcurve (drops all its keyframes)
DELETE FROM fcurves
WHERE action='RigAction' AND layer=0 AND strip_index=0 AND channelbag=0 AND fcurve_index=4;

-- Add a new fcurve to a channelbag (data_path + array_index)
INSERT INTO fcurves(action, layer, strip_index, channelbag, data_path, array_index)
VALUES ('RigAction', 0, 0, 0, 'location', 2);
```

### Verbs — the easy path

For new animation it's usually less fiddly to use the verbs than to assemble the composite key by hand. They auto-create the layer / strip / slot / fcurve as needed (the 4.4+ `keyframe_insert` behavior):

```sql
-- Key a property at a frame (datablock_type, datablock_name, data_path, frame, value?, ...)
-- datablock_type is lowercase singular: 'object', 'camera', 'light', 'material', 'mesh', 'armature', ...
SELECT set_keyframe('object', 'Cube', 'location', 10, '[1,2,3]');         -- whole vector
SELECT set_keyframe('object', 'Cube', 'location', 20, 4.0, 'LINEAR', 0);  -- one component (array_index 0), LINEAR
SELECT set_keyframe('camera', 'Camera', 'lens', 30, 85.0);               -- on the camera data block directly
SELECT set_keyframe('object', 'Camera', 'data.lens', 30, 85.0);          -- or via a nested data_path on the object

-- Make sure an fcurve exists for a path (creates an action if the datablock has none)
SELECT ensure_fcurve('object', 'Cube', 'rotation_euler', 2, 'MyGroup');
```

`datablock_type` is the lowercase-singular datablock kind (`object`, `camera`, `light`, `material`, `mesh`, `armature`, `scene`, `world`, …) — *not* the uppercase object-type enum. `value` may be a JSON array (whole vector) or a scalar. Verb failures land in the JSON envelope.

---

## Gotchas

- **The composite key has five parts** for fcurves (`action, layer, strip_index, channelbag, fcurve_index`) and six for a keyframe (+ `index`). Get the fcurve row first, then carry all of its parts into the keyframe query — partial filters match the wrong rows.
- Layered (`is_action_layered=1`) vs legacy (`is_action_legacy=1`) actions: layered ones have real layers/strips/channelbags; legacy ones still surface here but with `layer=0`/`strip_index=0`/`channelbag=0` placeholders.
- `set_keyframe` *sets the property* (if `value` given) **and** inserts a key — handy for posing-then-keying in one step.
- Drivers are read-only here; create/edit a driver with `bpy_exec` (`obj.driver_add('location', 0)`) or `bpy_op`. `driver_*` rows let you audit existing ones.
- NLA tracks/strips aren't modeled as tables yet — `animation_data.use_nla` flags it; use `bpy_exec` for NLA work.
