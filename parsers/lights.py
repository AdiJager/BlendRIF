# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""STDLIGHT parser."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..binary_reader import BinaryReader
from ..utils import log


STDLIGHT_MIN_SIZE = 76

# STDLIGHT payload field offsets.
STDLIGHT_OFF_NUMBER     = 0     # int32 light index
STDLIGHT_OFF_LOC        = 4     # int32 x3 position
STDLIGHT_OFF_BRIGHTNESS = 52    # int32 brightness
STDLIGHT_OFF_SPREAD     = 56    # int32 spot cone angle (degrees)
STDLIGHT_OFF_RANGE      = 60    # int32 cutoff distance
STDLIGHT_OFF_COLOUR     = 64    # uint32 0x00RRGGBB
STDLIGHT_OFF_ENGFLAGS   = 68    # int32 engine flags
STDLIGHT_OFF_LOCFLAGS   = 72    # int32 local (per-light) flags


@dataclass
class StdLight:
    light_number: int
    location: tuple[int, int, int]
    brightness: int
    spread: int
    range: int
    colour: tuple[int, int, int]
    engine_flags: int
    local_flags: int


def parse_stdlight(data: bytes) -> StdLight | None:
    """Parse a STDLIGHT payload into a StdLight, or None if malformed."""
    if len(data) < STDLIGHT_MIN_SIZE:
        return None
    try:
        r = BinaryReader(data)
        r.seek(STDLIGHT_OFF_NUMBER);     light_number = r.i32()
        r.seek(STDLIGHT_OFF_LOC);        loc          = r.i32x3()
        r.seek(STDLIGHT_OFF_BRIGHTNESS); brightness   = r.i32()
        r.seek(STDLIGHT_OFF_SPREAD);     spread       = r.i32()
        r.seek(STDLIGHT_OFF_RANGE);      light_range  = r.i32()
        r.seek(STDLIGHT_OFF_COLOUR);     colour       = r.u32()
        r.seek(STDLIGHT_OFF_ENGFLAGS);   engine_flags = r.i32()
        r.seek(STDLIGHT_OFF_LOCFLAGS);   local_flags  = r.i32()

        # 0x00RRGGBB -> (R, G, B)
        rr = (colour >> 16) & 0xFF
        gg = (colour >> 8) & 0xFF
        bb = colour & 0xFF
        return StdLight(light_number=light_number, location=loc,
                        brightness=brightness, spread=spread,
                        range=light_range, colour=(rr, gg, bb),
                        engine_flags=engine_flags, local_flags=local_flags)
    except (struct.error, IndexError) as e:
        log.warning(f"parse_stdlight: {type(e).__name__}: {e}")
        return None