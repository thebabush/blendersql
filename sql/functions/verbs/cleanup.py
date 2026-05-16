"""Housekeeping verbs that wrap Blender's "clean up" operators.

purge_orphans              -> bpy.ops.outliner.orphans_purge (the Orphan Data
                              "Purge" button); removes datablocks with 0 real
                              users (fake-user'd ones survive).
remove_unused_material_slots -> drops material slots no face/stroke/spline
                              references, via `data.materials.pop(index=…)`
                              (Blender remaps the geometry's material indices
                              as it pops, same as the UI's "Remove Unused
                              Slots"). We do it directly rather than through
                              bpy.ops.object.material_slot_remove_unused
                              because that operator's poll fails in
                              `--background` (no editable-object context).

Both report exactly what they removed, since these are destructive ("I mean
it") operations. orphans_purge's undo-ability depends on the Blender version;
slot removal is reliably undoable.
"""

from __future__ import annotations

import time
from typing import Any

import bpy

from ...vtables.datablocks import DATABLOCK_KINDS
from .._meta import function_meta
from ._common import VerbError, arg, envelope, opt_str


def _id_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for attr in DATABLOCK_KINDS:
        c = getattr(bpy.data, attr, None)
        if c is not None:
            out[attr] = len(c)
    return out


@function_meta(
    kind='verb',
    arity=-1,
    description='Purge datablocks with no real users (the Orphan Data "Purge" button).',
    agent_hint=(
        'Args: (recursive?). Reports a per-kind removal tally so the agent '
        'can verify what was freed. Datablocks with fake_user=1 survive — '
        "that's by design."
    ),
    return_shape='json_envelope',
    side_effects=True,
)
def purge_orphans(*args: Any) -> str:
    start = time.monotonic()
    recursive = bool(arg(args, 0))
    audit_text = f'purge_orphans(recursive={recursive})'
    try:
        before = _id_counts()
        try:
            bpy.ops.outliner.orphans_purge(
                do_local_ids=True, do_linked_ids=True, do_recursive=recursive
            )
        except RuntimeError as exc:
            raise VerbError(f'orphans_purge failed: {exc}') from exc
        after = _id_counts()
        removed = {
            k: before[k] - after.get(k, 0) for k in before if before[k] - after.get(k, 0) > 0
        }
        bpy.ops.ed.undo_push(message='blendersql: purge orphans')
        return envelope(
            start,
            'purge_orphans',
            audit_text,
            {'removed': removed, 'total': sum(removed.values()), 'recursive': recursive},
            None,
        )
    except Exception as exc:
        return envelope(start, 'purge_orphans', audit_text, None, exc)


def _used_material_indices(obj: Any) -> set[int] | None:
    """Material-slot indices referenced by the object's geometry, or None if we
    can't tell (in which case nothing is removed)."""
    data = getattr(obj, 'data', None)
    if data is None or not hasattr(data, 'materials'):
        return None
    if obj.type == 'MESH':
        return {p.material_index for p in data.polygons}
    if obj.type in ('CURVE', 'SURFACE', 'FONT'):
        return {sp.material_index for sp in data.splines}
    if obj.type == 'GREASEPENCIL':
        used: set[int] = set()
        for layer in data.layers:
            for fr in layer.frames:
                for st in fr.drawing.strokes:
                    used.add(st.material_index)
        return used
    return None  # other data types: leave their slots alone


@function_meta(
    kind='verb',
    arity=-1,
    description='Drop material slots not referenced by an object data geometry.',
    agent_hint=(
        'Args: (object?). With no object, walks every object with material '
        'slots. Pops empty slots from the data datablock (mesh/curve/GP), so '
        'shared geometry only pays once. Reports per-object tallies.'
    ),
    return_shape='json_envelope',
    side_effects=True,
)
def remove_unused_material_slots(*args: Any) -> str:
    start = time.monotonic()
    obj_name = opt_str(arg(args, 0), 'object')
    audit_text = f'remove_unused_material_slots({obj_name or "*"})'
    try:
        if obj_name is not None:
            o = bpy.data.objects.get(obj_name)
            if o is None:
                raise VerbError(f"object '{obj_name}' not found")
            targets = [o]
        else:
            targets = [o for o in bpy.data.objects if len(o.material_slots) > 0]

        per_object: dict[str, int] = {}
        seen_data: set[int] = set()  # shared meshes/GP: pop once, but credit each user
        for o in targets:
            data = getattr(o, 'data', None)
            if data is None or not hasattr(data, 'materials'):
                continue
            n0 = len(data.materials)
            if n0 == 0:
                continue
            removed = 0
            if id(data) not in seen_data:
                used = _used_material_indices(o)
                if used is not None:
                    for i in reversed(range(n0)):
                        if i not in used:
                            data.materials.pop(index=i)  # Blender remaps the geometry's indices
                            removed += 1
                seen_data.add(id(data))
            else:
                removed = n0 - len(data.materials)  # already popped via another user of this data
            if removed > 0:
                per_object[o.name] = removed
        total = sum(per_object.values())
        if total:
            bpy.ops.ed.undo_push(message='blendersql: remove unused material slots')
        return envelope(
            start,
            'remove_unused_material_slots',
            audit_text,
            {'objects': per_object, 'total': total},
            None,
        )
    except Exception as exc:
        return envelope(start, 'remove_unused_material_slots', audit_text, None, exc)
