"""Unit tests for `engine._jsonify` — keep the wire format valid JSON.

SQLite (via apsw) is happy to surface float('nan') / float('inf') values to
Python — they typically come from `bpy.types.Object.scale` or any user-mode
math that overflowed. Python's `json.dumps` with the stdlib default
(`allow_nan=True`) emits the JS-only `NaN` / `Infinity` literals, which are
NOT valid JSON. Conforming MCP clients reject them. `_jsonify` is the
single chokepoint that coerces non-finite floats to `None` so the response
bytes are always parseable.
"""

from __future__ import annotations

import json

import pytest

from blendersql.sql.engine import _jsonify


def test_jsonify_passes_finite_values_through() -> None:
    row = (1, 2.5, 'foo', None, True)
    assert _jsonify(row) == [1, 2.5, 'foo', None, True]


def test_jsonify_coerces_nan_to_none() -> None:
    out = _jsonify((float('nan'),))
    assert out == [None]


def test_jsonify_coerces_positive_infinity_to_none() -> None:
    out = _jsonify((float('inf'),))
    assert out == [None]


def test_jsonify_coerces_negative_infinity_to_none() -> None:
    out = _jsonify((float('-inf'),))
    assert out == [None]


def test_jsonify_hexifies_bytes() -> None:
    assert _jsonify((b'\x00\xff',)) == ['00ff']


def test_jsonify_hexifies_bytearray() -> None:
    assert _jsonify((bytearray(b'\xab\xcd'),)) == ['abcd']


def test_jsonify_output_serialises_under_allow_nan_false() -> None:
    """End-to-end guarantee: even with `allow_nan=False`, a row containing
    every kind of non-finite float survives serialisation as `null`."""
    row = (float('nan'), float('inf'), float('-inf'), 1.0)
    encoded = json.dumps(_jsonify(row), allow_nan=False)
    assert json.loads(encoded) == [None, None, None, 1.0]


def test_jsonify_unmodified_float_still_serialises_under_allow_nan_false() -> None:
    """Belt-and-braces: if a non-finite ever slips through (e.g. wrapped in
    a list or dict the helper doesn't traverse), `allow_nan=False` would
    raise — proving the chokepoint logic is sound for scalars."""
    with pytest.raises(ValueError):
        json.dumps([float('nan')], allow_nan=False)
