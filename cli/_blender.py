"""Shared helpers for locating Blender and picking a free TCP port.

Imported by both the CLI (cli/blendersql.py) and the pytest harness
(tests/conftest.py) so the Blender-location logic lives in exactly one place.
"""

from __future__ import annotations

import os
import shutil
import socket
from pathlib import Path

_MAC_BLENDER = '/Applications/Blender.app/Contents/MacOS/Blender'


def find_blender() -> str | None:
    env = os.environ.get('BLENDER')
    if env and Path(env).exists():
        return env
    which = shutil.which('blender')
    if which:
        return which
    if Path(_MAC_BLENDER).exists():
        return _MAC_BLENDER
    return None


def pick_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def port_is_free(port: int, bind: str = '127.0.0.1') -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((bind, port))
    except OSError:
        return False
    finally:
        s.close()
    return True
