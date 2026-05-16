"""Smoke tests for every registered virtual table.

Parametrized over EXPECTED (the canonical static row-count fixture; 76 tables
today, bsql_tables/bsql_columns excluded because their counts are asserted
dynamically below). A separate guard test combines EXPECTED with the two
introspection tables and asserts the union exactly matches `sqlite_master`,
so the two never drift silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fixtures.expected import EXPECTED

# bsql_tables / bsql_columns are excluded from EXPECTED because their counts
# track the live registry — covered by dedicated dynamic tests below. Keep
# them in the inventory's expected set so drift is still detected here.
_INTROSPECTION_TABLES: frozenset[str] = frozenset({'bsql_tables', 'bsql_columns'})

ALL_TABLES: list[str] = sorted(EXPECTED.keys())
ALL_REGISTERED_TABLES: list[str] = sorted(set(EXPECTED.keys()) | _INTROSPECTION_TABLES)


def test_table_inventory_matches_expected(client) -> None:
    r = client.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    assert r['ok'], r
    live = [row[0] for row in r['rows']]
    expected_set = set(ALL_REGISTERED_TABLES)
    missing = sorted(expected_set - set(live))
    extra = sorted(set(live) - expected_set)
    assert not missing and not extra, (
        f'sqlite_master drift: missing in live={missing}, extra in live={extra}'
    )


@pytest.mark.parametrize('table', ALL_REGISTERED_TABLES)
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


def test_every_bsql_table_has_metadata(client) -> None:
    # Phase-1 regression guard: description must be a real one-liner (>= 10
    # chars after trim — catches 'TODO', single tokens, whitespace), agent_hint
    # must say something (>= 20 chars), and the table must declare columns. If
    # a future vtable lands without filling these in, this surfaces here —
    # don't loosen the test; fix the class's metadata.
    r = client.query(
        'SELECT name, description, agent_hint, column_count FROM bsql_tables '
        'WHERE LENGTH(TRIM(description)) < 10 '
        'OR LENGTH(TRIM(agent_hint)) < 20 '
        'OR column_count=0 '
        'ORDER BY name'
    )
    assert r['ok'], r
    assert r['rows'] == [], f'tables with weak/missing metadata: {r["rows"]}'


# ---------------------------------------------------------------------------
# bsql_columns — per-column introspection over the same metadata pipeline


def test_bsql_columns_schema(client) -> None:
    r = client.query('PRAGMA table_info(bsql_columns)')
    assert r['ok'], r
    cols = [row[1] for row in r['rows']]
    assert cols == ['table', 'name', 'type', 'writable', 'pk', 'hint']


def test_bsql_columns_lists_objects_columns(client) -> None:
    r = client.query('SELECT name FROM bsql_columns WHERE "table"=\'objects\' ORDER BY rowid')
    assert r['ok'], r
    names = [row[0] for row in r['rows']]
    assert names == [
        'name',
        'type',
        'parent',
        'data',
        'collection',
        'hide_viewport',
        'hide_render',
        'rotation_mode',
        'location_x',
        'location_y',
        'location_z',
        'rotation_x',
        'rotation_y',
        'rotation_z',
        'scale_x',
        'scale_y',
        'scale_z',
    ]
    assert len(names) == 17


def test_bsql_columns_writability_propagates(client) -> None:
    r = client.query(
        'SELECT name, writable FROM bsql_columns '
        "WHERE \"table\"='objects' AND name IN ('name','type','parent','data','location_x')"
    )
    assert r['ok'], r
    by_name = dict(r['rows'])
    assert by_name['name'] == 1
    assert by_name['type'] == 0
    assert by_name['parent'] == 1
    assert by_name['data'] == 0
    assert by_name['location_x'] == 1


def test_bsql_columns_covers_every_registered_table(client) -> None:
    # Phase-1 complete: every registered table is now migrated, so the set of
    # tables in bsql_columns must exactly equal the set in bsql_tables.
    a = client.query('SELECT DISTINCT "table" FROM bsql_columns')
    b = client.query('SELECT name FROM bsql_tables')
    assert a['ok'] and b['ok'], (a, b)
    in_columns = {row[0] for row in a['rows']}
    registered = {row[0] for row in b['rows']}
    assert in_columns == registered, (
        f'missing from bsql_columns: {registered - in_columns}; '
        f'unexpected in bsql_columns: {in_columns - registered}'
    )


def test_bsql_tables_count_matches_registry(client) -> None:
    # bsql_tables surfaces every registered vtable (including itself); the row
    # count must match sqlite_master. No hand-maintained number.
    expected = client.query("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
    actual = client.query('SELECT COUNT(*) FROM bsql_tables')
    assert expected['ok'] and actual['ok'], (expected, actual)
    assert actual['rows'][0][0] == expected['rows'][0][0], (expected, actual)


def test_bsql_columns_count_matches_sum_of_metadata(client) -> None:
    # SUM(column_count) FROM bsql_tables must equal COUNT(*) FROM bsql_columns —
    # internally consistent without anchoring to a hardcoded total.
    a = client.query('SELECT SUM(column_count) FROM bsql_tables')
    b = client.query('SELECT COUNT(*) FROM bsql_columns')
    assert a['ok'] and b['ok'], (a, b)
    assert a['rows'][0][0] == b['rows'][0][0], (a, b)


# Tables whose `schema` declares HIDDEN columns that intentionally don't appear
# in `COLUMNS` metadata. Today: grep's `pattern` is a HIDDEN bind column that
# drives the search; it's exposed in the schema for the apsw module protocol
# but doesn't fit the "user-visible column" mental model COLUMNS describes.
_SCHEMA_HIDDEN_EXCEPTIONS: dict[str, frozenset[str]] = {
    'grep': frozenset({'pattern'}),
}


# Writable vtables (WRITABLE=1) that legitimately expose zero writable columns.
# Today only gp_strokes is in this set — it's DELETE-only (INSERT/UPDATE both
# raise; use gp_add_stroke or bpy_exec for inserts). If a new table joins this
# allowlist, document the write surface in its AGENT_HINT and add it here.
_DELETE_ONLY_TABLES: frozenset[str] = frozenset({'gp_strokes'})


def test_pk_implies_writable_table(client) -> None:
    # Column.pk means "stable identifier for writes" (see _meta.py). It only
    # makes sense on writable vtables. If pk=1 appears on a read-only table
    # the conventions have drifted — fix the class, don't loosen the test.
    r = client.query(
        'SELECT c."table", c.name FROM bsql_columns c '
        'JOIN bsql_tables t ON t.name=c."table" '
        'WHERE c.pk=1 AND t.writable=0 '
        'ORDER BY c."table", c.name'
    )
    assert r['ok'], r
    assert r['rows'] == [], f'pk=True on read-only tables: {r["rows"]}'


def test_every_writable_table_has_writable_columns(client) -> None:
    r = client.query(
        'SELECT t.name, COUNT(c.name) FROM bsql_tables t '
        'LEFT JOIN bsql_columns c ON c."table"=t.name AND c.writable=1 '
        'WHERE t.writable=1 '
        'GROUP BY t.name '
        'HAVING COUNT(c.name) = 0 '
        'ORDER BY t.name'
    )
    assert r['ok'], r
    bad = [row[0] for row in r['rows']]
    unexpected = sorted(set(bad) - _DELETE_ONLY_TABLES)
    assert not unexpected, f'writable tables without writable columns: {unexpected}'


def test_columns_match_schema(client) -> None:
    # Every registered vtable's PRAGMA table_info must agree with its bsql_columns
    # metadata, modulo the documented HIDDEN-column allowlist above. Drift here
    # means the class's COLUMNS tuple lost sync with its `schema` CREATE TABLE.
    r = client.query('SELECT name FROM bsql_tables ORDER BY name')
    assert r['ok'], r
    for (table,) in r['rows']:
        # `table` comes from our own registry — safe to interpolate.
        assert table.replace('_', '').isalnum(), f'unsafe table name: {table!r}'
        pragma = client.query(f'PRAGMA table_info({table})')
        assert pragma['ok'], f'{table}: {pragma}'
        pragma_cols = {row[1] for row in pragma['rows']}
        meta = client.query(f'SELECT name FROM bsql_columns WHERE "table"=\'{table}\'')
        assert meta['ok'], f'{table}: {meta}'
        meta_cols = {row[0] for row in meta['rows']}
        allowed_extra = _SCHEMA_HIDDEN_EXCEPTIONS.get(table, frozenset())
        in_schema_not_meta = pragma_cols - meta_cols - allowed_extra
        in_meta_not_schema = meta_cols - pragma_cols
        assert not in_schema_not_meta, (
            f'{table}: in schema but missing from COLUMNS: {sorted(in_schema_not_meta)}'
        )
        assert not in_meta_not_schema, (
            f'{table}: in COLUMNS but missing from schema: {sorted(in_meta_not_schema)}'
        )
