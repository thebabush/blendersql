"""Tier 3 Grease Pencil v3 verbs: gp_add_layer, gp_add_frame, gp_add_stroke,
gp_resize_strokes.

GP v3 (Blender 5.x) replaced the legacy stroke API. Strokes are curve geometry
on a per-keyframe `GreasePencilDrawing`; new strokes are appended via
`drawing.add_strokes([n_points, ...])` and edited through `drawing.strokes[i]`.
Re-fetch the stroke slice after any geometry change — old slices go stale.
"""

from __future__ import annotations

import time
from typing import Any

import bpy

from .._meta import Param, function_meta
from ._common import (
    VerbError,
    arg,
    envelope,
    opt_str,
    parse_json_arg,
    parse_json_list,
    require_int,
    require_str,
)


@function_meta(
    kind='verb',
    arity=-1,
    description='Add a layer to a GreasePencil v3 datablock; optional layer group.',
    agent_hint=(
        'Args: (grease_pencil, name, layer_group?). layer_group is an existing '
        'group on the gp datablock. Returns the new layer name.'
    ),
    return_shape='json_envelope',
    side_effects=True,
    params=(
        Param('grease_pencil', 'TEXT', required=True, hint='GreasePencil v3 datablock name.'),
        Param('name', 'TEXT', required=True, hint='Layer name (unique within the datablock).'),
        Param(
            'layer_group',
            'TEXT',
            required=False,
            default_json='null',
            hint='Optional existing layer group to place the new layer under.',
        ),
    ),
)
def gp_add_layer(*args: Any) -> str:
    start = time.monotonic()
    gp_name = arg(args, 0)
    layer_name = arg(args, 1)
    audit_text = f'gp_add_layer({gp_name}, {layer_name})'
    try:
        gp = _resolve_gp(gp_name)
        layer_name = require_str(layer_name, 'name')
        group_name = opt_str(arg(args, 2), 'layer_group')
        group = None
        if group_name is not None:
            group = gp.layer_groups.get(group_name)
            if group is None:
                raise VerbError(f"layer group '{group_name}' not found")
        layer = gp.layers.new(layer_name, layer_group=group)
        bpy.ops.ed.undo_push(message=f'blendersql: gp_add_layer {gp_name}/{layer.name}')
        return envelope(start, 'gp_add_layer', audit_text, layer.name, None)
    except Exception as exc:
        return envelope(start, 'gp_add_layer', audit_text, None, exc)


@function_meta(
    kind='verb',
    arity=-1,
    description='Create a new GP v3 frame on a layer at a given frame_number.',
    agent_hint=(
        'Args: (grease_pencil, layer, frame_number, keyframe_type?). '
        'Required before adding strokes. keyframe_type is KEYFRAME / BREAKDOWN '
        '/ EXTREME / JITTER / MOVING_HOLD.'
    ),
    return_shape='json_envelope',
    side_effects=True,
    params=(
        Param('grease_pencil', 'TEXT', required=True, hint='GreasePencil v3 datablock name.'),
        Param('layer', 'TEXT', required=True, hint='Existing layer name on the datablock.'),
        Param(
            'frame_number', 'INTEGER', required=True, hint='Frame number to create the keyframe at.'
        ),
        Param(
            'keyframe_type',
            'TEXT',
            required=False,
            default_json='null',
            hint='Optional KEYFRAME / BREAKDOWN / EXTREME / JITTER / MOVING_HOLD.',
        ),
    ),
)
def gp_add_frame(*args: Any) -> str:
    start = time.monotonic()
    gp_name = arg(args, 0)
    layer_name = arg(args, 1)
    audit_text = f'gp_add_frame({gp_name}, {layer_name}, {arg(args, 2)})'
    try:
        gp = _resolve_gp(gp_name)
        layer = _resolve_layer(gp, layer_name)
        frame_number = require_int(arg(args, 2), 'frame_number')
        keyframe_type = opt_str(arg(args, 3), 'keyframe_type')
        frame = layer.frames.new(frame_number)
        if keyframe_type is not None:
            try:
                frame.keyframe_type = keyframe_type
            except (ValueError, TypeError) as exc:
                raise VerbError(f"invalid keyframe_type '{keyframe_type}': {exc}") from exc
        bpy.ops.ed.undo_push(
            message=f'blendersql: gp_add_frame {gp_name}/{layer_name}@{frame_number}'
        )
        return envelope(start, 'gp_add_frame', audit_text, {'frame_number': frame_number}, None)
    except Exception as exc:
        return envelope(start, 'gp_add_frame', audit_text, None, exc)


