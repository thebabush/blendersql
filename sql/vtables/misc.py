from __future__ import annotations

import json
from typing import Any

import bpy

from .base import IteratorVTable
from .modifiers import _dump_props


class Palettes(IteratorVTable):
    schema = 'CREATE TABLE palettes(name TEXT, users INTEGER, color_count INTEGER)'

    def snapshot(self) -> list[tuple[Any, ...]]:
        return [(p.name, int(p.users), len(p.colors)) for p in bpy.data.palettes]


class PaletteColors(IteratorVTable):
    schema = (
        'CREATE TABLE palette_colors('
        'palette TEXT, '
        'idx INTEGER, '
        'r REAL, g REAL, b REAL, '
        'weight REAL, '
        'strength REAL)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for p in bpy.data.palettes:
            for i, pc in enumerate(p.colors):
                c = pc.color
                rows.append(
                    (
                        p.name,
                        i,
                        float(c[0]),
                        float(c[1]),
                        float(c[2]),
                        float(pc.weight),
                        float(pc.strength),
                    )
                )
        return rows


class LineStyles(IteratorVTable):
    schema = (
        'CREATE TABLE linestyles('
        'name TEXT, '
        'users INTEGER, '
        'color_r REAL, color_g REAL, color_b REAL, '
        'alpha REAL, '
        'thickness REAL, '
        'use_chaining INTEGER, '
        'chaining TEXT, '
        'use_nodes INTEGER, '
        'chain_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for ls in bpy.data.linestyles:
            c = ls.color
            rows.append(
                (
                    ls.name,
                    int(ls.users),
                    float(c[0]),
                    float(c[1]),
                    float(c[2]),
                    float(ls.alpha),
                    float(ls.thickness),
                    int(ls.use_chaining),
                    ls.chaining,
                    int(ls.use_nodes),
                    int(ls.chain_count),
                )
            )
        return rows


class Worlds(IteratorVTable):
    schema = (
        'CREATE TABLE worlds('
        'name TEXT, '
        'users INTEGER, '
        'use_nodes INTEGER, '
        'color_r REAL, color_g REAL, color_b REAL)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for w in bpy.data.worlds:
            c = w.color
            rows.append(
                (
                    w.name,
                    int(w.users),
                    int(w.use_nodes),
                    float(c[0]),
                    float(c[1]),
                    float(c[2]),
                )
            )
        return rows


# 5.1 renamed `Brush.{sculpt,image,vertex,weight,gpencil}_tool` to
# `*_brush_type`. We surface the new names; tool-mode-specific extras live
# in params_json via bl_rna enumeration.
_BRUSH_COMMON: frozenset[str] = frozenset(
    {
        'rna_type',
        'name',
        'name_full',
        'id_type',
        'session_uid',
        'users',
        'use_fake_user',
        'use_extra_user',
        'is_embedded_data',
        'is_linked_packed',
        'is_missing',
        'is_runtime_data',
        'is_editable',
        'tag',
        'is_library_indirect',
        'is_evaluated',
        'original',
        'override_library',
        'library',
        'library_weak_reference',
        'asset_data',
        'preview',
        'animation_data',
        'size',
        'strength',
        'blend',
        'image_brush_type',
        'sculpt_brush_type',
        'vertex_brush_type',
        'weight_brush_type',
        'gpencil_brush_type',
    }
)


class Brushes(IteratorVTable):
    schema = (
        'CREATE TABLE brushes('
        'name TEXT, '
        'users INTEGER, '
        'size INTEGER, '
        'strength REAL, '
        'blend TEXT, '
        'image_brush_type TEXT, '
        'sculpt_brush_type TEXT, '
        'vertex_brush_type TEXT, '
        'weight_brush_type TEXT, '
        'gpencil_brush_type TEXT, '
        'params_json TEXT)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for b in bpy.data.brushes:
            rows.append(
                (
                    b.name,
                    int(b.users),
                    int(b.size),
                    float(b.strength),
                    b.blend,
                    getattr(b, 'image_brush_type', None),
                    getattr(b, 'sculpt_brush_type', None),
                    getattr(b, 'vertex_brush_type', None),
                    getattr(b, 'weight_brush_type', None),
                    getattr(b, 'gpencil_brush_type', None),
                    json.dumps(_dump_props(b, _BRUSH_COMMON), default=str),
                )
            )
        return rows


class Masks(IteratorVTable):
    schema = (
        'CREATE TABLE masks('
        'name TEXT, '
        'users INTEGER, '
        'frame_start INTEGER, '
        'frame_end INTEGER, '
        'layer_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for m in bpy.data.masks:
            rows.append(
                (
                    m.name,
                    int(m.users),
                    int(m.frame_start),
                    int(m.frame_end),
                    len(m.layers),
                )
            )
        return rows


# `bpy.data.annotations` holds legacy GP v2 datablocks (distinct from
# `bpy.data.grease_pencils` which is v3). Surfaced minimally — the v2 frames
# / strokes hierarchy is not worth schema effort in 5.1.
class Annotations(IteratorVTable):
    schema = 'CREATE TABLE annotations(name TEXT, users INTEGER)'

    def snapshot(self) -> list[tuple[Any, ...]]:
        return [(a.name, int(a.users)) for a in bpy.data.annotations]
