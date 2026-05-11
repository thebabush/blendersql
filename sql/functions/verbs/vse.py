"""Tier 3 VSE verbs: vse_add_sound / movie / scene_strip / text / color.

In Blender 5.1 the sequencer collection is `scene.sequence_editor.strips`
(a StripsTopLevel). The `new_*` factories take a *name* + a source — note
`new_sound` / `new_movie` take a filepath string (not a datablock), and
`new_effect` for COLOR / TEXT takes `*, length=` (not `frame_end`), so the
verbs translate an optional `frame_end` into a length.
"""

from __future__ import annotations

import time
from typing import Any

import bpy

from ._common import (
    VerbError,
    arg,
    envelope,
    opt_int,
    parse_vec,
    require_int,
    require_str,
)


def vse_add_sound(*args: Any) -> str:
    start = time.monotonic()
    scene_name = arg(args, 0)
    sound_name = arg(args, 1)
    audit_text = f'vse_add_sound({scene_name}, {sound_name})'
    try:
        se = _resolve_editor(scene_name)
        sound_name = require_str(sound_name, 'sound')
        channel = require_int(arg(args, 2), 'channel')
        frame_start = require_int(arg(args, 3), 'frame_start')
        sound = bpy.data.sounds.get(sound_name)
        if sound is None:
            raise VerbError(f"sound '{sound_name}' not found")
        strip = se.strips.new_sound(sound_name, sound.filepath, channel, frame_start)
        return _ok(start, 'vse_add_sound', audit_text, strip)
    except Exception as exc:
        return envelope(start, 'vse_add_sound', audit_text, None, exc)


def vse_add_movie(*args: Any) -> str:
    start = time.monotonic()
    scene_name = arg(args, 0)
    filepath = arg(args, 1)
    audit_text = f'vse_add_movie({scene_name}, {filepath})'
    try:
        se = _resolve_editor(scene_name)
        filepath = require_str(filepath, 'filepath')
        channel = require_int(arg(args, 2), 'channel')
        frame_start = require_int(arg(args, 3), 'frame_start')
        name = _basename(filepath)
        strip = se.strips.new_movie(name, filepath, channel, frame_start)
        return _ok(start, 'vse_add_movie', audit_text, strip)
    except Exception as exc:
        return envelope(start, 'vse_add_movie', audit_text, None, exc)


def vse_add_scene_strip(*args: Any) -> str:
    start = time.monotonic()
    scene_name = arg(args, 0)
    source_name = arg(args, 1)
    audit_text = f'vse_add_scene_strip({scene_name}, {source_name})'
    try:
        se = _resolve_editor(scene_name)
        source_name = require_str(source_name, 'source_scene')
        channel = require_int(arg(args, 2), 'channel')
        frame_start = require_int(arg(args, 3), 'frame_start')
        source = bpy.data.scenes.get(source_name)
        if source is None:
            raise VerbError(f"scene '{source_name}' not found")
        strip = se.strips.new_scene(source_name, source, channel, frame_start)
        return _ok(start, 'vse_add_scene_strip', audit_text, strip)
    except Exception as exc:
        return envelope(start, 'vse_add_scene_strip', audit_text, None, exc)


def vse_add_text(*args: Any) -> str:
    start = time.monotonic()
    scene_name = arg(args, 0)
    text = arg(args, 1)
    audit_text = f'vse_add_text({scene_name})'
    try:
        se = _resolve_editor(scene_name)
        text = require_str(text, 'text')
        channel = require_int(arg(args, 2), 'channel')
        frame_start = require_int(arg(args, 3), 'frame_start')
        length = _length_from_frame_end(arg(args, 4), frame_start)
        strip = se.strips.new_effect('Text', 'TEXT', channel, frame_start, length=length)
        strip.text = text
        return _ok(start, 'vse_add_text', audit_text, strip)
    except Exception as exc:
        return envelope(start, 'vse_add_text', audit_text, None, exc)


def vse_add_color(*args: Any) -> str:
    start = time.monotonic()
    scene_name = arg(args, 0)
    audit_text = f'vse_add_color({scene_name})'
    try:
        se = _resolve_editor(scene_name)
        color = parse_vec(arg(args, 1), 'color_json', 3)
        channel = require_int(arg(args, 2), 'channel')
        frame_start = require_int(arg(args, 3), 'frame_start')
        length = _length_from_frame_end(arg(args, 4), frame_start)
        strip = se.strips.new_effect('Color', 'COLOR', channel, frame_start, length=length)
        strip.color = color
        return _ok(start, 'vse_add_color', audit_text, strip)
    except Exception as exc:
        return envelope(start, 'vse_add_color', audit_text, None, exc)


def _ok(start: float, op: str, audit_text: str, strip: Any) -> str:
    bpy.ops.ed.undo_push(message=f'blendersql: {op} {strip.name}')
    return envelope(start, op, audit_text, strip.name, None)


def _resolve_editor(scene_name: Any) -> Any:
    scene_name = require_str(scene_name, 'scene')
    scene = bpy.data.scenes.get(scene_name)
    if scene is None:
        raise VerbError(f"scene '{scene_name}' not found")
    se = scene.sequence_editor
    if se is None:
        se = scene.sequence_editor_create()
    return se


def _length_from_frame_end(frame_end: Any, frame_start: int) -> int:
    end = opt_int(frame_end, 'frame_end', 0)
    if end <= 0:
        return 0
    if end <= frame_start:
        raise VerbError('frame_end must be greater than frame_start')
    return end - frame_start


def _basename(path: str) -> str:
    cleaned = path.rstrip('/').rstrip('\\')
    for sep in ('/', '\\'):
        if sep in cleaned:
            cleaned = cleaned.rsplit(sep, 1)[1]
    return cleaned or 'Strip'
