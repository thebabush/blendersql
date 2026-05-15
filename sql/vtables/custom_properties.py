from __future__ import annotations

import contextlib
import json
from typing import Any

import apsw
import bpy

from ..functions.jsonify import to_jsonable as _jsonify
from ._meta import Column
from .base import WritableSnapshotVTable
from .datablocks import RESOLVE_CONTAINER as _CONTAINERS
from .datablocks import iter_named_datablocks

_COLUMNS: tuple[str, ...] = (
    'datablock_type',
    'datablock_name',
    'key',
    'value_json',
    'subtype',
    'description',
    'min',
    'max',
    'soft_min',
    'soft_max',
    'step',
    'default',
)
_COL_INDEX: dict[str, int] = {name: i for i, name in enumerate(_COLUMNS)}

_UI_COLUMNS: tuple[str, ...] = (
    'subtype',
    'description',
    'min',
    'max',
    'soft_min',
    'soft_max',
    'step',
    'default',
)


class CustomProperties(WritableSnapshotVTable):
    table_name = 'custom_properties'
    DESCRIPTION = 'ID-property key/value pairs across every named datablock, with UI metadata.'
    AGENT_HINT = (
        'Per-row identity is (datablock_type, datablock_name, key). UPDATE can rename `key` and '
        'edit value_json / UI fields; cross-datablock moves are blocked (use DELETE + INSERT). '
        'INSERT requires datablock_type / datablock_name / key / value_json.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column(
            'datablock_type',
            'TEXT',
            writable=True,
            pk=True,
            hint='Container kind (objects / materials / ...); immutable on UPDATE.',
        ),
        Column(
            'datablock_name',
            'TEXT',
            writable=True,
            pk=True,
            hint='Owning datablock name; immutable on UPDATE.',
        ),
        Column(
            'key',
            'TEXT',
            writable=True,
            pk=True,
            hint='ID-property key; UPDATE may rename if non-colliding.',
        ),
        Column(
            'value_json',
            'TEXT',
            writable=True,
            hint='JSON-encoded value; bool coerces to 0/1 (no IDProp bool type).',
        ),
        Column('subtype', 'TEXT', writable=True, hint='UI subtype (NONE / COLOR / FACTOR / ...).'),
        Column('description', 'TEXT', writable=True, hint='UI tooltip text.'),
        Column('min', 'REAL', writable=True, hint='UI hard minimum.'),
        Column('max', 'REAL', writable=True, hint='UI hard maximum.'),
        Column('soft_min', 'REAL', writable=True, hint='UI soft minimum (slider range).'),
        Column('soft_max', 'REAL', writable=True, hint='UI soft maximum (slider range).'),
        Column('step', 'REAL', writable=True, hint='UI step increment.'),
        Column('default', 'TEXT', writable=True, hint='JSON-encoded default; may be NULL.'),
    )
    RELATED: tuple[str, ...] = ()
    schema = (
        'CREATE TABLE custom_properties('
        'datablock_type TEXT, '
        'datablock_name TEXT, '
        'key TEXT, '
        'value_json TEXT, '
        'subtype TEXT, '
        'description TEXT, '
        'min REAL, '
        'max REAL, '
        'soft_min REAL, '
        'soft_max REAL, '
        'step REAL, '
        '"default" TEXT)'
    )

    def _snapshot(self) -> tuple[list[tuple[Any, ...]], list[tuple[str, str, str]]]:
        rows: list[tuple[Any, ...]] = []
        idents: list[tuple[str, str, str]] = []
        for kind, id_block in iter_named_datablocks():
            keys = getattr(id_block, 'keys', None)
            if keys is None:
                continue
            try:
                key_list = list(keys())
            except Exception:
                continue
            for key in key_list:
                try:
                    value = id_block[key]
                except Exception:
                    continue
                ui = _read_ui(id_block, key)
                rows.append(
                    (
                        kind,
                        id_block.name,
                        key,
                        json.dumps(_jsonify(value), default=str),
                        ui.get('subtype'),
                        ui.get('description'),
                        _to_float(ui.get('min')),
                        _to_float(ui.get('max')),
                        _to_float(ui.get('soft_min')),
                        _to_float(ui.get('soft_max')),
                        _to_float(ui.get('step')),
                        json.dumps(_jsonify(ui.get('default')), default=str)
                        if 'default' in ui
                        else None,
                    )
                )
                idents.append((kind, id_block.name, key))
        return rows, idents

    def _describe_identifier(self, identifier: Any) -> str:
        _kind, name, key = identifier
        return f'{name}.{key}'

    def _apply_insert(self, fields: tuple[Any, ...]) -> tuple[str, str, str]:
        kind = fields[_COL_INDEX['datablock_type']]
        name = fields[_COL_INDEX['datablock_name']]
        key = fields[_COL_INDEX['key']]
        value_json = fields[_COL_INDEX['value_json']]

        if not isinstance(kind, str) or not kind:
            raise apsw.SQLError('INSERT into custom_properties requires datablock_type')
        if not isinstance(name, str) or not name:
            raise apsw.SQLError('INSERT into custom_properties requires datablock_name')
        if not isinstance(key, str) or not key:
            raise apsw.SQLError('INSERT into custom_properties requires key')
        if value_json is None:
            raise apsw.SQLError('INSERT into custom_properties requires value_json')

        id_block = _resolve_id_block(kind, name)
        if key in id_block:
            raise apsw.SQLError(f"key '{key}' already exists on this datablock; use UPDATE")

        parsed = _parse_value_json(value_json)
        ui_updates = _collect_ui_updates_from_insert(fields)

        id_block[key] = parsed
        _apply_ui(id_block, key, ui_updates)

        return (kind, name, key)

    def _apply_update(self, identifier: Any, fields: tuple[Any, ...]) -> None:
        old_kind, old_name, old_key = identifier
        new_kind = fields[_COL_INDEX['datablock_type']]
        new_name = fields[_COL_INDEX['datablock_name']]
        new_key = fields[_COL_INDEX['key']]

        # Cross-datablock moves are rejected: a successful move-and-fail
        # leaves data in either zero or two places. DELETE + INSERT keeps
        # the agent honest.
        if new_kind != old_kind or new_name != old_name:
            raise apsw.SQLError(
                'moving custom_properties across datablocks is not supported; use DELETE + INSERT'
            )

        id_block = _resolve_id_block(old_kind, old_name)
        if old_key not in id_block:
            raise apsw.SQLError(f"key '{old_key}' vanished between snapshot and update")

        current_row = _row_for(old_kind, id_block, old_key)
        new_value_json = fields[_COL_INDEX['value_json']]
        current_value_json = current_row[_COL_INDEX['value_json']]

        ui_updates = _collect_ui_updates_from_update(fields, current_row)

        if new_key != old_key:
            if not isinstance(new_key, str) or not new_key:
                raise apsw.SQLError('key must be a non-empty string')
            if new_key in id_block:
                raise apsw.SQLError(f"key '{new_key}' already exists on this datablock")

            parsed = (
                _parse_value_json(new_value_json)
                if new_value_json != current_value_json
                else id_block[old_key]
            )
            existing_ui = _read_ui(id_block, old_key)
            del id_block[old_key]
            id_block[new_key] = parsed
            _apply_ui(id_block, new_key, existing_ui)
            _apply_ui(id_block, new_key, ui_updates)
            return

        if new_value_json != current_value_json:
            parsed = _parse_value_json(new_value_json)
            id_block[old_key] = parsed

        _apply_ui(id_block, old_key, ui_updates)

    def _apply_delete(self, identifier: Any) -> None:
        kind, name, key = identifier
        id_block = _resolve_id_block(kind, name)
        if key not in id_block:
            raise apsw.SQLError(f"key '{key}' vanished between snapshot and delete")
        del id_block[key]


