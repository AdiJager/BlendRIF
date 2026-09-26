# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Locate shape_rifs/ and fastfile/_ffl_unpacked/ relative to a selected RIF.

The two directories live either next to the selected RIF or up to
_LEVELS_UP levels above it; the first existing candidate per subpath
wins. A fallback also checks <textures_root_parent>/shape_rifs to
cover RIFs that live deep inside fastfile/_ffl_unpacked/<level>/...
"""

from __future__ import annotations

import os
from dataclasses import dataclass


# Base directory + 4 parents -> 5 candidates per subpath.
_LEVELS_UP = 4


@dataclass(frozen=True)
class DiscoveredPaths:
    """Result of discover_paths(): the two directories, or None if absent."""
    shape_rifs: str | None
    textures: str | None


def _candidates(base: str, subparts: tuple[str, ...]):
    """Yield `base/subparts`, `parent/subparts`, ... up to _LEVELS_UP."""
    cur = base
    for _ in range(_LEVELS_UP + 1):
        yield os.path.join(cur, *subparts)
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent


def _first_existing(paths):
    """Return the first path that exists as a directory, or None."""
    for p in paths:
        if os.path.isdir(p):
            return p
    return None


def discover_paths(rif_path: str) -> DiscoveredPaths:
    """Find shape_rifs and fastfile/_ffl_unpacked relative to a RIF file."""
    base = os.path.dirname(os.path.abspath(rif_path))

    shape_rifs = _first_existing(_candidates(base, ("shape_rifs",)))
    textures = _first_existing(
        _candidates(base, ("fastfile", "_ffl_unpacked")))

    # Fallback: shape_rifs sitting next to the textures root's parent.
    if shape_rifs is None and textures is not None:
        root = os.path.dirname(os.path.dirname(textures))
        candidate = os.path.join(root, "shape_rifs")
        if os.path.isdir(candidate):
            shape_rifs = candidate

    return DiscoveredPaths(shape_rifs=shape_rifs, textures=textures)