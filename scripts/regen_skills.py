"""Regenerate marker-managed sections in BlenderSQL skill markdown.

Markers look like:

    <!-- BSQL-AUTOGEN:<kind> -->
    ...content the script owns; everything between the markers is replaced...
    <!-- /BSQL-AUTOGEN:<kind> -->

Scalar substitutions use the same markers around a single-line body, e.g.:

    <!-- BSQL-AUTOGEN:vtable-count -->80<!-- /BSQL-AUTOGEN:vtable-count -->

Source of truth: the introspection vtables (`bsql_tables`, `bsql_columns`,
`bsql_functions`) running inside a headless Blender. We boot one Blender via
the CLI's `-f` mode (semicolon-split multi-statement SQL — one boot, many
queries, JSON-per-statement out), parse the JSON stream, and run a tiny
per-kind generator that returns the markdown body.

Modes:

    python scripts/regen_skills.py            # default = --check
    python scripts/regen_skills.py --check    # explicit; exits 1 + unified diff on drift
    python scripts/regen_skills.py --write    # apply changes in place

Exit codes:

    0  clean (or --write succeeded)
    1  drift detected — re-run with --write and commit
    2  setup error (Blender boot failed, CLI missing, fixture absent,
       JSON parse error, unknown / duplicate / orphan marker kind, etc.)

The CI guard in `tests/test_skill_regen.py` shells out with `--check` and
distinguishes 1 vs 2 in its failure message.

Marker kinds supported:

* `vtables`           — every registered vtable; name + writable + description.
* `writable-tables`   — vtables with writable=1; bare list.
* `verbs`             — every typed verb function; name + side_effects + description.
* `escape-hatches`    — bpy_eval / bpy_exec / bpy_op; name + side_effects + description.
* `scalars`           — non-verb non-escape-hatch scalar functions (e.g. `grep`).
* `vtable-count`      — scalar: total vtable count.
* `writable-table-count` — scalar: count of writable vtables.
* `verb-count`        — scalar: count of kind='verb' functions.
* `function-count`    — scalar: total registered function count.

Bare invocation defaults to --check because an accidental write that silently
rewrites docs is worse than an accidental check.
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import json
import os
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

# Exit codes — kept as named constants so the pytest guard can mirror them.
EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_SETUP = 2


class _SetupError(Exception):
    """Raised for environment / config errors (missing fixture, bad markers, …).

    Caught at `main()` and translated to exit code 2.
    """


# Each marker is a regex pair: open / close around the body. We capture the
# body greedily up to the first matching close marker — markers don't nest, so
# this is fine. (?s) lets `.` cross newlines.
_MARKER_RE = re.compile(
    r'(<!-- BSQL-AUTOGEN:(?P<kind>[a-z0-9_-]+) -->)'
    r'(?P<body>.*?)'
    r'(<!-- /BSQL-AUTOGEN:(?P=kind) -->)',
    re.DOTALL,
)

# Used for orphan-marker / typo detection: matches an open OR close token
# regardless of whether it has a matching partner. After the substitution scan,
# any of these tokens still in the text indicates a structural problem.
_OPEN_MARKER_RE = re.compile(r'<!-- BSQL-AUTOGEN:(?P<kind>[a-z0-9_-]+) -->')
_CLOSE_MARKER_RE = re.compile(r'<!-- /BSQL-AUTOGEN:(?P<kind>[a-z0-9_-]+) -->')
# Relaxed scan for anything that mentions BSQL-AUTOGEN in a marker-ish way.
# Compared against the canonical open/close forms in `_validate_markers` so
# any near-miss (forward-slash close, missing whitespace, lowercase token) is
# caught.
_LOOSE_MARKER_RE = re.compile(
    r'</?BSQL-AUTOGEN[^>]*>|<!--[^>]*BSQL-AUTOGEN[^>]*-->',
    re.IGNORECASE,
)
_CANONICAL_MARKER_RE = re.compile(
    r'<!-- /?BSQL-AUTOGEN:[a-z0-9_-]+ -->',
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

    Each rowset is a list of dicts (column-name -> value). Raises `_SetupError`
    on any query failure — drift detection means nothing if the source is wrong.
    """
    if not _FIXTURE.exists():
        raise _SetupError(
            f'fixture .blend missing at {_FIXTURE}; '
            'run the test suite once so conftest.py builds it.'
        )
    if not _CLI.exists():
        raise _SetupError(f'blendersql CLI missing at {_CLI}.')

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
        raise _SetupError(
            f'blendersql CLI exited {result.returncode}\n'
            f'--- stdout ---\n{result.stdout}\n'
            f'--- stderr ---\n{result.stderr}'
        )

    # CLI prints one JSON document per statement, whitespace-separated.
    try:
        docs = _iter_json_docs(result.stdout)
    except ValueError as exc:
        raise _SetupError(
            f'failed to parse CLI stdout as JSON stream: {exc}\n{result.stdout}'
        ) from exc
    if len(docs) != len(_QUERIES):
        raise _SetupError(
            f'expected {len(_QUERIES)} JSON docs from CLI; got {len(docs)}.\n'
            f'stdout:\n{result.stdout}'
        )

    out: dict[str, list[dict[str, Any]]] = {}
    for (tag, _sql), doc in zip(_QUERIES, docs, strict=True):
        if not doc.get('ok'):
            raise _SetupError(f'query for {tag!r} failed: {json.dumps(doc, indent=2)}')
        columns: list[str] = doc.get('columns') or []
        rows: list[list[Any]] = doc.get('rows') or []
        out[tag] = [dict(zip(columns, r, strict=True)) for r in rows]
    return out


