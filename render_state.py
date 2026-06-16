"""Scene render/bake state guard around a bake run."""
from __future__ import annotations


class RenderStateGuard:
    """Applies Cycles + bake settings and restores the originals afterward.

    Cycles is required for baking, so the engine and a couple of bake margin
    settings are overridden temporarily. Usable two ways:

    * as a context manager (``with guard:``) for the blocking sync path;
    * via :meth:`apply` / :meth:`restore` for the modal path, where the bake
      spans many operator ticks and a ``with`` block cannot wrap it.
    """

    def __init__(self, context, margin: int, active=None):
        self._context = context
        self._scene = context.scene
        self._margin = margin
        self._active = active if active is not None else context.view_layer.objects.active
        self._saved = None

    def apply(self) -> None:
        scene = self._scene
        self._saved = (
            scene.render.engine,
            scene.render.bake.margin,
            scene.render.bake.margin_type,
            self._context.view_layer.objects.active,
        )
        scene.render.engine = 'CYCLES'
        scene.render.bake.margin = self._margin
        scene.render.bake.margin_type = 'EXTEND'
        self._context.view_layer.objects.active = self._active

    def restore(self) -> None:
        if self._saved is None:
            return
        engine, margin, margin_type, active = self._saved
        scene = self._scene
        scene.render.engine = engine
        scene.render.bake.margin = margin
        scene.render.bake.margin_type = margin_type
        self._context.view_layer.objects.active = active
        self._saved = None

    def __enter__(self):
        self.apply()
        return self

    def __exit__(self, *exc):
        self.restore()
        return False
