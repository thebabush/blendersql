from __future__ import annotations

from typing import Any

import apsw
import bpy

from .base import WritableSnapshotVTable

_COLUMNS: tuple[str, ...] = (
    'name',
    'users',
    'use_nodes',
    'is_grease_pencil',
    'surface_render_method',
)
_COL_INDEX: dict[str, int] = {name: i for i, name in enumerate(_COLUMNS)}


class Materials(WritableSnapshotVTable):
    table_name = 'materials'
    schema = (
        'CREATE TABLE materials('
        'name TEXT, '
        'users INTEGER, '
        'use_nodes INTEGER, '
        'is_grease_pencil INTEGER, '
        'surface_render_method TEXT)'
    )

    def _snapshot(self) -> tuple[list[tuple[Any, ...]], list[str]]:
        rows: list[tuple[Any, ...]] = []
        names: list[str] = []
        for m in bpy.data.materials:
            rows.append(_row_for(m))
            names.append(m.name)
        return rows, names

    def _describe_identifier(self, identifier: Any) -> str:
        return str(identifier)

    def _apply_insert(self, fields: tuple[Any, ...]) -> str:
        name = fields[_COL_INDEX['name']]
        if not isinstance(name, str) or not name:
            raise apsw.SQLError('INSERT into materials requires a non-empty name')
        if bpy.data.materials.get(name) is not None:
            raise apsw.SQLError(f"material '{name}' already exists; use UPDATE")
        use_nodes = fields[_COL_INDEX['use_nodes']]
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True if use_nodes is None else bool(use_nodes)
        # is_grease_pencil attaches the GP-style backing via the dedicated
        # `create_gpencil_data` API; just setting the attribute is a no-op.
        # Toggling this back off after INSERT is out of scope (UPDATE keeps it
        # read-only — it would need to restructure the datablock).
        is_gp = fields[_COL_INDEX['is_grease_pencil']]
        if is_gp is not None and bool(is_gp):
            bpy.data.materials.create_gpencil_data(mat)
        srm = fields[_COL_INDEX['surface_render_method']]
        if srm is not None:
            _set_surface_render_method(mat, srm)
        return mat.name

    def _apply_update(self, identifier: Any, fields: tuple[Any, ...]) -> None:
        mat = bpy.data.materials.get(identifier)
        if mat is None:
            raise apsw.SQLError(f"material '{identifier}' no longer exists")
        current = _row_for(mat)

        new_users = fields[_COL_INDEX['users']]
        if new_users != current[_COL_INDEX['users']]:
            raise apsw.SQLError("column 'users' is read-only on UPDATE")

        # Toggling is_grease_pencil restructures the datablock (it swaps the
        # node-tree / GP-settings backing); reject rather than silently no-op.
        new_gp = fields[_COL_INDEX['is_grease_pencil']]
        if new_gp != current[_COL_INDEX['is_grease_pencil']]:
            raise apsw.SQLError("column 'is_grease_pencil' is read-only on UPDATE")

        new_name = fields[_COL_INDEX['name']]
        if new_name != current[_COL_INDEX['name']]:
            if not isinstance(new_name, str) or not new_name:
                raise apsw.SQLError('name must be a non-empty string')
            mat.name = new_name

        new_use_nodes = fields[_COL_INDEX['use_nodes']]
        if new_use_nodes != current[_COL_INDEX['use_nodes']]:
            mat.use_nodes = bool(new_use_nodes)

        new_srm = fields[_COL_INDEX['surface_render_method']]
        if new_srm != current[_COL_INDEX['surface_render_method']]:
            _set_surface_render_method(mat, new_srm)

    def _apply_delete(self, identifier: Any) -> None:
        mat = bpy.data.materials.get(identifier)
        if mat is None:
            raise apsw.SQLError(f"material '{identifier}' no longer exists")
        bpy.data.materials.remove(mat, do_unlink=True)


