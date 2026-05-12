from __future__ import annotations

import bpy


class BlenderSQLPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    # bpy's property idiom puts a callable in annotation position; mypy can't
    # model this and bpy is untyped here anyway.
    bind: bpy.props.StringProperty(  # type: ignore[valid-type]
        name='Bind address',
        default='127.0.0.1',
        description='Address the HTTP server binds to. Use 127.0.0.1 unless you know what you are doing.',
    )
    port: bpy.props.IntProperty(  # type: ignore[valid-type]
        name='Port',
        default=8174,
        min=1024,
        max=65535,
    )
    autostart: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name='Start server on load',
        default=True,
        description='Start the HTTP server automatically when the add-on is enabled / Blender starts.',
    )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self, 'bind')
        col.prop(self, 'port')
        col.prop(self, 'autostart')
        layout.separator()
        row = layout.row(align=True)
        row.operator('blendersql.start_server', icon='PLAY')
        row.operator('blendersql.stop_server', icon='SNAP_FACE')


def get() -> BlenderSQLPreferences:
    return bpy.context.preferences.addons[__package__].preferences


def register() -> None:
    bpy.utils.register_class(BlenderSQLPreferences)


def unregister() -> None:
    bpy.utils.unregister_class(BlenderSQLPreferences)
