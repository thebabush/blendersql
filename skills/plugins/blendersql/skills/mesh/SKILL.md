---
name: mesh
description: "Meshes and their geometry — the 5.x attribute system, vertices/edges/polygons/loops/uvs. Use to inspect mesh topology or attributes. Mostly read; these are the heaviest tables on big files."
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
---

Mesh data and its geometry tables. A mesh is the *data* of an object with `objects.type='MESH'` — bridge via `JOIN objects o ON o.data = m.name`.

---

## Tables

| Table | Key columns |
|---|---|
| `meshes` | `name`, `users`, `vertex_count`, `edge_count`, `polygon_count`, `loop_count`, `uv_layer_count`, `material_count` |
| `mesh_attributes` | `mesh`, `name`, `domain` (`POINT`/`EDGE`/`FACE`/`CORNER`), `data_type` (`FLOAT`/`FLOAT_VECTOR`/`INT`/`BOOLEAN`/…) |
| `mesh_vertices` | `mesh`, `index`, `x`, `y`, `z`, `normal_x/y/z`, `hide`, `select` |
| `mesh_edges` | `mesh`, `index`, `v1`, `v2`, `use_seam`, `use_edge_sharp`, `is_loose`, `hide`, `select` |
| `mesh_polygons` | `mesh`, `index`, `material_index`, `vertex_count`, `area`, `normal_x/y/z`, `center_x/y/z`, `use_smooth`, `hide`, `select` |
| `mesh_loops` | `mesh`, `index`, `vertex_index`, `edge_index`, `normal_x/y/z` |
| `mesh_uvs` | `mesh`, `layer`, `loop_index`, `u`, `v` |

All read-only. `select` and `index` are SQL keywords — **quote them** (`"select"`, `"index"`). Discovery: `PRAGMA table_info(mesh_vertices);`

> **Performance.** `mesh_vertices`, `mesh_edges`, `mesh_polygons`, `mesh_loops`, `mesh_uvs` are the heaviest tables in the schema — one row per element. Always constrain by `mesh = '<name>'` (and ideally a further filter). Never run an unbounded `SELECT * FROM mesh_loops` on a real scene.

---

## Common Queries

```sql
-- Mesh sizes, biggest first
SELECT name, vertex_count, edge_count, polygon_count, loop_count, uv_layer_count
FROM meshes ORDER BY polygon_count DESC LIMIT 20;

-- Which object uses each mesh? (a mesh with users>1 is shared)
SELECT o.name AS object, m.name AS mesh, m.users, m.polygon_count
FROM meshes m JOIN objects o ON o.data = m.name WHERE o.type='MESH' ORDER BY m.users DESC;

-- Attribute layers on a mesh (custom data: color attrs, vertex weights baked as attrs, etc.)
SELECT name, domain, data_type FROM mesh_attributes WHERE mesh='Suzanne' ORDER BY domain, name;

-- Vertices of a small mesh
SELECT "index", x, y, z FROM mesh_vertices WHERE mesh='Cube' ORDER BY "index";

-- Bounding box of a mesh (cheap-ish: scans its verts only)
SELECT MIN(x), MAX(x), MIN(y), MAX(y), MIN(z), MAX(z) FROM mesh_vertices WHERE mesh='Cube';

-- Edges marked as seams (for UV unwrapping audits)
SELECT "index", v1, v2 FROM mesh_edges WHERE mesh='Suzanne' AND use_seam=1;

-- Faces by material slot
SELECT material_index, COUNT(*) AS faces, ROUND(SUM(area),3) AS total_area
FROM mesh_polygons WHERE mesh='Suzanne' GROUP BY material_index;

-- Non-manifold-ish smell test: loose edges
SELECT COUNT(*) FROM mesh_edges WHERE mesh='Suzanne' AND is_loose=1;

-- UVs of a layer (loop-indexed)
SELECT loop_index, u, v FROM mesh_uvs WHERE mesh='Cube' AND layer='UVMap' ORDER BY loop_index;

-- Loop → vertex/edge mapping for one face's corners
SELECT l."index" AS loop, l.vertex_index, l.edge_index
FROM mesh_loops l WHERE l.mesh='Cube' ORDER BY l."index" LIMIT 8;
```

---

## Editing meshes

These tables are **read-only** — there's no `UPDATE mesh_vertices`. To edit geometry:

- **Object-level** (transform, hide, etc.): see the `scene` skill (`UPDATE objects …`).
- **Generative geometry**: add a modifier — `add_modifier('Suzanne', 'SUBSURF', '{"levels":2}')` or `bpy_op('mesh.primitive_uv_sphere_add', ...)` — see the `modifiers` skill.
- **Direct vertex/poly edits, attribute writes, bmesh ops**: use `bpy_exec` (the `python` skill), e.g.

  ```sql
  SELECT bpy_exec('m = bpy.data.meshes["Cube"]; m.vertices[0].co.z += 1.0; m.update()');
  ```

  Edit-mode geometry needs `bmesh`; from a headless/CLI session you typically stay in object mode and edit `mesh.vertices` / `mesh.attributes` directly, then `mesh.update()`.

---

## Gotchas

- **Constrain by `mesh`** on every geometry table — these are the slowest queries you can write here.
- Mesh name ≠ object name; join on `objects.data`.
- `mesh_uvs.loop_index` is into the *loop* list, not the vertex list — a vertex shared by N faces has N loops, hence N UVs.
- `mesh_polygons.vertex_count` is the face's corner count (3 = tri, 4 = quad, >4 = ngon).
- Custom color attributes / vertex groups baked as attributes show up in `mesh_attributes` but their *values* aren't exposed as a table — read them with `bpy_exec` (`m.attributes['Col'].data[i].color`) or via `mesh_uvs`-style for the well-known ones.
