"""Typed result envelope for `engine.execute()`.

The wire format is the JSON `to_dict()` emits — success and failure carry
different keys, matching the historical loose-dict shape exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class QueryResult:
    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    duration_ms: float = 0.0
    error: str | None = None
    error_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.ok:
            return {
                'ok': True,
                'columns': self.columns,
                'rows': self.rows,
                'row_count': self.row_count,
                'duration_ms': self.duration_ms,
            }
        return {
            'ok': False,
            'error': self.error,
            'error_type': self.error_type,
            'duration_ms': self.duration_ms,
        }
