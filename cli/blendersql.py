"""blendersql — query a .blend file with SQL from the command line.

Spawns a headless Blender that hosts the extension's HTTP server, then talks
to it over HTTP. Three modes:

    blendersql -s file.blend -q "SELECT ..."   one query, JSON to stdout
    blendersql -s file.blend -f queries.sql    each statement, JSON to stdout
    blendersql -s file.blend -i                interactive REPL
    blendersql -s file.blend --http [port]     server-only (curl it)

stdlib only — apsw lives inside Blender's Python via the extension.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Any

_readline: ModuleType | None
try:  # readline gives history/editing in the REPL; degrade gracefully without it.
    import readline as _readline
except ImportError:  # pragma: no cover - platform dependent
    _readline = None

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
_RUNNER_PY = _HERE / 'runner.py'
_MANIFEST = _REPO_ROOT / 'blender_manifest.toml'

if __package__:
    from ._blender import find_blender, pick_free_port, port_is_free
else:  # invoked as a script: `python cli/blendersql.py`
    sys.path.insert(0, str(_HERE))
    from _blender import find_blender, pick_free_port, port_is_free  # type: ignore[no-redef]

_DEFAULT_HTTP_PORT = 8174
_READY_TIMEOUT_S = 60.0
_SHUTDOWN_TIMEOUT_S = 5.0


def _eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def _manifest_version() -> str:
    text = _MANIFEST.read_text(encoding='utf-8')
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('version'):
            _, _, rhs = line.partition('=')
            return rhs.strip().strip('"').strip("'")
    return 'unknown'


# ---------------------------------------------------------------------------
# HTTP helpers


def _http_get(url: str, timeout: float = 2.0) -> tuple[int, bytes]:
    req = urllib.request.Request(url, method='GET')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def _http_post(url: str, body: str = '', timeout: float = 60.0) -> tuple[int, bytes]:
    data = body.encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def _post_query(base_url: str, sql: str, timeout: float = 60.0) -> dict[str, Any]:
    try:
        _, body = _http_post(base_url + '/query', sql, timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read()
    return json.loads(body.decode('utf-8'))


# ---------------------------------------------------------------------------
# Subprocess lifecycle


class _BlenderSession:
    def __init__(self, proc: subprocess.Popen[str], base_url: str) -> None:
        self.proc = proc
        self.base_url = base_url

    def shutdown(self) -> None:
        with contextlib.suppress(Exception):
            _http_post(self.base_url + '/shutdown', '', timeout=2.0)
        try:
            self.proc.wait(timeout=_SHUTDOWN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.wait(timeout=2.0)


def _spawn_runner(
    blender: str, blend: Path, bind: str, port: int, save: bool
) -> tuple[subprocess.Popen[str], str]:
    base_url = f'http://{bind}:{port}'
    env = os.environ.copy()
    env['BLENDERSQL_CLI_PORT'] = str(port)
    env['BLENDERSQL_CLI_BIND'] = bind
    if save:
        env['BLENDERSQL_CLI_SAVE'] = '1'
    else:
        env.pop('BLENDERSQL_CLI_SAVE', None)

    cmd = [
        blender,
        '--background',
        '--factory-startup',
        '--python-use-system-env',
        str(blend),
        '--python',
        str(_RUNNER_PY),
    ]
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait_ready(proc, base_url)
    return proc, base_url


def _wait_ready(proc: subprocess.Popen[str], base_url: str) -> None:
    deadline = time.monotonic() + _READY_TIMEOUT_S
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            _drain_dead(proc, 'Blender exited before the server became ready')
        try:
            status, _ = _http_get(base_url + '/status', timeout=1.0)
            if status == 200:
                return
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            last_err = exc
        time.sleep(0.1)
    with contextlib.suppress(Exception):
        proc.kill()
        proc.wait(timeout=2)
    raise SystemExit(f'blendersql: server never became ready (last error: {last_err})')


def _drain_dead(proc: subprocess.Popen[str], prefix: str) -> None:
    out = ''
    err = ''
    with contextlib.suppress(Exception):
        out, err = proc.communicate(timeout=2)
    msg = [f'blendersql: {prefix} (exit code {proc.returncode}).']
    if out.strip():
        msg.append(f'--- blender stdout ---\n{out.rstrip()}')
    if err.strip():
        msg.append(f'--- blender stderr ---\n{err.rstrip()}')
    raise SystemExit('\n'.join(msg))


# ---------------------------------------------------------------------------
# Output formatting


def _print_json(result: dict[str, Any]) -> None:
    print(json.dumps(result, indent=2))


def _render_table(result: dict[str, Any]) -> str:
    columns = result.get('columns') or []
    rows = result.get('rows') or []
    if not columns:
        return json.dumps(result)
    str_rows = [[('NULL' if v is None else str(v)) for v in row] for row in rows]
    widths = [len(c) for c in columns]
    for row in str_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    sep = '+' + '+'.join('-' * (w + 2) for w in widths) + '+'
    lines = [sep]
    lines.append('| ' + ' | '.join(c.ljust(widths[i]) for i, c in enumerate(columns)) + ' |')
    lines.append(sep)
    for row in str_rows:
        lines.append('| ' + ' | '.join(cell.ljust(widths[i]) for i, cell in enumerate(row)) + ' |')
    lines.append(sep)
    lines.append(
        f'{result.get("row_count", len(rows))} row(s) in {result.get("duration_ms", "?")} ms'
    )
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Modes


def _run_statements(session: _BlenderSession, statements: list[str]) -> int:
    last_ok = True
    for sql in statements:
        result = _post_query(session.base_url, sql)
        _print_json(result)
        last_ok = bool(result.get('ok'))
    return 0 if last_ok else 1


def _split_sql(text: str) -> list[str]:
    return [stmt.strip() for stmt in text.split(';') if stmt.strip()]


_REPL_HELP = """\
Commands:
  .help                this message
  .tables              list tables
  .schema <table>      show CREATE statement for <table>
  .q / .quit / .exit   shut down and exit
