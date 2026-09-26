# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Bake character OBANALLS sequences into Blender NLA tracks.

Character RIFs (avp_huds/hnpc*.rif) store per-bone animation in
OBANALLS chunks. Each bone has N sequences, each sequence a list of
keyframes with orientation (quaternion) and transform (position).

One NLA track is created per sequence per bone. A SINGLE global
"default" sequence key (sequence_number, sub_sequence_number) is left
unmuted across every bone, so pressing Play animates the whole
creature in lockstep. Every other track is muted.

Convention (verified empirically from raw dumps):
OBANALLS frames are BONE-LOCAL relative to the parent, not absolute.

  - body (root):     f0.trans == OBJHEAD1.pos     (root: local == absolute)
  - left a1 finger:  f0.trans == rest.pos - body.pos
                     f0.q == rest.q
  - body sub6 (attack): body rotates ~49 deg around X; finger's q
                     stays at its rest value (0, 0.707, 0, 0.707) -
                     proof the child does not carry the parent's
                     rotation inside its own q.

Composition: the parent's world rotation already carries the
AvP->Blender axis conversion, so a child's local transform passes
through UNCONVERTED and Blender composes it correctly. Only the root
gets the axis conversion (nothing above it provides it):

    root:  M_local_blender = T(apply_axis(trans)*scale)
                             @ R(R_axis * q)
    child: M_local_blender = T(trans*scale) @ R(q)

matrix_basis in the baker is then simply:

    root:  M_basis = M_local_blender
    child: M_basis = M_parent_rest @ M_local_blender

because Stage 1c sets matrix_parent_inverse = M_parent_rest^-1, so
Blender evaluates:

    world = parent.world @ parent_inverse @ basis
          = parent.world @ M_local_blender

which is exactly the desired hierarchy composition. No parent
interpolation is needed - Blender does it for us.

Frame timing: Object_Animation_Frame.at_frame_no is an AvP-internal
tick (stored as -1 sentinel in shipped RIFs); we spread frames
uniformly across AnimSequence.sequence_time (ms) at animation_fps.
AvP's native animation tick is 60 Hz, so animation_fps=60 by default
in the operator and scene.render.fps is synced to match - without it
Blender plays the baked strips at 24/30 fps and the creature moves at
the wrong speed.

bake_character_nla overwrites scene.render.fps to match `fps`. This is
intentional - it guarantees correct playback speed for BOTH character
and level animations, since the operator exposes a single
animation_fps property for both. If you later import a second RIF
with a different animation_fps, the last import wins.

API note: Blender 4.4 replaced flat Action.fcurves with a layered
model (action.layers[i].strips[j].channelbags[k].fcurves); 5.x
removed the legacy attribute entirely. _iter_action_fcurves()
handles both.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from .utils import apply_axis, log
from .parsers.char_anim import (
    AnimFrame, AnimSequence,
    HIER_FLAG_DELTA_FRAME, SEQ_FLAG_NO_INTERPOLATION,
)


_R_AXIS_MAT3 = Matrix.Rotation(-math.pi / 2.0, 3, 'X')
_R_AXIS_QUAT = _R_AXIS_MAT3.to_quaternion()


def _iter_action_fcurves(action):
    """Yield every FCurve in an Action, on Blender 3.x-5.x."""
    layers = getattr(action, "layers", None)
    if layers:
        for layer in layers:
            for strip in layer.strips:
                cbags = getattr(strip, "channelbags", None)
                if cbags is not None:
                    for cbag in cbags:
                        for fc in cbag.fcurves:
                            yield fc
                    continue
                cbag_fn = getattr(strip, "channelbag", None)
                if cbag_fn is None:
                    continue
                for slot in getattr(action, "slots", []):
                    cbag = cbag_fn(slot)
                    if cbag is None:
                        continue
                    for fc in cbag.fcurves:
                        yield fc
        return
    for fc in getattr(action, "fcurves", []):
        yield fc


def _frame_local_matrix(frame: AnimFrame, scale: float,
                        is_root: bool) -> Matrix:
    """Convert one AnimFrame to a LOCAL Blender 4x4 relative to parent."""
    # Root bones (no parent) get the full AvP->Blender axis conversion
    # on translation (apply_axis) and rotation (R_axis * q), because
    # nothing above them supplies it. Child bones receive the
    # conversion through the parent's world rotation - their local
    # translation and rotation pass through unconverted, which is
    # exactly what makes the parent's rotation compose correctly in
    # Blender.
    tx, ty, tz = frame.transform
    if is_root:
        vx, vy, vz = apply_axis(tx, ty, tz)
    else:
        vx, vy, vz = tx, ty, tz
    loc = Vector((vx * scale, vy * scale, vz * scale))
    qx, qy, qz, qw = frame.orientation
    q_avp = Quaternion((qw, qx, qy, qz))
    q_b = (_R_AXIS_QUAT @ q_avp) if is_root else q_avp
    return Matrix.Translation(loc) @ q_b.to_matrix().to_4x4()


