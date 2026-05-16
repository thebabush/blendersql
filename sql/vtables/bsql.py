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

from ._meta import Column
from .base import IteratorVTable


class BsqlTables(IteratorVTable):
    """One row per registered vtable; columns documented on COLUMNS below."""

    table_name = 'bsql_tables'
    DESCRIPTION = 'Self-describing catalog of every blendersql vtable.'
    AGENT_HINT = (
        'Call this FIRST when orienting against an unfamiliar fixture. One row per table, '
        'with writability + a one-liner. Avoid a describe_table spree by joining hints from here.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', hint='Table name as registered in the engine.'),
        Column('writable', 'INTEGER', hint='Boolean as 0/1; 1 if UPDATE/INSERT/DELETE allowed.'),
        Column('description', 'TEXT', hint='One-line agent-facing summary of the table.'),
        Column('agent_hint', 'TEXT', hint='When to reach for this table; common JOINs; gotchas.'),
        Column('column_count', 'INTEGER', hint='Number of declared columns in COLUMNS metadata.'),
        Column(
            'related', 'TEXT', hint='Comma-separated list of related table names (may be empty).'
        ),
    )
    RELATED: tuple[str, ...] = ('bsql_columns',)
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
    """One row per declared column across every registered vtable."""

    table_name = 'bsql_columns'
    DESCRIPTION = 'Per-column metadata across every registered vtable.'
    AGENT_HINT = (
        'Use to discover writable columns, primary keys, and per-column hints without '
        'PRAGMA table_info on every table. Filter with `WHERE "table"=?` — `table` is a '
        'SQL keyword so it must be quoted. Every registered table is covered now that '
        'Phase-1 migration is complete.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('table', 'TEXT', hint='Owning bsql_tables.name (SQL keyword — quote in WHERE).'),
        Column('name', 'TEXT', hint='Column name within the owning table.'),
        Column('type', 'TEXT', hint='SQLite affinity: TEXT / INTEGER / REAL / BLOB / ANY.'),
        Column(
            'writable', 'INTEGER', hint='Boolean as 0/1; 1 if UPDATE/INSERT may write this column.'
        ),
        Column(
            'pk',
            'INTEGER',
            hint='Boolean as 0/1; 1 if this column is the row identifier for writes.',
        ),
        Column('hint', 'TEXT', hint='One-line agent-facing description; may be empty.'),
    )
    RELATED: tuple[str, ...] = ('bsql_tables',)
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