def _resolve_id_block(kind: str, name: str) -> Any:
    attr = _CONTAINERS.get(kind)
    if attr is None:
        raise apsw.SQLError(f"unknown datablock_type '{kind}'")
    container = getattr(bpy.data, attr, None)
    if container is None:
        raise apsw.SQLError(f"datablock_type '{kind}' has no container in this Blender build")
    id_block = container.get(name)
    if id_block is None:
        raise apsw.SQLError(f"no {kind} named '{name}'")
    return id_block


def _parse_value_json(raw: Any) -> Any:
    if not isinstance(raw, str):
        raise apsw.SQLError('value_json must be a JSON-encoded TEXT value')
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise apsw.SQLError(f'value_json: invalid JSON ({exc.msg})') from exc
    if parsed is None:
        raise apsw.SQLError('value_json: null cannot be stored as an ID-property')
    # Blender ID-properties don't have a bool type — assigning a Python bool
    # silently flips to int internally. Be explicit so the read-back round-trip
    # is unambiguous (we always see 0/1, never true/false).
    if isinstance(parsed, bool):
        return int(parsed)
    return parsed


def _collect_ui_updates_from_insert(fields: tuple[Any, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in _UI_COLUMNS:
        v = fields[_COL_INDEX[col]]
        if v is None:
            continue
        if col == 'default':
            try:
                out['default'] = json.loads(v) if isinstance(v, str) else v
            except json.JSONDecodeError as exc:
                raise apsw.SQLError(f'default: invalid JSON ({exc.msg})') from exc
        else:
            out[col] = v
    return out


def _collect_ui_updates_from_update(
    fields: tuple[Any, ...], current: tuple[Any, ...]
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in _UI_COLUMNS:
        new_v = fields[_COL_INDEX[col]]
        old_v = current[_COL_INDEX[col]]
        if new_v == old_v:
            continue
        if new_v is None:
            continue
        if col == 'default':
            try:
                out['default'] = json.loads(new_v) if isinstance(new_v, str) else new_v
            except json.JSONDecodeError as exc:
                raise apsw.SQLError(f'default: invalid JSON ({exc.msg})') from exc
        else:
            out[col] = new_v
    return out


def _apply_ui(id_block: Any, key: str, kwargs: dict[str, Any]) -> None:
    if not kwargs:
        return
    ui_getter = getattr(id_block, 'id_properties_ui', None)
    if ui_getter is None:
        return
    try:
        ui = ui_getter(key)
    except (TypeError, KeyError):
        return

    # 5.1 quirk: id_properties_ui(int_key).update(min=0.0) raises TypeError
    # ('float object cannot be interpreted as an integer'). The read schema
    # surfaces min/max/step as REAL, so we coerce numerics back to the
    # underlying value's type before handing them to Blender. Float-valued
    # props accept either ints or floats.
    try:
        stored = id_block[key]
    except KeyError:
        stored = None
    coerced = _coerce_ui_numerics(kwargs, stored)

    # `default` on list-valued / IDPropertyGroup props raises TypeError on
    # .update(); apply other fields first, then default in isolation so a
    # rejected default doesn't drop the rest.
    default = coerced.pop('default', None)
    if coerced:
        with contextlib.suppress(TypeError, KeyError):
            ui.update(**coerced)
    if default is not None:
        with contextlib.suppress(TypeError, KeyError):
            ui.update(default=default)


def _coerce_ui_numerics(kwargs: dict[str, Any], stored: Any) -> dict[str, Any]:
    if not isinstance(stored, int) or isinstance(stored, bool):
        return dict(kwargs)
    out: dict[str, Any] = {}
    for k, v in kwargs.items():
        if k in ('min', 'max', 'soft_min', 'soft_max', 'step') and isinstance(v, float):
            out[k] = int(v)
        else:
            out[k] = v
    return out


def _read_ui(id_block: Any, key: str) -> dict[str, Any]:
    ui_getter = getattr(id_block, 'id_properties_ui', None)
    if ui_getter is None:
        return {}
    try:
        return ui_getter(key).as_dict() or {}
    except (TypeError, KeyError):
        return {}


def _row_for(kind: str, id_block: Any, key: str) -> tuple[Any, ...]:
    value = id_block[key]
    ui = _read_ui(id_block, key)
    return (
        kind,
        id_block.name,
        key,
        json.dumps(_jsonify(value), default=str),
        ui.get('subtype'),
        ui.get('description'),
        _to_float(ui.get('min')),
        _to_float(ui.get('max')),
        _to_float(ui.get('soft_min')),
        _to_float(ui.get('soft_max')),
        _to_float(ui.get('step')),
        json.dumps(_jsonify(ui.get('default')), default=str) if 'default' in ui else None,
    )


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
