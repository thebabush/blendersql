from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import apsw

from ._meta import Column
from .datablocks import iter_named_datablocks

_PATTERN_COL = 0

# Constraint operators we claim on the hidden `pattern` column. EQ is the
# original surface; LIKE/GLOB are accepted because `compile_matcher` already
# handles `%`/`_` wildcards, and `LIKE` is the natural SQL spelling.
_PATTERN_OPS = frozenset(
    {
        apsw.SQLITE_INDEX_CONSTRAINT_EQ,
        apsw.SQLITE_INDEX_CONSTRAINT_LIKE,
        apsw.SQLITE_INDEX_CONSTRAINT_GLOB,
    }
)


class Grep:
    # Grep is a special-case vtable: it doesn't inherit from IteratorVTable
    # because it implements its own pushdown-aware apsw module protocol.
    # Metadata still needs to be on the class so the introspection layer
    # (`bsql_tables`) treats it like any other registered vtable.
    DESCRIPTION = 'Full-text-ish search across every named bpy datablock.'
    AGENT_HINT = (
        'Bind ?pattern with LIKE/GLOB on a hidden first column; returns '
        'matching datablock names plus their kind / parent. Use for ad-hoc '
        '"find anything named X" queries that span dozens of vtables.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', hint='Matched datablock name.'),
        Column('kind', 'TEXT', hint='Source vtable (objects / materials / ...).'),
        Column('parent_name', 'TEXT', hint='Parent (for nested items like bones).'),
        Column('full_name', 'TEXT', hint='Disambiguated name (kind:name).'),
    )
    RELATED: tuple[str, ...] = ()
    WRITABLE = False

    schema = (
        'CREATE TABLE grep('
        'pattern TEXT HIDDEN, '
        'name TEXT, '
        'kind TEXT, '
        'parent_name TEXT, '
        'full_name TEXT)'
    )

    def Create(
        self, db: Any, modulename: str, dbname: str, tablename: str, *args: Any
    ) -> tuple[str, _GrepVTable]:
        return self.schema, _GrepVTable()

    Connect = Create


class _GrepVTable:
    def BestIndex(self, constraints: Any, orderbys: Any) -> Any:
        used: list[Any] = [None] * len(constraints)
        argv_index = 0
        for i, (col, op) in enumerate(constraints):
            if col == _PATTERN_COL and op in _PATTERN_OPS:
                used[i] = (argv_index, True)
                argv_index += 1
        estimated_cost = 100.0 if argv_index > 0 else 1e9
        return (used, 0, None, False, estimated_cost)

    def Open(self) -> _GrepCursor:
        return _GrepCursor()

    def Disconnect(self) -> None:
        pass

    Destroy = Disconnect


class _GrepCursor:
    def __init__(self) -> None:
        self._rows: list[tuple[Any, ...]] = []
        self._i = 0

    def Filter(self, indexnum: int, indexname: str | None, constraintargs: tuple[Any, ...]) -> None:
        pattern = constraintargs[0] if constraintargs else None
        if pattern is None or not isinstance(pattern, str) or not pattern:
            self._rows = []
        else:
            self._rows = list(grep_rows(pattern))
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


def compile_matcher(pattern: str):
    if '%' in pattern:
        lowered = pattern.lower()
        return lambda name: _like_match(name.lower(), lowered)
    needle = pattern.lower()
    return lambda name: needle in name.lower()


def _like_match(text: str, pattern: str) -> bool:
    ti = 0
    pi = 0
    star = -1
    retry = 0
    while ti < len(text):
        if pi < len(pattern) and (pattern[pi] == '_' or pattern[pi] == text[ti]):
            ti += 1
            pi += 1
            continue
        if pi < len(pattern) and pattern[pi] == '%':
            star = pi
            pi += 1
            retry = ti
            continue
        if star != -1:
            pi = star + 1
            retry += 1
            ti = retry
            continue
        return False
    while pi < len(pattern) and pattern[pi] == '%':
        pi += 1
    return pi == len(pattern)


def grep_rows(pattern: str) -> Iterator[tuple[Any, Any, Any, Any, Any]]:
    match = compile_matcher(pattern)
    for kind, id_block in iter_named_datablocks():
        name = id_block.name
        if match(name):
            yield (pattern, name, kind, None, name)

        if kind == 'armature':
            for b in id_block.bones:
                if match(b.name):
                    yield (pattern, b.name, 'bone', id_block.name, f'{id_block.name}/{b.name}')

        elif kind == 'object':
            for vg in id_block.vertex_groups:
                if match(vg.name):
                    yield (
                        pattern,
                        vg.name,
                        'vertex_group',
                        id_block.name,
                        f'{id_block.name}/{vg.name}',
                    )
            for i, s in enumerate(id_block.material_slots):
                mat = s.material
                if mat is None:
                    continue
                if match(mat.name):
                    yield (
                        pattern,
                        mat.name,
                        'material_slot',
                        id_block.name,
                        f'{id_block.name}[{i}]',
                    )

        elif kind == 'grease_pencil':
            for layer in id_block.layers:
                if match(layer.name):
                    yield (
                        pattern,
                        layer.name,
                        'gp_layer',
                        id_block.name,
                        f'{id_block.name}/{layer.name}',
                    )

        tree = _node_tree_of(kind, id_block)
        if tree is not None:
            for node in tree.nodes:
                if match(node.name):
                    yield (
                        pattern,
                        node.name,
                        'node',
                        id_block.name,
                        f'{id_block.name}/{node.name}',
                    )


def _node_tree_of(kind: str, id_block: Any) -> Any:
    if kind == 'node_group':
        return id_block
    if kind in ('material', 'world', 'linestyle'):
        return getattr(id_block, 'node_tree', None)
    if kind == 'scene':
        # 5.1: scene.node_tree was replaced by scene.compositing_node_group (a NodeGroup datablock).
        return id_block.compositing_node_group if getattr(id_block, 'use_nodes', False) else None
    return None


def grep_json(pattern: str, limit: int | None = None, offset: int | None = None) -> str:
    if not isinstance(pattern, str) or not pattern:
        return json.dumps([])
    offset = int(offset) if offset is not None else 0
    limit = int(limit) if limit is not None else -1
    out: list[dict[str, Any]] = []
    skipped = 0
    for row in grep_rows(pattern):
        if skipped < offset:
            skipped += 1
            continue
        out.append(
            {
                'name': row[1],
                'kind': row[2],
                'parent_name': row[3],
                'full_name': row[4],
            }
        )
        if limit >= 0 and len(out) >= limit:
            break
    return json.dumps(out)
