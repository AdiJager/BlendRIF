# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""High-level per-shape import.

Resolves the transform and bitmap table for a single ShapeGroup, then
delegates the actual mesh build to geometry.build_mesh. Handles the
placeholder-vs-external-RIF decision and the orphan-shape policy.

When an SHPEXTFL reference cannot be resolved and
ctx.mark_missing_ext is True, an Empty marker is spawned at the
shape's pivot inside a dedicated MissingExtRif subcollection, so the
user can navigate to that spot in-game and check what the level
originally had there.

Level RIFs commonly contain the referenced shape as placeholder
geometry even when the SHPEXTFL target does not exist on disk. The
fallback to that placeholder is the *correct* outcome, not a bug -
so failures with a non-empty placeholder are logged at info level and
do not pollute ctx.warnings. Only genuinely empty placeholders (no
fallback geometry at all) produce a warning.

A separate counter tracks the third outcome: the external RIF *was*
found and *did* have geometry, but the AUTO strategy still picked the
level's own placeholder because it had at least as many verts. This
is not a failure - it is exactly what AUTO is for - but it must be
counted so the SHPEXTFL breakdown in the summary adds up.

ImportContext carries `cull_backfaces` (default True), forwarded
verbatim to geometry.build_mesh. The operator exposes this as a
checkbox in the Materials section.

Repeated SHPEXTFL misses for the same external name do not flood the
log: the first miss per unique ext_name logs the full INFO line,
subsequent placements of the same shape downgrade to DEBUG. Counters
still tick per-use, so the SHPEXTFL breakdown in the summary keeps
its "uses" semantics (78 uses of a missing 'catseye' shape, not
"1 unique missing shape"). The ext_miss_logged set on ImportContext
tracks which names have already been announced.

Character RIFs store OBJHEAD1.pos / .quat as ABSOLUTE (world) values,
not bone-local. When ctx.character_mode is True, process_shape keeps
vertices in raw bone-local space (scaled only) and puts the absolute
transform on the Blender object, with the AvP->Blender axis
conversion applied uniformly to every bone. Stage 1c then sets
matrix_parent_inverse to the parent's world inverse so the child's
world position stays exactly where process_shape put it - the
Outliner hierarchy becomes purely navigational.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import bpy
from mathutils import Vector, Quaternion, Matrix

from .chunks import ShapeGroup
from .config import (
    OBJECT_FLAG_PLACED_OBJECT,
    PivotMode, ExtRifStrategy, OrphanMode,
)
from .geometry import build_mesh, quat_to_mat, is_identity_quat
from .utils import sanitize, apply_axis, _safe_name, log
from .props import (
    AVP_PROP_TYPE, AVP_PROP_EXT_NAME, AVP_PROP_SHAPE_IDX,
    AVP_PROP_PLACEHOLDER_VERTS, AVP_TYPE_MISSING_EXT,
)
from .parsers.shapes import (
    ShpHead, ObjHead, parse_shphead1, parse_objhead1, parse_shpextfl,
)
from .rif_loader import load_ext_rif, pick_ext_shape, count_verts


# AvP -> Blender axis conversion as a 3x3 matrix: rotate -90 deg about X.
# Equivalent to apply_axis(x, y, z) = (x, z, -y). Used in character mode
# to convert the absolute bone rotation: q_b = R_axis * q_avp.
_R_AXIS_MAT3 = Matrix.Rotation(-math.pi / 2.0, 3, 'X')


