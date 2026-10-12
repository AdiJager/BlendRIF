# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Empties, lights, curves and animation keyframes creation.

Each create_*_empties function takes the raw payloads collected by the
scanner, parses them, and creates one Blender object per record with its
relevant fields exposed as custom `avp_*` properties.

Note: OBJTRAK2 level-track baking lives in level_baker.py, not here.
This module only creates static marker objects (dummies, hierarchies,
generators, sounds, player starts, camera origins, paths, lights).
"""

from __future__ import annotations

import math

import bpy
from mathutils import Quaternion

from .chunk_ids import Chunk
from .chunks import parse_chunks
from .utils import _safe_name, apply_axis, world_pos, sanitize
from .props import (
    AVP_PROP_TYPE, AVP_PROP_NAME, AVP_PROP_TEXT,
    AVP_PROP_BBOX_MIN, AVP_PROP_BBOX_MAX,
    AVP_PROP_HIERARCHY_INDEX, AVP_PROP_ID,
    AVP_PROP_GENER_TYPE, AVP_PROP_FLAGS,
    AVP_PROP_SND_NAME, AVP_PROP_WAV_NAME,
    AVP_PROP_INNER_RANGE, AVP_PROP_OUTER_RANGE,
    AVP_PROP_MAX_VOLUME, AVP_PROP_PITCH, AVP_PROP_PROBABILITY,
    AVP_PROP_MODULE_ID, AVP_PROP_NUM_POINTS,
    AVP_PROP_MODULE_INDEX, AVP_PROP_POINT_FLAGS,
    AVP_PROP_BRIGHTNESS, AVP_PROP_SPREAD, AVP_PROP_RANGE,
    AVP_PROP_WP_MODULE_INDEX, AVP_PROP_WP_INDEX, AVP_PROP_WP_CENTRE,
    AVP_PROP_WP_MIN_EXTENTS, AVP_PROP_WP_MAX_EXTENTS,
    AVP_PROP_WP_LINK_INDICES, AVP_PROP_WP_LINK_FLAGS,
    AVP_TYPE_DUMMY, AVP_TYPE_HIERARCHY, AVP_TYPE_GENERATOR,
    AVP_TYPE_SOUND, AVP_TYPE_PLAYER_START, AVP_TYPE_CAMERA_ORIGIN,
    AVP_TYPE_PATH, AVP_TYPE_LIGHT, AVP_TYPE_WAYPOINT,
)
from .parsers.markers import (
    parse_dumobjdt, parse_dumobjtx, parse_plachidt,
    parse_avpgener, parse_soundob2, parse_avpstart,
    parse_camorign, parse_avppath2,
    PATH_FLAG_LOOP, PATH_FLAG_BACK_AND_FORTH,
)
from .parsers.lights import parse_stdlight


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _apply_props(obj, props) -> None:
    """Assign custom properties, coercing unsupported types to str."""
    if not props:
        return
    for k, v in props.items():
        try:
            obj[k] = v
        except (TypeError, ValueError):
            obj[k] = str(v)


def create_empty(name, location, quat=None, display='PLAIN_AXES',
                 size=0.5, collection=None, props=None):
    """Create and link one empty with optional rotation and custom properties."""
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = display
    e.empty_display_size = size
    e.location = location
    if quat:
        e.rotation_mode = 'QUATERNION'
        e.rotation_quaternion = Quaternion((quat[3], quat[0], quat[1], quat[2]))
    _apply_props(e, props)
    collection.objects.link(e)
    return e


# ---------------------------------------------------------------------------
# Per-marker-type creators
# ---------------------------------------------------------------------------

def create_dummy_empties(dummies, base, scale, collection) -> int:
    """Create one cube empty per DUMOBJ record; returns the count created."""
    n = 0
    for d in dummies:
        dt = d.get(Chunk.DUMOBJDT, [])
        tx = d.get(Chunk.DUMOBJTX, [])
        if not dt:
            continue
        p = parse_dumobjdt(dt[0])
        if not p:
            continue
        text = parse_dumobjtx(tx[0]) if tx else ""
        loc = world_pos(p.location, scale)
        obj_name = _safe_name(base, "dummy", p.name, n)
        create_empty(obj_name, loc, p.orientation, display='CUBE',
                     collection=collection,
                     props={
                         AVP_PROP_TYPE:      AVP_TYPE_DUMMY,
                         AVP_PROP_NAME:      p.name,
                         AVP_PROP_TEXT:      text,
                         AVP_PROP_BBOX_MIN:  str(p.min_extents),
                         AVP_PROP_BBOX_MAX:  str(p.max_extents),
                     })
        n += 1
    return n


def create_placed_hierarchy_empties(placed, base, scale, collection) -> int:
    """Create one cone empty per PLACHIDT record; returns the count created."""
    n = 0
    for p in placed:
        dt = p.get(Chunk.PLACHIDT, [])
        if not dt:
            continue
        pi = parse_plachidt(dt[0])
        if not pi:
            continue
        loc = world_pos(pi.location, scale)
        obj_name = _safe_name(base, "hier", pi.name, n)
        create_empty(obj_name, loc, pi.orientation, display='CONE',
                     collection=collection,
                     props={
                         AVP_PROP_TYPE:            AVP_TYPE_HIERARCHY,
                         AVP_PROP_NAME:            pi.name,
                         AVP_PROP_HIERARCHY_INDEX: pi.hierarchy_index,
                         AVP_PROP_ID:              str(pi.id),
                     })
        n += 1
    return n


def create_avpgener_empties(generators, base, scale, collection) -> int:
    """Create one sphere empty per AVPGENER record; returns the count created."""
    n = 0
    for g in generators:
        p = parse_avpgener(g)
        if not p:
            continue
        loc = world_pos(p.location, scale)
        # Orientation is stored as 0..65535 mapping to 0..360 degrees.
        angle_rad = (math.radians(p.orientation / 65536.0 * 360)
                     if p.orientation else 0)
        obj_name = _safe_name(base, "gen", p.name, n)
        e = bpy.data.objects.new(obj_name, None)
        e.empty_display_type = 'SPHERE'
        e.empty_display_size = 1.0 * max(scale, 0.1)
        e.location = loc
        e.rotation_euler = (0, angle_rad, 0)
        _apply_props(e, {
            AVP_PROP_TYPE:       AVP_TYPE_GENERATOR,
            AVP_PROP_NAME:       p.name,
            AVP_PROP_GENER_TYPE: p.type,
            AVP_PROP_FLAGS:      f"0x{p.flags:08x}",
        })
        collection.objects.link(e)
        n += 1
    return n


def create_sound_empties(sounds, base, scale, collection) -> int:
    """Create one sphere empty per SOUNDOB2 record; returns the count created."""
    n = 0
    for s in sounds:
        p = parse_soundob2(s)
        if not p:
            continue
        loc = world_pos(p.position, scale)
        obj_name = _safe_name(base, "snd", p.snd_name, n)
        create_empty(obj_name, loc, None, display='SPHERE',
                     size=0.3 * max(scale, 0.1), collection=collection,
                     props={
                         AVP_PROP_TYPE:        AVP_TYPE_SOUND,
                         AVP_PROP_SND_NAME:    p.snd_name,
                         AVP_PROP_WAV_NAME:    p.wav_name,
                         AVP_PROP_INNER_RANGE: p.inner,
                         AVP_PROP_OUTER_RANGE: p.outer,
                         AVP_PROP_MAX_VOLUME:  p.max_volume,
                         AVP_PROP_PITCH:       p.pitch,
                         AVP_PROP_FLAGS:       f"0x{p.flags:08x}",
                         AVP_PROP_PROBABILITY: p.probability,
                     })
        n += 1
    return n


def create_avpstart_empties(starts, base, scale, collection) -> int:
    """Create one arrow empty per AVPSTART record; returns the count created."""
    n = 0
    for s in starts:
        p = parse_avpstart(s)
        if not p:
            continue
        loc = world_pos(p.location, scale)
        create_empty(f"{base}_pstart_{n:03d}", loc, None,
                     display='ARROWS', size=0.5 * max(scale, 0.1),
                     collection=collection,
                     props={
                         AVP_PROP_TYPE:      AVP_TYPE_PLAYER_START,
                         AVP_PROP_MODULE_ID: str(p.module_id),
                     })
        n += 1
    return n


def create_camorign_empties(cams, base, scale, collection) -> int:
    """Create one arrow empty per CAMORIGN record; returns the count created."""
    n = 0
    for cm in cams:
        p = parse_camorign(cm)
        if not p:
            continue
        loc = world_pos(p.location, scale)
        obj_name = _safe_name(base, "camorigin", "", n)
        e = bpy.data.objects.new(obj_name, None)
        e.empty_display_type = 'ARROWS'
        e.empty_display_size = 1.0 * max(scale, 0.1)
        e.location = loc
        _apply_props(e, {AVP_PROP_TYPE: AVP_TYPE_CAMERA_ORIGIN})
        collection.objects.link(e)
        n += 1
    return n


def create_path_curves(paths, base, scale, collection, obj_by_index=None) -> int:
    """Create one poly-curve object per AVPPATH2 record; returns the count.

    A patrol path is a list of *modules*, not of coordinates: every
    point carries a `module_index` and the game walks the path by moving
    from one module to the next (`modules_in_path` in Projload.cpp /
    bh_ais.c), using each module's world position. The point's own
    location field is zero in all 1098 retail points, so the curve is
    built from the module origins resolved through OBJHEAD1.

    Objects whose module cannot be resolved are skipped; the object
    properties keep the module index, the point flags and the path
    flags so the original record can still be inspected.
    """
    n = 0
    by_index = obj_by_index or {}
    for p_data in paths:
        p = parse_avppath2(p_data)
        if not p or not p.points:
            continue
        located = []
        for pt in p.points:
            oh = by_index.get(pt.module)
            if oh is not None:
                located.append((pt, oh))
        if not located:
            log.info(f"    [PATH] '{p.name}' skipped: none of its "
                     f"{len(p.points)} module(s) resolved to an OBJHEAD1")
            continue
        obj_name = _safe_name(base, "path", p.name, n)
        curve_data = bpy.data.curves.new(obj_name, 'CURVE')
        curve_data.dimensions = '3D'
        spline = curve_data.splines.new('POLY')
        spline.points.add(len(located) - 1)
        for i, (pt, oh) in enumerate(located):
            vx, vy, vz = world_pos(oh.pos, scale)
            spline.points[i].co = (vx, vy, vz, 1.0)
        # PathFlag_LoopPath: the game loops straight back to module 0.
        # use_cyclic_u lives on the spline, not on the curve datablock.
        if p.flags & PATH_FLAG_LOOP:
            spline.use_cyclic_u = True
        curve_data.bevel_depth = 0.5 * scale if scale > 0 else 0.5
        obj = bpy.data.objects.new(obj_name, curve_data)
        modules = ",".join(str(pt.module) for pt, _ in located)
        flags = ",".join(str(pt.flags) for pt, _ in located)
        _apply_props(obj, {
            AVP_PROP_TYPE:        AVP_TYPE_PATH,
            AVP_PROP_NAME:        p.name,
            AVP_PROP_ID:          p.id,
            AVP_PROP_FLAGS:       p.flags,
            AVP_PROP_NUM_POINTS:  len(located),
            AVP_PROP_MODULE_INDEX: modules,
            AVP_PROP_POINT_FLAGS: flags,
        })
        collection.objects.link(obj)
        n += 1
    return n


def create_waypoint_objects(groups, base, scale, collection) -> int:
    """Create one cube empty per Alien navigation volume; returns the count.

    A waypoint volume is an axis-aligned box: `min`/`max` are its world
    corners and `centre` their midpoint, so the empty sits at the centre
    and its display size is half of the longest edge. Links to sibling
    volumes are written as `avp_wp_link_*` properties instead of
    geometry - the graph is far easier to read from the object
    properties than from a thicket of connecting curves.
    """
    n = 0
    for grp in groups:
        for wp in grp.alien:
            vx, vy, vz = world_pos(wp.centre, scale)
            longest = max(wp.max_extents[i] - wp.min_extents[i]
                          for i in range(3))
            half = max(longest, 0) / 2.0
            tag = sanitize(grp.module_tag) if grp.module_tag else ""
            name = (f"{base}_wp_{tag}_{wp.index:03d}" if tag
                    else f"{base}_wp_m{grp.module_index}_{wp.index:03d}")
            e = bpy.data.objects.new(name, None)
            e.empty_display_type = 'CUBE'
            # Cube display size is a half-extent, matching min/max.
            e.empty_display_size = half * scale if scale > 0 else half
            e.location = (vx, vy, vz)
            props = {
                AVP_PROP_TYPE:            AVP_TYPE_WAYPOINT,
                AVP_PROP_NAME:            grp.module_tag,
                AVP_PROP_FLAGS:           wp.flags,
                AVP_PROP_WP_MODULE_INDEX: grp.module_index,
                AVP_PROP_WP_INDEX:        wp.index,
                AVP_PROP_WP_CENTRE:       str(wp.centre),
                AVP_PROP_WP_MIN_EXTENTS:  str(wp.min_extents),
                AVP_PROP_WP_MAX_EXTENTS:  str(wp.max_extents),
            }
            if wp.links:
                # Comma-separated indices: readable in the UI and cheap to
                # parse back from a script.
                props[AVP_PROP_WP_LINK_INDICES] = ",".join(
                    str(lk.index) for lk in wp.links)
                props[AVP_PROP_WP_LINK_FLAGS] = ",".join(
                    str(lk.flags) for lk in wp.links)
            _apply_props(e, props)
            collection.objects.link(e)
            n += 1
    return n


def create_lights_from_lightset(lightset_data, base, scale, collection) -> int:
    """Parse one LIGHTSET payload and create one Blender light per STDLIGHT."""
    sub = parse_chunks(lightset_data, quiet=True)
    if sub is None:
        return 0
    n = 0
    for cid, cdata in sub:
        if cid != Chunk.STDLIGHT:
            continue
        p = parse_stdlight(cdata)
        if not p:
            continue
        vx, vy, vz = apply_axis(*p.location)
        spread = p.spread
        # Spread in (0, 360) means spot; 0 or >=360 means point.
        is_spot = 0 < spread < 360
        light_data = bpy.data.lights.new(f"{base}_light_{n:03d}",
                                         type='SPOT' if is_spot else 'POINT')
        light_data.energy = max(0.0, p.brightness / 65536.0) * 100.0
        r, g, b = p.colour
        light_data.color = (r / 255.0, g / 255.0, b / 255.0)
        light_data.cutoff_distance = p.range * scale if p.range > 0 else 10.0
        if is_spot:
            light_data.spot_size = math.radians(spread)
            light_data.spot_blend = 0.5
        lo = bpy.data.objects.new(f"{base}_light_{n:03d}", light_data)
        lo.location = (vx * scale, vy * scale, vz * scale)
        _apply_props(lo, {
            AVP_PROP_TYPE:       AVP_TYPE_LIGHT,
            AVP_PROP_BRIGHTNESS: p.brightness,
            AVP_PROP_SPREAD:     spread,
            AVP_PROP_RANGE:      p.range,
        })
        collection.objects.link(lo)
        n += 1
    return n