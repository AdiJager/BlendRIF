# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Mutable counters for the import pipeline.

ImportStats covers the geometry stage; ImportCounters covers markers,
lights, animations, and both character stages (hierarchy + NLA bake).
They are plain dataclasses so stages can mutate them by reference
without the operator having to thread dicts around.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ImportStats:
    """Counters for the geometry stage."""
    ok: int = 0
    placements_ok: int = 0      # placements that produced a mesh
    orphan_ok: int = 0          # orphan shapes that produced a mesh
    skipped_no_shape: int = 0   # placement references a missing shape_id
    skipped_nogeom: int = 0     # placement's shape has no usable geometry
    orphan_skipped: int = 0     # orphan shape skipped per orphan_mode


@dataclass
class ImportCounters:
    """Counters for markers, lights, animations and character stages."""
    dum: int = 0                # DUMMYOBJ markers
    ph: int = 0                 # PLACHIER markers
    gen: int = 0                # AVPGENER generators
    snd: int = 0                # SOUNDOB2 sound emitters
    ps: int = 0                 # AVPSTART player starts
    cam: int = 0                # CAMORIGN camera origins
    path: int = 0               # AVPPATH2 patrol paths
    lights: int = 0             # LIGHTSET lights
    anims: int = 0              # OBJTRAK2 level-track animations
    smooth: int = 0             # meshes smoothed by Auto Smooth
    max_frame: int = 1          # highest keyframe produced so far
    # Character hierarchy counters, filled in Stage 1c.
    hier_bones: int = 0
    hier_parented: int = 0
    # Character animation counters, filled in Stage 4b.
    char_anim_bones: int = 0
    char_anim_strips: int = 0