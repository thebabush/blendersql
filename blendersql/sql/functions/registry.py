"""Live registry of SQL functions — mirror of `sql/vtables/_REGISTRY`.

Populated at engine-init time by `register_all` / `register_verbs` after the
`createscalarfunction` call: every callable carrying a `_bsql_meta` attribute
is recorded here. The `bsql_functions` introspection vtable reads this dict
to surface one row per function. Separate version counter so the vtable's
snapshot cache can invalidate independently of `registry_version()`.
"""

from __future__ import annotations

from ._meta import FunctionMeta

_FUNCTIONS_REGISTRY: dict[str, FunctionMeta] = {}
_FUNCTIONS_VERSION = 0


def register_function(meta: FunctionMeta) -> None:
    """Record `meta` keyed by `meta.name`. Bumps `functions_version()`.

    Re-registration with an identical `FunctionMeta` is a no-op (safe — same
    module imported twice). Re-registration with a DIFFERENT meta under the
    same name raises: silent clobbering was the kind of drift the
    introspection system was built to catch.
    """
    existing = _FUNCTIONS_REGISTRY.get(meta.name)
    if existing is not None and existing != meta:
        raise RuntimeError(f'duplicate function registration: {meta.name}')
    _FUNCTIONS_REGISTRY[meta.name] = meta
    global _FUNCTIONS_VERSION
    _FUNCTIONS_VERSION += 1


def functions_registry() -> dict[str, FunctionMeta]:
    """Return the {name: FunctionMeta} registry. Read-only by convention."""
    return _FUNCTIONS_REGISTRY


def functions_version() -> int:
    """Monotonic version bumped every time `register_function` is called."""
    return _FUNCTIONS_VERSION


def clear_registry() -> None:
    """Reset the registry — called by `register_all` to avoid stale entries
    across re-registrations (same pattern as `_REGISTRY.clear()` in vtables).
    """
    _FUNCTIONS_REGISTRY.clear()
