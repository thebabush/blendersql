"""Introspection vtables — query the blendersql surface from SQL.

`bsql_tables` exposes the live registry of vtables along with the metadata
each class declares on itself (DESCRIPTION, AGENT_HINT, WRITABLE, column
count, related tables). `bsql_columns` zooms in one level: one row per
declared column, with type / writability / identifier flags / hint.
`bsql_related` is the JOIN-friendly long form of `bsql_tables.related` —
one row per (a, b) related-table edge. Lets agents ask one question
instead of N describe_table calls.

This is the entry point of the metadata pipeline tracked in issue #5: as
each vtable migrates its class-attr metadata, all three introspection
vtables instantly reflect the change with zero hand-maintained list to
keep in sync.
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
        'with writability + a one-liner. Avoid a describe_table spree by joining hints from here. '
        'The `related` column is a comma-joined convenience; for JOINable form use bsql_related.'
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
    RELATED: tuple[str, ...] = ('bsql_columns', 'bsql_related')
    schema = (
        'CREATE TABLE bsql_tables('
        'name TEXT, '
        'writable INTEGER, '
        'description TEXT, '
        'agent_hint TEXT, '
        'column_count INTEGER, '
        'related TEXT)'
    )

    # Instance-level snapshot cache keyed on registry_version(). apsw keeps one
    # source instance alive per `_bind`, reused across cursors, so the cache
    # survives between queries. No locking: blendersql runs all SQL on the
    # main thread (see bridge/main_thread.py).
    def __init__(self) -> None:
        self._cached_version: int = -1
        self._cached_rows: list[tuple[Any, ...]] = []

    def snapshot(self) -> list[tuple[Any, ...]]:
        from . import registry, registry_version

        v = registry_version()
        if v == self._cached_version:
            return self._cached_rows
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
        self._cached_rows = rows
        self._cached_version = v
        return self._cached_rows


class BsqlColumns(IteratorVTable):
    """One row per declared column across every registered vtable."""

    table_name = 'bsql_columns'
    DESCRIPTION = 'Per-column metadata across every registered vtable.'
    AGENT_HINT = (
        'Use to discover writable columns, identifiers, and per-column hints without '
        'PRAGMA table_info on every table. Filter with `WHERE "table"=?` — `table` is a '
        'SQL keyword so it must be quoted. `pk` is the write-side identifier subset; '
        '`identifier` is the natural row-key on any table (read-only or writable). '
        '`insert_only` marks columns settable on INSERT but frozen on UPDATE.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('table', 'TEXT', hint='Owning bsql_tables.name (SQL keyword — quote in WHERE).'),
        Column('name', 'TEXT', hint='Column name within the owning table.'),
        Column('type', 'TEXT', hint='SQLite affinity: TEXT / INTEGER / REAL / BLOB / ANY.'),
        Column('writable', 'INTEGER', hint='Boolean as 0/1; 1 if UPDATE may write this column.'),
        Column(
            'pk',
            'INTEGER',
            hint='Boolean as 0/1; 1 if this column is the row identifier for writes.',
        ),
        Column(
            'identifier',
            'INTEGER',
            hint='Boolean as 0/1; 1 if this column is part of the natural row-key tuple.',
        ),
        Column(
            'insert_only',
            'INTEGER',
            hint='Boolean as 0/1; 1 if settable on INSERT but rejected on UPDATE.',
        ),
        Column('hint', 'TEXT', hint='One-line agent-facing description; may be empty.'),
    )
    RELATED: tuple[str, ...] = ('bsql_tables', 'bsql_related')
    schema = (
        'CREATE TABLE bsql_columns('
        '"table" TEXT, '
        'name TEXT, '
        'type TEXT, '
        'writable INTEGER, '
        'pk INTEGER, '
        'identifier INTEGER, '
        'insert_only INTEGER, '
        'hint TEXT)'
    )

    # Instance-level cache; see BsqlTables for the rationale.
    def __init__(self) -> None:
        self._cached_version: int = -1
        self._cached_rows: list[tuple[Any, ...]] = []

    def snapshot(self) -> list[tuple[Any, ...]]:
        from . import registry, registry_version

        v = registry_version()
        if v == self._cached_version:
            return self._cached_rows
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
                        int(col.identifier),
                        int(col.insert_only),
                        col.hint,
                    )
                )
        self._cached_rows = rows
        self._cached_version = v
        return self._cached_rows


class BsqlRelated(IteratorVTable):
    """One row per (a, b) related-table edge across the registry."""

    table_name = 'bsql_related'
    DESCRIPTION = 'Long form of bsql_tables.related: one row per (table, related-table) edge.'
    AGENT_HINT = (
        'JOIN-friendly form of bsql_tables.related. Each row is a single edge a -> b; the '
        'set is kept symmetric (a,b present iff b,a present). Use to discover neighbouring '
        "tables: SELECT b FROM bsql_related WHERE a='objects'."
    )
    COLUMNS: tuple[Column, ...] = (
        Column('a', 'TEXT', identifier=True, hint='Source table (bsql_tables.name).'),
        Column('b', 'TEXT', identifier=True, hint='Related table (bsql_tables.name).'),
    )
    RELATED: tuple[str, ...] = ('bsql_tables', 'bsql_columns')
    schema = 'CREATE TABLE bsql_related(a TEXT, b TEXT)'

    def __init__(self) -> None:
        self._cached_version: int = -1
        self._cached_rows: list[tuple[Any, ...]] = []

    def snapshot(self) -> list[tuple[Any, ...]]:
        from . import registry, registry_version

        v = registry_version()
        if v == self._cached_version:
            return self._cached_rows
        reg = registry()
        rows: list[tuple[Any, ...]] = []
        for name in sorted(reg):
            inst = reg[name]
            for other in inst.RELATED:
                rows.append((name, other))
        rows.sort()
        self._cached_rows = rows
        self._cached_version = v
        return self._cached_rows
