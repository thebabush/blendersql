---
name: analysis
description: "Triage and audit a .blend file — orientation, most-referenced and orphaned datablocks, heaviest meshes/GP, name search, cross-file comparison. The 'where do I start' skill."
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
---

When the prompt is "what's in this file?", "is anything broken?", "what's making this slow?", or "clean it up", start here. This skill composes the others — it's mostly a recipe book.

---

## 1. Orient

```sql
-- The one-line summary
SELECT * FROM welcome;
-- blender_version, filepath, is_dirty, active_scene,
-- scene_count, object_count, collection_count, material_count,
-- mesh_count, grease_pencil_count, action_count, image_count, sound_count

-- The full surface list
SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;

-- Scenes and their frame ranges / engines
SELECT name, frame_start, frame_end, render_engine, camera, world FROM scenes;

-- Object-type breakdown
SELECT type, COUNT(*) FROM objects GROUP BY type ORDER BY 2 DESC;
```

---

## 2. Find things by name — `grep`

```sql
-- Anything matching a pattern, grouped by kind
SELECT kind, COUNT(*) FROM grep WHERE pattern LIKE 'Probe%' GROUP BY kind;

-- Just the objects
SELECT name FROM grep WHERE pattern LIKE '%rig%' AND kind='object';

-- `=` works too — both spellings claim the same constraint internally
SELECT name FROM grep WHERE pattern='Probe%';

-- Or the JSON form for a quick payload
SELECT grep('Mat%', 20, 0);
```

`grep` covers every named datablock (objects, meshes, materials, lights, cameras, curves, armatures, images, actions, collections, …). Use it to seed a deeper dive in a domain skill.

---

## 3. Reference counts — what's load-bearing, what's dead

Most datablock tables expose `users` (the bpy user count). `users = 0` ⇒ orphaned (purged on save unless fake-user-flagged).

```sql
-- Most-shared materials / meshes (high users = used in many places)
SELECT name, users FROM materials ORDER BY users DESC LIMIT 15;
SELECT name, users, polygon_count FROM meshes ORDER BY users DESC LIMIT 15;

-- Orphaned datablocks across the common types
SELECT 'mesh'     AS kind, name FROM meshes        WHERE users=0
UNION ALL SELECT 'material', name FROM materials   WHERE users=0
UNION ALL SELECT 'image',    name FROM images      WHERE users=0
UNION ALL SELECT 'action',   name FROM actions     WHERE users=0
UNION ALL SELECT 'curve',    name FROM curves      WHERE users=0
UNION ALL SELECT 'armature', name FROM armatures   WHERE users=0
UNION ALL SELECT 'light',    name FROM lights      WHERE users=0
UNION ALL SELECT 'camera',   name FROM cameras     WHERE users=0
UNION ALL SELECT 'sound',    name FROM sounds      WHERE users=0
ORDER BY kind, name;

-- Materials that exist but aren't in any slot
SELECT name FROM materials WHERE name NOT IN (SELECT DISTINCT material FROM material_slots WHERE material IS NOT NULL);

-- Meshes with no object using them
SELECT m.name FROM meshes m LEFT JOIN objects o ON o.data=m.name AND o.type='MESH' WHERE o.name IS NULL;

-- "Dead" material slots: a slot whose index no stroke on that GP datablock uses
-- (a material can be users>0 yet drawn-with by nothing, sitting in unused slots)
WITH gp_slots AS (
  SELECT ms.object, ms.slot_index, ms.material, o.data AS gp_data
  FROM material_slots ms JOIN objects o ON o.name=ms.object WHERE o.type='GREASEPENCIL'
)
SELECT object, slot_index, COALESCE(material,'(empty)') AS material FROM gp_slots gs
WHERE (SELECT COUNT(*) FROM gp_strokes st WHERE st.gp=gs.gp_data AND st.material_index=gs.slot_index) = 0
ORDER BY object, slot_index;
```

