from __future__ import annotations

from typing import Any

from ..functions import audit
from .base import IteratorVTable


class SessionLog(IteratorVTable):
    schema = (
        'CREATE TABLE session_log('
        'ts REAL, '
        'op TEXT, '
        'input TEXT, '
        'success INTEGER, '
        'duration_ms REAL, '
        'error_type TEXT)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        return list(audit.snapshot())
