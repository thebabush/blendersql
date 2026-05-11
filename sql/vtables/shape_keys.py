from __future__ import annotations

from typing import Any

import bpy

from .base import IteratorVTable

# bpy.data.shape_keys holds the top-level Key datablocks. Each .user is the
# owning ID (Mesh / Curve / Lattice). owner_type is the class name; owner_name
# is the bare ID name (matching how `meshes`/`curves` index rows). Each block
# in .key_blocks is a named shape; .relative_key is the basis it diffs from
# when use_relative is true.


class ShapeKeys(IteratorVTable):
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
