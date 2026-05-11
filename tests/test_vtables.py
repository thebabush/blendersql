"""Smoke tests for every registered virtual table.

Parametrized over EXPECTED (the canonical static list of 75 tables). A
separate guard test asserts the live `sqlite_master` view matches that list
so the two never drift silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fixtures.expected import EXPECTED

ALL_TABLES: list[str] = sorted(EXPECTED.keys())


def test_table_inventory_matches_expected(client) -> None:
    r = client.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    assert r['ok'], r
    live = [row[0] for row in r['rows']]
    missing = sorted(set(ALL_TABLES) - set(live))
    extra = sorted(set(live) - set(ALL_TABLES))
    assert not missing and not extra, (
        f'sqlite_master drift: missing in live={missing}, extra in live={extra}'
    )


@pytest.mark.parametrize('table', ALL_TABLES)
def test_table_queryable(client, table: str) -> None:
    r = client.query(f'SELECT * FROM {table} LIMIT 1')
    assert r['ok'], f'{table} failed: {r}'


# session_log accumulates as tests fire bpy_eval/bpy_exec/bpy_op calls; images
# gains a 'Render Result' datablock the first time anything renders (render /
# render_object). Both counts are session-order-dependent.
_NON_DETERMINISTIC: frozenset[str] = frozenset({'session_log', 'images'})


@pytest.mark.parametrize('table', ALL_TABLES)
def test_table_count(client, table: str) -> None:
    r = client.query(f'SELECT COUNT(*) FROM {table}')
    assert r['ok'], f'{table} failed: {r}'
    n = r['rows'][0][0]
    assert isinstance(n, int) and n >= 0, f'{table}: non-integer count {n!r}'
    if table in _NON_DETERMINISTIC:
        return
    assert n == EXPECTED[table], f'{table}: expected {EXPECTED[table]}, got {n}'


def test_users_column_on_id_datablock_vtables(client) -> None:
    # lights / cameras / texts / shape_keys gained a `users` column for parity
    # with the other ID-datablock vtables.
    for table in ('lights', 'cameras', 'texts', 'shape_keys'):
        r = client.query(f'SELECT name, users FROM {table}')
        assert r['ok'], f'{table}: {r}'
        for name, users in r['rows']:
            assert isinstance(users, int) and users >= 1, f'{table}.{name}: users={users!r}'
