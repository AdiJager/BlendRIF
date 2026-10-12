# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Materials and MATCHIMG substitution.

Which PNG a bitmap resolves to is decided in textures.py (path first,
bare name only as a unique last resort). This module turns the resolved
path into a Blender material and guarantees one material per texture
path: the material name is derived from that path
(`Stat101_Common_Lights`, `Stat101_Envrnmts_Towers03_Lights`), so two
textures that share a file name under different directories never alias
onto the same material. If a name is ever already taken by a material
bound to a different texture, a short hash of the path is appended
instead of silently rebinding (see textures.disambiguate_name).

Every material produced by get_material carries the backface-culling
flag requested by the caller. AvP culls back-facing polygons like
every id-tech derivative, so designer geometry with inverted normals
(Lockdown4's VAULTLEVELS room copy, Colony signs) is invisible
in-game; enabling the same cull in Blender hides it in the viewport
too and stops Z-fighting on coincident surfaces. The option lives in
the operator's Materials section (default ON) and is threaded through
build_mesh -> get_material as `cull_backfaces`.

`TEX_PATH_PROP` records the texture's tree-relative path on every
material, so a material can be traced back to the file it came from
without guessing from its name.
"""

from __future__ import annotations

import os

import bpy

from .config import MAGENTA, MAT_ROUGHNESS, MAT_SPECULAR
from .utils import log
from .parsers.bitmaps import MatchImgRule
from .textures import (
    build_texture_index, resolve_texture, material_name, disambiguate_name,
)


# Custom property on materials: the tree-relative texture path.
TEX_PATH_PROP = "avp_tex_path"


# ---------------------------------------------------------------------------
# BSDF helpers
# ---------------------------------------------------------------------------

def _get_bsdf(mat):
    """Return the Principled BSDF node of a material, or None."""
    if not mat.use_nodes or not mat.node_tree:
        return None
    for n in mat.node_tree.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            return n
    return None


def _apply_material_defaults(bsdf):
    """Force our preferred roughness / specular values on a BSDF."""
    if bsdf is None:
        return
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = MAT_ROUGHNESS
    # Blender renamed "Specular" to "Specular IOR Level" in 4.0.
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = MAT_SPECULAR
    elif "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = MAT_SPECULAR


def _new_principled(mat, cull_backfaces: bool = True):
    """Clear a material's node tree and rebuild it with a fresh Principled BSDF."""
    mat.use_nodes = True
    # use_backface_culling exists on every Blender 3.0+ material and
    # controls Eevee viewport / render visibility of back-facing
    # polygons. When True, designer geometry with inverted normals
    # (Lockdown4's VAULTLEVELS room copy, Colony floor signs) is hidden
    # the same way AvP hides it. Cycles ignores this flag; users who
    # render with Cycles can add a Geometry > Backfacing mix node
    # manually.
    if hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = cull_backfaces
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    _apply_material_defaults(bsdf)
    return nodes, links, bsdf


def _current_image_path(mat) -> str | None:
    """Absolute filepath of the first image node on the material, or None."""
    if not mat.use_nodes or not mat.node_tree:
        return None
    for n in mat.node_tree.nodes:
        if n.type == 'TEX_IMAGE' and n.image:
            fp = n.image.filepath
            if fp:
                return bpy.path.abspath(fp)
    return None


def _mat_has_image_at(mat, png: str | None) -> bool:
    """True iff the material's current texture matches `png` (or None)."""
    if png is None:
        return _current_image_path(mat) is not None
    current = _current_image_path(mat)
    if current is None:
        return False
    return os.path.normcase(os.path.normpath(current)) == \
           os.path.normcase(os.path.normpath(bpy.path.abspath(png)))


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def get_material(name, png, cache, color=None,
                 raw_name: str = "", level_hint: str = "",
                 cull_backfaces: bool = True, tex_path: str = ""):
    """Return a cached material for (name, png, tex_path); create if needed.

    `name` is the display name derived from the texture path (see
    textures.material_name); `png` the resolved file; `tex_path` its
    tree-relative path, which is what the material is actually keyed
    and identified by.

    When `name` is already taken by a material bound to a *different*
    texture, the new material gets a hashed suffix instead of rebinding
    the existing one - which would flip every earlier user of that
    material to the wrong image.

    `cull_backfaces` mirrors the game engine's polygon culling: with
    True (default) every material produced here - new, reused or
    disambiguated - gets `use_backface_culling = True`.
    """
    # Cache key includes the resolved file so two shapes with the same
    # material name but different textures do not collide.
    key = (name, png, color)
    if key in cache:
        return cache[key]

    identity = tex_path or raw_name or (png or "")
    ex = bpy.data.materials.get(name)
    if ex is not None:
        ex_path = ex.get(TEX_PATH_PROP, "")
        same_texture = (ex_path == identity) if identity else True
        if hasattr(ex, "use_backface_culling"):
            ex.use_backface_culling = cull_backfaces
        if same_texture and (png is None or _mat_has_image_at(ex, png)):
            bsdf = _get_bsdf(ex)
            if bsdf is not None:
                _apply_material_defaults(bsdf)
            _set_tex_path(ex, identity)
            cache[key] = ex
            return ex
        # Name taken by a different texture: derive a unique name.
        new_name = disambiguate_name(name, identity or name)
        alt = bpy.data.materials.get(new_name)
        if alt is not None and _mat_has_image_at(alt, png):
            if hasattr(alt, "use_backface_culling"):
                alt.use_backface_culling = cull_backfaces
            bsdf = _get_bsdf(alt)
            if bsdf is not None:
                _apply_material_defaults(bsdf)
            cache[key] = alt
            return alt
        log.info(f"    [MAT] '{name}' -> '{new_name}' "
                 f"(name already bound to {ex_path or 'another texture'})")
        name = new_name

    m = bpy.data.materials.new(name)
    nodes, links, bsdf = _new_principled(m, cull_backfaces=cull_backfaces)
    if color:
        bsdf.inputs["Base Color"].default_value = color
    elif png and os.path.exists(png):
        try:
            img = bpy.data.images.load(png, check_existing=True)
            t = nodes.new("ShaderNodeTexImage")
            t.image = img
            t.extension = 'REPEAT'
            links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
        except (OSError, RuntimeError):
            bsdf.inputs["Base Color"].default_value = MAGENTA
    else:
        bsdf.inputs["Base Color"].default_value = MAGENTA
    _set_tex_path(m, identity)
    cache[key] = m
    return m


def _set_tex_path(mat, tex_path: str) -> None:
    """Record the source texture path on a material, when known."""
    if not tex_path:
        return
    try:
        mat[TEX_PATH_PROP] = tex_path
    except (TypeError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Compatibility shims
# ---------------------------------------------------------------------------

def build_tex_index(root: str):
    """Legacy 2-tuple view of textures.build_texture_index."""
    return build_texture_index(root)


def find_tex(tex_idx, name: str, raw_name: str = "",
             level_hint: str = "") -> str | None:
    """Legacy wrapper around textures.resolve_texture (path only, no stats)."""
    res = resolve_texture(tex_idx, name, raw_name, level_hint)
    return res.png


# ---------------------------------------------------------------------------
# MATCHIMG
# ---------------------------------------------------------------------------
#
# The engine builds an ImageDescriptor for every bitmap (filename + the
# RIM the bitmap belongs to) and replaces it with a rule's `load`
# descriptor when a rule's `insteadof` descriptor compares equal
# (BMPNAMES.CPP Matching_Images_Chunk::GetLoadImage, applied in
# CHNKTEXI.CPP / CHNKIMAG.CPP). The importer keeps a basename lookup and
# prefers the rule whose `rifname` matches the bitmap's own RIM, which is
# how the shipped rules are written.

def _basename_no_ext(path: str) -> str:
    """Basename of a path with the extension stripped."""
    return os.path.splitext(os.path.basename(path.replace('\\', '/')))[0]


def build_matchimg_index(rules: list[MatchImgRule]) -> dict[str, list]:
    """Map 'insteadof' basenames (lower case) to their rules.

    A list per name, because a name can carry several rules differing in
    the RIM they apply to; `apply_matchimg_index` picks between them.
    """
    idx: dict[str, list] = {}
    for r in rules:
        io_name = _basename_no_ext(r.insteadof.filename)
        load_name = r.load.filename
        if io_name and load_name:
            idx.setdefault(io_name.lower(), []).append(r)
    return idx


def _rule_matches_rim(rule, raw_name: str, name: str) -> int:
    """Score how well a rule's `insteadof` describes this bitmap (higher first).

    3 = its RIM name appears in the bitmap's path, 2 = the rule does not
    restrict the RIM, 1 = some other RIM (kept as a last resort so a
    substitution still happens when nothing better is on offer).
    """
    want = (rule.insteadof.rifname or "").replace('\\', '/').lower().strip('/')
    have = (raw_name or "").replace('\\', '/').lower()
    if not want:
        return 2
    if want in have:
        return 3
    if want == (name or "").lower():
        return 3
    return 1


def apply_matchimg_index(name: str | None, index: dict) -> str | None:
    """Substitute a bitmap name through the MATCHIMG rules.

    Returns the *basename* of the bitmap to load instead (the rule's
    `load` name), or `name` unchanged when no rule applies. Callers that
    need the exact file should use `apply_matchimg_rule`, which also
    returns the load descriptor's own path.
    """
    res = apply_matchimg_rule(name, "", index)
    return res[0] if res else name


def apply_matchimg_rule(name: str | None, raw_name: str, index: dict):
    """Resolve a bitmap through MATCHIMG; return (name, path) or None.

    `name` is the bitmap basename, `raw_name` its stored path (used to
    pick the rule whose RIM matches). The returned path is the `load`
    descriptor's filename, and the name its basename.
    """
    if not name or not index:
        return None
    rules = index.get(name.lower())
    if not rules:
        return None
    best = max(rules, key=lambda r: _rule_matches_rim(r, raw_name, name))
    load = best.load
    load_name = _basename_no_ext(load.filename)
    return (load_name or name), load.filename
