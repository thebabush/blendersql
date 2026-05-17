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
_AUTOSTART_FALSY = frozenset({'0', 'false', 'no', 'off'})


def _resolve_listen_config(prefs: object) -> tuple[str, int, bool]:
    """Layer BLENDERSQL_{BIND,PORT,AUTOSTART} env vars over the saved prefs.

    All three vars treat empty-string-after-strip as "unset, use prefs", so
    `BLENDERSQL_PORT=''` and `BLENDERSQL_AUTOSTART=''` and
    `BLENDERSQL_BIND=''` all fall back consistently. `BLENDERSQL_PORT` is
    bounds-checked to a valid TCP port (1..65535); out-of-range or non-
    integer values raise `ValueError`. Hosts in `BLENDERSQL_BIND` aren't
    DNS-resolved — too expensive at register time — only whitespace-stripped
    and required non-empty after the strip.
    """
    bind_env = os.environ.get('BLENDERSQL_BIND')
    bind = bind_env.strip() if bind_env is not None and bind_env.strip() else prefs.bind  # type: ignore[attr-defined]

    port_env = os.environ.get('BLENDERSQL_PORT')
    if port_env is not None and port_env.strip():
        try:
            port = int(port_env.strip())
        except ValueError as exc:
            raise ValueError(f'BLENDERSQL_PORT must be an integer; got {port_env!r}') from exc
        if not 1 <= port <= 65535:
            raise ValueError(f'BLENDERSQL_PORT must be in 1..65535; got {port}')
    else:
        port = int(prefs.port)  # type: ignore[attr-defined]

    autostart_env = os.environ.get('BLENDERSQL_AUTOSTART')
    if autostart_env is None or not autostart_env.strip():
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
