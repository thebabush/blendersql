from __future__ import annotations

from typing import Any

import bpy

from .base import IteratorVTable


class Welcome(IteratorVTable):
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