def _set_surface_render_method(mat: bpy.types.Material, value: Any) -> None:
    if not isinstance(value, str):
        raise apsw.SQLError('surface_render_method must be a string')
    allowed = {
        item.identifier for item in mat.bl_rna.properties['surface_render_method'].enum_items
    }
    if value not in allowed:
        raise apsw.SQLError(f"invalid surface_render_method '{value}' (allowed: {sorted(allowed)})")
    mat.surface_render_method = value


def _row_for(m: bpy.types.Material) -> tuple[Any, ...]:
    return (
        m.name,
        m.users,
        int(m.use_nodes),
        int(m.is_grease_pencil),
        m.surface_render_method,
    )


_SLOT_COLUMNS: tuple[str, ...] = ('object', 'slot_index', 'material', 'link')
_SLOT_COL_INDEX: dict[str, int] = {name: i for i, name in enumerate(_SLOT_COLUMNS)}


class MaterialSlots(WritableSnapshotVTable):
    """material_slots vtable.

    UPDATE rebinds slot.material to a different (or NULL) material datablock.
    INSERT / DELETE are intentionally not implemented: adding or removing a
    slot also requires remapping `mesh.polygons[i].material_index` (and the
    grease-pencil / curve equivalents), which is its own design problem —
    future work, do via bpy_exec for now.
    """

    table_name = 'material_slots'
    schema = (
        'CREATE TABLE material_slots(object TEXT, slot_index INTEGER, material TEXT, link TEXT)'
    )

    def _snapshot(self) -> tuple[list[tuple[Any, ...]], list[tuple[str, int]]]:
        rows: list[tuple[Any, ...]] = []
        idents: list[tuple[str, int]] = []
        for o in bpy.data.objects:
            for i, s in enumerate(o.material_slots):
                rows.append(
                    (
                        o.name,
                        i,
                        s.material.name if s.material else None,
                        s.link,
                    )
                )
                idents.append((o.name, i))
        return rows, idents

    def _describe_identifier(self, identifier: Any) -> str:
        obj_name, slot_index = identifier
        return f'{obj_name}[{slot_index}]'

    def _apply_insert(self, fields: tuple[Any, ...]) -> Any:
        raise apsw.SQLError(
            'INSERT into material_slots is not supported; use bpy_exec to append a slot '
            '(future work: SQL-level slot management needs material_index remapping)'
        )

    def _apply_update(self, identifier: Any, fields: tuple[Any, ...]) -> None:
        obj_name, slot_index = identifier
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            raise apsw.SQLError(f"object '{obj_name}' no longer exists")
        if slot_index < 0 or slot_index >= len(obj.material_slots):
            raise apsw.SQLError(
                f"slot_index {slot_index} out of range for '{obj_name}' "
                f'(has {len(obj.material_slots)} slot(s))'
            )
        slot = obj.material_slots[slot_index]
        current_material = slot.material.name if slot.material else None

        new_object = fields[_SLOT_COL_INDEX['object']]
        if new_object != obj_name:
            raise apsw.SQLError("column 'object' is read-only on UPDATE")
        new_slot_index = fields[_SLOT_COL_INDEX['slot_index']]
        if new_slot_index != slot_index:
            raise apsw.SQLError("column 'slot_index' is read-only on UPDATE")
        new_link = fields[_SLOT_COL_INDEX['link']]
        if new_link != slot.link:
            raise apsw.SQLError("column 'link' is read-only on UPDATE")

        new_material = fields[_SLOT_COL_INDEX['material']]
        if new_material == current_material:
            return
        if new_material is None:
            slot.material = None
            return
        if not isinstance(new_material, str):
            raise apsw.SQLError('material must be a string name or NULL')
        mat = bpy.data.materials.get(new_material)
        if mat is None:
            raise apsw.SQLError(f"material '{new_material}' not found")
        slot.material = mat

    def _apply_delete(self, identifier: Any) -> None:
        raise apsw.SQLError(
            'DELETE from material_slots is not supported; use bpy_exec to pop a slot '
            '(future work: SQL-level slot management needs material_index remapping)'
        )
