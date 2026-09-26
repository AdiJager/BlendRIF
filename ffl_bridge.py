# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Bridge between the RIF importer and the ffl_extractor package.

Called from operator.execute() before discover_paths(). Decides
whether to extract textures from fastfile/*.ffl into the conventional
fastfile/_ffl_unpacked/ directory, using the same upward search
pattern as discovery.py (base + up to 4 parents).

Never raises. On any failure, returns a 'failed' result and lets the
import continue without materials. Extraction runs only once:
if _ffl_unpacked/ already contains at least one PNG, it is reused.

Snd*.ffl archives (sound-only, no ILBM bitmaps) are skipped, matching
the behaviour of the standalone texture importer. The archive count
reported in the log therefore reflects only the archives that were
actually processed, not every .ffl on disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from .utils import log

_LEVELS_UP = 4


@dataclass(frozen=True)
class FflExtractResult:
    """Outcome of ensure_textures()."""
    status: str          # disabled | cached | extracted | no-ffl | failed
    textures_dir: str | None
    png_count: int
    message: str


def ensure_textures(rif_path: str, *,
                    enabled: bool,
                    materials: bool,
                    progress_cb: Callable[[int, int, str], None] | None = None
                    ) -> FflExtractResult:
    """Ensure fastfile/_ffl_unpacked/ exists; return what happened."""
    if not enabled:
        return FflExtractResult("disabled", None, 0, "extract_ffl is off")
    if not materials:
        return FflExtractResult("disabled", None, 0,
                                "Import Materials is off")

    base = os.path.dirname(os.path.abspath(rif_path))

    cached = _first_dir_with_png(
        _candidates(base, ("fastfile", "_ffl_unpacked")))
    if cached is not None:
        n = _count_png(cached)
        return FflExtractResult("cached", cached, n,
                                f"using {n} cached PNG")

    fastfile = _first_existing_dir(_candidates(base, ("fastfile",)))
    if fastfile is None:
        return FflExtractResult("no-ffl", None, 0,
                                "no fastfile/ directory found near RIF")

    all_ffl = _list_ffl(fastfile)
    if not all_ffl:
        return FflExtractResult("no-ffl", None, 0,
                                "fastfile/ has no .ffl archives")
    ffl_files = [f for f in all_ffl if not f.lower().startswith("snd")]
    skipped = len(all_ffl) - len(ffl_files)
    if not ffl_files:
        return FflExtractResult("no-ffl", None, 0,
                                "fastfile/ has no non-Snd .ffl archives")

    out_dir = os.path.join(fastfile, "_ffl_unpacked")
    log.info(f"FFL extract: {len(ffl_files)} archive(s) in {fastfile}"
             + (f" ({skipped} Snd*.ffl skipped)" if skipped else ""))
    log.info(f"FFL extract: writing to {out_dir}")

    try:
        from .ffl_extractor import extract_all
        stats = extract_all(fastfile, out_dir, progress_cb=progress_cb)
    except Exception as e:                                  # noqa: BLE001
        log.error(f"FFL extract failed: {e}")
        return FflExtractResult("failed", None, 0, str(e))

    n = stats["png"]
    msg = (f"extracted {n} PNG from {stats['archives']} archive(s) "
           f"({stats['unknown']} unknown, {stats['nested']} nested RFFL)")
    if n == 0:
        return FflExtractResult("no-ffl", out_dir, 0, msg)
    return FflExtractResult("extracted", out_dir, n, msg)


# --- helpers ---------------------------------------------------------------

def _candidates(base: str, subparts: tuple[str, ...]):
    """Yield base/subparts, parent/subparts, ... up to _LEVELS_UP."""
    cur = base
    for _ in range(_LEVELS_UP + 1):
        yield os.path.join(cur, *subparts)
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent


def _first_existing_dir(paths) -> str | None:
    for p in paths:
        if os.path.isdir(p):
            return p
    return None


def _first_dir_with_png(paths) -> str | None:
    for p in paths:
        if os.path.isdir(p) and _count_png(p, limit=1) > 0:
            return p
    return None


def _count_png(root: str, limit: int | None = None) -> int:
    n = 0
    for _dirpath, _dirnames, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".png"):
                n += 1
                if limit is not None and n >= limit:
                    return n
    return n


def _list_ffl(root: str) -> list[str]:
    try:
        return [f for f in os.listdir(root)
                if f.lower().endswith(".ffl")]
    except OSError:
        return []