"""Tier 1 scene verbs: add_object, add_modifier, add_constraint, set_keyframe,
ensure_fcurve."""

from __future__ import annotations

import time
from typing import Any

import bpy

from ...vtables._params import apply_params_json
from ...vtables.datablocks import RESOLVE_CONTAINER
from .._meta import function_meta
from ._common import (
    VerbError,
    arg,
    envelope,
    opt_int,
    opt_str,
    parse_json_dict,
    parse_vec,
    require_int,
    require_str,
    trunc,
)

# Object types that pair with a same-named data container; EMPTY → data=None.
# For these we create the matching datablock via bpy.data.<container>.new(name).
_DATA_CONTAINER: dict[str, str] = {
    'MESH': 'meshes',
    'CURVE': 'curves',
    'SURFACE': 'curves',
    'FONT': 'curves',
    'META': 'metaballs',
    'ARMATURE': 'armatures',
    'LATTICE': 'lattices',
    'CAMERA': 'cameras',
    'LIGHT': 'lights',
    'SPEAKER': 'speakers',
    'CURVES': 'hair_curves',
    'POINTCLOUD': 'pointclouds',
    'VOLUME': 'volumes',
    'GREASEPENCIL': 'grease_pencils',
    'LIGHT_PROBE': 'lightprobes',
}
# bpy.data.<container>.new() that needs a type= arg.
_DATA_NEW_TYPE: dict[str, str] = {'CURVE': 'CURVE', 'SURFACE': 'SURFACE', 'FONT': 'FONT'}


@function_meta(
    kind='verb',
    arity=-1,
    description='Create a new object of given type and link it into a collection.',
    agent_hint=(
        'Args: (type, name, location_json?, collection?). type is the bpy obj '
        'type (MESH/EMPTY/CURVE/...); matching data container is created '
        "automatically. Returns the object's name in the envelope's result."
    ),
    return_shape='json_envelope',
    side_effects=True,
)
def add_object(*args: Any) -> str:
    start = time.monotonic()
    obj_type = arg(args, 0)
    name = arg(args, 1)
    audit_text = f'add_object({obj_type}, {name})'
    try:
        obj_type = require_str(obj_type, 'type')
        name = require_str(name, 'name')
        location = parse_vec(arg(args, 2), 'location_json', 3) if arg(args, 2) is not None else None
        coll_name = opt_str(arg(args, 3), 'collection')

        collection = (
            bpy.context.scene.collection
            if coll_name is None
            else bpy.data.collections.get(coll_name)
        )
        if collection is None:
            raise VerbError(f"collection '{coll_name}' not found")

        if obj_type == 'EMPTY':
            data = None
        else:
            container_attr = _DATA_CONTAINER.get(obj_type)
            if container_attr is None:
                raise VerbError(f"unsupported object type '{obj_type}'")
            container = getattr(bpy.data, container_attr, None)
            if container is None:
                raise VerbError(f"object type '{obj_type}' has no data container in this build")
            new_type = _DATA_NEW_TYPE.get(obj_type)
            data = container.new(name, new_type) if new_type is not None else container.new(name)

        obj = bpy.data.objects.new(name, data)
        collection.objects.link(obj)
        if location is not None:
            obj.location = location
        bpy.ops.ed.undo_push(message=f'blendersql: add_object {obj.name}')
        return envelope(start, 'add_object', audit_text, obj.name, None)
    # verbs report every failure via the envelope, never as a SQL error
    except Exception as exc:
        return envelope(start, 'add_object', audit_text, None, exc)


@function_meta(
    kind='verb',
    arity=-1,
    description='Add a modifier of a given type to an object; apply optional params.',
    agent_hint=(
        'Args: (object, type, params_json?). params_json keys map to modifier '
        "attributes (e.g. {'levels': 2} on SUBSURF). Returns the modifier name."
    ),
    return_shape='json_envelope',
    side_effects=True,
)
def add_modifier(*args: Any) -> str:
    start = time.monotonic()
    obj_name = arg(args, 0)
    mod_type = arg(args, 1)
    audit_text = f'add_modifier({obj_name}, {mod_type})'
    try:
        obj_name = require_str(obj_name, 'object')
        mod_type = require_str(mod_type, 'type')
        params = parse_json_dict(arg(args, 2), 'params_json')

        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            raise VerbError(f"object '{obj_name}' not found")
        base_name = mod_type.title()
        try:
            mod = obj.modifiers.new(name=base_name, type=mod_type)
        except (RuntimeError, TypeError) as exc:
            raise VerbError(f"could not add modifier of type '{mod_type}': {exc}") from exc
        if mod is None:
            raise VerbError(f"object '{obj_name}' rejected modifier of type '{mod_type}'")
        if params:
            apply_params_json(mod, params, {})
        bpy.ops.ed.undo_push(message=f'blendersql: add_modifier {obj_name}/{mod.name}')
        return envelope(start, 'add_modifier', audit_text, mod.name, None)
    except Exception as exc:
        return envelope(start, 'add_modifier', audit_text, None, exc)


