from __future__ import annotations

from typing import Any

import apsw
import bpy

from .base import WritableSnapshotVTable

# `material.grease_pencil` is a MaterialGPencilStyle in 5.1 (GP v3 kept the
# class name even though Annotation/GreasePencil v2 datablocks are gone).
# Row count tracks `materials.is_grease_pencil = 1` exactly. mix_color is RGBA
# in 5.1 (4 floats), so we surface it as 4 columns. mix_stroke_factor exists
# alongside mix_factor — the latter is the legacy fill mix factor.
#
# Writable via UPDATE: colors, styles, flags, texture transform, pass_index.
# `material` is the identity (read-only). INSERT/DELETE are not supported — a
# settings row exists iff its material is a Grease Pencil material; manage that
# through the materials surface / bpy_exec.

_COLUMNS: tuple[str, ...] = (
    'material',
    'mode',
    'color_r',
    'color_g',
    'color_b',
    'color_a',
    'fill_color_r',
    'fill_color_g',
    'fill_color_b',
    'fill_color_a',
    'mix_color_r',
    'mix_color_g',
    'mix_color_b',
    'mix_color_a',
    'stroke_style',
    'fill_style',
    'alignment_mode',
    'alignment_rotation',
    'mix_factor',
    'mix_stroke_factor',
    'gradient_type',
    'texture_angle',
    'texture_scale_x',
    'texture_scale_y',
    'texture_offset_x',
    'texture_offset_y',
    'texture_clamp',
    'pass_index',
    'pixel_size',
    'show_stroke',
    'show_fill',
    'use_fill_holdout',
    'use_stroke_holdout',
    'use_overlap_strokes',
    'flip',
    'ghost',
    'hide',
    'lock',
)
_COL_INDEX: dict[str, int] = {name: i for i, name in enumerate(_COLUMNS)}

# Split-component columns -> the MaterialGPencilStyle vector attribute they back.
_VECTOR_COLS: dict[str, tuple[str, ...]] = {
    'color': ('color_r', 'color_g', 'color_b', 'color_a'),
    'fill_color': ('fill_color_r', 'fill_color_g', 'fill_color_b', 'fill_color_a'),
    'mix_color': ('mix_color_r', 'mix_color_g', 'mix_color_b', 'mix_color_a'),
    'texture_scale': ('texture_scale_x', 'texture_scale_y'),
    'texture_offset': ('texture_offset_x', 'texture_offset_y'),
}
_ENUM_COLS: frozenset[str] = frozenset(
    {'mode', 'stroke_style', 'fill_style', 'alignment_mode', 'gradient_type'}
)
_FLOAT_COLS: frozenset[str] = frozenset(
    {'alignment_rotation', 'mix_factor', 'mix_stroke_factor', 'texture_angle', 'pixel_size'}
)
_INT_COLS: frozenset[str] = frozenset({'pass_index'})
_BOOL_COLS: frozenset[str] = frozenset(
    {
        'texture_clamp',
        'show_stroke',
        'show_fill',
        'use_fill_holdout',
        'use_stroke_holdout',
        'use_overlap_strokes',
        'flip',
        'ghost',
        'hide',
        'lock',
    }
)


