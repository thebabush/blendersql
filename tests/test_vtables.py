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
    {
        'bsql_tables',
        'bsql_columns',
        'bsql_related',
        'bsql_functions',
        'bsql_function_params',
    }
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
    #
    # The "every function has at least one Param" guard lives standalone as
    # `test_every_function_has_documented_params_when_arity_known` below
    # (same query — there used to be a Phase-5 duplicate here).
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
    # Mirror of test_bsql_tables_count_matches_registry. Internal consistency
    # check — COUNT(*) FROM bsql_functions must equal the count of distinct
    # owning functions in bsql_function_params (both come from the same
    # registry). No magic number — exactly the drift the introspection
    # system was built to kill.
    a = client.query('SELECT COUNT(*) FROM bsql_functions')
    b = client.query('SELECT COUNT(DISTINCT function) FROM bsql_function_params')
    assert a['ok'] and b['ok'], (a, b)
    assert a['rows'][0][0] == b['rows'][0][0], (a, b)


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


# ---------------------------------------------------------------------------
# bsql_function_params — per-parameter metadata across every SQL function


def test_bsql_function_params_schema(client) -> None:
    r = client.query('PRAGMA table_info(bsql_function_params)')
    assert r['ok'], r
    cols = [row[1] for row in r['rows']]
    assert cols == [
        'function',
        'position',
        'name',
        'type',
        'required',
        'default_json',
        'hint',
    ]


def test_bsql_function_params_count_matches_metadata(client) -> None:
    # COUNT(*) FROM bsql_function_params must equal the total Param count across
    # the function registry. Without a registry-side projection (Params don't
    # show up in bsql_functions today), we cross-check the count against an
    # in-Blender enumeration via bpy_exec — same pattern as the snapshot-cache
    # tests. The minimum is the documented param shape (>=1 param per non-arg-
    # less function); the equality check pins exact behaviour.
    import json

    code = (
        'import sys\n'
        'registry = next(m for n, m in sys.modules.items() if n.endswith(".sql.functions.registry"))\n'
        'reg = registry.functions_registry()\n'
        'result = sum(len(meta.params) for meta in reg.values())\n'
    )
    blender_total = client.query(f"SELECT bpy_exec('{code}')")
    assert blender_total['ok'], blender_total
    payload = json.loads(blender_total['rows'][0][0])
    assert payload.get('error') is None, payload
    expected = payload['result']

    actual = client.query('SELECT COUNT(*) FROM bsql_function_params')
    assert actual['ok'], actual
    assert actual['rows'][0][0] == expected, (actual, expected)


def test_bsql_function_params_join_with_functions(client) -> None:
    # Every row's `function` must JOIN cleanly against bsql_functions.name.
    # A LEFT JOIN that turns up NULL means a Param escaped without an owning
    # FunctionMeta — that should be impossible (params are stored on the meta
    # itself) but the guard pins it.
    r = client.query(
        'SELECT p.function FROM bsql_function_params p '
        'LEFT JOIN bsql_functions f ON f.name=p.function '
        'WHERE f.name IS NULL '
        'GROUP BY p.function'
    )
    assert r['ok'], r
    assert r['rows'] == [], f'orphan function names in bsql_function_params: {r["rows"]}'


def test_every_function_has_documented_params_when_arity_known(client) -> None:
    # Every variadic (arity=-1) function carries a typed param list — that's
    # the whole point of Phase 5. The escape hatches with arity>=1 (bpy_eval,
    # bpy_exec) are also documented and likewise get caught here. The set of
    # functions with zero params should always be empty.
    r = client.query(
        'SELECT f.name, f.arity FROM bsql_functions f '
        'LEFT JOIN bsql_function_params p ON p.function=f.name '
        'GROUP BY f.name '
        'HAVING COUNT(p.name) = 0 '
        'ORDER BY f.name'
    )
    assert r['ok'], r
    assert r['rows'] == [], f'functions without documented params: {r["rows"]}'


def test_bsql_function_params_required_first_then_optional(client) -> None:
    # Conventional shape: every required param appears at a lower `position`
    # than every optional param within the same function. Catches a verb that
    # accidentally interleaved an optional arg before a required one.
    r = client.query(
        'SELECT a.function FROM bsql_function_params a '
        'JOIN bsql_function_params b '
        'ON a.function=b.function AND a.position < b.position '
        'WHERE a.required=0 AND b.required=1 '
        'GROUP BY a.function '
        'ORDER BY a.function'
    )
    assert r['ok'], r
    assert r['rows'] == [], f'optional-before-required params: {r["rows"]}'


