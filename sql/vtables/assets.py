from __future__ import annotations

from typing import Any

import bpy

from ._meta import Column
from .base import IteratorVTable


class Images(IteratorVTable):
    DESCRIPTION = 'Image datablocks: filepath, source, dimensions, packed state.'
    AGENT_HINT = (
        'Read-only catalog of bpy.data.images (referenced from materials, world settings, '
        'shader/compositor image nodes, brushes, and VSE image strips — there is no direct '
        'objects-side join). filepath is the on-disk path; when packed=1 the pixel data lives '
        'inside the .blend (filepath is just a hint). source distinguishes FILE / MOVIE / '
        'SEQUENCE / GENERATED / TILED / VIEWER. Render Result appears as a session-order side '
        "effect after the first render — don't assert exact row counts. Mutate via bpy_exec."
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', hint='Unique within bpy.data.images.'),
        Column('filepath', 'TEXT', hint='On-disk path; advisory when packed=1.'),
        Column('source', 'TEXT', hint='FILE / MOVIE / SEQUENCE / GENERATED / TILED / VIEWER.'),
        Column('width', 'INTEGER', hint='size[0]; 0 when has_data=0.'),
        Column('height', 'INTEGER', hint='size[1]; 0 when has_data=0.'),
        Column('channels', 'INTEGER', hint='1 / 3 / 4 (e.g. BW / RGB / RGBA).'),
        Column('depth', 'INTEGER', hint='Bits per pixel total across channels.'),
        Column('file_format', 'TEXT', hint='PNG / JPEG / OPEN_EXR / ...'),
        Column('packed', 'INTEGER', hint='Boolean as 0/1; pixel data stored inside the .blend.'),
        Column('users', 'INTEGER', hint='Refcount across the file.'),
        Column('has_data', 'INTEGER', hint='Boolean as 0/1; pixels are loaded.'),
        Column('alpha_mode', 'TEXT', hint='STRAIGHT / PREMUL / CHANNEL_PACKED / NONE.'),
        Column(
            'colorspace_name', 'TEXT', hint='colorspace_settings.name (sRGB / Non-Color / ...).'
        ),
    )
    RELATED: tuple[str, ...] = ('materials', 'node_trees', 'vse_strip_image')
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
    DESCRIPTION = 'Sound datablocks: filepath, refcount, cache + packed state.'
    AGENT_HINT = (
        'Read-only catalog of bpy.data.sounds. Sounds are consumed by VSE sound strips — '
        'JOIN vse_strip_sound ON vse_strip_sound.sound=sounds.name. packed=1 means the audio '
        'is embedded in the .blend (filepath is advisory). Mutate via bpy_exec.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', hint='Unique within bpy.data.sounds.'),
        Column('filepath', 'TEXT', hint='On-disk path; advisory when packed=1.'),
        Column('users', 'INTEGER', hint='Refcount across the file.'),
        Column('use_memory_cache', 'INTEGER', hint='Boolean as 0/1; decoded audio cached in RAM.'),
        Column('packed', 'INTEGER', hint='Boolean as 0/1; audio embedded in the .blend.'),
    )
    RELATED: tuple[str, ...] = ('vse_strip_sound',)
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
    DESCRIPTION = 'MovieClip datablocks: filepath, duration, fps, resolution.'
    AGENT_HINT = (
        'Read-only catalog of bpy.data.movieclips (video files / image sequences used for '
        'compositing footage and motion tracking — distinct from VSE movie strips, which '
        'reference these). JOIN vse_strip_movie ON vse_strip_movie.movieclip=movieclips.name. '
        'The clip is always file-backed (no pack flag here). Mutate via bpy_exec.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', hint='Unique within bpy.data.movieclips.'),
        Column('filepath', 'TEXT', hint='On-disk path to the video / image sequence.'),
        Column('users', 'INTEGER', hint='Refcount across the file.'),
        Column('frame_duration', 'INTEGER', hint='Total frames in the clip.'),
        Column('fps', 'REAL', hint='Native frames per second from the source.'),
        Column('size_x', 'INTEGER', hint='Pixel width (size[0]).'),
        Column('size_y', 'INTEGER', hint='Pixel height (size[1]).'),
    )
    RELATED: tuple[str, ...] = ('vse_strip_movie',)
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
    DESCRIPTION = 'CacheFile datablocks: Alembic / USD references with playback offsets.'
    AGENT_HINT = (
        'Read-only catalog of bpy.data.cache_files — external Alembic/USD caches that '
        'MeshSequenceCache / Transform Cache modifiers and constraints sample from. The cache '
        "is always file-backed (no pack flag). Standalone-ish — there's no clean per-row join "
        'to objects/modifiers from SQL today (those references are inside modifier params).'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', hint='Unique within bpy.data.cache_files.'),
        Column('filepath', 'TEXT', hint='On-disk path to the .abc / .usd archive.'),
        Column('users', 'INTEGER', hint='Refcount across the file.'),
        Column('frame', 'REAL', hint='Current evaluation frame within the cache.'),
        Column('frame_offset', 'REAL', hint='Offset applied to the playback frame.'),
        Column(
            'override_frame', 'INTEGER', hint='Boolean as 0/1; use `frame` instead of scene time.'
        ),
        Column('scale', 'REAL', hint='Uniform scale applied when sampling.'),
        Column('forward_axis', 'TEXT', hint='POS_X / POS_Y / POS_Z / NEG_X / NEG_Y / NEG_Z.'),
        Column('up_axis', 'TEXT', hint='POS_X / POS_Y / POS_Z / NEG_X / NEG_Y / NEG_Z.'),
    )
    RELATED: tuple[str, ...] = ()
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
    DESCRIPTION = 'VectorFont datablocks: filepath, refcount, packed state.'
    AGENT_HINT = (
        'Read-only catalog of bpy.data.fonts (loaded VectorFont datablocks for 3D text). '
        'Includes the built-in Bfont stub which has no on-disk file. JOIN texts ON '
        'texts.font=fonts.name to find which TextCurve datablocks use a given font (NULL '
        'font on texts means the built-in Bfont). packed=1 means the .ttf/.otf is embedded.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', hint='Unique within bpy.data.fonts; Bfont for the built-in.'),
        Column(
            'filepath', 'TEXT', hint='On-disk path to the font file; empty for the built-in Bfont.'
        ),
        Column('users', 'INTEGER', hint='Refcount across the file.'),
        Column('packed', 'INTEGER', hint='Boolean as 0/1; font embedded in the .blend.'),
    )
    RELATED: tuple[str, ...] = ('texts',)
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
