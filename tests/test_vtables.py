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

# bsql_tables / bsql_columns / bsql_related are excluded from EXPECTED because
# their counts track the live registry — covered by dedicated dynamic tests
# below. Keep them in the inventory's expected set so drift is still detected
# here.
_INTROSPECTION_TABLES: frozenset[str] = frozenset(
    {'bsql_tables', 'bsql_columns', 'bsql_related', 'bsql_functions'}
)

ALL_TABLES: list[str] = sorted(EXPECTED.keys())
ALL_REGISTERED_TABLES: list[str] = sorted(set(EXPECTED.keys()) | _INTROSPECTION_TABLES)

# Canonical taxonomy mirrored in the issue brief. Adding a new value here means
# adding a real domain to the registry — keep the two in sync. The regen script
# accepts any of these as a `vtables-domain=<x>` marker argument.
_KNOWN_DOMAINS: frozenset[str] = frozenset(
    {
        'scene',
        'mesh',
        'curve',
        'materials',
        'nodes',
        'modifiers',
        'animation',
        'grease_pencil',
        'armature',
        'vse',
        'lights',
        'assets',
        'paint',
        'audit',
        'search',
        'introspection',
    }
)


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
    assert cols == [
        'name',
        'writable',
        'description',
        'domain',
        'agent_hint',
        'column_count',
        'related',
    ]


def test_bsql_tables_snapshot_is_cached(client) -> None:
    # G4 regression: repeated `snapshot()` calls on the same BsqlTables /
    # BsqlColumns instance must return the cached list (same object identity)
    # while registry_version() is unchanged. Driven inside Blender via
    # bpy_exec because the cache lives on the live vtable instance owned by
    # the engine's apsw connection, not in the pytest process.
    import json

    code = (
        # The extension package path inside Blender is namespaced — pull the
        # modules by suffix so the test is robust to bl_ext layout changes.
        'import sys\n'
        'bsql = next(m for n, m in sys.modules.items() if n.endswith(".sql.vtables.bsql"))\n'
        'vtables = next(m for n, m in sys.modules.items() if n.endswith(".sql.vtables") and not n.endswith(".sql.vtables.bsql"))\n'
        '\n'
        'v_before = vtables.registry_version()\n'
        't = bsql.BsqlTables()\n'
        'c = bsql.BsqlColumns()\n'
        't1 = t.snapshot(); t2 = t.snapshot()\n'
        'c1 = c.snapshot(); c2 = c.snapshot()\n'
        'result = {\n'
        '    "tables_same": t1 is t2,\n'
        '    "columns_same": c1 is c2,\n'
        '    "version_stable": vtables.registry_version() == v_before,\n'
        '    "tables_len": len(t1),\n'
        '    "columns_len": len(c1),\n'
        '}\n'
    )
    r = client.query(f"SELECT bpy_exec('{code}')")
    assert r['ok'], r
    payload = json.loads(r['rows'][0][0])
    assert payload.get('error') is None, payload
    res = payload['result']
    assert res['tables_same'], res
    assert res['columns_same'], res
    assert res['version_stable'], res
    assert res['tables_len'] > 0
    assert res['columns_len'] > 0


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


def test_every_vtable_has_domain(client) -> None:
    # Positive assertion: every registered vtable must declare a non-empty
    # DOMAIN. A new class that forgets the attribute (or leaves it ``''`` from
    # the base default) flunks here. Fix the class, don't loosen the test.
    r = client.query("SELECT name FROM bsql_tables WHERE TRIM(domain)='' ORDER BY name")
    assert r['ok'], r
    assert r['rows'] == [], f'vtables without domain: {[row[0] for row in r["rows"]]}'


def test_domain_is_in_known_set(client) -> None:
    # Mirror of the canonical taxonomy. Adding a new domain requires updating
    # `_KNOWN_DOMAINS` AND the brief — keep the script's accepted argument set
    # in sync with this.
    r = client.query('SELECT DISTINCT domain FROM bsql_tables ORDER BY domain')
    assert r['ok'], r
    actual = {row[0] for row in r['rows']}
    unknown = actual - _KNOWN_DOMAINS
    assert not unknown, f'vtables declared unknown domain(s): {sorted(unknown)}'


# ---------------------------------------------------------------------------
# bsql_columns — per-column introspection over the same metadata pipeline


def test_bsql_columns_schema(client) -> None:
    r = client.query('PRAGMA table_info(bsql_columns)')
    assert r['ok'], r
    cols = [row[1] for row in r['rows']]
    assert cols == [
        'table',
        'name',
        'type',
        'writable',
        'pk',
        'identifier',
        'insert_only',
        'hint',
    ]


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


