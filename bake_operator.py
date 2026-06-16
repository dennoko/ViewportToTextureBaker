"""The ``Export Viewport to Textures`` operator (UI, props, and run paths)."""
from __future__ import annotations

import os
import traceback

import bpy

from .baker import (
    BakeSettings,
    BakeWatcher,
    ChannelBakePass,
    bake_all_sync,
    mesh_objects,
    remove_images,
    validate_meshes,
    write_results,
)
from .constants import CHANNELS
from .materials import EmissionRewriter, unique_materials
from .paths import project_base_name, resolve_output_path
from .render_state import RenderStateGuard

_CHANNEL_ITEMS = [
    ('R', "R (Red)", "Red channel"),
    ('G', "G (Green)", "Green channel"),
    ('B', "B (Blue)", "Blue channel"),
    ('A', "A (Alpha)", "Alpha channel"),
]


class OBJECT_OT_viewport_to_texture_baker(bpy.types.Operator):
    """Export viewport material properties (Color, Metallic, Roughness) to textures"""

    bl_idname = "object.viewport_to_texture_baker"
    bl_label = "Export Viewport to Textures"
    bl_options = {'REGISTER', 'UNDO'}

    # ── bpy.props ─────────────────────────────────────────────────────────────

    resolution: bpy.props.EnumProperty(
        name="Resolution",
        description="Output texture resolution",
        items=[
            ('512', "512", "512×512 pixels"),
            ('1024', "1024", "1024×1024 pixels"),
            ('2048', "2048", "2048×2048 pixels"),
            ('4096', "4096", "4096×4096 pixels"),
        ],
        default='2048',
    )

    margin: bpy.props.IntProperty(
        name="Margin (px)",
        description="Pixels to extend UV island edges outward (bleed/padding)",
        default=16,
        min=0,
        max=64,
    )

    output_path: bpy.props.StringProperty(
        name="Output Path",
        description="Directory where textures are saved",
        subtype='DIR_PATH',
        default="",
    )

    overwrite: bpy.props.BoolProperty(
        name="Overwrite Existing",
        description="Overwrite existing files instead of saving under a new "
                    "numbered name (_1, _2, ...)",
        default=False,
    )

    pack_textures: bpy.props.BoolProperty(
        name="Pack Metallic/Roughness",
        description="Pack Metallic and Roughness into a single combined texture",
        default=False,
    )

    metallic_channel: bpy.props.EnumProperty(
        name="Metallic →",
        description="Channel in the packed texture for Metallic values",
        items=_CHANNEL_ITEMS,
        default='B',
    )

    roughness_channel: bpy.props.EnumProperty(
        name="Roughness →",
        description="Channel in the packed texture for Roughness values",
        items=_CHANNEL_ITEMS,
        default='G',
    )

    # ── poll ──────────────────────────────────────────────────────────────────

    @classmethod
    def poll(cls, context):
        return (
            context.mode == 'OBJECT' and
            any(o.type == 'MESH' for o in context.selected_objects)
        )

    # ── settings ──────────────────────────────────────────────────────────────

    def _build_settings(self) -> BakeSettings:
        return BakeSettings(
            resolution=int(self.resolution),
            margin=self.margin,
            output_dir=resolve_output_path(self.output_path),
            base_name=project_base_name(),
            pack_textures=self.pack_textures,
            metallic_channel=self.metallic_channel,
            roughness_channel=self.roughness_channel,
            overwrite=self.overwrite,
        )

    def _validate(self, context) -> bool:
        err = validate_meshes(context.selected_objects)
        if err:
            self.report({'ERROR'}, err)
            return False
        return True

    # ── execute: sync path (called by Adjust Last Operation) ──────────────────

    def execute(self, context):
        if not self._validate(context):
            return {'CANCELLED'}

        settings = self._build_settings()
        os.makedirs(settings.output_dir, exist_ok=True)

        meshes = mesh_objects(context.selected_objects)
        materials = unique_materials(meshes)

        baked = {}
        with RenderStateGuard(context, settings.margin, active=meshes[-1]):
            try:
                baked = bake_all_sync(context, materials, settings)
                context.area.header_text_set("Viewport Baker: Saving textures...")
                write_results(baked, settings)
                self.report({'INFO'}, "Textures saved to: " + settings.output_dir)
            except Exception as exc:
                self.report({'ERROR'}, str(exc))
                print("[ViewportToTextureBaker]\n" + traceback.format_exc())
                return {'CANCELLED'}
            finally:
                remove_images(*baked.values())
                context.area.header_text_set(None)

        return {'FINISHED'}

    # ── invoke: async modal path (called from the right-click menu) ───────────

    def invoke(self, context, event):
        if not self.output_path:
            self.output_path = resolve_output_path(self.output_path)

        if not self._validate(context):
            return {'CANCELLED'}

        self._settings = self._build_settings()
        os.makedirs(self._settings.output_dir, exist_ok=True)

        meshes = mesh_objects(context.selected_objects)
        self._materials = unique_materials(meshes)
        self._rewriter = EmissionRewriter()
        self._watcher = BakeWatcher()
        self._guard = RenderStateGuard(context, self._settings.margin, active=meshes[-1])
        self._channel_idx = 0
        self._baked = {}
        self._pass = None
        self._state = 'INIT_CHANNEL'

        self._guard.apply()

        wm = context.window_manager
        wm.progress_begin(0, 100)
        self._timer = wm.event_timer_add(0.2, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    # ── modal state machine ───────────────────────────────────────────────────

    def modal(self, context, event):
        # Only act on our own timer ticks; pass everything else through so
        # Blender's native bake operator can still receive its own events.
        if event.type == 'TIMER' and event.timer == self._timer:
            return self._tick(context)
        return {'PASS_THROUGH'}

    def _tick(self, context):
        if self._state == 'INIT_CHANNEL':
            return self._tick_init_channel(context)
        if self._state == 'BAKE_WAITING':
            return self._tick_bake_waiting(context)
        if self._state == 'SAVE':
            return self._tick_save(context)
        return {'RUNNING_MODAL'}

    def _tick_init_channel(self, context):
        total = len(CHANNELS)
        if self._channel_idx >= total:
            self._state = 'SAVE'
            return {'RUNNING_MODAL'}

        channel = CHANNELS[self._channel_idx]
        context.window_manager.progress_update(int(self._channel_idx / total * 85))

        self._pass = ChannelBakePass(
            self._materials, channel, self._settings.resolution, self._rewriter
        )
        self._pass.prepare()

        self._watcher.start()
        # Clear our header so Cycles can display its own bake progress bar.
        context.area.header_text_set(None)
        try:
            bpy.ops.object.bake('INVOKE_DEFAULT', type='EMIT', use_clear=True)
        except Exception as exc:
            self._watcher.stop()
            self._pass.restore()
            self.report({'ERROR'}, str(exc))
            return self._do_cancel(context)

        self._state = 'BAKE_WAITING'
        return {'RUNNING_MODAL'}

    def _tick_bake_waiting(self, context):
        if self._watcher.failed:
            self._watcher.stop()
            self._pass.restore()
            self.report({'WARNING'}, "Bake was cancelled or failed")
            return self._do_cancel(context)

        if self._watcher.done:
            self._watcher.stop()
            self._pass.restore()
            self._baked[CHANNELS[self._channel_idx].name] = self._pass.image
            self._pass = None
            self._channel_idx += 1
            self._state = 'INIT_CHANNEL'

        return {'RUNNING_MODAL'}

    def _tick_save(self, context):
        context.window_manager.progress_update(92)
        context.area.header_text_set("Viewport Baker: Saving textures...")
        try:
            write_results(self._baked, self._settings)
            self.report({'INFO'}, "Textures saved to: " + self._settings.output_dir)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            print("[ViewportToTextureBaker]\n" + traceback.format_exc())
        return self._do_finish(context)

    # ── modal teardown ────────────────────────────────────────────────────────

    def _do_finish(self, context):
        self._teardown(context)
        return {'FINISHED'}

    def _do_cancel(self, context):
        self._teardown(context)
        return {'CANCELLED'}

    def _teardown(self, context):
        wm = context.window_manager
        if self._timer:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.progress_end()
        context.area.header_text_set(None)
        self._guard.restore()
        in_progress = self._pass.image if self._pass else None
        remove_images(*self._baked.values(), in_progress)
        self._baked = {}
        self._pass = None

    # ── draw: "Adjust Last Operation" panel UI ────────────────────────────────

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, 'resolution')
        layout.prop(self, 'margin')
        layout.prop(self, 'output_path')
        layout.prop(self, 'overwrite')
        layout.separator()
        layout.prop(self, 'pack_textures')
        if self.pack_textures:
            col = layout.column()
            col.label(text="Packed Texture Channel Assignment:")
            col.prop(self, 'metallic_channel')
            col.prop(self, 'roughness_channel')
