from __future__ import annotations

import time
from collections import deque

_MAX_INPUT = 200
_log: deque[tuple[float, str, str, int, float, str | None]] = deque(maxlen=256)


def log(
    op: str, input_text: str, success: bool, duration_ms: float, error_type: str | None
) -> None:
    truncated = input_text if len(input_text) <= _MAX_INPUT else input_text[:_MAX_INPUT]
    _log.append((time.time(), op, truncated, 1 if success else 0, duration_ms, error_type))


def snapshot() -> list[tuple[float, str, str, int, float, str | None]]:
    return list(_log)


def clear() -> None:
    _log.clear()
