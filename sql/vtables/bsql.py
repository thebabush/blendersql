"""Introspection vtables — query the blendersql surface from SQL.

`bsql_tables` exposes the live registry of vtables along with the metadata
each class declares on itself (DESCRIPTION, AGENT_HINT, WRITABLE, column
count, related tables). Lets agents ask one question instead of N
describe_table calls.

This is the entry point of the metadata pipeline tracked in issue #5: as
each vtable migrates its class-attr metadata, bsql_tables instantly reflects
the change with zero hand-maintained list to keep in sync.

`bsql_columns` (planned) will surface the per-column shape; until then,
`describe_table` / PRAGMA cover that need.
"""

from __future__ import annotations

from typing import Any

from .base import IteratorVTable


class BsqlTables(IteratorVTable):
    """One row per registered vtable.

    Columns:
        name           — table name as registered in the engine.
        writable       — 1 if the class is writable (UPDATE/INSERT/DELETE), else 0.
        description    — one-line agent-facing summary.
        agent_hint     — when to reach for this table; common JOINs; gotchas.
        column_count   — number of columns declared via the COLUMNS metadata
                         (0 if the class hasn't been migrated yet).
        related        — comma-separated list of related table names, or ''.
    """

    table_name = 'bsql_tables'
    DESCRIPTION = 'Self-describing catalog of every blendersql vtable.'
    AGENT_HINT = (
        'Call this FIRST when orienting against an unfamiliar fixture. One row per table, '
        'with writability + a one-liner. Avoid a describe_table spree by joining hints from here.'
    )
    schema = (
        'CREATE TABLE bsql_tables('
        'name TEXT, '
        'writable INTEGER, '
        'description TEXT, '
        'agent_hint TEXT, '
        'column_count INTEGER, '
        'related TEXT)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        from . import registry

        reg = registry()
        rows: list[tuple[Any, ...]] = []
        for name in sorted(reg):
            inst = reg[name]
            rows.append(
                (
                    name,
                    int(inst.WRITABLE),
                    inst.DESCRIPTION,
                    inst.AGENT_HINT,
                    len(inst.COLUMNS),
                    ','.join(inst.RELATED),
                )
            )
        return rows
