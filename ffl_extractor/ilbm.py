# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""IFF/ILBM decoder for AvP textures inside RFFL archives.

All chunk IDs and numeric fields are big-endian (per iff.hpp
ArchvIn::Transfer). Chunks live inside FORM....ILBM; BODY may be
ByteRun1-compressed when bmhd.compression == 1. Odd-size chunks are
followed by a single pad byte (also per iff.cpp Chunk::Write/Load).
Palette is the CMAP chunk (3 bytes per entry, RGB 0..255).
"""

from __future__ import annotations

from dataclasses import dataclass
import struct

_BMHD_SIZE = 20
_COMPRESS_NONE = 0
_COMPRESS_BYTERUN1 = 1
_MASK_TRANSPARENT = 2


@dataclass(frozen=True)
class BmhdInfo:
    """Header of an ILBM bitmap."""
    width: int
    height: int
    n_planes: int
    masking: int
    compression: int
    transp_col: int


@dataclass(frozen=True)
class IlbmImage:
    """A parsed ILBM image: header, palette, raw BODY bytes."""
    bmhd: BmhdInfo
    palette: tuple[tuple[int, int, int], ...]
    body: bytes


def find_iff_start(data: bytes) -> int:
    """Return the byte offset of the first FORM....ILBM, or -1."""
    idx = 0
    while True:
        idx = data.find(b"FORM", idx)
        if idx < 0:
            return -1
        if idx + 12 <= len(data) and data[idx + 8:idx + 12] == b"ILBM":
            return idx
        idx += 1


def parse_bmhd(chunk: bytes) -> BmhdInfo | None:
    """Parse a BMHD chunk payload (20 bytes) into BmhdInfo."""
    if len(chunk) < _BMHD_SIZE:
        return None
    return BmhdInfo(
        width=struct.unpack_from(">H", chunk, 0)[0],
        height=struct.unpack_from(">H", chunk, 2)[0],
        n_planes=chunk[8],
        masking=chunk[9],
        compression=chunk[10],
        transp_col=struct.unpack_from(">H", chunk, 12)[0],
    )


def parse_cmap(chunk: bytes) -> tuple[tuple[int, int, int], ...]:
    """Parse a CMAP chunk into a tuple of RGB triples."""
    n = len(chunk) // 3
    return tuple(
        (chunk[i * 3], chunk[i * 3 + 1], chunk[i * 3 + 2])
        for i in range(n)
    )


def decode_byterun1(src: bytes, dst_size: int) -> bytes:
    """Decode a ByteRun1 (PackBits) stream into exactly dst_size bytes."""
    out = bytearray()
    pos = 0
    n = len(src)
    while pos < n and len(out) < dst_size:
        b = src[pos]
        pos += 1
        if b <= 127:
            count = b + 1
            out.extend(src[pos:pos + count])
            pos += count
        elif b == 128:
            continue
        else:
            count = 257 - b
            if pos < n:
                out.extend([src[pos]] * count)
                pos += 1
    return bytes(out[:dst_size])


def decode_ilbm_body(body: bytes, bmhd: BmhdInfo) -> list[list[int]]:
    """Decode BODY into per-row lists of palette indices."""
    w, h = bmhd.width, bmhd.height
    nplanes = bmhd.n_planes
    row_bytes = (w + 7) // 8
    plane_row = row_bytes * nplanes
    total = plane_row * h
    if bmhd.compression == _COMPRESS_BYTERUN1:
        decoded = decode_byterun1(body, total)
    else:
        decoded = body[:total]

    rows: list[list[int]] = []
    pos = 0
    for _ in range(h):
        row_planes = decoded[pos:pos + plane_row]
        pos += plane_row
        indices = [0] * w
        for x in range(w):
            byte_idx = x // 8
            bit_idx = 7 - (x % 8)
            val = 0
            for p in range(nplanes):
                byte = row_planes[p * row_bytes + byte_idx]
                bit = (byte >> bit_idx) & 1
                val |= bit << p
            indices[x] = val
        rows.append(indices)
    return rows


def ilbm_to_rgba(rows: list[list[int]],
                 palette: tuple[tuple[int, int, int], ...],
                 width: int, height: int,
                 transparent_index: int | None = None) -> bytes:
    """Flatten palette-indexed rows into top-down RGBA bytes."""
    out = bytearray()
    npal = len(palette)
    for y in range(height):
        row = rows[y]
        for x in range(width):
            idx = row[x]
            if idx < npal:
                r, g, b = palette[idx]
            else:
                r, g, b = 0, 0, 0
            a = 0 if (transparent_index is not None
                      and idx == transparent_index) else 255
            out.extend((r, g, b, a))
    return bytes(out)


def parse_ilbm_at(data: bytes, offset: int) -> IlbmImage | None:
    """Parse FORM....ILBM starting at offset; None on any error."""
    if offset < 0 or offset + 12 > len(data):
        return None
    if data[offset:offset + 4] != b"FORM":
        return None
    if data[offset + 8:offset + 12] != b"ILBM":
        return None

    bmhd: BmhdInfo | None = None
    cmap: tuple[tuple[int, int, int], ...] = ()
    body: bytes | None = None

    pos = offset + 12
    form_size = struct.unpack_from(">I", data, offset + 4)[0]
    end = min(offset + 8 + form_size, len(data))
    while pos + 8 <= end:
        cid = data[pos:pos + 4]
        size = struct.unpack_from(">I", data, pos + 4)[0]
        if pos + 8 + size > end:
            break
        chunk = data[pos + 8:pos + 8 + size]
        if cid == b"BMHD":
            bmhd = parse_bmhd(chunk)
        elif cid == b"CMAP":
            cmap = parse_cmap(chunk)
        elif cid == b"BODY":
            body = chunk
        pos += 8 + size
        if size & 1:
            pos += 1

    if bmhd is None or body is None:
        return None
    return IlbmImage(bmhd=bmhd, palette=cmap, body=body)