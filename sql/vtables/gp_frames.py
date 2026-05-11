from __future__ import annotations

from typing import Any

import apsw
import bpy

from .base import IteratorVTable, WritableSnapshotVTable

# gp_points snapshots the full point set every query. AI_TEST.blend (~59k points)
# materialises in well under 500ms; if this becomes a hotspot, add BestIndex
# pushdown on (gp, layer) before walking strokes.


class GpFrames(IteratorVTable):
    schema = (
        'CREATE TABLE gp_frames('
        'gp TEXT, '
        'layer TEXT, '
        'frame_number INTEGER, '
        'keyframe_type TEXT, '
        'stroke_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for gp in bpy.data.grease_pencils:
            for layer in gp.layers:
                for f in layer.frames:
                    rows.append(
                        (
                            gp.name,
                            layer.name,
                            int(f.frame_number),
                            f.keyframe_type,
                            len(f.drawing.strokes),
                        )
                    )
        return rows


class GpStrokes(WritableSnapshotVTable):
    table_name = 'gp_strokes'
    # curve_type is the underlying INT8 attribute (0=CATMULL_ROM, 1=POLY, 2=BEZIER, 3=NURBS).
    # start_cap / end_cap are integer enums (0=ROUND, 1=FLAT, ...).
    schema = (
        'CREATE TABLE gp_strokes('
        'gp TEXT, '
        'layer TEXT, '
        'frame INTEGER, '
        '"index" INTEGER, '
        'curve_type INTEGER, '
        'cyclic INTEGER, '
        'material_index INTEGER, '
        'fill_color_r REAL, fill_color_g REAL, fill_color_b REAL, fill_color_a REAL, '
        'fill_opacity REAL, '
        'softness REAL, '
        'time_start REAL, '
        'start_cap INTEGER, '
        'end_cap INTEGER, '
        'point_count INTEGER)'
    )

    def _snapshot(self) -> tuple[list[tuple[Any, ...]], list[tuple[str, str, int, int]]]:
        rows: list[tuple[Any, ...]] = []
        idents: list[tuple[str, str, int, int]] = []
        for gp in bpy.data.grease_pencils:
            for layer in gp.layers:
                for f in layer.frames:
                    fn = int(f.frame_number)
                    for i, s in enumerate(f.drawing.strokes):
                        fc = s.fill_color
                        rows.append(
                            (
                                gp.name,
                                layer.name,
                                fn,
                                i,
                                int(s.curve_type),
                                int(s.cyclic),
                                int(s.material_index),
                                float(fc[0]),
                                float(fc[1]),
                                float(fc[2]),
                                float(fc[3]),
                                float(s.fill_opacity),
                                float(s.softness),
                                float(s.time_start),
                                int(s.start_cap),
                                int(s.end_cap),
                                len(s.points),
                            )
                        )
                        idents.append((gp.name, layer.name, fn, i))
        return rows, idents

    def _describe_identifier(self, identifier: Any) -> str:
        gp_name, layer_name, frame_number, stroke_index = identifier
        return f'{gp_name}/{layer_name}@{frame_number}#{stroke_index}'

    def _apply_insert(self, fields: tuple[Any, ...]) -> Any:
        raise apsw.SQLError(
            'INSERT into gp_strokes is not supported; use the gp_add_stroke verb (M2.c)'
        )

    def _apply_update(self, identifier: Any, fields: tuple[Any, ...]) -> None:
        raise apsw.SQLError('UPDATE of gp_strokes is not supported')

    def _apply_delete(self, identifier: Any) -> None:
        gp_name, layer_name, frame_number, stroke_index = identifier
        gp = bpy.data.grease_pencils.get(gp_name)
        if gp is None:
            raise apsw.SQLError(f"grease pencil '{gp_name}' no longer exists")
        layer = gp.layers.get(layer_name)
        if layer is None:
            raise apsw.SQLError(f"layer '{layer_name}' no longer exists on '{gp_name}'")
        frame = next((f for f in layer.frames if int(f.frame_number) == frame_number), None)
        if frame is None:
            raise apsw.SQLError(f"frame {frame_number} no longer exists on '{layer_name}'")
        drawing = frame.drawing
        if stroke_index < 0 or stroke_index >= len(drawing.strokes):
            raise apsw.SQLError(f'stroke index {stroke_index} out of range')
        # GP v3 (Blender 5.1): strokes are curve geometry on the drawing — there
        # is no per-stroke .remove(); the drawing-level API takes indices.
        drawing.remove_strokes(indices=[stroke_index])


class GpPoints(IteratorVTable):
    schema = (
        'CREATE TABLE gp_points('
        'gp TEXT, '
        'layer TEXT, '
        'frame INTEGER, '
        'stroke INTEGER, '
        '"index" INTEGER, '
        'x REAL, y REAL, z REAL, '
        'radius REAL, '
        'opacity REAL, '
        'rotation REAL, '
        'vertex_color_r REAL, vertex_color_g REAL, vertex_color_b REAL, vertex_color_a REAL)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for gp in bpy.data.grease_pencils:
            gp_name = gp.name
            for layer in gp.layers:
                layer_name = layer.name
                for f in layer.frames:
                    fn = int(f.frame_number)
                    for si, s in enumerate(f.drawing.strokes):
                        for pi, p in enumerate(s.points):
                            pos = p.position
                            vc = p.vertex_color
                            rows.append(
                                (
                                    gp_name,
                                    layer_name,
                                    fn,
                                    si,
                                    pi,
                                    float(pos[0]),
                                    float(pos[1]),
                                    float(pos[2]),
                                    float(p.radius),
                                    float(p.opacity),
                                    float(p.rotation),
                                    float(vc[0]),
                                    float(vc[1]),
                                    float(vc[2]),
                                    float(vc[3]),
                                )
                            )
        return rows


class GpDrawingAttributes(IteratorVTable):
    schema = (
        'CREATE TABLE gp_drawing_attributes('
        'gp TEXT, '
        'layer TEXT, '
        'frame INTEGER, '
        'name TEXT, '
        'domain TEXT, '
        'data_type TEXT)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for gp in bpy.data.grease_pencils:
            for layer in gp.layers:
                for f in layer.frames:
                    for a in f.drawing.attributes:
                        rows.append(
                            (
                                gp.name,
                                layer.name,
                                int(f.frame_number),
                                a.name,
                                a.domain,
                                a.data_type,
                            )
                        )
        return rows
