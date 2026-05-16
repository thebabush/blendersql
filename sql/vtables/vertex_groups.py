from __future__ import annotations

from typing import Any

import bpy

from ._meta import Column
from .base import IteratorVTable


class VertexGroups(IteratorVTable):
    # Vertex groups live on the OBJECT (not the mesh data), even though weights
    # are stored per-vertex on the mesh. Two objects sharing one mesh datablock
    # can have entirely different vertex-group lists.
    DESCRIPTION = 'Per-object vertex groups: name, slot index, lock flag.'
    AGENT_HINT = (
        'Object-scoped, NOT mesh-scoped — vertex_groups live on the object even when the mesh is '
        'shared. Read-only; mutate via bpy_exec. Key is (object, name). Weight values per vertex are '
        'NOT surfaced here. JOIN objects ON objects.name=vertex_groups.object; JOIN bones ON '
        'bones.name=vertex_groups.name (by-name binding into the armature).'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('object', 'TEXT', identifier=True, hint='Owning objects.name; part of identity.'),
        Column(
            'name',
            'TEXT',
            identifier=True,
            hint='Group name (often matches a bone name for armature deform).',
        ),
        Column('index', 'INTEGER', hint='Positional slot index on the object.'),
        Column(
            'lock_weight',
            'INTEGER',
            hint='Boolean as 0/1; locks weights against weight-paint edits.',
        ),
    )
    RELATED: tuple[str, ...] = ('objects', 'bones', 'meshes')
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