@dataclass
class ImportContext:
    """Everything the per-shape importer needs beyond the shape itself."""
    base: str
    scale: float
    bmp_names: dict
    tex_idx: tuple
    bm_mode: str
    uv_scale: float
    uv_int16_mode: bool
    mat_cache: dict
    matchimg_index: dict
    rif_index: dict
    ext_cache: dict
    ext_stats: dict
    pivot_mode: PivotMode = PivotMode.ROTATED_ONLY
    ext_strategy: ExtRifStrategy = ExtRifStrategy.AUTO
    use_rotation: bool = True
    clrlookp_table: list | None = None
    orphan_mode: OrphanMode = OrphanMode.SKIP
    placed_positions: dict = field(default_factory=dict)
    all_objects: list = field(default_factory=list)   # list[ObjHead]
    warnings: list = field(default_factory=list)
    level_hint: str = ""
    import_materials: bool = True
    # Enable backface culling on materials - matches the AvP engine,
    # hides designer geometry with inverted normals (Lockdown4
    # VAULTLEVELS, Colony floor signs). Set False to inspect that
    # geometry in Blender.
    cull_backfaces: bool = True
    # --- Missing-ext debug markers ---
    mark_missing_ext: bool = False
    missing_ext_collection: object | None = None       # bpy.types.Collection
    # Counters, incremented in place, per-use.
    missing_ext_count: int = 0           # markers actually created
    placeholder_fallback_count: int = 0  # fallback OK, had geometry
    empty_missing_count: int = 0         # fallback had zero geometry
    placeholder_preferred_count: int = 0 # external found, Auto chose placeholder
    # Log-dedupe for repeated SHPEXTFL misses: first miss per unique
    # ext_name logs the full INFO line; subsequent placements of the
    # same shape downgrade to DEBUG. Counters above keep their
    # per-use semantics - only the log is deduped.
    ext_miss_logged: set = field(default_factory=set)
    # Character RIF mode: OBJHEAD1.pos / .quat are ABSOLUTE (world)
    # values. Vertices stay in raw bone-local space (scaled only) and
    # the absolute transform goes on the object with the AvP->Blender
    # axis conversion applied uniformly. Stage 1c then sets
    # matrix_parent_inverse = parent.matrix_world.inverted() so each
    # child's world stays exactly where process_shape put it; the
    # Outliner hierarchy is decorative.
    character_mode: bool = False


@dataclass
class ResolvedShape:
    """The chosen shape (placeholder or external) plus the bitmaps to use."""
    shape: ShapeGroup
    local_bitmaps: dict
    ext_bitmaps: dict | None
    ext_loaded: bool
    ext_name: str | None = None
    # True iff SHPEXTFL pointed at an unresolvable external RIF (or one
    # with no usable shape). Used by the marker feature regardless of
    # whether the placeholder happened to be a valid fallback.
    ext_missing: bool = False


def try_infer_position(shape: ShapeGroup, header: ShpHead | None,
                       all_objects: list[ObjHead], base: str,
                       idx: int):
    """Guess a world position for an orphan shape; returns (pos, quat, reason)."""
    if not header:
        return None
    h_tag = header.tag or ""
    h_names = header.obj_names or []
    for oname in h_names:
        for oh in all_objects:
            if oh.tag and oh.tag.lower() == oname.lower():
                return (oh.pos, oh.quat, "INFER:name")
    if h_tag:
        h_lower = h_tag.lower()
        for oh in all_objects:
            if oh.tag:
                ot = oh.tag.lower()
                if h_lower in ot or ot in h_lower:
                    return (oh.pos, oh.quat, "INFER:substr")
    return None


def _log_ext_miss(ctx: ImportContext, ext_name: str, reason: str,
                  ph_verts: int) -> None:
    """Log a placeholder-fallback message once per unique ext_name."""
    # The same external name (e.g. nostromo's 'catseye') can be
    # referenced by dozens of placements. Full INFO on first sight,
    # DEBUG afterwards - so the log doesn't repeat the same line 78x.
    if ext_name not in ctx.ext_miss_logged:
        log.info(f"    [EXT] '{ext_name}': {reason} "
                 f"-> placeholder fallback ({ph_verts} verts)")
        ctx.ext_miss_logged.add(ext_name)
    else:
        log.debug(f"    [EXT] '{ext_name}': placeholder fallback "
                  f"({ph_verts} verts)")


