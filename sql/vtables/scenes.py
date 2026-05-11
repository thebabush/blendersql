from __future__ import annotations

from typing import Any

import bpy

from .base import IteratorVTable


class Scenes(IteratorVTable):
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
