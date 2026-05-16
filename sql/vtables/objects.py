from __future__ import annotations

from typing import Any

import apsw
import bpy

from ._meta import Column
from .base import WritableSnapshotVTable

_COLUMNS: tuple[str, ...] = (
    'name',
    'type',
    'parent',
    'data',
    'collection',
    'hide_viewport',
    'hide_render',
    'rotation_mode',
    'location_x',
    'location_y',
    'location_z',
    'rotation_x',
    'rotation_y',
    'rotation_z',
    'scale_x',
    'scale_y',
    'scale_z',
)
_COL_INDEX: dict[str, int] = {name: i for i, name in enumerate(_COLUMNS)}

_READ_ONLY_ON_UPDATE: frozenset[str] = frozenset({'type', 'data', 'collection'})
_INSERT_NON_EMPTY_HINT = (
    'INSERT into objects only supports type=EMPTY for v0; use bpy_exec to create '
    'objects with a data datablock (mesh/light/curve/…)'
)


class Objects(WritableSnapshotVTable):
    table_name = 'objects'
    DESCRIPTION = 'Scene objects: identity, type, transform, parent, first collection.'
    AGENT_HINT = (
        "Use for 'all empties', 'objects with no parent', mass renames, and transform updates. "
        'Writes are fine via UPDATE (name/parent/transforms/hides/rotation_mode); for new objects '
        'with a data datablock use the add_object() verb (only EMPTY supported via direct INSERT).'
    )
    COLUMNS: tuple[Column, ...] = (
        Column(
            'name',
            'TEXT',
            writable=True,
            pk=True,
            identifier=True,
            hint='Unique within bpy.data.objects.',
        ),
        Column(
            'type', 'TEXT', hint='MESH / EMPTY / LIGHT / CAMERA / ARMATURE / CURVE / GPENCIL / ...'
        ),
        Column('parent', 'TEXT', writable=True, hint='Name of parent object; NULL for root.'),
        Column('data', 'TEXT', hint='Name of the wrapped datablock (mesh / light / camera / ...).'),
        Column(
            'collection', 'TEXT', hint='First users_collection of the object (NULL if unlinked).'
        ),
        Column(
            'hide_viewport', 'INTEGER', writable=True, hint='Boolean as 0/1; viewport visibility.'
        ),
        Column('hide_render', 'INTEGER', writable=True, hint='Boolean as 0/1; render visibility.'),
        Column('rotation_mode', 'TEXT', writable=True, hint='XYZ / QUATERNION / AXIS_ANGLE / ...'),
        Column('location_x', 'REAL', writable=True),
        Column('location_y', 'REAL', writable=True),
        Column('location_z', 'REAL', writable=True),
        Column(
            'rotation_x',
            'REAL',
            writable=True,
            hint='Always Euler-stored; non-XYZ modes need bpy_exec.',
        ),
        Column('rotation_y', 'REAL', writable=True),
        Column('rotation_z', 'REAL', writable=True),
        Column('scale_x', 'REAL', writable=True),
        Column('scale_y', 'REAL', writable=True),
        Column('scale_z', 'REAL', writable=True),
    )
    RELATED: tuple[str, ...] = (
        'scene_objects',
        'collection_objects',
        'collections',
        'material_slots',
        'materials',
        'modifiers',
        'constraints',
        'meshes',
        'armatures',
        'lights',
        'cameras',
        'curves',
        'texts',
        'pose_bones',
        'vertex_groups',
    )
    DOMAIN = 'scene'
    schema = (
        'CREATE TABLE objects('
        'name TEXT, '
        'type TEXT, '
        'parent TEXT, '
        'data TEXT, '
        'collection TEXT, '
        'hide_viewport INTEGER, '
        'hide_render INTEGER, '
        'rotation_mode TEXT, '
        'location_x REAL, location_y REAL, location_z REAL, '
        'rotation_x REAL, rotation_y REAL, rotation_z REAL, '
        'scale_x REAL, scale_y REAL, scale_z REAL)'
    )

    def _snapshot(self) -> tuple[list[tuple[Any, ...]], list[str]]:
        rows: list[tuple[Any, ...]] = []
        names: list[str] = []
        for o in bpy.data.objects:
            rows.append(_row_for(o))
            names.append(o.name)
        return rows, names

    def _describe_identifier(self, identifier: Any) -> str:
        return str(identifier)

    def _apply_insert(self, fields: tuple[Any, ...]) -> str:
        return _apply_insert(fields)

    def _apply_update(self, identifier: Any, fields: tuple[Any, ...]) -> None:
        name = identifier
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise apsw.SQLError(f"object '{name}' no longer exists")
        _apply_update(obj, fields)

    def _apply_delete(self, identifier: Any) -> None:
        name = identifier
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise apsw.SQLError(f"object '{name}' no longer exists")
        bpy.data.objects.remove(obj, do_unlink=True)


