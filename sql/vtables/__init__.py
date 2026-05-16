"""Virtual tables. register_all() wires them into an Engine on init."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._meta import VTableMeta

if TYPE_CHECKING:
    from ..engine import Engine


# Live registry of {table_name: vtable_instance} populated by `_bind()` on every
# `register_all()`. Read by introspection vtables like `bsql_tables`. The
# in-process Engine is single-tenant, so a module-level dict is safe; cleared
# on every fresh registration to avoid leftover entries.
_REGISTRY: dict[str, VTableMeta] = {}

# Monotonic counter bumped on every `_bind` call. Lets introspection vtables
# (bsql_tables / bsql_columns) cache their snapshots and invalidate cheaply —
# the registry only changes when `register_all` re-runs, so the counter is
# stable for the lifetime of a session.
_REGISTRY_VERSION = 0


def registry() -> dict[str, VTableMeta]:
    """Return the {table_name: vtable_instance} registry. Read-only by convention."""
    return _REGISTRY


def registry_version() -> int:
    """Monotonic version; bumped every time `_bind` mutates the registry."""
    return _REGISTRY_VERSION


def register_all(engine: Engine) -> None:
    from . import (
        actions,
        animation,
        armatures,
        assets,
        bsql,
        cameras,
        collections,
        constraints,
        curves,
        custom_properties,
        gp_frames,
        grease_pencils,
        grep,
        lights,
        material_gp_settings,
        materials,
        meshes,
        misc,
        modifiers,
        node_trees,
        objects,
        scenes,
        session_log,
        shape_keys,
        vertex_groups,
        vse,
        welcome,
    )

    _REGISTRY.clear()
    _bind(engine, 'welcome', welcome.Welcome())
    _bind(engine, 'objects', objects.Objects())
    _bind(engine, 'scenes', scenes.Scenes())
    _bind(engine, 'scene_objects', scenes.SceneObjects())
    _bind(engine, 'collections', collections.Collections())
    _bind(engine, 'collection_objects', collections.CollectionObjects())
    _bind(engine, 'materials', materials.Materials())
    _bind(engine, 'material_slots', materials.MaterialSlots())
    _bind(engine, 'modifiers', modifiers.Modifiers())
    _bind(engine, 'constraints', constraints.Constraints())
    _bind(engine, 'custom_properties', custom_properties.CustomProperties())
    _bind(engine, 'grease_pencils', grease_pencils.GreasePencils())
    _bind(engine, 'gp_layer_groups', grease_pencils.GpLayerGroups())
    _bind(engine, 'gp_layers', grease_pencils.GpLayers())
    _bind(engine, 'gp_frames', gp_frames.GpFrames())
    _bind(engine, 'gp_strokes', gp_frames.GpStrokes())
    _bind(engine, 'gp_points', gp_frames.GpPoints())
    _bind(engine, 'gp_drawing_attributes', gp_frames.GpDrawingAttributes())
    _bind(engine, 'actions', actions.Actions())
    _bind(engine, 'action_slots', actions.ActionSlots())
    _bind(engine, 'action_layers', actions.ActionLayers())
    _bind(engine, 'action_strips', actions.ActionStrips())
    _bind(engine, 'action_channelbags', actions.ActionChannelbags())
    _bind(engine, 'fcurves', actions.FCurves())
    _bind(engine, 'keyframes', actions.Keyframes())
    _bind(engine, 'animation_data', animation.AnimationData())
    _bind(engine, 'drivers', animation.Drivers())
    _bind(engine, 'driver_variables', animation.DriverVariables())
    _bind(engine, 'driver_targets', animation.DriverTargets())
    _bind(engine, 'node_trees', node_trees.NodeTrees())
    _bind(engine, 'nodes', node_trees.Nodes())
    _bind(engine, 'node_inputs', node_trees.NodeInputs())
    _bind(engine, 'node_outputs', node_trees.NodeOutputs())
    _bind(engine, 'node_links', node_trees.NodeLinks())
    _bind(engine, 'node_tree_interface', node_trees.NodeTreeInterface())
    _bind(engine, 'material_gp_settings', material_gp_settings.MaterialGpSettings())
    _bind(engine, 'meshes', meshes.Meshes())
    _bind(engine, 'mesh_attributes', meshes.MeshAttributes())
    _bind(engine, 'mesh_vertices', meshes.MeshVertices())
    _bind(engine, 'mesh_edges', meshes.MeshEdges())
    _bind(engine, 'mesh_polygons', meshes.MeshPolygons())
    _bind(engine, 'mesh_loops', meshes.MeshLoops())
    _bind(engine, 'mesh_uvs', meshes.MeshUvs())
    _bind(engine, 'armatures', armatures.Armatures())
    _bind(engine, 'bones', armatures.Bones())
    _bind(engine, 'pose_bones', armatures.PoseBones())
    _bind(engine, 'curves', curves.Curves())
    _bind(engine, 'curve_splines', curves.CurveSplines())
    _bind(engine, 'curve_points', curves.CurvePoints())
    _bind(engine, 'texts', curves.Texts())
    _bind(engine, 'lights', lights.Lights())
    _bind(engine, 'cameras', cameras.Cameras())
    _bind(engine, 'shape_keys', shape_keys.ShapeKeys())
    _bind(engine, 'shape_key_blocks', shape_keys.ShapeKeyBlocks())
    _bind(engine, 'vertex_groups', vertex_groups.VertexGroups())
    _bind(engine, 'vse_strips', vse.VseStrips())
    _bind(engine, 'vse_strip_sound', vse.VseStripSound())
    _bind(engine, 'vse_strip_movie', vse.VseStripMovie())
    _bind(engine, 'vse_strip_image', vse.VseStripImage())
    _bind(engine, 'vse_strip_scene', vse.VseStripScene())
    _bind(engine, 'vse_strip_text', vse.VseStripText())
    _bind(engine, 'vse_strip_color', vse.VseStripColor())
    _bind(engine, 'images', assets.Images())
    _bind(engine, 'sounds', assets.Sounds())
    _bind(engine, 'movieclips', assets.MovieClips())
    _bind(engine, 'cache_files', assets.CacheFiles())
    _bind(engine, 'fonts', assets.Fonts())
    _bind(engine, 'palettes', misc.Palettes())
    _bind(engine, 'palette_colors', misc.PaletteColors())
    _bind(engine, 'linestyles', misc.LineStyles())
    _bind(engine, 'worlds', misc.Worlds())
    _bind(engine, 'brushes', misc.Brushes())
    _bind(engine, 'masks', misc.Masks())
    _bind(engine, 'annotations', misc.Annotations())
    _bind(engine, 'grep', grep.Grep())
    _bind(engine, 'session_log', session_log.SessionLog())
    _bind(engine, 'bsql_tables', bsql.BsqlTables())
    _bind(engine, 'bsql_columns', bsql.BsqlColumns())
    _bind(engine, 'bsql_related', bsql.BsqlRelated())

    engine.conn.createscalarfunction('grep', _grep_scalar, -1, deterministic=False)


def _bind(engine: Engine, table_name: str, source: VTableMeta) -> None:
    module_name = f'blendersql_vt_{table_name}'
    # Vtable sources implement apsw's duck-typed module protocol, not its
    # nominal VTModule type.
    engine.conn.createmodule(module_name, source)  # type: ignore[arg-type]
    engine.conn.execute(f'CREATE VIRTUAL TABLE {table_name} USING {module_name}')
    _REGISTRY[table_name] = source
    global _REGISTRY_VERSION
    _REGISTRY_VERSION += 1


def _grep_scalar(*args: object) -> str:
    from . import grep

    if not args:
        return '[]'
    pattern = args[0]
    if not isinstance(pattern, str):
        return '[]'
    limit = args[1] if len(args) > 1 else None
    offset = args[2] if len(args) > 2 else None
    return grep.grep_json(pattern, limit, offset)  # type: ignore[arg-type]
