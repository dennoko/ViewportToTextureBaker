"""Temporary material node rewiring for emission bakes."""
from __future__ import annotations

from typing import List

import bpy

from .constants import Color


def unique_materials(objects) -> List["bpy.types.Material"]:
    """Collect distinct materials across objects, preserving first-seen order."""
    seen, result = set(), []
    for obj in objects:
        for slot in obj.material_slots:
            mat = slot.material
            if mat and mat.name not in seen:
                seen.add(mat.name)
                result.append(mat)
    return result


class EmissionRewriter:
    """Rewires a material to emit a flat color, then restores it.

    The bake reads viewport values, so each material's Surface output is
    temporarily replaced with an Emission node feeding a constant color, plus an
    active Image Texture node that Cycles bakes into. Every change is captured in
    a returned state dict so :meth:`restore` can fully undo it.
    """

    def setup(self, mat, bake_img, color: Color) -> dict:
        """Rewire ``mat`` to emit ``color`` into ``bake_img``; return undo state."""
        if not mat.use_nodes:
            mat.use_nodes = True

        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        out_node = next(
            (n for n in nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output),
            None,
        )
        created_output = out_node is None
        if created_output:
            out_node = nodes.new('ShaderNodeOutputMaterial')
            out_node.is_active_output = True

        surface = out_node.inputs['Surface']
        orig_src = surface.links[0].from_socket if surface.links else None
        for lnk in list(surface.links):
            links.remove(lnk)

        emit_node = nodes.new('ShaderNodeEmission')
        emit_node.inputs['Color'].default_value = color
        emit_node.inputs['Strength'].default_value = 1.0
        links.new(emit_node.outputs['Emission'], surface)

        tex_node = nodes.new('ShaderNodeTexImage')
        tex_node.image = bake_img
        nodes.active = tex_node  # Cycles bakes into the active image node

        return {
            'emit': emit_node,
            'tex': tex_node,
            'out': out_node,
            'orig_src': orig_src,
            'created_output': created_output,
        }

    def restore(self, mat, state: dict) -> None:
        """Undo all changes recorded by :meth:`setup`."""
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        out = state['out']

        for lnk in list(out.inputs['Surface'].links):
            links.remove(lnk)
        if state['orig_src']:
            links.new(state['orig_src'], out.inputs['Surface'])
        if state['created_output']:
            nodes.remove(out)
        nodes.remove(state['emit'])
        nodes.remove(state['tex'])
