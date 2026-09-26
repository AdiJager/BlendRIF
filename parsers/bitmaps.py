# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""BMPLSTST / MATCHIMG / CLRLOOKP parsers."""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field

from ..utils import log
from ._shared import read_cstr


BMP_HEADER_SIZE = 4
# Fixed part of a BMPLSTST record before the NUL-terminated name:
# flags(4) + index(4) + packed version/enum(4) + 8 bytes reserved.
BMP_RECORD_SIZE = 20


@dataclass
class BitmapEntry:
    name: str
    flags: int
    raw_name: str
    version: int
    enum_id: int


@dataclass
class ImageDescriptor:
    flags: int
    filename: str
    rifname: str
    fixrifname: str


@dataclass
class MatchImgRule:
    load: ImageDescriptor
    insteadof: ImageDescriptor


@dataclass
class MatchImg:
    flags: int
    rules: list[MatchImgRule] = field(default_factory=list)


@dataclass
class ClrLookp:
    flags: int
    filename: str
    table: list[int] = field(default_factory=list)


def parse_bitmap_list(data: bytes) -> dict[int, BitmapEntry]:
    """Parse a BMPLSTST payload; always returns a (possibly empty) dict."""
    result: dict[int, BitmapEntry] = {}
    if data is None or len(data) < BMP_HEADER_SIZE:
        return result
    try:
        count = struct.unpack_from("<I", data, 0)[0]
        pos = BMP_HEADER_SIZE
        for _ in range(count):
            if pos + BMP_RECORD_SIZE > len(data):
                break
            flags = struct.unpack_from("<I", data, pos)[0]
            index = struct.unpack_from("<I", data, pos + 4)[0]
            d1 = struct.unpack_from("<I", data, pos + 8)[0]
            version_num = d1 & 0x000fffff
            enum_id = (d1 >> 20) & 0xfff
            raw_name, pos = read_cstr(data, pos + BMP_RECORD_SIZE)
            base = os.path.splitext(
                os.path.basename(raw_name.replace('\\', '/')))[0]
            result[index] = BitmapEntry(name=base, flags=flags,
                                        raw_name=raw_name,
                                        version=version_num, enum_id=enum_id)
            # Each BMPLSTST record is 4-byte aligned.
            while pos % 4 != 0:
                pos += 1
    except (struct.error, IndexError) as e:
        log.warning(f"parse_bitmap_list: {type(e).__name__}: {e}")
    return result


def parse_image_descriptor(data: bytes, offset: int):
    """Parse one ImageDescriptor at offset; returns (descriptor, new_offset)."""
    if offset + 16 > len(data):
        return None, offset
    flags = struct.unpack_from("<i", data, offset)[0]
    offset += 16
    filename, offset = read_cstr(data, offset)
    rifname, offset = read_cstr(data, offset)
    fixrifname, offset = read_cstr(data, offset)
    return ImageDescriptor(flags=flags, filename=filename,
                           rifname=rifname, fixrifname=fixrifname), offset


def parse_matchimg(data: bytes) -> MatchImg | None:
    """Parse a MATCHIMG payload into a MatchImg, or None if malformed."""
    if len(data) < 16:
        return None
    try:
        flags = struct.unpack_from("<i", data, 8)[0]
        listsize = struct.unpack_from("<i", data, 12)[0]
        offset = 16
        rules: list[MatchImgRule] = []
        # Cap at 200 rules defensively - corrupt listsize would loop forever.
        for _ in range(min(listsize, 200)):
            if offset + 12 > len(data):
                break
            offset += 12
            load, offset = parse_image_descriptor(data, offset)
            insteadof, offset = parse_image_descriptor(data, offset)
            if load and insteadof:
                rules.append(MatchImgRule(load=load, insteadof=insteadof))
        return MatchImg(flags=flags, rules=rules)
    except (struct.error, IndexError) as e:
        log.warning(f"parse_matchimg: {type(e).__name__}: {e}")
        return None


def parse_clrlookp(data: bytes) -> ClrLookp | None:
    """Parse a CLRLOOKP payload into a ClrLookp, or None if malformed."""
    if len(data) < 4:
        return None
    try:
        flags = struct.unpack_from("<i", data, 0)[0]
        offset = 4 + 28
        if flags & 0x01:
            filename = data[offset:].split(b'\x00')[0].decode(
                'ascii', errors='ignore')
            return ClrLookp(flags=flags, filename=filename, table=[])
        table_len = 1 << 15
        table = list(data[offset:offset + table_len])
        return ClrLookp(flags=flags, filename="", table=table)
    except (struct.error, IndexError) as e:
        log.warning(f"parse_clrlookp: {type(e).__name__}: {e}")
        return None