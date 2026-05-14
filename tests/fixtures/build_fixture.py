"""Generate the deterministic test_scene.blend fixture inside Blender.

Run as:
    blender --background --factory-startup \
        --python tests/fixtures/build_fixture.py -- <output_path>

The fixture exercises every vtable with at least one row where practical.
Keep additions to this scene minimal and predictable — tests/fixtures/expected.py
hardcodes the resulting row counts.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import bpy


def _reset_scene() -> None:
    for block_seq in (
        bpy.data.objects,
        bpy.data.meshes,
        bpy.data.armatures,
        bpy.data.lights,
        bpy.data.cameras,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.actions,
        bpy.data.grease_pencils,
        bpy.data.images,
        bpy.data.collections,
        bpy.data.node_groups,
    ):
        for block in list(block_seq):
            with contextlib.suppress(RuntimeError, ReferenceError):
                block_seq.remove(block, do_unlink=True)


def _build_cube() -> bpy.types.Object:
    mesh = bpy.data.meshes.new('CubeMesh')
    verts = [
        (-1, -1, -1),
        (1, -1, -1),
        (1, 1, -1),
        (-1, 1, -1),
        (-1, -1, 1),
        (1, -1, 1),
        (1, 1, 1),
        (-1, 1, 1),
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (2, 3, 7, 6),
        (1, 2, 6, 5),
        (3, 0, 4, 7),
    ]
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    obj = bpy.data.objects.new('Cube', mesh)
    bpy.context.scene.collection.objects.link(obj)

    obj.modifiers.new('Subdiv', type='SUBSURF')

    vg = obj.vertex_groups.new(name='TopHalf')
    vg.add([4, 5, 6, 7], 1.0, 'REPLACE')

    # Shape keys: Basis first, then 'Stretch' value=0.5.
    obj.shape_key_add(name='Basis')
    stretch = obj.shape_key_add(name='Stretch')
    stretch.value = 0.5

    obj['health'] = 100
    ui = obj.id_properties_ui('health')
    ui.update(min=0, max=200, description='Hit points')

    mat = bpy.data.materials.new('Mat')
    mat.use_nodes = True
    obj.data.materials.append(mat)

    return obj


def _build_armature() -> bpy.types.Object:
    arm_data = bpy.data.armatures.new('RigData')
    arm_obj = bpy.data.objects.new('Rig', arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)

    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')
    eb_root = arm_data.edit_bones.new('Root')
    eb_root.head = (0, 0, 0)
    eb_root.tail = (0, 0, 1)
    eb_child = arm_data.edit_bones.new('Child')
    eb_child.head = (0, 0, 1)
    eb_child.tail = (0, 0, 2)
    eb_child.parent = eb_root
    bpy.ops.object.mode_set(mode='OBJECT')

    return arm_obj


def _build_light() -> bpy.types.Object:
    light_data = bpy.data.lights.new('Sun', type='SUN')
    light_data.energy = 5
    obj = bpy.data.objects.new('Sun', light_data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _build_camera() -> bpy.types.Object:
    cam_data = bpy.data.cameras.new('Cam')
    obj = bpy.data.objects.new('Cam', cam_data)
    obj.location = (7, -7, 5)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _build_curve() -> bpy.types.Object:
    curve = bpy.data.curves.new('PathData', type='CURVE')
    curve.dimensions = '3D'
    spline = curve.splines.new('BEZIER')
    spline.bezier_points.add(2)
    for i, pt in enumerate(spline.bezier_points):
        pt.co = (i, 0, 0)
        pt.handle_left = (i - 0.25, 0, 0)
        pt.handle_right = (i + 0.25, 0, 0)
    obj = bpy.data.objects.new('Path', curve)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _build_text() -> bpy.types.Object:
    text = bpy.data.curves.new('TitleData', type='FONT')
    text.body = 'Hi'
    obj = bpy.data.objects.new('Title', text)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _build_action(cube: bpy.types.Object) -> bpy.types.Action:
    cube.animation_data_create()
    action = bpy.data.actions.new('CubeAction')
    cube.animation_data.action = action
    # Keyframe location across frames 1..30 — exercises the layered action path.
    for frame in (1, 30):
        cube.location.x = float(frame) / 10
        cube.keyframe_insert(data_path='location', frame=frame)
    return action


def _ensure_world() -> None:
    if not bpy.data.worlds:
        bpy.data.worlds.new('World')
    if bpy.context.scene.world is None:
        bpy.context.scene.world = bpy.data.worlds[0]


def _build_extra_scene_with_nested_collection(shared: bpy.types.Object) -> None:
    """Create a second scene that links `shared` and exercises nested collections.

    Layout for the new scene 'Scene.002':
        master collection
          - 'Outer'
              - 'Inner'
                  - Empty 'NestedEmpty'
          - directly-linked 'shared' (object also in main scene)

    The shared object lets us assert it appears once per scene it's linked
    into. The nested empty lets us assert all_objects recurses.
    """
    extra = bpy.data.scenes.new('Scene.002')
    inner = bpy.data.collections.new('Inner')
    outer = bpy.data.collections.new('Outer')
    outer.children.link(inner)
    extra.collection.children.link(outer)

    nested_empty = bpy.data.objects.new('NestedEmpty', None)
    inner.objects.link(nested_empty)

    extra.collection.objects.link(shared)


def main() -> None:
    argv = sys.argv
    sep = argv.index('--') if '--' in argv else -1
    if sep < 0 or sep + 1 >= len(argv):
        raise SystemExit('build_fixture.py: missing output path after --')
    output = Path(argv[sep + 1]).resolve()

    _reset_scene()
    _ensure_world()

    cube = _build_cube()
    _build_armature()
    _build_light()
    _build_camera()
    _build_curve()
    _build_text()
    _build_action(cube)

    _build_extra_scene_with_nested_collection(cube)

    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()

    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    print(f'BUILD_FIXTURE_OK {output}')


if __name__ == '__main__':
    main()
