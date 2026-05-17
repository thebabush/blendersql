"""Protocol-level tests for the /mcp endpoint.

Exercises JSON-RPC 2.0 dispatch (initialize, tools/list, tools/call, ping,
unknown methods, malformed bodies) against the live Blender HTTP server
booted by the session-scoped `blender_server` fixture in conftest.py. The
HTTP self-call is intentional — we want to verify the wire surface, not
just the python dispatcher.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import pytest


def _mcp_post(
    base_url: str,
    body: bytes,
    timeout: float = 30.0,
    content_type: str | None = 'application/json',
) -> tuple[int, bytes]:
    headers = {'Content-Type': content_type} if content_type is not None else {}
    req = urllib.request.Request(
        base_url + '/mcp',
        data=body,
        method='POST',
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _mcp_get(base_url: str, timeout: float = 5.0) -> int:
    req = urllib.request.Request(base_url + '/mcp', method='GET')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _rpc(
    base_url: str, method: str, params: dict[str, Any] | None = None, req_id: Any = 1
) -> dict[str, Any]:
    body: dict[str, Any] = {'jsonrpc': '2.0', 'method': method, 'id': req_id}
    if params is not None:
        body['params'] = params
    _, raw = _mcp_post(base_url, json.dumps(body).encode('utf-8'))
    return json.loads(raw.decode('utf-8'))


def _tool_call(base_url: str, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return _rpc(base_url, 'tools/call', {'name': name, 'arguments': arguments or {}})


def _content_text(reply: dict[str, Any]) -> str:
    return reply['result']['content'][0]['text']


# ---------------------------------------------------------------------------
# Tests


def test_initialize_handshake(blender_server: dict[str, Any]) -> None:
    """initialize returns protocolVersion, tools capability, serverInfo, instructions."""
    reply = _rpc(
        blender_server['base_url'],
        'initialize',
        {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {'name': 'pytest', 'version': '0'},
        },
    )
    assert reply.get('jsonrpc') == '2.0'
    assert reply.get('id') == 1
    result = reply['result']
    assert result['protocolVersion'] == '2024-11-05'
    assert 'tools' in result['capabilities']
    assert result['serverInfo']['name'] == 'blendersql'
    assert isinstance(result['serverInfo']['version'], str) and result['serverInfo']['version']
    assert isinstance(result['instructions'], str)
    assert result['instructions'].strip()


def test_tools_list_returns_six_named_tools(blender_server: dict[str, Any]) -> None:
    reply = _rpc(blender_server['base_url'], 'tools/list')
    tools = reply['result']['tools']
    names = sorted(t['name'] for t in tools)
    assert names == sorted(
        [
            'query',
            'execute',
            'list_tables',
            'describe_table',
            'list_functions',
            'describe_function',
        ]
    )
    for tool in tools:
        assert isinstance(tool['description'], str) and tool['description']
        schema = tool['inputSchema']
        assert schema['type'] == 'object'
        assert 'properties' in schema


def test_tools_call_list_tables(blender_server: dict[str, Any]) -> None:
    reply = _tool_call(blender_server['base_url'], 'list_tables')
    payload = json.loads(_content_text(reply))
    assert payload['ok'] is True
    table_names = {row[0] for row in payload['rows']}
    assert 'bsql_tables' in table_names
    assert reply['result']['isError'] is False


def test_query_rejects_writes_structurally(blender_server: dict[str, Any]) -> None:
    """A write SQL through `query` is a structured error, not a tool-level one."""
    reply = _tool_call(blender_server['base_url'], 'query', {'sql': 'DELETE FROM objects'})
    assert reply['result']['isError'] is False
    payload = json.loads(_content_text(reply))
    assert payload['ok'] is False
    assert 'read-only' in payload['error']


def test_describe_function_known_verb(blender_server: dict[str, Any]) -> None:
    reply = _tool_call(blender_server['base_url'], 'describe_function', {'name': 'add_object'})
    payload = json.loads(_content_text(reply))
    assert payload['ok'] is True
    param_names = {row[1] for row in payload['rows']}
    # add_object has a `type` and `name` parameter per the verb signature.
    assert {'type', 'name'} <= param_names


def test_describe_table_unknown_returns_structured_error(blender_server: dict[str, Any]) -> None:
    reply = _tool_call(blender_server['base_url'], 'describe_table', {'name': 'nonexistent_table'})
    assert reply['result']['isError'] is False
    payload = json.loads(_content_text(reply))
    assert payload['ok'] is False
    assert 'unknown table' in payload['error']


def test_tools_call_unknown_tool_is_tool_level_error(blender_server: dict[str, Any]) -> None:
    reply = _tool_call(blender_server['base_url'], 'nonsense_tool')
    assert reply['result']['isError'] is True
    text = reply['result']['content'][0]['text']
    assert 'unknown tool' in text


def test_unknown_method_returns_minus_32601(blender_server: dict[str, Any]) -> None:
    reply = _rpc(blender_server['base_url'], 'not_a_method')
    assert 'error' in reply
    assert reply['error']['code'] == -32601


def test_malformed_json_returns_parse_error(blender_server: dict[str, Any]) -> None:
    _, raw = _mcp_post(blender_server['base_url'], b'{not valid json')
    reply = json.loads(raw.decode('utf-8'))
    assert reply['error']['code'] == -32700


def test_ping_returns_empty_result(blender_server: dict[str, Any]) -> None:
    reply = _rpc(blender_server['base_url'], 'ping')
    assert reply['result'] == {}


def test_initialized_notification_no_response_body(blender_server: dict[str, Any]) -> None:
    """A notification (no `id`) gets HTTP 202 with empty body."""
    body = json.dumps({'jsonrpc': '2.0', 'method': 'initialized'}).encode('utf-8')
    status, raw = _mcp_post(blender_server['base_url'], body)
    assert status == 202
    assert raw == b''


def test_get_mcp_returns_405_or_404(blender_server: dict[str, Any]) -> None:
    """GET /mcp isn't a JSON-RPC verb — the handler emits 404 (the default
    `do_GET` else-branch)."""
    status = _mcp_get(blender_server['base_url'])
    assert status in (404, 405)


def test_post_mcp_with_text_plain_returns_415(blender_server: dict[str, Any]) -> None:
    """Content-Type must be application/json on /mcp. /query keeps raw-body
    semantics so this enforcement is local to /mcp."""
    body = json.dumps({'jsonrpc': '2.0', 'method': 'ping', 'id': 1}).encode('utf-8')
    status, _ = _mcp_post(blender_server['base_url'], body, content_type='text/plain')
    assert status == 415


def test_post_mcp_with_charset_param_accepted(blender_server: dict[str, Any]) -> None:
    """`application/json; charset=utf-8` should match — parameters ignored."""
    body = json.dumps({'jsonrpc': '2.0', 'method': 'ping', 'id': 1}).encode('utf-8')
    status, raw = _mcp_post(
        blender_server['base_url'], body, content_type='application/json; charset=utf-8'
    )
    assert status == 200
    assert json.loads(raw.decode('utf-8'))['result'] == {}


def test_jsonrpc_batch_rejected(blender_server: dict[str, Any]) -> None:
    """We don't implement JSON-RPC batches (spec-optional). A top-level JSON
    array must come back as -32600 invalid request."""
    body = json.dumps([{'jsonrpc': '2.0', 'method': 'ping', 'id': 1}]).encode('utf-8')
    _, raw = _mcp_post(blender_server['base_url'], body)
    reply = json.loads(raw.decode('utf-8'))
    assert reply['error']['code'] == -32600


def test_tools_call_query_null_sql_returns_structured_error(blender_server: dict[str, Any]) -> None:
    """`sql=null` is a tool-level argument validation failure surfaced as a
    structured ok=false envelope (not a JSON-RPC error)."""
    reply = _tool_call(blender_server['base_url'], 'query', {'sql': None})
    assert reply['result']['isError'] is False
    payload = json.loads(_content_text(reply))
    assert payload['ok'] is False
    assert 'sql' in payload['error']


def test_tools_call_query_rejects_side_effect_function(blender_server: dict[str, Any]) -> None:
    """`SELECT save()` is a SELECT but calls a side-effecting function — the
    read-only contract must reject it with a structured envelope, not run
    save() and silently write a file."""
    reply = _tool_call(blender_server['base_url'], 'query', {'sql': "SELECT save('/tmp/x.blend')"})
    assert reply['result']['isError'] is False
    payload = json.loads(_content_text(reply))
    assert payload['ok'] is False
    assert 'save' in payload['error']
    assert 'side effect' in payload['error']


def test_tools_call_query_rejects_nested_side_effect(blender_server: dict[str, Any]) -> None:
    """Nested side-effecting calls are caught — the scan is `\\b<name>\\(` so
    it matches even inside another function's args."""
    reply = _tool_call(blender_server['base_url'], 'query', {'sql': "SELECT length(bpy_exec('1'))"})
    payload = json.loads(_content_text(reply))
    assert payload['ok'] is False
    assert 'bpy_exec' in payload['error']


@pytest.mark.parametrize('method', ['initialize', 'tools/list', 'ping'])
def test_id_echo(blender_server: dict[str, Any], method: str) -> None:
    """JSON-RPC requires that the id be echoed back exactly."""
    reply = _rpc(
        blender_server['base_url'],
        method,
        params={}
        if method != 'initialize'
        else {
            'protocolVersion': '2024-11-05',
            'capabilities': {},
            'clientInfo': {'name': 'x', 'version': '0'},
        },
        req_id='abc-42',
    )
    assert reply['id'] == 'abc-42'