def _rest_world_matrix(pos, quat, scale: float) -> Matrix:
    """Convert an OBJHEAD1 (pos, quat) pair to a Blender world 4x4."""
    # Rest poses in OBJHEAD1 ARE absolute - verified from a raw dump:
    # adjacent finger bones are exactly 128 AvP units apart. Only the
    # ANIMATION frames are bone-local.
    vx, vy, vz = apply_axis(pos[0], pos[1], pos[2])
    loc = Vector((vx * scale, vy * scale, vz * scale))
    q_avp = Quaternion((quat[3], quat[0], quat[1], quat[2]))
    q_b = _R_AXIS_QUAT @ q_avp
    return Matrix.Translation(loc) @ q_b.to_matrix().to_4x4()


def _sequence_frame_numbers(seq: AnimSequence, fps: int,
                            canonical_time_ms: int | None = None) -> list[int]:
    """Return the Blender frame number for each RIF frame in `seq`.

    Frames are spread uniformly across `canonical_time_ms` (ms) at
    `fps`. When canonical_time_ms is None, the sequence's own
    sequence_time is used. Callers pass the canonical time when parent
    and child must share the same Blender-frame grid.

    at_frame_no is deliberately ignored - it is an AvP tick value
    (0-65535), not a Blender frame index, and is stored as the sentinel
    -1 in shipped RIFs.
    """
    n = len(seq.frames)
    if n == 0:
        return []
    if n == 1:
        return [1]

    if canonical_time_ms is None:
        seq_ms = max(0, int(seq.sequence_time))
    else:
        seq_ms = max(0, int(canonical_time_ms))
    if seq_ms <= 0:
        return [1 + i for i in range(n)]

    total_frames = max(1, round(seq_ms / 1000.0 * fps))
    return [1 + round(i * total_frames / (n - 1)) for i in range(n)]