@function_meta(
    kind='verb',
    arity=-1,
    description='Append a stroke (point list) to a GP v3 frame drawing.',
    agent_hint=(
        'Args: (grease_pencil, layer, frame, points_json, material_index?, '
        'cyclic?). points_json is [{x,y,z,radius?,opacity?}, ...] or [[x,y,z], '
        '...]. Frame must already exist (gp_add_frame first). Returns the new '
        "stroke's index in the drawing."
    ),
    return_shape='json_envelope',
    side_effects=True,
    params=(
        Param('grease_pencil', 'TEXT', required=True, hint='GreasePencil v3 datablock name.'),
        Param('layer', 'TEXT', required=True, hint='Existing layer name on the datablock.'),
        Param(
            'frame',
            'INTEGER',
            required=True,
            hint='Frame number — must already exist (gp_add_frame first).',
        ),
        Param(
            'points_json',
            'JSON',
            required=True,
            hint='Stroke points as [{x,y,z,radius?,opacity?}, ...] or [[x,y,z], ...].',
        ),
        Param(
            'material_index',
            'INTEGER',
            required=False,
            default_json='null',
            hint='Optional material slot index to assign the stroke.',
        ),
        Param(
            'cyclic',
            'INTEGER',
            required=False,
            default_json='null',
            hint='Optional 0/1; close the stroke into a loop.',
        ),
    ),
)
def gp_add_stroke(*args: Any) -> str:
    start = time.monotonic()
    gp_name = arg(args, 0)
    layer_name = arg(args, 1)
    frame_number = arg(args, 2)
    audit_text = f'gp_add_stroke({gp_name}, {layer_name}, {frame_number})'
    try:
        gp = _resolve_gp(gp_name)
        layer = _resolve_layer(gp, layer_name)
        frame_number = require_int(frame_number, 'frame')
        frame = _resolve_frame(layer, frame_number)
        points = _parse_points(arg(args, 3))
        material_index = arg(args, 4)
        cyclic = arg(args, 5)

        drawing = frame.drawing
        first_new = len(drawing.strokes)
        drawing.add_strokes([len(points)])
        stroke = drawing.strokes[first_new]
        for i, pt in enumerate(points):
            sp = stroke.points[i]
            sp.position = (pt['x'], pt['y'], pt['z'])
            if 'radius' in pt:
                sp.radius = pt['radius']
            if 'opacity' in pt:
                sp.opacity = pt['opacity']
        if material_index is not None:
            stroke.material_index = require_int(material_index, 'material_index')
        if cyclic is not None:
            stroke.cyclic = bool(cyclic)
        bpy.ops.ed.undo_push(message=f'blendersql: gp_add_stroke {gp_name}/{layer_name}')
        result = {'stroke_index': first_new, 'point_count': len(points)}
        return envelope(start, 'gp_add_stroke', audit_text, result, None)
    except Exception as exc:
        return envelope(start, 'gp_add_stroke', audit_text, None, exc)


