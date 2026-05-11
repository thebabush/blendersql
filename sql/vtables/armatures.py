from __future__ import annotations

from typing import Any

import bpy

from .base import IteratorVTable


class Armatures(IteratorVTable):
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
