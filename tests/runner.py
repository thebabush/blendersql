"""In-Blender bootstrap: enable the addon, start the HTTP server, signal ready.

Invoked by tests/conftest.py via:

    blender --background --factory-startup --python-use-system-env \
        tests/fixtures/test_scene.blend \
        --python tests/runner.py

Environment:
    BLENDERSQL_TEST_PORT — port the HTTP server binds to (required)
    BLENDERSQL_TEST_INFO — path to the JSON ready-marker file (required)

The runner blocks the main thread on a modal-ish loop driven by bpy.app.timers
because `--background` exits after the script returns; we keep Blender alive by
calling `time.sleep` forever and letting the bpy.app.timers drain pending bridge
work. A POST /shutdown stops the server, which sets a flag we poll here.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import traceback
from pathlib import Path

import bpy

_BIND = '127.0.0.1'


def _fail(message: str) -> None:
    sys.stderr.write(f'RUNNER_FAIL: {message}\n')
    sys.stderr.flush()
    bpy.ops.wm.quit_blender()


def main() -> None:
    port_str = os.environ.get('BLENDERSQL_TEST_PORT')
    info_path_str = os.environ.get('BLENDERSQL_TEST_INFO')
    if not port_str or not info_path_str:
        _fail('BLENDERSQL_TEST_PORT and BLENDERSQL_TEST_INFO must be set')
        return

    port = int(port_str)
    info_path = Path(info_path_str)

    try:
        bpy.ops.preferences.addon_enable(module='bl_ext.user_default.blendersql')
    except Exception:
        traceback.print_exc()
        _fail('failed to enable blendersql addon')
        return

    from bl_ext.user_default.blendersql import server as bsql_server

    try:
        # The add-on auto-starts the server on its default port when enabled;
        # stop it and rebind to the port this runner was told to use.
        bsql_server.stop()
        bsql_server.start(_BIND, port)
    except Exception:
        traceback.print_exc()
        _fail('failed to start HTTP server')
        return

    info_path.parent.mkdir(parents=True, exist_ok=True)
    info_path.write_text(
        json.dumps(
            {
                'bind': _BIND,
                'port': port,
                'pid': os.getpid(),
                'blender_version': bpy.app.version_string,
            }
        )
    )

    sys.stdout.write(f'RUNNER_READY {_BIND}:{port}\n')
    sys.stdout.flush()

    # In --background mode bpy.app.timers do NOT tick during time.sleep, so the
    # bridge's _drain timer never fires. We drain the queue directly from this
    # main-thread loop instead. Blocking on `_pending.get` with a short timeout
    # is much friendlier to the HTTP server threads than a busy spin — it
    # releases the GIL until a real request lands.
    from bl_ext.user_default.blendersql.bridge import main_thread as _bridge

    try:
        while bsql_server.is_running():
            try:
                fn, fut = _bridge._pending.get(timeout=0.01)
            except Exception:
                continue
            if fut.cancelled():
                continue
            try:
                fut.set_result(fn())
            except BaseException as exc:
                fut.set_exception(exc)
            # Drain any additional queued work without releasing the GIL so a
            # burst is processed back-to-back.
            _bridge._drain()
    finally:
        with contextlib.suppress(Exception):
            bsql_server.stop()
        with contextlib.suppress(Exception):
            info_path.unlink(missing_ok=True)

    bpy.ops.wm.quit_blender()


main()
