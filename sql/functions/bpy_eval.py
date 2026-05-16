from __future__ import annotations

import json
import time

import bpy
import mathutils

from . import audit
from ._meta import Param, function_meta
from .jsonify import to_jsonable


@function_meta(
    kind='escape_hatch',
    arity=1,
    description='Eval a Python expression in a bpy/mathutils scope; returns JSON.',
    agent_hint=(
        'Read-only escape hatch — use for one-off reads when no vtable covers '
        'what you need. Returns a JSON-encoded value (or {"error": ...}). For '
        'multi-statement code, reach for bpy_exec instead.'
    ),
    return_shape='json',
    side_effects=False,
    params=(
        Param(
            'expr',
            'TEXT',
            required=True,
            hint='Python expression evaluated in a {bpy, mathutils} scope.',
        ),
    ),
)
def bpy_eval(expr: str) -> str:
    start = time.monotonic()
    if not isinstance(expr, str):
        duration = round((time.monotonic() - start) * 1000, 2)
        audit.log('bpy_eval', str(expr), False, duration, 'TypeError')
        return json.dumps({'error': 'expr must be a string'})

    try:
        value = eval(expr, {'bpy': bpy, 'mathutils': mathutils})
        result = json.dumps(to_jsonable(value), default=str)
        duration = round((time.monotonic() - start) * 1000, 2)
        audit.log('bpy_eval', expr, True, duration, None)
        return result
    except Exception as exc:
        duration = round((time.monotonic() - start) * 1000, 2)
        audit.log('bpy_eval', expr, False, duration, type(exc).__name__)
        return json.dumps({'error': f'{type(exc).__name__}: {exc}'})
