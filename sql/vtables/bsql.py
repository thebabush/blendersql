"""Introspection vtables — query the blendersql surface from SQL.

`bsql_tables` exposes the live registry of vtables along with the metadata
each class declares on itself (DESCRIPTION, AGENT_HINT, WRITABLE, column
count, related tables). `bsql_columns` zooms in one level: one row per
declared column, with type / writability / hint. Lets agents ask one
question instead of N describe_table calls.

This is the entry point of the metadata pipeline tracked in issue #5: as
each vtable migrates its class-attr metadata, both introspection vtables
instantly reflect the change with zero hand-maintained list to keep in sync.
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


class BsqlColumns(IteratorVTable):
    """One row per declared column across every migrated vtable.

    Skips tables whose COLUMNS tuple is still empty (not yet migrated to the
    class-attr metadata); those remain queryable via PRAGMA table_info().

    Columns:
        table     — vtable name as registered in the engine.
        name      — column name.
        type      — SQLite affinity (TEXT / INTEGER / REAL / BLOB / ANY).
        writable  — 1 if UPDATE/INSERT may write this column, else 0.
        pk        — 1 if this column is the row identifier for writes.
        hint      — one-line agent-facing description (may be empty).
    """

    table_name = 'bsql_columns'
    DESCRIPTION = 'Per-column metadata across every migrated vtable.'
    AGENT_HINT = (
        'Use to discover writable columns, primary keys, and per-column hints without '
        'PRAGMA table_info on every table. Filter with `WHERE "table"=?` — `table` is a '
        'SQL keyword so it must be quoted. Unmigrated tables have zero rows here; fall '
        'back to PRAGMA for those.'
    )
    schema = (
        'CREATE TABLE bsql_columns('
        '"table" TEXT, '
        'name TEXT, '
        'type TEXT, '
        'writable INTEGER, '
        'pk INTEGER, '
        'hint TEXT)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        from . import registry

        reg = registry()
        rows: list[tuple[Any, ...]] = []
        for table_name in sorted(reg):
            inst = reg[table_name]
            if not inst.COLUMNS:
                continue
            for col in inst.COLUMNS:
                rows.append(
                    (
                        table_name,
                        col.name,
                        col.type,
                        int(col.writable),
                        int(col.pk),
                        col.hint,
                    )
                )
        return rows