def _resolve_ext_shape(shape: ShapeGroup, ctx: ImportContext,
                       header: ShpHead | None) -> ResolvedShape:
    """Choose between the placeholder shape and an external RIF's shape."""
    ext_name = None
    local_bm: dict = {}
    if shape.ext_fl is not None:
        e = parse_shpextfl(shape.ext_fl)
        ext_name = e.riff_name
        local_bm = e.bitmaps
        if ctx.ext_stats is not None:
            ctx.ext_stats["with_extfl"] += 1

    # No SHPEXTFL at all (or nothing to look up against) - normal shape.
    if not (ext_name and ctx.rif_index and ctx.ext_cache is not None):
        return ResolvedShape(shape, local_bm, None, False, ext_name,
                             ext_missing=False)

    want = header.tag if header else None
    ext, reason = load_ext_rif(ext_name, ctx.rif_index, ctx.ext_cache, want)

    if ext is None or not ext["shapes"]:
        # Level RIFs usually carry the referenced shape as placeholder
        # geometry. When the placeholder has verts, the fallback is
        # the correct outcome - log at info level, no warning. Only
        # warn when there is literally nothing to fall back to.
        ph_verts = count_verts(shape)
        if not reason and ext is not None:
            reason = f"no usable shape in {ext.get('path', '?')}"
        if ph_verts == 0:
            if reason:
                ctx.warnings.append(
                    f"SHPEXTFL '{ext_name}': {reason} "
                    f"(placeholder has no geometry)")
            ctx.empty_missing_count += 1
        else:
            _log_ext_miss(ctx, ext_name,
                          reason or "external RIF not found",
                          ph_verts)
            ctx.placeholder_fallback_count += 1
        return ResolvedShape(shape, local_bm, None, False, ext_name,
                             ext_missing=True)

    ext_shape = pick_ext_shape(ext, want)
    if not ext_shape:
        ph_verts = count_verts(shape)
        if ph_verts == 0:
            ctx.warnings.append(
                f"SHPEXTFL '{ext_name}': no matching shape and "
                f"placeholder has no geometry")
            ctx.empty_missing_count += 1
        else:
            _log_ext_miss(ctx, ext_name,
                          "no tag match",
                          ph_verts)
            ctx.placeholder_fallback_count += 1
        return ResolvedShape(shape, local_bm, None, False, ext_name,
                             ext_missing=True)

    ev = count_verts(ext_shape)
    pv = count_verts(shape)

    if ctx.ext_strategy == ExtRifStrategy.PREFER_EXT:
        use_ext = True
    elif ctx.ext_strategy == ExtRifStrategy.PREFER_PLACEHOLDER:
        use_ext = False
    else:
        # Auto: prefer whichever has more vertices.
        use_ext = (pv == 0) or (ev >= pv)

    if use_ext and ev > 0:
        if ctx.ext_stats is not None:
            ctx.ext_stats["resolved"] += 1
        return ResolvedShape(ext_shape, local_bm, ext["bitmaps"], True,
                             ext_name, ext_missing=False)
    # Deliberate placeholder choice - external exists but the strategy
    # picked the level's own copy (Auto: placeholder has >= verts, or
    # PREFER_PLACEHOLDER is set). Not a miss, no marker, but count it
    # so the SHPEXTFL breakdown in the summary adds up.
    if ev > 0:
        ctx.placeholder_preferred_count += 1
    return ResolvedShape(shape, local_bm, None, False, ext_name,
                         ext_missing=False)


def _resolve_transform(obj: ObjHead | None, header: ShpHead | None,
                       ctx: ImportContext, shape: ShapeGroup, idx: int):
    """Resolve the world transform for a shape; None means skip the shape."""
    if obj:
        ox, oy, oz = obj.pos
        quat = obj.quat
        # Placed objects override the header transform with PLACHIDT data.
        if ctx.placed_positions and (obj.flags & OBJECT_FLAG_PLACED_OBJECT):
            hit = None
            if obj.tag:
                hit = ctx.placed_positions.get(("tag", obj.tag.lower()))
            if hit is None:
                hit = ctx.placed_positions.get(("id", obj.shape_id))
            if hit is not None:
                ox, oy, oz = hit["location"]
                quat = hit["orientation"]
        return ox, oy, oz, quat

    if ctx.orphan_mode == OrphanMode.SKIP:
        return None
    if ctx.orphan_mode == OrphanMode.INFER and ctx.all_objects:
        inferred = try_infer_position(shape, header,
                                      ctx.all_objects, ctx.base, idx)
        if inferred:
            return inferred[0][0], inferred[0][1], inferred[0][2], inferred[1]
    return 0, 0, 0, (0.0, 0.0, 0.0, 1.0)


