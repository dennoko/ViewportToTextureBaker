import bpy
import os
import numpy as np
from pathlib import Path


_CHANNELS = (
    ('BaseColor', True),
    ('Metallic',  False),
    ('Roughness', False),
)
_MAX_FILE_SUFFIX = 10000


# ─────────────────────────────────────────────────────────────────────────────
# Operator
# ─────────────────────────────────────────────────────────────────────────────

class OBJECT_OT_viewport_to_texture_baker(bpy.types.Operator):
    """Export viewport material properties (Color, Metallic, Roughness) to textures"""
    bl_idname = "object.viewport_to_texture_baker"
    bl_label = "Export Viewport to Textures"
    bl_options = {'UNDO'}

    # ── bpy.props ─────────────────────────────────────────────────────────────

    resolution: bpy.props.EnumProperty(
        name="Resolution",
        description="Output texture resolution",
        items=[
            ('512',  "512",  "512×512 pixels"),
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

    overwrite_existing: bpy.props.BoolProperty(
        name="Overwrite Existing",
        description="Overwrite files with the same name. Disable to save with numbered suffixes",
        default=True,
    )

    pack_textures: bpy.props.BoolProperty(
        name="Pack Metallic/Roughness",
        description="Pack Metallic and Roughness into a single combined texture",
        default=False,
    )

    metallic_channel: bpy.props.EnumProperty(
        name="Metallic →",
        description="Channel in the packed texture for Metallic values",
        items=[
            ('R', "R (Red)",   "Red channel"),
            ('G', "G (Green)", "Green channel"),
            ('B', "B (Blue)",  "Blue channel"),
            ('A', "A (Alpha)", "Alpha channel"),
        ],
        default='B',
    )

    roughness_channel: bpy.props.EnumProperty(
        name="Roughness →",
        description="Channel in the packed texture for Roughness values",
        items=[
            ('R', "R (Red)",   "Red channel"),
            ('G', "G (Green)", "Green channel"),
            ('B', "B (Blue)",  "Blue channel"),
            ('A', "A (Alpha)", "Alpha channel"),
        ],
        default='G',
    )

    # ── poll ──────────────────────────────────────────────────────────────────

    @classmethod
    def poll(cls, context):
        return (
            context.mode == 'OBJECT' and
            any(o.type == 'MESH' for o in context.selected_objects)
        )

    # ── path helpers ──────────────────────────────────────────────────────────

    def _resolved_output_path(self):
        if self.output_path:
            return bpy.path.abspath(self.output_path)
        docs = Path.home() / "Documents" / "ViewportToTextureBaker"
        blend = bpy.path.basename(bpy.data.filepath)
        proj  = os.path.splitext(blend)[0] if blend else "untitled"
        return str(docs / proj)

    def _base_name(self):
        blend = bpy.path.basename(bpy.data.filepath)
        return os.path.splitext(blend)[0] if blend else "untitled"

    # ── material node manipulation ────────────────────────────────────────────

    def _setup_material(self, mat, bake_img, channel):
        """Rewire mat to emit a flat viewport value. Returns undo state dict."""
        if not mat.use_nodes:
            mat.use_nodes = True

        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        if channel == 'BaseColor':
            col = (*mat.diffuse_color[:3], 1.0)
        elif channel == 'Metallic':
            v = mat.metallic
            col = (v, v, v, 1.0)
        else:  # Roughness
            v = mat.roughness
            col = (v, v, v, 1.0)

        out_node = next(
            (n for n in nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output),
            None,
        )
        created_output = out_node is None
        if created_output:
            out_node = nodes.new('ShaderNodeOutputMaterial')
            out_node.is_active_output = True

        orig_src = (
            out_node.inputs['Surface'].links[0].from_socket
            if out_node.inputs['Surface'].links
            else None
        )

        for lnk in list(out_node.inputs['Surface'].links):
            links.remove(lnk)

        emit_node = nodes.new('ShaderNodeEmission')
        emit_node.inputs['Color'].default_value = col
        emit_node.inputs['Strength'].default_value = 1.0
        links.new(emit_node.outputs['Emission'], out_node.inputs['Surface'])

        tex_node = nodes.new('ShaderNodeTexImage')
        tex_node.image = bake_img
        nodes.active = tex_node  # required for Cycles to target this image

        return {
            'emit': emit_node,
            'tex':  tex_node,
            'out':  out_node,
            'orig_src': orig_src,
            'created_output': created_output,
        }

    def _restore_material(self, mat, state):
        """Undo all changes made by _setup_material."""
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        out   = state['out']

        for lnk in list(out.inputs['Surface'].links):
            links.remove(lnk)
        if state['orig_src']:
            links.new(state['orig_src'], out.inputs['Surface'])
        if state['created_output']:
            nodes.remove(out)
        nodes.remove(state['emit'])
        nodes.remove(state['tex'])

    # ── shared bake helpers ───────────────────────────────────────────────────

    def _unique_materials(self, objects):
        seen, result = set(), []
        for obj in objects:
            for slot in obj.material_slots:
                if slot.material and slot.material.name not in seen:
                    seen.add(slot.material.name)
                    result.append(slot.material)
        return result

    def _new_bake_image(self, name, res, is_color):
        if name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[name])
        img = bpy.data.images.new(name, width=res, height=res, alpha=False)
        img.colorspace_settings.name = 'sRGB' if is_color else 'Non-Color'
        return img

    def _make_packed_image(self, metal_img, rough_img, res):
        """Build a packed texture with Metallic/Roughness in their configured channels."""
        ch   = {'R': 0, 'G': 1, 'B': 2, 'A': 3}
        m_ch = ch[self.metallic_channel]
        r_ch = ch[self.roughness_channel]

        m_px = np.array(metal_img.pixels[:]).reshape(-1, 4)
        r_px = np.array(rough_img.pixels[:]).reshape(-1, 4)
        out  = np.zeros((res * res, 4), dtype=np.float32)
        out[:, 3]    = 1.0
        out[:, m_ch] = m_px[:, 0]
        out[:, r_ch] = r_px[:, 0]

        img = self._new_bake_image("__vtb_packed__", res, False)
        img.pixels = out.flatten().tolist()
        return img

    def _save_png(self, img, filepath):
        img.filepath_raw = filepath
        img.file_format  = 'PNG'
        img.save()

    def _resolve_output_filepath(self, out_dir, filename):
        path = os.path.join(out_dir, filename)
        if self.overwrite_existing or not os.path.exists(path):
            return path
        stem, ext = os.path.splitext(filename)
        i = 1
        while i < _MAX_FILE_SUFFIX:
            candidate = os.path.join(out_dir, f"{stem}_{i:04d}{ext}")
            if not os.path.exists(candidate):
                return candidate
            i += 1
        raise RuntimeError(
            f"No available filename suffix in range 0001-{_MAX_FILE_SUFFIX - 1:04d} for: {filename}"
        )

    def _prepare_save_queue(self, baked, base, out_dir, res):
        queue = []
        if self.pack_textures:
            queue.append((
                "BaseColor",
                baked['BaseColor'],
                self._resolve_output_filepath(out_dir, f"{base}_BaseColor.png"),
                False,
            ))
            packed = self._make_packed_image(baked['Metallic'], baked['Roughness'], res)
            queue.append((
                "MetallicRoughness",
                packed,
                self._resolve_output_filepath(out_dir, f"{base}_MetallicRoughness.png"),
                True,
            ))
        else:
            for ch in ('BaseColor', 'Metallic', 'Roughness'):
                queue.append((
                    ch,
                    baked[ch],
                    self._resolve_output_filepath(out_dir, f"{base}_{ch}.png"),
                    False,
                ))
        return queue

    # ── bake completion handlers (modal path) ─────────────────────────────────

    def _on_bake_complete(self, *args):
        self._bake_done = True

    def _on_bake_error(self, *args):
        self._bake_failed = True

    def _register_bake_handlers(self):
        self._bake_done   = False
        self._bake_failed = False
        # Store bound-method references so we can remove the same objects later
        self._h_complete = self._on_bake_complete
        self._h_error    = self._on_bake_error
        bpy.app.handlers.object_bake_complete.append(self._h_complete)
        bpy.app.handlers.object_bake_cancel.append(self._h_error)

    def _deregister_bake_handlers(self):
        for lst, h in (
            (bpy.app.handlers.object_bake_complete, self._h_complete),
            (bpy.app.handlers.object_bake_cancel,   self._h_error),
        ):
            if h is not None and h in lst:
                lst.remove(h)
        self._h_complete = None
        self._h_error    = None

    # ── modal state machine ───────────────────────────────────────────────────

    def modal(self, context, event):
        # Only act on our own timer ticks; pass everything else through so
        # Blender's native bake operator can still receive its own events.
        if event.type == 'TIMER' and event.timer == self._timer:
            return self._tick(context)
        return {'PASS_THROUGH'}

    def _tick(self, context):
        wm    = context.window_manager
        total = len(_CHANNELS)

        # ── INIT_CHANNEL: set up nodes and start an async bake ────────────────
        if self._state == 'INIT_CHANNEL':
            idx = self._channel_idx
            if idx >= total:
                self._state = 'SAVE_PREP'
                return {'RUNNING_MODAL'}

            channel, is_color = _CHANNELS[idx]
            wm.progress_update(int(idx / total * 85))
            context.area.header_text_set(
                f"Viewport Baker: Preparing {channel} ({idx + 1}/{total})..."
            )

            img = self._new_bake_image(f"__vtb_{channel}__", self._res, is_color)
            self._current_img = img
            self._mat_states  = {
                mat.name: self._setup_material(mat, img, channel)
                for mat in self._materials
            }

            self._register_bake_handlers()
            # Clear our header so Cycles can display its own bake progress bar
            context.area.header_text_set(None)

            try:
                bpy.ops.object.bake('INVOKE_DEFAULT', type='EMIT', use_clear=True)
            except Exception as exc:
                self._deregister_bake_handlers()
                self._restore_mat_states()
                self.report({'ERROR'}, str(exc))
                return self._do_cancel(context)

            self._state = 'BAKE_WAITING'
            return {'RUNNING_MODAL'}

        # ── BAKE_WAITING: poll handler flags set by bake completion callbacks ─
        elif self._state == 'BAKE_WAITING':
            if self._bake_failed:
                self._deregister_bake_handlers()
                self._restore_mat_states()
                self.report({'WARNING'}, "Bake was cancelled or failed")
                return self._do_cancel(context)

            if self._bake_done:
                self._deregister_bake_handlers()
                self._restore_mat_states()
                channel = _CHANNELS[self._channel_idx][0]
                self._baked[channel] = self._current_img
                self._current_img    = None
                self._channel_idx   += 1
                self._state          = 'INIT_CHANNEL'

            return {'RUNNING_MODAL'}

        # ── SAVE_PREP: cache save targets then start incremental writes ───────
        elif self._state == 'SAVE_PREP':
            wm.progress_update(90)
            context.area.header_text_set("Viewport Baker: Preparing file output...")
            self._save_queue = self._prepare_save_queue(
                self._baked, self._base, self._out_dir, self._res
            )
            self._save_done = 0
            self._save_total = len(self._save_queue)
            self._state = 'SAVE_NEXT'
            return {'RUNNING_MODAL'}

        # ── SAVE_NEXT: write one file per timer tick for better responsiveness ─
        elif self._state == 'SAVE_NEXT':
            if not self._save_queue:
                if self._save_total > 0:
                    self.report({'INFO'}, "Textures saved to: " + self._out_dir)
                else:
                    self.report({'WARNING'}, "No textures were saved")
                return self._do_finish(context)

            name, img, path, remove_after_save = self._save_queue.pop(0)
            self._save_done += 1
            progress_ratio = self._save_done / self._save_total
            progress = 92 + int(progress_ratio * 8)
            wm.progress_update(min(100, progress))
            context.area.header_text_set(
                f"Viewport Baker: Saving {name} ({self._save_done}/{self._save_total})..."
            )
            try:
                self._save_png(img, path)
                # Cleanup temporary packed image created in _prepare_save_queue.
                if remove_after_save and img and img.name in bpy.data.images:
                    bpy.data.images.remove(img)
            except Exception as exc:
                import traceback
                self.report(
                    {'ERROR'},
                    f"Failed to save {name}: {exc}. Previously saved files remain in output directory."
                )
                print("[ViewportToTextureBaker]\n" + traceback.format_exc())
                return self._do_cancel(context)
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}

    def _restore_mat_states(self):
        for mat in self._materials:
            if mat.name in self._mat_states:
                self._restore_material(mat, self._mat_states[mat.name])
        self._mat_states = {}

    def _do_finish(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)
        self._timer = None
        wm.progress_end()
        context.area.header_text_set(None)
        self._restore_render_state(context)
        self._cleanup_baked()
        return {'FINISHED'}

    def _do_cancel(self, context):
        wm = context.window_manager
        if self._timer:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.progress_end()
        context.area.header_text_set(None)
        self._restore_render_state(context)
        self._cleanup_baked()
        return {'CANCELLED'}

    def _restore_render_state(self, context):
        scene = context.scene
        scene.render.engine           = self._orig_engine
        scene.render.bake.margin      = self._orig_margin
        scene.render.bake.margin_type = self._orig_margin_type
        context.view_layer.objects.active = self._orig_active

    def _cleanup_baked(self):
        for img in self._baked.values():
            if img and img.name in bpy.data.images:
                bpy.data.images.remove(img)
        if self._current_img and self._current_img.name in bpy.data.images:
            bpy.data.images.remove(self._current_img)
        self._baked       = {}
        self._current_img = None

    # ── invoke: show pre-execution settings dialog ─────────────────────────────

    def invoke(self, context, event):
        if not self.output_path:
            self.output_path = self._resolved_output_path()
        return context.window_manager.invoke_props_dialog(self, width=420)

    # ── execute: async modal path (called after dialog confirmation) ───────────

    def execute(self, context):
        mesh_objs = [o for o in context.selected_objects if o.type == 'MESH']
        if not mesh_objs:
            self.report({'ERROR'}, "No mesh objects selected")
            return {'CANCELLED'}

        missing_uv = [o.name for o in mesh_objs if not o.data.uv_layers]
        if missing_uv:
            self.report({'ERROR'}, "No UV map: " + ", ".join(missing_uv))
            return {'CANCELLED'}

        out_dir = self._resolved_output_path()
        os.makedirs(out_dir, exist_ok=True)

        # Modal instance state (not bpy.props, invisible to Adjust Last Operation)
        self._mesh_objs    = mesh_objs
        self._materials    = self._unique_materials(mesh_objs)
        self._out_dir      = out_dir
        self._base         = self._base_name()
        self._res          = int(self.resolution)
        self._channel_idx  = 0
        self._baked        = {}
        self._mat_states   = {}
        self._current_img  = None
        self._state        = 'INIT_CHANNEL'
        self._bake_done    = False
        self._bake_failed  = False
        self._h_complete   = None
        self._h_error      = None
        self._save_queue   = []
        self._save_done    = 0
        self._save_total   = 0

        # Save render state before overriding
        scene = context.scene
        self._orig_engine      = scene.render.engine
        self._orig_margin      = scene.render.bake.margin
        self._orig_margin_type = scene.render.bake.margin_type
        self._orig_active      = context.view_layer.objects.active

        scene.render.engine           = 'CYCLES'
        scene.render.bake.margin      = self.margin
        scene.render.bake.margin_type = 'EXTEND'
        context.view_layer.objects.active = mesh_objs[-1]

        wm = context.window_manager
        wm.progress_begin(0, 100)
        self._timer = wm.event_timer_add(0.2, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    # ── draw: pre-execution settings dialog UI ─────────────────────────────────

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, 'resolution')
        layout.prop(self, 'margin')
        layout.prop(self, 'output_path')
        layout.prop(self, 'overwrite_existing')
        layout.separator()
        layout.prop(self, 'pack_textures')
        if self.pack_textures:
            col = layout.column()
            col.label(text="Packed Texture Channel Assignment:")
            col.prop(self, 'metallic_channel')
            col.prop(self, 'roughness_channel')


# ─────────────────────────────────────────────────────────────────────────────
# Context-menu entry
# ─────────────────────────────────────────────────────────────────────────────

def _menu_func(self, context):
    if any(o.type == 'MESH' for o in context.selected_objects):
        self.layout.separator()
        self.layout.operator(
            OBJECT_OT_viewport_to_texture_baker.bl_idname,
            icon='RENDER_RESULT',
        )


# ─────────────────────────────────────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────────────────────────────────────

def register():
    bpy.utils.register_class(OBJECT_OT_viewport_to_texture_baker)
    bpy.types.VIEW3D_MT_object_context_menu.append(_menu_func)


def unregister():
    bpy.types.VIEW3D_MT_object_context_menu.remove(_menu_func)
    bpy.utils.unregister_class(OBJECT_OT_viewport_to_texture_baker)
