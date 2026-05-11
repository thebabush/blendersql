from __future__ import annotations

from typing import Any

import bpy

from .base import IteratorVTable

# bpy.data.curves contains both Curve and TextCurve datablocks; TextCurve is a
# subclass that adds .body/.align_x/.font/etc. The `texts` view filters by
# isinstance(..., bpy.types.TextCurve); the `curves`/`curve_splines`/
# `curve_points` tables include text curves too (text data is still spline-
# based under the hood and the splines are queryable).


class Curves(IteratorVTable):
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
