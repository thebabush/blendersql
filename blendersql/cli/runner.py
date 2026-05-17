"""In-Blender bootstrap for the standalone CLI.

Invoked by blendersql/cli/blendersql.py via:

    blender --background --factory-startup --python-use-system-env \
        <file.blend> --python blendersql/cli/runner.py

Environment:
    BLENDERSQL_CLI_PORT — port the HTTP server binds to (required)
    BLENDERSQL_CLI_BIND — bind address (optional, default 127.0.0.1)
    BLENDERSQL_CLI_SAVE — if set/non-empty, save the .blend on shutdown

Prints `RUNNER_READY http://<bind>:<port>` to stdout once the server is up so
the CLI can stop tailing and start querying. On failure prints a
`RUNNER_FAIL: ...` line to stderr and quits.
"""

from __future__ import annotations

import contextlib
import os
import sys
import traceback

import bpy

_ADDON_MODULE = 'bl_ext.user_default.blendersql'


def _fail(message: str) -> None:
    sys.stderr.write(f'RUNNER_FAIL: {message}\n')
    sys.stderr.flush()
    bpy.ops.wm.quit_blender()


def main() -> None:
    port_str = os.environ.get('BLENDERSQL_CLI_PORT')
    if not port_str:
        _fail('BLENDERSQL_CLI_PORT must be set')
        return
    port = int(port_str)
    bind = os.environ.get('BLENDERSQL_CLI_BIND') or '127.0.0.1'
    save_on_exit = bool(os.environ.get('BLENDERSQL_CLI_SAVE'))

    # Under --factory-startup the user_default extension repo is configured but
    # no extensions are enabled; addon_enable succeeds only if the extension is
    # actually installed (dev symlink or built zip).
    try:
        bpy.ops.preferences.addon_enable(module=_ADDON_MODULE)
    except Exception:
        traceback.print_exc()
        _fail(
            "blendersql extension not installed — run 'make install-dev' or install the built zip"
        )
        return

    from bl_ext.user_default.blendersql import server as bsql_server

    try:
        # The add-on auto-starts the server on its default port when enabled;
        # stop it and rebind to the port this runner was told to use.
        bsql_server.stop()
        bsql_server.start(bind, port)
    except Exception:
        traceback.print_exc()
        _fail('failed to start HTTP server')
        return

    sys.stdout.write(f'RUNNER_READY http://{bind}:{port}\n')
    sys.stdout.flush()

    # In --background mode bpy.app.timers do NOT tick, so the bridge's _drain
    # timer never fires. Drain the queue directly from this main-thread loop;
    # blocking on `_pending.get` with a short timeout releases the GIL until a
    # real request lands.
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
            _bridge._drain()
    finally:
        with contextlib.suppress(Exception):
            bsql_server.stop()

    if save_on_exit:
        with contextlib.suppress(Exception):
            bpy.ops.wm.save_mainfile()

    bpy.ops.wm.quit_blender()


main()