@function_meta(
    kind='verb',
    arity=-1,
    description='Add a constraint of a given type to an object; optional target + params.',
    agent_hint=(
        'Args: (object, type, target?, params_json?). target is an object name '
        '(required for constraints with a target slot). params_json patches '
        'constraint attributes after creation.'
    ),
    return_shape='json_envelope',
    side_effects=True,
)
def add_constraint(*args: Any) -> str:
    start = time.monotonic()
    obj_name = arg(args, 0)
    con_type = arg(args, 1)
    audit_text = f'add_constraint({obj_name}, {con_type})'
    try:
        obj_name = require_str(obj_name, 'object')
        con_type = require_str(con_type, 'type')
        target_name = opt_str(arg(args, 2), 'target')
        params = parse_json_dict(arg(args, 3), 'params_json')

        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            raise VerbError(f"object '{obj_name}' not found")
        try:
            con = obj.constraints.new(con_type)
        except (RuntimeError, TypeError) as exc:
            raise VerbError(f"could not add constraint of type '{con_type}': {exc}") from exc
        if con is None:
            raise VerbError(f"object '{obj_name}' rejected constraint of type '{con_type}'")
        if target_name is not None:
            if not hasattr(con, 'target'):
                raise VerbError(f"constraint type '{con_type}' has no target")
            tgt = bpy.data.objects.get(target_name)
            if tgt is None:
                raise VerbError(f"target object '{target_name}' not found")
            con.target = tgt
        if params:
            apply_params_json(con, params, {})
        bpy.ops.ed.undo_push(message=f'blendersql: add_constraint {obj_name}/{con.name}')
        return envelope(start, 'add_constraint', audit_text, con.name, None)
    except Exception as exc:
        return envelope(start, 'add_constraint', audit_text, None, exc)


@function_meta(
    kind='verb',
    arity=-1,
    description='Assign and insert a keyframe at frame on any datablock data_path.',
    agent_hint=(
        'Args: (datablock_type, datablock_name, data_path, frame, value?, '
        'array_index?, interpolation?). Auto-creates the action/layer/strip/'
        'slot/fcurve on layered-action IDs. Pass array_index=-1 for whole-'
        'vector keyframes.'
    ),
    return_shape='json_envelope',
    side_effects=True,
)
def set_keyframe(*args: Any) -> str:
    start = time.monotonic()
    db_type = arg(args, 0)
    db_name = arg(args, 1)
    data_path = arg(args, 2)
    frame = arg(args, 3)
    audit_text = trunc(f'set_keyframe({db_type}, {db_name}, {data_path}, {frame})')
    try:
        db_type = require_str(db_type, 'datablock_type')
        db_name = require_str(db_name, 'datablock_name')
        data_path = require_str(data_path, 'data_path')
        frame = require_int(frame, 'frame')
        array_index = opt_int(arg(args, 5), 'array_index', -1)
        interpolation = opt_str(arg(args, 6), 'interpolation')
        raw_value = arg(args, 4)
        # `value` may be a JSON array (whole vector) or a scalar; arg() strips ''.
        value: Any = None
        if raw_value is not None:
            if isinstance(raw_value, str):
                from ._common import parse_json_arg

                value = parse_json_arg(raw_value, 'value')
            else:
                value = raw_value

        id_block = _resolve_id_block(db_type, db_name)

        if value is not None:
            _assign_at_path(id_block, data_path, array_index, value)

        kw: dict[str, Any] = {'frame': frame}
        if array_index >= 0:
            kw['index'] = array_index
        # keyframe_insert on a layered-action ID auto-creates the layer / keyframe
        # strip / action slot / fcurve as needed (Blender 4.4+ behavior).
        try:
            inserted = id_block.keyframe_insert(data_path, **kw)
        except (RuntimeError, TypeError) as exc:
            raise VerbError(f'keyframe_insert failed: {exc}') from exc
        if not inserted:
            raise VerbError(f"keyframe_insert returned False for '{data_path}'")

        if interpolation is not None:
            _set_interpolation(id_block, data_path, array_index, frame, interpolation)

        bpy.ops.ed.undo_push(message=f'blendersql: set_keyframe {db_name}.{data_path}@{frame}')
        result = {'frame': frame, 'value': _read_at_path(id_block, data_path, array_index)}
        return envelope(start, 'set_keyframe', audit_text, result, None)
    except Exception as exc:
        return envelope(start, 'set_keyframe', audit_text, None, exc)