@function_meta(
    kind='verb',
    arity=-1,
    description='Resize every stroke in a GP v3 frame to match a sizes array.',
    agent_hint=(
        'Args: (grease_pencil, layer, frame, sizes_json). sizes_json must have '
        'exactly one entry per stroke in the drawing. Use when you need to '
        'bulk-change stroke point counts; per-stroke resize happens via the GP '
        'API.'
    ),
    return_shape='json_envelope',
    side_effects=True,
    params=(
        Param('grease_pencil', 'TEXT', required=True, hint='GreasePencil v3 datablock name.'),
        Param('layer', 'TEXT', required=True, hint='Existing layer name on the datablock.'),
        Param('frame', 'INTEGER', required=True, hint='Frame number of the drawing to resize.'),
        Param(
            'sizes_json',
            'JSON',
            required=True,
            hint='Array of new point counts; one entry per stroke in the drawing.',
        ),
    ),
)
def gp_resize_strokes(*args: Any) -> str:
    start = time.monotonic()
    gp_name = arg(args, 0)
    layer_name = arg(args, 1)
    frame_number = arg(args, 2)
    audit_text = f'gp_resize_strokes({gp_name}, {layer_name}, {frame_number})'
    try:
        gp = _resolve_gp(gp_name)
        layer = _resolve_layer(gp, layer_name)
        frame_number = require_int(frame_number, 'frame')
        frame = _resolve_frame(layer, frame_number)
        sizes_raw = parse_json_list(arg(args, 3), 'sizes_json')
        if not sizes_raw:
            raise VerbError('sizes_json must be a non-empty array of integers')
        sizes = [require_int(s, 'sizes_json[]') for s in sizes_raw]
        drawing = frame.drawing
        if len(sizes) != len(drawing.strokes):
            raise VerbError(
                f'sizes_json has {len(sizes)} entries but drawing has {len(drawing.strokes)} strokes'
            )
        drawing.resize_strokes(sizes=sizes, indices=list(range(len(sizes))))
        bpy.ops.ed.undo_push(message=f'blendersql: gp_resize_strokes {gp_name}/{layer_name}')
        return envelope(start, 'gp_resize_strokes', audit_text, {'stroke_count': len(sizes)}, None)
    except Exception as exc:
        return envelope(start, 'gp_resize_strokes', audit_text, None, exc)


def _parse_points(raw: Any) -> list[dict[str, Any]]:
    parsed = parse_json_arg(raw, 'points_json')
    if not isinstance(parsed, list) or not parsed:
        raise VerbError('points_json must be a non-empty array')
    out: list[dict[str, Any]] = []
    for i, p in enumerate(parsed):
        if isinstance(p, dict):
            try:
                out.append(
                    {
                        'x': float(p['x']),
                        'y': float(p['y']),
                        'z': float(p['z']),
                        **({'radius': float(p['radius'])} if 'radius' in p else {}),
                        **({'opacity': float(p['opacity'])} if 'opacity' in p else {}),
                    }
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise VerbError(f'points_json[{i}]: {exc}') from exc
        elif isinstance(p, (list, tuple)) and len(p) == 3:
            try:
                out.append({'x': float(p[0]), 'y': float(p[1]), 'z': float(p[2])})
            except (TypeError, ValueError) as exc:
                raise VerbError(f'points_json[{i}]: {exc}') from exc
        else:
            raise VerbError(f'points_json[{i}] must be [x,y,z] or {{x,y,z,...}}')
    return out


def _resolve_gp(name: Any) -> Any:
    name = require_str(name, 'gp')
    gp = bpy.data.grease_pencils.get(name)
    if gp is None:
        raise VerbError(f"grease pencil '{name}' not found")
    return gp


def _resolve_layer(gp: Any, layer_name: Any) -> Any:
    layer_name = require_str(layer_name, 'layer')
    layer = gp.layers.get(layer_name)
    if layer is None:
        raise VerbError(f"layer '{layer_name}' not found on '{gp.name}'")
    return layer


def _resolve_frame(layer: Any, frame_number: int) -> Any:
    frame = next((f for f in layer.frames if int(f.frame_number) == frame_number), None)
    if frame is None:
        raise VerbError(f'no frame at {frame_number} on layer; create it with gp_add_frame first')
    return frame
