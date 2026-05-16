from __future__ import annotations

from typing import Any

import bpy

from ._meta import Column
from .base import IteratorVTable


class Armatures(IteratorVTable):
    DESCRIPTION = 'Armature datablocks: name, refcount, bone count.'
    AGENT_HINT = (
        'Top of the rigging tree (armatures -> bones; pose_bones is the per-object runtime view). '
        'Read-only; mutate via bpy_exec. JOIN objects ON objects.data=armatures.name to find armature '
        'objects (multiple objects can share one armature datablock); JOIN bones ON bones.armature=armatures.name.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column('name', 'TEXT', identifier=True, hint='Unique within bpy.data.armatures.'),
        Column(
            'users', 'INTEGER', hint='Refcount across the file (objects sharing this armature).'
        ),
        Column('bone_count', 'INTEGER', hint='len(armature.bones); rest-pose bones.'),
    )
    RELATED: tuple[str, ...] = ('bones', 'pose_bones', 'objects')
    schema = 'CREATE TABLE armatures(name TEXT, users INTEGER, bone_count INTEGER)'

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for a in bpy.data.armatures:
            rows.append((a.name, a.users, len(a.bones)))
        return rows


class Bones(IteratorVTable):
    # Rest-pose bones from armature DATA — one row per bone per armature.
    # Multiple armature objects can share an armature datablock; pose-space
    # transforms live on pose_bones (per-object).
    DESCRIPTION = (
        'Rest-pose bones from armature data: hierarchy, deform flags, head/tail in local space.'
    )
    AGENT_HINT = (
        'Tree level 2 (armatures -> bones). Read-only; head_local/tail_local are armature-local rest '
        'positions — edit-mode topology lives here, NOT pose-space transforms (see pose_bones for those). '
        'Key is (armature, name). JOIN armatures ON armatures.name=bones.armature; JOIN pose_bones ON '
        'pose_bones.name=bones.name within an armature object (pose_bones is per-object, not per-data).'
    )
    COLUMNS: tuple[Column, ...] = (
        Column(
            'armature', 'TEXT', identifier=True, hint='Owning armatures.name; part of identity.'
        ),
        Column('name', 'TEXT', identifier=True, hint='Bone name; unique within the armature.'),
        Column('parent', 'TEXT', hint='Parent bone name; NULL for root bones.'),
        Column('use_deform', 'INTEGER', hint='Boolean as 0/1; bone deforms geometry.'),
        Column('use_connect', 'INTEGER', hint='Boolean as 0/1; head locked to parent tail.'),
        Column('envelope_weight', 'REAL', hint='Envelope deform weight multiplier.'),
        Column('head_local_x', 'REAL', hint='Rest head position X in armature-local space.'),
        Column('head_local_y', 'REAL', hint='Rest head position Y in armature-local space.'),
        Column('head_local_z', 'REAL', hint='Rest head position Z in armature-local space.'),
        Column('tail_local_x', 'REAL', hint='Rest tail position X in armature-local space.'),
        Column('tail_local_y', 'REAL', hint='Rest tail position Y in armature-local space.'),
        Column('tail_local_z', 'REAL', hint='Rest tail position Z in armature-local space.'),
    )
    RELATED: tuple[str, ...] = ('armatures', 'pose_bones', 'vertex_groups')
    schema = (
        'CREATE TABLE bones('
        'armature TEXT, '
        'name TEXT, '
        'parent TEXT, '
        'use_deform INTEGER, '
        'use_connect INTEGER, '
        'envelope_weight REAL, '
        'head_local_x REAL, head_local_y REAL, head_local_z REAL, '
        'tail_local_x REAL, tail_local_y REAL, tail_local_z REAL)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for a in bpy.data.armatures:
            for b in a.bones:
                hl = b.head_local
                tl = b.tail_local
                rows.append(
                    (
                        a.name,
                        b.name,
                        b.parent.name if b.parent is not None else None,
                        int(b.use_deform),
                        int(b.use_connect),
                        float(b.envelope_weight),
                        float(hl[0]),
                        float(hl[1]),
                        float(hl[2]),
                        float(tl[0]),
                        float(tl[1]),
                        float(tl[2]),
                    )
                )
        return rows


class PoseBones(IteratorVTable):
    # Pose-space transforms live on the OBJECT, not the armature data, so two
    # objects sharing one armature datablock produce two pose_bones rows per
    # bone (one per object).
    DESCRIPTION = 'Per-object pose-space bone transforms: location/rotation/scale relative to rest.'
    AGENT_HINT = (
        'Runtime per-object pose state (objects -> pose_bones; rest geometry is in bones). Read-only; '
        'two objects sharing one armature datablock yield two pose_bones rows per bone. Key is '
        "(object, name). head/tail aren't surfaced here — they're rest-pose only on bones. JOIN bones "
        'ON bones.name=pose_bones.name AND bones.armature=<armature_data_of_object>; JOIN constraints '
        "ON constraints.owner_type='POSE_BONE' AND constraints.owner_name=pose_bones.object||'/'||pose_bones.name."
    )
    COLUMNS: tuple[Column, ...] = (
        Column(
            'object', 'TEXT', identifier=True, hint='Owning armature object name (objects.name).'
        ),
        Column(
            'name',
            'TEXT',
            identifier=True,
            hint='Pose-bone name (matches the rest-pose bones.name).',
        ),
        Column('location_x', 'REAL', hint='Pose-space location offset X relative to rest.'),
        Column('location_y', 'REAL', hint='Pose-space location offset Y relative to rest.'),
        Column('location_z', 'REAL', hint='Pose-space location offset Z relative to rest.'),
        Column('rotation_quaternion_w', 'REAL', hint='Pose rotation quaternion W.'),
        Column('rotation_quaternion_x', 'REAL', hint='Pose rotation quaternion X.'),
        Column('rotation_quaternion_y', 'REAL', hint='Pose rotation quaternion Y.'),
        Column('rotation_quaternion_z', 'REAL', hint='Pose rotation quaternion Z.'),
        Column(
            'rotation_mode', 'TEXT', hint='QUATERNION / XYZ / AXIS_ANGLE / ... — per pose-bone.'
        ),
        Column('scale_x', 'REAL', hint='Pose scale X.'),
        Column('scale_y', 'REAL', hint='Pose scale Y.'),
        Column('scale_z', 'REAL', hint='Pose scale Z.'),
        Column(
            'constraint_count', 'INTEGER', hint='len(pose_bone.constraints); see constraints table.'
        ),
    )
    RELATED: tuple[str, ...] = ('bones', 'armatures', 'objects', 'constraints')
    schema = (
        'CREATE TABLE pose_bones('
        'object TEXT, '
        'name TEXT, '
        'location_x REAL, location_y REAL, location_z REAL, '
        'rotation_quaternion_w REAL, rotation_quaternion_x REAL, rotation_quaternion_y REAL, rotation_quaternion_z REAL, '
        'rotation_mode TEXT, '
        'scale_x REAL, scale_y REAL, scale_z REAL, '
        'constraint_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for o in bpy.data.objects:
            if o.type != 'ARMATURE' or o.pose is None:
                continue
            for pb in o.pose.bones:
                loc = pb.location
                q = pb.rotation_quaternion
                sc = pb.scale
                rows.append(
                    (
                        o.name,
                        pb.name,
                        float(loc[0]),
                        float(loc[1]),
                        float(loc[2]),
                        float(q[0]),
                        float(q[1]),
                        float(q[2]),
                        float(q[3]),
                        pb.rotation_mode,
                        float(sc[0]),
                        float(sc[1]),
                        float(sc[2]),
                        len(pb.constraints),
                    )
                )
        return rows
