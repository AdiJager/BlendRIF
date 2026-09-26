# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Recursive RFFL unpacker. Walks nested archives, extracts ILBM/PNG.

`extract_all` is the entry point called from the bridge. It iterates
`*.ffl` in a directory (skipping Snd*.ffl when skip_snd=True), reads
each archive into memory, and calls `unpack_rffl_recursive`. Progress
is reported through an optional callback so the caller can log per
file without this module depending on the UI.

Non-RFFL archives (e.g. common.ffl, which wraps raw WAV files rather
than RFFL sub-archives) are reported with a note so the user knows
they were seen and skipped deliberately, not silently dropped.
"""

from __future__ import annotations

import os
from typing import Callable

from ..utils import log
from .rffl import parse_rffl
from .ilbm import (
    find_iff_start, parse_ilbm_at,
    decode_ilbm_body, ilbm_to_rgba,
    _MASK_TRANSPARENT,
)
from .png_writer import save_png


ProgressCb = Callable[[int, int, str], None]


def extract_all(ffl_dir: str, out_dir: str, *,
                skip_snd: bool = True,
                max_depth: int = 5,
                progress_cb: ProgressCb | None = None) -> dict:
    """Extract every .ffl under ffl_dir into out_dir; return stats."""
    files = sorted(
        f for f in os.listdir(ffl_dir) if f.lower().endswith(".ffl")
    )
    if skip_snd:
        files = [f for f in files if not f.lower().startswith("snd")]

    os.makedirs(out_dir, exist_ok=True)
    stats = {"archives": 0, "png": 0, "unknown": 0, "nested": 0}
    seen: set[int] = set()
    total = len(files)

    for i, fname in enumerate(files, 1):
        if progress_cb is not None:
            progress_cb(i, total, fname)
        fpath = os.path.join(ffl_dir, fname)
        try:
            with open(fpath, "rb") as f:
                data = f.read()
        except OSError as e:
            log.warning(f"FFL read failed: {fname}: {e}")
            continue

        sub = unpack_rffl_recursive(data, out_dir, depth=0,
                                    max_depth=max_depth, seen=seen)
        stats["archives"] += 1
        stats["png"] += sub["png"]
        stats["unknown"] += sub["unknown"]
        stats["nested"] += sub["rffl"]

        note = ""
        if sub["png"] == 0 and sub["unknown"] == 0 and sub["rffl"] == 0:
            note = " (not an RFFL archive - skipped)"
        log.info(f"  [{i}/{total}] {fname}: {sub['png']} PNG, "
                 f"{sub['unknown']} unknown, {sub['rffl']} nested "
                 f"RFFL{note}")

    return stats


def unpack_rffl_recursive(data: bytes, out_dir: str, *,
                          depth: int = 0,
                          max_depth: int = 5,
                          seen: set[int] | None = None) -> dict:
    """Unpack one RFFL buffer recursively; return per-call stats."""
    if seen is None:
        seen = set()
    if depth > max_depth:
        return {"png": 0, "unknown": 0, "rffl": 0}

    archive = parse_rffl(data)
    if archive is None:
        return {"png": 0, "unknown": 0, "rffl": 0}

    # Cheap cycle guard: (num_files, dir_len, data_size, first bytes).
    sig = hash((
        archive.num_files,
        archive.dir_len,
        len(data),
        data[:64],
    ))
    if sig in seen:
        return {"png": 0, "unknown": 0, "rffl": 0}
    seen.add(sig)

    stats = {"png": 0, "unknown": 0, "rffl": 0}
    data_start = archive.data_start

    for entry in archive.entries:
        off = data_start + entry.offset
        ln = entry.length
        if off + ln > len(data):
            continue
        raw = data[off:off + ln]

        if raw[:4] == b"RFFL":
            stats["rffl"] += 1
            rel = _safe_relpath(entry.name)
            sub_dir = os.path.join(out_dir, os.path.dirname(rel)) or out_dir
            sub = unpack_rffl_recursive(raw, sub_dir,
                                        depth=depth + 1,
                                        max_depth=max_depth, seen=seen)
            stats["png"] += sub["png"]
            stats["unknown"] += sub["unknown"]
            continue

        iff_off = find_iff_start(raw)
        if iff_off < 0:
            stats["unknown"] += 1
            continue

        ilbm = parse_ilbm_at(raw, iff_off)
        if ilbm is None:
            stats["unknown"] += 1
            continue

        bmhd = ilbm.bmhd
        rows = decode_ilbm_body(ilbm.body, bmhd)
        transp = (bmhd.transp_col
                  if bmhd.masking == _MASK_TRANSPARENT else None)
        rgba = ilbm_to_rgba(rows, ilbm.palette,
                            bmhd.width, bmhd.height,
                            transparent_index=transp)

        rel = _safe_relpath(entry.name)
        base = os.path.splitext(rel)[0]
        png_path = os.path.join(out_dir, base + ".png")
        if save_png(png_path, rgba, bmhd.width, bmhd.height):
            stats["png"] += 1
        else:
            stats["unknown"] += 1

    return stats


def _safe_relpath(name: str) -> str:
    """Normalise a stored path: forward slashes, no leading or '..'."""
    name = name.replace("\\", "/").lstrip("/")
    parts = [p for p in name.split("/") if p and p != ".."]
    return "/".join(parts) if parts else "unnamed"