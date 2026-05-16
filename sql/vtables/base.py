"""Base classes for snapshot-based vtables.

Two flavours:

* `IteratorVTable` — read-only. Subclass defines `schema` + `snapshot()`.
* `WritableSnapshotVTable` — adds INSERT/UPDATE/DELETE. Subclass defines
  `schema`, `_snapshot()` returning `(rows, identifiers)` where
  `identifiers[i]` is the opaque handle the subclass needs to resolve back
  to bpy state for row i, and `_apply_insert(fields) -> identifier`,
  `_apply_update(identifier, fields)`, `_apply_delete(identifier)`.

On every cursor open (each SQL query) we take a fresh snapshot. bpy.data
is live, but our vtables are *consistent within a query* — we never observe
bpy mutating mid-cursor. For large tables this is intentionally simple;
push-down can be added later table-by-table.
"""

from __future__ import annotations

from typing import Any

from ._meta import Column


class IteratorVTable:
    schema: str = ''

    # Agent-facing metadata. Empty defaults so existing subclasses stay valid
    # while the per-class migration happens. Populate as you go; query via
    # the `bsql_tables` / `bsql_columns` introspection vtables. See _meta.py.
    DESCRIPTION: str = ''
    AGENT_HINT: str = ''
    COLUMNS: tuple[Column, ...] = ()
    RELATED: tuple[str, ...] = ()
    WRITABLE: bool = False
    # Primary domain bucket — used by the bsql_tables introspection layer and
    # the regen script's `vtables-domain=<x>` marker to filter the catalog into
    # per-area lists. Empty default keeps existing tests happy until each
    # subclass declares its slice; CI guards in test_vtables.py make sure no
    # registered vtable ships with an empty DOMAIN.
    DOMAIN: str = ''

    def snapshot(self) -> list[tuple[Any, ...]]:
        raise NotImplementedError

    def Create(
        self, db: Any, modulename: str, dbname: str, tablename: str, *args: Any
    ) -> tuple[str, Any]:
        return self.schema, _VTable(self)

    Connect = Create


class _VTable:
    def __init__(self, source: IteratorVTable) -> None:
        self._source = source

    def BestIndex(self, constraints: Any, orderbys: Any) -> Any:
        return None

    def Open(self) -> _Cursor:
        return _Cursor(self._source.snapshot())

    def Disconnect(self) -> None:
        pass

    Destroy = Disconnect


class _Cursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self._i = 0

    def Filter(self, *args: Any, **kw: Any) -> None:
        self._i = 0

    def Eof(self) -> bool:
        return self._i >= len(self._rows)

    def Column(self, n: int) -> Any:
        return self._rows[self._i][n]

    def Next(self) -> None:
        self._i += 1

    def Rowid(self) -> int:
        return self._i

    def Close(self) -> None:
        pass


class WritableSnapshotVTable:
    """Base for writable vtables that snapshot on every cursor open.

    Subclasses override `_snapshot`, `_apply_insert`, `_apply_update`,
    `_apply_delete`. Identifiers are stashed on the vtable from the cursor's
    snapshot — safe because apsw runs statements serially on the main thread.
    """

    schema: str = ''
    table_name: str = ''

    # Agent-facing metadata. Same convention as IteratorVTable but WRITABLE
    # defaults to True for the writable base.
    DESCRIPTION: str = ''
    AGENT_HINT: str = ''
    COLUMNS: tuple[Column, ...] = ()
    RELATED: tuple[str, ...] = ()
    WRITABLE: bool = True
    # See IteratorVTable.DOMAIN for the convention. Same empty default so the
    # base class works for in-progress migrations.
    DOMAIN: str = ''

    def _snapshot(self) -> tuple[list[tuple[Any, ...]], list[Any]]:
        raise NotImplementedError

    def _apply_insert(self, fields: tuple[Any, ...]) -> Any:
        raise NotImplementedError

    def _apply_update(self, identifier: Any, fields: tuple[Any, ...]) -> None:
        raise NotImplementedError

    def _apply_delete(self, identifier: Any) -> None:
        raise NotImplementedError

    def _describe_identifier(self, identifier: Any) -> str:
        return str(identifier)

    def Create(
        self, db: Any, modulename: str, dbname: str, tablename: str, *args: Any
    ) -> tuple[str, _WritableVTable]:
        return self.schema, _WritableVTable(self)

    Connect = Create


class _WritableVTable:
    def __init__(self, source: WritableSnapshotVTable) -> None:
        self._source = source
        self._identifiers: list[Any] = []

    def BestIndex(self, constraints: Any, orderbys: Any) -> Any:
        return None

    def Open(self) -> _Cursor:
        rows, identifiers = self._source._snapshot()
        # Single-statement cursor lifecycle: the vtable borrows the cursor's
        # identifier list so xUpdate (called between Open() and Close()) can
        # map rowid back to the bpy handle. apsw runs one statement at a time
        # on a connection so this is safe today.
        self._identifiers = identifiers
        return _Cursor(rows)

    def Disconnect(self) -> None:
        pass

    Destroy = Disconnect

    def UpdateChangeRow(self, oldrowid: int, newrowid: int, fields: tuple[Any, ...]) -> None:
        ident = self._identifiers[oldrowid]
        self._source._apply_update(ident, fields)
        import bpy

        bpy.ops.ed.undo_push(
            message=f'blendersql: update {self._source.table_name} ({self._source._describe_identifier(ident)})'
        )

    def UpdateInsertRow(self, rowid: int | None, fields: tuple[Any, ...]) -> int:
        ident = self._source._apply_insert(fields)
        # apsw's contract: return the new rowid; subsequent ops on this row in
        # the same cursor look it up via `_identifiers[rowid]` (see
        # UpdateChangeRow / UpdateDeleteRow). Append first, then return the
        # index of the just-appended entry. Previously this returned
        # `len(_identifiers)` *without* appending — one past the end.
        self._identifiers.append(ident)
        import bpy

        bpy.ops.ed.undo_push(
            message=f'blendersql: insert {self._source.table_name} ({self._source._describe_identifier(ident)})'
        )
        return len(self._identifiers) - 1

    def UpdateDeleteRow(self, rowid: int) -> None:
        ident = self._identifiers[rowid]
        self._source._apply_delete(ident)
        import bpy

        bpy.ops.ed.undo_push(
            message=f'blendersql: delete {self._source.table_name} ({self._source._describe_identifier(ident)})'
        )
