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


# --- scene_objects --------------------------------------------------------
#
# Fixture layout (see tests/fixtures/build_fixture.py):
#   Scene:     Cube, Rig, Sun, Cam, Path, Title   (6 objects)
#   Scene.002: Cube (shared), Outer > Inner > NestedEmpty   (2 objects)
# Cube is linked into both scenes.


def test_scene_objects_group_by_scene(client) -> None:
    r = client.query('SELECT scene, COUNT(*) FROM scene_objects GROUP BY scene ORDER BY scene')
    assert r['ok'], r
    counts = {row[0]: row[1] for row in r['rows']}
    assert counts == {'Scene': 6, 'Scene.002': 2}, counts


def test_scene_objects_known_object_in_main_scene(client) -> None:
    r = client.query("SELECT object, type FROM scene_objects WHERE scene='Scene' AND object='Cube'")
    assert r['ok'], r
    assert r['rows'] == [['Cube', 'MESH']], r['rows']


def test_scene_objects_shared_object_appears_in_both_scenes(client) -> None:
    r = client.query("SELECT scene FROM scene_objects WHERE object='Cube' ORDER BY scene")
    assert r['ok'], r
    scenes_with_cube = [row[0] for row in r['rows']]
    assert scenes_with_cube == ['Scene', 'Scene.002'], scenes_with_cube


def test_scene_objects_where_scene_filter(client) -> None:
    r = client.query("SELECT object FROM scene_objects WHERE scene='Scene.002' ORDER BY object")
    assert r['ok'], r
    objs = [row[0] for row in r['rows']]
    assert objs == ['Cube', 'NestedEmpty'], objs


def test_scene_objects_nested_collection_object_included(client) -> None:
    # NestedEmpty is in Inner, which is a child of Outer, which is a child of
    # Scene.002's master collection. all_objects must recurse to surface it.
    r = client.query(
        'SELECT scene, type, hide_viewport, hide_render FROM scene_objects '
        "WHERE object='NestedEmpty'"
    )
    assert r['ok'], r
    assert r['rows'] == [['Scene.002', 'EMPTY', 0, 0]], r['rows']


# ---------------------------------------------------------------------------
# bsql_tables — introspection vtable surfaces class-attr metadata


def test_bsql_tables_columns(client) -> None:
    r = client.query('PRAGMA table_info(bsql_tables)')
    assert r['ok'], r
    cols = [row[1] for row in r['rows']]
    assert cols == ['name', 'writable', 'description', 'agent_hint', 'column_count', 'related']


def test_bsql_tables_lists_every_registered_table(client) -> None:
    # bsql_tables should mirror sqlite_master's table list exactly.
    a = client.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    b = client.query('SELECT name FROM bsql_tables ORDER BY name')
    assert a['ok'] and b['ok'], (a, b)
    assert [row[0] for row in a['rows']] == [row[0] for row in b['rows']]


def test_bsql_tables_objects_metadata(client) -> None:
    r = client.query(
        "SELECT name, writable, description, column_count FROM bsql_tables WHERE name='objects'"
    )
    assert r['ok'], r
    assert len(r['rows']) == 1, r['rows']
    name, writable, description, column_count = r['rows'][0]
    assert name == 'objects'
    assert writable == 1
    assert 'Scene objects' in description
    assert column_count == 17


def test_bsql_tables_writability_matches_class_hierarchy(client) -> None:
    # The writable set is whatever the live registry reports — that's the
    # whole point of bsql_tables (no more hardcoded drift). Sanity-check a
    # handful of known cases. Note: `node_trees` itself is read-only;
    # `node_inputs` is the writable vtable in that module.
    r = client.query(
        'SELECT name, writable FROM bsql_tables '
        "WHERE name IN ('objects','materials','modifiers','node_inputs',"
        "'node_trees','welcome','grep','session_log','bsql_tables') "
        'ORDER BY name'
    )
    assert r['ok'], r
    by_name = dict(r['rows'])
    assert by_name['objects'] == 1
    assert by_name['materials'] == 1
    assert by_name['modifiers'] == 1
    assert by_name['node_inputs'] == 1
    assert by_name['node_trees'] == 0
    assert by_name['welcome'] == 0
    assert by_name['grep'] == 0
    assert by_name['session_log'] == 0
    assert by_name['bsql_tables'] == 0


def test_bsql_tables_unmigrated_classes_have_empty_metadata(client) -> None:
    # Sanity: classes that haven't been migrated to the COLUMNS metadata yet
    # still appear, just with column_count=0 and empty description. Once the
    # rest of the migration lands this test goes away.
    r = client.query("SELECT description, column_count FROM bsql_tables WHERE name='collections'")
    assert r['ok'], r
    assert r['rows'][0] == ['', 0]