# ---------------------------------------------------------------------------
# bsql_related — long-form (a, b) RELATED edges with symmetry guards


def test_bsql_related_schema(client) -> None:
    r = client.query('PRAGMA table_info(bsql_related)')
    assert r['ok'], r
    cols = [row[1] for row in r['rows']]
    assert cols == ['a', 'b']


def test_bsql_related_matches_bsql_tables_related(client) -> None:
    # The long form must exactly enumerate bsql_tables.related (comma-joined).
    long_form = client.query('SELECT a, b FROM bsql_related ORDER BY a, b')
    short_form = client.query('SELECT name, related FROM bsql_tables ORDER BY name')
    assert long_form['ok'] and short_form['ok'], (long_form, short_form)
    expected_pairs: set[tuple[str, str]] = set()
    for name, related in short_form['rows']:
        if not related:
            continue
        for other in related.split(','):
            expected_pairs.add((name, other))
    got_pairs = {(a, b) for a, b in long_form['rows']}
    assert expected_pairs == got_pairs, (
        f'missing in long form: {sorted(expected_pairs - got_pairs)}; '
        f'extra in long form: {sorted(got_pairs - expected_pairs)}'
    )


def test_related_is_symmetric(client) -> None:
    # Every (a, b) edge must have its (b, a) reverse. New RELATED entries must
    # come in pairs.
    r = client.query('SELECT a, b FROM bsql_related')
    assert r['ok'], r
    pairs = {(row[0], row[1]) for row in r['rows']}
    asym = sorted({(a, b) for (a, b) in pairs if (b, a) not in pairs})
    assert not asym, f'asymmetric RELATED pairs: {asym}'


def test_related_has_no_self_loops(client) -> None:
    # A class listing itself in RELATED is almost certainly a typo.
    r = client.query('SELECT a FROM bsql_related WHERE a=b')
    assert r['ok'], r
    self_loops = sorted({row[0] for row in r['rows']})
    assert not self_loops, f'self-referential RELATED entries: {self_loops}'


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


def test_pk_implies_identifier(client) -> None:
    # Every write-side identifier (pk=1) must also be marked as part of the
    # natural identifier (identifier=1). identifier is the superset; pk is the
    # writable-side subset.
    r = client.query(
        'SELECT "table", name FROM bsql_columns WHERE pk=1 AND identifier=0 ORDER BY "table", name'
    )
    assert r['ok'], r
    assert r['rows'] == [], f'pk=True without identifier=True: {r["rows"]}'


def test_writable_table_has_identifier(client) -> None:
    # Every writable vtable must declare at least one identifier column so
    # agents can reach a row deterministically without scanning. Cross-checked
    # against bsql_columns.identifier.
    r = client.query(
        'SELECT t.name, COUNT(c.name) FROM bsql_tables t '
        'LEFT JOIN bsql_columns c ON c."table"=t.name AND c.identifier=1 '
        'WHERE t.writable=1 '
        'GROUP BY t.name '
        'HAVING COUNT(c.name) = 0 '
        'ORDER BY t.name'
    )
    assert r['ok'], r
    bad = [row[0] for row in r['rows']]
    assert not bad, f'writable tables without identifier columns: {bad}'


def test_insert_only_on_writable_table(client) -> None:
    # insert_only is a write-side property; it has no meaning on read-only
    # tables (UPDATE doesn't run there to begin with).
    r = client.query(
        'SELECT c."table", c.name FROM bsql_columns c '
        'JOIN bsql_tables t ON t.name=c."table" '
        'WHERE c.insert_only=1 AND t.writable=0 '
        'ORDER BY c."table", c.name'
    )
    assert r['ok'], r
    assert r['rows'] == [], f'insert_only=True on read-only tables: {r["rows"]}'


def test_every_writable_table_has_writable_columns(client) -> None:
    # "Writable" here counts UPDATE-writable OR insert_only — insert_only
    # columns are still a legitimate write surface, just not on UPDATE.
    r = client.query(
        'SELECT t.name, COUNT(c.name) FROM bsql_tables t '
        'LEFT JOIN bsql_columns c ON c."table"=t.name '
        'AND (c.writable=1 OR c.insert_only=1) '
        'WHERE t.writable=1 '
        'GROUP BY t.name '
        'HAVING COUNT(c.name) = 0 '
        'ORDER BY t.name'
    )
    assert r['ok'], r
    bad = [row[0] for row in r['rows']]
    unexpected = sorted(set(bad) - _DELETE_ONLY_TABLES)
    assert not unexpected, f'writable tables without writable columns: {unexpected}'


# ---------------------------------------------------------------------------
# bsql_functions — introspection vtable for SQL scalar functions + verbs


