# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Materials, textures and MATCHIMG substitution.

Texture lookup tries, in order: (1) the original game path from
BitmapEntry.raw_name, (2) the RIF level name as a subdirectory hint,
(3) the first PNG whose basename matches. build_tex_index caches its
walk per (root, mtime) so repeated imports do not re-scan a directory
that may hold thousands of PNGs.

Basename collisions are handled in two places:
  * build_tex_index inserts every PNG under both its full relative
    path (graphics/envrnmts/towers03/lights) and its stripped form
    (envrnmts/towers03/lights). The retail _ffl_unpacked layout
    starts at graphics/ but RIF raw_names never carry that prefix, so
    without the stripped key the normalized lookup always misses and
    every lookup falls back to by_base - where basename collisions
    silently resolve to the alphabetically-first file
    (Common/Lights.png would beat Envrnmts/Towers03/Lights.png).
  * get_material creates a disambiguated material (Stat101_Common_Lights)
    when a name collision would otherwise rebind a shared material to a
    different texture. Material names derive from the bitmap basename
    only ("Stat101_Lights"), so two distinct textures under different
    paths (Common/Lights vs Towers03/Lights) would otherwise alias to
    one material and the last write would win.

Every material produced by get_material carries the backface-culling
flag requested by the caller. AvP culls back-facing polygons like
every id-tech derivative, so designer geometry with inverted normals
(Lockdown4's VAULTLEVELS room copy, Colony signs) is invisible
in-game; enabling the same cull in Blender hides it in the viewport
too and stops Z-fighting on coincident surfaces. The option lives in
the operator's Materials section (default ON) and is threaded through
build_mesh -> get_material as `cull_backfaces`.
"""

from __future__ import annotations

import os

import bpy

from .config import MAGENTA, MAT_ROUGHNESS, MAT_SPECULAR
from .utils import log
from .parsers.bitmaps import MatchImgRule


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


def _parent_dir_name(png: str | None) -> str:
    """Immediate parent dir name of a PNG path, without leading/trailing slashes."""
    if not png:
        return ""
    parent = os.path.basename(os.path.dirname(png.replace('\\', '/')))
    return parent or ""


def _set_tex(mat, png: str) -> None:
    """Replace the material's image node with a fresh one for `png`."""
    # Kept for callers that explicitly want to mutate an existing
    # material (e.g. a future "force reimport this material" feature).
    # The normal import path does NOT use this to swap a shared
    # material's texture - see get_material for the collision handling
    # that replaced it.
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for n in list(nodes):
        if n.type == 'TEX_IMAGE':
            nodes.remove(n)
    bsdf = _get_bsdf(mat)
    if bsdf is None:
        nodes, links, bsdf = _new_principled(mat)
    else:
        _apply_material_defaults(bsdf)
    try:
        img = bpy.data.images.load(png, check_existing=True)
        t = nodes.new("ShaderNodeTexImage")
        t.image = img
        t.extension = 'REPEAT'
        links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    except (OSError, RuntimeError) as e:
        log.warning(f"    Failed to load {png}: {e}")
        bsdf.inputs["Base Color"].default_value = MAGENTA


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def get_material(name, png, cache, color=None,
                 raw_name: str = "", level_hint: str = "",
                 cull_backfaces: bool = True):
    """Return a cached material for (name, png, color), creating one if needed.

    `cull_backfaces` mirrors the game engine's polygon culling. When
    True (default), every material produced here - new, reused, or
    disambiguated - gets `use_backface_culling = True`. Set False to
    keep Blender's default two-sided rendering, which shows the
    designer/helper geometry the game hides.

    A material name is derived from the bitmap basename only
    ("Stat101_Lights"), so two distinct textures with the same
    basename under different directories (Common/Lights.png vs
    Envrnmts/Towers03/Lights.png) produce the same name. When that
    name exists but with a DIFFERENT texture bound, a disambiguated
    material carrying the texture's parent directory
    (Stat101_Common_Lights) is created instead of silently rebinding -
    which would flip every existing user of Stat101_Lights to the
    wrong texture.
    """
    # Cache key includes png so two shapes with the same material name
    # but different textures do not collide.
    key = (name, png, color)
    if key in cache:
        return cache[key]

    ex = bpy.data.materials.get(name)
    if ex is not None:
        # Refresh the culling flag even on reused materials - a later
        # import with a different setting must not inherit stale state.
        if hasattr(ex, "use_backface_culling"):
            ex.use_backface_culling = cull_backfaces
        if png is not None and not _mat_has_image_at(ex, png):
            # Texture mismatch under the same basename - disambiguate.
            parent = _parent_dir_name(png)
            new_name = f"{name}_{parent}" if parent else f"{name}_alt"
            # The disambiguated name may already exist from a previous
            # import in the same session; keep bumping until we find
            # either a free slot or an existing material that already
            # has exactly the texture we want.
            alt = bpy.data.materials.get(new_name)
            guard = 0
            while alt is not None and not _mat_has_image_at(alt, png) \
                    and guard < 32:
                new_name = f"{new_name}_x"
                alt = bpy.data.materials.get(new_name)
                guard += 1
            if alt is not None:
                # Reuse the disambiguated material.
                if hasattr(alt, "use_backface_culling"):
                    alt.use_backface_culling = cull_backfaces
                bsdf = _get_bsdf(alt)
                if bsdf is not None:
                    _apply_material_defaults(bsdf)
                cache[key] = alt
                return alt
            # Fall through to creation with the disambiguated name.
            log.info(f"    [MAT] '{name}' -> '{new_name}' "
                     f"(basename collision, keeping both textures)")
            name = new_name
        else:
            bsdf = _get_bsdf(ex)
            if bsdf is not None:
                _apply_material_defaults(bsdf)
            cache[key] = ex
            return ex

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
    cache[key] = m
    return m


# ---------------------------------------------------------------------------
# Texture index (cached per (root, mtime))
# ---------------------------------------------------------------------------

# Keyed by (absolute root, mtime); invalidates when the directory changes.
_TEX_INDEX_CACHE: dict[tuple[str, float], tuple[dict, dict]] = {}


def build_tex_index(root: str):
    """Return ({relative path: full}, {basename: full}) for PNGs under root."""
    if not os.path.isdir(root):
        return {}, {}

    try:
        mtime = os.path.getmtime(root)
    except OSError:
        mtime = 0.0

    cache_key = (os.path.abspath(root), mtime)
    hit = _TEX_INDEX_CACHE.get(cache_key)
    if hit is not None:
        return hit

    by_rel: dict[str, str] = {}
    by_base: dict[str, str] = {}
    for r, _, fs in os.walk(root):
        for f in fs:
            if not f.lower().endswith('.png'):
                continue
            full = os.path.join(r, f)
            rel = os.path.relpath(full, root).replace(os.sep, '/').lower()
            rel_noext = os.path.splitext(rel)[0]
            # Insert both keys. The retail _ffl_unpacked layout starts
            # at graphics/, but RIF raw_names never carry that prefix,
            # so _normalize_raw strips it - by_rel lookups would
            # otherwise always miss and fall through to by_base, where
            # basename collisions silently pick the wrong file.
            by_rel[rel_noext] = full
            if rel_noext.startswith('graphics/'):
                by_rel[rel_noext[len('graphics/'):]] = full
            base = os.path.splitext(f)[0].lower()
            if base not in by_base:
                by_base[base] = full

    _TEX_INDEX_CACHE[cache_key] = (by_rel, by_base)
    return by_rel, by_base


def _normalize_raw(raw_name: str) -> str:
    """Normalise a game path to a relative-path key for by_rel."""
    if not raw_name:
        return ""
    p = raw_name.replace('\\', '/').lower()
    p = os.path.splitext(p)[0]
    for pref in ("textures/", "texture/", "art/", "artwork/"):
        if p.startswith(pref):
            p = p[len(pref):]
    return p.lstrip('/')


def find_tex(tex_idx, name: str, raw_name: str = "",
             level_hint: str = "") -> str | None:
    """Resolve a bitmap basename to a PNG path (raw -> level -> basename)."""
    if not name:
        return None
    by_rel, by_base = tex_idx if isinstance(tex_idx, tuple) else (tex_idx, tex_idx)

    # 1. raw game path from the RIF.
    cand = _normalize_raw(raw_name)
    if cand and cand in by_rel:
        return by_rel[cand]

    # 2. level-name subdirectory.
    if level_hint:
        key = f"{level_hint.lower()}/{name.lower()}"
        if key in by_rel:
            return by_rel[key]
        suffix = f"/{name.lower()}"
        for rel, full in by_rel.items():
            if rel.endswith(suffix) and level_hint.lower() in rel:
                return full

    # 3. bare basename (legacy fallback).
    return by_base.get(name.lower())


# ---------------------------------------------------------------------------
# MATCHIMG
# ---------------------------------------------------------------------------

def _basename_no_ext(path: str) -> str:
    """Basename of a path with the extension stripped."""
    return os.path.splitext(os.path.basename(path.replace('\\', '/')))[0]


def build_matchimg_index(rules: list[MatchImgRule]) -> dict[str, str]:
    """Map 'insteadof' basenames to 'load' basenames, both lowercase."""
    idx: dict[str, str] = {}
    for r in rules:
        io_name = r.insteadof.filename
        load_name = r.load.filename
        if io_name and load_name:
            idx[_basename_no_ext(io_name).lower()] = _basename_no_ext(load_name)
    return idx


def apply_matchimg_index(name: str | None, index: dict[str, str]) -> str | None:
    """Apply a MATCHIMG index substitution, leaving unmatched names intact."""
    if not name or not index:
        return name
    return index.get(name.lower(), name)