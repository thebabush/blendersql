---
name: materials
description: "Materials, GP material settings, and the unified node-tree model (node_trees/nodes/node_inputs/node_outputs/node_links/node_tree_interface). Use to inspect or edit shaders, recolor BSDFs, or build node graphs."
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
---

Materials plus the *uniform node-tree model* — the same `node_trees` / `nodes` / `node_inputs` / … tables describe shader trees, geometry-node trees, compositor trees, and world trees. A tree is keyed by its **owner** (`owner_type` + `owner_name`); for a material-owned shader tree the owner name is the material name, and `nodes.tree` / `node_inputs.tree` etc. use that same owner name.

---

## Tables

| Table | RW | Key columns |
|---|---|---|
| `materials` | **RW** | `name`, `users`, `use_nodes`, `is_grease_pencil`, `surface_render_method` |
| `material_slots` | R | `object`, `slot_index`, `material`, `link` (`DATA`/`OBJECT`) |
| `material_gp_settings` | **RW (UPDATE)** | `material`, `mode`, `color_r/g/b/a`, `fill_color_r/g/b/a`, `mix_color_r/g/b/a`, `stroke_style`, `fill_style`, `alignment_mode`, `alignment_rotation`, `mix_factor`, `mix_stroke_factor`, `gradient_type`, `texture_angle`, `texture_scale_x/y`, `texture_offset_x/y`, `texture_clamp`, `pass_index`, `pixel_size`, `show_stroke`, `show_fill`, `use_fill_holdout`, `use_stroke_holdout`, `use_overlap_strokes`, `flip`, `ghost`, `hide`, `lock` |
| `node_trees` | R | `name`, `bl_idname`, `type` (`SHADER`/`GEOMETRY`/`COMPOSITING`/`TEXTURE`), `owner_type`, `owner_name`, `node_count`, `link_count` |
| `nodes` | R | `tree`, `name`, `bl_idname`, `type`, `location_x/y`, `mute`, `hide`, `parent`, `label`, `width`, `height` |
| `node_inputs` | **RW (UPDATE)** | `tree`, `node`, `identifier`, `index`, `name`, `type`, `default_value_json`, `is_linked` |
| `node_outputs` | R | `tree`, `node`, `identifier`, `index`, `name`, `type`, `default_value_json`, `is_linked` |
| `node_links` | R | `tree`, `from_node`, `from_socket`, `to_node`, `to_socket`, `is_muted`, `is_valid` |
| `node_tree_interface` | R | `tree`, `identifier`, `name`, `item_type` (`SOCKET`/`PANEL`), `in_out` (`INPUT`/`OUTPUT`), `socket_type`, `parent_panel`, `description`, `index`, `default_value_json` |

