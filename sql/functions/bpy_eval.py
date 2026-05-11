from __future__ import annotations

import json
import time

import bpy
import mathutils

from . import audit
from .jsonify import to_jsonable


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
