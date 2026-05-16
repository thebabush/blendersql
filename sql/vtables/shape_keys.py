from __future__ import annotations

from typing import Any

import bpy

from ._meta import Column
from .base import IteratorVTable

# bpy.data.shape_keys holds the top-level Key datablocks. Each .user is the
# owning ID (Mesh / Curve / Lattice). owner_type is the class name; owner_name
# is the bare ID name (matching how `meshes`/`curves` index rows). Each block
# in .key_blocks is a named shape; .relative_key is the basis it diffs from
# when use_relative is true.


class ShapeKeys(IteratorVTable):
    DESCRIPTION = 'Shape-key datablocks (Key): owning geometry, basis, blend mode, block count.'
    AGENT_HINT = (
        'Top of the shape-keys tree (shape_keys -> shape_key_blocks). Read-only; mutate via bpy_exec. '
        'shape_keys is a SEPARATE datablock from the mesh/curve/lattice it animates — find owners via '
        "owner_type + owner_name (e.g. owner_type='Mesh' AND owner_name='Cube'). JOIN meshes ON "
        "meshes.name=shape_keys.owner_name AND shape_keys.owner_type='Mesh'; JOIN shape_key_blocks ON "
        'shape_key_blocks.shape_keys=shape_keys.name.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column(
            'name',
            'TEXT',
            identifier=True,
            hint='Unique within bpy.data.shape_keys (usually "Key", "Key.001"...).',
        ),
        Column('users', 'INTEGER', hint='Refcount; typically 1 (the owning ID).'),
        Column('owner_type', 'TEXT', hint="Owning ID class name: 'Mesh' / 'Curve' / 'Lattice'."),
        Column('owner_name', 'TEXT', hint='Bare ID name of the owner (NOT the wrapping object).'),
        Column(
            'use_relative', 'INTEGER', hint='Boolean as 0/1; relative-key blending (vs absolute).'
        ),
        Column('reference_key', 'TEXT', hint='Name of the basis key_block; NULL if none.'),
        Column('key_count', 'INTEGER', hint='len(key.key_blocks); includes the basis.'),
    )
    RELATED: tuple[str, ...] = ('shape_key_blocks', 'meshes')
    schema = (
        'CREATE TABLE shape_keys('
        'name TEXT, '
        'users INTEGER, '
        'owner_type TEXT, '
        'owner_name TEXT, '
        'use_relative INTEGER, '
        'reference_key TEXT, '
        'key_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for k in bpy.data.shape_keys:
            user = k.user
            ref = k.reference_key
            rows.append(
                (
                    k.name,
                    int(k.users),
                    type(user).__name__ if user is not None else None,
                    user.name if user is not None else None,
                    int(k.use_relative),
                    ref.name if ref is not None else None,
                    len(k.key_blocks),
                )
            )
        return rows


class ShapeKeyBlocks(IteratorVTable):
    DESCRIPTION = 'Individual shape-key blocks: per-shape value, slider range, relative-to basis.'
    AGENT_HINT = (
        'Leaf of the shape-keys tree (shape_keys -> shape_key_blocks). Read-only; mutate via bpy_exec. '
        "Key is (shape_keys, name) — the basis block is usually named 'Basis' and is the natural "
        'relative_key for others. value drives the active blend. JOIN shape_keys ON '
        'shape_keys.name=shape_key_blocks.shape_keys; vertex_group ties the shape to a vertex group '
        'by-name on the owning object (JOIN vertex_groups ON vertex_groups.name=shape_key_blocks.vertex_group).'
    )
    COLUMNS: tuple[Column, ...] = (
        Column(
            'shape_keys',
            'TEXT',
            identifier=True,
            hint='Owning shape_keys.name; part of identity.',
        ),
        Column(
            'name',
            'TEXT',
            identifier=True,
            hint='Block name; unique within the Key (e.g. "Basis", "Smile").',
        ),
        Column('value', 'REAL', hint='Active blend value, typically in [slider_min, slider_max].'),
        Column('slider_min', 'REAL', hint='UI slider minimum (defaults to 0).'),
        Column('slider_max', 'REAL', hint='UI slider maximum (defaults to 1).'),
        Column('mute', 'INTEGER', hint='Boolean as 0/1; disables this block.'),
        Column(
            'relative_key',
            'TEXT',
            hint='Name of the basis block this one diffs from; NULL if none.',
        ),
        Column(
            'vertex_group',
            'TEXT',
            hint='Vertex-group mask name on the owning object; NULL if unset.',
        ),
    )
    RELATED: tuple[str, ...] = ('shape_keys',)
    schema = (
        'CREATE TABLE shape_key_blocks('
        'shape_keys TEXT, '
        'name TEXT, '
        'value REAL, '
        'slider_min REAL, '
        'slider_max REAL, '
        'mute INTEGER, '
        'relative_key TEXT, '
        'vertex_group TEXT)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for k in bpy.data.shape_keys:
            for b in k.key_blocks:
                rk = b.relative_key
                rows.append(
                    (
                        k.name,
                        b.name,
                        float(b.value),
                        float(b.slider_min),
                        float(b.slider_max),
                        int(b.mute),
                        rk.name if rk is not None else None,
                        b.vertex_group or None,
                    )
                )
        return rows
