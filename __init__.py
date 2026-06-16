"""Viewport to Texture Baker — Blender extension entry point.

The implementation is split across modules by responsibility:

* :mod:`constants`     — bakeable channel definitions
* :mod:`paths`         — output path resolution
* :mod:`materials`     — temporary emission-node rewiring
* :mod:`images`        — image creation, packing, saving
* :mod:`render_state`  — Cycles/bake state guard
* :mod:`baker`         — bake orchestration shared by both run paths
* :mod:`bake_operator` — the operator (UI, props, sync + modal paths)

This module only wires the operator into the right-click menu.
"""
import bpy

from .bake_operator import OBJECT_OT_viewport_to_texture_baker


def _menu_func(self, context):
    if any(o.type == 'MESH' for o in context.selected_objects):
        self.layout.separator()
        self.layout.operator(
            OBJECT_OT_viewport_to_texture_baker.bl_idname,
            icon='RENDER_RESULT',
        )


def register():
    bpy.utils.register_class(OBJECT_OT_viewport_to_texture_baker)
    bpy.types.VIEW3D_MT_object_context_menu.append(_menu_func)


def unregister():
    bpy.types.VIEW3D_MT_object_context_menu.remove(_menu_func)
    bpy.utils.unregister_class(OBJECT_OT_viewport_to_texture_baker)
