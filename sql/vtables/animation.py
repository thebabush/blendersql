from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ._meta import Column
from .base import IteratorVTable
from .datablocks import iter_named_datablocks


class AnimationData(IteratorVTable):
    # AnimData lives on many ID types — objects, cameras, materials, lights,
    # node_groups, scenes (with use_nodes), worlds, grease_pencils, armatures,
    # curves, meshes, linestyles, etc. We walk every named datablock that has
    # an `animation_data` slot. `action_slot_handle` is the durable link to a
    # channelbag (slot identifiers can rename).
    DESCRIPTION = 'AnimData blocks across every datablock kind: bound action, slot, NLA state.'
    AGENT_HINT = (
        'One row per datablock that owns an animation_data block. Read-only. JOIN actions ON '
        'actions.name=animation_data.action to inspect the bound action; JOIN action_slots ON '
        'action_slots.action=animation_data.action AND action_slots.identifier='
        'animation_data.action_slot for the active slot. action_slot_handle is the durable '
        'integer link to action_channelbags.slot_handle. Drivers live in the `drivers` vtable.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column(
            'owner_type',
            'TEXT',
            identifier=True,
            hint='Container kind (objects / materials / scenes / ...).',
        ),
        Column(
            'owner_id',
            'TEXT',
            identifier=True,
            hint='Datablock name that owns this animation_data.',
        ),
        Column('action', 'TEXT', hint='Bound action name; NULL if unbound.'),
        Column(
            'action_slot', 'TEXT', hint='Slot identifier within the bound action; NULL if unbound.'
        ),
        Column(
            'action_slot_handle',
            'INTEGER',
            hint='Durable handle linking to action_channelbags.slot_handle.',
        ),
        Column('use_nla', 'INTEGER', hint='Boolean as 0/1.'),
        Column('use_pin', 'INTEGER', hint='Boolean as 0/1.'),
        Column('use_tweak_mode', 'INTEGER', hint='Boolean as 0/1.'),
        Column('action_blend_type', 'TEXT', hint='REPLACE / COMBINE / ADD / SUBTRACT / MULTIPLY.'),
        Column('action_extrapolation', 'TEXT', hint='NOTHING / HOLD / HOLD_FORWARD.'),
        Column('action_influence', 'REAL', hint='Blend factor in [0,1].'),
        Column('last_slot_identifier', 'TEXT', hint='Slot identifier remembered from last bind.'),
        Column('driver_count', 'INTEGER', hint='len(animation_data.drivers).'),
    )
    RELATED: tuple[str, ...] = ('actions', 'action_slots', 'action_channelbags', 'drivers')
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
    DESCRIPTION = 'Property drivers on every datablock: expression, variables, remap curve.'
    AGENT_HINT = (
        'Read-only. Key is (owner_type, owner_id, data_path, array_index). JOIN animation_data '
        'ON animation_data.owner_type=drivers.owner_type AND animation_data.owner_id='
        'drivers.owner_id to find which datablock owns the driver. JOIN driver_variables on '
        'the same four-tuple to inspect inputs. Drivers attach to FCurves on the AnimData '
        'block, not the channelbag fcurves table.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column(
            'owner_type', 'TEXT', identifier=True, hint='Container kind of the owning datablock.'
        ),
        Column('owner_id', 'TEXT', identifier=True, hint='Owning datablock name.'),
        Column(
            'data_path',
            'TEXT',
            identifier=True,
            hint="RNA path being driven (e.g. 'location[0]').",
        ),
        Column(
            'array_index',
            'INTEGER',
            identifier=True,
            hint='Vector component index, 0 for scalars.',
        ),
        Column('type', 'TEXT', hint='AVERAGE / SUM / SCRIPTED / MIN / MAX.'),
        Column('expression', 'TEXT', hint='Python expression when type=SCRIPTED.'),
        Column('use_self', 'INTEGER', hint='Boolean as 0/1; expression has access to `self`.'),
        Column('is_valid', 'INTEGER', hint='Boolean as 0/1.'),
        Column('is_simple_expression', 'INTEGER', hint='Boolean as 0/1; safe expression flag.'),
        Column('mute', 'INTEGER', hint='Boolean as 0/1; disables the driver.'),
        Column('hide', 'INTEGER', hint='Boolean as 0/1 (UI-only).'),
        Column('lock', 'INTEGER', hint='Boolean as 0/1.'),
        Column('extrapolation', 'TEXT', hint='Extrapolation of the underlying remap fcurve.'),
        Column(
            'keyframe_count',
            'INTEGER',
            hint='len(driver_fcurve.keyframe_points); remap curve length.',
        ),
        Column('variable_count', 'INTEGER', hint='len(driver.variables).'),
    )
    RELATED: tuple[str, ...] = ('animation_data', 'driver_variables', 'driver_targets')
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
    DESCRIPTION = 'Driver input variables: name, type, target count.'
    AGENT_HINT = (
        'Read-only. Key is (owner_type, owner_id, data_path, array_index, name). JOIN drivers '
        'on the four-tuple to access expression/type; JOIN driver_targets on the five-tuple to '
        'walk inputs. Most types have 1 target; ROTATION_DIFF and LOC_DIFF have 2.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column(
            'owner_type', 'TEXT', identifier=True, hint='Container kind of the owning datablock.'
        ),
        Column('owner_id', 'TEXT', identifier=True, hint='Owning datablock name.'),
        Column('data_path', 'TEXT', identifier=True, hint='RNA path of the driven property.'),
        Column(
            'array_index',
            'INTEGER',
            identifier=True,
            hint='Vector component index of the driven property.',
        ),
        Column(
            'name', 'TEXT', identifier=True, hint='Variable name used in the driver expression.'
        ),
        Column(
            'type',
            'TEXT',
            hint='SINGLE_PROP / TRANSFORMS / ROTATION_DIFF / LOC_DIFF / CONTEXT_PROP.',
        ),
        Column('is_name_valid', 'INTEGER', hint='Boolean as 0/1; safe Python identifier.'),
        Column(
            'target_count',
            'INTEGER',
            hint='len(variable.targets); 1 for most, 2 for ROTATION_DIFF/LOC_DIFF.',
        ),
    )
    RELATED: tuple[str, ...] = ('drivers', 'driver_targets')
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
    DESCRIPTION = 'Driver variable targets: the actual ID + data_path / transform-source bindings.'
    AGENT_HINT = (
        'Read-only. Key is (owner_type, owner_id, data_path, array_index, variable, index). '
        'JOIN driver_variables on the five-tuple; JOIN objects ON objects.name=driver_targets.id '
        'when id_type=OBJECT to chase the actual datablock. bone_target is set for armature '
        'targets; transform_type / transform_space matter for TRANSFORMS variable type.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column(
            'owner_type', 'TEXT', identifier=True, hint='Container kind of the owning datablock.'
        ),
        Column('owner_id', 'TEXT', identifier=True, hint='Owning datablock name.'),
        Column('data_path', 'TEXT', identifier=True, hint='RNA path of the driven property.'),
        Column(
            'array_index',
            'INTEGER',
            identifier=True,
            hint='Vector component index of the driven property.',
        ),
        Column('variable', 'TEXT', identifier=True, hint='Owning driver variable name.'),
        Column(
            'index',
            'INTEGER',
            identifier=True,
            hint='Positional index in variable.targets (0 or 1).',
        ),
        Column(
            'id_type', 'TEXT', hint='OBJECT / MATERIAL / NODETREE / ... — what the id points to.'
        ),
        Column('id', 'TEXT', hint='Target datablock name; NULL if unset.'),
        Column(
            'target_data_path',
            'TEXT',
            hint='RNA path on the target; NULL/empty for transform sources.',
        ),
        Column(
            'transform_type', 'TEXT', hint='LOC_X / ROT_X / SCALE_X / ... for TRANSFORMS variables.'
        ),
        Column('transform_space', 'TEXT', hint='WORLD_SPACE / LOCAL_SPACE / TRANSFORM_SPACE.'),
        Column('rotation_mode', 'TEXT', hint='Rotation interpretation for rotation-diff targets.'),
        Column('bone_target', 'TEXT', hint='Bone name when id is an armature; NULL otherwise.'),
    )
    RELATED: tuple[str, ...] = ('driver_variables', 'drivers')
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