def bake_character_nla(scan, cols, scale: float, fps: int = 30,
                       limit_sequences: int = 0) -> tuple[int, int]:
    """Bake every bone's OBANALLS sequences as NLA tracks on its object.

    See module docstring for the frame convention. Returns
    (num_bones_processed, num_strips).
    """
    if not scan.char_bones:
        return 0, 0

    geometry_col = cols["geometry"]
    obj_by_tag: dict[str, object] = {}
    for obj in geometry_col.objects:
        tag = obj.get("avp_tag")
        if tag:
            obj_by_tag[str(tag).lower()] = obj

    oh_by_tag = {oh.tag.lower(): oh for oh in scan.all_obj_headers if oh.tag}
    rest_world: dict[str, Matrix] = {}
    for bone in scan.char_bones:
        oh = oh_by_tag.get(bone.name.lower())
        if oh is None:
            continue
        rest_world[bone.name.lower()] = _rest_world_matrix(
            oh.pos, oh.quat, scale)

    # --- 1. Global sequence-key order + canonical time per key ---------
    seq_key_order: list[tuple[int, int]] = []
    seen_keys: set[tuple[int, int]] = set()
    max_time_by_key: dict[tuple[int, int], int] = {}
    for bone in scan.char_bones:
        if bone.anim is None:
            continue
        for seq in bone.anim.sequences:
            key = (seq.sequence_number, seq.sub_sequence_number)
            if key not in seen_keys:
                seen_keys.add(key)
                seq_key_order.append(key)
            st = max(0, int(seq.sequence_time))
            if st > max_time_by_key.get(key, 0):
                max_time_by_key[key] = st

    if seq_key_order:
        keys_str = ", ".join(f"seq{s}_sub{b}" for s, b in seq_key_order)
        log.info(f"  Sequence keys ({len(seq_key_order)}): {keys_str}")

    if limit_sequences > 0:
        seq_key_order = seq_key_order[:limit_sequences]
    allowed_keys = set(seq_key_order)

    # --- 2. Per-bone LOCAL frame data indexed by sequence key ----------
    bone_frames: dict[str, dict[tuple[int, int],
                                tuple[AnimSequence, list]]] = {}
    n_delta = 0
    n_frames_total = 0
    for bone in scan.char_bones:
        if bone.anim is None:
            continue
        is_root = (bone.parent_name is None)
        by_key: dict[tuple[int, int], tuple[AnimSequence, list]] = {}
        for seq in bone.anim.sequences:
            key = (seq.sequence_number, seq.sub_sequence_number)
            if key not in allowed_keys:
                continue
            canonical_ms = max_time_by_key.get(key)
            frame_nos = _sequence_frame_numbers(seq, fps, canonical_ms)
            frame_data: list[tuple[int, Matrix]] = []
            for f, fno in zip(seq.frames, frame_nos):
                if f.flags & HIER_FLAG_DELTA_FRAME:
                    n_delta += 1
                frame_data.append(
                    (fno, _frame_local_matrix(f, scale, is_root)))
            if frame_data:
                by_key[key] = (seq, frame_data)
                n_frames_total += len(frame_data)
        if by_key:
            bone_frames[bone.name.lower()] = by_key

    if n_delta:
        log.warning(f"  {n_delta} delta frame(s) treated as absolute "
                    f"(HierarchyFrameFlag_DeltaFrame not applied)")

    if not bone_frames:
        return 0, 0

    # --- 3. Global default key: first key with >1 frame in any bone ----
    default_key: tuple[int, int] | None = None
    for key in seq_key_order:
        for by_key in bone_frames.values():
            entry = by_key.get(key)
            if entry is not None and len(entry[1]) > 1:
                default_key = key
                break
        if default_key is not None:
            break

    # --- 4. Snapshot rest transforms before mutating objects -----------
    rest_xform: dict[str, tuple[Vector, Quaternion]] = {}
    for bone in scan.char_bones:
        obj = obj_by_tag.get(bone.name.lower())
        if obj is None:
            continue
        rest_xform[bone.name.lower()] = (
            Vector(obj.location),
            Quaternion(obj.rotation_quaternion),
        )

    # --- 5. Bake per bone ---------------------------------------------
    n_bones = 0
    n_strips = 0
    n_unmuted = 0
    max_frame = 1

    for bone in scan.char_bones:
        tag = bone.name.lower()
        if tag not in bone_frames:
            continue
        obj = obj_by_tag.get(tag)
        if obj is None:
            log.debug(f"  no mesh for animated bone '{bone.name}'")
            continue

        obj.rotation_mode = 'QUATERNION'

        if obj.animation_data is not None:
            obj.animation_data_clear()
        anim = obj.animation_data_create()

        by_key = bone_frames[tag]
        is_root = (bone.parent_name is None)

        M_parent_rest: Matrix | None = None
        if bone.parent_name is not None:
            M_parent_rest = rest_world.get(bone.parent_name.lower())

        for key in seq_key_order:
            entry = by_key.get(key)
            if entry is None:
                continue
            seq, fdata = entry

            action = bpy.data.actions.new(f"{obj.name}.{seq.label()}")
            action.use_fake_user = True
            anim.action = action

            for fno, M_local in fdata:
                # Stage 1c installed matrix_parent_inverse =
                # M_parent_rest^-1, so Blender evaluates
                #   world = parent.world @ M_parent_rest^-1 @ basis
                # We want world = parent.world @ M_local, hence
                #   basis = M_parent_rest @ M_local.
                # For roots there is no parent, so basis = M_local.
                if is_root or M_parent_rest is None:
                    M_basis = M_local
                else:
                    M_basis = M_parent_rest @ M_local
                loc, rot, _ = M_basis.decompose()
                obj.location = loc
                obj.rotation_quaternion = rot
                obj.keyframe_insert("location", frame=fno)
                obj.keyframe_insert("rotation_quaternion", frame=fno)
                if fno > max_frame:
                    max_frame = fno

            interp = 'LINEAR'
            if seq.frames and (seq.frames[0].flags
                               & SEQ_FLAG_NO_INTERPOLATION):
                interp = 'CONSTANT'
            for fc in _iter_action_fcurves(action):
                for kp in fc.keyframe_points:
                    kp.interpolation = interp

            track = anim.nla_tracks.new()
            track.name = seq.label()
            strip = track.strips.new(seq.label(), 1, action)
            strip.name = seq.label()
            track.mute = (key != default_key)
            if not track.mute:
                n_unmuted += 1
            n_strips += 1

        anim.action = None
        n_bones += 1

    for tag, (loc, rot) in rest_xform.items():
        obj = obj_by_tag.get(tag)
        if obj is None:
            continue
        obj.location = loc
        obj.rotation_quaternion = rot

    scene = bpy.context.scene
    if scene.frame_end < max_frame:
        scene.frame_end = max_frame
    scene.frame_start = 1
    # Sync scene.render.fps to `fps`. Frames were distributed across
    # sequence_time using AvP's native 60 Hz tick (animation_fps prop,
    # default 60); if Blender's scene fps stays at 24/30, the baked
    # strips play back at the wrong speed. Both character and level
    # animations share the operator's animation_fps, so a single sync
    # here covers both. Last import wins if the prop differs.
    prev_fps = scene.render.fps
    scene.render.fps = max(1, int(fps))
    scene.render.fps_base = 1.0
    if prev_fps != scene.render.fps:
        log.info(f"  Scene FPS: {prev_fps} -> {scene.render.fps} "
                 f"(matches AvP animation tick)")
    scene.frame_set(1)

    log.info(f"  Baked NLA: {n_bones} bone(s), {n_strips} strip(s), "
             f"{n_frames_total} keyframe(s), frame range 1..{max_frame}")
    if n_unmuted:
        log.info(f"  {n_unmuted} track(s) unmuted "
                 f"(shared default sequence per bone) - press Space.")
    else:
        log.info(f"  All {n_strips} track(s) muted - no multi-frame "
                 f"sequences found. Rest pose stays visible; un-mute a "
                 f"track in the NLA Editor to preview.")
    if default_key is not None:
        log.info(f"  Default (unmuted) key: seq{default_key[0]}"
                 f"_sub{default_key[1]}  (same across all bones)")
    return n_bones, n_strips