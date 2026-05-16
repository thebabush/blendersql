"""M2.c domain verbs — typed SQL-function wrappers over the imperative bpy
operations agents reach for most. Registered after the escape-hatch scalars.

Each verb is a variadic scalar function returning a JSON envelope
`{ok, result, error}` (see `_common.envelope`); every invocation pushes to the
`session_log` audit ring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...engine import Engine


def register_verbs(engine: Engine) -> None:
    from ..registry import register_function
    from . import cleanup, files, gp, nodes, scene, vse

    verbs = {
        'add_object': scene.add_object,
        'add_modifier': scene.add_modifier,
        'add_constraint': scene.add_constraint,
        'set_keyframe': scene.set_keyframe,
        'ensure_fcurve': scene.ensure_fcurve,
        'add_node': nodes.add_node,
        'link_nodes': nodes.link_nodes,
        'build_node_tree': nodes.build_node_tree,
        'gp_add_layer': gp.gp_add_layer,
        'gp_add_frame': gp.gp_add_frame,
        'gp_add_stroke': gp.gp_add_stroke,
        'gp_resize_strokes': gp.gp_resize_strokes,
        'vse_add_sound': vse.vse_add_sound,
        'vse_add_movie': vse.vse_add_movie,
        'vse_add_scene_strip': vse.vse_add_scene_strip,
        'vse_add_text': vse.vse_add_text,
        'vse_add_color': vse.vse_add_color,
        'save': files.save,
        'load': files.load,
        'render': files.render,
        'render_object': files.render_object,
        'import_file': files.import_file,
        'export_file': files.export_file,
        'purge_orphans': cleanup.purge_orphans,
        'remove_unused_material_slots': cleanup.remove_unused_material_slots,
    }
    for name, fn in verbs.items():
        engine.conn.createscalarfunction(name, fn, -1, deterministic=False)
        # Every verb is decorated with @function_meta, so _bsql_meta is
        # guaranteed present. Defensive AttributeError surfaces the missing
        # decorator clearly if a future verb is added without one.
        meta = getattr(fn, '_bsql_meta', None)
        if meta is None:
            raise RuntimeError(f"verb '{name}' is missing @function_meta")
        register_function(meta)
