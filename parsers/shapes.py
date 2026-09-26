# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""SHPHEAD1 / OBJHEAD1 / SHPEXTFL parsers."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from ..binary_reader import BinaryReader
from ..chunk_ids import Chunk
from ..chunks import parse_chunks
from ..utils import log
from .bitmaps import BitmapEntry, parse_bitmap_list


# Minimum payload sizes in bytes (parser bails below this).
SHPHEAD1_MIN_SIZE = 60
OBJHEAD1_MIN_SIZE = 60

# OBJHEAD1 field offsets (little-endian).
OBJHEAD_OFF_FLAGS   = 0     # int32 engine flags
OBJHEAD_OFF_POS     = 20    # int32 x3 world position
OBJHEAD_OFF_QUAT    = 32    # float x4 rotation quaternion
OBJHEAD_OFF_INDEX   = 48    # int32 index of this object
OBJHEAD_OFF_SHAPEID = 56    # int32 shape id (-1 for none)
OBJHEAD_OFF_NAME    = 60    # NUL-terminated ascii tag


@dataclass
class ShpHead:
    flags: int
    lock_user: str
    file_id_num: int
    num_verts: int
    num_polys: int
    radius: float
    version_no: int
    num_as_obj: int
    obj_names: list[str]
    tag: str


@dataclass
class ObjHead:
    flags: int
    pos: tuple[int, int, int]
    quat: tuple[float, float, float, float]
    index_num: int
    shape_id: int
    tag: str


@dataclass
class ShpExtFl:
    riff_name: str | None
    bitmaps: dict[int, BitmapEntry]


def parse_shphead1(data: bytes) -> ShpHead | None:
    """Parse a SHPHEAD1 payload into a ShpHead, or None if malformed."""
    if len(data) < SHPHEAD1_MIN_SIZE:
        return None
    try:
        r = BinaryReader(data)
        flags = r.i32()
        lock_user = (r.data[4:20]
                     .split(b'\x00')[0]
                     .decode('ascii', errors='ignore'))
        r.seek(20)
        file_id_num = r.i32()
        num_verts   = r.i32()
        num_polys   = r.i32()
        radius      = r.f32()
        r.seek(60)
        version_no  = r.i32() if r.remaining() >= 4 else 0
        num_as_obj  = r.i32() if r.remaining() >= 4 else 0
        obj_names: list[str] = []
        # Cap at 32 names defensively - a corrupt count could be huge.
        for _ in range(min(num_as_obj, 32)):
            if r.remaining() <= 0:
                break
            nm = r.strz()
            if nm:
                obj_names.append(nm)
        tag = obj_names[0] if obj_names else ""
        return ShpHead(flags=flags, lock_user=lock_user,
                       file_id_num=file_id_num, num_verts=num_verts,
                       num_polys=num_polys, radius=radius,
                       version_no=version_no, num_as_obj=num_as_obj,
                       obj_names=obj_names, tag=tag)
    except (struct.error, IndexError) as e:
        log.warning(f"parse_shphead1: {type(e).__name__}: {e}")
        return None


def parse_objhead1(data: bytes) -> ObjHead | None:
    """Parse an OBJHEAD1 payload into an ObjHead, or None if malformed."""
    if len(data) < OBJHEAD1_MIN_SIZE:
        return None
    try:
        r = BinaryReader(data)
        r.seek(OBJHEAD_OFF_FLAGS);   flags      = r.i32()
        r.seek(OBJHEAD_OFF_POS);     pos        = r.i32x3()
        r.seek(OBJHEAD_OFF_QUAT);    qx, qy, qz, qw = r.f32x4()
        r.seek(OBJHEAD_OFF_INDEX);   index_num  = r.i32()
        r.seek(OBJHEAD_OFF_SHAPEID); shape_id   = r.i32()
        r.seek(OBJHEAD_OFF_NAME);    name       = r.strz()

        # Normalize; a zero quaternion falls back to identity.
        n = math.sqrt(qx*qx + qy*qy + qz*qz + qw*qw)
        if n > 1e-10:
            qx, qy, qz, qw = qx/n, qy/n, qz/n, qw/n
        else:
            qx, qy, qz, qw = 0.0, 0.0, 0.0, 1.0

        return ObjHead(flags=flags, pos=pos, quat=(qx, qy, qz, qw),
                       index_num=index_num, shape_id=shape_id, tag=name)
    except (struct.error, IndexError) as e:
        log.warning(f"parse_objhead1: {type(e).__name__}: {e}")
        return None


def parse_shpextfl(ext_fl_payload: bytes) -> ShpExtFl:
    """Parse a SHPEXTFL payload into a ShpExtFl (never None, may be empty)."""
    result = ShpExtFl(riff_name=None, bitmaps={})
    sub = parse_chunks(ext_fl_payload, quiet=True)
    if sub is None:
        return result
    for cid, cdata in sub:
        if cid == Chunk.RIFFNAME:
            result.riff_name = cdata.split(b'\x00')[0].decode(
                'ascii', errors='replace')
        elif cid == Chunk.BMPLSTST:
            parsed = parse_bitmap_list(cdata)
            if parsed:
                result.bitmaps.update(parsed)
    return result