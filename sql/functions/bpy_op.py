from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import bpy

from . import audit
from ._meta import Param, function_meta
from .jsonify import to_jsonable


@dataclass(frozen=True)
class _OpResult:
    status: str | None
    result: Any
    error: dict[str, Any] | None

    def to_json(self) -> str:
        return json.dumps(
            {'status': self.status, 'result': self.result, 'error': self.error}, default=str
        )


# Override keys whose JSON values are stringified names that must resolve to
# bpy IDs before being passed to context.temp_override(). Everything else
# (area, region, window, custom keys) is passed through verbatim — agents that
# need GUI-bound overrides can stage them via bpy_exec.
_OBJECT_KEYS = ('active_object', 'object', 'edit_object')
_OBJECT_LIST_KEYS = ('selected_objects', 'selected_editable_objects')


@function_meta(
    kind='escape_hatch',
    arity=-1,
    description='Invoke a bpy.ops operator with optional params + context override.',
    agent_hint=(
        'Args: (operator, params_json?, context_override_json?). Returns the '
        '{status, result, error} envelope. Use when an operator has no typed '
        'verb wrapper; otherwise prefer the verb so audit semantics stay '
        'uniform.'
    ),
    return_shape='json_envelope',
    side_effects=True,
    params=(
        Param(
            'operator',
            'TEXT',
            required=True,
            hint='Dotted bpy.ops path (e.g. mesh.primitive_cube_add).',
        ),
        Param(
            'params_json',
            'JSON',
            required=False,
            default_json='{}',
            hint='JSON object of operator kwargs; empty / null for no params.',
        ),
        Param(
            'context_override_json',
            'JSON',
            required=False,
            default_json='{}',
            hint='JSON object passed to bpy.context.temp_override; string IDs resolved to bpy data.',
        ),
    ),
)
def bpy_op(*args: Any) -> str:
    start = time.monotonic()

    if not args:
        return _envelope(
            start, '<no args>', None, None, 'TypeError', 'bpy_op requires at least an operator name'
        )

    operator = args[0]
    params_arg = args[1] if len(args) >= 2 else None
    context_arg = args[2] if len(args) >= 3 else None

    if not isinstance(operator, str):
        return _envelope(start, str(operator), None, None, 'TypeError', 'operator must be a string')

    audit_input = _audit_input(operator, params_arg)

    params, err = _parse_dict_arg(params_arg, 'params_json')
    if err is not None:
        return _envelope(start, audit_input, None, None, err[0], err[1])

    override, err = _parse_dict_arg(context_arg, 'context_override_json')
    if err is not None:
        return _envelope(start, audit_input, None, None, err[0], err[1])

    try:
        node = bpy.ops
        for part in operator.split('.'):
            node = getattr(node, part)
    except AttributeError as exc:
        return _envelope(start, audit_input, None, None, 'AttributeError', str(exc))

    try:
        resolved_override = _resolve_override(override) if override else None
    except (KeyError, AttributeError) as exc:
        return _envelope(start, audit_input, None, None, type(exc).__name__, str(exc))

    # bpy.ops operators register their own undo step; calling ed.undo_push here
    # would double-push. Leave undo to the operator's own behavior.
    try:
        if resolved_override is not None:
            with bpy.context.temp_override(**resolved_override):
                raw = node(**(params or {}))
        else:
            raw = node(**(params or {}))
    except Exception as exc:
        return _envelope(start, audit_input, None, None, type(exc).__name__, str(exc))

    # bpy.ops returns a set of mutually-exclusive status strings (e.g.
    # {'FINISHED'}, {'CANCELLED'}); a handful of custom operators return dicts.
    if isinstance(raw, (set, frozenset)):
        status = next(iter(raw), None)
        result = None
    else:
        status = None
        result = to_jsonable(raw)

    return _envelope(start, audit_input, status, result, None, None)


def _parse_dict_arg(value: Any, label: str) -> tuple[dict[str, Any] | None, tuple[str, str] | None]:
    if value is None or value == '':
        return None, None
    if not isinstance(value, str):
        return None, ('TypeError', f'{label} must be a JSON string')
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        return None, ('JSONDecodeError', f'{label}: {exc}')
    if not isinstance(parsed, dict):
        return None, ('TypeError', f'{label} must decode to an object')
    return parsed, None


def _resolve_override(override: dict[str, Any]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    scene = bpy.data.scenes[override['scene']] if isinstance(override.get('scene'), str) else None

    for key, value in override.items():
        if key in _OBJECT_KEYS and isinstance(value, str):
            resolved[key] = bpy.data.objects[value]
        elif key in _OBJECT_LIST_KEYS and isinstance(value, list):
            resolved[key] = [bpy.data.objects[name] for name in value]
        elif key == 'scene' and isinstance(value, str):
            resolved[key] = bpy.data.scenes[value]
        elif key == 'view_layer' and isinstance(value, str):
            owner = scene if scene is not None else bpy.context.scene
            resolved[key] = owner.view_layers[value]
        else:
            resolved[key] = value
    return resolved


def _audit_input(operator: str, params_arg: Any) -> str:
    if isinstance(params_arg, str) and params_arg:
        suffix = params_arg if len(params_arg) <= 80 else params_arg[:80] + '...'
        return f'{operator}({suffix})'
    return f'{operator}()'


def _envelope(
    start: float,
    audit_input: str,
    status: str | None,
    result: Any,
    error_type: str | None,
    error_message: str | None,
) -> str:
    duration = round((time.monotonic() - start) * 1000, 2)
    success = error_type is None
    audit.log('bpy_op', audit_input, success, duration, error_type)
    error = None if error_type is None else {'type': error_type, 'message': error_message}
    return _OpResult(status=status, result=result, error=error).to_json()
