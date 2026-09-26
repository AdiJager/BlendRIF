# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Low-level chunk stream parsing and typed ShapeGroup / ObjectGroup views.

parse_chunks splits a byte stream into (id, payload) tuples, tolerating
a small amount of garbage between chunks. walk_chunks recursively
descends into nested chunks until a caller-supplied stop condition
matches, then groups the sibling chunks of each match. collect_rebshape
and collect_rbobject wrap walk_chunks into typed dataclasses so
downstream code does not have to juggle dicts of raw chunk payloads.

parse_chunks returns None (not []) for input that is entirely garbage,
unless at least one valid chunk was parsed first.

Chunk-size validation returns None on a bad size; diagnostics go
through log.debug rather than log.warning because walk_chunks and
find_all_chunks recurse into arbitrary nested payloads - shape data
can contain ASCII fragment names followed by non-chunk bytes, so
false-positive IDs with bogus sizes are expected during normal
parsing. Logging them at INFO would flood the console for every
import. Users who need to see them can enable the importer's
diagnostics mode, which raises the log level to DEBUG.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable

from .chunk_ids import Chunk
from .utils import log


# ---------------------------------------------------------------------------
# Typed views of one REBSHAPE / RBOBJECT
# ---------------------------------------------------------------------------

@dataclass
class ShapeGroup:
    """Raw payloads of the chunks that make up one RIF shape."""
    head: bytes | None = None       # SHPHEAD1
    raw_verts: bytes | None = None  # SHPRAWVT
    polys: bytes | None = None      # SHPPOLYS
    uvcrds: bytes | None = None     # SHPUVCRD
    ext_fl: bytes | None = None     # SHPEXTFL


@dataclass
class ObjectGroup:
    """Raw payloads of the chunks that make up one RBOBJECT."""
    head: bytes | None = None       # OBJHEAD1


def _first(lst: list[bytes] | None) -> bytes | None:
    """Return lst[0] or None - helper for the walker's grouped output."""
    return lst[0] if lst else None


# ---------------------------------------------------------------------------
# Chunk stream
# ---------------------------------------------------------------------------

def _is_valid_chunk_id(cid_bytes: bytes) -> bool:
    """True if the 8-byte ID field looks like a plausible chunk identifier."""
    cid = cid_bytes.split(b'\x00')[0]
    if len(cid) < 2 or len(cid) > 8:
        return False
    for b in cid:
        if not ((0x30 <= b <= 0x39) or (0x41 <= b <= 0x5A) or
                (0x61 <= b <= 0x7A) or b == 0x5F):
            return False
    return True


def parse_chunks(data: bytes, allow_trailing: int = 64,
                 resync_max: int = 64, quiet: bool = False):
    """Parse a chunk stream into a list of (id, payload) tuples or None."""
    if not data:
        return []

    chunks = []
    pos = 0
    while pos + 12 <= len(data):
        cid_bytes = data[pos:pos + 8]
        if not _is_valid_chunk_id(cid_bytes):
            # Scan forward a bounded distance to find the next real chunk.
            resynced = False
            max_skip = min(resync_max, len(data) - pos - 12)
            for skip in range(1, max_skip + 1):
                np = pos + skip
                if not _is_valid_chunk_id(data[np:np + 8]):
                    continue
                nsize = struct.unpack_from("<i", data, np + 8)[0]
                if nsize < 12 or np + nsize > len(data):
                    continue
                if not quiet:
                    log.info(f"    parse_chunks: resynced at offset {np} "
                             f"(skipped {skip} byte(s))")
                pos = np
                resynced = True
                break
            if not resynced:
                # Trailing garbage is only tolerable *after* a valid chunk.
                if chunks and allow_trailing > 0 and \
                        0 < len(data) - pos <= allow_trailing:
                    if not quiet:
                        log.info(f"    parse_chunks: {len(data) - pos} trailing "
                                 f"byte(s) ignored at offset {pos}")
                    return chunks
                return None

        cid = cid_bytes.split(b'\x00')[0].decode('ascii', errors='ignore')
        size = struct.unpack_from("<i", data, pos + 8)[0]
        # Two failure modes: a size below the 12-byte header, or a
        # size pointing past the end of the stream. Return None (the
        # caller decides whether the surrounding parse is
        # salvageable) and surface the reason only at DEBUG -
        # false-positive IDs from walk_chunks / find_all_chunks
        # recursion are expected during normal imports, so logging
        # these at WARNING would flood the console. Enable
        # diagnostics_mode to see them.
        if size < 12:
            log.debug(f"    parse_chunks: chunk {cid!r} at offset {pos} "
                      f"has invalid size {size} (< 12)")
            return None
        if pos + size > len(data):
            log.debug(f"    parse_chunks: chunk {cid!r} at offset {pos} "
                      f"size {size} exceeds stream "
                      f"({len(data) - pos} B left)")
            return None
        chunks.append((cid, data[pos + 12:pos + size]))
        pos += size

    if pos == len(data):
        return chunks
    if chunks and allow_trailing > 0 and 0 < len(data) - pos <= allow_trailing:
        if not quiet:
            log.info(f"    parse_chunks: {len(data) - pos} trailing byte(s) "
                     f"ignored at offset {pos}")
        return chunks
    return None


