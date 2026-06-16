"""Output path resolution for baked textures."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import bpy

_ADDON_DIRNAME = "ViewportToTextureBaker"


def project_base_name() -> str:
    """Return the .blend file name without extension, or ``"untitled"``."""
    blend = bpy.path.basename(bpy.data.filepath)
    return os.path.splitext(blend)[0] if blend else "untitled"


def resolve_output_path(output_path: str) -> str:
    """Resolve the directory textures are written to.

    An explicit ``output_path`` wins; otherwise default to
    ``Documents/ViewportToTextureBaker/<project>/``.
    """
    if output_path:
        return bpy.path.abspath(output_path)
    docs = Path.home() / "Documents" / _ADDON_DIRNAME
    return str(docs / project_base_name())


def apply_suffix(filepath: str, suffix: str) -> str:
    """Insert ``suffix`` before the extension, e.g. ``foo.png`` + ``_1`` → ``foo_1.png``."""
    if not suffix:
        return filepath
    root, ext = os.path.splitext(filepath)
    return f"{root}{suffix}{ext}"


def resolve_unique_suffix(filepaths: Iterable[str]) -> str:
    """Find the smallest numeric suffix so none of ``filepaths`` collide on disk.

    The same suffix is applied to every path in a run so related outputs (e.g.
    BaseColor + MetallicRoughness) stay a matched, consistently numbered set.
    Returns ``""`` when the un-suffixed names are all free, otherwise ``"_N"``.
    """
    filepaths = list(filepaths)

    def all_free(suffix: str) -> bool:
        return not any(os.path.exists(apply_suffix(p, suffix)) for p in filepaths)

    if all_free(""):
        return ""
    n = 1
    while not all_free(f"_{n}"):
        n += 1
    return f"_{n}"
