# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Stage 1 (geometry) and Stage 1c (character hierarchy).

Stage 1 iterates RBOBJECTS placements, then orphan shapes, and
delegates per-shape work to shape_processor.process_shape. Stage 1c
parents the resulting mesh objects according to the OBJCHIER tree and
installs matrix_parent_inverse = M_abs[parent].inverted() using
matrices computed locally - never reads Blender's lazy
parent.matrix_world.

Virtual bones: a bone in the OBJCHIER tree with no matching OBJHEAD1
is legal - attachment points, pivots and rigs for throwable items
(Mdisk has 2 bones but 1 shape) rely on them. They are counted
separately as "virtual bones" and not logged as unresolved. Likewise
a bone whose parent is virtual is placed at its absolute rest
transform without parenting - Blender keeps it at the scene root and
the world position stays correct.

Neither run_stage_geometry nor run_stage_char_hierarchy reads any
operator property - they operate purely on the scan, the ImportContext
and the collection they write into, so the stages are independent of
IMPORT_OT_avp_rif.
"""

from __future__ import annotations

import math
import time

import bpy
from mathutils import Matrix, Quaternion, Vector

from .config import OrphanMode
from .shape_processor import process_shape
from .utils import log, apply_axis


# AvP -> Blender axis conversion as a 3x3 rotation about X by -90 deg.
_R_AXIS_MAT3 = Matrix.Rotation(-math.pi / 2.0, 3, 'X')


def run_stage_geometry(scan, ctx, stats, geometry_collection):
    """Import every placement, then orphan shapes; returns sub-timings."""
    shapes = scan.shapes
    placements = scan.all_obj_headers

    log.info("")
    log.info(f"--- Stage 1: Geometry "
             f"({len(shapes)} shapes, {len(placements)} placements) ---")

    sub_timings = {"parse": 0.0, "mesh": 0.0, "mat": 0.0}

    shape_by_id: dict[int, int] = {}
    for i, g in enumerate(shapes):
        h = scan.shape_headers[i]
        if h is not None and h.file_id_num >= 0:
            if h.file_id_num in shape_by_id:
                log.warning(f"  Duplicate shape file_id_num="
                            f"{h.file_id_num} (indices "
                            f"{shape_by_id[h.file_id_num]} and {i})")
            shape_by_id[h.file_id_num] = i

    wm = bpy.context.window_manager
    use_progress = hasattr(wm, "progress_begin") and placements
    if use_progress:
        wm.progress_begin(0, max(1, len(placements)))
    try:
        for i, oh in enumerate(placements):
            if use_progress and (i % 8 == 0):
                wm.progress_update(i)

            shp_idx = shape_by_id.get(oh.shape_id)
            if shp_idx is None:
                stats.skipped_no_shape += 1
                log.debug(f"  [{i:03d}] no shape for "
                          f"shape_id={oh.shape_id} (tag='{oh.tag}')")
                continue

            g = shapes[shp_idx]
            try:
                name = process_shape(g, oh, i, ctx, geometry_collection,
                                     sub_timings)
                if name:
                    stats.ok += 1
                    stats.placements_ok += 1
                    # Double-import safety: fetch from the collection we
                    # just linked into, not from bpy.data.objects by
                    # name. On a second import the object name gets a
                    # ".001" suffix and bpy.data.objects.get(name) would
                    # return the FIRST import's object - the avp_tag
                    # would land on the wrong mesh and Stage 1c (which
                    # matches by avp_tag) would silently find only the
                    # first-import copies.
                    obj = geometry_collection.objects.get(name)
                    if obj is not None and oh.tag:
                        obj["avp_tag"] = oh.tag
                else:
                    stats.skipped_nogeom += 1
                    log.warning(f"  [{i:03d}] no geometry "
                                f"(shape_id={oh.shape_id}, "
                                f"tag='{oh.tag}')")
            except (ValueError, RuntimeError, KeyError) as e:
                log.error(f"  [{i:03d}] ERR: {type(e).__name__}: {e}")
    finally:
        if use_progress:
            wm.progress_end()

    referenced_ids = set(scan.id_to_objs.keys())
    for i, g in enumerate(shapes):
        h = scan.shape_headers[i]
        if h is not None and h.file_id_num >= 0 \
                and h.file_id_num in referenced_ids:
            continue
        if ctx.orphan_mode == OrphanMode.SKIP:
            stats.orphan_skipped += 1
            continue
        try:
            name = process_shape(g, None, i, ctx, geometry_collection,
                                 sub_timings)
            if name:
                stats.ok += 1
                stats.orphan_ok += 1
            else:
                stats.orphan_skipped += 1
        except (ValueError, RuntimeError, KeyError) as e:
            log.error(f"  [orphan {i:03d}] ERR: {type(e).__name__}: {e}")

    if stats.orphan_skipped:
        log.info(f"  Orphan shapes: {stats.orphan_skipped} "
                 f"[mode: {ctx.orphan_mode.name}]")

    return sub_timings


def run_stage_char_hierarchy(scan, base, cols, counters, scale):
    """Parent imported mesh objects according to the OBJCHIER tree.

    Rest pose positions in OBJHEAD1 are ABSOLUTE (world) in the AvP
    frame - verified from a raw dump: adjacent finger bones are exactly
    128 AvP units apart.

    Algorithm (no reliance on Blender's lazy matrix_world):

      1. For every bone, build M_abs[tag] = T(apply_axis(pos)*scale)
         @ R(R_axis * q_avp). scan.char_bones is in DFS pre-order,
         so a single linear pass suffices.
      2. Set obj.parent for each bone and install
         matrix_parent_inverse = M_abs[parent].inverted(). Blender
         then evaluates matrix_world = parent.matrix_world @
         M_abs[parent].inverted() @ matrix_basis, which - since
         parent.matrix_world resolves to M_abs[parent] after the
         final view_layer.update() - reduces to matrix_basis =
         M_abs[bone]. The Outliner hierarchy is decorative.

    Virtual bones / parents: a bone (or its parent) that has no
    OBJHEAD1 entry is a legal rig construct - attachment points,
    pivots, throwable-item rigs (Mdisk: 2 bones, 1 shape). Such bones
    are placed at their absolute rest transform without parenting; the
    Outliner simply shows them at the scene root. They are logged as
    "virtual" and never confused with real missing-mesh errors.
    """
    if not scan.char_bones:
        return
    log.info("")
    log.info(f"--- Stage 1c: Character Hierarchy "
             f"({len(scan.char_bones)} bones) ---")

    oh_by_tag: dict[str, object] = {
        oh.tag.lower(): oh for oh in scan.all_obj_headers if oh.tag
    }
    geometry_col = cols["geometry"]
    by_tag: dict[str, object] = {}
    for obj in geometry_col.objects:
        tag = obj.get("avp_tag")
        if tag:
            by_tag[str(tag).lower()] = obj

    M_abs: dict[str, Matrix] = {}
    for bone in scan.char_bones:
        oh = oh_by_tag.get(bone.name.lower())
        if oh is None:
            continue
        vx, vy, vz = apply_axis(oh.pos[0], oh.pos[1], oh.pos[2])
        loc_b = Vector((vx * scale, vy * scale, vz * scale))
        q_avp = Quaternion((oh.quat[3], oh.quat[0],
                            oh.quat[1], oh.quat[2]))
        q_b = (_R_AXIS_MAT3 @ q_avp.to_matrix()).to_quaternion()
        M_abs[bone.name.lower()] = (
            Matrix.Translation(loc_b) @ q_b.to_matrix().to_4x4())

    n_parented = 0
    n_roots = 0
    # Real problems (something expected is missing from the scene):
    n_no_child_mesh = 0    # own OBJHEAD1 exists but no mesh in the scene
    n_no_parent_mesh = 0   # parent OBJHEAD1 exists but no mesh in the scene
    # Legal rig constructs (attachment points / pivots):
    n_virtual_bones = 0    # bone has no OBJHEAD1 at all
    n_virtual_parent = 0   # parent has no OBJHEAD1 (child placed absolute)

    for bone in scan.char_bones:
        tag = bone.name.lower()
        obj = by_tag.get(tag)
        M = M_abs.get(tag)

        # Virtual bone: the OBJCHIER tree lists this bone but the RIF
        # has no matching OBJHEAD1. Legal for attachment points and
        # pivots (Mdisk disc rig).
        if M is None:
            n_virtual_bones += 1
            log.debug(f"  virtual bone '{bone.name}' (no OBJHEAD1)")
            continue

        # Real problem: OBJHEAD1 exists but Stage 1 produced no mesh.
        if obj is None:
            n_no_child_mesh += 1
            log.debug(f"  no mesh for '{bone.name}' (OBJHEAD1 present)")
            continue

        if bone.parent_name is None:
            n_roots += 1
            obj.parent = None
            loc, rot, _ = M.decompose()
            obj.rotation_mode = 'QUATERNION'
            obj.location = loc
            obj.rotation_quaternion = rot
            continue

        parent_tag = bone.parent_name.lower()
        parent_obj = by_tag.get(parent_tag)
        M_parent = M_abs.get(parent_tag)

        # Virtual parent: parent has no OBJHEAD1. The child keeps its
        # absolute rest position; Blender simply has no parent to
        # attach it to. Correct for pivots and attachment rigs.
        if M_parent is None:
            n_virtual_parent += 1
            obj.parent = None
            loc, rot, _ = M.decompose()
            obj.rotation_mode = 'QUATERNION'
            obj.location = loc
            obj.rotation_quaternion = rot
            log.debug(f"  virtual parent '{bone.parent_name}' for "
                      f"'{bone.name}' - placed absolute, no parent")
            continue

        if parent_obj is None:
            n_no_parent_mesh += 1
            log.debug(f"  no mesh for parent '{bone.parent_name}' "
                      f"(child='{bone.name}')")
            continue

        obj.parent = parent_obj
        obj.matrix_parent_inverse = M_parent.inverted()
        loc, rot, _ = M.decompose()
        obj.rotation_mode = 'QUATERNION'
        obj.location = loc
        obj.rotation_quaternion = rot
        n_parented += 1

    try:
        bpy.context.view_layer.update()
    except (AttributeError, RuntimeError) as e:
        log.warning(f"  view_layer.update() failed: "
                    f"{type(e).__name__}: {e}")

    counters.hier_bones = len(scan.char_bones)
    counters.hier_parented = n_parented
    log.info(f"  Root bones: {n_roots}")
    log.info(f"  Parented:   {n_parented} bone(s)")
    if n_virtual_bones or n_virtual_parent:
        log.info(f"  Virtual:    {n_virtual_bones} bone(s), "
                 f"{n_virtual_parent} parent(s) "
                 f"(no OBJHEAD1, attachment rigs - OK)")
    if n_no_child_mesh or n_no_parent_mesh:
        log.info(f"  Unresolved: child_missing={n_no_child_mesh}, "
                 f"parent_missing={n_no_parent_mesh}")