from __future__ import annotations

from typing import Any

import bpy

from ._meta import Column
from .base import IteratorVTable


class Collections(IteratorVTable):
    DESCRIPTION = 'Collection hierarchy: parent link, visibility, child/object counts.'
    AGENT_HINT = (
        'Walk the collection tree via parent_collection (NULL for scene-master roots). '
        'JOIN collection_objects (collection=collections.name) to expand objects, or '
        'scene_objects for the flattened recursive view per scene.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', pk=True, hint='Unique within bpy.data.collections.'),
        Column(
            'parent_collection', 'TEXT', hint='Name of parent collection; NULL for scene roots.'
        ),
        Column('hide_viewport', 'INTEGER', hint='Boolean as 0/1; viewport visibility.'),
        Column('hide_render', 'INTEGER', hint='Boolean as 0/1; render visibility.'),
        Column('child_count', 'INTEGER', hint='Number of direct child collections.'),
        Column('object_count', 'INTEGER', hint='Number of directly linked objects.'),
    )
    RELATED: tuple[str, ...] = ('collection_objects', 'scene_objects', 'objects')
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
