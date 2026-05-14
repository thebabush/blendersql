"""Tests for the scalar SQL functions: bpy_eval, bpy_exec, bpy_op, grep."""

from __future__ import annotations

import json


def test_bpy_eval_simple(client) -> None:
    r = client.query("SELECT bpy_eval('bpy.context.scene.frame_current')")
    assert r['ok'], r
    payload = json.loads(r['rows'][0][0])
    assert isinstance(payload, int)


def test_bpy_eval_error_envelope(client) -> None:
    r = client.query("SELECT bpy_eval('1/0')")
    assert r['ok'], r
    payload = json.loads(r['rows'][0][0])
    assert 'error' in payload
    assert 'ZeroDivisionError' in payload['error']


def test_bpy_exec_result(client) -> None:
    r = client.query("SELECT bpy_exec('result = 1 + 2')")
    assert r['ok'], r
    payload = json.loads(r['rows'][0][0])
    assert payload['result'] == 3
    assert payload['error'] is None


def test_bpy_exec_stdout_captured(client) -> None:
    r = client.query('SELECT bpy_exec(\'print("hello"); result = 42\')')
    assert r['ok'], r
    payload = json.loads(r['rows'][0][0])
    assert payload['stdout'].rstrip() == 'hello'
    assert payload['result'] == 42


def test_bpy_op_select_all(client) -> None:
    r = client.query('SELECT bpy_op(\'object.select_all\', \'{"action":"DESELECT"}\')')
    assert r['ok'], r
    payload = json.loads(r['rows'][0][0])
    assert payload['error'] is None
    assert payload['status'] in ('FINISHED', 'CANCELLED')


def test_grep_table_matches(client) -> None:
    r = client.query("SELECT name, kind FROM grep WHERE pattern='Cube%'")
    assert r['ok'], r
    names = [row[0] for row in r['rows']]
    assert 'Cube' in names


def test_grep_table_like_matches_eq(client) -> None:
    # `WHERE pattern LIKE '<pat>'` should return the same rows as
    # `WHERE pattern = '<pat>'` for any pattern. The vtable claims the
    # LIKE constraint in BestIndex so the value is forwarded to the
    # cursor's Filter exactly like an EQ.
    for pat in ('Cube%', '%Cube%', 'Cube'):
        eq = client.query(f"SELECT name, kind FROM grep WHERE pattern='{pat}'")
        like = client.query(f"SELECT name, kind FROM grep WHERE pattern LIKE '{pat}'")
        assert eq['ok'], eq
        assert like['ok'], like
        assert sorted(map(tuple, eq['rows'])) == sorted(map(tuple, like['rows'])), (
            f'LIKE vs EQ mismatch for {pat!r}: eq={eq["rows"]!r} like={like["rows"]!r}'
        )
        assert like['row_count'] > 0, f'expected matches for {pat!r}, got none'


def test_grep_scalar_function(client) -> None:
    r = client.query("SELECT grep('Cube%', 20, 0)")
    assert r['ok'], r
    payload = json.loads(r['rows'][0][0])
    assert isinstance(payload, list)
    assert any(item['name'] == 'Cube' for item in payload)


def test_bpy_exec_dict_result(client) -> None:
    r = client.query('SELECT bpy_exec(\'result = {"a": 1, "b": [2, 3], "c": {"d": 4}}\')')
    assert r['ok'], r
    payload = json.loads(r['rows'][0][0])
    assert payload['error'] is None
    assert payload['result'] == {'a': 1, 'b': [2, 3], 'c': {'d': 4}}
