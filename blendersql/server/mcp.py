"""HTTP-native MCP endpoint — Model Context Protocol over JSON-RPC 2.0.

Single endpoint `/mcp` mounted from `http.py`. Stateless, stdlib-only.
No SSE; plain JSON responses. The methods implemented are the minimal set
claude code's MCP client needs: `initialize`, `initialized`, `tools/list`,
`tools/call`, `ping`. Six tools mirror the bench wrapper at
`experiments/compare/blendersql_mcp/server.py`, but instead of HTTP self-
calling `/query` we route directly through the engine (which already
marshals to Blender's main thread via the bridge).

Note on bpy isolation: this module itself is pure-stdlib (no `bpy` import),
and the SQL runner is dependency-injected by `http.py` so the dispatcher
can be unit-tested without booting Blender. The sibling `http.py` and the
`SqlRunner` it injects DO touch `bpy` (via the bridge). The package's
`__init__.py` re-exports from `http`, so `import blendersql.server` pulls
`bpy` in — import `blendersql.server.mcp` directly to keep that isolation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from ..sql.functions.registry import functions_registry, functions_version

# JSON-RPC 2.0 error codes
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603

# Stable MCP protocol version claude code's client accepts.
_PROTOCOL_VERSION = '2024-11-05'
_SERVER_NAME = 'blendersql'
_SERVER_VERSION = '0.0.1'

_INSTRUCTIONS = (
    'BlenderSQL exposes the running Blender as a SQL database. First move: '
    'call `list_tables` (or run `SELECT * FROM bsql_tables` via `query`) to '
    'discover the introspection vtables, then `describe_table` / '
    '`describe_function` to learn the column and verb signatures before '
    'writing real queries.'
)

# `\Z` rather than `$` so a trailing newline can't sneak past `match()`.
_TABLE_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*\Z')
_READ_PREFIXES = ('SELECT', 'WITH', 'PRAGMA', 'EXPLAIN')

# Cache the snapshot of side-effecting function names keyed by the registry
# version. `functions_version()` bumps on every register_function call, so
# this auto-invalidates when the engine reinitialises.
_SIDE_EFFECT_CACHE: tuple[int, tuple[str, ...], re.Pattern[str] | None] = (-1, (), None)


def _side_effect_pattern() -> tuple[tuple[str, ...], re.Pattern[str] | None]:
    """Return (names, regex) for all functions registered with side_effects=True.

    Cached against `functions_version()` so the scan cost is one-shot per
    registration epoch. Returns `(names, None)` when nothing is registered
    yet (the regex would be invalid with an empty alternation).
    """
    global _SIDE_EFFECT_CACHE
    version = functions_version()
    if _SIDE_EFFECT_CACHE[0] == version:
        return _SIDE_EFFECT_CACHE[1], _SIDE_EFFECT_CACHE[2]
    names = tuple(sorted(name for name, meta in functions_registry().items() if meta.side_effects))
    pattern: re.Pattern[str] | None = None
    if names:
        # `\b<name>\(` is a coarse syntactic match — it false-positives inside
        # SQL string literals (e.g. `SELECT '... save( ...'`). We accept the
        # over-rejection for v1: it errs on the safe side for a read-only
        # contract. A proper SQL tokenizer is out of scope for this fix.
        pattern = re.compile(r'\b(?:' + '|'.join(re.escape(n) for n in names) + r')\s*\(')
    _SIDE_EFFECT_CACHE = (version, names, pattern)
    return names, pattern


def _find_side_effect_call(sql: str) -> str | None:
    """Return the first side-effecting function name called in `sql`, or None.

    Caveat: a coarse regex scan — `save(` inside a string literal is a
    false positive. We accept the over-rejection for `query()`'s read-only
    contract (safer to reject than to allow a write through). Nested calls
    like `SELECT length(save())` are caught because `save(` still appears.
    """
    _, pattern = _side_effect_pattern()
    if pattern is None:
        return None
    match = pattern.search(sql)
    if match is None:
        return None
    # Strip the trailing `(` plus any whitespace the regex tolerated.
    return match.group(0).rstrip('(').rstrip()


# Type alias for the SQL runner injected from http.py — keeps this module
# free of any bpy / engine import so it stays testable in isolation.
SqlRunner = Callable[[str], dict[str, Any]]


# ---------------------------------------------------------------------------
# Tool catalog


_TOOL_QUERY = {
    'name': 'query',
    'description': (
        'Run a read-only SQL query against the running Blender. Accepts '
        'SELECT / WITH / PRAGMA / EXPLAIN. Writes (INSERT/UPDATE/DELETE, '
        'function calls with side effects) are rejected — use `execute` '
        'for those. Returns JSON: {ok, columns, rows, row_count, '
        'duration_ms} on success; {ok: false, error: ...} on failure.'
    ),
    'inputSchema': {
        'type': 'object',
        'properties': {
            'sql': {'type': 'string', 'description': 'Read-only SQL to execute.'},
        },
        'required': ['sql'],
        'additionalProperties': False,
    },
}

_TOOL_EXECUTE = {
    'name': 'execute',
    'description': (
        'Run any SQL — including writes and side-effecting function calls '
        '(bpy_eval, bpy_exec, bpy_op, typed verbs like add_object, save, '
        'render, ...). Use `list_functions()` to discover available '
        'functions. Returns the same JSON shape as query().'
    ),
    'inputSchema': {
        'type': 'object',
        'properties': {
            'sql': {'type': 'string', 'description': 'Any SQL to execute.'},
        },
        'required': ['sql'],
        'additionalProperties': False,
    },
}

_TOOL_LIST_TABLES = {
    'name': 'list_tables',
    'description': (
        "List every virtual table in the running Blender's SQL schema. "
        'Sourced live from `bsql_tables`. Returns columns [name, writable, '
        'domain, description]. `writable=1` means the table accepts '
        'INSERT/UPDATE/DELETE directly via `execute`. Use '
        'describe_table(name) for per-column detail.'
    ),
    'inputSchema': {
        'type': 'object',
        'properties': {},
        'additionalProperties': False,
    },
}

_TOOL_DESCRIBE_TABLE = {
    'name': 'describe_table',
    'description': (
        'Return column info for one virtual table from `bsql_columns`: '
        'name, type, writable, pk, identifier, insert_only, hint. Probes '
        "`bsql_tables` first so typo'd / wrong-case names surface as "
        '`unknown table: <name>`.'
    ),
    'inputSchema': {
        'type': 'object',
        'properties': {
            'name': {'type': 'string', 'description': 'Table name to describe.'},
        },
        'required': ['name'],
        'additionalProperties': False,
    },
}

_TOOL_LIST_FUNCTIONS = {
    'name': 'list_functions',
    'description': (
        'List BlenderSQL SQL scalar functions usable inside `execute(...)`. '
        'Sourced live from `bsql_functions`: name, kind (escape_hatch / '
        'verb / scalar), arity (-1 = variadic), description. Use '
        "describe_function(name) to see a function's parameters."
    ),
    'inputSchema': {
        'type': 'object',
        'properties': {},
        'additionalProperties': False,
    },
}

_TOOL_DESCRIBE_FUNCTION = {
    'name': 'describe_function',
    'description': (
        'Return parameter signature for one SQL scalar function from '
        '`bsql_function_params`: position, name, type, required, '
        "default_json, hint. Probes `bsql_functions` first so typo'd "
        'names surface as `unknown function: <name>`.'
    ),
    'inputSchema': {
        'type': 'object',
        'properties': {
            'name': {'type': 'string', 'description': 'Function name to describe.'},
        },
        'required': ['name'],
        'additionalProperties': False,
    },
}

TOOLS: list[dict[str, Any]] = [
    _TOOL_QUERY,
    _TOOL_EXECUTE,
    _TOOL_LIST_TABLES,
    _TOOL_DESCRIBE_TABLE,
    _TOOL_LIST_FUNCTIONS,
    _TOOL_DESCRIBE_FUNCTION,
]

TOOL_NAMES = frozenset(t['name'] for t in TOOLS)


# ---------------------------------------------------------------------------
# Helpers


def _starts_with_read(sql: str) -> bool:
    """Match the bench wrapper's leading-comment-stripping read check."""
    s = sql.lstrip()
    while s.startswith(('--', '/*')):
        if s.startswith('--'):
            nl = s.find('\n')
            s = '' if nl == -1 else s[nl + 1 :].lstrip()
        else:
            end = s.find('*/')
            s = '' if end == -1 else s[end + 2 :].lstrip()
    return s.upper().startswith(_READ_PREFIXES)