def test_bsql_function_params_default_json_only_on_optional(client) -> None:
    # Required params carry an empty `default_json`; optional params carry a
    # non-empty JSON-encoded default. A required-with-default would imply
    # contradictory semantics — fix the Param decl, not the test.
    r = client.query(
        'SELECT function, name FROM bsql_function_params '
        "WHERE required=1 AND default_json != '' "
        'ORDER BY function, position'
    )
    assert r['ok'], r
    assert r['rows'] == [], f'required params with non-empty default_json: {r["rows"]}'


def test_bsql_function_params_types_in_known_set(client) -> None:
    # Param.type follows the same enum-as-string discipline as Column.type.
    r = client.query(
        'SELECT DISTINCT type FROM bsql_function_params '
        "WHERE type NOT IN ('TEXT','REAL','INTEGER','JSON','ANY')"
    )
    assert r['ok'], r
    assert r['rows'] == [], f'unexpected Param.type values: {r["rows"]}'


def test_bsql_function_params_snapshot_is_cached(client) -> None:
    # Mirror of test_bsql_functions_snapshot_is_cached — the params vtable
    # shares the functions_version() counter for invalidation.
    import json

    code = (
        'import sys\n'
        'bsql = next(m for n, m in sys.modules.items() if n.endswith(".sql.vtables.bsql"))\n'
        'registry = next(m for n, m in sys.modules.items() if n.endswith(".sql.functions.registry"))\n'
        '\n'
        'v_before = registry.functions_version()\n'
        'f = bsql.BsqlFunctionParams()\n'
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
    assert res['rows_len'] > 0, res


def test_function_names_unique(client) -> None:
    # bsql_functions is keyed on name; duplicates would only appear if
    # register_function ever clobbered. Pair with the register_function
    # RuntimeError so silent overwrites surface at both registration time
    # (raise) and inspection time (this).
    r = client.query('SELECT name, COUNT(*) FROM bsql_functions GROUP BY name HAVING COUNT(*) > 1')
    assert r['ok'], r
    assert r['rows'] == [], r['rows']


def test_param_metadata_matches_python_registry(client) -> None:
    # COUNT(*) parity only catches "wrong number of params"; a typo in
    # Param.name vs the Python variable name slips through silently. Walk
    # the live registry inside Blender and serialise every Param tuple,
    # then compare row-for-row against bsql_function_params. If a future
    # Param drifts from the Python decorator, this is the test that catches
    # it.
    import json

    code = (
        'import sys, json\n'
        'registry = next(m for n, m in sys.modules.items() if n.endswith(".sql.functions.registry"))\n'
        'reg = registry.functions_registry()\n'
        'rows = []\n'
        'for fname in sorted(reg):\n'
        '    meta = reg[fname]\n'
        '    for pos, p in enumerate(meta.params):\n'
        '        rows.append([\n'
        '            meta.name, pos, p.name, p.type, int(p.required),\n'
        '            p.default_json, p.hint,\n'
        '        ])\n'
        'result = rows\n'
    )
    blender = client.query(f"SELECT bpy_exec('{code}')")
    assert blender['ok'], blender
    payload = json.loads(blender['rows'][0][0])
    assert payload.get('error') is None, payload
    expected = [tuple(row) for row in payload['result']]

    actual_q = client.query(
        'SELECT function, position, name, type, required, default_json, hint '
        'FROM bsql_function_params ORDER BY function, position'
    )
    assert actual_q['ok'], actual_q
    actual = [tuple(row) for row in actual_q['rows']]
    # Sort the Blender-side rows the same way SQL ORDER BY does (lexicographic
    # on function name, numeric on position).
    expected_sorted = sorted(expected, key=lambda r: (r[0], r[1]))
    assert actual == expected_sorted, (
        f'Param metadata drift between Python registry and bsql_function_params.\n'
        f'first divergence: {next((i for i, (a, e) in enumerate(zip(actual, expected_sorted, strict=False)) if a != e), None)}'
    )


def test_default_json_parses(client) -> None:
    # Every non-empty default_json must be valid JSON. Catches a stray
    # `default_json='false'` thinking it's a bool literal (it is, but the
    # type field might not agree — see the next test) or an unquoted string.
    import json

    r = client.query(
        "SELECT function, name, default_json FROM bsql_function_params WHERE default_json != ''"
    )
    assert r['ok'], r
    for func, param, default_json in r['rows']:
        try:
            json.loads(default_json)
        except json.JSONDecodeError as e:
            pytest.fail(f'{func}.{param}: invalid default_json {default_json!r}: {e}')


def test_default_json_matches_declared_type(client) -> None:
    # default_json must parse as a value compatible with the declared `type`.
    # INTEGER -> int, REAL -> int|float, TEXT -> str, JSON -> any, ANY skipped.
    # Catches Bug-5-style drift (INTEGER declared with `default_json='false'`).
    import json

    rows = client.query(
        'SELECT function, name, type, default_json FROM bsql_function_params '
        "WHERE default_json != ''"
    )['rows']
    for func, name, type_, default_json in rows:
        val = json.loads(default_json)
        if type_ == 'ANY':
            continue
        if type_ == 'JSON':
            # Any JSON value is fine.
            continue
        if val is None:
            # JSON null is permissible for any nullable optional. The opt_*
            # helpers in _common.py treat null as "absent".
            continue
        if type_ == 'INTEGER':
            assert isinstance(val, int) and not isinstance(val, bool), (
                f'{func}.{name}: type=INTEGER but default_json={default_json!r}'
            )
        elif type_ == 'REAL':
            assert isinstance(val, (int, float)) and not isinstance(val, bool), (
                f'{func}.{name}: type=REAL but default_json={default_json!r}'
            )
        elif type_ == 'TEXT':
            assert isinstance(val, str), (
                f'{func}.{name}: type=TEXT but default_json={default_json!r}'
            )
        else:
            pytest.fail(f'{func}.{name}: unknown declared type {type_!r}')


def test_optional_param_has_default(client) -> None:
    # The converse of test_bsql_function_params_default_json_only_on_optional.
    # An optional param without a default leaves the agent guessing — and the
    # verb body has no source of truth for the omitted-arg value.
    r = client.query(
        "SELECT function, name FROM bsql_function_params WHERE required=0 AND default_json=''"
    )
    assert r['ok'], r
    assert r['rows'] == [], r['rows']


def test_bind_is_idempotent() -> None:
    # Bug-3 regression: calling _bind() twice on the same Engine/table name
    # must not raise. apsw rejects a duplicate CREATE VIRTUAL TABLE without
    # an explicit DROP first; _bind() now prefixes DROP TABLE IF EXISTS for
    # exactly this case.
    #
    # Run as a pure-Python unit test (no Blender, no bpy_exec) so we avoid
    # apsw's BusyError on re-`createscalarfunction` while a statement is
    # active — the same call path register_all() uses, but exercising _bind
    # in isolation is the targeted Bug-3 surface. The full register_all()
    # idempotency follows by induction once _bind is.
    import apsw

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from blendersql.sql.vtables import _REGISTRY, _bind
    from blendersql.sql.vtables._meta import Column as VColumn

    _COLUMNS_FIXTURE = (VColumn('x', 'INTEGER'),)

    class _MockSource:
        DESCRIPTION = 'mock'
        AGENT_HINT = 'mock vtable for idempotency test'
        COLUMNS = _COLUMNS_FIXTURE
        RELATED: tuple[str, ...] = ()
        WRITABLE = False
        DOMAIN = 'introspection'
        schema = 'CREATE TABLE mock_idemp(x INTEGER)'

        def Create(self, db, modulename, dbname, tablename, *args):
            return self.schema, self

        Connect = Create

        def BestIndex(self, *a):
            return None

        def Open(self):
            return self

        def Disconnect(self):
            pass

        Destroy = Disconnect

        def Filter(self, *a):
            pass

        def Eof(self):
            return True

        def Column(self, n):
            return None

        def Rowid(self):
            return 0

        def Next(self):
            pass

        def Close(self):
            pass

    class _Eng:
        def __init__(self) -> None:
            self.conn = apsw.Connection(':memory:')

    eng = _Eng()
    try:
        # _bind is typed against the real Engine class; _Eng is a minimal
        # duck-typed stand-in (only `.conn` is touched).
        _bind(eng, 'mock_idemp', _MockSource())
        # Second call must not raise — that's the whole bug.
        _bind(eng, 'mock_idemp', _MockSource())
    finally:
        _REGISTRY.pop('mock_idemp', None)
        eng.conn.close()
