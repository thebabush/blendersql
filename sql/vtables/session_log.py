from __future__ import annotations

from typing import Any

from ..functions import audit
from ._meta import Column
from .base import IteratorVTable


class SessionLog(IteratorVTable):
    DESCRIPTION = 'In-memory audit ring of side-effecting calls (bpy_eval/bpy_exec/bpy_op/verbs).'
    AGENT_HINT = (
        'Append-only ring buffer scoped to the current engine session — resets on engine init. '
        'Each row is one bpy_eval / bpy_exec / bpy_op / verb call with timing + outcome; SELECT '
        'to see what side-effecting calls have run this session. `input` is truncated; '
        '`error_type` is the exception class name (NULL on success).'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('ts', 'REAL', hint='Wall-clock timestamp (time.time() seconds since epoch).'),
        Column('op', 'TEXT', hint='Call kind: bpy_eval / bpy_exec / bpy_op / a verb name.'),
        Column('input', 'TEXT', hint='Truncated payload (expression / source / op id / args).'),
        Column(
            'success', 'INTEGER', hint='Boolean as 0/1; 1 if the call returned without raising.'
        ),
        Column('duration_ms', 'REAL', hint='Elapsed wall-clock milliseconds.'),
        Column('error_type', 'TEXT', hint='Exception class name on failure; NULL on success.'),
    )
    RELATED: tuple[str, ...] = ()
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