def _iter_json_docs(text: str) -> list[dict[str, Any]]:
    """Parse a stream of whitespace-separated JSON objects.

    Asserts the entire stream was consumed — a trailing non-JSON warning from
    Blender would otherwise silently drop a query result.
    """
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
    # Trailing whitespace was consumed by the inner loop; check we're at EOF.
    while i < n and text[i].isspace():
        i += 1
    if i != n:
        raise ValueError(f'unparsed trailing content at offset {i}/{n}: {text[i : i + 80]!r}')
    return out


# ---------------------------------------------------------------------------
# Generators — one per marker kind.


# Sequences that would confuse the marker scanner if they leaked into a cell.
# We wrap them in backticks so they render as code spans and the regex above
# never matches them.
_DANGEROUS_HTML_TOKENS = ('<!--', '-->')


def _md_escape_cell(text: str) -> str:
    """Make a cell safe for a GitHub-flavoured markdown table.

    Tables only need pipes escaped and newlines flattened; we also wrap any
    literal HTML-comment open/close tokens in backticks so a future hint can't
    masquerade as a marker.
    """
    out = text.replace('|', r'\|').replace('\n', ' ').strip()
    for tok in _DANGEROUS_HTML_TOKENS:
        # Idempotent: only wrap if not already in backticks. We don't try to
        # be clever here — a literal `<!--` in a cell is exotic enough that
        # always wrapping it is fine even if it was already in code-span.
        if tok in out:
            out = out.replace(tok, f'`{tok}`')
    return out


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


def _gen_scalars(data: dict[str, list[dict[str, Any]]]) -> str:
    """Non-verb / non-escape-hatch scalar functions (currently just `grep`).

    Table layout mirrors `escape-hatches` so the two read consistently. Kept
    as its own kind because scalars have a distinct flavour (table-valued in
    spirit) and lumping them with escape hatches misleads readers.
    """
    rows = [r for r in data['functions'] if r['kind'] == 'scalar']
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


# Scalar generators — return a single token, no surrounding newlines. The
# `_rewrite` helper detects single-line bodies and emits them inline so a count
# can live inside prose: `…now exposes <!-- … -->80<!-- /… --> tables…`.


def _gen_vtable_count(data: dict[str, list[dict[str, Any]]]) -> str:
    return str(len(data['vtables']))


def _gen_writable_table_count(data: dict[str, list[dict[str, Any]]]) -> str:
    return str(sum(1 for r in data['vtables'] if int(r['writable'])))


def _gen_verb_count(data: dict[str, list[dict[str, Any]]]) -> str:
    return str(sum(1 for r in data['functions'] if r['kind'] == 'verb'))


def _gen_function_count(data: dict[str, list[dict[str, Any]]]) -> str:
    return str(len(data['functions']))


Generator = Callable[[dict[str, list[dict[str, Any]]]], str]

_GENERATORS: dict[str, Generator] = {
    'vtables': _gen_vtables,
    'writable-tables': _gen_writable_tables,
    'verbs': _gen_verbs,
    'escape-hatches': _gen_escape_hatches,
    'scalars': _gen_scalars,
    'vtable-count': _gen_vtable_count,
    'writable-table-count': _gen_writable_table_count,
    'verb-count': _gen_verb_count,
    'function-count': _gen_function_count,
}


# ---------------------------------------------------------------------------
# Marker rewrite — pure string transformation, no I/O.


def _rewrite(text: str, data: dict[str, list[dict[str, Any]]], path: Path) -> str:
    """Replace every marker body in `text` with the generated content.

    Multi-line generator output (e.g. the table generators) is wrapped with
    leading/trailing newlines so it sits on its own block. Single-line output
    (the scalar count generators) is emitted inline — `<!-- ... -->80<!-- ... -->`.
    """

    def _sub(match: re.Match[str]) -> str:
        kind = match.group('kind')
        gen = _GENERATORS.get(kind)
        if gen is None:
            raise _SetupError(
                f'{path}: unknown marker kind {kind!r}. Known: {", ".join(sorted(_GENERATORS))}.'
            )
        body = gen(data)
        if '\n' in body:
            # Multi-line block — pad with newlines so the open/close markers
            # sit on their own lines.
            if not body.startswith('\n'):
                body = '\n' + body
            if not body.endswith('\n'):
                body = body + '\n'
        # Single-line bodies are emitted verbatim (inline substitution).
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


