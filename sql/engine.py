"""apsw engine + vtable registration.

The engine owns a single apsw Connection on an in-memory database. All vtables
are read against this connection. apsw connections are thread-checked by
default — every execute() call must happen on the main thread, which is the
job of bridge.run_on_main.
"""

from __future__ import annotations

import time
from typing import Any

import apsw

from .result import QueryResult

_engine: Engine | None = None


class Engine:
    def __init__(self) -> None:
        self.conn: apsw.Connection = apsw.Connection(':memory:')

    def execute(self, sql: str) -> QueryResult:
        start = time.monotonic()
        try:
            cursor = self.conn.execute(sql)
            columns = _peek_columns(cursor)
            rows = [_jsonify(r) for r in cursor]
            # Empty SELECTs strand the cursor in 'complete' state before we can
            # grab description; non-empty rows let us peek before draining.
            return QueryResult(
                ok=True,
                columns=columns,
                rows=rows,
                row_count=len(rows),
                duration_ms=_ms_since(start),
            )
        except apsw.Error as exc:
            return QueryResult(
                ok=False,
                error=str(exc),
                error_type=type(exc).__name__,
                duration_ms=_ms_since(start),
            )


def initialize() -> Engine:
    global _engine
    if _engine is not None:
        return _engine
    _engine = Engine()
    from .functions import register_all as register_functions
    from .vtables import register_all as register_vtables

    register_vtables(_engine)
    register_functions(_engine)
    return _engine


def shutdown() -> None:
    global _engine
    if _engine is None:
        return
    _engine.conn.close()
    _engine = None


def get() -> Engine:
    if _engine is None:
        raise RuntimeError('engine not initialised')
    return _engine


def _ms_since(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 2)


def _jsonify(row: tuple) -> list[Any]:
    return [v.hex() if isinstance(v, (bytes, bytearray)) else v for v in row]


def _peek_columns(cursor: apsw.Cursor) -> list[str]:
    try:
        desc = cursor.description
    except apsw.ExecutionCompleteError:
        return []
    return [d[0] for d in desc] if desc else []
