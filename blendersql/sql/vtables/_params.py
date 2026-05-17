"""Shared `params_json` apply helper for modifiers / constraints.

Both tables surface their grab-bag of type-specific RNA properties as a
`params_json` blob (see `modifiers._dump_props`). On UPDATE we receive the
full blob back; this helper diffs it against the current state and pushes
each changed key onto the bpy datablock, resolving pointer properties (which
`_dump_props` serialised as bare datablock names) by name.
"""

from __future__ import annotations

import json
from typing import Any

import apsw
import bpy

# Pointer props on modifiers/constraints almost always reference an Object
# (target, offset_object, mirror_object, start_cap, end_cap, …). A few point
# at other ID types (curve -> Curve, texture -> Texture, …). We probe a small
# ordered set of containers by datablock name; the first hit wins.
_POINTER_CONTAINERS: tuple[str, ...] = (
    'objects',
    'curves',
    'meshes',
    'textures',
    'images',
    'collections',
    'materials',
    'node_groups',
    'armatures',
)


def parse_params_json(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, str):
        raise apsw.SQLError('params_json must be a JSON-encoded TEXT value')
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise apsw.SQLError(f'params_json: invalid JSON ({exc.msg})') from exc
    if not isinstance(parsed, dict):
        raise apsw.SQLError('params_json must decode to a JSON object')
    return parsed


def apply_params_json(
    target: Any, new_params: dict[str, Any], current_params: dict[str, Any]
) -> None:
    rna_props = target.bl_rna.properties
    for key, new_value in new_params.items():
        if key in current_params and current_params[key] == new_value:
            continue
        prop = rna_props.get(key)
        if prop is None:
            raise apsw.SQLError(f"params_json: unknown property '{key}'")
        if prop.is_readonly:
            continue
        if prop.type == 'POINTER':
            resolved = None if new_value is None else _resolve_pointer(prop, new_value)
            try:
                setattr(target, key, resolved)
            except (ValueError, TypeError) as exc:
                raise apsw.SQLError(f'{key}: {exc}') from exc
            continue
        try:
            setattr(target, key, new_value)
        except (ValueError, TypeError) as exc:
            raise apsw.SQLError(f'{key}: {exc}') from exc


def _resolve_pointer(prop: Any, name: Any) -> Any:
    if not isinstance(name, str):
        raise apsw.SQLError(f'{prop.identifier}: pointer value must be a datablock name string')
    # Prefer the container matching the RNA fixed_type when we can name it; fall
    # back to probing the common containers in order.
    fixed = getattr(prop, 'fixed_type', None)
    fixed_id = getattr(fixed, 'identifier', None) if fixed is not None else None
    containers: tuple[str, ...] = _POINTER_CONTAINERS
    if fixed_id == 'Object':
        containers = ('objects',)
    elif fixed_id == 'Curve':
        containers = ('curves',)
    elif fixed_id == 'Mesh':
        containers = ('meshes',)
    elif fixed_id == 'Collection':
        containers = ('collections',)
    for attr in containers:
        container = getattr(bpy.data, attr, None)
        if container is None:
            continue
        block = container.get(name)
        if block is not None:
            return block
    raise apsw.SQLError(f"{prop.identifier}: no datablock named '{name}'")
