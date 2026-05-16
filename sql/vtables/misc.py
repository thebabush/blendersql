from __future__ import annotations

import json
from typing import Any

import bpy

from ._meta import Column
from .base import IteratorVTable
from .modifiers import _dump_props


class Palettes(IteratorVTable):
    DESCRIPTION = 'Palette datablocks: name, refcount, color count.'
    AGENT_HINT = (
        'Read-only catalog of bpy.data.palettes (named color swatches used by paint/sculpt/'
        'GP tools). One palette holds N colors — JOIN palette_colors ON '
        'palette_colors.palette=palettes.name to drill in. Mutate via bpy_exec.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', hint='Unique within bpy.data.palettes.'),
        Column('users', 'INTEGER', hint='Refcount across the file.'),
        Column('color_count', 'INTEGER', hint='len(palette.colors).'),
    )
    RELATED: tuple[str, ...] = ('palette_colors',)
    schema = 'CREATE TABLE palettes(name TEXT, users INTEGER, color_count INTEGER)'

    def snapshot(self) -> list[tuple[Any, ...]]:
        return [(p.name, int(p.users), len(p.colors)) for p in bpy.data.palettes]


class PaletteColors(IteratorVTable):
    DESCRIPTION = 'Per-palette color entries: RGB plus weight/strength for paint tools.'
    AGENT_HINT = (
        'Read-only; key is (palette, idx). idx is the 0-based position within the palette '
        'and is meaningful — order is preserved and surfaces in the palette UI. JOIN palettes '
        'ON palettes.name=palette_colors.palette. weight/strength apply to weight-paint and '
        'GP tools respectively. Mutate via bpy_exec.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('palette', 'TEXT', hint='Owning palettes.name; part of identity.'),
        Column('idx', 'INTEGER', hint='0-based index within the palette (order matters).'),
        Column('r', 'REAL', hint='Color red channel (0..1).'),
        Column('g', 'REAL'),
        Column('b', 'REAL'),
        Column('weight', 'REAL', hint='Weight-paint strength multiplier (0..1).'),
        Column('strength', 'REAL', hint='GP draw strength multiplier (0..1).'),
    )
    RELATED: tuple[str, ...] = ('palettes',)
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
    DESCRIPTION = 'FreestyleLineStyle datablocks: base color, thickness, chaining, node usage.'
    AGENT_HINT = (
        'Read-only catalog of bpy.data.linestyles (Freestyle NPR stroke styles). Linestyles '
        'are wired into scenes via per-view-layer Freestyle linesets — there is no flat '
        '`linestyle` column on scenes/view_layers; the relationship lives in scene.view_layers'
        '[*].freestyle_settings.linesets (not exposed in SQL today, mutate via bpy_exec). When '
        'use_nodes=1 the stroke shader lives in node_trees (owner_type=linestyle).'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', hint='Unique within bpy.data.linestyles.'),
        Column('users', 'INTEGER', hint='Refcount across the file.'),
        Column('color_r', 'REAL', hint='Base stroke color red channel.'),
        Column('color_g', 'REAL'),
        Column('color_b', 'REAL'),
        Column('alpha', 'REAL', hint='Base stroke alpha.'),
        Column('thickness', 'REAL', hint='Base stroke thickness in px.'),
        Column('use_chaining', 'INTEGER', hint='Boolean as 0/1; chain strokes together.'),
        Column('chaining', 'TEXT', hint='PLAIN / SKETCHY — chaining algorithm.'),
        Column('use_nodes', 'INTEGER', hint='Boolean as 0/1; surface a node_trees row.'),
        Column('chain_count', 'INTEGER', hint='Number of strokes to chain (sketchy mode).'),
    )
    RELATED: tuple[str, ...] = ('scenes', 'node_trees')
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
    DESCRIPTION = 'World datablocks: nodes flag and base color (background).'
    AGENT_HINT = (
        'Read-only — mutate via bpy_exec. JOIN scenes ON scenes.world=worlds.name to find the '
        'scene-bound world. When use_nodes=1 the actual sky color lives in the node tree '
        "(JOIN node_trees ON node_trees.owner_type='world' AND node_trees.owner_name=worlds.name)."
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', hint='Unique within bpy.data.worlds.'),
        Column('users', 'INTEGER', hint='Refcount across the file.'),
        Column('use_nodes', 'INTEGER', hint='Boolean as 0/1; toggles shader node tree.'),
        Column('color_r', 'REAL'),
        Column('color_g', 'REAL'),
        Column('color_b', 'REAL'),
    )
    RELATED: tuple[str, ...] = ('scenes', 'node_trees')
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
    DESCRIPTION = 'Brush datablocks: per-mode tool type, size/strength, blend mode, params blob.'
    AGENT_HINT = (
        "Read-only catalog of bpy.data.brushes — factory brushes (Blender's bundled ones, "
        'users=0 unless picked) plus any custom brushes the file added. A fresh file already '
        'has dozens of factory rows, so always filter (e.g. WHERE users>0, or by '
        '*_brush_type IS NOT NULL for the mode you care about). Each *_brush_type column is '
        "NULL when the brush isn't usable in that mode. params_json is a JSON blob of "
        'mode-specific extras not promoted to top-level columns. Mutate via bpy_exec.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', hint='Unique within bpy.data.brushes.'),
        Column(
            'users',
            'INTEGER',
            hint='Refcount; factory brushes often sit at 0 until selected as the active tool.',
        ),
        Column('size', 'INTEGER', hint='Brush radius in px.'),
        Column('strength', 'REAL', hint='Effect strength multiplier (0..1).'),
        Column('blend', 'TEXT', hint='Brush blend mode (MIX / ADD / SUB / ...).'),
        Column(
            'image_brush_type',
            'TEXT',
            hint='Texture-paint tool id when applicable; NULL otherwise.',
        ),
        Column('sculpt_brush_type', 'TEXT', hint='Sculpt tool id when applicable; NULL otherwise.'),
        Column(
            'vertex_brush_type',
            'TEXT',
            hint='Vertex-paint tool id when applicable; NULL otherwise.',
        ),
        Column(
            'weight_brush_type',
            'TEXT',
            hint='Weight-paint tool id when applicable; NULL otherwise.',
        ),
        Column(
            'gpencil_brush_type', 'TEXT', hint='GP draw tool id when applicable; NULL otherwise.'
        ),
        Column('params_json', 'TEXT', hint='JSON dump of mode-specific properties.'),
    )
    RELATED: tuple[str, ...] = ()
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
    DESCRIPTION = 'Mask datablocks: 2D bezier masks with playback range and layer count.'
    AGENT_HINT = (
        'Read-only catalog of bpy.data.masks (2D vector masks used in compositing, VSE, and '
        'tracking). VSE mask strips reference these (vse_strip_mask is not surfaced today; '
        'JOIN vse_strip_movie / vse_strip_image only by side reference). The mask layers / '
        'splines / points hierarchy is not surfaced here — mutate via bpy_exec.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', hint='Unique within bpy.data.masks.'),
        Column('users', 'INTEGER', hint='Refcount across the file.'),
        Column('frame_start', 'INTEGER', hint='Playback range start frame.'),
        Column('frame_end', 'INTEGER', hint='Playback range end frame.'),
        Column('layer_count', 'INTEGER', hint='len(mask.layers).'),
    )
    RELATED: tuple[str, ...] = ('vse_strip_movie', 'vse_strip_image')
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
