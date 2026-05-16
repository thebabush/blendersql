from __future__ import annotations

from typing import Any

import apsw
import bpy

from ._meta import Column
from .base import IteratorVTable, WritableSnapshotVTable

# gp_points snapshots the full point set every query. AI_TEST.blend (~59k points)
# materialises in well under 500ms; if this becomes a hotspot, add BestIndex
# pushdown on (gp, layer) before walking strokes.


class GpFrames(IteratorVTable):
    DESCRIPTION = 'Grease Pencil per-layer frames: frame number, keyframe type, stroke count.'
    AGENT_HINT = (
        'Tree level 3 (gp_layers -> gp_frames -> gp_strokes). Read-only; mutate via bpy_exec. '
        'Key is (gp, layer, frame_number). JOIN gp_layers ON gp_layers.gp=gp_frames.gp AND '
        'gp_layers.name=gp_frames.layer; JOIN gp_strokes ON gp_strokes.gp=gp_frames.gp AND '
        'gp_strokes.layer=gp_frames.layer AND gp_strokes.frame=gp_frames.frame_number.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('gp', 'TEXT', identifier=True, hint='Owning grease_pencils.name.'),
        Column('layer', 'TEXT', identifier=True, hint='Owning gp_layers.name.'),
        Column(
            'frame_number',
            'INTEGER',
            identifier=True,
            hint='Scene frame number this drawing occupies.',
        ),
        Column(
            'keyframe_type', 'TEXT', hint='KEYFRAME / BREAKDOWN / MOVING_HOLD / EXTREME / JITTER.'
        ),
        Column('stroke_count', 'INTEGER', hint='len(frame.drawing.strokes).'),
    )
    RELATED: tuple[str, ...] = ('gp_layers', 'gp_strokes', 'gp_drawing_attributes')
    DOMAIN = 'grease_pencil'
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
    DESCRIPTION = 'Grease Pencil strokes inside a drawing: curve geometry, fill, caps, material.'
    AGENT_HINT = (
        'Tree level 4 (gp_frames -> gp_strokes -> gp_points). PK is (gp, layer, frame, index). '
        'DELETE works (drawing.remove_strokes by index); INSERT/UPDATE are blocked — use bpy_exec '
        'or the gp_add_stroke verb. JOIN gp_points ON gp_points.gp=gp_strokes.gp AND '
        'gp_points.layer=gp_strokes.layer AND gp_points.frame=gp_strokes.frame AND '
        'gp_points.stroke=gp_strokes."index"; JOIN material_slots ON material_slots.object=<obj> '
        'AND material_slots.slot_index=gp_strokes.material_index.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('gp', 'TEXT', pk=True, identifier=True, hint='Owning grease_pencils.name.'),
        Column('layer', 'TEXT', pk=True, identifier=True, hint='Owning gp_layers.name.'),
        Column('frame', 'INTEGER', pk=True, identifier=True, hint='Owning gp_frames.frame_number.'),
        Column(
            'index',
            'INTEGER',
            pk=True,
            identifier=True,
            hint='Positional index in drawing.strokes.',
        ),
        Column(
            'curve_type',
            'INTEGER',
            hint='Int8 attribute: 0=CATMULL_ROM, 1=POLY, 2=BEZIER, 3=NURBS.',
        ),
        Column('cyclic', 'INTEGER', hint='Boolean as 0/1; closed stroke.'),
        Column('material_index', 'INTEGER', hint='Slot index into the object material_slots.'),
        Column('fill_color_r', 'REAL'),
        Column('fill_color_g', 'REAL'),
        Column('fill_color_b', 'REAL'),
        Column('fill_color_a', 'REAL'),
        Column('fill_opacity', 'REAL', hint='Fill alpha multiplier in [0,1].'),
        Column('softness', 'REAL', hint='Edge softness in [0,1].'),
        Column('time_start', 'REAL', hint='Stroke playback start time.'),
        Column('start_cap', 'INTEGER', hint='Integer enum: 0=ROUND, 1=FLAT, ...'),
        Column('end_cap', 'INTEGER', hint='Integer enum: 0=ROUND, 1=FLAT, ...'),
        Column('point_count', 'INTEGER', hint='len(stroke.points).'),
    )
    RELATED: tuple[str, ...] = ('gp_frames', 'gp_points', 'gp_drawing_attributes', 'materials')
    DOMAIN = 'grease_pencil'
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
    DESCRIPTION = 'Grease Pencil per-stroke points: position, radius, opacity, vertex color.'
    AGENT_HINT = (
        'Tree leaf (gp_strokes -> gp_points). Read-only; mutate via bpy_exec. Key extends the '
        'stroke PK: (gp, layer, frame, stroke, index). JOIN gp_strokes ON gp_strokes.gp=gp_points.gp '
        'AND gp_strokes.layer=gp_points.layer AND gp_strokes.frame=gp_points.frame AND '
        'gp_strokes."index"=gp_points.stroke. Snapshots the full point set every query — fine for '
        'tens of thousands of points, push down on (gp, layer) if it grows further.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('gp', 'TEXT', identifier=True, hint='Owning grease_pencils.name.'),
        Column('layer', 'TEXT', identifier=True, hint='Owning gp_layers.name.'),
        Column('frame', 'INTEGER', identifier=True, hint='Owning gp_frames.frame_number.'),
        Column('stroke', 'INTEGER', identifier=True, hint='Owning gp_strokes."index".'),
        Column('index', 'INTEGER', identifier=True, hint='Positional index in stroke.points.'),
        Column('x', 'REAL', hint='Point position X.'),
        Column('y', 'REAL', hint='Point position Y.'),
        Column('z', 'REAL', hint='Point position Z.'),
        Column('radius', 'REAL', hint='Per-point thickness.'),
        Column('opacity', 'REAL', hint='Per-point alpha in [0,1].'),
        Column('rotation', 'REAL', hint='Per-point rotation in radians.'),
        Column('vertex_color_r', 'REAL'),
        Column('vertex_color_g', 'REAL'),
        Column('vertex_color_b', 'REAL'),
        Column('vertex_color_a', 'REAL'),
    )
    RELATED: tuple[str, ...] = ('gp_strokes',)
    DOMAIN = 'grease_pencil'
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
    DESCRIPTION = 'Generic geometry attributes on each GP drawing: domain (POINT/CURVE) + dtype.'
    AGENT_HINT = (
        'Per-drawing attribute catalog — one row per (gp, layer, frame, name). domain is POINT '
        '(per gp_point) or CURVE (per gp_stroke). Read-only metadata; values stay on the bpy '
        'attribute object. JOIN gp_frames ON gp_frames.gp=gp_drawing_attributes.gp AND '
        'gp_frames.layer=gp_drawing_attributes.layer AND gp_frames.frame_number=gp_drawing_attributes.frame.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('gp', 'TEXT', identifier=True, hint='Owning grease_pencils.name.'),
        Column('layer', 'TEXT', identifier=True, hint='Owning gp_layers.name.'),
        Column('frame', 'INTEGER', identifier=True, hint='Owning gp_frames.frame_number.'),
        Column('name', 'TEXT', identifier=True, hint='Attribute name on the drawing.'),
        Column('domain', 'TEXT', hint='POINT (per gp_point) or CURVE (per gp_stroke).'),
        Column('data_type', 'TEXT', hint='FLOAT / INT / FLOAT_VECTOR / FLOAT_COLOR / ...'),
    )
    RELATED: tuple[str, ...] = ('gp_frames', 'gp_strokes')
    DOMAIN = 'grease_pencil'
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