def find_all_chunks(data, target, max_depth=10, depth=0, results=None,
                    quiet=False, resync_max=64):
    """Recursively collect the payloads of every chunk with the given id."""
    if results is None:
        results = []
    if depth > max_depth:
        return results
    chunks = parse_chunks(data, quiet=(quiet or depth > 0),
                          resync_max=resync_max)
    if chunks is None:
        return results
    for cid, cdata in chunks:
        if cid == target:
            results.append(cdata)
        find_all_chunks(cdata, target, max_depth, depth + 1, results,
                        quiet=True, resync_max=resync_max)
    return results


def walk_chunks(blob: bytes,
                stop_when: Callable[[set[str]], bool],
                max_depth: int = 8,
                resync_max: int = 64):
    """Descend into nested chunks; group siblings wherever stop_when matches."""
    found: list[dict[str, list[bytes]]] = []

    def _walk(data: bytes, depth: int) -> None:
        if depth > max_depth:
            return
        chunks = parse_chunks(data, quiet=True, resync_max=resync_max)
        if chunks is None:
            return
        ids = {c[0] for c in chunks}
        if stop_when(ids):
            grp: dict[str, list[bytes]] = {}
            for cid, cdata in chunks:
                grp.setdefault(cid, []).append(cdata)
            found.append(grp)
            return
        for _, cdata in chunks:
            _walk(cdata, depth + 1)

    _walk(blob, 0)
    return found


# ---------------------------------------------------------------------------
# Typed collectors
# ---------------------------------------------------------------------------

def collect_rebshape(decoded: bytes,
                     resync_max: int = 64) -> list[ShapeGroup]:
    """Return every REBSHAPE in `decoded` as a typed ShapeGroup."""
    raw_groups = walk_chunks(
        decoded,
        lambda ids: Chunk.SHPRAWVT in ids or Chunk.SHPHEAD1 in ids,
        resync_max=resync_max)
    return [
        ShapeGroup(
            head=_first(g.get(Chunk.SHPHEAD1)),
            raw_verts=_first(g.get(Chunk.SHPRAWVT)),
            polys=_first(g.get(Chunk.SHPPOLYS)),
            uvcrds=_first(g.get(Chunk.SHPUVCRD)),
            ext_fl=_first(g.get(Chunk.SHPEXTFL)),
        )
        for g in raw_groups
    ]


def collect_rbobject(decoded: bytes,
                     resync_max: int = 64) -> list[ObjectGroup]:
    """Return every RBOBJECT in `decoded` as a typed ObjectGroup."""
    raw_groups = walk_chunks(decoded,
                             lambda ids: Chunk.OBJHEAD1 in ids,
                             resync_max=resync_max)
    return [ObjectGroup(head=_first(g.get(Chunk.OBJHEAD1)))
            for g in raw_groups]