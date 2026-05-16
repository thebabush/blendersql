from __future__ import annotations

from typing import Any

import bpy

from ._meta import Column
from .base import IteratorVTable


class Scenes(IteratorVTable):
    DESCRIPTION = 'Scene datablocks: frame range, fps, render engine, camera/world bindings.'
    AGENT_HINT = (
        'Read-only here; use bpy_exec to mutate scene state. JOIN scene_objects '
        '(scene=scenes.name) to enumerate the flattened object set per scene.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', pk=True, hint='Unique within bpy.data.scenes.'),
        Column('frame_current', 'INTEGER', hint='Current playhead frame.'),
        Column('frame_start', 'INTEGER', hint='Playback range start.'),
        Column('frame_end', 'INTEGER', hint='Playback range end.'),
        Column('fps', 'INTEGER', hint='Render fps numerator.'),
        Column('fps_base', 'REAL', hint='Render fps denominator (effective fps = fps/fps_base).'),
        Column('render_engine', 'TEXT', hint='BLENDER_EEVEE_NEXT / CYCLES / WORKBENCH / ...'),
        Column('camera', 'TEXT', hint='Active scene camera object name; NULL if unset.'),
        Column('world', 'TEXT', hint='Bound world datablock name; NULL if unset.'),
        Column('use_nodes', 'INTEGER', hint='Boolean as 0/1; legacy compositor flag.'),
        Column('resolution_x', 'INTEGER', hint='Render width in pixels.'),
        Column('resolution_y', 'INTEGER', hint='Render height in pixels.'),
        Column('view_layer_count', 'INTEGER', hint='Number of view layers.'),
        Column('sequence_strip_count', 'INTEGER', hint='Total VSE strips across all channels.'),
    )
    RELATED: tuple[str, ...] = ('scene_objects', 'collections', 'vse_strips')
    schema = (
        'CREATE TABLE scenes('
        'name TEXT, '
        'frame_current INTEGER, '
        'frame_start INTEGER, '
        'frame_end INTEGER, '
        'fps INTEGER, '
        'fps_base REAL, '
        'render_engine TEXT, '
        'camera TEXT, '
        'world TEXT, '
        'use_nodes INTEGER, '
        'resolution_x INTEGER, '
        'resolution_y INTEGER, '
        'view_layer_count INTEGER, '
        'sequence_strip_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for s in bpy.data.scenes:
            seq = s.sequence_editor
            rows.append(
                (
                    s.name,
                    s.frame_current,
                    s.frame_start,
                    s.frame_end,
                    s.render.fps,
                    s.render.fps_base,
                    s.render.engine,
                    s.camera.name if s.camera else None,
                    s.world.name if s.world else None,
                    int(s.use_nodes),
                    s.render.resolution_x,
                    s.render.resolution_y,
                    len(s.view_layers),
                    len(seq.strips_all) if seq else 0,
                )
            )
        return rows


class SceneObjects(IteratorVTable):
    """Flattened scene -> all linked objects (recursive across nested collections).

    Uses `scene.collection.all_objects` which already recursively walks the
    scene's master collection and its child collections. An object linked
    into multiple scenes appears once per scene.
    """

    DESCRIPTION = 'Recursively flattened per-scene object list (walks nested collections).'
    AGENT_HINT = (
        'Use this — not scenes.objects-style joins — when you need every object reachable '
        'from a scene including those nested inside child collections; `collection.all_objects` '
        'is the recursion. An object linked into multiple scenes appears once per scene. '
        'Contrast with collection_objects which is the direct (non-recursive) collection<->object link.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('scene', 'TEXT', hint='Owning scenes.name.'),
        Column('object', 'TEXT', hint='objects.name reachable from this scene (any depth).'),
        Column(
            'type', 'TEXT', hint='Object type (MESH / EMPTY / LIGHT / ...); mirrors objects.type.'
        ),
        Column('hide_viewport', 'INTEGER', hint='Boolean as 0/1; object-level viewport hide.'),
        Column('hide_render', 'INTEGER', hint='Boolean as 0/1; object-level render hide.'),
    )
    RELATED: tuple[str, ...] = ('scenes', 'objects', 'collections', 'collection_objects')
    schema = (
        'CREATE TABLE scene_objects('
        'scene TEXT, '
        'object TEXT, '
        'type TEXT, '
        'hide_viewport INTEGER, '
        'hide_render INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for s in bpy.data.scenes:
            for o in s.collection.all_objects:
                rows.append(
                    (
                        s.name,
                        o.name,
                        o.type,
                        int(o.hide_viewport),
                        int(o.hide_render),
                    )
                )
        return rows