def _effective_bitmaps(res: ResolvedShape, ctx: ImportContext) -> dict:
    """Return the bitmap table to use for a given ResolvedShape."""
    # External path never consults bmp_names - different namespace.
    if res.ext_loaded:
        bm = dict(res.ext_bitmaps or {})
        if res.local_bitmaps:
            bm.update(res.local_bitmaps)
        return bm

    # Placeholder path: level bitmaps, with SHPEXTFL overrides on top.
    bm = dict(ctx.bmp_names)
    if res.local_bitmaps:
        bm.update(res.local_bitmaps)
    return bm


def _create_missing_marker(res: ResolvedShape, shape: ShapeGroup,
                           ctx: ImportContext,
                           ox, oy, oz, quat, idx: int,
                           fallback_collection) -> None:
    """Spawn an Empty marker at the pivot of an unresolved SHPEXTFL."""
    col = ctx.missing_ext_collection or fallback_collection
    if col is None:
        return

    ext_label = res.ext_name or f"ext_{idx}"
    name = _safe_name(ctx.base, "MISSING", ext_label, idx)

    # Same coordinate transform used for geometry: apply_axis then scale.
    vx, vy, vz = apply_axis(ox, oy, oz)
    loc = (vx * ctx.scale, vy * ctx.scale, vz * ctx.scale)

    placeholder_verts = count_verts(res.shape)

    e = bpy.data.objects.new(name, None)
    e.empty_display_type = 'SPHERE'
    # Bigger than dummy markers so they pop when the level is loaded.
    e.empty_display_size = 1.5 * max(ctx.scale, 0.1)
    e.location = loc
    if quat:
        e.rotation_mode = 'QUATERNION'
        e.rotation_quaternion = Quaternion(
            (quat[3], quat[0], quat[1], quat[2]))
    # Custom properties let the user click the marker in the viewport
    # and read the details in Object Properties > Custom Properties.
    try:
        e[AVP_PROP_TYPE] = AVP_TYPE_MISSING_EXT
        e[AVP_PROP_EXT_NAME] = res.ext_name or ""
        e[AVP_PROP_SHAPE_IDX] = idx
        e[AVP_PROP_PLACEHOLDER_VERTS] = placeholder_verts
    except (TypeError, ValueError):
        pass
    col.objects.link(e)
    ctx.missing_ext_count += 1


