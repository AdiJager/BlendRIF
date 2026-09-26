# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Parser for OBJTRAK2 - the level-track animation chunk.

Runtime layout confirmed from the AvP (1999) developer kit, file
track.c. On-disk layout confirmed from Derelict.RIF hex dumps:
88 B payload for 1 section, 240 B for 3 sections, i.e.

    int32 num_sections
    per section (76 B):
        4 x float   quat_start      (x, y, z, w)
        4 x float   quat_end
        3 x int32   pivot_start     (x, y, z)
        3 x int32   pivot_end       (x, y, z) - ABSOLUTE end position
        3 x int32   object_offset   (x, y, z)
        int32       time_for_section
        int32       spare
    8 B trailer:
        int32       flags
        int32       timer_start

Runtime stores pivot_travel = pivot_end - pivot_start and interpolates
between sections with slerp for rotation and cubic Catmull-Rom for
position when use_smoothing is set (see track.c). For static Blender
export we bake each section boundary as one keyframe.

A section's time_for_section is often 0 in shipped RIFs - the runtime
gets it from the surrounding track controller. Callers pass a default
per-section duration (in Blender frames at animation_fps).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from ..binary_reader import BinaryReader
from ..utils import log


SECTION_SIZE = 76
TAIL_SIZE = 8
MIN_PAYLOAD = 4 + SECTION_SIZE + TAIL_SIZE   # 88

# Guard against pathological counts.
MAX_SECTIONS = 4096


@dataclass
class TrackSection:
    quat_start: tuple[float, float, float, float]
    quat_end: tuple[float, float, float, float]
    pivot_start: tuple[int, int, int]
    pivot_end: tuple[int, int, int]
    object_offset: tuple[int, int, int]
    time_for_section: int
    spare: int


@dataclass
class LevelTrack:
    num_sections: int
    sections: list[TrackSection] = field(default_factory=list)
    flags: int = 0
    timer_start: int = 0


def parse_objtrak2(data: bytes) -> LevelTrack | None:
    """Parse an OBJTRAK2 payload into a LevelTrack, or None if malformed."""
    if len(data) < MIN_PAYLOAD:
        return None
    try:
        r = BinaryReader(data)
        num_sections = r.i32()
        if num_sections < 0 or num_sections > MAX_SECTIONS:
            log.warning(f"parse_objtrak2: implausible num_sections="
                        f"{num_sections}")
            return None

        expected = 4 + num_sections * SECTION_SIZE + TAIL_SIZE
        if len(data) < expected:
            log.warning(f"parse_objtrak2: payload {len(data)} B < "
                        f"expected {expected} B for {num_sections} "
                        f"section(s); will parse what fits")

        sections: list[TrackSection] = []
        for _ in range(num_sections):
            if r.remaining() < SECTION_SIZE:
                break
            qs = r.f32x4()
            qe = r.f32x4()
            ps = r.i32x3()
            pe = r.i32x3()
            oo = r.i32x3()
            tfs = r.i32()
            spare = r.i32()
            sections.append(TrackSection(
                quat_start=qs, quat_end=qe,
                pivot_start=ps, pivot_end=pe,
                object_offset=oo,
                time_for_section=tfs, spare=spare))

        if r.remaining() >= TAIL_SIZE:
            flags = r.i32()
            timer_start = r.i32()
        else:
            flags = 0
            timer_start = 0

        return LevelTrack(num_sections=num_sections, sections=sections,
                          flags=flags, timer_start=timer_start)
    except (struct.error, IndexError) as e:
        log.warning(f"parse_objtrak2: {type(e).__name__}: {e}")
        return None