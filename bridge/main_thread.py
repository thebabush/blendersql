"""Schedule callables from worker threads onto Blender's main thread.

bpy is main-thread-only. The HTTP server runs on a background thread, but
anything that touches bpy.data must run on the main thread. We use
bpy.app.timers to drain a queue of pending callables once per tick.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

import bpy

_TICK: float = 0.0  # request to be called again next tick
_MAX_PER_TICK: int = 64  # cap drain per tick so heavy queries don't freeze the UI

_pending: queue.Queue[tuple[Callable[[], Any], Future]] = queue.Queue()


def _drain() -> float:
    drained = 0
    while drained < _MAX_PER_TICK:
        try:
            fn, fut = _pending.get_nowait()
        except queue.Empty:
            break
        if fut.cancelled():
            continue
        try:
            fut.set_result(fn())
        except BaseException as exc:
            fut.set_exception(exc)
        drained += 1
    return _TICK


def run_on_main[T](fn: Callable[[], T], timeout: float | None = 30.0) -> T:
    """Run *fn* on the main thread and return its result. Re-raises exceptions.

    If called from the main thread, runs *fn* synchronously.
    """
    if threading.current_thread() is threading.main_thread():
        return fn()
    fut: Future[T] = Future()
    _pending.put((fn, fut))
    return fut.result(timeout=timeout)


def install() -> None:
    if not bpy.app.timers.is_registered(_drain):
        bpy.app.timers.register(_drain, persistent=True)


def uninstall() -> None:
    if bpy.app.timers.is_registered(_drain):
        bpy.app.timers.unregister(_drain)
