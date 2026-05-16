"""Vtable metadata for self-describing introspection.

Class-attribute conventions live on the base classes in `base.py`:

    class Foo(IteratorVTable):
        DESCRIPTION = "One-line, agent-facing."
        AGENT_HINT  = "When to reach for this table; common JOINs; gotchas."
        COLUMNS = (Column(...), Column(...), ...)   # immutable tuple
        RELATED = ('other_table', ...)              # immutable tuple
        # WRITABLE is set on the base class (False on IteratorVTable,
        # True on WritableSnapshotVTable) — override only for special cases.

`VTableMeta` is the structural type the introspection layer relies on; both
`IteratorVTable` and `WritableSnapshotVTable` satisfy it after the defaults
on `base.py` are in place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Column:
    """Per-column metadata.

    Attributes:
        name: SQL column name.
        type: SQLite affinity — 'TEXT' / 'REAL' / 'INTEGER' / 'BLOB' / 'ANY'.
        writable: True when UPDATE may write this column. INSERT-only columns
            (see `insert_only`) deliberately leave this False.
        pk: True when this column functions as a stable identifier in writes.
            Implies `identifier=True`; only meaningful on writable tables.
        identifier: True when this column is part of the natural row-key tuple
            of its table. Set on both read-only and writable tables — pk is the
            writable-side subset.
        insert_only: True when the column accepts a value on INSERT but rejects
            UPDATE changes (datablock-restructure cases). Implies writable=False
            on UPDATE — keep `writable=False` and set `insert_only=True`.
        hint: One-line agent-facing description.
    """

    name: str
    type: str
    writable: bool = False
    pk: bool = False
    identifier: bool = False
    insert_only: bool = False
    hint: str = ''


@runtime_checkable
class VTableMeta(Protocol):
    """Structural type of every registered vtable instance.

    Both `IteratorVTable` and `WritableSnapshotVTable` declare these as class
    attrs with safe defaults, so any subclass automatically satisfies this
    Protocol — no need for `getattr` fallbacks in introspection code.
    """

    DESCRIPTION: str
    AGENT_HINT: str
    COLUMNS: tuple[Column, ...]
    RELATED: tuple[str, ...]
    WRITABLE: bool