def _validate_markers() -> None:
    """Up-front sanity check on every marker in every skill file.

    Catches three classes of mistake before we waste a Blender boot:

    * unknown marker kind (typo in the open or close token).
    * orphan markers (open without matching close, or vice versa).
    * duplicate same-kind markers in one file (re.sub would silently replace
      both with identical content — almost certainly a copy-paste bug).
    """
    known = set(_GENERATORS)
    for path in _markdown_files():
        text = path.read_text(encoding='utf-8')
        rel = path.relative_to(_REPO_ROOT)

        # 1. Strip well-formed marker pairs first so anything left over is an orphan.
        stripped = _MARKER_RE.sub('', text)

        # 2. Anything that still looks like our token is an orphan / typo.
        leftover_open = list(_OPEN_MARKER_RE.finditer(stripped))
        leftover_close = list(_CLOSE_MARKER_RE.finditer(stripped))
        if leftover_open or leftover_close:
            tokens = [m.group(0) for m in (*leftover_open, *leftover_close)]
            raise _SetupError(
                f'{rel}: orphan BSQL-AUTOGEN marker(s) with no matching pair: '
                f'{tokens}. Fix the open/close tokens by hand.'
            )
        # Typo scan — run on the original text so we catch tokens hiding inside
        # a well-formed pair too. Anything matching the loose pattern but not
        # the canonical `<!-- (/?)BSQL-AUTOGEN:<kind> -->` form is a typo.
        typos = [
            m.group(0)
            for m in _LOOSE_MARKER_RE.finditer(text)
            if not _CANONICAL_MARKER_RE.fullmatch(m.group(0))
        ]
        if typos:
            raise _SetupError(
                f'{rel}: marker-token typo(s) detected: {typos}. '
                f'The canonical form is `<!-- BSQL-AUTOGEN:<kind> -->` and '
                f'`<!-- /BSQL-AUTOGEN:<kind> -->`.'
            )

        # 3. Unknown-kind + duplicate-kind checks on the well-formed pairs.
        seen: dict[str, int] = {}
        for m in _MARKER_RE.finditer(text):
            kind = m.group('kind')
            if kind not in known:
                raise _SetupError(
                    f'{rel}: unknown marker kind {kind!r}. Known: {", ".join(sorted(known))}.'
                )
            seen[kind] = seen.get(kind, 0) + 1
        dupes = [k for k, n in seen.items() if n > 1]
        if dupes:
            raise _SetupError(
                f'{rel}: duplicate same-kind marker(s) in one file: {dupes}. '
                f'Two identical blocks render identically — almost certainly a mistake. '
                f'Remove one or rename one of the kinds.'
            )


# ---------------------------------------------------------------------------
# Atomic write helper.


def _atomic_write(path: Path, text: str) -> None:
    """Replace `path` with `text` atomically (write to a sibling tmp + rename).

    Standard pattern — protects against half-written files if the process is
    killed mid-write. Sibling-of-target so the rename is on the same fs.
    """
    parent = path.parent
    fd, tmp_name = tempfile.mkstemp(dir=str(parent), prefix=f'.{path.name}.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup if the rename never happened.
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


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
        return EXIT_DRIFT
    return EXIT_OK


def _write(data: dict[str, list[dict[str, Any]]]) -> int:
    changed = 0
    for path in _files_with_markers():
        original = path.read_text(encoding='utf-8')
        regenerated = _rewrite(original, data, path)
        if regenerated != original:
            _atomic_write(path, regenerated)
            rel = path.relative_to(_REPO_ROOT)
            sys.stdout.write(f'updated {rel}\n')
            changed += 1
    if changed == 0:
        sys.stdout.write('no changes\n')
    return EXIT_OK


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

    try:
        # Validate first — saves ~1.4s of Blender boot on a marker typo.
        _validate_markers()
        data = _fetch_live_data()
    except _SetupError as exc:
        sys.stderr.write(f'regen_skills setup error: {exc}\n')
        return EXIT_SETUP

    try:
        if args.write:
            return _write(data)
        return _check(data)
    except _SetupError as exc:
        # _rewrite can also raise _SetupError (unknown kind reached at sub time).
        sys.stderr.write(f'regen_skills setup error: {exc}\n')
        return EXIT_SETUP


if __name__ == '__main__':
    raise SystemExit(main())
