"""Bakeable viewport channel definitions.

Each channel is described declaratively so adding a new one is just a matter of
appending to ``CHANNELS`` — no branching logic elsewhere (Open/Closed).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Tuple

# RGBA color tuple emitted during a bake.
Color = Tuple[float, float, float, float]


@dataclass(frozen=True)
class ChannelSpec:
    """Describes one bakeable viewport channel.

    Attributes:
        name:     suffix used in image and file names (e.g. ``"BaseColor"``).
        is_color: ``True`` for sRGB color data, ``False`` for non-color data.
        extract:  maps a material to the flat RGBA value to emit for this channel.
    """

    name: str
    is_color: bool
    extract: Callable[["bpy.types.Material"], Color]


def _base_color(mat) -> Color:
    return (*mat.diffuse_color[:3], 1.0)


def _metallic(mat) -> Color:
    v = mat.metallic
    return (v, v, v, 1.0)


def _roughness(mat) -> Color:
    v = mat.roughness
    return (v, v, v, 1.0)


CHANNELS: Tuple[ChannelSpec, ...] = (
    ChannelSpec("BaseColor", True, _base_color),
    ChannelSpec("Metallic", False, _metallic),
    ChannelSpec("Roughness", False, _roughness),
)
