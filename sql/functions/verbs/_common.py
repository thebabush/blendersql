"""Shared envelope + argument helpers for the M2.c domain verbs.

Every verb wraps its body in a `try/except` and returns the JSON produced by
`envelope()`:

    {"ok": bool, "result": <verb-specific> | null, "error": {type, message} | null}

Note this is a deliberately different shape from `bpy_op`'s
`{status, result, error}` — `bpy_op` mirrors operator return semantics
(a status string set), whereas the verbs are plain function calls. On any
failure the verb still returns a JSON string with `ok: false`; the outer SQL
query stays `ok: true`, matching the `bpy_eval`/`bpy_exec`/`bpy_op` contract.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from .. import audit


@dataclass(frozen=True)
class VerbResult:
    ok: bool
    result: Any
    error: dict[str, Any] | None

    def to_json(self) -> str:
        return json.dumps({'ok': self.ok, 'result': self.result, 'error': self.error}, default=str)


def envelope(start: float, op: str, input_text: str, result: Any, exc: BaseException | None) -> str:
    duration = round((time.monotonic() - start) * 1000, 2)
    success = exc is None
    error_type = None if exc is None else type(exc).__name__
    audit.log(op, input_text, success, duration, error_type)
    if exc is None:
        envelope_result = VerbResult(ok=True, result=result, error=None)
    else:
        envelope_result = VerbResult(
            ok=False, result=None, error={'type': error_type, 'message': str(exc)}
        )
    return envelope_result.to_json()


class VerbError(Exception):
    """Raised for bad arguments / resolution failures inside a verb body."""


def arg(args: tuple[Any, ...], index: int, default: Any = None) -> Any:
    if index >= len(args):
        return default
    v = args[index]
    return default if v == '' else v


def require_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise VerbError(f'{name} must be a non-empty string')
    return value


def opt_str(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise VerbError(f'{name} must be a string')
    return value or None


def require_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VerbError(f'{name} must be a number')
    return int(value)


def opt_int(value: Any, name: str, default: int) -> int:
    if value is None:
        return default
    return require_int(value, name)


def parse_json_arg(value: Any, name: str) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        raise VerbError(f'{name} must be a JSON-encoded string')
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise VerbError(f'{name}: invalid JSON ({exc})') from exc


def parse_json_dict(value: Any, name: str) -> dict[str, Any]:
    parsed = parse_json_arg(value, name)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise VerbError(f'{name} must decode to a JSON object')
    return parsed


def parse_json_list(value: Any, name: str) -> list[Any] | None:
    parsed = parse_json_arg(value, name)
    if parsed is None:
        return None
    if not isinstance(parsed, list):
        raise VerbError(f'{name} must decode to a JSON array')
    return parsed


def parse_vec(value: Any, name: str, length: int | None = None) -> list[float]:
    parsed = parse_json_arg(value, name)
    if not isinstance(parsed, list):
        raise VerbError(f'{name} must decode to a JSON array of numbers')
    out: list[float] = []
    for v in parsed:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise VerbError(f'{name} must contain only numbers')
        out.append(float(v))
    if length is not None and len(out) != length:
        raise VerbError(f'{name} must have {length} components, got {len(out)}')
    return out


def trunc(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 3] + '...'
