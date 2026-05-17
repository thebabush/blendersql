"""BlenderSQL — SQL interface to bpy.data.

Submodule imports are deferred into `register()` / `unregister()` so that
non-Blender callers (the standalone CLI, the test harness) can import
sibling pure-stdlib modules like `blendersql.cli._blender` without
triggering the bpy-dependent submodules.
"""

from __future__ import annotations


def register() -> None:
    from . import bridge, operators, preferences, server
    from .sql import engine

    preferences.register()
    operators.register()
    bridge.install()
    engine.initialize()
    prefs = preferences.get()
    if prefs.autostart:
        try:
            server.start(prefs.bind, prefs.port)
        except OSError as exc:
            print(f'BlenderSQL: HTTP server not started ({prefs.bind}:{prefs.port}): {exc}')


def unregister() -> None:
    from . import bridge, operators, preferences, server
    from .sql import engine

    server.stop()
    bridge.uninstall()
    engine.shutdown()
    operators.unregister()
    preferences.unregister()