def _rpc_error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {'code': code, 'message': message}
    if data is not None:
        err['data'] = data
    return {'jsonrpc': '2.0', 'id': req_id, 'error': err}


def _rpc_result(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {'jsonrpc': '2.0', 'id': req_id, 'result': result}


def _tool_text(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    # allow_nan=False forces stdlib to raise on NaN/Infinity rather than emit
    # the JS-only `NaN` / `Infinity` literals that aren't valid JSON. The
    # engine's `_jsonify` already coerces non-finite floats to None, so this
    # is belt-and-braces — if something slips through we want a loud
    # ValueError, not silent corruption on the wire.
    return {
        'content': [{'type': 'text', 'text': json.dumps(payload, allow_nan=False)}],
        'isError': is_error,
    }


# ---------------------------------------------------------------------------
# Tool handlers — each takes the parsed arguments dict + a SqlRunner.


def _tool_query(args: dict[str, Any], run_sql: SqlRunner) -> dict[str, Any]:
    sql = args.get('sql')
    if not isinstance(sql, str):
        return _tool_text({'ok': False, 'error': "missing or invalid 'sql' argument"})
    if not _starts_with_read(sql):
        return _tool_text(
            {
                'ok': False,
                'error': (
                    'query() is read-only. Use execute() for writes or '
                    'function calls with side effects.'
                ),
            }
        )
    side_effect = _find_side_effect_call(sql)
    if side_effect is not None:
        return _tool_text(
            {
                'ok': False,
                'error': (f'query() is read-only; {side_effect} has side effects, use execute()'),
            }
        )
    return _tool_text(run_sql(sql))


def _tool_execute(args: dict[str, Any], run_sql: SqlRunner) -> dict[str, Any]:
    sql = args.get('sql')
    if not isinstance(sql, str):
        return _tool_text({'ok': False, 'error': "missing or invalid 'sql' argument"})
    return _tool_text(run_sql(sql))


def _tool_list_tables(_args: dict[str, Any], run_sql: SqlRunner) -> dict[str, Any]:
    return _tool_text(
        run_sql('SELECT name, writable, domain, description FROM bsql_tables ORDER BY name')
    )


def _tool_describe_table(args: dict[str, Any], run_sql: SqlRunner) -> dict[str, Any]:
    name = args.get('name')
    if not isinstance(name, str) or not _TABLE_NAME_RE.match(name):
        return _tool_text({'ok': False, 'error': f'invalid table name: {name!r}'})
    probe = run_sql(f"SELECT 1 FROM bsql_tables WHERE name='{name}' LIMIT 1")
    if not probe.get('ok'):
        return _tool_text(probe)
    if not (probe.get('rows') or []):
        return _tool_text({'ok': False, 'error': f'unknown table: {name}'})
    sql = (
        'SELECT name, type, writable, pk, identifier, insert_only, hint '
        f'FROM bsql_columns WHERE "table" = \'{name}\' ORDER BY rowid'
    )
    data = run_sql(sql)
    if data.get('ok') and (data.get('rows') or []):
        return _tool_text(data)
    # Registered table with no bsql_columns rows — cheap PRAGMA fallback.
    return _tool_text(run_sql(f'PRAGMA table_info({name})'))


def _tool_list_functions(_args: dict[str, Any], run_sql: SqlRunner) -> dict[str, Any]:
    return _tool_text(
        run_sql('SELECT name, kind, arity, description FROM bsql_functions ORDER BY name')
    )


def _tool_describe_function(args: dict[str, Any], run_sql: SqlRunner) -> dict[str, Any]:
    name = args.get('name')
    if not isinstance(name, str) or not _TABLE_NAME_RE.match(name):
        return _tool_text({'ok': False, 'error': f'invalid function name: {name!r}'})
    probe = run_sql(f"SELECT 1 FROM bsql_functions WHERE name='{name}' LIMIT 1")
    if not probe.get('ok'):
        return _tool_text(probe)
    if not (probe.get('rows') or []):
        return _tool_text({'ok': False, 'error': f'unknown function: {name}'})
    sql = (
        'SELECT position, name, type, required, default_json, hint '
        f"FROM bsql_function_params WHERE function = '{name}' ORDER BY position"
    )
    return _tool_text(run_sql(sql))


_TOOL_HANDLERS: dict[str, Callable[[dict[str, Any], SqlRunner], dict[str, Any]]] = {
    'query': _tool_query,
    'execute': _tool_execute,
    'list_tables': _tool_list_tables,
    'describe_table': _tool_describe_table,
    'list_functions': _tool_list_functions,
    'describe_function': _tool_describe_function,
}


# ---------------------------------------------------------------------------
# JSON-RPC dispatch


def dispatch(raw_body: bytes, run_sql: SqlRunner) -> tuple[int, bytes] | None:
    """Handle one HTTP POST to /mcp.

    Returns (status, body) for request messages, or `None` for notifications
    (no `id` field) — in which case the caller should reply 202 Accepted with
    an empty body. A `None` return for a parse error is not possible: parse
    errors get id=null per JSON-RPC 2.0.
    """
    try:
        text = raw_body.decode('utf-8')
    except UnicodeDecodeError:
        return 200, _encode(_rpc_error(None, _PARSE_ERROR, 'invalid utf-8'))

    try:
        msg = json.loads(text) if text else None
    except json.JSONDecodeError as exc:
        return 200, _encode(_rpc_error(None, _PARSE_ERROR, f'parse error: {exc.msg}'))

    if not isinstance(msg, dict):
        return 200, _encode(_rpc_error(None, _INVALID_REQUEST, 'request must be a JSON object'))

    if msg.get('jsonrpc') != '2.0':
        return 200, _encode(
            _rpc_error(msg.get('id'), _INVALID_REQUEST, "missing or wrong 'jsonrpc' field")
        )

    method = msg.get('method')
    if not isinstance(method, str):
        return 200, _encode(
            _rpc_error(msg.get('id'), _INVALID_REQUEST, "missing or non-string 'method'")
        )

    params = msg.get('params') or {}
    if not isinstance(params, dict):
        return 200, _encode(
            _rpc_error(msg.get('id'), _INVALID_PARAMS, "'params' must be an object")
        )

    is_notification = 'id' not in msg
    req_id = msg.get('id')

    try:
        result = _handle_method(method, params, run_sql)
    except _MethodNotFound:
        if is_notification:
            return None
        return 200, _encode(_rpc_error(req_id, _METHOD_NOT_FOUND, f'method not found: {method}'))
    except _InvalidParams as exc:
        if is_notification:
            return None
        return 200, _encode(_rpc_error(req_id, _INVALID_PARAMS, str(exc)))
    except Exception as exc:
        if is_notification:
            return None
        return 200, _encode(_rpc_error(req_id, _INTERNAL_ERROR, f'{type(exc).__name__}: {exc}'))

    if is_notification or result is None:
        # Notifications get no response body; handler returned sentinel None
        # to indicate "no reply" (e.g. `initialized` notification).
        return None

    return 200, _encode(_rpc_result(req_id, result))


class _MethodNotFound(Exception):
    """Raised internally to map to JSON-RPC -32601."""


class _InvalidParams(Exception):
    """Raised internally to map to JSON-RPC -32602."""


def _handle_method(
    method: str, params: dict[str, Any], run_sql: SqlRunner
) -> dict[str, Any] | None:
    if method == 'initialize':
        return {
            'protocolVersion': _PROTOCOL_VERSION,
            'capabilities': {'tools': {}},
            'serverInfo': {'name': _SERVER_NAME, 'version': _SERVER_VERSION},
            'instructions': _INSTRUCTIONS,
        }
    if method == 'initialized' or method == 'notifications/initialized':
        return None  # Notification — no response.
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': TOOLS}
    if method == 'tools/call':
        return _handle_tools_call(params, run_sql)
    raise _MethodNotFound(method)


def _handle_tools_call(params: dict[str, Any], run_sql: SqlRunner) -> dict[str, Any]:
    name = params.get('name')
    if not isinstance(name, str):
        raise _InvalidParams("'name' must be a string")
    args = params.get('arguments') or {}
    if not isinstance(args, dict):
        raise _InvalidParams("'arguments' must be an object")
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        return {
            'content': [{'type': 'text', 'text': f'unknown tool: {name}'}],
            'isError': True,
        }
    return handler(args, run_sql)


def _encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, allow_nan=False).encode('utf-8')
