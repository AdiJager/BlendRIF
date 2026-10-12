# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""WAYPOINT parser: the AI navigation volumes stored inside MODULEDT.

Each AI module of a level stores one WAYPOINT chunk inside its module
data (path: REBINFF2 > RBOBJECT > MODULEDT > WAYPOINT). The payload is a
flat list of axis-aligned volumes the Alien AI uses to navigate the
level; the ground/marine variant recorded in the same list was
superseded by the AVPPATH2 patrol paths during development and is not
imported by this add-on.

Layout (wpchunk.cpp / wpchunk.hpp in the AvP source):

    int32   num_waypoints
    per waypoint:
        int32 x3    min      low corner in world space
        int32 x3    max      high corner in world space
        int32 x3    centre   AI aim point (world space)
        int32       flags
        int32       spare2
        int32       num_links
        num_links x (int32 index, int32 flags)   links to sibling volumes
        int32       num_mod_links
        num_mod_links x (NUL-terminated name padded to 4 bytes, int32 flags)

`min`/`max` are the absolute corners of the volume in world space - the
box spans them, which is what the importer draws. `centre` is the point
the AI aims for: the designer places it by hand in most volumes
(`WaypointFlag_CentreDefinedByUser` is set on ~60% of the shipped ones),
otherwise it is the midpoint of the corners. The wpchunk.hpp comments
calling min/max "relative to centre" do not match the shipped data.

Accounting, confirmed by parsing all 664 WAYPOINT chunks of the retail
levels: 4 bytes for the count, then per volume 48 bytes (min/max/centre,
flags, spare2, both counts) plus 8 bytes per link plus (name + 4 flag
bytes) per module link. The engine's size_chunk() also counts two
trailing spare ints, but the shipped chunks end right after the last
volume, so those are read only when present.

In the retail game only the Alien half is ever populated: none of the
664 chunks carries `WaypointFlag_FirstGroundWaypoint` (the ground half
was superseded by AVPPATH2 during development). `split_alien_waypoints`
still honours the flag so a pre-release file would import correctly.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from ..binary_reader import BinaryReader
from ..utils import log


# --- flags (wpchunk.hpp) ------------------------------------------------
WAYPOINT_FLAG_CENTRE_USER = 0x80000000   # WaypointFlag_CentreDefinedByUser
WAYPOINT_FLAG_FIRST_GROUND = 0x40000000  # WaypointFlag_FirstGroundWaypoint

# --- link flags (bh_waypt.h) -------------------------------------------
LINK_FLAG_ONEWAY = 0x00000001
LINK_FLAG_REVERSED_ONEWAY = 0x00000002
LINK_FLAG_ALIEN_ONLY = 0x00000004
LINK_FLAG_LARGE_TARGET = 0x00000008

# --- volume flags (bh_waypt.h) -----------------------------------------
WAYPOINT_VOLUME_FLAG_CAN_CRAWL = 0x00000001

# --- parser limits ------------------------------------------------------
# A payload holds the count plus the volume records; the shipped chunks
# carry no trailing data, so four bytes is a legal (empty) payload.
MIN_PAYLOAD = 4
# Sanity cap: the largest shipped chunk holds a few dozen volumes, so a
# corrupt count cannot make the parser allocate forever.
MAX_WAYPOINTS = 4096


@dataclass
class WaypointLink:
    """One link to another volume of the same module."""
    index: int
    flags: int


@dataclass
class Waypoint:
    """One navigation volume of one AI module."""
    index: int
    min_extents: tuple[int, int, int]
    max_extents: tuple[int, int, int]
    centre: tuple[int, int, int]
    flags: int
    links: list = field(default_factory=list)      # list[WaypointLink]
    mod_links: list = field(default_factory=list)  # list[tuple[str, int]]

    @property
    def is_user_centre(self) -> bool:
        """True when the designer placed the centre by hand."""
        return bool(self.flags & WAYPOINT_FLAG_CENTRE_USER)


@dataclass
class ModuleWaypoints:
    """Every waypoint of a single module, in stored order."""
    waypoints: list = field(default_factory=list)  # list[Waypoint]
    spare1: int = 0
    spare2: int = 0


def parse_waypoint(data: bytes) -> ModuleWaypoints | None:
    """Parse a WAYPOINT payload into ModuleWaypoints, or None if malformed."""
    if len(data) < MIN_PAYLOAD:
        return None
    try:
        r = BinaryReader(data)
        count = r.i32()
        if count < 0 or count > MAX_WAYPOINTS:
            log.warning(f"parse_waypoint: implausible count {count}")
            return None

        waypoints: list[Waypoint] = []
        for i in range(count):
            # min/max/centre + flags + spare2 = 44 bytes of fixed fields;
            # bail out before reading when the stream is already too short.
            if r.remaining() < 44:
                log.warning(f"parse_waypoint: truncated at waypoint {i}/{count}")
                return None
            mn = r.i32x3()
            mx = r.i32x3()
            centre = r.i32x3()
            flags = r.i32()
            r.i32()                       # spare2 - unused
            n_links = r.i32()
            if n_links < 0 or r.remaining() < 8 * n_links:
                log.warning(f"parse_waypoint: bad link count {n_links} "
                            f"at waypoint {i}")
                return None
            links = [WaypointLink(index=r.i32(), flags=r.i32())
                     for _ in range(n_links)]
            n_mod = r.i32()
            if n_mod < 0:
                log.warning(f"parse_waypoint: bad module link count {n_mod}")
                return None
            mod_links = []
            for _ in range(n_mod):
                name = r.strz()
                r.align4()
                mod_links.append((name, r.i32()))
            waypoints.append(Waypoint(index=i, min_extents=mn,
                                      max_extents=mx, centre=centre,
                                      flags=flags, links=links,
                                      mod_links=mod_links))

        # The engine's size_chunk() counts two trailing spares, but the
        # shipped chunks end right after the last volume - read them
        # only when they are actually present.
        spare1 = r.i32() if r.remaining() >= 4 else 0
        spare2 = r.i32() if r.remaining() >= 4 else 0
        return ModuleWaypoints(waypoints=waypoints, spare1=spare1,
                               spare2=spare2)
    except (struct.error, IndexError) as e:
        log.warning(f"parse_waypoint: {type(e).__name__}: {e}")
        return None


def first_ground_index(waypoints: list) -> int | None:
    """Return the index of the first ground volume, or None if there is none."""
    for w in waypoints:
        if w.flags & WAYPOINT_FLAG_FIRST_GROUND:
            return w.index
    return None


def split_alien_waypoints(parsed: ModuleWaypoints) -> list:
    """Return only the Alien volumes of a parsed chunk.

    The game flags the first ground volume; everything before it is the
    Alien navigation mesh, and a chunk without the flag is Alien-only
    (every one of the 664 retail chunks is). Returning the ground
    volumes too is pointless for the importer: AVPPATH2 patrol paths
    replaced them before release, so they hold no usable data.
    """
    cut = first_ground_index(parsed.waypoints)
    if cut is None:
        return list(parsed.waypoints)
    return [w for w in parsed.waypoints if w.index < cut]
