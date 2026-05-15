from __future__ import annotations

import json
from typing import Any

import apsw
import bpy

from ._meta import Column
from ._params import apply_params_json, parse_params_json
from .base import WritableSnapshotVTable

_MODIFIER_COMMON: frozenset[str] = frozenset(
    {
        'rna_type',
        'name',
        'type',
        'show_viewport',
        'show_render',
    }
)

_COLUMNS: tuple[str, ...] = (
    'object',
    'name',
    'type',
    'show_viewport',
    'show_render',
    'params_json',
)
_COL_INDEX: dict[str, int] = {name: i for i, name in enumerate(_COLUMNS)}

_INSERT_HINT = 'INSERT into modifiers is not supported; use the add_modifier verb (M2.c)'


class Modifiers(WritableSnapshotVTable):
    table_name = 'modifiers'
    DESCRIPTION = 'Per-object modifier stack with type and packed parameters.'
    AGENT_HINT = (
        "Use to inspect or tweak modifier params; tune via UPDATE on params_json (it's a "
        'JSON blob of every non-common bl_rna prop). JOIN objects (object=objects.name) for '
        'object context. INSERT is blocked — use the add_modifier verb to create one.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('object', 'TEXT', pk=True, hint='Owning object name; part of the identifier.'),
        Column(
            'name',
            'TEXT',
            writable=True,
            pk=True,
            hint='Modifier name on the object; part of the identifier.',
        ),
        Column('type', 'TEXT', hint='SUBSURF / ARRAY / MIRROR / BEVEL / ... read-only.'),
        Column('show_viewport', 'INTEGER', writable=True, hint='Boolean as 0/1; viewport display.'),
        Column('show_render', 'INTEGER', writable=True, hint='Boolean as 0/1; render display.'),
        Column(
            'params_json',
            'TEXT',
            writable=True,
            hint='JSON object of type-specific bl_rna props; UPDATE diffs against current.',
        ),
    )
    RELATED: tuple[str, ...] = ('objects',)
    schema = (
        'CREATE TABLE modifiers('
        'object TEXT, '
        'name TEXT, '
        'type TEXT, '
        'show_viewport INTEGER, '
        'show_render INTEGER, '
        'params_json TEXT)'
    )

    def _snapshot(self) -> tuple[list[tuple[Any, ...]], list[tuple[str, str]]]:
        rows: list[tuple[Any, ...]] = []
        idents: list[tuple[str, str]] = []
        for o in bpy.data.objects:
            for m in o.modifiers:
                rows.append(_row_for(o, m))
                idents.append((o.name, m.name))
        return rows, idents

    def _describe_identifier(self, identifier: Any) -> str:
        obj_name, mod_name = identifier
        return f'{obj_name}/{mod_name}'

    def _apply_insert(self, fields: tuple[Any, ...]) -> Any:
        raise apsw.SQLError(_INSERT_HINT)

    def _apply_update(self, identifier: Any, fields: tuple[Any, ...]) -> None:
        obj_name, mod_name = identifier
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            raise apsw.SQLError(f"object '{obj_name}' no longer exists")
        mod = obj.modifiers.get(mod_name)
        if mod is None:
            raise apsw.SQLError(f"modifier '{mod_name}' no longer exists on '{obj_name}'")
        current = _row_for(obj, mod)

        new_type = fields[_COL_INDEX['type']]
        if new_type != current[_COL_INDEX['type']]:
            raise apsw.SQLError("column 'type' is read-only on UPDATE")

        new_show_vp = fields[_COL_INDEX['show_viewport']]
        if new_show_vp != current[_COL_INDEX['show_viewport']]:
            mod.show_viewport = bool(new_show_vp)
        new_show_rn = fields[_COL_INDEX['show_render']]
        if new_show_rn != current[_COL_INDEX['show_render']]:
            mod.show_render = bool(new_show_rn)

        new_params = parse_params_json(fields[_COL_INDEX['params_json']])
        current_params = json.loads(current[_COL_INDEX['params_json']])
        apply_params_json(mod, new_params, current_params)

        new_name = fields[_COL_INDEX['name']]
        if new_name != current[_COL_INDEX['name']]:
            if not isinstance(new_name, str) or not new_name:
                raise apsw.SQLError('name must be a non-empty string')
            mod.name = new_name

    def _apply_delete(self, identifier: Any) -> None:
        obj_name, mod_name = identifier
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            raise apsw.SQLError(f"object '{obj_name}' no longer exists")
        mod = obj.modifiers.get(mod_name)
        if mod is None:
            raise apsw.SQLError(f"modifier '{mod_name}' no longer exists on '{obj_name}'")
        obj.modifiers.remove(mod)


def _row_for(obj: Any, m: Any) -> tuple[Any, ...]:
    return (
        obj.name,
        m.name,
        m.type,
        int(m.show_viewport),
        int(m.show_render),
        json.dumps(_dump_props(m, _MODIFIER_COMMON), default=str),
    )


def _dump_props(obj: Any, skip: frozenset[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for p in obj.bl_rna.properties:
        ident = p.identifier
        if ident in skip:
            continue
        try:
            v = getattr(obj, ident)
        except Exception:
            continue
        out[ident] = _stringify(v)
    return out


def _stringify(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    name = getattr(v, 'name', None)
    if isinstance(name, str) and hasattr(v, 'bl_rna'):
        return name
    if hasattr(v, '__iter__'):
        try:
            return [_stringify(x) for x in v]
        except Exception:
            return str(v)
    return str(v)
