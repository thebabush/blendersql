from __future__ import annotations

from typing import Any

import bpy

from .base import IteratorVTable


class Collections(IteratorVTable):
    schema = (
        'CREATE TABLE collections('
        'name TEXT, '
        'parent_collection TEXT, '
        'hide_viewport INTEGER, '
        'hide_render INTEGER, '
        'child_count INTEGER, '
        'object_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        parents: dict[str, str] = {}
        for c in bpy.data.collections:
            for child in c.children:
                parents[child.name] = c.name
        rows: list[tuple[Any, ...]] = []
        for c in bpy.data.collections:
            rows.append(
                (
                    c.name,
                    parents.get(c.name),
                    int(c.hide_viewport),
                    int(c.hide_render),
                    len(c.children),
                    len(c.objects),
                )
            )
        return rows


class CollectionObjects(IteratorVTable):
    schema = 'CREATE TABLE collection_objects(collection TEXT, object TEXT)'

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for c in bpy.data.collections:
            for o in c.objects:
                rows.append((c.name, o.name))
        return rows
