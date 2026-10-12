# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""DUMOBJ / PLACHIDT / AVPGENER / SOUNDOB2 / AVPSTART / CAMORIGN / AVPPATH2 parsers.

AVPPATH2 is the AI patrol-path system that replaced the ground half of
the waypoint data. A path is an ordered list of AI *modules*; the game
resolves the geometry at runtime from each module's world position, so
the importer does the same (see empties.create_path_curves).
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

from ..binary_reader import BinaryReader
from ..utils import log


# Minimum payload sizes in bytes (parser bails below this).
DUMOBJDT_MIN_SIZE = 56
SOUNDOB2_MIN_SIZE = 40
AVPGENER_MIN_SIZE = 28
AVPSTART_MIN_SIZE = 56
CAMORIGN_MIN_SIZE = 60

# Field offsets within their payloads.
SOUNDOB_OFF_NAMES   = 40    # NUL-terminated sound name starts here
AVPGEN_OFF_NAME     = 28    # NUL-terminated generator name starts here
AVPSTART_OFF_MATRIX = 12    # int32 x9 rotation matrix
AVPSTART_OFF_MODULE = 48    # int32 x2 module id
CAMORIGN_OFF_MATRIX = 24    # int32 x9 rotation matrix

# Each AVPPATH2 point: module(4) + loc(12) + flags(4) + pad(4) = 24 bytes.
PATH_POINT_SIZE = 24

# Sanity cap on the declared point count. The longest shipped path has
# 80 points; a corrupt count must not make the parser loop forever.
MAX_PATH_POINTS = 4096

# Path flags (PathChnk.hpp). LoopPath makes the game walk straight back
# to the first module; BackAndForth mirrors the module list before
# walking it. The path point's own `loc` field is legacy: every one of
# the 1098 points in the retail levels stores (0, 0, 0) there and the
# game tracks patrols by module, not by coordinate (see Projload.cpp
# setup_paths / bh_ais.c modules_in_path).
PATH_FLAG_LOOP          = 0x00000001   # PathFlag_LoopPath
PATH_FLAG_BACK_AND_FORTH = 0x00000002  # PathFlag_BackAndForth
PATH_POINT_FLAG_INTERPOLATED = 0x00000001  # PathPointFlag_InterpolatedPoint
PATH_POINT_FLAG_LOCATION_VALID = 0x00000002  # PathPointFlag_LocationValid


@dataclass
class DumObj:
    name: str
    location: tuple[int, int, int]
    orientation: tuple[float, float, float, float]
    min_extents: tuple[int, int, int]
    max_extents: tuple[int, int, int]


@dataclass
class PlachId:
    name: str
    hierarchy_index: int
    location: tuple[int, int, int]
    orientation: tuple[float, float, float, float]
    id: tuple[int, int]
    num_extra: int


@dataclass
class AvpGener:
    location: tuple[int, int, int]
    orientation: int
    type: int
    flags: int
    texid: int
    subtype: int
    name: str


@dataclass
class SoundOb2:
    position: tuple[int, int, int]
    inner: int
    outer: int
    max_volume: int
    pitch: int
    flags: int
    probability: int
    snd_name: str
    wav_name: str


@dataclass
class AvpStart:
    location: tuple[int, int, int]
    matrix: tuple[int, ...]
    module_id: tuple[int, int]


@dataclass
class CamOrign:
    location: tuple[float, float, float]
    matrix: tuple[int, ...]


@dataclass
class PathPoint:
    """One step of a patrol path: an AI module, not a coordinate.

    `loc` is the legacy per-point position. It is (0, 0, 0) in all 1098
    points of the retail levels, so callers should place the point at
    the referenced module's world position (OBJHEAD1 with this
    `module` as its index_num).
    """
    module: int
    loc: tuple[int, int, int]
    flags: int


@dataclass
class AvpPath2:
    name: str
    id: int
    flags: int
    points: list[PathPoint] = field(default_factory=list)
    path_length: int = 0


def _normalize_quat(qx, qy, qz, qw):
    """Normalize a quaternion; falls back to identity on zero length."""
    n = math.sqrt(qx*qx + qy*qy + qz*qz + qw*qw)
    if n > 1e-10:
        return qx/n, qy/n, qz/n, qw/n
    return 0.0, 0.0, 0.0, 1.0


def parse_dumobjdt(data: bytes) -> DumObj | None:
    """Parse a DUMOBJDT payload into a DumObj, or None if malformed."""
    if len(data) < DUMOBJDT_MIN_SIZE:
        return None
    try:
        r = BinaryReader(data)
        name = r.strz()
        r.align4()
        loc = r.i32x3()
        qx, qy, qz, qw = r.f32x4()
        min_ext = r.i32x3()
        max_ext = r.i32x3()
        qx, qy, qz, qw = _normalize_quat(qx, qy, qz, qw)
        return DumObj(name=name, location=loc, orientation=(qx, qy, qz, qw),
                      min_extents=min_ext, max_extents=max_ext)
    except (struct.error, IndexError) as e:
        log.warning(f"parse_dumobjdt: {type(e).__name__}: {e}")
        return None


def parse_dumobjtx(data: bytes) -> str:
    """Extract the text field of a DUMOBJTX payload."""
    return data.split(b'\x00')[0].decode('ascii', errors='ignore')


