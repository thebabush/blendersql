from __future__ import annotations

from typing import Any

import bpy

from ._meta import Column
from .base import IteratorVTable

# bpy.data.curves contains both Curve and TextCurve datablocks; TextCurve is a
# subclass that adds .body/.align_x/.font/etc. The `texts` view filters by
# isinstance(..., bpy.types.TextCurve); the `curves`/`curve_splines`/
# `curve_points` tables include text curves too (text data is still spline-
# based under the hood and the splines are queryable).


class Curves(IteratorVTable):
    DESCRIPTION = 'Curve datablocks: dimensions, bevel/fill settings, spline count.'
    AGENT_HINT = (
        'Top of the curve tree (curves -> curve_splines -> curve_points). Includes TextCurve datablocks '
        'too — for text-only views use the `texts` vtable. Read-only; mutate via bpy_exec. '
        'JOIN objects ON objects.data=curves.name to find curve objects; JOIN curve_splines ON '
        'curve_splines.curve=curves.name to walk geometry.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', hint='Unique within bpy.data.curves.'),
        Column('users', 'INTEGER', hint='Refcount across the file.'),
        Column('dimensions', 'TEXT', hint="'2D' or '3D'."),
        Column('bevel_depth', 'REAL', hint='Round-bevel radius along the curve.'),
        Column('bevel_mode', 'TEXT', hint='ROUND / OBJECT / PROFILE.'),
        Column('fill_mode', 'TEXT', hint='FULL / BACK / FRONT / HALF (2D) etc.'),
        Column('spline_count', 'INTEGER', hint='len(curve.splines).'),
    )
    RELATED: tuple[str, ...] = ('curve_splines', 'curve_points', 'objects')
    schema = (
        'CREATE TABLE curves('
        'name TEXT, '
        'users INTEGER, '
        'dimensions TEXT, '
        'bevel_depth REAL, '
        'bevel_mode TEXT, '
        'fill_mode TEXT, '
        'spline_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for c in bpy.data.curves:
            rows.append(
                (
                    c.name,
                    c.users,
                    c.dimensions,
                    float(c.bevel_depth),
                    c.bevel_mode,
                    c.fill_mode,
                    len(c.splines),
                )
            )
        return rows


class CurveSplines(IteratorVTable):
    DESCRIPTION = 'Per-curve splines: type (BEZIER/POLY/NURBS), point count, U-axis settings.'
    AGENT_HINT = (
        'Tree level 2 (curves -> curve_splines -> curve_points). Read-only; key is (curve, "index"). '
        'JOIN curves ON curves.name=curve_splines.curve; JOIN curve_points ON '
        'curve_points.curve=curve_splines.curve AND curve_points.spline=curve_splines."index". '
        'point_count uses bezier_points for BEZIER, points otherwise. Quote "index".'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('curve', 'TEXT', hint='Owning curves.name.'),
        Column('index', 'INTEGER', hint='0-based spline index within the curve.'),
        Column(
            'type', 'TEXT', hint='BEZIER / POLY / NURBS — picks bezier_points vs points domain.'
        ),
        Column('point_count', 'INTEGER', hint='len(bezier_points) for BEZIER else len(points).'),
        Column('use_cyclic_u', 'INTEGER', hint='Boolean as 0/1; closed loop along U.'),
        Column('resolution_u', 'INTEGER', hint='Tessellation steps along U.'),
        Column('order_u', 'INTEGER', hint='NURBS order along U (1..6).'),
    )
    RELATED: tuple[str, ...] = ('curves', 'curve_points')
    schema = (
        'CREATE TABLE curve_splines('
        'curve TEXT, '
        '"index" INTEGER, '
        'type TEXT, '
        'point_count INTEGER, '
        'use_cyclic_u INTEGER, '
        'resolution_u INTEGER, '
        'order_u INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for c in bpy.data.curves:
            for i, s in enumerate(c.splines):
                points = s.bezier_points if s.type == 'BEZIER' else s.points
                rows.append(
                    (
                        c.name,
                        i,
                        s.type,
                        len(points),
                        int(s.use_cyclic_u),
                        int(s.resolution_u),
                        int(s.order_u),
                    )
                )
        return rows


class CurvePoints(IteratorVTable):
    # point_type discriminates: 'BEZIER' uses bezier_points (with handles),
    # 'POLY'/'NURBS' use points (4D co; weight is .co[3]). handle_left/right
    # are NULL for non-bezier rows.
    DESCRIPTION = 'Per-spline control points: position, radius/tilt, bezier handles (BEZIER only).'
    AGENT_HINT = (
        'Tree level 3 (curves -> curve_splines -> curve_points). Read-only; key is (curve, spline, "index"). '
        'handle_left_*/handle_right_* are NULL when point_type != BEZIER. JOIN curve_splines ON '
        'curve_splines.curve=curve_points.curve AND curve_splines."index"=curve_points.spline. Quote "index".'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('curve', 'TEXT', hint='Owning curves.name.'),
        Column('spline', 'INTEGER', hint='Owning curve_splines."index" within the curve.'),
        Column('index', 'INTEGER', hint='0-based point index within the spline.'),
        Column('point_type', 'TEXT', hint='BEZIER / POLY / NURBS — mirror of curve_splines.type.'),
        Column('x', 'REAL', hint='Control point X (local space).'),
        Column('y', 'REAL'),
        Column('z', 'REAL'),
        Column('radius', 'REAL', hint='Per-point bevel radius factor.'),
        Column('tilt', 'REAL', hint='Per-point twist in radians.'),
        Column('weight_softbody', 'REAL', hint='Softbody goal weight.'),
        Column('handle_left_x', 'REAL', hint='Left bezier handle X; NULL for non-BEZIER.'),
        Column('handle_left_y', 'REAL'),
        Column('handle_left_z', 'REAL'),
        Column('handle_right_x', 'REAL', hint='Right bezier handle X; NULL for non-BEZIER.'),
        Column('handle_right_y', 'REAL'),
        Column('handle_right_z', 'REAL'),
    )
    RELATED: tuple[str, ...] = ('curve_splines', 'curves')
    schema = (
        'CREATE TABLE curve_points('
        'curve TEXT, '
        'spline INTEGER, '
        '"index" INTEGER, '
        'point_type TEXT, '
        'x REAL, y REAL, z REAL, '
        'radius REAL, '
        'tilt REAL, '
        'weight_softbody REAL, '
        'handle_left_x REAL, handle_left_y REAL, handle_left_z REAL, '
        'handle_right_x REAL, handle_right_y REAL, handle_right_z REAL)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for c in bpy.data.curves:
            cname = c.name
            for si, s in enumerate(c.splines):
                stype = s.type
                if stype == 'BEZIER':
                    for pi, p in enumerate(s.bezier_points):
                        co = p.co
                        hl = p.handle_left
                        hr = p.handle_right
                        rows.append(
                            (
                                cname,
                                si,
                                pi,
                                'BEZIER',
                                float(co[0]),
                                float(co[1]),
                                float(co[2]),
                                float(p.radius),
                                float(p.tilt),
                                float(p.weight_softbody),
                                float(hl[0]),
                                float(hl[1]),
                                float(hl[2]),
                                float(hr[0]),
                                float(hr[1]),
                                float(hr[2]),
                            )
                        )
                else:
                    for pi, p in enumerate(s.points):
                        co = p.co
                        rows.append(
                            (
                                cname,
                                si,
                                pi,
                                stype,
                                float(co[0]),
                                float(co[1]),
                                float(co[2]),
                                float(p.radius),
                                float(p.tilt),
                                float(p.weight_softbody),
                                None,
                                None,
                                None,
                                None,
                                None,
                                None,
                            )
                        )
        return rows


class Texts(IteratorVTable):
    # bpy.types.TextCurve subclasses Curve; isinstance check is the canonical
    # way to spot text datablocks (hasattr('body') also works but is less
    # explicit). text_boxes_count includes the implicit first box.
    DESCRIPTION = 'TextCurve datablocks (3D text): body string, size, alignment, font.'
    AGENT_HINT = (
        'Filtered view of bpy.data.curves where the datablock is a TextCurve (3D text objects, NOT '
        'VSE text strips — those are vse_strip_text — and NOT bpy.data.texts script blocks, which '
        "this engine doesn't surface). The same datablock also shows up in curves / curve_splines / "
        'curve_points because TextCurve subclasses Curve. Read-only; mutate via bpy_exec.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', hint='Unique within bpy.data.curves (TextCurve subset).'),
        Column('users', 'INTEGER', hint='Refcount across the file.'),
        Column('body', 'TEXT', hint='The displayed text content.'),
        Column('size', 'REAL', hint='Font size in local units.'),
        Column('align_x', 'TEXT', hint='LEFT / CENTER / RIGHT / JUSTIFY / FLUSH.'),
        Column('align_y', 'TEXT', hint='TOP / TOP_BASELINE / CENTER / BOTTOM / BOTTOM_BASELINE.'),
        Column('font', 'TEXT', hint='fonts.name of the loaded VectorFont; NULL for the built-in.'),
        Column('extrude', 'REAL', hint='3D extrude depth.'),
        Column(
            'text_boxes_count', 'INTEGER', hint='len(text_boxes); includes the implicit first box.'
        ),
    )
    RELATED: tuple[str, ...] = ('curves', 'fonts', 'objects')
    schema = (
        'CREATE TABLE texts('
        'name TEXT, '
        'users INTEGER, '
        'body TEXT, '
        'size REAL, '
        'align_x TEXT, '
        'align_y TEXT, '
        'font TEXT, '
        'extrude REAL, '
        'text_boxes_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for c in bpy.data.curves:
            if not isinstance(c, bpy.types.TextCurve):
                continue
            rows.append(
                (
                    c.name,
                    int(c.users),
                    c.body,
                    float(c.size),
                    c.align_x,
                    c.align_y,
                    c.font.name if c.font is not None else None,
                    float(c.extrude),
                    len(c.text_boxes),
                )
            )
        return rows
