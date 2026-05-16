"""Unit-level smoke tests for `scripts/regen_skills.py`.

These exercise the pure-string helpers (`_rewrite`, `_MARKER_RE`, the
generators) on synthetic data — no Blender boot, ~50ms total. Catches a
class of regressions (regex changes, single-line wrapping behaviour, the
grep / scalar path) that the full guard would only catch after a 1-2s
subprocess.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / 'scripts'))

import regen_skills as rs  # noqa: E402


def _synthetic_data() -> dict[str, list[dict[str, object]]]:
    """Minimal in-memory fixture mirroring what `_fetch_live_data` returns."""
    return {
        'vtables': [
            {
                'name': 'objects',
                'writable': 1,
                'description': 'Scene objects.',
                'domain': 'scene',
            },
            {
                'name': 'meshes',
                'writable': 0,
                'description': 'Mesh datablocks.',
                'domain': 'mesh',
            },
            {
                'name': 'mesh_vertices',
                'writable': 0,
                'description': 'Mesh vertex positions.',
                'domain': 'mesh',
            },
            {
                'name': 'grep',
                'writable': 0,
                'description': 'Full-text search.',
                'domain': 'search',
            },
        ],
        'functions': [
            {
                'name': 'bpy_eval',
                'kind': 'escape_hatch',
                'side_effects': 0,
                'description': 'Eval a Python expression.',
            },
            {
                'name': 'add_object',
                'kind': 'verb',
                'side_effects': 1,
                'description': 'Create a new object.',
            },
            {
                'name': 'grep',
                'kind': 'scalar',
                'side_effects': 0,
                'description': 'Search every named bpy datablock.',
            },
        ],
    }


def test_marker_re_matches_open_close_pair() -> None:
    text = '<!-- BSQL-AUTOGEN:verbs -->BODY<!-- /BSQL-AUTOGEN:verbs -->'
    m = rs._MARKER_RE.search(text)
    assert m is not None
    assert m.group('kind') == 'verbs'
    assert m.group('body') == 'BODY'


def test_rewrite_multiline_wraps_with_newlines() -> None:
    data = _synthetic_data()
    src = 'x\n<!-- BSQL-AUTOGEN:vtables -->stale<!-- /BSQL-AUTOGEN:vtables -->\ny'
    out = rs._rewrite(src, data, Path('synthetic.md'))
    # Multi-line generator output should sit on its own line (open marker
    # followed by a newline, close marker preceded by a newline).
    assert '<!-- BSQL-AUTOGEN:vtables -->\n' in out
    assert '\n<!-- /BSQL-AUTOGEN:vtables -->' in out
    # Spot-check a row landed.
    assert '`objects`' in out
    assert 'Scene objects.' in out


def test_rewrite_singleline_scalar_is_inline() -> None:
    data = _synthetic_data()
    src = (
        'There are <!-- BSQL-AUTOGEN:vtable-count -->OLD<!-- /BSQL-AUTOGEN:vtable-count --> '
        'vtables registered.'
    )
    out = rs._rewrite(src, data, Path('synthetic.md'))
    # Single-line scalar body must remain inline — no \n injected.
    assert (
        'There are <!-- BSQL-AUTOGEN:vtable-count -->4<!-- /BSQL-AUTOGEN:vtable-count --> '
        'vtables registered.' in out
    )


def test_scalars_generator_includes_grep() -> None:
    """Regression: grep has kind='scalar' which falls through the verbs and
    escape-hatches filters. The dedicated `scalars` kind catches it."""
    data = _synthetic_data()
    body = rs._gen_scalars(data)
    assert '| `grep` |' in body
    # Should NOT include verbs or escape hatches.
    assert 'add_object' not in body
    assert 'bpy_eval' not in body


def test_scalar_count_generators() -> None:
    data = _synthetic_data()
    assert rs._gen_vtable_count(data) == '4'
    assert rs._gen_writable_table_count(data) == '1'
    assert rs._gen_verb_count(data) == '1'
    assert rs._gen_function_count(data) == '3'


def test_parameterized_vtables_domain_marker_filters_and_renders() -> None:
    """Parameterized kind: `<!-- BSQL-AUTOGEN:vtables-domain=mesh -->...`.

    The substitution should pick up only the two mesh-domain rows in the
    synthetic data (meshes, mesh_vertices), keep the table shape, and the
    different-arg markers must NOT trip the duplicate-kind validator (covered
    by parsing both kinds in one source string here).
    """
    data = _synthetic_data()
    src = (
        '<!-- BSQL-AUTOGEN:vtables-domain=mesh -->old<!-- /BSQL-AUTOGEN:vtables-domain=mesh -->\n'
        '<!-- BSQL-AUTOGEN:vtables-domain=scene -->old<!-- /BSQL-AUTOGEN:vtables-domain=scene -->\n'
        'count=<!-- BSQL-AUTOGEN:vtable-count-domain=mesh -->X<!-- /BSQL-AUTOGEN:vtable-count-domain=mesh -->'
    )
    out = rs._rewrite(src, data, Path('synthetic.md'))
    assert '`meshes`' in out
    assert '`mesh_vertices`' in out
    assert '`objects`' in out  # scene-domain substitution landed too
    # `grep` is search domain — must NOT appear inside the mesh block.
    mesh_block_start = out.index('<!-- BSQL-AUTOGEN:vtables-domain=mesh -->')
    mesh_block_end = out.index('<!-- /BSQL-AUTOGEN:vtables-domain=mesh -->')
    assert 'grep' not in out[mesh_block_start:mesh_block_end]
    # Scalar parameterized count rendered inline.
    assert (
        'count=<!-- BSQL-AUTOGEN:vtable-count-domain=mesh -->2'
        '<!-- /BSQL-AUTOGEN:vtable-count-domain=mesh -->' in out
    )


def test_parameterized_marker_unknown_arg_raises() -> None:
    """Zero rows in a domain filter must surface as a setup error — never
    silently render an empty body."""
    data = _synthetic_data()
    src = (
        '<!-- BSQL-AUTOGEN:vtables-domain=not_a_real_domain -->'
        'x'
        '<!-- /BSQL-AUTOGEN:vtables-domain=not_a_real_domain -->'
    )
    with pytest.raises(rs._SetupError) as exc:
        rs._rewrite(src, data, Path('synthetic.md'))
    assert 'not_a_real_domain' in str(exc.value)


def test_unknown_kind_raises_setup_error() -> None:
    data = _synthetic_data()
    src = '<!-- BSQL-AUTOGEN:not-a-real-kind -->x<!-- /BSQL-AUTOGEN:not-a-real-kind -->'
    with pytest.raises(rs._SetupError) as exc:
        rs._rewrite(src, data, Path('synthetic.md'))
    assert 'unknown marker kind' in str(exc.value)


def test_md_escape_cell_wraps_marker_lookalikes() -> None:
    # Defensive: a future hint with a literal `<!--` must not confuse the
    # scanner — escape it into a code-span.
    out = rs._md_escape_cell('hint with <!-- nested --> token')
    assert '`<!--`' in out
    assert '`-->`' in out
