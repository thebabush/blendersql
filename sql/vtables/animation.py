from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .base import IteratorVTable
from .datablocks import iter_named_datablocks


class AnimationData(IteratorVTable):
    # AnimData lives on many ID types — objects, cameras, materials, lights,
    # node_groups, scenes (with use_nodes), worlds, grease_pencils, armatures,
    # curves, meshes, linestyles, etc. We walk every named datablock that has
    # an `animation_data` slot. `action_slot_handle` is the durable link to a
    # channelbag (slot identifiers can rename).
    schema = (
        'CREATE TABLE animation_data('
        'owner_type TEXT, '
        'owner_id TEXT, '
        'action TEXT, '
        'action_slot TEXT, '
        'action_slot_handle INTEGER, '
        'use_nla INTEGER, '
        'use_pin INTEGER, '
        'use_tweak_mode INTEGER, '
        'action_blend_type TEXT, '
        'action_extrapolation TEXT, '
        'action_influence REAL, '
        'last_slot_identifier TEXT, '
        'driver_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for kind, id_block, ad in _iter_anim_data():
            slot = ad.action_slot
            rows.append(
                (
                    kind,
                    id_block.name,
                    ad.action.name if ad.action else None,
                    slot.identifier if slot is not None else None,
                    int(ad.action_slot_handle),
                    int(ad.use_nla),
                    int(ad.use_pin),
                    int(ad.use_tweak_mode),
                    ad.action_blend_type,
                    ad.action_extrapolation,
                    float(ad.action_influence),
                    ad.last_slot_identifier or None,
                    len(ad.drivers),
                )
            )
        return rows


class Drivers(IteratorVTable):
    # Drivers identify by (owner_type, owner_id, data_path, array_index). The
    # underlying FCurve carries the driver — its own keyframe_points usually
    # describe a remap curve, surfaced via keyframe_count.
    schema = (
        'CREATE TABLE drivers('
        'owner_type TEXT, '
        'owner_id TEXT, '
        'data_path TEXT, '
        'array_index INTEGER, '
        'type TEXT, '
        'expression TEXT, '
        'use_self INTEGER, '
        'is_valid INTEGER, '
        'is_simple_expression INTEGER, '
        'mute INTEGER, '
        'hide INTEGER, '
        'lock INTEGER, '
        'extrapolation TEXT, '
        'keyframe_count INTEGER, '
        'variable_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for kind, id_block, ad in _iter_anim_data():
            for d_fc in ad.drivers:
                d = d_fc.driver
                rows.append(
                    (
                        kind,
                        id_block.name,
                        d_fc.data_path,
                        int(d_fc.array_index),
                        d.type,
                        d.expression,
                        int(d.use_self),
                        int(d.is_valid),
                        int(d.is_simple_expression),
                        int(d_fc.mute),
                        int(d_fc.hide),
                        int(d_fc.lock),
                        d_fc.extrapolation,
                        len(d_fc.keyframe_points),
                        len(d.variables),
                    )
                )
        return rows


class DriverVariables(IteratorVTable):
    schema = (
        'CREATE TABLE driver_variables('
        'owner_type TEXT, '
        'owner_id TEXT, '
        'data_path TEXT, '
        'array_index INTEGER, '
        'name TEXT, '
        'type TEXT, '
        'is_name_valid INTEGER, '
        'target_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for kind, id_block, ad in _iter_anim_data():
            for d_fc in ad.drivers:
                for v in d_fc.driver.variables:
                    rows.append(
                        (
                            kind,
                            id_block.name,
                            d_fc.data_path,
                            int(d_fc.array_index),
                            v.name,
                            v.type,
                            int(v.is_name_valid),
                            len(v.targets),
                        )
                    )
        return rows


class DriverTargets(IteratorVTable):
    # Most variable types have 1 target; ROTATION_DIFF and LOC_DIFF have 2.
    # DriverTarget.id is an ID datablock pointer — we store its name.
    schema = (
        'CREATE TABLE driver_targets('
        'owner_type TEXT, '
        'owner_id TEXT, '
        'data_path TEXT, '
        'array_index INTEGER, '
        'variable TEXT, '
        '"index" INTEGER, '
        'id_type TEXT, '
        'id TEXT, '
        'target_data_path TEXT, '
        'transform_type TEXT, '
        'transform_space TEXT, '
        'rotation_mode TEXT, '
        'bone_target TEXT)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for kind, id_block, ad in _iter_anim_data():
            for d_fc in ad.drivers:
                for v in d_fc.driver.variables:
                    for ti, t in enumerate(v.targets):
                        tid = t.id
                        rows.append(
                            (
                                kind,
                                id_block.name,
                                d_fc.data_path,
                                int(d_fc.array_index),
                                v.name,
                                ti,
                                t.id_type,
                                tid.name if tid is not None else None,
                                t.data_path or None,
                                t.transform_type,
                                t.transform_space,
                                t.rotation_mode,
                                t.bone_target or None,
                            )
                        )
        return rows


def _iter_anim_data() -> Iterator[tuple[str, Any, Any]]:
    for kind, id_block in iter_named_datablocks():
        ad = getattr(id_block, 'animation_data', None)
        if ad is None:
            continue
        yield kind, id_block, ad