Then clean up: `SELECT purge_orphans();` removes the `users=0` datablocks, and `SELECT remove_unused_material_slots();` drops the dead slots (and remaps the geometry's `material_index`). Both report exactly what they removed and are undoable.

---

## 4. Weight / cost — what makes the file big or slow

```sql
-- Heaviest meshes (poly/loop counts)
SELECT name, vertex_count, edge_count, polygon_count, loop_count FROM meshes ORDER BY polygon_count DESC LIMIT 20;
SELECT SUM(polygon_count) AS total_polys, SUM(vertex_count) AS total_verts FROM meshes;

-- Fattest Grease Pencil datablocks (cheap: uses cached counts, not gp_points)
SELECT gp, SUM(stroke_count) AS strokes FROM gp_frames GROUP BY gp ORDER BY strokes DESC;
SELECT gp, layer, SUM(point_count) AS points FROM gp_strokes GROUP BY gp, layer ORDER BY points DESC LIMIT 20;

-- Subdivision blow-up: objects with high Subsurf levels
SELECT object, name, json_extract(params_json,'$.levels') AS lv, json_extract(params_json,'$.render_levels') AS rlv
FROM modifiers WHERE type='SUBSURF' ORDER BY rlv DESC;

-- Modifier load per object
SELECT object, COUNT(*) AS mod_count, GROUP_CONCAT(type) AS types FROM modifiers GROUP BY object ORDER BY mod_count DESC LIMIT 15;

-- Big external files referenced
SELECT name, filepath, width, height, file_format, packed FROM images WHERE filepath<>'' ORDER BY width*height DESC LIMIT 15;

-- Image textures referenced from node trees vs. orphaned images
SELECT i.name, i.users, EXISTS(SELECT 1 FROM nodes n WHERE n.bl_idname='ShaderNodeTexImage') AS used_somewhere FROM images i;
```

---

## 5. Smell tests / broken-ness

```sql
-- Objects with no data block where one is expected
SELECT name, type FROM objects WHERE type IN ('MESH','CURVE','LIGHT','CAMERA','ARMATURE') AND (data IS NULL OR data='');

-- Constraints pointing at a missing target
SELECT owner_type, owner_name, name, type, target FROM constraints
WHERE target IS NOT NULL AND target NOT IN (SELECT name FROM objects);

-- F-curves flagged invalid, or empty fcurves cluttering actions
SELECT action, data_path, array_index, is_valid, is_empty, keyframe_count FROM fcurves WHERE is_valid=0 OR is_empty=1;

-- Drivers flagged invalid
SELECT owner_type, owner_id, data_path, expression, is_valid FROM drivers WHERE is_valid=0;

-- Loose geometry
SELECT mesh, COUNT(*) AS loose_edges FROM mesh_edges WHERE is_loose=1 GROUP BY mesh HAVING loose_edges>0;

-- Datablocks the file kept around with a fake user but nothing else (audit via bpy)
SELECT bpy_eval('[m.name for m in bpy.data.meshes if m.use_fake_user and m.users==1]');

-- Recent edits this session
SELECT op, success, error_type, input FROM session_log ORDER BY ts DESC LIMIT 20;
```

---

## 6. Cross-`.blend` comparison

If you have **two** sessions open (e.g. `blendersql -s a.blend --http 8174` and `blendersql -s b.blend --http 8175`), run the same query against each and diff. Or within one session, `load()` a second file after recording the first's stats:

```sql
-- Snapshot file A
SELECT * FROM welcome;
SELECT type, COUNT(*) FROM objects GROUP BY type;
-- ... record results ...
SELECT load('/projects/shot_b.blend');
-- Snapshot file B and compare
SELECT * FROM welcome;
SELECT type, COUNT(*) FROM objects GROUP BY type;
```

(`load` discards the current in-memory state — save first if you've made edits, e.g. `SELECT save('');`.)

---

## Routing from here

Once triage points at a problem area, hand off:
- objects / hierarchy / transforms → `scene`
- grease pencil → `grease_pencil`
- mesh geometry → `mesh`
- materials / shaders / node trees → `materials`
- animation / keyframes / drivers → `animation`
- modifiers / constraints → `modifiers`
- video sequencer → `vse`
- images / sounds / curves / lights / cameras / armatures / shape keys / custom props / … → `assets`
- arbitrary edits or operators → `python`
- function signatures → `functions`

---

## Gotchas

- **`users` is the bpy user count**, not a "is it visible" flag — a mesh with `users=1` linked to one object is normal; `users=0` is the orphan signal. `use_fake_user` (probe via `bpy_eval`) keeps a 0-real-user block alive.
- Use the **cheap GP aggregates** (`gp_frames.stroke_count`, `gp_strokes.point_count`) for counts — don't `COUNT(*) FROM gp_points` on a real file.
- Constrain `mesh_*` tables by `mesh` — an unbounded scan of `mesh_loops`/`mesh_uvs` will dominate the query.
- "Is anything broken" beyond what's modeled (NLA, libraries/linked data, override hierarchies): probe with `bpy_eval`/`bpy_exec` — `bpy.data.libraries`, `obj.override_library`, etc.
- Cross-file comparison via `load()` is destructive to the in-memory session — save (`SELECT save('')`) before switching, or use two `--http` servers.
