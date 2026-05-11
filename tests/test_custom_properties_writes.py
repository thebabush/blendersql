"""Round-trip write tests for the writable `custom_properties` vtable.

Each test that mutates Cube's custom properties is wrapped by the autouse
fixture which records Cube's pre-existing key set and removes anything the
test added (or restores the value if the test mangled a pre-existing key
like `health`).
"""

from __future__ import annotations

import json

import pytest

_TEST_KEY = 'sql_test_int'
_TEST_KEY_LIST = 'sql_test_list'
_TEST_KEY_DICT = 'sql_test_dict'
_TEST_KEY_UI = 'sql_test_ui'
_TEST_KEY_RENAME = 'sql_test_rename'
_TEST_KEY_RENAMED = 'sql_test_renamed'
_ALL_TEST_KEYS = (
    _TEST_KEY,
    _TEST_KEY_LIST,
    _TEST_KEY_DICT,
    _TEST_KEY_UI,
    _TEST_KEY_RENAME,
    _TEST_KEY_RENAMED,
)


@pytest.fixture(autouse=True)
def _cleanup_cube_props(client):
    snap = client.query(
        "SELECT key FROM custom_properties WHERE datablock_type='object' AND datablock_name='Cube'"
    )
    assert snap['ok'], snap
    pre_keys = {row[0] for row in snap['rows']}
    yield
    for k in _ALL_TEST_KEYS:
        client.query(
            f"DELETE FROM custom_properties WHERE datablock_type='object' AND datablock_name='Cube' AND key='{k}'"
        )
    post = client.query(
        "SELECT key FROM custom_properties WHERE datablock_type='object' AND datablock_name='Cube'"
    )
    assert post['ok'], post
    post_keys = {row[0] for row in post['rows']}
    leaked = post_keys - pre_keys
    assert not leaked, f'tests leaked custom-property keys on Cube: {sorted(leaked)}'


def _select_one(client, key: str) -> dict | None:
    r = client.query(
        f'SELECT value_json, subtype, description, min, max, soft_min, soft_max, step, "default" '
        f"FROM custom_properties WHERE datablock_type='object' AND datablock_name='Cube' AND key='{key}'"
    )
    assert r['ok'], r
    if r['row_count'] == 0:
        return None
    cols = [
        'value_json',
        'subtype',
        'description',
        'min',
        'max',
        'soft_min',
        'soft_max',
        'step',
        'default',
    ]
    return dict(zip(cols, r['rows'][0], strict=True))


def test_insert_scalar_int(client) -> None:
    r = client.query(
        f'INSERT INTO custom_properties(datablock_type, datablock_name, key, value_json) '
        f"VALUES ('object', 'Cube', '{_TEST_KEY}', '42')"
    )
    assert r['ok'], r
    row = _select_one(client, _TEST_KEY)
    assert row is not None
    assert json.loads(row['value_json']) == 42


def test_insert_list(client) -> None:
    r = client.query(
        f'INSERT INTO custom_properties(datablock_type, datablock_name, key, value_json) '
        f"VALUES ('object', 'Cube', '{_TEST_KEY_LIST}', '[1, 2, 3]')"
    )
    assert r['ok'], r
    row = _select_one(client, _TEST_KEY_LIST)
    assert row is not None
    assert json.loads(row['value_json']) == [1, 2, 3]


def test_insert_dict(client) -> None:
    r = client.query(
        f'INSERT INTO custom_properties(datablock_type, datablock_name, key, value_json) '
        f"VALUES ('object', 'Cube', '{_TEST_KEY_DICT}', '{{\"a\": 1, \"b\": 2}}')"
    )
    assert r['ok'], r
    row = _select_one(client, _TEST_KEY_DICT)
    assert row is not None
    assert json.loads(row['value_json']) == {'a': 1, 'b': 2}


def test_insert_with_ui_metadata(client) -> None:
    r = client.query(
        f'INSERT INTO custom_properties(datablock_type, datablock_name, key, value_json, description, min, max, step) '
        f"VALUES ('object', 'Cube', '{_TEST_KEY_UI}', '7', 'a test prop', 0.0, 100.0, 1.0)"
    )
    assert r['ok'], r
    row = _select_one(client, _TEST_KEY_UI)
    assert row is not None
    assert row['description'] == 'a test prop'
    assert row['min'] == 0.0
    assert row['max'] == 100.0
    assert row['step'] == 1.0


