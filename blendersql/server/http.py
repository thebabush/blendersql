"""HTTP server hosted on a background thread.

POST /query    — execute a SQL query (raw SQL in body), return JSON
POST /mcp      — Model Context Protocol over JSON-RPC 2.0 (see mcp.py)
GET  /status   — server status
GET  /help     — endpoint help
POST /shutdown — stop the server

Queries are marshaled to the main thread via bridge.run_on_main, because
bpy.data (and the apsw connection that wraps it) is main-thread-only.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .. import bridge
from ..sql import engine
from ..sql.result import QueryResult
from . import mcp

_server: ThreadingHTTPServer | None = None
_thread: threading.Thread | None = None


def _json_response(handler: BaseHTTPRequestHandler, status: int, body: dict[str, Any]) -> None:
    payload = json.dumps(body).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # silence stderr noise
        return

    def _content_length(self) -> int | None:
        """Parse Content-Length; return None on garbage (caller should 400).

        Missing header defaults to 0 (some clients omit it for empty bodies).
        Returns None on non-integer values so the caller can emit 400 instead
        of crashing on a ValueError into the BaseHTTPRequestHandler default
        500 page.
        """
        raw = self.headers.get('Content-Length')
        if raw is None or raw == '':
            return 0
        try:
            return int(raw)
        except ValueError:
            return None

    def _bad_content_length(self) -> None:
        self.send_response(400)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b'Invalid Content-Length')

    def _read_body_str(self) -> str | None:
        """Read the body as text. Returns None on bad Content-Length (and
        emits a 400 inline so callers can early-return)."""
        length = self._content_length()
        if length is None:
            self._bad_content_length()
            return None
        return self.rfile.read(length).decode('utf-8') if length else ''

    def _read_body_bytes(self) -> bytes | None:
        """Read the body as bytes. Returns None on bad Content-Length (and
        emits a 400 inline so callers can early-return)."""
        length = self._content_length()
        if length is None:
            self._bad_content_length()
            return None
        return self.rfile.read(length) if length else b''

    def do_GET(self) -> None:
        if self.path == '/status':
            _json_response(self, 200, {'status': 'ok', 'running': True})
        elif self.path == '/help':
            _json_response(
                self,
                200,
                {
                    'endpoints': {
                        'POST /query': 'Execute a SQL query (body: raw SQL).',
                        'POST /mcp': 'Model Context Protocol over JSON-RPC 2.0.',
                        'GET /status': 'Server status.',
                        'GET /help': 'This message.',
                        'POST /shutdown': 'Stop the server.',
                    }
                },
            )
        else:
            _json_response(self, 404, {'error': 'not_found', 'path': self.path})

    def do_POST(self) -> None:
        if self.path == '/query':
            body = self._read_body_str()
            if body is None:
                return
            sql = body.strip()
            if not sql:
                _json_response(self, 400, {'ok': False, 'error': 'empty_query'})
                return
            try:
                result = bridge.run_on_main(lambda: engine.get().execute(sql), timeout=60.0)
            except Exception as exc:
                result = QueryResult(ok=False, error=str(exc), error_type=type(exc).__name__)
                _json_response(self, 500, result.to_dict())
                return
            status = 200 if result.ok else 400
            _json_response(self, status, result.to_dict())
        elif self.path == '/mcp':
            # Content-Type: present must be application/json (parameters like
            # `charset=utf-8` are ignored). Missing header is tolerated — some
            # MCP clients omit it. /query keeps raw-body semantics; only /mcp
            # enforces this.
            ctype = self.headers.get('Content-Type')
            if ctype is not None:
                bare = ctype.split(';', 1)[0].strip().lower()
                if bare and bare != 'application/json':
                    self.send_response(415)
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(b'Unsupported Media Type; expected application/json')
                    return
            raw = self._read_body_bytes()
            if raw is None:
                return
            reply = mcp.dispatch(raw, _run_sql)
            if reply is None:
                # Notification: no response body. 202 Accepted per JSON-RPC
                # convention. Content-Type still set so picky clients are
                # happy even though the body is empty.
                self.send_response(202)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            status, payload = reply
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif self.path == '/shutdown':
            _json_response(self, 200, {'status': 'shutting_down'})
            threading.Thread(target=stop, daemon=True).start()
        else:
            _json_response(self, 404, {'error': 'not_found', 'path': self.path})


def _run_sql(sql: str) -> dict[str, Any]:
    """SQL runner injected into the MCP dispatcher.

    Identical execution path to POST /query: bounce onto the main thread
    through the bridge, then materialize the result envelope. Errors are
    flattened into the same {ok: false, error, error_type} dict the rest of
    the wire surface uses, so MCP tool calls never see Python exceptions.
    """
    try:
        result = bridge.run_on_main(lambda: engine.get().execute(sql), timeout=60.0)
    except Exception as exc:
        result = QueryResult(ok=False, error=str(exc), error_type=type(exc).__name__)
    return result.to_dict()


def is_running() -> bool:
    return _server is not None


def start(bind: str, port: int) -> None:
    global _server, _thread
    if _server is not None:
        return
    _server = ThreadingHTTPServer((bind, port), _Handler)
    _thread = threading.Thread(target=_server.serve_forever, name='blendersql-http', daemon=True)
    _thread.start()


def stop() -> None:
    global _server, _thread
    if _server is None:
        return
    srv, _server = _server, None
    srv.shutdown()
    srv.server_close()
    if _thread is not None:
        _thread.join(timeout=2.0)
        _thread = None