@function_meta(
    kind='verb',
    arity=-1,
    description='Ensure an fcurve exists for a datablock data_path; create on demand.',
    agent_hint=(
        'Args: (datablock_type, datablock_name, data_path, array_index?, '
        'group_name?). Idempotent: creates the action + fcurve if missing, '
        'then guarantees the fcurve_ensure_for_datablock slot exists. Use '
        'before populating keyframes manually.'
    ),
    return_shape='json_envelope',
    side_effects=True,
)
def ensure_fcurve(*args: Any) -> str:
    start = time.monotonic()
    db_type = arg(args, 0)
    db_name = arg(args, 1)
    data_path = arg(args, 2)
    audit_text = trunc(f'ensure_fcurve({db_type}, {db_name}, {data_path})')
    try:
        db_type = require_str(db_type, 'datablock_type')
        db_name = require_str(db_name, 'datablock_name')
        data_path = require_str(data_path, 'data_path')
        array_index = opt_int(arg(args, 3), 'array_index', 0)
        group_name = opt_str(arg(args, 4), 'group_name') or ''

        id_block = _resolve_id_block(db_type, db_name)
        ad = id_block.animation_data
        if ad is None or ad.action is None:
            if ad is None:
                ad = id_block.animation_data_create()
            ad.action = bpy.data.actions.new(f'{db_name}Action')
        action = ad.action
        try:
            action.fcurve_ensure_for_datablock(
                id_block, data_path, index=array_index, group_name=group_name
            )
        except (RuntimeError, TypeError) as exc:
            raise VerbError(f'fcurve_ensure_for_datablock failed: {exc}') from exc
        bpy.ops.ed.undo_push(message=f'blendersql: ensure_fcurve {db_name}.{data_path}')
        result = {'action': action.name, 'data_path': data_path, 'array_index': array_index}
        return envelope(start, 'ensure_fcurve', audit_text, result, None)
    except Exception as exc:
        return envelope(start, 'ensure_fcurve', audit_text, None, exc)


def _resolve_id_block(db_type: str, db_name: str) -> Any:
    attr = RESOLVE_CONTAINER.get(db_type)
    if attr is None:
        raise VerbError(f"unknown datablock_type '{db_type}'")
    container = getattr(bpy.data, attr, None)
    if container is None:
        raise VerbError(f"datablock_type '{db_type}' has no container in this build")
    block = container.get(db_name)
    if block is None:
        raise VerbError(f"no {db_type} named '{db_name}'")
    return block


def _resolve_path_owner(id_block: Any, data_path: str) -> tuple[Any, str]:
    """Return (owner, attr) for a possibly-nested data_path like 'data.lens'."""
    if '.' not in data_path:
        return id_block, data_path
    head, _, attr = data_path.rpartition('.')
    try:
        owner = id_block.path_resolve(head)
    except (ValueError, AttributeError) as exc:
        raise VerbError(f"data_path '{data_path}': {exc}") from exc
    return owner, attr


def _assign_at_path(id_block: Any, data_path: str, array_index: int, value: Any) -> None:
    owner, attr = _resolve_path_owner(id_block, data_path)
    # A list/tuple value always sets the whole property even when array_index is
    # supplied (array_index still scopes the keyframe_insert call); a scalar with
    # array_index >= 0 sets that one component.
    try:
        if array_index >= 0 and not isinstance(value, (list, tuple)):
            getattr(owner, attr)[array_index] = value
        else:
            setattr(owner, attr, value)
    except (ValueError, TypeError, IndexError, AttributeError) as exc:
        raise VerbError(f"could not set '{data_path}': {exc}") from exc


def _read_at_path(id_block: Any, data_path: str, array_index: int) -> Any:
    from ...functions.jsonify import to_jsonable

    owner, attr = _resolve_path_owner(id_block, data_path)
    try:
        cur = getattr(owner, attr)
    except AttributeError:
        return None
    if array_index >= 0:
        try:
            return to_jsonable(cur[array_index])
        except (IndexError, TypeError):
            return None
    return to_jsonable(cur)


def _iter_action_fcurves(id_block: Any) -> Any:
    ad = id_block.animation_data
    if ad is None or ad.action is None:
        return
    action = ad.action
    slot = ad.action_slot
    legacy = getattr(action, 'fcurves', None)
    if legacy is not None and len(legacy) > 0:
        yield from legacy
    for layer in getattr(action, 'layers', []):
        for strip in layer.strips:
            cb = strip.channelbag(slot) if slot is not None else None
            if cb is None:
                for c in getattr(strip, 'channelbags', []):
                    yield from c.fcurves
            else:
                yield from cb.fcurves


def _set_interpolation(
    id_block: Any, data_path: str, array_index: int, frame: int, interpolation: str
) -> None:
    for fc in _iter_action_fcurves(id_block):
        if fc.data_path != data_path:
            continue
        if array_index >= 0 and fc.array_index != array_index:
            continue
        for kp in fc.keyframe_points:
            if round(kp.co[0]) == frame:
                try:
                    kp.interpolation = interpolation
                except (ValueError, TypeError) as exc:
                    raise VerbError(f"invalid interpolation '{interpolation}': {exc}") from exc
                return
    raise VerbError(f"no keyframe at frame {frame} for '{data_path}' to set interpolation on")
