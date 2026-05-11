from __future__ import annotations

import json
from typing import Any

import bpy

from .base import IteratorVTable
from .modifiers import _dump_props

# Common fields surfaced as columns; type-specific (spot_size, shape, angle,
# shadow_soft_size, etc.) go into params_json via bl_rna enumeration. Skips
# ID-housekeeping fields (session_uid, is_evaluated, etc.) and node_tree which
# is queryable via the nodes vtables.
_LIGHT_COMMON: frozenset[str] = frozenset(
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
        'energy',
        'color',
        'use_shadow',
        'use_nodes',
        'diffuse_factor',
        'specular_factor',
        'node_tree',
        'cycles',
        'cycles_custom',
    }
)


class Lights(IteratorVTable):
    schema = (
        'CREATE TABLE lights('
        'name TEXT, '
        'users INTEGER, '
        'type TEXT, '
        'energy REAL, '
        'color_r REAL, color_g REAL, color_b REAL, '
        'use_shadow INTEGER, '
        'use_nodes INTEGER, '
        'diffuse_factor REAL, '
        'specular_factor REAL, '
        'params_json TEXT)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for light in bpy.data.lights:
            col = light.color
            rows.append(
                (
                    light.name,
                    int(light.users),
                    light.type,
                    float(light.energy),
                    float(col[0]),
                    float(col[1]),
                    float(col[2]),
                    int(light.use_shadow),
                    int(light.use_nodes),
                    float(light.diffuse_factor),
                    float(light.specular_factor),
                    json.dumps(_dump_props(light, _LIGHT_COMMON), default=str),
                )
            )
        return rows
