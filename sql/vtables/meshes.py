from __future__ import annotations

from typing import Any

import bpy

from ._meta import Column
from .base import IteratorVTable

# mesh_vertices / mesh_edges / mesh_polygons / mesh_loops / mesh_uvs materialise
# the entire mesh on every cursor open. AI_TEST.blend has one 8-vert mesh so
# this is trivial; production scenes with 100k+ vert meshes will be the first
# BestIndex pushdown candidates on `mesh = ?`. Defer until a real file hurts.


class Meshes(IteratorVTable):
    DESCRIPTION = 'Mesh datablocks: vertex/edge/polygon/loop counts, UV+material counts.'
    AGENT_HINT = (
        'Use for shape summary and refcount audits; the per-element vtables '
        '(mesh_vertices / mesh_edges / mesh_polygons / mesh_loops / mesh_uvs / '
        'mesh_attributes) materialize the full geometry on cursor open — cheap for '
        'small fixtures, future BestIndex pushdown candidate for production scenes.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', hint='Unique within bpy.data.meshes.'),
        Column('users', 'INTEGER', hint='Refcount across the file.'),
        Column('vertex_count', 'INTEGER', hint='len(mesh.vertices).'),
        Column('edge_count', 'INTEGER', hint='len(mesh.edges).'),
        Column('polygon_count', 'INTEGER', hint='len(mesh.polygons).'),
        Column('loop_count', 'INTEGER', hint='len(mesh.loops); sum of polygon corners.'),
        Column('uv_layer_count', 'INTEGER', hint='len(mesh.uv_layers).'),
        Column('material_count', 'INTEGER', hint='len(mesh.materials).'),
    )
    RELATED: tuple[str, ...] = (
        'mesh_vertices',
        'mesh_edges',
        'mesh_polygons',
        'mesh_loops',
        'mesh_uvs',
        'mesh_attributes',
        'objects',
    )
    schema = (
        'CREATE TABLE meshes('
        'name TEXT, '
        'users INTEGER, '
        'vertex_count INTEGER, '
        'edge_count INTEGER, '
        'polygon_count INTEGER, '
        'loop_count INTEGER, '
        'uv_layer_count INTEGER, '
        'material_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for m in bpy.data.meshes:
            rows.append(
                (
                    m.name,
                    m.users,
                    len(m.vertices),
                    len(m.edges),
                    len(m.polygons),
                    len(m.loops),
                    len(m.uv_layers),
                    len(m.materials),
                )
            )
        return rows


class MeshAttributes(IteratorVTable):
    # Includes built-ins (position, .edge_verts, .corner_vert, .corner_edge,
    # sharp_face, etc.) alongside any user-created attributes (UV maps,
    # vertex colors, custom data).
    DESCRIPTION = 'Per-mesh generic attributes: built-ins + user data, with domain + type.'
    AGENT_HINT = (
        'Use to enumerate custom attributes and discover where per-element data lives. '
        'Domain dictates the JOIN: POINT -> mesh_vertices(mesh,index), EDGE -> mesh_edges(mesh,"index"), '
        'CORNER -> mesh_loops(mesh,"index"), FACE -> mesh_polygons(mesh,"index"). Attribute *values* are '
        'not materialised here — query the per-domain vtable. Read-only; bpy_exec for writes.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('mesh', 'TEXT', hint='Owning mesh datablock name.'),
        Column('name', 'TEXT', hint='Attribute name (includes built-ins like position).'),
        Column(
            'domain', 'TEXT', hint='POINT / EDGE / CORNER / FACE — picks the per-element table.'
        ),
        Column(
            'data_type', 'TEXT', hint='FLOAT / INT / FLOAT_VECTOR / FLOAT_COLOR / BOOLEAN / ...'
        ),
    )
    RELATED: tuple[str, ...] = (
        'meshes',
        'mesh_vertices',
        'mesh_edges',
        'mesh_loops',
        'mesh_polygons',
    )
    schema = 'CREATE TABLE mesh_attributes(mesh TEXT, name TEXT, domain TEXT, data_type TEXT)'

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for m in bpy.data.meshes:
            for a in m.attributes:
                rows.append((m.name, a.name, a.domain, a.data_type))
        return rows


class MeshVertices(IteratorVTable):
    DESCRIPTION = 'Per-mesh vertices: position, normal, hide/select flags.'
    AGENT_HINT = (
        'Read-only; materialised on every cursor open. JOIN meshes (mesh=meshes.name) for '
        'totals, or mesh_edges/mesh_polygons via the vertex/loop indices. Mutate via '
        'bpy_exec / bmesh — SQL-level vertex writes are future work.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('mesh', 'TEXT', hint='Owning mesh datablock name.'),
        Column('index', 'INTEGER', hint='0-based vertex index within the mesh.'),
        Column('x', 'REAL', hint='Local-space coordinate.'),
        Column('y', 'REAL', hint='Local-space coordinate.'),
        Column('z', 'REAL', hint='Local-space coordinate.'),
        Column('normal_x', 'REAL'),
        Column('normal_y', 'REAL'),
        Column('normal_z', 'REAL'),
        Column('hide', 'INTEGER', hint='Boolean as 0/1; hidden in edit mode.'),
        Column('select', 'INTEGER', hint='Boolean as 0/1; selected in edit mode.'),
    )
    RELATED: tuple[str, ...] = ('meshes', 'mesh_edges', 'mesh_polygons', 'mesh_loops')
    schema = (
        'CREATE TABLE mesh_vertices('
        'mesh TEXT, '
        '"index" INTEGER, '
        'x REAL, y REAL, z REAL, '
        'normal_x REAL, normal_y REAL, normal_z REAL, '
        'hide INTEGER, '
        '"select" INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for m in bpy.data.meshes:
            name = m.name
            for i, v in enumerate(m.vertices):
                co = v.co
                n = v.normal
                rows.append(
                    (
                        name,
                        i,
                        float(co[0]),
                        float(co[1]),
                        float(co[2]),
                        float(n[0]),
                        float(n[1]),
                        float(n[2]),
                        int(v.hide),
                        int(v.select),
                    )
                )
        return rows


class MeshEdges(IteratorVTable):
    DESCRIPTION = 'Per-mesh edges: vertex pair, seam/sharp/loose flags, edit-mode visibility.'
    AGENT_HINT = (
        'Read-only; full snapshot on every cursor open. Key is (mesh, "index"). '
        'JOIN mesh_vertices ON mesh_vertices.mesh=mesh_edges.mesh AND mesh_vertices."index" IN (v1, v2) '
        'for endpoint coords; JOIN meshes (mesh=meshes.name) for totals. Quote "index" and "select" — both '
        'are SQL keywords. Mutate via bpy_exec / bmesh.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('mesh', 'TEXT', hint='Owning mesh datablock name.'),
        Column('index', 'INTEGER', hint='0-based edge index within the mesh.'),
        Column('v1', 'INTEGER', hint='First endpoint vertex index (mesh_vertices."index").'),
        Column('v2', 'INTEGER', hint='Second endpoint vertex index.'),
        Column('use_seam', 'INTEGER', hint='Boolean as 0/1; UV seam marker.'),
        Column(
            'use_edge_sharp', 'INTEGER', hint='Boolean as 0/1; sharp edge for shading/modifiers.'
        ),
        Column('is_loose', 'INTEGER', hint='Boolean as 0/1; edge belongs to no polygon.'),
        Column('hide', 'INTEGER', hint='Boolean as 0/1; hidden in edit mode.'),
        Column('select', 'INTEGER', hint='Boolean as 0/1; selected in edit mode.'),
    )
    RELATED: tuple[str, ...] = ('meshes', 'mesh_vertices', 'mesh_loops', 'mesh_polygons')
    schema = (
        'CREATE TABLE mesh_edges('
        'mesh TEXT, '
        '"index" INTEGER, '
        'v1 INTEGER, '
        'v2 INTEGER, '
        'use_seam INTEGER, '
        'use_edge_sharp INTEGER, '
        'is_loose INTEGER, '
        'hide INTEGER, '
        '"select" INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for m in bpy.data.meshes:
            name = m.name
            for i, e in enumerate(m.edges):
                vs = e.vertices
                rows.append(
                    (
                        name,
                        i,
                        int(vs[0]),
                        int(vs[1]),
                        int(e.use_seam),
                        int(e.use_edge_sharp),
                        int(e.is_loose),
                        int(e.hide),
                        int(e.select),
                    )
                )
        return rows


class MeshPolygons(IteratorVTable):
    DESCRIPTION = 'Per-mesh polygons (faces): material index, geometry, flags.'
    AGENT_HINT = (
        'Read-only; materialised on every cursor open. JOIN meshes (mesh=meshes.name) '
        'and mesh_loops (mesh,index pairs via loop_total) for full topology. '
        'Mutate via bpy_exec / bmesh — SQL writes here would need a careful design.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('mesh', 'TEXT', hint='Owning mesh datablock name.'),
        Column('index', 'INTEGER', hint='0-based polygon index within the mesh.'),
        Column('material_index', 'INTEGER', hint='Slot index into object.material_slots.'),
        Column('vertex_count', 'INTEGER', hint='Number of corners (loop_total).'),
        Column('area', 'REAL', hint='Face area in object-local units.'),
        Column('normal_x', 'REAL'),
        Column('normal_y', 'REAL'),
        Column('normal_z', 'REAL'),
        Column('center_x', 'REAL'),
        Column('center_y', 'REAL'),
        Column('center_z', 'REAL'),
        Column('use_smooth', 'INTEGER', hint='Boolean as 0/1; smooth shading.'),
        Column('hide', 'INTEGER', hint='Boolean as 0/1; hidden in edit mode.'),
        Column('select', 'INTEGER', hint='Boolean as 0/1; selected in edit mode.'),
    )
    RELATED: tuple[str, ...] = ('meshes', 'mesh_loops', 'mesh_vertices', 'mesh_edges')
    schema = (
        'CREATE TABLE mesh_polygons('
        'mesh TEXT, '
        '"index" INTEGER, '
        'material_index INTEGER, '
        'vertex_count INTEGER, '
        'area REAL, '
        'normal_x REAL, normal_y REAL, normal_z REAL, '
        'center_x REAL, center_y REAL, center_z REAL, '
        'use_smooth INTEGER, '
        'hide INTEGER, '
        '"select" INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for m in bpy.data.meshes:
            name = m.name
            for i, p in enumerate(m.polygons):
                n = p.normal
                c = p.center
                rows.append(
                    (
                        name,
                        i,
                        int(p.material_index),
                        int(p.loop_total),
                        float(p.area),
                        float(n[0]),
                        float(n[1]),
                        float(n[2]),
                        float(c[0]),
                        float(c[1]),
                        float(c[2]),
                        int(p.use_smooth),
                        int(p.hide),
                        int(p.select),
                    )
                )
        return rows


class MeshLoops(IteratorVTable):
    DESCRIPTION = 'Per-mesh polygon corners (loops): vertex/edge reference and corner normal.'
    AGENT_HINT = (
        'Loops are the polygon-corner domain; one row per face corner. Read-only; full snapshot on '
        'cursor open. JOIN mesh_polygons ON mesh_loops.mesh=mesh_polygons.mesh '
        "to walk a face's corners (mesh_polygons.vertex_count is the corner count). JOIN mesh_vertices "
        'ON mesh_vertices.mesh=mesh_loops.mesh AND mesh_vertices."index"=mesh_loops.vertex_index for '
        'positions; JOIN mesh_uvs ON mesh_uvs.mesh=mesh_loops.mesh AND mesh_uvs.loop_index=mesh_loops."index". '
        'Quote "index".'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('mesh', 'TEXT', hint='Owning mesh datablock name.'),
        Column('index', 'INTEGER', hint='0-based loop index within the mesh.'),
        Column('vertex_index', 'INTEGER', hint='mesh_vertices."index" this corner refers to.'),
        Column('edge_index', 'INTEGER', hint='mesh_edges."index" outgoing from this corner.'),
        Column('normal_x', 'REAL', hint='Per-corner (split) normal X.'),
        Column('normal_y', 'REAL'),
        Column('normal_z', 'REAL'),
    )
    RELATED: tuple[str, ...] = ('meshes', 'mesh_polygons', 'mesh_vertices', 'mesh_uvs')
    schema = (
        'CREATE TABLE mesh_loops('
        'mesh TEXT, '
        '"index" INTEGER, '
        'vertex_index INTEGER, '
        'edge_index INTEGER, '
        'normal_x REAL, normal_y REAL, normal_z REAL)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for m in bpy.data.meshes:
            name = m.name
            for i, lp in enumerate(m.loops):
                n = lp.normal
                rows.append(
                    (
                        name,
                        i,
                        int(lp.vertex_index),
                        int(lp.edge_index),
                        float(n[0]),
                        float(n[1]),
                        float(n[2]),
                    )
                )
        return rows


class MeshUvs(IteratorVTable):
    DESCRIPTION = 'Per-loop UV coordinates across every UV layer of every mesh.'
    AGENT_HINT = (
        'UVs live on the CORNER domain — one row per (mesh, layer, loop). Read-only; full snapshot on '
        'cursor open. JOIN mesh_loops ON mesh_loops.mesh=mesh_uvs.mesh AND mesh_loops."index"=mesh_uvs.loop_index '
        'to map a UV back to its vertex/edge; a mesh with no uv_layers yields zero rows. Mutate via bpy_exec.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('mesh', 'TEXT', hint='Owning mesh datablock name.'),
        Column('layer', 'TEXT', hint='UV layer name (mesh.uv_layers[*].name).'),
        Column('loop_index', 'INTEGER', hint='mesh_loops."index" this UV belongs to.'),
        Column('u', 'REAL', hint='U coordinate.'),
        Column('v', 'REAL', hint='V coordinate.'),
    )
    RELATED: tuple[str, ...] = ('meshes', 'mesh_loops')
    schema = 'CREATE TABLE mesh_uvs(mesh TEXT, layer TEXT, loop_index INTEGER, u REAL, v REAL)'

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for m in bpy.data.meshes:
            name = m.name
            for layer in m.uv_layers:
                lname = layer.name
                data = layer.data
                for i, item in enumerate(data):
                    uv = item.uv
                    rows.append((name, lname, i, float(uv[0]), float(uv[1])))
        return rows