Anything else is sent to /query."""


def _repl(session: _BlenderSession) -> int:
    if _readline is not None and sys.stdin.isatty():
        with contextlib.suppress(Exception):
            _readline.parse_and_bind('tab: complete')
    is_tty = sys.stdin.isatty()
    while True:
        try:
            line = input('blendersql> ' if is_tty else '')
        except EOFError:
            if is_tty:
                print()
            break
        except KeyboardInterrupt:
            print()
            continue
        line = line.strip()
        if not line:
            continue
        if line in ('.q', '.quit', '.exit'):
            break
        if line == '.help':
            print(_REPL_HELP)
            continue
        if line == '.tables':
            line = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        elif line.startswith('.schema'):
            parts = line.split(None, 1)
            if len(parts) != 2:
                print('usage: .schema <table>')
                continue
            tbl = parts[1].strip().strip('"').strip("'")
            line = f"SELECT sql FROM sqlite_master WHERE name='{tbl}'"
        elif line.startswith('.'):
            print(f'unknown command: {line}  (try .help)')
            continue
        result = _post_query(session.base_url, line)
        if result.get('ok'):
            print(_render_table(result))
        else:
            print(json.dumps(result, indent=2))
    return 0


def _serve_only(session: _BlenderSession, bind: str, port: int) -> int:
    print(f'BlenderSQL HTTP server: http://{bind}:{port}', flush=True)

    stop = False

    def _on_signal(signum: int, _frame: Any) -> None:
        nonlocal stop
        stop = True
        # Forward to the Blender subprocess so it shuts the server down cleanly.
        with contextlib.suppress(Exception):
            session.proc.send_signal(signum)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    while not stop and session.proc.poll() is None:
        time.sleep(0.2)

    with contextlib.suppress(Exception):
        _http_post(session.base_url + '/shutdown', '', timeout=2.0)
    try:
        session.proc.wait(timeout=_SHUTDOWN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        session.proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            session.proc.wait(timeout=2.0)
    return 0


# ---------------------------------------------------------------------------
# Argument parsing / entry point


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='blendersql',
        description='Query a .blend file with SQL via a headless Blender.',
    )
    p.add_argument('-s', '--source', metavar='FILE', help='path to the .blend file')
    p.add_argument('--version', action='store_true', help='print the extension version and exit')

    mode = p.add_mutually_exclusive_group()
    mode.add_argument('-q', '--query', metavar='SQL', help='run one SQL statement and print JSON')
    mode.add_argument(
        '-f', '--file', metavar='SQLFILE', help='run statements from a .sql file (semicolon-split)'
    )
    mode.add_argument('-i', '--interactive', action='store_true', help='interactive SQL REPL')
    mode.add_argument(
        '--http',
        nargs='?',
        const=_DEFAULT_HTTP_PORT,
        type=int,
        metavar='PORT',
        help=f'server-only mode (default port {_DEFAULT_HTTP_PORT})',
    )

    p.add_argument(
        '-w', '--write', action='store_true', help='save the .blend on exit (persist changes)'
    )
    p.add_argument('--bind', default='127.0.0.1', metavar='ADDR', help='server bind address')
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(_manifest_version())
        return 0

    if not args.source:
        parser.error('the -s/--source argument is required (except with --version)')
    blend = Path(args.source).expanduser()
    if not blend.exists():
        _eprint(f'blendersql: .blend file not found: {blend}')
        return 2

    if not (args.query or args.file or args.interactive or args.http is not None):
        parser.error('one of -q/--query, -f/--file, -i/--interactive, --http is required')

    blender = find_blender()
    if blender is None:
        _eprint(
            'blendersql: Blender executable not found (set $BLENDER or install at the default location)'
        )
        return 2

    save = args.write
    if args.http is not None and args.http != 0 and port_is_free(args.http, args.bind):
        port = args.http
    else:
        port = pick_free_port()

    try:
        proc, base_url = _spawn_runner(blender, blend, args.bind, port, save)
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        _eprint(f'blendersql: failed to start Blender: {exc}')
        return 2
    session = _BlenderSession(proc, base_url)

    try:
        if args.http is not None:
            return _serve_only(session, args.bind, port)
        if args.query is not None:
            return _run_statements(session, [args.query])
        if args.file is not None:
            sql_path = Path(args.file).expanduser()
            if not sql_path.exists():
                _eprint(f'blendersql: SQL file not found: {sql_path}')
                return 2
            statements = _split_sql(sql_path.read_text(encoding='utf-8'))
            if not statements:
                _eprint('blendersql: SQL file contains no statements')
                return 2
            return _run_statements(session, statements)
        if args.interactive:
            return _repl(session)
        return 2
    finally:
        if args.http is None:
            session.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
