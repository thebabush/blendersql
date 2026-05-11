from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import bpy

from .base import IteratorVTable

# 5.1 renamed `bpy.types.Sequence` to `bpy.types.Strip` and `sequences_all`
# to `strips_all`. We walk `strips_all` (recursive incl. metastrip children)
# so nested strips get rows; `parent_meta` is NULL for top-level. Identity
# within a scene is `(scene, name)`; names can repeat across scenes. Side
# tables key on `(scene, strip)` to mirror that.


def _iter_all_strips() -> Iterator[tuple[Any, Any]]:
    for scene in bpy.data.scenes:
        se = scene.sequence_editor
        if se is None:
            continue
        for strip in se.strips_all:
            yield scene, strip


def _parent_meta_name(strip: Any) -> str | None:
    pm = strip.parent_meta
    if callable(pm):
        pm = pm()
    return pm.name if pm is not None else None


class VseStrips(IteratorVTable):
    schema = (
        'CREATE TABLE vse_strips('
        'scene TEXT, '
        'name TEXT, '
        'type TEXT, '
        'channel INTEGER, '
        'frame_start REAL, '
        'frame_final_duration INTEGER, '
        'frame_final_end REAL, '
        'frame_offset_start REAL, '
        'frame_offset_end REAL, '
        'mute INTEGER, '
        'lock INTEGER, '
        '"select" INTEGER, '
        'blend_type TEXT, '
        'blend_alpha REAL, '
        'parent_meta TEXT)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for scene, s in _iter_all_strips():
            rows.append(
                (
                    scene.name,
                    s.name,
                    s.type,
                    int(s.channel),
                    float(s.frame_start),
                    int(s.frame_final_duration),
                    float(s.frame_final_end),
                    float(getattr(s, 'frame_offset_start', 0.0) or 0.0),
                    float(getattr(s, 'frame_offset_end', 0.0) or 0.0),
                    int(s.mute),
                    int(s.lock),
                    int(s.select),
                    getattr(s, 'blend_type', None),
                    float(getattr(s, 'blend_alpha', 1.0)),
                    _parent_meta_name(s),
                )
            )
        return rows


class VseStripSound(IteratorVTable):
    # SoundStrip in 5.1: `pitch` was renamed to `pitch_correction`.
    schema = (
        'CREATE TABLE vse_strip_sound('
        'scene TEXT, '
        'strip TEXT, '
        'sound TEXT, '
        'volume REAL, '
        'pan REAL, '
        'pitch_correction INTEGER, '
        'show_waveform INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for scene, s in _iter_all_strips():
            if s.type != 'SOUND':
                continue
            snd = s.sound
            rows.append(
                (
                    scene.name,
                    s.name,
                    snd.name if snd is not None else None,
                    float(s.volume),
                    float(s.pan),
                    int(getattr(s, 'pitch_correction', 0)),
                    int(s.show_waveform),
                )
            )
        return rows


class VseStripMovie(IteratorVTable):
    schema = (
        'CREATE TABLE vse_strip_movie('
        'scene TEXT, '
        'strip TEXT, '
        'filepath TEXT, '
        'stream_index INTEGER, '
        'fps REAL)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for scene, s in _iter_all_strips():
            if s.type != 'MOVIE':
                continue
            rows.append(
                (
                    scene.name,
                    s.name,
                    s.filepath,
                    int(s.stream_index),
                    float(s.fps),
                )
            )
        return rows


class VseStripImage(IteratorVTable):
    schema = (
        'CREATE TABLE vse_strip_image('
        'scene TEXT, '
        'strip TEXT, '
        'directory TEXT, '
        'frame_offset_start REAL, '
        'animation_offset_start INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for scene, s in _iter_all_strips():
            if s.type != 'IMAGE':
                continue
            rows.append(
                (
                    scene.name,
                    s.name,
                    s.directory,
                    float(s.frame_offset_start),
                    int(s.animation_offset_start),
                )
            )
        return rows


class VseStripScene(IteratorVTable):
    # 5.1: `camera_override` → `scene_camera`; `use_sequence` replaced by
    # `scene_input` enum ('CAMERA' / 'SEQUENCER').
    schema = (
        'CREATE TABLE vse_strip_scene('
        'scene TEXT, '
        'strip TEXT, '
        'source_scene TEXT, '
        'scene_camera TEXT, '
        'scene_input TEXT)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for scene, s in _iter_all_strips():
            if s.type != 'SCENE':
                continue
            src = s.scene
            cam = s.scene_camera
            rows.append(
                (
                    scene.name,
                    s.name,
                    src.name if src is not None else None,
                    cam.name if cam is not None else None,
                    s.scene_input,
                )
            )
        return rows


class VseStripText(IteratorVTable):
    # 5.1: TextStrip uses `anchor_x`/`anchor_y` (no `alignment_y`); `location`
    # is the 2D placement vector.
    schema = (
        'CREATE TABLE vse_strip_text('
        'scene TEXT, '
        'strip TEXT, '
        'text TEXT, '
        'font TEXT, '
        'font_size REAL, '
        'color_r REAL, color_g REAL, color_b REAL, color_a REAL, '
        'location_x REAL, location_y REAL, '
        'wrap_width REAL, '
        'alignment_x TEXT, '
        'anchor_x TEXT, '
        'anchor_y TEXT, '
        'use_shadow INTEGER, '
        'use_outline INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for scene, s in _iter_all_strips():
            if s.type != 'TEXT':
                continue
            c = s.color
            loc = s.location
            font = s.font
            rows.append(
                (
                    scene.name,
                    s.name,
                    s.text,
                    font.name if font is not None else None,
                    float(s.font_size),
                    float(c[0]),
                    float(c[1]),
                    float(c[2]),
                    float(c[3]),
                    float(loc[0]),
                    float(loc[1]),
                    float(s.wrap_width),
                    s.alignment_x,
                    s.anchor_x,
                    s.anchor_y,
                    int(s.use_shadow),
                    int(s.use_outline),
                )
            )
        return rows


class VseStripColor(IteratorVTable):
    schema = (
        'CREATE TABLE vse_strip_color('
        'scene TEXT, '
        'strip TEXT, '
        'color_r REAL, color_g REAL, color_b REAL)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for scene, s in _iter_all_strips():
            if s.type != 'COLOR':
                continue
            c = s.color
            rows.append(
                (
                    scene.name,
                    s.name,
                    float(c[0]),
                    float(c[1]),
                    float(c[2]),
                )
            )
        return rows