class MaterialGpSettings(WritableSnapshotVTable):
    table_name = 'material_gp_settings'
    schema = (
        'CREATE TABLE material_gp_settings('
        'material TEXT, '
        'mode TEXT, '
        'color_r REAL, color_g REAL, color_b REAL, color_a REAL, '
        'fill_color_r REAL, fill_color_g REAL, fill_color_b REAL, fill_color_a REAL, '
        'mix_color_r REAL, mix_color_g REAL, mix_color_b REAL, mix_color_a REAL, '
        'stroke_style TEXT, '
        'fill_style TEXT, '
        'alignment_mode TEXT, '
        'alignment_rotation REAL, '
        'mix_factor REAL, '
        'mix_stroke_factor REAL, '
        'gradient_type TEXT, '
        'texture_angle REAL, '
        'texture_scale_x REAL, texture_scale_y REAL, '
        'texture_offset_x REAL, texture_offset_y REAL, '
        'texture_clamp INTEGER, '
        'pass_index INTEGER, '
        'pixel_size REAL, '
        'show_stroke INTEGER, '
        'show_fill INTEGER, '
        'use_fill_holdout INTEGER, '
        'use_stroke_holdout INTEGER, '
        'use_overlap_strokes INTEGER, '
        'flip INTEGER, '
        'ghost INTEGER, '
        'hide INTEGER, '
        'lock INTEGER)'
    )

    def _snapshot(self) -> tuple[list[tuple[Any, ...]], list[str]]:
        rows: list[tuple[Any, ...]] = []
        names: list[str] = []
        for m in bpy.data.materials:
            if not m.is_grease_pencil:
                continue
            gp = m.grease_pencil
            if gp is None:
                continue
            rows.append(_row_for(m.name, gp))
            names.append(m.name)
        return rows, names

    def _describe_identifier(self, identifier: Any) -> str:
        return str(identifier)

    def _apply_insert(self, fields: tuple[Any, ...]) -> Any:
        raise apsw.SQLError(
            'INSERT into material_gp_settings is not supported — a row exists iff its material '
            'is a Grease Pencil material; create that first (bpy_exec: bpy.data.materials.create_gpencil_data(mat)) '
            'then UPDATE here'
        )

    def _apply_delete(self, identifier: Any) -> None:
        raise apsw.SQLError(
            'DELETE from material_gp_settings is not supported — the settings are intrinsic to a '
            'Grease Pencil material; delete the material via DELETE FROM materials'
        )

    def _apply_update(self, identifier: Any, fields: tuple[Any, ...]) -> None:
        name = identifier
        mat = bpy.data.materials.get(name)
        if mat is None:
            raise apsw.SQLError(f"no material named '{name}'")
        gp = mat.grease_pencil
        if gp is None:
            raise apsw.SQLError(f"material '{name}' is not a Grease Pencil material")
        current = _row_for(name, gp)

        if fields[_COL_INDEX['material']] != current[_COL_INDEX['material']]:
            raise apsw.SQLError("column 'material' is read-only on UPDATE")

        for attr, cols in _VECTOR_COLS.items():
            new_vec = tuple(float(fields[_COL_INDEX[c]]) for c in cols)
            cur_vec = tuple(float(current[_COL_INDEX[c]]) for c in cols)
            if new_vec != cur_vec:
                try:
                    setattr(gp, attr, new_vec)
                except (ValueError, TypeError) as exc:
                    raise apsw.SQLError(f'{attr}: {exc}') from exc

        for col in _ENUM_COLS:
            v = fields[_COL_INDEX[col]]
            if v != current[_COL_INDEX[col]]:
                try:
                    setattr(gp, col, v)
                except (ValueError, TypeError) as exc:
                    raise apsw.SQLError(f'{col}: {exc}') from exc
        for col in _FLOAT_COLS:
            v = fields[_COL_INDEX[col]]
            if v != current[_COL_INDEX[col]]:
                setattr(gp, col, float(v))
        for col in _INT_COLS:
            v = fields[_COL_INDEX[col]]
            if v != current[_COL_INDEX[col]]:
                setattr(gp, col, int(v))
        for col in _BOOL_COLS:
            v = fields[_COL_INDEX[col]]
            if v != current[_COL_INDEX[col]]:
                setattr(gp, col, bool(v))


def _row_for(name: str, gp: Any) -> tuple[Any, ...]:
    c = gp.color
    fc = gp.fill_color
    mc = gp.mix_color
    ts = gp.texture_scale
    to = gp.texture_offset
    return (
        name,
        gp.mode,
        float(c[0]),
        float(c[1]),
        float(c[2]),
        float(c[3]),
        float(fc[0]),
        float(fc[1]),
        float(fc[2]),
        float(fc[3]),
        float(mc[0]),
        float(mc[1]),
        float(mc[2]),
        float(mc[3]),
        gp.stroke_style,
        gp.fill_style,
        gp.alignment_mode,
        float(gp.alignment_rotation),
        float(gp.mix_factor),
        float(gp.mix_stroke_factor),
        gp.gradient_type,
        float(gp.texture_angle),
        float(ts[0]),
        float(ts[1]),
        float(to[0]),
        float(to[1]),
        int(gp.texture_clamp),
        int(gp.pass_index),
        float(gp.pixel_size),
        int(gp.show_stroke),
        int(gp.show_fill),
        int(gp.use_fill_holdout),
        int(gp.use_stroke_holdout),
        int(gp.use_overlap_strokes),
        int(gp.flip),
        int(gp.ghost),
        int(gp.hide),
        int(gp.lock),
    )
