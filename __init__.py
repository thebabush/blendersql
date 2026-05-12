"""BlenderSQL — SQL interface to bpy.data."""

from __future__ import annotations

from . import bridge, operators, preferences, server
from .sql import engine


def register() -> None:
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
    server.stop()
    bridge.uninstall()
    engine.shutdown()
    operators.unregister()
    preferences.unregister()
