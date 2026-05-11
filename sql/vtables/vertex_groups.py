from __future__ import annotations

from typing import Any

import bpy

from .base import IteratorVTable


class VertexGroups(IteratorVTable):
    schema = (
        'CREATE TABLE vertex_groups(object TEXT, name TEXT, "index" INTEGER, lock_weight INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for o in bpy.data.objects:
            for vg in o.vertex_groups:
                rows.append(
                    (
                        o.name,
                        vg.name,
                        int(vg.index),
                        int(vg.lock_weight),
                    )
                )
        return rows
