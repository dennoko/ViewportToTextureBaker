"""Core bake orchestration shared by the sync and modal operator paths."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import bpy

from . import images, paths
from .constants import CHANNELS, ChannelSpec
from .materials import EmissionRewriter


@dataclass
class BakeSettings:
    """Resolved, context-free parameters for a single bake run."""

    resolution: int
    margin: int
    output_dir: str
    base_name: str
    pack_textures: bool
    metallic_channel: str
    roughness_channel: str
    overwrite: bool


def mesh_objects(objects) -> List["bpy.types.Object"]:
    """Return only the mesh objects from a selection."""
    return [o for o in objects if o.type == 'MESH']


def validate_meshes(objects) -> Optional[str]:
    """Return an error message if the selection can't be baked, else ``None``."""
    meshes = mesh_objects(objects)
    if not meshes:
        return "No mesh objects selected"
    missing_uv = [o.name for o in meshes if not o.data.uv_layers]
    if missing_uv:
        return "No UV map: " + ", ".join(missing_uv)
    return None


def remove_images(*imgs) -> None:
    """Remove any still-existing images from ``bpy.data`` (None-safe)."""
    for img in imgs:
        if img and img.name in bpy.data.images:
            bpy.data.images.remove(img)


class ChannelBakePass:
    """Prepares and tears down one channel's bake (image + material rewiring).

    Splitting ``prepare`` from the actual bake call lets the sync path run a
    blocking bake and the modal path run an async (``INVOKE_DEFAULT``) bake while
    sharing identical setup/teardown.
    """

    def __init__(self, materials, channel: ChannelSpec, res: int,
                 rewriter: EmissionRewriter):
        self._materials = materials
        self._channel = channel
        self._res = res
        self._rewriter = rewriter
        self._states: Dict[str, dict] = {}
        self.image = None

    def prepare(self):
        """Create the bake image and rewire every material to emit this channel."""
        self.image = images.new_bake_image(
            f"__vtb_{self._channel.name}__", self._res, self._channel.is_color
        )
        self._states = {
            mat.name: self._rewriter.setup(mat, self.image, self._channel.extract(mat))
            for mat in self._materials
        }
        return self.image

    def restore(self):
        """Restore every material rewired by :meth:`prepare`."""
        for mat in self._materials:
            state = self._states.get(mat.name)
            if state is not None:
                self._rewriter.restore(mat, state)
        self._states = {}


class BakeWatcher:
    """Tracks async bake completion via Blender's bake handlers.

    The modal path can't block on ``bpy.ops.object.bake``, so it watches the
    ``object_bake_complete`` / ``object_bake_cancel`` handlers for the result.
    """

    def __init__(self):
        self.done = False
        self.failed = False
        self._h_complete = None
        self._h_error = None

    def start(self) -> None:
        self.done = False
        self.failed = False
        # Keep bound-method references so the exact same objects can be removed.
        self._h_complete = self._on_complete
        self._h_error = self._on_error
        bpy.app.handlers.object_bake_complete.append(self._h_complete)
        bpy.app.handlers.object_bake_cancel.append(self._h_error)

    def stop(self) -> None:
        for lst, handler in (
            (bpy.app.handlers.object_bake_complete, self._h_complete),
            (bpy.app.handlers.object_bake_cancel, self._h_error),
        ):
            if handler is not None and handler in lst:
                lst.remove(handler)
        self._h_complete = None
        self._h_error = None

    def _on_complete(self, *args):
        self.done = True

    def _on_error(self, *args):
        self.failed = True


def bake_all_sync(context, materials, settings: BakeSettings,
                  ) -> Dict[str, "bpy.types.Image"]:
    """Run a blocking bake for every channel and return the baked images.

    On failure, any images already baked are cleaned up before re-raising so the
    caller never leaks orphaned datablocks.
    """
    baked: Dict[str, "bpy.types.Image"] = {}
    rewriter = EmissionRewriter()
    total = len(CHANNELS)
    try:
        for i, channel in enumerate(CHANNELS):
            context.area.header_text_set(
                f"Viewport Baker: Baking {channel.name} ({i + 1}/{total})..."
            )
            bake_pass = ChannelBakePass(materials, channel, settings.resolution, rewriter)
            bake_pass.prepare()
            try:
                bpy.ops.object.bake(type='EMIT', use_clear=True)
            finally:
                bake_pass.restore()
            baked[channel.name] = bake_pass.image
    except Exception:
        remove_images(*baked.values())
        raise
    return baked


def _result_targets(settings: BakeSettings) -> Dict[str, str]:
    """Map each output key to its destination file path (before collision check)."""
    out_dir = settings.output_dir
    base = settings.base_name
    if settings.pack_textures:
        return {
            "BaseColor": os.path.join(out_dir, f"{base}_BaseColor.png"),
            "_packed": os.path.join(out_dir, f"{base}_MetallicRoughness.png"),
        }
    return {
        channel.name: os.path.join(out_dir, f"{base}_{channel.name}.png")
        for channel in CHANNELS
    }


def write_results(baked: Dict[str, "bpy.types.Image"], settings: BakeSettings) -> None:
    """Save baked images to disk per the pack/individual setting.

    Unless ``overwrite`` is set, a shared numeric suffix (``_1``, ``_2``, ...) is
    appended to every file in the run when any of them would clash with an
    existing file, so nothing is silently overwritten.
    """
    targets = _result_targets(settings)
    if not settings.overwrite:
        suffix = paths.resolve_unique_suffix(targets.values())
        targets = {key: paths.apply_suffix(path, suffix) for key, path in targets.items()}

    if settings.pack_textures:
        images.save_png(baked["BaseColor"], targets["BaseColor"])
        packed = images.pack_metallic_roughness(
            baked["Metallic"], baked["Roughness"], settings.resolution,
            settings.metallic_channel, settings.roughness_channel,
        )
        try:
            images.save_png(packed, targets["_packed"])
        finally:
            remove_images(packed)
    else:
        for channel in CHANNELS:
            images.save_png(baked[channel.name], targets[channel.name])
