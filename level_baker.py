# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Bake OBJTRAK2 level tracks as NLA strips on dedicated Empty objects.

AvP level animation has two separate systems:

  - OBANALLS: character skeletons (see char_baker.py), bone-local
    frames relative to the parent bone.
  - OBJTRAK2: level tracks (doors, lifts, rotating fans, moving
    platforms). Each track is a list of sections; every section is a
    piecewise-linear (or slerp'd) movement from pivot_start to
    pivot_end with a quaternion rotation from quat_start to quat_end.

This module handles OBJTRAK2. Each track is baked onto its own Empty
object, with one location+quaternion keyframe pair per section
boundary. The Empty is placed at the track's pivot_start position
(AvP -> Blender axis conversion applied).

Binding tracks to specific meshes (which door / fan / lift a track
drives) is a future improvement - for now every track gets a
visually distinct Empty so the animation can be inspected in the
viewport.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from .utils import apply_axis, log
from .parsers.level_track import parse_objtrak2, LevelTrack


_R_AXIS_MAT3 = Matrix.Rotation(-math.pi / 2.0, 3, 'X')
_R_AXIS_QUAT = _R_AXIS_MAT3.to_quaternion()


def _pivot_to_blender(pivot, scale: float) -> Vector:
    """Convert an AvP pivot position to Blender world coordinates."""
    vx, vy, vz = apply_axis(pivot[0], pivot[1], pivot[2])
    return Vector((vx * scale, vy * scale, vz * scale))


def _quat_to_blender(q) -> Quaternion:
    """Convert an AvP quaternion (x, y, z, w) to Blender space."""
    qx, qy, qz, qw = q
    q_avp = Quaternion((qw, qx, qy, qz))
    return _R_AXIS_QUAT @ q_avp


def bake_level_tracks(scan, base: str, cols, scale: float,
                      fps: int = 60,
                      section_seconds: float = 1.0) -> tuple[int, int, int]:
    """Bake every OBJTRAK2 chunk as an NLA strip on a dedicated Empty.

    Returns (num_tracks_baked, num_strips_created, max_frame).
    section_seconds controls the per-section duration in the baked
    animation: each section becomes round(section_seconds * fps)
    Blender frames.
    """
    if not scan.objtrak_list:
        return 0, 0, 1

    anim_col = cols.get("animations")
    if anim_col is None:
        log.warning("  bake_level_tracks: no animations collection")
        return 0, 0, 1

    section_frames = max(1, int(round(section_seconds * fps)))

    n_tracks = 0
    n_strips = 0
    max_frame = 1
    n_unparsed = 0

    # Late import to avoid a circular dependency at module load time.
    from .char_baker import _iter_action_fcurves

    for i, payload in enumerate(scan.objtrak_list):
        track = parse_objtrak2(payload)
        if track is None or not track.sections:
            n_unparsed += 1
            continue

        name = f"{base}_track_{i:03d}"
        empty = bpy.data.objects.new(name, None)
        empty.empty_display_type = 'SPHERE'
        empty.empty_display_size = 0.5
        anim_col.objects.link(empty)

        action = bpy.data.actions.new(name)
        action.use_fake_user = True
        empty.rotation_mode = 'QUATERNION'
        anim = empty.animation_data_create()
        anim.action = action

        current_frame = 1
        for j, section in enumerate(track.sections):
            # Start of section - keyframe at current_frame
            loc_s = _pivot_to_blender(section.pivot_start, scale)
            rot_s = _quat_to_blender(section.quat_start)
            empty.location = loc_s
            empty.rotation_quaternion = rot_s
            empty.keyframe_insert("location", frame=current_frame)
            empty.keyframe_insert("rotation_quaternion",
                                  frame=current_frame)

            # End of section - keyframe at current_frame + section_frames
            loc_e = _pivot_to_blender(section.pivot_end, scale)
            rot_e = _quat_to_blender(section.quat_end)
            end_frame = current_frame + section_frames
            empty.location = loc_e
            empty.rotation_quaternion = rot_e
            empty.keyframe_insert("location", frame=end_frame)
            empty.keyframe_insert("rotation_quaternion", frame=end_frame)

            current_frame = end_frame
            if current_frame > max_frame:
                max_frame = current_frame

        # LINEAR interpolation between keyframes - Blender's default
        # quaternion linear interpolation matches the runtime's slerp
        # closely enough for preview purposes.
        for fc in _iter_action_fcurves(action):
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'

        track_nla = anim.nla_tracks.new()
        track_nla.name = f"track_{i:03d}"
        strip = track_nla.strips.new(f"track_{i:03d}", 1, action)
        strip.name = f"track_{i:03d}"
        # Leave unmuted so the user immediately sees motion.
        track_nla.mute = False

        anim.action = None
        n_tracks += 1
        n_strips += 1

    if n_unparsed:
        log.warning(f"  {n_unparsed} OBJTRAK2 chunk(s) could not be parsed")

    # Sync scene FPS so preview runs at the same speed as the bake grid.
    scene = bpy.context.scene
    prev_fps = scene.render.fps
    scene.render.fps = max(1, int(fps))
    scene.render.fps_base = 1.0
    if prev_fps != scene.render.fps:
        log.info(f"  Scene FPS: {prev_fps} -> {scene.render.fps} "
                 f"(level track timing)")
    if scene.frame_end < max_frame:
        scene.frame_end = max_frame
    scene.frame_start = 1
    scene.frame_set(1)

    return n_tracks, n_strips, max_frame