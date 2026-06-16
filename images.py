"""Bake image creation, channel packing, and saving.

Pixel reads/writes use ``foreach_get`` / ``foreach_set`` with NumPy buffers.
These transfer raw float data in one C-level call, whereas slicing
(``img.pixels[:]``) or assigning a Python list materializes tens of millions of
Python floats — orders of magnitude slower at 2K/4K resolutions.
"""
from __future__ import annotations

import bpy
import numpy as np

_CHANNEL_INDEX = {'R': 0, 'G': 1, 'B': 2, 'A': 3}


def new_bake_image(name: str, res: int, is_color: bool):
    """Create (replacing any existing image of the same name) a square bake image."""
    if name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[name])
    img = bpy.data.images.new(name, width=res, height=res, alpha=False)
    img.colorspace_settings.name = 'sRGB' if is_color else 'Non-Color'
    return img


def _read_pixels(img) -> np.ndarray:
    """Fast bulk read of an image's RGBA pixels as an ``(N, 4)`` float array."""
    buf = np.empty(len(img.pixels), dtype=np.float32)
    img.pixels.foreach_get(buf)
    return buf.reshape(-1, 4)


def _write_pixels(img, pixels: np.ndarray) -> None:
    """Fast bulk write of an ``(N, 4)`` (or flat) array into an image."""
    img.pixels.foreach_set(np.ascontiguousarray(pixels, dtype=np.float32).ravel())


def pack_metallic_roughness(metal_img, rough_img, res: int,
                            metallic_channel: str, roughness_channel: str):
    """Combine Metallic and Roughness greyscale bakes into one packed image.

    Each source value is read from its red channel and written into the
    configured destination channel; unused channels stay 0 and alpha is 1.
    """
    m_ch = _CHANNEL_INDEX[metallic_channel]
    r_ch = _CHANNEL_INDEX[roughness_channel]

    m_px = _read_pixels(metal_img)
    r_px = _read_pixels(rough_img)

    out = np.zeros((res * res, 4), dtype=np.float32)
    out[:, 3] = 1.0
    out[:, m_ch] = m_px[:, 0]
    out[:, r_ch] = r_px[:, 0]

    img = new_bake_image("__vtb_packed__", res, is_color=False)
    _write_pixels(img, out)
    return img


def save_png(img, filepath: str) -> None:
    """Write ``img`` to ``filepath`` as a PNG."""
    img.filepath_raw = filepath
    img.file_format = 'PNG'
    img.save()
