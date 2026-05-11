from __future__ import annotations

import json
from typing import Any

import apsw
import bpy

from ._params import apply_params_json, parse_params_json
from .base import WritableSnapshotVTable
from .modifiers import _dump_props

_CONSTRAINT_COMMON: frozenset[str] = frozenset(
    {
        'rna_type',
        'name',
        'type',
        'target',
        'subtarget',
        'influence',
        'mute',
    }
)

_COLUMNS: tuple[str, ...] = (
    'owner_type',
    'owner_name',
    'name',
    'type',
    'target',
    'subtarget',
    'influence',
    'mute',
    'params_json',
)
_COL_INDEX: dict[str, int] = {name: i for i, name in enumerate(_COLUMNS)}

_INSERT_HINT = 'INSERT into constraints is not supported; use the add_constraint verb (M2.c)'


class Constraints(WritableSnapshotVTable):
    table_name = 'constraints'
    schema = (
        'CREATE TABLE constraints('
        'owner_type TEXT, '
        'owner_name TEXT, '
        'name TEXT, '
        'type TEXT, '
        'target TEXT, '
        'subtarget TEXT, '
        'influence REAL, '
        'mute INTEGER, '
        'params_json TEXT)'
    )

    def _snapshot(self) -> tuple[list[tuple[Any, ...]], list[tuple[str, str, str]]]:
        rows: list[tuple[Any, ...]] = []
        idents: list[tuple[str, str, str]] = []
        for o in bpy.data.objects:
            for c in o.constraints:
                rows.append(_row('OBJECT', o.name, c))
                idents.append(('OBJECT', o.name, c.name))
            if o.type == 'ARMATURE' and o.pose:
                for pb in o.pose.bones:
                    for c in pb.constraints:
                        owner_name = f'{o.name}/{pb.name}'
                        rows.append(_row('POSE_BONE', owner_name, c))
                        idents.append(('POSE_BONE', owner_name, c.name))
        return rows, idents

    def _describe_identifier(self, identifier: Any) -> str:
        _owner_type, owner_name, con_name = identifier
        return f'{owner_name}/{con_name}'

    def _apply_insert(self, fields: tuple[Any, ...]) -> Any:
        raise apsw.SQLError(_INSERT_HINT)

    def _apply_update(self, identifier: Any, fields: tuple[Any, ...]) -> None:
        owner_type, owner_name, con_name = identifier
        owner = _resolve_owner(owner_type, owner_name)
        con = owner.constraints.get(con_name)
        if con is None:
            raise apsw.SQLError(f"constraint '{con_name}' no longer exists on '{owner_name}'")
        current = _row(owner_type, owner_name, con)

        new_type = fields[_COL_INDEX['type']]
        if new_type != current[_COL_INDEX['type']]:
            raise apsw.SQLError("column 'type' is read-only on UPDATE")

        new_influence = fields[_COL_INDEX['influence']]
        if new_influence != current[_COL_INDEX['influence']]:
            con.influence = float(new_influence)
        new_mute = fields[_COL_INDEX['mute']]
        if new_mute != current[_COL_INDEX['mute']]:
            con.mute = bool(new_mute)

        new_target = fields[_COL_INDEX['target']]
        if new_target != current[_COL_INDEX['target']]:
            if not hasattr(con, 'target'):
                raise apsw.SQLError(f"constraint type '{con.type}' has no target")
            if new_target is None:
                con.target = None
            else:
                obj = bpy.data.objects.get(new_target)
                if obj is None:
                    raise apsw.SQLError(f"target object '{new_target}' not found")
                con.target = obj

        new_subtarget = fields[_COL_INDEX['subtarget']]
        if new_subtarget != current[_COL_INDEX['subtarget']]:
            if not hasattr(con, 'subtarget'):
                raise apsw.SQLError(f"constraint type '{con.type}' has no subtarget")
            con.subtarget = new_subtarget or ''

        new_params = parse_params_json(fields[_COL_INDEX['params_json']])
        current_params = json.loads(current[_COL_INDEX['params_json']])
        apply_params_json(con, new_params, current_params)

        new_name = fields[_COL_INDEX['name']]
        if new_name != current[_COL_INDEX['name']]:
            if not isinstance(new_name, str) or not new_name:
                raise apsw.SQLError('name must be a non-empty string')
            con.name = new_name

    def _apply_delete(self, identifier: Any) -> None:
        owner_type, owner_name, con_name = identifier
        owner = _resolve_owner(owner_type, owner_name)
        con = owner.constraints.get(con_name)
        if con is None:
            raise apsw.SQLError(f"constraint '{con_name}' no longer exists on '{owner_name}'")
        owner.constraints.remove(con)


def _resolve_owner(owner_type: str, owner_name: str) -> Any:
    if owner_type == 'POSE_BONE':
        obj_name, _, bone_name = owner_name.partition('/')
        obj = bpy.data.objects.get(obj_name)
        if obj is None or obj.pose is None:
            raise apsw.SQLError(f"armature object '{obj_name}' not found")
        pb = obj.pose.bones.get(bone_name)
        if pb is None:
            raise apsw.SQLError(f"pose bone '{bone_name}' not found on '{obj_name}'")
        return pb
    obj = bpy.data.objects.get(owner_name)
    if obj is None:
        raise apsw.SQLError(f"object '{owner_name}' not found")
    return obj


def _row(owner_type: str, owner_name: str, c: Any) -> tuple[Any, ...]:
    target = getattr(c, 'target', None)
    target_name = target.name if target is not None and hasattr(target, 'name') else None
    return (
        owner_type,
        owner_name,
        c.name,
        c.type,
        target_name,
        getattr(c, 'subtarget', None) or None,
        float(c.influence),
        int(c.mute),
        json.dumps(_dump_props(c, _CONSTRAINT_COMMON), default=str),
    )