def test_update_value(client) -> None:
    ins = client.query(
        f'INSERT INTO custom_properties(datablock_type, datablock_name, key, value_json) '
        f"VALUES ('object', 'Cube', '{_TEST_KEY}', '1')"
    )
    assert ins['ok'], ins
    upd = client.query(
        f"UPDATE custom_properties SET value_json='99' "
        f"WHERE datablock_type='object' AND datablock_name='Cube' AND key='{_TEST_KEY}'"
    )
    assert upd['ok'], upd
    row = _select_one(client, _TEST_KEY)
    assert row is not None
    assert json.loads(row['value_json']) == 99


def test_update_ui_description(client) -> None:
    ins = client.query(
        f'INSERT INTO custom_properties(datablock_type, datablock_name, key, value_json, description) '
        f"VALUES ('object', 'Cube', '{_TEST_KEY_UI}', '5', 'before')"
    )
    assert ins['ok'], ins
    upd = client.query(
        f"UPDATE custom_properties SET description='after' "
        f"WHERE datablock_type='object' AND datablock_name='Cube' AND key='{_TEST_KEY_UI}'"
    )
    assert upd['ok'], upd
    row = _select_one(client, _TEST_KEY_UI)
    assert row is not None
    assert row['description'] == 'after'


def test_update_key_rename(client) -> None:
    ins = client.query(
        f'INSERT INTO custom_properties(datablock_type, datablock_name, key, value_json, description) '
        f"VALUES ('object', 'Cube', '{_TEST_KEY_RENAME}', '11', 'carry me')"
    )
    assert ins['ok'], ins
    upd = client.query(
        f"UPDATE custom_properties SET key='{_TEST_KEY_RENAMED}' "
        f"WHERE datablock_type='object' AND datablock_name='Cube' AND key='{_TEST_KEY_RENAME}'"
    )
    assert upd['ok'], upd
    assert _select_one(client, _TEST_KEY_RENAME) is None
    row = _select_one(client, _TEST_KEY_RENAMED)
    assert row is not None
    assert json.loads(row['value_json']) == 11
    assert row['description'] == 'carry me'


def test_delete(client) -> None:
    ins = client.query(
        f'INSERT INTO custom_properties(datablock_type, datablock_name, key, value_json) '
        f"VALUES ('object', 'Cube', '{_TEST_KEY}', '1')"
    )
    assert ins['ok'], ins
    dlt = client.query(
        f'DELETE FROM custom_properties '
        f"WHERE datablock_type='object' AND datablock_name='Cube' AND key='{_TEST_KEY}'"
    )
    assert dlt['ok'], dlt
    assert _select_one(client, _TEST_KEY) is None


def test_insert_duplicate_key_rejected(client) -> None:
    ins = client.query(
        f'INSERT INTO custom_properties(datablock_type, datablock_name, key, value_json) '
        f"VALUES ('object', 'Cube', '{_TEST_KEY}', '1')"
    )
    assert ins['ok'], ins
    dup = client.query(
        f'INSERT INTO custom_properties(datablock_type, datablock_name, key, value_json) '
        f"VALUES ('object', 'Cube', '{_TEST_KEY}', '2')"
    )
    assert dup['ok'] is False, dup
    row = _select_one(client, _TEST_KEY)
    assert row is not None
    assert json.loads(row['value_json']) == 1


def test_insert_unknown_datablock_type_rejected(client) -> None:
    r = client.query(
        'INSERT INTO custom_properties(datablock_type, datablock_name, key, value_json) '
        "VALUES ('not_a_thing', 'Cube', 'x', '1')"
    )
    assert r['ok'] is False, r


def test_insert_missing_datablock_name_rejected(client) -> None:
    r = client.query(
        'INSERT INTO custom_properties(datablock_type, datablock_name, key, value_json) '
        "VALUES ('object', 'NoSuchObject', 'x', '1')"
    )
    assert r['ok'] is False, r


def test_update_cross_datablock_move_rejected(client) -> None:
    ins = client.query(
        f'INSERT INTO custom_properties(datablock_type, datablock_name, key, value_json) '
        f"VALUES ('object', 'Cube', '{_TEST_KEY}', '1')"
    )
    assert ins['ok'], ins
    bad = client.query(
        f"UPDATE custom_properties SET datablock_name='Rig' "
        f"WHERE datablock_type='object' AND datablock_name='Cube' AND key='{_TEST_KEY}'"
    )
    assert bad['ok'] is False, bad
    row = _select_one(client, _TEST_KEY)
    assert row is not None
    assert json.loads(row['value_json']) == 1