`tree` everywhere = the owner name (material name for shader trees, object name for the geometry-node *modifier* tree's group, scene name for the compositor, etc.). Discovery: `SELECT sql FROM sqlite_master WHERE name='materials';` · `PRAGMA table_info(node_inputs);`

Canonical writability + one-line descriptions kept in sync by `scripts/regen_skills.py` (materials-domain subset; node_* tables live under the `nodes` domain — query `WHERE domain='nodes'` on `bsql_tables` for those):

<!-- BSQL-AUTOGEN:vtables-domain=materials -->
| name | writable | description |
|---|---|---|
| `material_gp_settings` | yes | Grease Pencil style settings on each GP material: stroke/fill colors, mix, texture, flags. |
| `material_slots` | yes | Per-object material slots: which material is bound at each slot index. |
| `materials` | yes | Material datablocks: nodes flag, GP flag, surface render method. |
<!-- /BSQL-AUTOGEN:vtables-domain=materials -->

---

## Common Queries

```sql
-- All materials, who uses them
SELECT name, users, use_nodes, is_grease_pencil, surface_render_method FROM materials ORDER BY users DESC;

-- Material slots on an object (which material in which slot)
SELECT slot_index, material, link FROM material_slots WHERE object='Cube' ORDER BY slot_index;

-- Node trees and their owners
SELECT name, type, owner_type, owner_name, node_count, link_count FROM node_trees ORDER BY type, name;

-- Nodes in a material's shader tree
SELECT name, bl_idname, type, location_x, location_y, mute FROM nodes WHERE tree='ProbeMat';

-- Inputs of the Principled BSDF in that tree, with current values
SELECT identifier, name, type, default_value_json, is_linked
FROM node_inputs WHERE tree='ProbeMat' AND node='Principled BSDF' ORDER BY "index";

-- Links inside a tree
SELECT from_node, from_socket, to_node, to_socket, is_muted FROM node_links WHERE tree='ProbeMat';

-- Geometry-node group interface (the modifier's exposed inputs/outputs)
SELECT in_out, name, socket_type, default_value_json FROM node_tree_interface
WHERE tree='ProbeGeo' ORDER BY in_out, "index";

-- Find every material that drives a given image texture
SELECT DISTINCT tree FROM nodes WHERE bl_idname='ShaderNodeTexImage';

-- GP material stroke/fill style audit
SELECT material, stroke_style, fill_style, show_stroke, show_fill,
       color_r, color_g, color_b, color_a FROM material_gp_settings ORDER BY material;
```

---

## Writing

### `materials` — `UPDATE` / `INSERT` / `DELETE`

```sql
-- Toggle node usage / render method
UPDATE materials SET use_nodes=1, surface_render_method='BLENDED' WHERE name='Glass';

-- Rename
UPDATE materials SET name='Glass.clear' WHERE name='Glass';

-- New material (created with use_nodes on by default in 5.x)
INSERT INTO materials(name) VALUES ('Emissive');
INSERT INTO materials(name, use_nodes) VALUES ('Flat', 0);

-- Delete
DELETE FROM materials WHERE name='Flat' AND users=0;
```

### `node_inputs` — `UPDATE default_value_json`

The headline edit: change a socket's default value. `default_value_json` is JSON — a scalar for a single-value socket, an array for a vector/color.

```sql
-- Recolor a Principled BSDF base color (RGBA)
UPDATE node_inputs SET default_value_json='[0.8, 0.1, 0.1, 1.0]'
WHERE tree='ProbeMat' AND node='Principled BSDF' AND identifier='Base Color';

-- Set a scalar input (Roughness, Metallic, …)
UPDATE node_inputs SET default_value_json='0.2'
WHERE tree='ProbeMat' AND node='Principled BSDF' AND name='Roughness';

-- Drive a geometry-nodes modifier input (the group's exposed value)
UPDATE node_inputs SET default_value_json='3'
WHERE tree='ProbeGeo' AND node='Group Input' AND name='Count';
```

Setting a default on a socket that is currently linked (`is_linked=1`) won't visibly change the render — unlink it first (`bpy_exec`/`bpy_op`) or edit the upstream node.

### `material_gp_settings` — `UPDATE`

```sql
-- Recolor a GP material's stroke
UPDATE material_gp_settings SET color_r=1, color_g=0, color_b=0, color_a=1
WHERE material='inkBlack';

-- Switch fill style to a gradient
UPDATE material_gp_settings SET show_fill=1, fill_style='GRADIENT', gradient_type='RADIAL',
       fill_color_r=1, fill_color_g=1, fill_color_b=0, fill_color_a=1 WHERE material='inkBlack';

-- Hide / lock a GP material
UPDATE material_gp_settings SET hide=1, lock=1 WHERE material='scratch';
```

### Verbs — build node graphs

```sql
-- Add a single node (tree owner name, node bl_idname, optional [x,y] location, optional params)
SELECT add_node('ProbeMat', 'ShaderNodeBump', '[-300, 0]');
SELECT add_node('ProbeMat', 'ShaderNodeTexNoise', '[-600, 100]', '{"noise_dimensions":"3D"}');

-- Link two sockets (by socket name or identifier; '#<index>' disambiguates duplicates)
SELECT link_nodes('ProbeMat', 'Noise Texture', 'Fac', 'Bump', 'Height');
SELECT link_nodes('ProbeMat', 'Bump', 'Normal', 'Principled BSDF', 'Normal');

-- Build a whole sub-graph in one call
SELECT build_node_tree('ProbeMat', '{
  "nodes": [
    {"name":"noise", "type":"ShaderNodeTexNoise", "location":[-600,0]},
    {"name":"ramp",  "type":"ShaderNodeValToRGB", "location":[-300,0]}
  ],
  "links": [
    {"from_node":"noise","from_socket":"Fac","to_node":"ramp","to_socket":"Fac"},
    {"from_node":"ramp","from_socket":"Color","to_node":"Principled BSDF","to_socket":"Base Color"}
  ]
}');
-- pass {"clear": true} in the spec to wipe existing nodes first.
```

Verb failures are reported *inside* the returned JSON envelope, not as a SQL error — inspect the cell.

---

## Gotchas

- **`tree` is the owner name**, not a separate tree id. For a material the owner is the material name; for a geometry-node modifier the relevant tree is the *node group* (`SELECT name FROM node_trees WHERE type='GEOMETRY'`), and `nodes.tree` uses that group name.
- A socket `name` can repeat within a node (e.g. math-node "Value"); prefer `identifier`, or use `#<index>` in `link_nodes`.
- `default_value_json` shape depends on socket type: float → `0.5`; color → `[r,g,b,a]`; vector → `[x,y,z]`; bool → `true`; int → `3`; string sockets → `"text"`.
- `material_slots` is read-only; assign materials to slots with `bpy_exec` (`obj.material_slots[i].material = bpy.data.materials['X']`) or `bpy_op('object.material_slot_add', ...)`.
- World / compositor / texture node trees use the same tables — filter `node_trees.type` and use the owner name (world name, scene name, …) as `tree`.
