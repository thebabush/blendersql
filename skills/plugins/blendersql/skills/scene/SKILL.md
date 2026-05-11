---
name: scene
description: "Scenes, collections, objects, the parent/child hierarchy, transforms. Use to inspect or edit objects — move/rotate/scale/parent/rename, add EMPTYs, delete objects."
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
---

The scene graph: `scenes` → `collections` → `collection_objects` → `objects`, with `objects.parent` giving the transform-parent hierarchy.

---

## Tables

| Table | RW | Key columns |
|---|---|---|
| `scenes` | R | `name`, `frame_current`, `frame_start`, `frame_end`, `fps`, `fps_base`, `render_engine`, `camera`, `world`, `use_nodes`, `resolution_x`, `resolution_y`, `view_layer_count`, `sequence_strip_count` |
| `collections` | R | `name`, `parent_collection`, `hide_viewport`, `hide_render`, `child_count`, `object_count` |
| `collection_objects` | R | `collection`, `object` (membership view; an object can be in several collections) |
| `objects` | **RW** | `name`, `type`, `parent`, `data`, `collection`, `hide_viewport`, `hide_render`, `rotation_mode`, `location_x/y/z`, `rotation_x/y/z`, `scale_x/y/z` |

`object_children` isn't a base table — the parent/child hierarchy lives in `objects.parent` (a self-join). `welcome.active_scene` names the active scene.

Discovery: `PRAGMA table_info(objects);` · `SELECT sql FROM sqlite_master WHERE name='scenes';` · `SELECT * FROM welcome;`

---

## Common Queries

```sql
-- Active scene + frame range
SELECT name, frame_current, frame_start, frame_end, render_engine, camera FROM scenes;

-- Objects with their type, data block, and transform-parent
SELECT name, type, data, parent FROM objects ORDER BY type, name;

-- Direct children of a parent object
SELECT name, type FROM objects WHERE parent = 'Rig';

-- The whole parent chain for one object (recursive)
WITH RECURSIVE chain(name, parent, depth) AS (
  SELECT name, parent, 0 FROM objects WHERE name = 'Hand.L'
  UNION ALL
  SELECT o.name, o.parent, c.depth+1 FROM objects o JOIN chain c ON o.name = c.parent
)
SELECT depth, name FROM chain ORDER BY depth DESC;

-- Collection membership (which collections is each camera in?)
SELECT object, collection FROM collection_objects
WHERE object IN (SELECT name FROM objects WHERE type='CAMERA') ORDER BY object;

-- Objects sitting at the origin
SELECT name, type FROM objects WHERE location_x=0 AND location_y=0 AND location_z=0;

-- Hidden objects
SELECT name FROM objects WHERE hide_viewport=1 OR hide_render=1;

-- Bridge object → mesh data
SELECT o.name AS object, m.name AS mesh, m.polygon_count
FROM objects o JOIN meshes m ON m.name = o.data WHERE o.type='MESH';
```

---

## Writing `objects`

`objects` is fully writable: `UPDATE`, `INSERT` (EMPTY only for now), `DELETE`. All writes are wrapped in `bpy.ops.ed.undo_push`, so Ctrl+Z in the GUI reverts them.

```sql
-- Move / rotate / scale (radians for rotation_*)
UPDATE objects SET location_x=5, location_y=0, location_z=2 WHERE name='Cube';
UPDATE objects SET scale_x=2, scale_y=2, scale_z=2 WHERE name='Cube';
UPDATE objects SET rotation_z=1.5708 WHERE name='Cube';   -- 90° about Z

-- Hide in viewport and render
UPDATE objects SET hide_viewport=1, hide_render=1 WHERE name LIKE 'debug_%';

-- Re-parent (NULL clears the parent); switch rotation mode
UPDATE objects SET parent='Rig' WHERE name='Hand.L';
UPDATE objects SET parent=NULL WHERE name='Hand.L';
UPDATE objects SET rotation_mode='QUATERNION' WHERE name='Cube';

-- Rename (must be a non-empty string; Blender may suffix on collision)
UPDATE objects SET name='Hero' WHERE name='Cube';

-- Add an empty (type EMPTY only; data must be NULL; lands in the active scene collection)
INSERT INTO objects(name, type) VALUES ('Pivot', 'EMPTY');
INSERT INTO objects(name, type, location_x, location_y, location_z) VALUES ('Pivot', 'EMPTY', 0, 0, 5);

-- Delete (unlinks from all collections; the object's data block is NOT deleted — see Gotchas)
DELETE FROM objects WHERE name='Pivot';
```

Read-only-on-`UPDATE`: `type`, `data`, `collection` — changing these raises a SQL error. To create an object **with** a data block (mesh/curve/light/…), use the `add_object(type, name, location_json, collection)` verb (see the `modifiers`/`functions` skills) or `bpy_exec` (see `python`):

```sql
SELECT add_object('MESH', 'NewCube', '[1,2,3]');                       -- lands in the active scene collection
SELECT add_object('MESH', 'NewCube', '[1,2,3]', 'Scene Collection');   -- or name a target collection (must exist)
```

---

## Eyeballing an object

`SELECT render_object('Bmw X5')` renders just that object — isolated, auto-framed, in a throwaway scene that **never touches the live scene/camera/frame/config** — to a PNG you can read back ("what is this thing?" before editing it). `render_object(object, frame?, filepath?, size?)`; for a Grease Pencil object it auto-picks the keyframe with the most strokes when `frame` is omitted. Default output is `<tmpdir>/blendersql_render_<object>.png`; pass `filepath` to override.

---

## Gotchas

- **Object name vs data name.** `objects.name` is the object; `objects.data` is the linked data block's name. Don't `JOIN meshes m ON m.name = o.name` — use `o.data`.
- **`collection_objects` is many-to-many** — an object may appear in multiple rows. Use `DISTINCT` when you only want object names.
- Rotation values are **radians**; `rotation_mode` decides whether `rotation_x/y/z` are Euler or (for QUATERNION/AXIS_ANGLE) ignored — those modes need `bpy_exec` to set the quaternion components.
- Re-parenting via `UPDATE objects SET parent=...` keeps the object's world transform offset; if you need "keep transform" or "clear inverse" semantics, use `bpy_op('object.parent_set', ...)`.
- **`DELETE FROM objects` doesn't cascade to the object's data block.** Deleting a mesh/curve/etc. object (or one created by `add_object('MESH',…)` / `bpy_op('mesh.primitive_*_add',…)`) leaves the mesh/curve datablock behind as a 0-user orphan until "Purge Orphans" or a file reload — standard Blender behavior. To also free the data: `SELECT bpy_exec('m = bpy.data.meshes.get("OldMesh");\nif m and m.users == 0: bpy.data.meshes.remove(m)')` after the delete, or `SELECT bpy_op('outliner.orphans_purge', '{}')` to sweep all orphans.
- Collections themselves aren't writable here; create/relink collections with `bpy_op('collection.create', ...)` / `bpy_exec`.