def test_bsql_functions_schema(client) -> None:
    r = client.query('PRAGMA table_info(bsql_functions)')
    assert r['ok'], r
    cols = [row[1] for row in r['rows']]
    assert cols == [
        'name',
        'kind',
        'description',
        'agent_hint',
        'arity',
        'return_shape',
        'side_effects',
    ]


def test_bsql_functions_includes_escape_hatches_and_verbs(client) -> None:
    r = client.query('SELECT name, kind FROM bsql_functions ORDER BY name')
    assert r['ok'], r
    rows = r['rows']
    names = {row[0] for row in rows}
    assert 'bpy_eval' in names and 'bpy_exec' in names and 'bpy_op' in names
    assert 'add_object' in names and 'save' in names and 'purge_orphans' in names
    assert 'grep' in names
    by_name = dict(rows)
    assert by_name['bpy_eval'] == 'escape_hatch'
    assert by_name['bpy_exec'] == 'escape_hatch'
    assert by_name['bpy_op'] == 'escape_hatch'
    assert by_name['add_object'] == 'verb'
    assert by_name['grep'] == 'scalar'


def test_every_bsql_function_has_metadata(client) -> None:
    # Phase-2 regression guard: positive assertion mirror of the bsql_tables
    # version. description must be a real one-liner (>= 10 chars after trim);
    # agent_hint must say something (>= 20 chars); kind + return_shape must be
    # in the documented enums. Don't loosen the test — fix the decorator.
    r = client.query(
        'SELECT name FROM bsql_functions '
        'WHERE LENGTH(TRIM(description)) < 10 '
        'OR LENGTH(TRIM(agent_hint)) < 20 '
        "OR kind NOT IN ('escape_hatch','verb','scalar') "
        "OR return_shape NOT IN ('json_envelope','json','value','string')"
    )
    assert r['ok'], r
    assert r['rows'] == [], r['rows']


def test_bsql_functions_count_matches_registry(client) -> None:
    # Mirror of test_bsql_tables_count_matches_registry. The registry lives
    # inside Blender so we can't double-check from the pytest process; the
    # minimum is the 25 verbs + 3 escape hatches + 1 scalar = 29.
    r = client.query('SELECT COUNT(*) FROM bsql_functions')
    assert r['ok'], r
    n = r['rows'][0][0]
    assert n >= 29, f'expected >= 29 registered functions, got {n}'


def test_bsql_functions_arity_for_verbs(client) -> None:
    # Every verb is registered as variadic (arity=-1); the only single-arity
    # entries are bpy_eval / bpy_exec.
    r = client.query("SELECT name, arity FROM bsql_functions WHERE kind='verb'")
    assert r['ok'], r
    for name, arity in r['rows']:
        assert arity == -1, f'{name}: expected variadic arity=-1, got {arity}'


def test_bsql_functions_side_effects_taxonomy(client) -> None:
    # Read-only entries: bpy_eval + grep. Everything else should be flagged
    # as side-effecting.
    r = client.query('SELECT name, side_effects FROM bsql_functions ORDER BY name')
    assert r['ok'], r
    by_name = dict(r['rows'])
    assert by_name['bpy_eval'] == 0, by_name
    assert by_name['grep'] == 0, by_name
    assert by_name['bpy_exec'] == 1, by_name
    assert by_name['bpy_op'] == 1, by_name
    assert by_name['add_object'] == 1, by_name
    assert by_name['save'] == 1, by_name


def test_bsql_functions_snapshot_is_cached(client) -> None:
    # G4 regression mirror: repeated `snapshot()` on the same BsqlFunctions
    # instance returns the cached list (same identity) while functions_version()
    # is unchanged. Driven inside Blender — the cache lives on the live vtable
    # instance owned by the engine's apsw connection.
    import json

    code = (
        'import sys\n'
        'bsql = next(m for n, m in sys.modules.items() if n.endswith(".sql.vtables.bsql"))\n'
        'registry = next(m for n, m in sys.modules.items() if n.endswith(".sql.functions.registry"))\n'
        '\n'
        'v_before = registry.functions_version()\n'
        'f = bsql.BsqlFunctions()\n'
        'r1 = f.snapshot(); r2 = f.snapshot()\n'
        'result = {\n'
        '    "rows_same": r1 is r2,\n'
        '    "version_stable": registry.functions_version() == v_before,\n'
        '    "rows_len": len(r1),\n'
        '}\n'
    )
    r = client.query(f"SELECT bpy_exec('{code}')")
    assert r['ok'], r
    payload = json.loads(r['rows'][0][0])
    assert payload.get('error') is None, payload
    res = payload['result']
    assert res['rows_same'], res
    assert res['version_stable'], res
    assert res['rows_len'] >= 29, res


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
