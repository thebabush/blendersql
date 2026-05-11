from __future__ import annotations

from typing import Any


def to_jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, dict):
        return {str(k): to_jsonable(x) for k, x in v.items()}
    if hasattr(v, 'to_list'):
        try:
            return v.to_list()
        except Exception:
            pass
    if hasattr(v, 'to_dict'):
        try:
            return v.to_dict()
        except Exception:
            pass
    if isinstance(v, (list, tuple)):
        return [to_jsonable(x) for x in v]
    try:
        return list(v)
    except TypeError:
        return str(v)
