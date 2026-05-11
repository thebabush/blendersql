from __future__ import annotations

import json
from typing import Any

import bpy

from .base import IteratorVTable
from .modifiers import _dump_props

# dof is a nested struct on Camera (CameraDOFSettings); its focus_distance and
# aperture_fstop are surfaced as top-level columns since they're the most-asked
# DOF fields. Type-specific stuff (panorama_type, fisheye_*, shift_*) lives in
# params_json.
_CAMERA_COMMON: frozenset[str] = frozenset(
    {
        'rna_type',
        'name',
        'name_full',
        'id_type',
        'session_uid',
        'users',
        'use_fake_user',
        'use_extra_user',
        'is_embedded_data',
        'is_linked_packed',
        'is_missing',
        'is_runtime_data',
        'is_editable',
        'tag',
        'is_library_indirect',
        'is_evaluated',
        'original',
        'override_library',
        'library',
        'library_weak_reference',
        'asset_data',
        'preview',
        'animation_data',
        'type',
        'lens',
        'sensor_width',
        'sensor_height',
        'clip_start',
        'clip_end',
        'ortho_scale',
        'dof',
        'cycles_custom',
        'background_images',
    }
)


class Cameras(IteratorVTable):
    schema = (
        'CREATE TABLE cameras('
        'name TEXT, '
        'users INTEGER, '
        'type TEXT, '
        'lens REAL, '
        'sensor_width REAL, '
        'sensor_height REAL, '
        'clip_start REAL, '
        'clip_end REAL, '
        'ortho_scale REAL, '
        'dof_focus_distance REAL, '
        'fstop REAL, '
        'params_json TEXT)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for c in bpy.data.cameras:
            dof = c.dof
            rows.append(
                (
                    c.name,
                    int(c.users),
                    c.type,
                    float(c.lens),
                    float(c.sensor_width),
                    float(c.sensor_height),
                    float(c.clip_start),
                    float(c.clip_end),
                    float(c.ortho_scale),
                    float(dof.focus_distance),
                    float(dof.aperture_fstop),
                    json.dumps(_dump_props(c, _CAMERA_COMMON), default=str),
                )
            )
        return rows
