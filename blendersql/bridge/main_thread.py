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
from concurrent.futures import TimeoutError as FutureTimeoutError
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

    On TimeoutError we cancel the future so the drain loop short-circuits
    when it dequeues the work later — otherwise queued-but-not-yet-running
    callables run after the caller has already given up, mutating Blender
    state without anyone listening for the result. If `fn` is already
    executing on the main thread, `fut.cancel()` returns False and the run
    completes; that in-flight case is unavoidable and harmless because the
    bridge holds no other state past `set_result`/`set_exception`.
    """
    if threading.current_thread() is threading.main_thread():
        return fn()
    fut: Future[T] = Future()
    _pending.put((fn, fut))
    try:
        return fut.result(timeout=timeout)
    except FutureTimeoutError:
        fut.cancel()
        raise


def install() -> None:
    if not bpy.app.timers.is_registered(_drain):
        bpy.app.timers.register(_drain, persistent=True)


def uninstall() -> None:
    if bpy.app.timers.is_registered(_drain):
        bpy.app.timers.unregister(_drain)
