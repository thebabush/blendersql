from __future__ import annotations

from typing import Any

import apsw
import bpy

from .base import IteratorVTable, WritableSnapshotVTable

# 5.1 layered Action: every action has slots + layers; layers hold strips; strips
# hold channelbags keyed by slot_handle; channelbags hold fcurves; fcurves hold
# keyframe_points. is_action_layered is always True in 5.1; is_action_legacy is
# True only for actions with neither layer nor slot. Strips have no name in 5.1,
# so we key strips by index and channelbags by their slot identifier.
#
# All seven tables fully materialise per query. Total keyframe rows in
# AI_TEST.blend run ~1.1k — comfortable. BestIndex pushdown on (action, layer)
# would help if a file pushes keyframes into the tens of thousands.


class Actions(IteratorVTable):
    schema = (
        'CREATE TABLE actions('
        'name TEXT, '
        'is_action_layered INTEGER, '
        'is_action_legacy INTEGER, '
        'frame_start REAL, '
        'frame_end REAL, '
        'use_cyclic INTEGER, '
        'use_frame_range INTEGER, '
        'users INTEGER, '
        'slot_count INTEGER, '
        'layer_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for a in bpy.data.actions:
            rows.append(
                (
                    a.name,
                    int(a.is_action_layered),
                    int(a.is_action_legacy),
                    float(a.frame_start),
                    float(a.frame_end),
                    int(a.use_cyclic),
                    int(a.use_frame_range),
                    int(a.users),
                    len(a.slots),
                    len(a.layers),
                )
            )
        return rows


class ActionSlots(IteratorVTable):
    # ActionSlot.users is a method returning the list of user datablocks; we
    # surface its length to match the rest of the schema's `users` column.
    schema = (
        'CREATE TABLE action_slots('
        'action TEXT, '
        'identifier TEXT, '
        'name_display TEXT, '
        'target_id_type TEXT, '
        'handle INTEGER, '
        'users INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for a in bpy.data.actions:
            for s in a.slots:
                try:
                    n_users = len(s.users())
                except Exception:
                    n_users = 0
                rows.append(
                    (
                        a.name,
                        s.identifier,
                        s.name_display,
                        s.target_id_type,
                        int(s.handle),
                        n_users,
                    )
                )
        return rows


class ActionLayers(IteratorVTable):
    schema = 'CREATE TABLE action_layers(action TEXT, name TEXT, strip_count INTEGER)'

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for a in bpy.data.actions:
            for layer in a.layers:
                rows.append((a.name, layer.name, len(layer.strips)))
        return rows


class ActionStrips(IteratorVTable):
    # Strips have no name in 5.1; positional index is the only identity. They
    # also have no frame_start/frame_end — those live on the layer / action.
    schema = (
        'CREATE TABLE action_strips('
        'action TEXT, '
        'layer TEXT, '
        'strip_index INTEGER, '
        'type TEXT, '
        'channelbag_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for a in bpy.data.actions:
            for layer in a.layers:
                for si, st in enumerate(layer.strips):
                    rows.append((a.name, layer.name, si, st.type, len(st.channelbags)))
        return rows


class ActionChannelbags(IteratorVTable):
    # Channelbags are keyed by slot_handle within a strip; we also surface the
    # human-friendly slot identifier (e.g. 'OBProbeCube') for joins from
    # animation_data.action_slot.
    schema = (
        'CREATE TABLE action_channelbags('
        'action TEXT, '
        'layer TEXT, '
        'strip_index INTEGER, '
        'slot_handle INTEGER, '
        'slot_identifier TEXT, '
        'fcurve_count INTEGER, '
        'group_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for a in bpy.data.actions:
            for layer in a.layers:
                for si, st in enumerate(layer.strips):
                    for cb in st.channelbags:
                        slot = cb.slot
                        rows.append(
                            (
                                a.name,
                                layer.name,
                                si,
                                int(cb.slot_handle),
                                slot.identifier if slot is not None else None,
                                len(cb.fcurves),
                                len(cb.groups),
                            )
                        )
        return rows


_FCURVE_COLUMNS: tuple[str, ...] = (
    'action',
    'layer',
    'strip_index',
    'channelbag',
    'fcurve_index',
    'data_path',
    'array_index',
    'extrapolation',
    'keyframe_count',
    'mute',
    'hide',
    'lock',
    'group',
    'has_driver',
    'is_empty',
    'is_valid',
)
_FC_COL_INDEX: dict[str, int] = {name: i for i, name in enumerate(_FCURVE_COLUMNS)}


class FCurves(WritableSnapshotVTable):
    table_name = 'fcurves'
    # Channelbag fcurves never carry drivers (drivers live on AnimData.drivers),
    # but has_driver is still a real RNA attribute so we surface it. The
    # composite key (action, layer, strip_index, channelbag, fcurve_index) joins
    # naturally to `keyframes`. `channelbag` is the slot identifier.
    schema = (
        'CREATE TABLE fcurves('
        'action TEXT, '
        'layer TEXT, '
        'strip_index INTEGER, '
        'channelbag TEXT, '
        'fcurve_index INTEGER, '
        'data_path TEXT, '
        'array_index INTEGER, '
        'extrapolation TEXT, '
        'keyframe_count INTEGER, '
        'mute INTEGER, '
        'hide INTEGER, '
        'lock INTEGER, '
        '"group" TEXT, '
        'has_driver INTEGER, '
        'is_empty INTEGER, '
        'is_valid INTEGER)'
    )

    def _snapshot(self) -> tuple[list[tuple[Any, ...]], list[_FCurveKey]]:
        rows: list[tuple[Any, ...]] = []
        idents: list[_FCurveKey] = []
        for a in bpy.data.actions:
            for layer in a.layers:
                for si, st in enumerate(layer.strips):
                    for cb in st.channelbags:
                        slot = cb.slot
                        cb_key = slot.identifier if slot is not None else None
                        for fi, fc in enumerate(cb.fcurves):
                            rows.append(_fcurve_row(a.name, layer.name, si, cb_key, fi, fc))
                            idents.append((a.name, layer.name, si, cb_key, fi))
        return rows, idents

    def _describe_identifier(self, identifier: Any) -> str:
        action, layer, si, cb, fi = identifier
        return f'{action}/{layer}/{si}/{cb}/{fi}'

    def _apply_insert(self, fields: tuple[Any, ...]) -> _FCurveKey:
        action = fields[_FC_COL_INDEX['action']]
        layer = fields[_FC_COL_INDEX['layer']]
        si = fields[_FC_COL_INDEX['strip_index']]
        cb_key = fields[_FC_COL_INDEX['channelbag']]
        data_path = fields[_FC_COL_INDEX['data_path']]
        if not isinstance(data_path, str) or not data_path:
            raise apsw.SQLError('INSERT into fcurves requires a non-empty data_path')
        array_index = fields[_FC_COL_INDEX['array_index']]
        array_index = 0 if array_index is None else int(array_index)
        group = fields[_FC_COL_INDEX['group']]
        cb = _resolve_channelbag(action, layer, si, cb_key)
        if cb.fcurves.find(data_path, index=array_index) is not None:
            raise apsw.SQLError(
                f"fcurve '{data_path}[{array_index}]' already exists in this channelbag"
            )
        fc = cb.fcurves.new(data_path, index=array_index, group_name=group or '')
        extrapolation = fields[_FC_COL_INDEX['extrapolation']]
        if extrapolation is not None:
            _set_enum(fc, 'extrapolation', extrapolation)
        for col, attr in (('mute', 'mute'), ('hide', 'hide'), ('lock', 'lock')):
            v = fields[_FC_COL_INDEX[col]]
            if v is not None:
                setattr(fc, attr, bool(v))
        new_index = list(cb.fcurves).index(fc)
        return (action, layer, si, cb_key, new_index)

    def _apply_update(self, identifier: Any, fields: tuple[Any, ...]) -> None:
        fc, key = _resolve_fcurve(identifier)
        current = _fcurve_row(*key, fc)
        for col in (
            'action',
            'layer',
            'strip_index',
            'channelbag',
            'fcurve_index',
            'data_path',
            'array_index',
            'keyframe_count',
            'has_driver',
            'is_empty',
            'is_valid',
        ):
            i = _FC_COL_INDEX[col]
            if fields[i] != current[i]:
                raise apsw.SQLError(f"column '{col}' is read-only on UPDATE")
        if fields[_FC_COL_INDEX['extrapolation']] != current[_FC_COL_INDEX['extrapolation']]:
            _set_enum(fc, 'extrapolation', fields[_FC_COL_INDEX['extrapolation']])
        for col, attr in (('mute', 'mute'), ('hide', 'hide'), ('lock', 'lock')):
            if fields[_FC_COL_INDEX[col]] != current[_FC_COL_INDEX[col]]:
                setattr(fc, attr, bool(fields[_FC_COL_INDEX[col]]))

    def _apply_delete(self, identifier: Any) -> None:
        fc, key = _resolve_fcurve(identifier)
        cb = _resolve_channelbag(key[0], key[1], key[2], key[3])
        cb.fcurves.remove(fc)


_KEYFRAME_COLUMNS: tuple[str, ...] = (
    'action',
    'layer',
    'strip_index',
    'channelbag',
    'fcurve_index',
    'index',
    'frame',
    'value',
    'interpolation',
    'easing',
    'handle_left_x',
    'handle_left_y',
    'handle_right_x',
    'handle_right_y',
    'handle_left_type',
    'handle_right_type',
    'type',
)
_KF_COL_INDEX: dict[str, int] = {name: i for i, name in enumerate(_KEYFRAME_COLUMNS)}

_KF_ENUM_COLS: tuple[tuple[str, str], ...] = (
    ('interpolation', 'interpolation'),
    ('easing', 'easing'),
    ('handle_left_type', 'handle_left_type'),
    ('handle_right_type', 'handle_right_type'),
    ('type', 'type'),
)


class Keyframes(WritableSnapshotVTable):
    table_name = 'keyframes'
    schema = (
        'CREATE TABLE keyframes('
        'action TEXT, '
        'layer TEXT, '
        'strip_index INTEGER, '
        'channelbag TEXT, '
        'fcurve_index INTEGER, '
        '"index" INTEGER, '
        'frame REAL, '
        'value REAL, '
        'interpolation TEXT, '
        'easing TEXT, '
        'handle_left_x REAL, '
        'handle_left_y REAL, '
        'handle_right_x REAL, '
        'handle_right_y REAL, '
        'handle_left_type TEXT, '
        'handle_right_type TEXT, '
        'type TEXT)'
    )

    def _snapshot(self) -> tuple[list[tuple[Any, ...]], list[_KeyframeKey]]:
        rows: list[tuple[Any, ...]] = []
        idents: list[_KeyframeKey] = []
        for a in bpy.data.actions:
            a_name = a.name
            for layer in a.layers:
                layer_name = layer.name
                for si, st in enumerate(layer.strips):
                    for cb in st.channelbags:
                        slot = cb.slot
                        cb_key = slot.identifier if slot is not None else None
                        for fi, fc in enumerate(cb.fcurves):
                            for ki, kp in enumerate(fc.keyframe_points):
                                rows.append(
                                    _keyframe_row(a_name, layer_name, si, cb_key, fi, ki, kp)
                                )
                                idents.append((a_name, layer_name, si, cb_key, fi, ki))
        return rows, idents

    def _describe_identifier(self, identifier: Any) -> str:
        action, layer, si, cb, fi, ki = identifier
        return f'{action}/{layer}/{si}/{cb}/{fi}#{ki}'

    def _apply_insert(self, fields: tuple[Any, ...]) -> _KeyframeKey:
        action = fields[_KF_COL_INDEX['action']]
        layer = fields[_KF_COL_INDEX['layer']]
        si = fields[_KF_COL_INDEX['strip_index']]
        cb_key = fields[_KF_COL_INDEX['channelbag']]
        fi = fields[_KF_COL_INDEX['fcurve_index']]
        if fi is None:
            raise apsw.SQLError('INSERT into keyframes requires fcurve_index')
        frame = fields[_KF_COL_INDEX['frame']]
        value = fields[_KF_COL_INDEX['value']]
        if frame is None or value is None:
            raise apsw.SQLError('INSERT into keyframes requires frame and value')
        fc, key = _resolve_fcurve((action, layer, si, cb_key, int(fi)))
        kp = fc.keyframe_points.insert(float(frame), float(value))
        for col, attr in _KF_ENUM_COLS:
            v = fields[_KF_COL_INDEX[col]]
            if v is not None:
                _set_enum(kp, attr, v)
        _apply_handles(kp, fields, current=None)
        fc.keyframe_points.sort()
        new_ki = next(
            (i for i, k in enumerate(fc.keyframe_points) if k.co[0] == float(frame)),
            len(fc.keyframe_points) - 1,
        )
        return (key[0], key[1], key[2], key[3], key[4], new_ki)

    def _apply_update(self, identifier: Any, fields: tuple[Any, ...]) -> None:
        kp, _fc, key = _resolve_keyframe(identifier)
        current = _keyframe_row(*key, kp)
        for col in ('action', 'layer', 'strip_index', 'channelbag', 'fcurve_index', 'index'):
            i = _KF_COL_INDEX[col]
            if fields[i] != current[i]:
                raise apsw.SQLError(f"column '{col}' is read-only on UPDATE")
        if fields[_KF_COL_INDEX['frame']] != current[_KF_COL_INDEX['frame']]:
            kp.co[0] = float(fields[_KF_COL_INDEX['frame']])
        if fields[_KF_COL_INDEX['value']] != current[_KF_COL_INDEX['value']]:
            kp.co[1] = float(fields[_KF_COL_INDEX['value']])
        for col, attr in _KF_ENUM_COLS:
            if fields[_KF_COL_INDEX[col]] != current[_KF_COL_INDEX[col]]:
                _set_enum(kp, attr, fields[_KF_COL_INDEX[col]])
        _apply_handles(kp, fields, current)

    def _apply_delete(self, identifier: Any) -> None:
        kp, fc, _key = _resolve_keyframe(identifier)
        fc.keyframe_points.remove(kp)


_FCurveKey = tuple[str, str, int, str | None, int]
_KeyframeKey = tuple[str, str, int, str | None, int, int]


def _resolve_channelbag(action: Any, layer_name: Any, strip_index: Any, cb_key: Any) -> Any:
    action_db = bpy.data.actions.get(action)
    if action_db is None:
        raise apsw.SQLError(f"action '{action}' not found")
    layer = action_db.layers.get(layer_name)
    if layer is None:
        raise apsw.SQLError(f"layer '{layer_name}' not found in action '{action}'")
    if strip_index is None or strip_index < 0 or strip_index >= len(layer.strips):
        raise apsw.SQLError(f"strip index {strip_index} out of range in layer '{layer_name}'")
    strip = layer.strips[int(strip_index)]
    for cb in strip.channelbags:
        slot = cb.slot
        if (slot.identifier if slot is not None else None) == cb_key:
            return cb
    raise apsw.SQLError(f"channelbag '{cb_key}' not found in strip {strip_index}")


def _resolve_fcurve(identifier: _FCurveKey) -> tuple[Any, _FCurveKey]:
    action, layer, si, cb_key, fi = identifier
    cb = _resolve_channelbag(action, layer, si, cb_key)
    if fi < 0 or fi >= len(cb.fcurves):
        raise apsw.SQLError(f'fcurve index {fi} out of range')
    return cb.fcurves[fi], identifier


def _resolve_keyframe(identifier: _KeyframeKey) -> tuple[Any, Any, _KeyframeKey]:
    action, layer, si, cb_key, fi, ki = identifier
    fc, _ = _resolve_fcurve((action, layer, si, cb_key, fi))
    if ki < 0 or ki >= len(fc.keyframe_points):
        raise apsw.SQLError(f'keyframe index {ki} out of range')
    return fc.keyframe_points[ki], fc, identifier


def _set_enum(obj: Any, attr: str, value: Any) -> None:
    if not isinstance(value, str):
        raise apsw.SQLError(f'{attr} must be a string')
    allowed = {item.identifier for item in obj.bl_rna.properties[attr].enum_items}
    if value not in allowed:
        raise apsw.SQLError(f"invalid {attr} '{value}' (allowed: {sorted(allowed)})")
    try:
        setattr(obj, attr, value)
    except (ValueError, TypeError) as exc:
        raise apsw.SQLError(f'{attr}: {exc}') from exc


def _apply_handles(kp: Any, fields: tuple[Any, ...], current: tuple[Any, ...] | None) -> None:
    def changed(col: str) -> bool:
        if current is None:
            return fields[_KF_COL_INDEX[col]] is not None
        return fields[_KF_COL_INDEX[col]] != current[_KF_COL_INDEX[col]]

    if changed('handle_left_x'):
        kp.handle_left[0] = float(fields[_KF_COL_INDEX['handle_left_x']])
    if changed('handle_left_y'):
        kp.handle_left[1] = float(fields[_KF_COL_INDEX['handle_left_y']])
    if changed('handle_right_x'):
        kp.handle_right[0] = float(fields[_KF_COL_INDEX['handle_right_x']])
    if changed('handle_right_y'):
        kp.handle_right[1] = float(fields[_KF_COL_INDEX['handle_right_y']])


def _fcurve_row(
    action: str, layer: str, si: int, cb_key: str | None, fi: int, fc: Any
) -> tuple[Any, ...]:
    grp = fc.group
    return (
        action,
        layer,
        si,
        cb_key,
        fi,
        fc.data_path,
        int(fc.array_index),
        fc.extrapolation,
        len(fc.keyframe_points),
        int(fc.mute),
        int(fc.hide),
        int(fc.lock),
        grp.name if grp is not None else None,
        int(bool(fc.driver)),
        int(fc.is_empty),
        int(fc.is_valid),
    )


def _keyframe_row(
    action: str, layer: str, si: int, cb_key: str | None, fi: int, ki: int, kp: Any
) -> tuple[Any, ...]:
    co = kp.co
    hl = kp.handle_left
    hr = kp.handle_right
    return (
        action,
        layer,
        si,
        cb_key,
        fi,
        ki,
        float(co[0]),
        float(co[1]),
        kp.interpolation,
        kp.easing,
        float(hl[0]),
        float(hl[1]),
        float(hr[0]),
        float(hr[1]),
        kp.handle_left_type,
        kp.handle_right_type,
        kp.type,
    )
