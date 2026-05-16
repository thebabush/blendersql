from __future__ import annotations

from typing import Any

import bpy

from ._meta import Column
from .base import IteratorVTable


class Welcome(IteratorVTable):
    DESCRIPTION = (
        'Single-row file summary: Blender version, filepath, active scene, datablock counts.'
    )
    AGENT_HINT = (
        'The file-summary one-liner — SELECT this FIRST to orient on an unfamiliar fixture. '
        'Always exactly one row; pairs naturally with bsql_tables for agent bootstrap. '
        'Counts here are top-level bpy.data lengths (not scene-scoped).'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('blender_version', 'TEXT', hint='bpy.app.version_string (e.g. "5.1.0").'),
        Column('filepath', 'TEXT', hint='Absolute path to the .blend; NULL if unsaved.'),
        Column('is_dirty', 'INTEGER', hint='Boolean as 0/1; unsaved changes flag.'),
        Column('active_scene', 'TEXT', hint='bpy.context.scene.name; NULL if no active scene.'),
        Column('scene_count', 'INTEGER', hint='len(bpy.data.scenes).'),
        Column('object_count', 'INTEGER', hint='len(bpy.data.objects).'),
        Column('collection_count', 'INTEGER', hint='len(bpy.data.collections).'),
        Column('material_count', 'INTEGER', hint='len(bpy.data.materials).'),
        Column('mesh_count', 'INTEGER', hint='len(bpy.data.meshes).'),
        Column('grease_pencil_count', 'INTEGER', hint='len(bpy.data.grease_pencils) (GPv3).'),
        Column('action_count', 'INTEGER', hint='len(bpy.data.actions).'),
        Column('image_count', 'INTEGER', hint='len(bpy.data.images).'),
        Column('sound_count', 'INTEGER', hint='len(bpy.data.sounds).'),
    )
    RELATED: tuple[str, ...] = ()
    schema = (
        'CREATE TABLE welcome('
        'blender_version TEXT, '
        'filepath TEXT, '
        'is_dirty INTEGER, '
        'active_scene TEXT, '
        'scene_count INTEGER, '
        'object_count INTEGER, '
        'collection_count INTEGER, '
        'material_count INTEGER, '
        'mesh_count INTEGER, '
        'grease_pencil_count INTEGER, '
        'action_count INTEGER, '
        'image_count INTEGER, '
        'sound_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        d = bpy.data
        active_scene = bpy.context.scene.name if bpy.context.scene else None
        return [
            (
                bpy.app.version_string,
                d.filepath or None,
                int(d.is_dirty),
                active_scene,
                len(d.scenes),
                len(d.objects),
                len(d.collections),
                len(d.materials),
                len(d.meshes),
                len(d.grease_pencils),
                len(d.actions),
                len(d.images),
                len(d.sounds),
            )
        ]
