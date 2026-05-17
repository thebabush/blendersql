"""HTTP server hosted on a background thread.

POST /query    — execute a SQL query (raw SQL in body), return JSON
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

    def _read_body(self) -> str:
        length = int(self.headers.get('Content-Length', '0'))
        return self.rfile.read(length).decode('utf-8') if length else ''

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
            sql = self._read_body().strip()
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
        elif self.path == '/shutdown':
            _json_response(self, 200, {'status': 'shutting_down'})
            threading.Thread(target=stop, daemon=True).start()
        else:
            _json_response(self, 404, {'error': 'not_found', 'path': self.path})


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
