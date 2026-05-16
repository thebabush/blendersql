from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import bpy

from ._meta import Column
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
    DESCRIPTION = 'VSE strips (all kinds): timing, channel, blend, mute/lock, metastrip parent.'
    AGENT_HINT = (
        'Base aggregate over every strip in every scene.sequence_editor (recurses into metastrips). '
        'Identity is (scene, name) — names repeat across scenes. JOIN type-specific tables on '
        'vse_strips.scene=vse_strip_*.scene AND vse_strips.name=vse_strip_*.strip; filter by type '
        '(SOUND/MOVIE/IMAGE/SCENE/TEXT/COLOR/META/...) to pick the right side table. Read-only; '
        'mutate via bpy_exec.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('scene', 'TEXT', hint='Owning scenes.name.'),
        Column('name', 'TEXT', hint='Strip name; unique within a scene.sequence_editor.'),
        Column('type', 'TEXT', hint='SOUND / MOVIE / IMAGE / SCENE / TEXT / COLOR / META / ...'),
        Column('channel', 'INTEGER', hint='Sequencer channel (1-based row).'),
        Column('frame_start', 'REAL', hint='Strip start in scene frames.'),
        Column('frame_final_duration', 'INTEGER', hint='Effective duration after offsets.'),
        Column('frame_final_end', 'REAL', hint='frame_start + frame_final_duration.'),
        Column('frame_offset_start', 'REAL', hint='Left trim into the source (frames).'),
        Column('frame_offset_end', 'REAL', hint='Right trim into the source (frames).'),
        Column('mute', 'INTEGER', hint='Boolean as 0/1.'),
        Column('lock', 'INTEGER', hint='Boolean as 0/1.'),
        Column('select', 'INTEGER', hint='Boolean as 0/1; UI selection state.'),
        Column('blend_type', 'TEXT', hint='REPLACE / CROSS / ADD / MULTIPLY / ALPHA_OVER / ...'),
        Column('blend_alpha', 'REAL', hint='Blend opacity in [0,1].'),
        Column('parent_meta', 'TEXT', hint='Owning metastrip name; NULL when top-level.'),
    )
    RELATED: tuple[str, ...] = (
        'vse_strip_sound',
        'vse_strip_movie',
        'vse_strip_image',
        'vse_strip_scene',
        'vse_strip_text',
        'vse_strip_color',
        'scenes',
    )
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
    DESCRIPTION = 'Sound-strip extension: bound sound datablock, volume/pan, pitch correction.'
    AGENT_HINT = (
        "Type-specific side table for vse_strips where type='SOUND' (filter applied implicitly). "
        'JOIN vse_strips ON vse_strips.scene=vse_strip_sound.scene AND vse_strips.name=vse_strip_sound.strip; '
        'JOIN sounds ON sounds.name=vse_strip_sound.sound to reach the audio datablock. Read-only.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('scene', 'TEXT', hint='Owning scenes.name.'),
        Column('strip', 'TEXT', hint='Owning vse_strips.name.'),
        Column('sound', 'TEXT', hint='Bound sounds.name; NULL when unlinked.'),
        Column('volume', 'REAL', hint='Playback volume multiplier.'),
        Column('pan', 'REAL', hint='Stereo pan in [-2,2].'),
        Column('pitch_correction', 'INTEGER', hint='Boolean as 0/1; 5.1 renamed from `pitch`.'),
        Column('show_waveform', 'INTEGER', hint='Boolean as 0/1; waveform draw in sequencer.'),
    )
    RELATED: tuple[str, ...] = ('vse_strips', 'sounds')
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
    DESCRIPTION = 'Movie-strip extension: source filepath, stream index, source fps.'
    AGENT_HINT = (
        "Type-specific side table for vse_strips where type='MOVIE'. JOIN vse_strips ON "
        'vse_strips.scene=vse_strip_movie.scene AND vse_strips.name=vse_strip_movie.strip; '
        'filepath references an on-disk file (movie strips have no datablock binding). Read-only.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('scene', 'TEXT', hint='Owning scenes.name.'),
        Column('strip', 'TEXT', hint='Owning vse_strips.name.'),
        Column('filepath', 'TEXT', hint='Absolute or // -relative source path.'),
        Column('stream_index', 'INTEGER', hint='Video stream index inside the container.'),
        Column('fps', 'REAL', hint='Source frames-per-second as reported by the container.'),
    )
    RELATED: tuple[str, ...] = ('vse_strips', 'movieclips')
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
    DESCRIPTION = 'Image-strip extension: source directory, frame offsets into the sequence.'
    AGENT_HINT = (
        "Type-specific side table for vse_strips where type='IMAGE'. JOIN vse_strips ON "
        'vse_strips.scene=vse_strip_image.scene AND vse_strips.name=vse_strip_image.strip. '
        'directory is the folder holding the image sequence (per-frame filenames live on the '
        'strip.elements list, not surfaced here). Read-only.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('scene', 'TEXT', hint='Owning scenes.name.'),
        Column('strip', 'TEXT', hint='Owning vse_strips.name.'),
        Column('directory', 'TEXT', hint='Directory containing the image sequence frames.'),
        Column('frame_offset_start', 'REAL', hint='Left trim into the source (frames).'),
        Column(
            'animation_offset_start',
            'INTEGER',
            hint='Source-side offset before frame_offset_start applies.',
        ),
    )
    RELATED: tuple[str, ...] = ('vse_strips', 'images')
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
    DESCRIPTION = 'Scene-strip extension: rendered source scene, camera override, input mode.'
    AGENT_HINT = (
        "Type-specific side table for vse_strips where type='SCENE'. Note `scene` is the owning "
        'sequencer scene and `source_scene` is the scene being rendered — different rows. JOIN '
        'vse_strips ON vse_strips.scene=vse_strip_scene.scene AND vse_strips.name=vse_strip_scene.strip; '
        'JOIN scenes ON scenes.name=vse_strip_scene.source_scene. Read-only.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('scene', 'TEXT', hint='Owning sequencer scenes.name (where the strip lives).'),
        Column('strip', 'TEXT', hint='Owning vse_strips.name.'),
        Column('source_scene', 'TEXT', hint='scenes.name being rendered by the strip.'),
        Column(
            'scene_camera',
            'TEXT',
            hint='Camera override (objects.name); NULL uses source_scene.camera. 5.1 rename.',
        ),
        Column('scene_input', 'TEXT', hint='CAMERA or SEQUENCER (5.1 replaced use_sequence).'),
    )
    RELATED: tuple[str, ...] = ('vse_strips', 'scenes')
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
    DESCRIPTION = 'Text-strip extension: text, font, size, color, anchor/alignment, outline/shadow.'
    AGENT_HINT = (
        "Type-specific side table for vse_strips where type='TEXT'. JOIN vse_strips ON "
        'vse_strips.scene=vse_strip_text.scene AND vse_strips.name=vse_strip_text.strip; JOIN fonts '
        'ON fonts.name=vse_strip_text.font. 5.1 uses anchor_x/anchor_y instead of alignment_y. '
        'Read-only.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('scene', 'TEXT', hint='Owning scenes.name.'),
        Column('strip', 'TEXT', hint='Owning vse_strips.name.'),
        Column('text', 'TEXT', hint='Rendered text content.'),
        Column('font', 'TEXT', hint='Bound fonts.name; NULL uses Blender built-in.'),
        Column('font_size', 'REAL', hint='Text size in points.'),
        Column('color_r', 'REAL'),
        Column('color_g', 'REAL'),
        Column('color_b', 'REAL'),
        Column('color_a', 'REAL'),
        Column('location_x', 'REAL', hint='Normalized X placement in [0,1].'),
        Column('location_y', 'REAL', hint='Normalized Y placement in [0,1].'),
        Column('wrap_width', 'REAL', hint='Word-wrap width; 0 disables.'),
        Column('alignment_x', 'TEXT', hint='LEFT / CENTER / RIGHT.'),
        Column('anchor_x', 'TEXT', hint='LEFT / CENTER / RIGHT (5.1).'),
        Column('anchor_y', 'TEXT', hint='TOP / CENTER / BOTTOM (5.1).'),
        Column('use_shadow', 'INTEGER', hint='Boolean as 0/1.'),
        Column('use_outline', 'INTEGER', hint='Boolean as 0/1.'),
    )
    RELATED: tuple[str, ...] = ('vse_strips', 'fonts')
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
    DESCRIPTION = 'Color-strip extension: solid RGB fill (no alpha at the strip level).'
    AGENT_HINT = (
        "Type-specific side table for vse_strips where type='COLOR'. JOIN vse_strips ON "
        'vse_strips.scene=vse_strip_color.scene AND vse_strips.name=vse_strip_color.strip. Strip-'
        'level opacity lives on vse_strips.blend_alpha. Read-only.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('scene', 'TEXT', hint='Owning scenes.name.'),
        Column('strip', 'TEXT', hint='Owning vse_strips.name.'),
        Column('color_r', 'REAL'),
        Column('color_g', 'REAL'),
        Column('color_b', 'REAL'),
    )
    RELATED: tuple[str, ...] = ('vse_strips',)
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
