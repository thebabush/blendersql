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


def _mcp_post(base_url: str, body: bytes, timeout: float = 30.0) -> tuple[int, bytes]:
    req = urllib.request.Request(
        base_url + '/mcp',
        data=body,
        method='POST',
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


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
