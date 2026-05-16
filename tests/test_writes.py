"""Round-trip write tests against the `objects` virtual table.

Each test snapshots Cube's location before running and reverts after, so
ordering between tests doesn't matter. INSERT tests clean up the row they
create.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _restore_cube(client):
    # Robust to a prior test having renamed the Cube and crashed before reverting.
    rescue = client.query("UPDATE objects SET name='Cube' WHERE name='CubeRenamed'")
    assert rescue['ok'] or rescue.get('row_count', 0) == 0, rescue

    snap = client.query(
        "SELECT location_x, location_y, location_z, hide_viewport, hide_render FROM objects WHERE name='Cube'"
    )
    assert snap['ok'] and snap['row_count'] == 1, snap
    yield
    lx, ly, lz, hv, hr = snap['rows'][0]
    r = client.query(
        f'UPDATE objects SET location_x={lx}, location_y={ly}, location_z={lz}, '
        f"hide_viewport={hv}, hide_render={hr} WHERE name='Cube'"
    )
    assert r['ok'], r
    client.query("DELETE FROM objects WHERE name='SqlInsertTest'")
    client.query("UPDATE objects SET name='Cube' WHERE name='CubeRenamed'")


def _cube_location(client) -> tuple[float, float, float]:
    r = client.query("SELECT location_x, location_y, location_z FROM objects WHERE name='Cube'")
    assert r['ok'], r
    return tuple(r['rows'][0])


def test_update_location_round_trip(client) -> None:
    before = _cube_location(client)
    r = client.query(
        "UPDATE objects SET location_x=2.5, location_y=-1.0, location_z=7.0 WHERE name='Cube'"
    )
    assert r['ok'], r
    after = _cube_location(client)
    assert after == (2.5, -1.0, 7.0)
    assert before != after


def test_update_hide_viewport(client) -> None:
    r = client.query("UPDATE objects SET hide_viewport=1 WHERE name='Cube'")
    assert r['ok'], r
    check = client.query("SELECT hide_viewport FROM objects WHERE name='Cube'")
    assert check['ok'] and check['rows'][0][0] == 1


def test_insert_then_delete(client) -> None:
    r = client.query("INSERT INTO objects(name, type) VALUES ('SqlInsertTest', 'EMPTY')")
    assert r['ok'], r
    check = client.query("SELECT COUNT(*) FROM objects WHERE name='SqlInsertTest'")
    assert check['ok'] and check['rows'][0][0] == 1

    r = client.query("DELETE FROM objects WHERE name='SqlInsertTest'")
    assert r['ok'], r
    check = client.query("SELECT COUNT(*) FROM objects WHERE name='SqlInsertTest'")
    assert check['ok'] and check['rows'][0][0] == 0


def test_insert_with_location_and_rotation_mode(client) -> None:
    r = client.query(
        'INSERT INTO objects(name, type, location_x, location_y, location_z, rotation_mode) '
        "VALUES ('SqlInsertTest', 'EMPTY', 1.0, 2.0, 3.0, 'XYZ')"
    )
    assert r['ok'], r
    check = client.query(
        "SELECT location_x, location_y, location_z, rotation_mode FROM objects WHERE name='SqlInsertTest'"
    )
    assert check['ok'], check
    assert check['rows'][0] == [1.0, 2.0, 3.0, 'XYZ']


def test_insert_with_parent(client) -> None:
    r = client.query(
        "INSERT INTO objects(name, type, parent) VALUES ('SqlInsertTest', 'EMPTY', 'Cube')"
    )
    assert r['ok'], r
    check = client.query("SELECT parent FROM objects WHERE name='SqlInsertTest'")
    assert check['ok'] and check['rows'][0][0] == 'Cube'


def test_update_read_only_column_rejected(client) -> None:
    # Cube is already type=MESH; pick a value that actually changes to trigger
    # the read-only check.
    r = client.query("UPDATE objects SET type='LIGHT' WHERE name='Cube'")
    assert r['ok'] is False, r
    assert 'read-only' in r.get('error', '').lower()


def test_insert_bad_rotation_mode_rejected(client) -> None:
    r = client.query(
        "INSERT INTO objects(name, type, rotation_mode) VALUES ('SqlInsertTest', 'EMPTY', 'BOGUS')"
    )
    assert r['ok'] is False, r
    # The orphaned datablock must not exist.
    check = client.query("SELECT COUNT(*) FROM objects WHERE name='SqlInsertTest'")
    assert check['ok'] and check['rows'][0][0] == 0


def test_insert_bad_parent_rejected(client) -> None:
    r = client.query(
        "INSERT INTO objects(name, type, parent) VALUES ('SqlInsertTest', 'EMPTY', 'DoesNotExist')"
    )
    assert r['ok'] is False, r
    check = client.query("SELECT COUNT(*) FROM objects WHERE name='SqlInsertTest'")
    assert check['ok'] and check['rows'][0][0] == 0


def test_insert_non_empty_type_rejected(client) -> None:
    r = client.query("INSERT INTO objects(name, type) VALUES ('SqlInsertTest', 'MESH')")
    assert r['ok'] is False, r
    assert 'EMPTY' in r.get('error', '')


def test_writable_vtable_insert_grows_identifiers(client) -> None:
    # Regression for B3: _WritableVTable.UpdateInsertRow used to return
    # `len(_identifiers)` without appending the new identifier. The returned
    # rowid then pointed one past the end of `_identifiers`; any apsw callback
    # that subsequently looked up `_identifiers[rowid]` (UpdateChangeRow /
    # UpdateDeleteRow) would IndexError. Drive the vtable directly inside
    # Blender via bpy_exec — pure-SQL paths don't exercise the bug because
    # apsw opens a fresh cursor (and we re-snapshot) for every top-level
    # statement, so `_identifiers` is always rebuilt before the next op.
    import json

    code = (
        # The extension package path inside Blender is namespaced — pull the
        # module by suffix so the test is robust to bl_ext layout changes.
        'import sys\n'
        'base = next(m for n, m in sys.modules.items() if n.endswith(".sql.vtables.base"))\n'
        '\n'
        'class FakeSource(base.WritableSnapshotVTable):\n'
        '    table_name = "fake"\n'
        '    def _apply_insert(self, fields):\n'
        '        return ("ident", fields[0])\n'
        '    def _describe_identifier(self, identifier):\n'
        '        return repr(identifier)\n'
        '\n'
        '# Stub the undo_push side-effect so we can drive the writable vtable\n'
        '# without an actual bpy operator context.\n'
        'class _NoOp:\n'
        '    def __call__(self, *a, **kw): pass\n'
        'import bpy\n'
        'orig = bpy.ops.ed.undo_push\n'
        'bpy.ops.ed.undo_push = _NoOp()\n'
        'try:\n'
        '    vt = base._WritableVTable(FakeSource())\n'
        '    vt._identifiers = ["pre0", "pre1"]\n'
        '    rid = vt.UpdateInsertRow(None, ("payload",))\n'
        '    ok = (\n'
        '        len(vt._identifiers) == 3\n'
        '        and 0 <= rid < len(vt._identifiers)\n'
        '        and vt._identifiers[rid] == ("ident", "payload")\n'
        '    )\n'
        '    result = {"ok": ok, "rid": rid, "ids_len": len(vt._identifiers)}\n'
        'finally:\n'
        '    bpy.ops.ed.undo_push = orig\n'
    )
    r = client.query(f"SELECT bpy_exec('{code}')")
    assert r['ok'], r
    payload = json.loads(r['rows'][0][0])
    assert payload.get('error') is None, payload
    assert payload['result']['ok'], payload['result']
    # Returned rowid must address the just-inserted entry (index of last
    # element after append).
    assert payload['result']['rid'] == payload['result']['ids_len'] - 1, payload['result']


def test_update_name_round_trip(client) -> None:
    r = client.query("UPDATE objects SET name='CubeRenamed' WHERE name='Cube'")
    assert r['ok'], r
    check = client.query("SELECT COUNT(*) FROM objects WHERE name='CubeRenamed'")
    assert check['ok'] and check['rows'][0][0] == 1
    # Restore so other tests' _restore_cube fixture finds it.
    revert = client.query("UPDATE objects SET name='Cube' WHERE name='CubeRenamed'")
    assert revert['ok'], revert
