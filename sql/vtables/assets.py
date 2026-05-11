from __future__ import annotations

from typing import Any

import bpy

from .base import IteratorVTable


class Images(IteratorVTable):
    schema = (
        'CREATE TABLE images('
        'name TEXT, '
        'filepath TEXT, '
        'source TEXT, '
        'width INTEGER, '
        'height INTEGER, '
        'channels INTEGER, '
        'depth INTEGER, '
        'file_format TEXT, '
        'packed INTEGER, '
        'users INTEGER, '
        'has_data INTEGER, '
        'alpha_mode TEXT, '
        'colorspace_name TEXT)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for i in bpy.data.images:
            sz = i.size
            rows.append(
                (
                    i.name,
                    i.filepath,
                    i.source,
                    int(sz[0]),
                    int(sz[1]),
                    int(i.channels),
                    int(i.depth),
                    i.file_format,
                    int(i.packed_file is not None),
                    int(i.users),
                    int(i.has_data),
                    i.alpha_mode,
                    i.colorspace_settings.name,
                )
            )
        return rows


class Sounds(IteratorVTable):
    schema = (
        'CREATE TABLE sounds('
        'name TEXT, '
        'filepath TEXT, '
        'users INTEGER, '
        'use_memory_cache INTEGER, '
        'packed INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for s in bpy.data.sounds:
            rows.append(
                (
                    s.name,
                    s.filepath,
                    int(s.users),
                    int(s.use_memory_cache),
                    int(s.packed_file is not None),
                )
            )
        return rows


class MovieClips(IteratorVTable):
    schema = (
        'CREATE TABLE movieclips('
        'name TEXT, '
        'filepath TEXT, '
        'users INTEGER, '
        'frame_duration INTEGER, '
        'fps REAL, '
        'size_x INTEGER, '
        'size_y INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for c in bpy.data.movieclips:
            sz = c.size
            rows.append(
                (
                    c.name,
                    c.filepath,
                    int(c.users),
                    int(c.frame_duration),
                    float(c.fps),
                    int(sz[0]),
                    int(sz[1]),
                )
            )
        return rows


class CacheFiles(IteratorVTable):
    schema = (
        'CREATE TABLE cache_files('
        'name TEXT, '
        'filepath TEXT, '
        'users INTEGER, '
        'frame REAL, '
        'frame_offset REAL, '
        'override_frame INTEGER, '
        'scale REAL, '
        'forward_axis TEXT, '
        'up_axis TEXT)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for c in bpy.data.cache_files:
            rows.append(
                (
                    c.name,
                    c.filepath,
                    int(c.users),
                    float(c.frame),
                    float(c.frame_offset),
                    int(c.override_frame),
                    float(c.scale),
                    c.forward_axis,
                    c.up_axis,
                )
            )
        return rows


class Fonts(IteratorVTable):
    schema = 'CREATE TABLE fonts(name TEXT, filepath TEXT, users INTEGER, packed INTEGER)'

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for f in bpy.data.fonts:
            rows.append(
                (
                    f.name,
                    f.filepath,
                    int(f.users),
                    int(f.packed_file is not None),
                )
            )
        return rows
