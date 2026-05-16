"""SQL-function metadata for self-describing introspection.

Mirrors `sql/vtables/_meta.py`. Every callable registered as a SQL scalar
function (escape-hatch, typed verb, or pure scalar) carries a `FunctionMeta`
record. The `@function_meta` decorator attaches it as the `_bsql_meta`
attribute on the function so introspection code can walk modules with
`hasattr(fn, '_bsql_meta')`. Registration code reads `_bsql_meta` and stuffs
it into the `bsql_functions` registry.

`kind` and `return_shape` are plain strings (no stdlib `Enum`) for symmetry
with `Column.type` over in vtables.

return_shape values:

* 'json_envelope' — `{ok, result, error, ...}` envelope (bpy_op, all verbs).
* 'json'          — a JSON-encoded value (bpy_eval, grep).
* 'value'         — bare SQL scalar (reserved; nothing today).
* 'string'        — plain string the model parses (bpy_exec returns a JSON
                    `{stdout, result, error}` dict but not the verb envelope).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

F = TypeVar('F', bound=Callable[..., Any])


@dataclass(frozen=True)
class FunctionMeta:
    """Per-function metadata surfaced via `bsql_functions`.

    Attributes:
        name: SQL function name.
        kind: 'escape_hatch' / 'verb' / 'scalar'.
        arity: positional arg count; -1 for variadic.
        description: one short agent-facing summary.
        agent_hint: 1-3 lines telling the agent when to reach for this fn.
        return_shape: 'json_envelope' / 'json' / 'value' / 'string'.
        side_effects: True if the function mutates Blender state.
    """

    name: str
    kind: str
    arity: int
    description: str
    agent_hint: str
    return_shape: str
    side_effects: bool


def function_meta(
    *,
    name: str | None = None,
    kind: str,
    arity: int,
    description: str,
    agent_hint: str,
    return_shape: str,
    side_effects: bool,
) -> Callable[[F], F]:
    """Decorator that attaches a `FunctionMeta` to the callable as `_bsql_meta`.

    Defaulting `name` to the wrapped function's `__name__` keeps the metadata
    in lockstep with the SQL surface — when callers fall back to that default
    they can't accidentally drift.
    """

    def wrap(fn: F) -> F:
        resolved = name or fn.__name__
        fn._bsql_meta = FunctionMeta(  # type: ignore[attr-defined]
            name=resolved,
            kind=kind,
            arity=arity,
            description=description,
            agent_hint=agent_hint,
            return_shape=return_shape,
            side_effects=side_effects,
        )
        return fn

    return wrap
