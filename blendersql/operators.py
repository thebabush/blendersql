from __future__ import annotations

import bpy

from . import preferences, server


class BLENDERSQL_OT_start_server(bpy.types.Operator):
    bl_idname = 'blendersql.start_server'
    bl_label = 'Start BlenderSQL Server'
    bl_description = 'Start the BlenderSQL HTTP server'
    bl_options = {'INTERNAL'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        prefs = preferences.get()
        try:
            server.start(prefs.bind, prefs.port)
        except Exception as e:
            self.report({'ERROR'}, f'Failed to start: {e}')
            return {'CANCELLED'}
        self.report({'INFO'}, f'BlenderSQL listening on http://{prefs.bind}:{prefs.port}')
        return {'FINISHED'}


class BLENDERSQL_OT_stop_server(bpy.types.Operator):
    bl_idname = 'blendersql.stop_server'
    bl_label = 'Stop BlenderSQL Server'
    bl_description = 'Stop the BlenderSQL HTTP server'
    bl_options = {'INTERNAL'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        server.stop()
        self.report({'INFO'}, 'BlenderSQL stopped')
        return {'FINISHED'}


CLASSES: tuple[type[bpy.types.Operator], ...] = (
    BLENDERSQL_OT_start_server,
    BLENDERSQL_OT_stop_server,
)


def register() -> None:
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister() -> None:
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
