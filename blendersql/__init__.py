"""BlenderSQL — SQL interface to bpy.data.

Submodule imports are deferred into `register()` / `unregister()` so that
non-Blender callers (the standalone CLI, the test harness) can import
sibling pure-stdlib modules like `blendersql.cli._blender` without
triggering the bpy-dependent submodules.

Headless multi-instance: env vars override the saved prefs at register
time. Useful when launching several Blender processes against different
ports so an agent can address each one separately:

    BLENDERSQL_BIND       — bind address (default: saved pref, default 127.0.0.1)
    BLENDERSQL_PORT       — TCP port (default: saved pref, default 8174)
    BLENDERSQL_AUTOSTART  — '1'/'true'/'yes' or '0'/'false'/'no' to force on/off
                            (default: saved pref)
"""

from __future__ import annotations

import os

_AUTOSTART_TRUTHY = frozenset({'1', 'true', 'yes', 'on'})
_AUTOSTART_FALSY = frozenset({'0', 'false', 'no', 'off', ''})


def _resolve_listen_config(prefs: object) -> tuple[str, int, bool]:
    """Layer BLENDERSQL_{BIND,PORT,AUTOSTART} env vars over the saved prefs."""
    bind = os.environ.get('BLENDERSQL_BIND') or prefs.bind  # type: ignore[attr-defined]
    port_env = os.environ.get('BLENDERSQL_PORT')
    port = int(port_env) if port_env else int(prefs.port)  # type: ignore[attr-defined]
    autostart_env = os.environ.get('BLENDERSQL_AUTOSTART')
    if autostart_env is None:
        autostart = bool(prefs.autostart)  # type: ignore[attr-defined]
    else:
        lowered = autostart_env.strip().lower()
        if lowered in _AUTOSTART_TRUTHY:
            autostart = True
        elif lowered in _AUTOSTART_FALSY:
            autostart = False
        else:
            raise ValueError(
                f'BLENDERSQL_AUTOSTART must be one of '
                f'{sorted(_AUTOSTART_TRUTHY | _AUTOSTART_FALSY)}; got {autostart_env!r}'
            )
    return bind, port, autostart


def register() -> None:
    from . import bridge, operators, preferences, server
    from .sql import engine

    preferences.register()
    operators.register()
    bridge.install()
    engine.initialize()
    prefs = preferences.get()
    bind, port, autostart = _resolve_listen_config(prefs)
    if autostart:
        try:
            server.start(bind, port)
        except OSError as exc:
            print(f'BlenderSQL: HTTP server not started ({bind}:{port}): {exc}')


def unregister() -> None:
    from . import bridge, operators, preferences, server
    from .sql import engine

    server.stop()
    bridge.uninstall()
    engine.shutdown()
    operators.unregister()
    preferences.unregister()
