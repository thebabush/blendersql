from __future__ import annotations

from typing import Any

import bpy

from .base import IteratorVTable

# mesh_vertices / mesh_edges / mesh_polygons / mesh_loops / mesh_uvs materialise
# the entire mesh on every cursor open. AI_TEST.blend has one 8-vert mesh so
# this is trivial; production scenes with 100k+ vert meshes will be the first
# BestIndex pushdown candidates on `mesh = ?`. Defer until a real file hurts.


class Meshes(IteratorVTable):
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
    schema = 'CREATE TABLE mesh_attributes(mesh TEXT, name TEXT, domain TEXT, data_type TEXT)'

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for m in bpy.data.meshes:
            for a in m.attributes:
                rows.append((m.name, a.name, a.domain, a.data_type))
        return rows


class MeshVertices(IteratorVTable):
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