def _apply_update(obj: bpy.types.Object, fields: tuple[Any, ...]) -> None:
    current = _row_for(obj)

    for col in _READ_ONLY_ON_UPDATE:
        idx = _COL_INDEX[col]
        if fields[idx] != current[idx]:
            raise apsw.SQLError(f"column '{col}' is read-only on UPDATE")

    new_name = fields[_COL_INDEX['name']]
    if new_name != current[_COL_INDEX['name']]:
        if not isinstance(new_name, str) or not new_name:
            raise apsw.SQLError('name must be a non-empty string')
        obj.name = new_name

    new_parent = fields[_COL_INDEX['parent']]
    if new_parent != current[_COL_INDEX['parent']]:
        if new_parent is None:
            obj.parent = None
        else:
            target = bpy.data.objects.get(new_parent)
            if target is None:
                raise apsw.SQLError(f"parent '{new_parent}' not found")
            obj.parent = target

    new_hv = fields[_COL_INDEX['hide_viewport']]
    if new_hv != current[_COL_INDEX['hide_viewport']]:
        obj.hide_viewport = bool(new_hv)

    new_hr = fields[_COL_INDEX['hide_render']]
    if new_hr != current[_COL_INDEX['hide_render']]:
        obj.hide_render = bool(new_hr)

    new_rmode = fields[_COL_INDEX['rotation_mode']]
    if new_rmode != current[_COL_INDEX['rotation_mode']]:
        _set_rotation_mode(obj, new_rmode)

    for axis_idx, col in enumerate(('location_x', 'location_y', 'location_z')):
        v = fields[_COL_INDEX[col]]
        if v != current[_COL_INDEX[col]]:
            obj.location[axis_idx] = float(v)

    # rotation_euler always stores Euler angles; if rotation_mode is QUATERNION
    # or AXIS_ANGLE the rotation_x/y/z columns still write into Euler — v0
    # limitation, callers should use bpy_exec for non-Euler rotation modes.
    for axis_idx, col in enumerate(('rotation_x', 'rotation_y', 'rotation_z')):
        v = fields[_COL_INDEX[col]]
        if v != current[_COL_INDEX[col]]:
            obj.rotation_euler[axis_idx] = float(v)

    for axis_idx, col in enumerate(('scale_x', 'scale_y', 'scale_z')):
        v = fields[_COL_INDEX[col]]
        if v != current[_COL_INDEX[col]]:
            obj.scale[axis_idx] = float(v)


def _apply_insert(fields: tuple[Any, ...]) -> str:
    name = fields[_COL_INDEX['name']]
    typ = fields[_COL_INDEX['type']]
    if not isinstance(name, str) or not name:
        raise apsw.SQLError('INSERT into objects requires a non-empty name')
    if typ is None:
        raise apsw.SQLError(
            "INSERT into objects requires a type (only 'EMPTY' is supported for v0)"
        )
    if typ != 'EMPTY':
        raise apsw.SQLError(_INSERT_NON_EMPTY_HINT)
    if fields[_COL_INDEX['data']] is not None:
        raise apsw.SQLError("data must be NULL for type='EMPTY' on INSERT")
    if fields[_COL_INDEX['collection']] is not None:
        raise apsw.SQLError(
            'explicit collection on INSERT is unsupported for v0; new objects link into the active scene collection'
        )

    # Resolve everything that can fail BEFORE creating the datablock, otherwise
    # a late raise leaves an orphaned object linked into the scene.
    parent_name = fields[_COL_INDEX['parent']]
    parent_target: bpy.types.Object | None = None
    if parent_name is not None:
        parent_target = bpy.data.objects.get(parent_name)
        if parent_target is None:
            raise apsw.SQLError(f"parent '{parent_name}' not found")

    rmode = fields[_COL_INDEX['rotation_mode']]
    if rmode is not None:
        if not isinstance(rmode, str):
            raise apsw.SQLError('rotation_mode must be a string')
        allowed = {
            item.identifier
            for item in bpy.types.Object.bl_rna.properties['rotation_mode'].enum_items
        }
        if rmode not in allowed:
            raise apsw.SQLError(f"invalid rotation_mode '{rmode}' (allowed: {sorted(allowed)})")

    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)

    if parent_target is not None:
        obj.parent = parent_target
    if rmode is not None:
        obj.rotation_mode = rmode

    hv = fields[_COL_INDEX['hide_viewport']]
    if hv is not None:
        obj.hide_viewport = bool(hv)
    hr = fields[_COL_INDEX['hide_render']]
    if hr is not None:
        obj.hide_render = bool(hr)

    for axis_idx, col in enumerate(('location_x', 'location_y', 'location_z')):
        v = fields[_COL_INDEX[col]]
        if v is not None:
            obj.location[axis_idx] = float(v)
    for axis_idx, col in enumerate(('rotation_x', 'rotation_y', 'rotation_z')):
        v = fields[_COL_INDEX[col]]
        if v is not None:
            obj.rotation_euler[axis_idx] = float(v)
    for axis_idx, col in enumerate(('scale_x', 'scale_y', 'scale_z')):
        v = fields[_COL_INDEX[col]]
        if v is not None:
            obj.scale[axis_idx] = float(v)

    return obj.name


def _set_rotation_mode(obj: bpy.types.Object, value: Any) -> None:
    if not isinstance(value, str):
        raise apsw.SQLError('rotation_mode must be a string')
    allowed = {item.identifier for item in obj.bl_rna.properties['rotation_mode'].enum_items}
    if value not in allowed:
        raise apsw.SQLError(f"invalid rotation_mode '{value}' (allowed: {sorted(allowed)})")
    obj.rotation_mode = value


def _row_for(obj: bpy.types.Object) -> tuple[Any, ...]:
    colls = obj.users_collection
    return (
        obj.name,
        obj.type,
        obj.parent.name if obj.parent else None,
        obj.data.name if obj.data is not None else None,
        colls[0].name if colls else None,
        int(obj.hide_viewport),
        int(obj.hide_render),
        obj.rotation_mode,
        obj.location.x,
        obj.location.y,
        obj.location.z,
        obj.rotation_euler.x,
        obj.rotation_euler.y,
        obj.rotation_euler.z,
        obj.scale.x,
        obj.scale.y,
        obj.scale.z,
    )
