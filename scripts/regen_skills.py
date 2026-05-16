"""Regenerate marker-managed sections in BlenderSQL skill markdown.

Markers look like:

    <!-- BSQL-AUTOGEN:<kind> -->
    ...content the script owns; everything between the markers is replaced...
    <!-- /BSQL-AUTOGEN:<kind> -->

Source of truth: the introspection vtables (`bsql_tables`, `bsql_columns`,
`bsql_functions`) running inside a headless Blender. We boot one Blender via
the CLI's `-f` mode (semicolon-split multi-statement SQL — one boot, many
queries, JSON-per-statement out), parse the JSON stream, and run a tiny
per-kind generator that returns the markdown body.

Modes:

    python scripts/regen_skills.py            # default = --check
    python scripts/regen_skills.py --check    # explicit; exits 1 + unified diff on drift
    python scripts/regen_skills.py --write    # apply changes in place

The CI guard in `tests/test_skill_regen.py` shells out with `--check`.

Marker kinds supported:

* `vtables`         — every registered vtable; name + writable + description.
* `writable-tables` — vtables with writable=1; bare list.
* `verbs`           — every typed verb function; name + side_effects + description.
* `escape-hatches`  — bpy_eval / bpy_exec / bpy_op; name + side_effects + description.

Bare invocation defaults to --check because an accidental write that silently
rewrites docs is worse than an accidental check.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLI = _REPO_ROOT / 'cli' / 'blendersql.py'
_FIXTURE = _REPO_ROOT / 'tests' / 'fixtures' / 'test_scene.blend'
_SKILLS_ROOT = _REPO_ROOT / 'skills' / 'plugins' / 'blendersql' / 'skills'

# Each marker is a regex pair: open / close around the body. We capture the
# body greedily up to the first matching close marker — markers don't nest, so
# this is fine. (?s) lets `.` cross newlines.
_MARKER_RE = re.compile(
    r'(<!-- BSQL-AUTOGEN:(?P<kind>[a-z0-9_-]+) -->)'
    r'(?P<body>.*?)'
    r'(<!-- /BSQL-AUTOGEN:(?P=kind) -->)',
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Live data fetch — one Blender boot, multiple queries.


# The queries are keyed by a short tag we use internally to dispatch results.
# Order is fixed so we can match results positionally on the JSON stream.
_QUERIES: tuple[tuple[str, str], ...] = (
    (
        'vtables',
        'SELECT name, writable, description FROM bsql_tables ORDER BY name;',
    ),
    (
        'functions',
        'SELECT name, kind, side_effects, description FROM bsql_functions ORDER BY kind, name;',
    ),
)


def _fetch_live_data() -> dict[str, list[dict[str, Any]]]:
    """Boot Blender once, run the bundled queries, return one rowset per tag.

    Each rowset is a list of dicts (column-name -> value). Raises on any
    query failure — drift detection means nothing if the source is wrong.
    """
    if not _FIXTURE.exists():
        raise SystemExit(
            f'fixture .blend missing at {_FIXTURE}; '
            'run the test suite once so conftest.py builds it.'
        )

    with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', delete=False, encoding='utf-8') as f:
        for _tag, sql in _QUERIES:
            f.write(sql + '\n')
        sql_path = Path(f.name)

    try:
        # uv run guarantees the right Python; the CLI itself only needs
        # stdlib, so we shell out plainly.
        result = subprocess.run(
            [
                sys.executable,
                str(_CLI),
                '-s',
                str(_FIXTURE),
                '-f',
                str(sql_path),
            ],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
    finally:
        sql_path.unlink(missing_ok=True)

    if result.returncode != 0:
        raise SystemExit(
            f'blendersql CLI exited {result.returncode}\n'
            f'--- stdout ---\n{result.stdout}\n'
            f'--- stderr ---\n{result.stderr}'
        )

    # CLI prints one JSON document per statement, whitespace-separated.
    docs = list(_iter_json_docs(result.stdout))
    if len(docs) != len(_QUERIES):
        raise SystemExit(
            f'expected {len(_QUERIES)} JSON docs from CLI; got {len(docs)}.\n'
            f'stdout:\n{result.stdout}'
        )

    out: dict[str, list[dict[str, Any]]] = {}
    for (tag, _sql), doc in zip(_QUERIES, docs, strict=True):
        if not doc.get('ok'):
            raise SystemExit(f'query for {tag!r} failed: {json.dumps(doc, indent=2)}')
        columns: list[str] = doc.get('columns') or []
        rows: list[list[Any]] = doc.get('rows') or []
        out[tag] = [dict(zip(columns, r, strict=True)) for r in rows]
    return out


def _iter_json_docs(text: str) -> list[dict[str, Any]]:
    """Parse a stream of whitespace-separated JSON objects."""
    dec = json.JSONDecoder()
    i = 0
    out: list[dict[str, Any]] = []
    n = len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        obj, end = dec.raw_decode(text, i)
        if not isinstance(obj, dict):
            raise ValueError(f'expected JSON object, got {type(obj).__name__}')
        out.append(obj)
        i = end
    return out


# ---------------------------------------------------------------------------
# Generators — one per marker kind.


def _md_escape_cell(text: str) -> str:
    """Make a cell safe for a GitHub-flavoured markdown table.

    Tables only need pipes escaped and newlines flattened; we don't try to
    sanitise arbitrary markup because skill text is hand-curated.
    """
    return text.replace('|', r'\|').replace('\n', ' ').strip()


def _gen_vtables(data: dict[str, list[dict[str, Any]]]) -> str:
    rows = data['vtables']
    lines = [
        '',
        '| name | writable | description |',
        '|---|---|---|',
    ]
    for r in rows:
        mark = 'yes' if int(r['writable']) else ''
        lines.append(f'| `{r["name"]}` | {mark} | {_md_escape_cell(str(r["description"] or ""))} |')
    lines.append('')
    return '\n'.join(lines)


def _gen_writable_tables(data: dict[str, list[dict[str, Any]]]) -> str:
    names = [r['name'] for r in data['vtables'] if int(r['writable'])]
    lines = ['']
    lines.extend(f'- `{n}`' for n in names)
    lines.append('')
    return '\n'.join(lines)


def _gen_verbs(data: dict[str, list[dict[str, Any]]]) -> str:
    rows = [r for r in data['functions'] if r['kind'] == 'verb']
    lines = [
        '',
        '| verb | side effects | description |',
        '|---|---|---|',
    ]
    for r in sorted(rows, key=lambda x: x['name']):
        mark = 'yes' if int(r['side_effects']) else ''
        lines.append(f'| `{r["name"]}` | {mark} | {_md_escape_cell(str(r["description"] or ""))} |')
    lines.append('')
    return '\n'.join(lines)


def _gen_escape_hatches(data: dict[str, list[dict[str, Any]]]) -> str:
    rows = [r for r in data['functions'] if r['kind'] == 'escape_hatch']
    lines = [
        '',
        '| function | side effects | description |',
        '|---|---|---|',
    ]
    for r in sorted(rows, key=lambda x: x['name']):
        mark = 'yes' if int(r['side_effects']) else ''
        lines.append(f'| `{r["name"]}` | {mark} | {_md_escape_cell(str(r["description"] or ""))} |')
    lines.append('')
    return '\n'.join(lines)


Generator = Callable[[dict[str, list[dict[str, Any]]]], str]

_GENERATORS: dict[str, Generator] = {
    'vtables': _gen_vtables,
    'writable-tables': _gen_writable_tables,
    'verbs': _gen_verbs,
    'escape-hatches': _gen_escape_hatches,
}


# ---------------------------------------------------------------------------
# Marker rewrite — pure string transformation, no I/O.


def _rewrite(text: str, data: dict[str, list[dict[str, Any]]], path: Path) -> str:
    """Replace every marker body in `text` with the generated content."""

    def _sub(match: re.Match[str]) -> str:
        kind = match.group('kind')
        gen = _GENERATORS.get(kind)
        if gen is None:
            raise SystemExit(
                f'{path}: unknown marker kind {kind!r}. Known: {", ".join(sorted(_GENERATORS))}.'
            )
        body = gen(data)
        if not body.startswith('\n'):
            body = '\n' + body
        if not body.endswith('\n'):
            body = body + '\n'
        return f'{match.group(1)}{body}{match.group(4)}'

    return _MARKER_RE.sub(_sub, text)


def _markdown_files() -> list[Path]:
    return sorted(_SKILLS_ROOT.rglob('*.md'))


def _files_with_markers() -> list[Path]:
    out: list[Path] = []
    for p in _markdown_files():
        if _MARKER_RE.search(p.read_text(encoding='utf-8')):
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Entry points.


def _check(data: dict[str, list[dict[str, Any]]]) -> int:
    drift = 0
    for path in _files_with_markers():
        original = path.read_text(encoding='utf-8')
        regenerated = _rewrite(original, data, path)
        if regenerated != original:
            drift += 1
            rel = path.relative_to(_REPO_ROOT)
            diff = difflib.unified_diff(
                original.splitlines(keepends=True),
                regenerated.splitlines(keepends=True),
                fromfile=f'a/{rel}',
                tofile=f'b/{rel}',
                n=3,
            )
            sys.stdout.write(''.join(diff))
    if drift:
        sys.stdout.write(
            f'\n{drift} file(s) out of sync. '
            f'Run `python scripts/regen_skills.py --write` and commit.\n'
        )
        return 1
    return 0


def _write(data: dict[str, list[dict[str, Any]]]) -> int:
    changed = 0
    for path in _files_with_markers():
        original = path.read_text(encoding='utf-8')
        regenerated = _rewrite(original, data, path)
        if regenerated != original:
            path.write_text(regenerated, encoding='utf-8')
            rel = path.relative_to(_REPO_ROOT)
            sys.stdout.write(f'updated {rel}\n')
            changed += 1
    if changed == 0:
        sys.stdout.write('no changes\n')
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog='regen_skills',
        description='Regenerate marker-managed sections of skill markdown.',
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        '--check',
        action='store_true',
        help='Exit 1 with a unified diff if any marker block would change (default).',
    )
    mode.add_argument(
        '--write',
        action='store_true',
        help='Rewrite markdown files in place.',
    )
    args = p.parse_args(argv)

    data = _fetch_live_data()
    if args.write:
        return _write(data)
    return _check(data)


if __name__ == '__main__':
    raise SystemExit(main())
