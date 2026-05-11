"""Tier 1/3 file verbs: save, load, render, import_file, export_file.

Import/export wire only the operators that exist in a vanilla Blender 5.1:
FBX/GLTF via `bpy.ops.import_scene.*` / `export_scene.*`, and OBJ/STL/PLY/USD
via `bpy.ops.wm.*_import` / `*_export` *when present* — those C operators are
built-in on most 4.x+ builds but availability is probed at call time so a
trimmed build degrades to a clear error instead of an AttributeError.
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
import time
from typing import Any

import bpy
import mathutils

from ._common import VerbError, arg, envelope, opt_int, opt_str, parse_json_list, require_str, trunc

# format -> (import_operator_path, export_operator_path); None where unavailable.
_FORMAT_OPS: dict[str, tuple[str | None, str | None]] = {
    'OBJ': ('wm.obj_import', 'wm.obj_export'),
    'STL': ('wm.stl_import', 'wm.stl_export'),
    'PLY': ('wm.ply_import', 'wm.ply_export'),
    'USD': ('wm.usd_import', 'wm.usd_export'),
    'FBX': ('import_scene.fbx', 'export_scene.fbx'),
    'GLTF': ('import_scene.gltf', 'export_scene.gltf'),
    'GLB': ('import_scene.gltf', 'export_scene.gltf'),
    'X3D': ('import_scene.x3d', 'export_scene.x3d'),
}
_EXT_FORMAT: dict[str, str] = {
    '.obj': 'OBJ',
    '.stl': 'STL',
    '.ply': 'PLY',
    '.usd': 'USD',
    '.usda': 'USD',
    '.usdc': 'USD',
    '.usdz': 'USD',
    '.fbx': 'FBX',
    '.gltf': 'GLTF',
    '.glb': 'GLB',
    '.x3d': 'X3D',
}


def save(*args: Any) -> str:
    start = time.monotonic()
    filepath = opt_str(arg(args, 0), 'filepath')
    audit_text = trunc(f'save({filepath or ""})')
    try:
        if filepath is None and not bpy.data.filepath:
            raise VerbError('blend file has never been saved; pass a filepath')
        kw: dict[str, Any] = {}
        if filepath is not None:
            kw['filepath'] = filepath
        try:
            bpy.ops.wm.save_mainfile(**kw)
        except RuntimeError as exc:
            raise VerbError(f'save failed: {exc}') from exc
        return envelope(start, 'save', audit_text, {'filepath': bpy.data.filepath}, None)
    except Exception as exc:
        return envelope(start, 'save', audit_text, None, exc)


def load(*args: Any) -> str:
    start = time.monotonic()
    filepath = arg(args, 0)
    audit_text = trunc(f'load({filepath})')
    try:
        filepath = require_str(filepath, 'filepath')
        if not os.path.exists(filepath):
            raise VerbError(f"file not found: '{filepath}'")
        try:
            bpy.ops.wm.open_mainfile(filepath=filepath)
        except RuntimeError as exc:
            raise VerbError(f'load failed: {exc}') from exc
        return envelope(start, 'load', audit_text, {'filepath': bpy.data.filepath}, None)
    except Exception as exc:
        return envelope(start, 'load', audit_text, None, exc)


def render(*args: Any) -> str:
    start = time.monotonic()
    scene_name = opt_str(arg(args, 0), 'scene')
    filepath = opt_str(arg(args, 1), 'filepath')
    audit_text = trunc(f'render({scene_name or ""}, {filepath or ""})')
    try:
        scene = bpy.context.scene if scene_name is None else bpy.data.scenes.get(scene_name)
        if scene is None:
            raise VerbError(f"scene '{scene_name}' not found")
        frame = opt_int(arg(args, 2), 'frame', 0)
        if frame:
            scene.frame_set(frame)
        if filepath is not None:
            scene.render.filepath = filepath
        try:
            if scene_name is not None:
                with bpy.context.temp_override(scene=scene):
                    bpy.ops.render.render(write_still=True)
            else:
                bpy.ops.render.render(write_still=True)
        except RuntimeError as exc:
            raise VerbError(f'render failed (engine={scene.render.engine}): {exc}') from exc
        return envelope(start, 'render', audit_text, {'filepath': scene.render.filepath}, None)
    except Exception as exc:
        return envelope(start, 'render', audit_text, None, exc)


def render_object(*args: Any) -> str:
    start = time.monotonic()
    obj_name = arg(args, 0)
    audit_text = trunc(f'render_object({obj_name})')
    try:
        obj_name = require_str(obj_name, 'object')
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            raise VerbError(f"object '{obj_name}' not found")
        frame_arg = arg(args, 1)
        filepath = opt_str(arg(args, 2), 'filepath')
        size = opt_int(arg(args, 3), 'size', 512)
        if size < 1:
            raise VerbError('size must be a positive integer')
        if filepath is None:
            safe = re.sub(r'[^A-Za-z0-9._-]', '_', obj_name)
            filepath = os.path.join(tempfile.gettempdir(), f'blendersql_render_{safe}.png')

        # Source scene = the first that contains the object — we borrow its world
        # (GP layers with use_lights render black without one), engine, and frame.
        src = next((s for s in bpy.data.scenes if obj.name in s.objects), bpy.context.scene)

        if frame_arg is not None and frame_arg != '':
            if isinstance(frame_arg, bool) or not isinstance(frame_arg, (int, float)):
                raise VerbError('frame must be a number')
            target_frame = int(frame_arg)
        elif obj.type == 'GREASEPENCIL' and obj.data is not None:
            counts: dict[int, int] = {}
            for lay in obj.data.layers:
                for fr in lay.frames:
                    counts[fr.frame_number] = counts.get(fr.frame_number, 0) + len(
                        fr.drawing.strokes
                    )
            target_frame = max(counts, key=counts.__getitem__) if counts else src.frame_current
        else:
            target_frame = src.frame_current

        out_path = _render_isolated(obj, src, target_frame, size, filepath)
        return envelope(
            start,
            'render_object',
            audit_text,
            {'path': out_path, 'frame': target_frame, 'object': obj_name},
            None,
        )
    except Exception as exc:
        return envelope(start, 'render_object', audit_text, None, exc)


def _render_isolated(obj: Any, src_scene: Any, frame: int, size: int, filepath: str) -> str:
    # All rendering happens in a throwaway scene — the live scene, its camera,
    # render config, view layers, hide flags and frame are never touched. The
    # finally block guarantees the temp scene is removed even if the render
    # raises, so nothing leaks into bpy.data.
    stale = bpy.data.scenes.get('__bsql_render')
    if stale is not None:
        bpy.data.scenes.remove(stale)
    rs = bpy.data.scenes.new('__bsql_render')
    cam_obj = None
    cam_data = None
    try:
        rs.render.engine = src_scene.render.engine
        rs.render.resolution_x = size
        rs.render.resolution_y = size
        rs.render.resolution_percentage = 100
        rs.render.film_transparent = True
        rs.render.image_settings.file_format = 'PNG'
        rs.world = src_scene.world

        def link_rec(o: Any) -> None:
            if o.name not in rs.collection.objects:
                rs.collection.objects.link(o)
            for c in o.children:
                link_rec(c)

        link_rec(obj)
        rs.frame_set(frame)
        rs.render.filepath = filepath

        # Frame and render against the temp scene's evaluated depsgraph, so the
        # bounding box reflects the geometry at `frame` (GP drawings change per
        # keyframe — reading the cached obj.bound_box would use a stale extent).
        try:
            with bpy.context.temp_override(scene=rs):
                dg = bpy.context.evaluated_depsgraph_get()
                ob_eval = obj.evaluated_get(dg)
                corners = [obj.matrix_world @ mathutils.Vector(c) for c in ob_eval.bound_box]
                xs, ys, zs = zip(*[(c.x, c.y, c.z) for c in corners], strict=True)
                mn = mathutils.Vector((min(xs), min(ys), min(zs)))
                mx = mathutils.Vector((max(xs), max(ys), max(zs)))
                center = (mn + mx) * 0.5
                sz = mx - mn
                flat = min(range(3), key=lambda i: sz[i])
                others = [i for i in range(3) if i != flat]

                cam_data = bpy.data.cameras.new('__bsql_cam')
                cam_data.type = 'ORTHO'
                cam_data.ortho_scale = max(sz[others[0]], sz[others[1]], 0.01) * 1.12
                cam_obj = bpy.data.objects.new('__bsql_cam', cam_data)
                rs.collection.objects.link(cam_obj)
                loc = center.copy()
                loc[flat] += max(max(sz), 1.0) * 3 + 1
                cam_obj.location = loc
                cam_obj.rotation_euler = (
                    (center - cam_obj.location).to_track_quat('-Z', 'Y').to_euler()
                )
                rs.camera = cam_obj
                bpy.ops.render.render(write_still=True)
        except RuntimeError as exc:
            raise VerbError(f'render failed (engine={rs.render.engine}): {exc}') from exc
        return bpy.path.abspath(filepath)
    finally:
        if cam_obj is not None:
            with contextlib.suppress(Exception):
                bpy.data.objects.remove(cam_obj)
        if cam_data is not None:
            with contextlib.suppress(Exception):
                bpy.data.cameras.remove(cam_data)
        with contextlib.suppress(Exception):
            bpy.data.scenes.remove(rs)


def import_file(*args: Any) -> str:
    start = time.monotonic()
    filepath = arg(args, 0)
    fmt = arg(args, 1)
    audit_text = trunc(f'import_file({filepath}, {fmt or ""})')
    try:
        filepath = require_str(filepath, 'filepath')
        fmt = _resolve_format(opt_str(fmt, 'format'), filepath)
        if not os.path.exists(filepath):
            raise VerbError(f"file not found: '{filepath}'")
        op_path = _FORMAT_OPS[fmt][0]
        if op_path is None:
            raise VerbError(f"no import operator wired for format '{fmt}'")
        op = _resolve_op(op_path, fmt, 'import')
        try:
            op(filepath=filepath)
        except RuntimeError as exc:
            raise VerbError(f'import_file failed: {exc}') from exc
        bpy.ops.ed.undo_push(message=f'blendersql: import_file {fmt}')
        return envelope(
            start, 'import_file', audit_text, {'format': fmt, 'filepath': filepath}, None
        )
    except Exception as exc:
        return envelope(start, 'import_file', audit_text, None, exc)


def export_file(*args: Any) -> str:
    start = time.monotonic()
    filepath = arg(args, 0)
    fmt = arg(args, 1)
    audit_text = trunc(f'export_file({filepath}, {fmt or ""})')
    try:
        filepath = require_str(filepath, 'filepath')
        fmt = _resolve_format(opt_str(fmt, 'format'), filepath)
        op_path = _FORMAT_OPS[fmt][1]
        if op_path is None:
            raise VerbError(f"no export operator wired for format '{fmt}'")
        op = _resolve_op(op_path, fmt, 'export')
        selection = parse_json_list(arg(args, 2), 'selection_json')
        if selection is not None:
            _select_objects(selection)
        try:
            op(filepath=filepath)
        except RuntimeError as exc:
            raise VerbError(f'export_file failed: {exc}') from exc
        return envelope(
            start, 'export_file', audit_text, {'format': fmt, 'filepath': filepath}, None
        )
    except Exception as exc:
        return envelope(start, 'export_file', audit_text, None, exc)


def _resolve_format(fmt: str | None, filepath: str) -> str:
    if fmt is not None:
        key = fmt.upper()
        if key not in _FORMAT_OPS:
            raise VerbError(f"unknown format '{fmt}' (known: {sorted(_FORMAT_OPS)})")
        return key
    _, ext = os.path.splitext(filepath)
    inferred = _EXT_FORMAT.get(ext.lower())
    if inferred is None:
        raise VerbError(f"cannot infer format from extension '{ext}'; pass format explicitly")
    return inferred


def _resolve_op(op_path: str, fmt: str, direction: str) -> Any:
    node: Any = bpy.ops
    for part in op_path.split('.'):
        node = getattr(node, part, None)
        if node is None:
            raise VerbError(f"this Blender build has no {direction} operator for '{fmt}'")
    return node


def _select_objects(names: list[Any]) -> None:
    try:
        bpy.ops.object.select_all(action='DESELECT')
    except RuntimeError:
        for o in bpy.data.objects:
            o.select_set(False)
    for n in names:
        if not isinstance(n, str):
            raise VerbError('selection_json must be an array of object names')
        obj = bpy.data.objects.get(n)
        if obj is None:
            raise VerbError(f"object '{n}' not found")
        obj.select_set(True)
