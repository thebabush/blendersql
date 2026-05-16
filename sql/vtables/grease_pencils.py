from __future__ import annotations

from typing import Any

import apsw
import bpy

from ._meta import Column
from .base import IteratorVTable, WritableSnapshotVTable


class GreasePencils(IteratorVTable):
    DESCRIPTION = 'Grease Pencil v3 datablocks: layer counts, onion-skin settings, depth order.'
    AGENT_HINT = (
        'Top of the GP v3 tree: grease_pencils -> gp_layer_groups + gp_layers -> gp_frames -> '
        'gp_strokes -> gp_points (+ gp_drawing_attributes). Read-only; mutate via bpy_exec. '
        'JOIN gp_layers ON gp_layers.gp=grease_pencils.name; material_slots binds to the gp '
        "datablock just like meshes (objects.data is the gp name when objects.type='GPENCIL')."
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', identifier=True, hint='Unique within bpy.data.grease_pencils.'),
        Column('users', 'INTEGER', hint='Refcount across the file.'),
        Column('layer_count', 'INTEGER', hint='len(gp.layers).'),
        Column('layer_group_count', 'INTEGER', hint='len(gp.layer_groups).'),
        Column('stroke_depth_order', 'TEXT', hint='2D / 3D — viewport draw ordering.'),
        Column('onion_factor', 'REAL', hint='Onion-skin opacity factor in [0,1].'),
        Column('onion_mode', 'TEXT', hint='ABSOLUTE / RELATIVE / SELECTED.'),
        Column('use_onion_fade', 'INTEGER', hint='Boolean as 0/1; fade onion skins by distance.'),
        Column('use_onion_loop', 'INTEGER', hint='Boolean as 0/1; loop onion skins past ends.'),
    )
    RELATED: tuple[str, ...] = ('gp_layers', 'gp_layer_groups', 'material_slots')
    schema = (
        'CREATE TABLE grease_pencils('
        'name TEXT, '
        'users INTEGER, '
        'layer_count INTEGER, '
        'layer_group_count INTEGER, '
        'stroke_depth_order TEXT, '
        'onion_factor REAL, '
        'onion_mode TEXT, '
        'use_onion_fade INTEGER, '
        'use_onion_loop INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for gp in bpy.data.grease_pencils:
            rows.append(
                (
                    gp.name,
                    gp.users,
                    len(gp.layers),
                    len(gp.layer_groups),
                    gp.stroke_depth_order,
                    float(gp.onion_factor),
                    gp.onion_mode,
                    int(gp.use_onion_fade),
                    int(gp.use_onion_loop),
                )
            )
        return rows


class GpLayerGroups(IteratorVTable):
    DESCRIPTION = 'Grease Pencil layer groups: nestable folders that hold gp_layers.'
    AGENT_HINT = (
        'Read-only sibling of gp_layers; groups are pure organisation (hide/lock cascade to '
        'their layers). JOIN grease_pencils ON grease_pencils.name=gp_layer_groups.gp; '
        'JOIN gp_layers ON gp_layers.gp=gp_layer_groups.gp AND gp_layers.parent_group=gp_layer_groups.name. '
        'parent_group is recursive (a group can sit inside another).'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('gp', 'TEXT', identifier=True, hint='Owning grease_pencils.name.'),
        Column('name', 'TEXT', identifier=True, hint='Group name; unique within the gp datablock.'),
        Column('parent_group', 'TEXT', hint='Enclosing group name; NULL for top-level.'),
        Column('hide', 'INTEGER', hint='Boolean as 0/1; cascades to child layers in the viewport.'),
        Column('lock', 'INTEGER', hint='Boolean as 0/1; cascades to child layers for editing.'),
    )
    RELATED: tuple[str, ...] = ('grease_pencils', 'gp_layers')
    schema = (
        'CREATE TABLE gp_layer_groups('
        'gp TEXT, '
        'name TEXT, '
        'parent_group TEXT, '
        'hide INTEGER, '
        'lock INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for gp in bpy.data.grease_pencils:
            for g in gp.layer_groups:
                parent = g.parent_group
                rows.append(
                    (
                        gp.name,
                        g.name,
                        parent.name if parent is not None else None,
                        int(g.hide),
                        int(g.lock),
                    )
                )
        return rows


_GP_LAYER_COLUMNS: tuple[str, ...] = (
    'gp',
    'name',
    'parent_group',
    'opacity',
    'blend_mode',
    'tint_color_r',
    'tint_color_g',
    'tint_color_b',
    'tint_factor',
    'hide',
    'lock',
    'use_lights',
    'use_masks',
    'use_onion_skinning',
    'translation_x',
    'translation_y',
    'translation_z',
    'rotation_x',
    'rotation_y',
    'rotation_z',
    'scale_x',
    'scale_y',
    'scale_z',
    'pass_index',
    'frame_count',
)
_GPL_COL_INDEX: dict[str, int] = {name: i for i, name in enumerate(_GP_LAYER_COLUMNS)}

_GPL_BOOL_COLS: tuple[str, ...] = (
    'hide',
    'lock',
    'use_lights',
    'use_masks',
    'use_onion_skinning',
)
_GPL_SCALAR_COLS: tuple[tuple[str, str], ...] = (
    ('opacity', 'opacity'),
    ('tint_factor', 'tint_factor'),
)


class GpLayers(WritableSnapshotVTable):
    table_name = 'gp_layers'
    # tint_color is RGB (3 floats) in GP v3 — no alpha column.
    DESCRIPTION = 'Grease Pencil layers: per-layer transform, tint, opacity, masking flags.'
    AGENT_HINT = (
        'Tree level 2 (grease_pencils -> gp_layers -> gp_frames). PK is (gp, name). UPDATE '
        'tweaks tint/transform/flags and can rename or reparent into a layer group; INSERT/DELETE '
        'are blocked (use bpy_exec or the gp_add_layer verb). JOIN gp_frames ON '
        'gp_frames.gp=gp_layers.gp AND gp_frames.layer=gp_layers.name; JOIN gp_layer_groups '
        'ON gp_layer_groups.gp=gp_layers.gp AND gp_layer_groups.name=gp_layers.parent_group.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column(
            'gp',
            'TEXT',
            pk=True,
            identifier=True,
            hint='Owning grease_pencils.name; part of identifier.',
        ),
        Column(
            'name',
            'TEXT',
            writable=True,
            pk=True,
            identifier=True,
            hint='Layer name; part of identifier.',
        ),
        Column(
            'parent_group',
            'TEXT',
            writable=True,
            hint='Enclosing gp_layer_groups.name; NULL for top-level.',
        ),
        Column('opacity', 'REAL', writable=True, hint='Layer opacity in [0,1].'),
        Column('blend_mode', 'TEXT', writable=True, hint='REGULAR / HARDLIGHT / ADD / ...'),
        Column('tint_color_r', 'REAL', writable=True, hint='RGB tint, no alpha in GP v3.'),
        Column('tint_color_g', 'REAL', writable=True),
        Column('tint_color_b', 'REAL', writable=True),
        Column('tint_factor', 'REAL', writable=True, hint='Tint blend factor in [0,1].'),
        Column('hide', 'INTEGER', writable=True, hint='Boolean as 0/1; viewport visibility.'),
        Column('lock', 'INTEGER', writable=True, hint='Boolean as 0/1.'),
        Column('use_lights', 'INTEGER', writable=True, hint='Boolean as 0/1.'),
        Column('use_masks', 'INTEGER', writable=True, hint='Boolean as 0/1.'),
        Column('use_onion_skinning', 'INTEGER', writable=True, hint='Boolean as 0/1.'),
        Column('translation_x', 'REAL', writable=True),
        Column('translation_y', 'REAL', writable=True),
        Column('translation_z', 'REAL', writable=True),
        Column('rotation_x', 'REAL', writable=True, hint='Euler radians.'),
        Column('rotation_y', 'REAL', writable=True),
        Column('rotation_z', 'REAL', writable=True),
        Column('scale_x', 'REAL', writable=True),
        Column('scale_y', 'REAL', writable=True),
        Column('scale_z', 'REAL', writable=True),
        Column('pass_index', 'INTEGER', writable=True, hint='Render pass index for compositing.'),
        Column('frame_count', 'INTEGER', hint='len(layer.frames); read-only.'),
    )
    RELATED: tuple[str, ...] = ('grease_pencils', 'gp_layer_groups', 'gp_frames')
    schema = (
        'CREATE TABLE gp_layers('
        'gp TEXT, '
        'name TEXT, '
        'parent_group TEXT, '
        'opacity REAL, '
        'blend_mode TEXT, '
        'tint_color_r REAL, tint_color_g REAL, tint_color_b REAL, '
        'tint_factor REAL, '
        'hide INTEGER, '
        'lock INTEGER, '
        'use_lights INTEGER, '
        'use_masks INTEGER, '
        'use_onion_skinning INTEGER, '
        'translation_x REAL, translation_y REAL, translation_z REAL, '
        'rotation_x REAL, rotation_y REAL, rotation_z REAL, '
        'scale_x REAL, scale_y REAL, scale_z REAL, '
        'pass_index INTEGER, '
        'frame_count INTEGER)'
    )

    def _snapshot(self) -> tuple[list[tuple[Any, ...]], list[tuple[str, str]]]:
        rows: list[tuple[Any, ...]] = []
        idents: list[tuple[str, str]] = []
        for gp in bpy.data.grease_pencils:
            for layer in gp.layers:
                rows.append(_layer_row(gp, layer))
                idents.append((gp.name, layer.name))
        return rows, idents

    def _describe_identifier(self, identifier: Any) -> str:
        gp_name, layer_name = identifier
        return f'{gp_name}/{layer_name}'

    def _apply_insert(self, fields: tuple[Any, ...]) -> Any:
        raise apsw.SQLError(
            'INSERT into gp_layers is not supported; use the gp_add_layer verb (M2.c)'
        )

    def _apply_delete(self, identifier: Any) -> None:
        raise apsw.SQLError(
            'DELETE from gp_layers is not supported; use bpy_exec to remove a layer'
        )

    def _apply_update(self, identifier: Any, fields: tuple[Any, ...]) -> None:
        gp_name, layer_name = identifier
        gp = bpy.data.grease_pencils.get(gp_name)
        if gp is None:
            raise apsw.SQLError(f"grease pencil '{gp_name}' no longer exists")
        layer = gp.layers.get(layer_name)
        if layer is None:
            raise apsw.SQLError(f"layer '{layer_name}' no longer exists on '{gp_name}'")
        current = _layer_row(gp, layer)

        if fields[_GPL_COL_INDEX['frame_count']] != current[_GPL_COL_INDEX['frame_count']]:
            raise apsw.SQLError("column 'frame_count' is read-only on UPDATE")

        def changed(col: str) -> bool:
            return fields[_GPL_COL_INDEX[col]] != current[_GPL_COL_INDEX[col]]

        try:
            for col, attr in _GPL_SCALAR_COLS:
                if changed(col):
                    setattr(layer, attr, float(fields[_GPL_COL_INDEX[col]]))
            if changed('pass_index'):
                layer.pass_index = int(fields[_GPL_COL_INDEX['pass_index']])
            for col in _GPL_BOOL_COLS:
                if changed(col):
                    setattr(layer, col, bool(fields[_GPL_COL_INDEX[col]]))
            if changed('blend_mode'):
                _set_enum(layer, 'blend_mode', fields[_GPL_COL_INDEX['blend_mode']])

            for axis, col in enumerate(('tint_color_r', 'tint_color_g', 'tint_color_b')):
                if changed(col):
                    layer.tint_color[axis] = float(fields[_GPL_COL_INDEX[col]])
            for axis, col in enumerate(('translation_x', 'translation_y', 'translation_z')):
                if changed(col):
                    layer.translation[axis] = float(fields[_GPL_COL_INDEX[col]])
            for axis, col in enumerate(('rotation_x', 'rotation_y', 'rotation_z')):
                if changed(col):
                    layer.rotation[axis] = float(fields[_GPL_COL_INDEX[col]])
            for axis, col in enumerate(('scale_x', 'scale_y', 'scale_z')):
                if changed(col):
                    layer.scale[axis] = float(fields[_GPL_COL_INDEX[col]])
        except (ValueError, TypeError) as exc:
            raise apsw.SQLError(str(exc)) from exc

        if changed('parent_group'):
            new_pg = fields[_GPL_COL_INDEX['parent_group']]
            if new_pg is None:
                layer.parent_group = None
            else:
                group = gp.layer_groups.get(new_pg)
                if group is None:
                    raise apsw.SQLError(f"layer group '{new_pg}' not found on '{gp_name}'")
                layer.parent_group = group

        if changed('name'):
            new_name = fields[_GPL_COL_INDEX['name']]
            if not isinstance(new_name, str) or not new_name:
                raise apsw.SQLError('name must be a non-empty string')
            layer.name = new_name


def _set_enum(obj: Any, attr: str, value: Any) -> None:
    if not isinstance(value, str):
        raise apsw.SQLError(f'{attr} must be a string')
    allowed = {item.identifier for item in obj.bl_rna.properties[attr].enum_items}
    if value not in allowed:
        raise apsw.SQLError(f"invalid {attr} '{value}' (allowed: {sorted(allowed)})")
    setattr(obj, attr, value)


def _layer_row(gp: Any, layer: Any) -> tuple[Any, ...]:
    parent = layer.parent_group
    tc = layer.tint_color
    tr = layer.translation
    rt = layer.rotation
    sc = layer.scale
    return (
        gp.name,
        layer.name,
        parent.name if parent is not None else None,
        float(layer.opacity),
        layer.blend_mode,
        float(tc[0]),
        float(tc[1]),
        float(tc[2]),
        float(layer.tint_factor),
        int(layer.hide),
        int(layer.lock),
        int(layer.use_lights),
        int(layer.use_masks),
        int(layer.use_onion_skinning),
        float(tr[0]),
        float(tr[1]),
        float(tr[2]),
        float(rt[0]),
        float(rt[1]),
        float(rt[2]),
        float(sc[0]),
        float(sc[1]),
        float(sc[2]),
        int(layer.pass_index),
        len(layer.frames),
    )
