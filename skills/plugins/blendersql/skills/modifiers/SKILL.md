---
name: modifiers
description: "Object modifiers and constraints. Use to inspect, add, edit, or delete modifiers/constraints; query type-specific fields via params_json."
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
---

The modifier stack and the constraint stack on objects (and bones). Both carry their type-specific fields as a JSON blob in `params_json` — query into it with `json_extract`, write to it by passing a JSON object.

---

## Tables

| Table | RW | Key columns |
|---|---|---|
| `modifiers` | **RW (UPDATE/DELETE)** | `object`, `name`, `type` (`SUBSURF`/`ARRAY`/`MIRROR`/`SOLIDIFY`/`NODES`/…), `show_viewport`, `show_render`, `params_json` |
| `constraints` | **RW (UPDATE/DELETE)** | `owner_type` (`OBJECT`/`BONE`), `owner_name`, `name`, `type` (`COPY_LOCATION`/`TRACK_TO`/`CHILD_OF`/`LIMIT_ROTATION`/…), `target`, `subtarget`, `influence`, `mute`, `params_json` |

`params_json` holds the fields that vary by modifier/constraint type — `{"levels": 2, "render_levels": 3}` for SUBSURF, `{"count": 5, "use_relative_offset": true}` for ARRAY, etc. Discovery: `PRAGMA table_info(modifiers);` · `SELECT object, name, type, params_json FROM modifiers WHERE object='Cube';` to see what keys a given one has.

Canonical writability + one-line descriptions kept in sync by `scripts/regen_skills.py`:

<!-- BSQL-AUTOGEN:vtables-domain=modifiers -->
| name | writable | description |
|---|---|---|
| `constraints` | yes | Object and pose-bone constraints: target binding, influence, packed params. |
| `modifiers` | yes | Per-object modifier stack with type and packed parameters. |
<!-- /BSQL-AUTOGEN:vtables-domain=modifiers -->

---

## Common Queries

```sql
-- Modifier stack on an object (order = stack order)
SELECT name, type, show_viewport, show_render FROM modifiers WHERE object='Cube';

-- Every object that has a Subsurf, with its level
SELECT object, name, json_extract(params_json,'$.levels') AS levels,
       json_extract(params_json,'$.render_levels') AS render_levels
FROM modifiers WHERE type='SUBSURF' ORDER BY object;

-- Geometry-nodes modifiers and the node group they run
SELECT object, name, json_extract(params_json,'$.node_group') AS node_group FROM modifiers WHERE type='NODES';

-- Modifier histogram across the file
SELECT type, COUNT(*) FROM modifiers GROUP BY type ORDER BY 2 DESC;

-- Constraints on an object
SELECT name, type, target, subtarget, influence, mute FROM constraints WHERE owner_name='Cube';

-- Bone constraints (owner_type='BONE'; owner_name is the pose-bone name)
SELECT owner_name, name, type, target, subtarget, influence FROM constraints WHERE owner_type='BONE' ORDER BY owner_name;

-- Constraints pointing at a given target object
SELECT owner_type, owner_name, type, influence FROM constraints WHERE target='Empty';

-- Type-specific constraint field (e.g. TRACK_TO axis)
SELECT owner_name, json_extract(params_json,'$.track_axis') AS track_axis FROM constraints WHERE type='TRACK_TO';
```

---

## Writing

### `modifiers` — `UPDATE` / `DELETE`

`params_json` is the whole knob set; assigning it applies each field in the object.

```sql
-- Bump Subsurf levels
UPDATE modifiers SET params_json='{"levels":3,"render_levels":4}' WHERE object='Cube' AND name='Subsurf';

-- Turn a modifier off in the viewport but keep it for render
UPDATE modifiers SET show_viewport=0, show_render=1 WHERE object='Cube' AND type='SUBSURF';

-- Reconfigure an Array modifier
UPDATE modifiers SET params_json='{"count":6,"use_relative_offset":true,"relative_offset_displace":[1.2,0,0]}'
WHERE object='Fence' AND type='ARRAY';

-- Rename / delete a modifier
UPDATE modifiers SET name='SubD' WHERE object='Cube' AND name='Subsurf';
DELETE FROM modifiers WHERE object='Cube' AND name='SubD';
```

You can't change a modifier's `type` by `UPDATE` — delete it and add a fresh one. You can't `INSERT` a modifier directly either — use the verb.

### `constraints` — `UPDATE` / `DELETE`

```sql
-- Dial influence, mute, retarget
UPDATE constraints SET influence=0.5 WHERE owner_name='Cube' AND name='Copy Location';
UPDATE constraints SET mute=1 WHERE owner_name='Cube' AND type='LIMIT_ROTATION';
UPDATE constraints SET target='NewTarget', subtarget='Head' WHERE owner_name='Cube' AND name='Track To';

-- Type-specific tweak
UPDATE constraints SET params_json='{"track_axis":"TRACK_NEGATIVE_Z","up_axis":"UP_Y"}'
WHERE owner_name='Cube' AND type='TRACK_TO';

-- Delete
DELETE FROM constraints WHERE owner_name='Cube' AND name='Track To';
```

### Verbs — add modifiers and constraints

```sql
-- add_modifier(object, type, params_json?)
SELECT add_modifier('Cube', 'SUBSURF', '{"levels":2,"render_levels":3}');
SELECT add_modifier('Fence', 'ARRAY', '{"count":5}');
SELECT add_modifier('Cube', 'NODES', '{"node_group":"MyGeoNodes"}');

-- add_constraint(object, type, target?, params_json?)
SELECT add_constraint('Cube', 'COPY_LOCATION', 'Empty');
SELECT add_constraint('Cube', 'TRACK_TO', 'Camera', '{"track_axis":"TRACK_NEGATIVE_Z","up_axis":"UP_Y"}');
SELECT add_constraint('Cube', 'LIMIT_ROTATION', NULL, '{"use_limit_x":true,"max_x":1.0}');
```

Verb failures (bad type, missing object/target, rejected param) come back *inside* the JSON envelope, not as a SQL error. Bone constraints aren't covered by `add_constraint` yet — use `bpy_exec` (`pose_bone.constraints.new('COPY_ROTATION')`).

---

## Gotchas

- **`params_json` is type-specific.** To know which keys a modifier/constraint accepts, read its current `params_json`, or check `bpy_eval('[p.identifier for p in bpy.data.objects["Cube"].modifiers["Subsurf"].bl_rna.properties]')`.
- Assigning `params_json` sets the listed fields *and only those*; unlisted fields keep their current value (it's not a full replace of the modifier).
- Stack order = row order in `modifiers` for an object; there's no reorder via SQL — use `bpy_op('object.modifier_move_to_index', ...)`.
- `bpy_op('object.modifier_apply', '{"modifier":"Subsurf"}', '{"active_object":"Cube"}')` to *apply* (bake) a modifier — that's an operator, not a row write.
- Constraint `subtarget` only matters when `target` is an armature (it's the bone name); for object targets leave it empty.