def process_shape(shape: ShapeGroup, obj: ObjHead | None, idx: int,
                  ctx: ImportContext, target_collection,
                  timings: dict | None = None):
    """Import a single shape; returns the object name or None if skipped."""
    t0 = time.perf_counter() if timings is not None else 0.0

    header = parse_shphead1(shape.head) if shape.head else None

    # Name priority: object tag > shape tag > generated index name.
    name = f"{ctx.base}_{idx:03d}"
    t_shape = header.tag if header and header.tag else ""
    t_obj = obj.tag if obj and obj.tag else ""
    if t_obj and t_obj.lower() != "player":
        chosen = t_obj
    elif t_shape and t_shape.lower() != "player":
        chosen = t_shape
    else:
        chosen = t_obj
    if chosen:
        c = sanitize(chosen)
        if c:
            name = f"{ctx.base}_{c}"

    res = _resolve_ext_shape(shape, ctx, header)

    resolved = _resolve_transform(obj, header, ctx, shape, idx)
    if resolved is None:
        if timings is not None:
            timings["parse"] = timings.get("parse", 0.0) + (
                time.perf_counter() - t0)
        return None
    ox, oy, oz, quat = resolved

    # Spawn a marker at the position of every unresolved SHPEXTFL,
    # regardless of whether the placeholder still produced geometry.
    # The marker lives in its own subcollection so it can be hidden
    # with one click.
    if res.ext_missing and ctx.mark_missing_ext:
        _create_missing_marker(res, shape, ctx, ox, oy, oz, quat, idx,
                               target_collection)

    # Character mode uses object-level transforms; non-character keeps
    # the legacy path that bakes the world transform into the vertices.
    char_loc: tuple[float, float, float] | None = None
    char_quat: Quaternion | None = None

    if ctx.character_mode and obj is not None:
        # Character RIF: OBJHEAD1.pos / .quat are ABSOLUTE (world) in
        # the RIF, not bone-local. Keep vertices in raw bone-local
        # space (scaled only) and put the absolute transform on the
        # object with the AvP->Blender axis conversion applied
        # uniformly.
        #
        # Stage 1c will set matrix_parent_inverse = parent.matrix_world
        # inverse so this object's world stays exactly what we compute
        # here, regardless of parenting; the Outliner hierarchy
        # becomes purely navigational.
        #
        #     loc_b = apply_axis(loc_avp) * scale
        #     q_b   = R_axis_quat * q_avp
        def xform(v):
            vx, vy, vz = float(v[0]), float(v[1]), float(v[2])
            return (vx * ctx.scale, vy * ctx.scale, vz * ctx.scale)

        do_center = False

        vx, vy, vz = apply_axis(ox, oy, oz)
        char_loc = (vx * ctx.scale, vy * ctx.scale, vz * ctx.scale)
        q_avp = Quaternion((quat[3], quat[0], quat[1], quat[2]))
        char_quat = (_R_AXIS_MAT3 @ q_avp.to_matrix()).to_quaternion()
    else:
        has_rot = not is_identity_quat(quat)
        rot_mat = (quat_to_mat(*quat)
                   if (ctx.use_rotation and has_rot) else None)

        # Transform vertices to world space: rotate, translate, axis-
        # swap, scale.
        def xform(v):
            vx, vy, vz = float(v[0]), float(v[1]), float(v[2])
            if rot_mat:
                vec = rot_mat @ Vector((vx, vy, vz))
                vx, vy, vz = vec.x, vec.y, vec.z
            vx += ox
            vy += oy
            vz += oz
            vx, vy, vz = apply_axis(vx, vy, vz)
            return (vx * ctx.scale, vy * ctx.scale, vz * ctx.scale)

        do_center = (ctx.pivot_mode == PivotMode.ALL
                     or (ctx.pivot_mode == PivotMode.ROTATED_ONLY
                         and has_rot))

    bitmaps = _effective_bitmaps(res, ctx)

    # Parse phase done - the rest is mesh + materials.
    if timings is not None:
        timings["parse"] = timings.get("parse", 0.0) + (
            time.perf_counter() - t0)
        t0 = time.perf_counter()

    mat_t = [0.0] if timings is not None else None

    result = build_mesh(
        res.shape, ctx.base, name, ctx.scale,
        bitmaps, ctx.tex_idx, ctx.bm_mode, ctx.uv_scale, ctx.mat_cache,
        xform, do_center, ctx.clrlookp_table, ctx.matchimg_index,
        uv_int16_mode=ctx.uv_int16_mode,
        level_hint=ctx.level_hint,
        mat_timing=mat_t,
        import_materials=ctx.import_materials,
        cull_backfaces=ctx.cull_backfaces)
    if timings is not None:
        elapsed = time.perf_counter() - t0
        mat_elapsed = mat_t[0]
        timings["mesh"] = timings.get("mesh", 0.0) + (elapsed - mat_elapsed)
        timings["mat"] = timings.get("mat", 0.0) + mat_elapsed

    if result is None:
        return None
    mesh, _, loc = result
    o = bpy.data.objects.new(name, mesh)
    target_collection.objects.link(o)
    if char_loc is not None and char_quat is not None:
        o.location = char_loc
        o.rotation_mode = 'QUATERNION'
        o.rotation_quaternion = char_quat
    else:
        o.location = loc
    return name