from __future__ import annotations

import contextlib
import io
import json
import time
from dataclasses import dataclass
from typing import Any

import bpy
import mathutils

from . import audit
from .jsonify import to_jsonable


@dataclass(frozen=True)
class _ExecResult:
    stdout: str
    result: Any
    error: dict[str, Any] | None

    def to_json(self) -> str:
        return json.dumps(
            {'stdout': self.stdout, 'result': self.result, 'error': self.error}, default=str
        )


def bpy_exec(code: str) -> str:
    start = time.monotonic()
    if not isinstance(code, str):
        duration = round((time.monotonic() - start) * 1000, 2)
        audit.log('bpy_exec', str(code), False, duration, 'TypeError')
        return _ExecResult(
            stdout='',
            result=None,
            error={'type': 'TypeError', 'message': 'code must be a string'},
        ).to_json()

    scope: dict[str, object] = {'bpy': bpy, 'mathutils': mathutils}
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(code, scope)
        result = to_jsonable(scope.get('result'))
        duration = round((time.monotonic() - start) * 1000, 2)
        audit.log('bpy_exec', code, True, duration, None)
        return _ExecResult(stdout=buf.getvalue(), result=result, error=None).to_json()
    except Exception as exc:
        duration = round((time.monotonic() - start) * 1000, 2)
        audit.log('bpy_exec', code, False, duration, type(exc).__name__)
        return _ExecResult(
            stdout=buf.getvalue(),
            result=None,
            error={'type': type(exc).__name__, 'message': str(exc)},
        ).to_json()
