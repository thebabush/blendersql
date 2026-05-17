"""SQL functions (verbs) — bpy_op, bpy_eval, bpy_exec, grep, etc."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..engine import Engine


def register_all(engine: Engine) -> None:
    from .bpy_eval import bpy_eval
    from .bpy_exec import bpy_exec
    from .bpy_op import bpy_op
    from .registry import register_function
    from .verbs import register_verbs

    # No clear_registry() here: `register_function` keys by name (idempotent
    # on re-registration), and the grep scalar's meta is registered by the
    # vtables side before us — clearing would wipe it. `initialize()` is a
    # one-shot anyway.

    # apsw types scalar-function callbacks as (*SQLiteValue) -> SQLiteValue;
    # these take a single declared `str` arg (they runtime-check the type).
    engine.conn.createscalarfunction('bpy_eval', bpy_eval, 1, deterministic=False)  # type: ignore[arg-type]
    engine.conn.createscalarfunction('bpy_exec', bpy_exec, 1, deterministic=False)  # type: ignore[arg-type]
    engine.conn.createscalarfunction('bpy_op', bpy_op, -1, deterministic=False)
    register_function(bpy_eval._bsql_meta)  # type: ignore[attr-defined]
    register_function(bpy_exec._bsql_meta)  # type: ignore[attr-defined]
    register_function(bpy_op._bsql_meta)  # type: ignore[attr-defined]
    register_verbs(engine)