def parse_plachidt(data: bytes) -> PlachId | None:
    """Parse a PLACHIDT payload into a PlachId, or None if malformed."""
    if len(data) < 4:
        return None
    try:
        r = BinaryReader(data)
        name = r.strz()
        if not name:
            return None
        r.align4()
        hier_index = r.i32()
        loc = r.i32x3()
        qx, qy, qz, qw = r.f32x4()
        obj_id1 = r.i32()
        obj_id2 = r.i32()
        n_extra = r.i32()
        qx, qy, qz, qw = _normalize_quat(qx, qy, qz, qw)
        return PlachId(name=name, hierarchy_index=hier_index,
                       location=loc, orientation=(qx, qy, qz, qw),
                       id=(obj_id1, obj_id2), num_extra=n_extra)
    except (struct.error, IndexError) as e:
        log.warning(f"parse_plachidt: {type(e).__name__}: {e}")
        return None


def parse_avpgener(data: bytes) -> AvpGener | None:
    """Parse an AVPGENER payload into an AvpGener, or None if malformed."""
    if len(data) < AVPGENER_MIN_SIZE:
        return None
    try:
        r = BinaryReader(data)
        loc = r.i32x3()
        orient = r.i32()
        gtype = r.i32()
        flags = r.i32()
        texid = r.data[r.pos]; r.pos += 1
        subtype = r.data[r.pos]; r.pos += 1
        r.seek(AVPGEN_OFF_NAME)
        name = r.strz()
        return AvpGener(location=loc, orientation=orient, type=gtype,
                        flags=flags, texid=texid, subtype=subtype, name=name)
    except (struct.error, IndexError) as e:
        log.warning(f"parse_avpgener: {type(e).__name__}: {e}")
        return None


def parse_soundob2(data: bytes) -> SoundOb2 | None:
    """Parse a SOUNDOB2 payload into a SoundOb2, or None if malformed."""
    if len(data) < SOUNDOB2_MIN_SIZE:
        return None
    try:
        r = BinaryReader(data)
        pos_ = r.i32x3()
        inner = r.i32()
        outer = r.i32()
        max_vol = r.i32()
        pitch = r.i32()
        flags = r.i32()
        probability = r.i32()
        r.seek(SOUNDOB_OFF_NAMES)
        snd_name = r.strz()
        r.align4()
        wav_name = r.strz() if r.remaining() > 0 else ""
        return SoundOb2(position=pos_, inner=inner, outer=outer,
                        max_volume=max_vol, pitch=pitch, flags=flags,
                        probability=probability, snd_name=snd_name,
                        wav_name=wav_name)
    except (struct.error, IndexError) as e:
        log.warning(f"parse_soundob2: {type(e).__name__}: {e}")
        return None


def parse_avpstart(data: bytes) -> AvpStart | None:
    """Parse an AVPSTART payload into an AvpStart, or None if malformed."""
    if len(data) < AVPSTART_MIN_SIZE:
        return None
    try:
        r = BinaryReader(data)
        loc = r.i32x3()
        r.seek(AVPSTART_OFF_MATRIX)
        mat = r.i32x9()
        r.seek(AVPSTART_OFF_MODULE)
        module_id = (r.i32(), r.i32())
        return AvpStart(location=loc, matrix=mat, module_id=module_id)
    except (struct.error, IndexError) as e:
        log.warning(f"parse_avpstart: {type(e).__name__}: {e}")
        return None


def parse_camorign(data: bytes) -> CamOrign | None:
    """Parse a CAMORIGN payload into a CamOrign, or None if malformed."""
    if len(data) < CAMORIGN_MIN_SIZE:
        return None
    try:
        r = BinaryReader(data)
        loc = r.f64x3()
        r.seek(CAMORIGN_OFF_MATRIX)
        mat = r.i32x9()
        return CamOrign(location=loc, matrix=mat)
    except (struct.error, IndexError) as e:
        log.warning(f"parse_camorign: {type(e).__name__}: {e}")
        return None


def parse_avppath2(data: bytes) -> AvpPath2 | None:
    """Parse an AVPPATH2 payload into an AvpPath2, or None if malformed.

    An empty path name is legal: one retail path (a 9-point patrol in
    Nost03.RIF) is stored with a zeroed name field, so it is parsed and
    named by the caller instead of being dropped.
    """
    if len(data) < 4:
        return None
    try:
        r = BinaryReader(data)
        name = r.strz()
        r.align4()
        path_id = r.i32()
        flags = r.i32()
        r.i32()                       # spare2 - unused
        path_length = r.i32()
        if path_length < 0 or path_length > MAX_PATH_POINTS:
            log.warning(f"parse_avppath2: implausible point count {path_length}")
            return None
        points: list[PathPoint] = []
        for _ in range(path_length):
            if r.remaining() < PATH_POINT_SIZE:
                # The header promises more points than the payload holds.
                log.warning(f"parse_avppath2: truncated after "
                            f"{len(points)}/{path_length} point(s)")
                return None
            module_idx = r.i32()
            loc = r.i32x3()
            pflags = r.i32()
            r.skip(4)                 # trailing padding
            points.append(PathPoint(module=module_idx, loc=loc, flags=pflags))
        return AvpPath2(name=name, id=path_id, flags=flags,
                        points=points, path_length=path_length)
    except (struct.error, IndexError) as e:
        log.warning(f"parse_avppath2: {type(e).__name__}: {e}")
        return None