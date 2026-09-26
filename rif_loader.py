# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Top-level RIF loading and external RIF resolution.

load_rif_auto turns a raw buffer into the decompressed chunk stream.
build_rif_index pre-scans a set of directories so a RIF with many
SHPEXTFL references does not re-scan the disk per shape. load_ext_rif
uses that index to resolve a SHPEXTFL target and caches the result.

build_rif_index walks recursively (os.walk) instead of a flat
os.listdir, matching build_tex_index in materials.py - AvP ships
shape_rifs/ flat in the retail data, but mods and the avp_rifs/ tree
use category subfolders (weapons/, characters/, items/...) that a flat
listing misses. load_ext_rif caches by name only; want_tag never
affected what was loaded, only which shape pick_ext_shape selects
later, and the (name, want_tag) key caused redundant disk+Huffman work
for the same RIF. Cache misses log the closest basenames via difflib
so adding a RIF_ALIASES entry is a copy-paste from the log.
"""

from __future__ import annotations

import difflib
import os

from .huffman import decompress_rif
from .chunks import parse_chunks, find_all_chunks, collect_rebshape, ShapeGroup
from .chunk_ids import Chunk, RIF_MAGIC, INFF_MAGIC
from .parsers.bitmaps import parse_bitmap_list
from .parsers.shapes import parse_shphead1
from .utils import log
from .config import RIF_ALIASES


def load_rif_auto(raw: bytes, verbose: bool = False) -> bytes | None:
    """Decompress a RIF buffer; returns the decoded chunk stream or None."""
    if len(raw) < 12:
        return None
    if raw.startswith(RIF_MAGIC):
        if verbose:
            log.info("    Format: REBCRIF1")
        try:
            dec = decompress_rif(raw)
        except ValueError as e:
            log.error(f"    Huffman error: {e}")
            return None
        if dec is None or len(dec) < 12:
            log.warning("    decompressed stream is empty "
                        f"({0 if dec is None else len(dec)} bytes)")
            return None
        if parse_chunks(dec) is None:
            log.warning("    top-level chunk stream did not parse cleanly.")
        return dec
    elif raw.startswith(INFF_MAGIC):
        if verbose:
            log.info("    Format: REBINFF2")
        return raw
    else:
        # Allow a REBINFF2 payload to be embedded at some offset.
        idx = raw.find(INFF_MAGIC)
        if idx >= 0:
            if verbose:
                log.info(f"    Format: REBINFF2 @ {idx}")
            return raw[idx:]
        return None


def build_rif_index(dirs: list[str]) -> dict[str, str]:
    """Return a lowercase basename -> absolute path index of .rif files."""
    # Walks each directory recursively. On basename collision the first
    # file found wins (os.walk is top-down and dirs/files are sorted
    # for deterministic ordering).
    idx: dict[str, str] = {}
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for root, subdirs, files in os.walk(d):
            # Sort in place for a deterministic, alphabetical walk order.
            subdirs.sort()
            for f in sorted(files):
                if not f.lower().endswith('.rif'):
                    continue
                key = os.path.splitext(f)[0].lower()
                # First write wins so a duplicate in a later dir does
                # not shadow the canonical location.
                idx.setdefault(key, os.path.join(root, f))
    return idx


def _expand_aliases(name: str) -> list[str]:
    """Return [name] plus any RIF_ALIASES entries for it, all lowercase."""
    target = name.lower()
    cands = [target]
    for k, aliases in RIF_ALIASES.items():
        if k.lower() == target:
            cands.extend(a.lower() for a in aliases)
            break
    return cands


def _suggest_close_keys(name: str, rif_index: dict, n: int = 5) -> list[str]:
    """Return up to n close basename matches for a miss, for diagnostics."""
    try:
        return difflib.get_close_matches(name.lower(), rif_index.keys(),
                                         n=n, cutoff=0.5)
    except Exception:
        return []


def load_ext_rif(name: str, rif_index: dict, cache: dict,
                 want_tag: str | None = None) -> tuple[dict | None, str]:
    """Load an external RIF via the index; returns (result, reason)."""
    # want_tag is kept for call-site compatibility; it only influences
    # which shape pick_ext_shape selects after this function returns,
    # so it is deliberately not part of the cache key.
    if not name:
        return None, "empty external RIF name"
    if not rif_index:
        return None, f"no RIF index available (looking for '{name}')"

    key = name.lower()
    if key in cache:
        cached = cache[key]
        if cached is None:
            return None, f"external RIF not found: {name}"
        return cached, ""

    path = None
    tried = _expand_aliases(name)
    for cand in tried:
        hit = rif_index.get(cand)
        if hit:
            path = hit
            break

    if path is None:
        # On a miss, log the tried names + closest basenames so a new
        # RIF_ALIASES entry can be copy-pasted straight from the log.
        near = _suggest_close_keys(name, rif_index)
        extra = f" (closest: {', '.join(near)})" if near else ""
        log.info(f"    [EXT] miss '{name}': tried={tried}{extra}")
        cache[key] = None
        return None, f"external RIF not found: {name}{extra}"

    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except OSError as e:
        cache[key] = None
        return None, f"cannot read external RIF {path}: {e}"

    dec = load_rif_auto(raw)
    if dec is None:
        cache[key] = None
        return None, f"unrecognized format in {path}"

    shapes = collect_rebshape(dec)
    if not shapes:
        cache[key] = None
        return None, f"no shapes in {path}"

    all_bmp = find_all_chunks(dec, Chunk.BMPNAMES, max_depth=8)
    bmp: dict = {}
    for bd in all_bmp:
        bmp.update(parse_bitmap_list(bd))

    r = {"shapes": shapes, "bitmaps": bmp, "path": path}
    cache[key] = r
    return r, ""


def count_verts(shape: ShapeGroup) -> int:
    """Number of vertices in a ShapeGroup, or 0 if there is no SHPRAWVT."""
    if shape.raw_verts is None:
        return 0
    return len(shape.raw_verts) // 12


def pick_ext_shape(ext, tag: str | None) -> ShapeGroup | None:
    """Pick a shape from an external RIF by tag, else the largest one."""
    if not ext or not ext["shapes"]:
        return None
    if tag:
        for s in ext["shapes"]:
            h = parse_shphead1(s.head) if s.head else None
            if h and h.tag == tag:
                return s
    best = None
    bc = 0
    for s in ext["shapes"]:
        c = count_verts(s)
        if c > bc:
            best = s
            bc = c
    return best