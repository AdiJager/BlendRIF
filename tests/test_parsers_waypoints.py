"""Tests for parsers.waypoints (WAYPOINT chunks inside MODULEDT).

Layout is locked in from wpchunk.cpp / wpchunk.hpp and confirmed
against every shipped level RIF: header = int32 count, then per volume
min/max/centre (int32 x3 each), flags, spare2, link count + links,
module link count + (name, flags), and two trailing spares. Payload size
is exactly 16 + 40*n + 8*links + module links, i.e. no padding.

The alien/ground split is decided by WaypointFlag_FirstGroundWaypoint on
the first ground volume; the importer keeps only the volumes before it.
"""

from __future__ import annotations

import struct
import unittest

from avp_rif_importer.parsers.waypoints import (
    parse_waypoint,
    first_ground_index,
    split_alien_waypoints,
    WAYPOINT_FLAG_FIRST_GROUND,
    WAYPOINT_FLAG_CENTRE_USER,
    MAX_WAYPOINTS,
)

from ._helpers import cstr, pad4


def _pack_i32(*values):
    """Pack int32 values, accepting the unsigned flag range (0x80000000)."""
    out = b""
    for v in values:
        out += struct.pack("<i" if v <= 0x7FFFFFFF else "<I", v)
    return out


def _volume(min_ext=(0, 0, 0), max_ext=(0, 0, 0), centre=(0, 0, 0),
            flags=0, spare2=0, links=(), mod_links=()):
    """Build one waypoint volume record."""
    out = struct.pack("<iii", *min_ext)
    out += struct.pack("<iii", *max_ext)
    out += struct.pack("<iii", *centre)
    out += _pack_i32(flags, spare2)
    out += struct.pack("<i", len(links))
    for index, lflags in links:
        out += struct.pack("<ii", index, lflags)
    out += struct.pack("<i", len(mod_links))
    for name, mflags in mod_links:
        out += pad4(cstr(name))
        out += struct.pack("<i", mflags)
    return out


def _payload(volumes, spare1=0, spare2=0):
    """Build a full WAYPOINT payload (count + volumes + trailing spares)."""
    return (struct.pack("<i", len(volumes))
            + b"".join(volumes)
            + struct.pack("<ii", spare1, spare2))


class TestParseWaypoint(unittest.TestCase):
    """Payload decoding, including the malformed-input guards."""

    def test_single_volume(self):
        p = parse_waypoint(_payload([
            _volume(min_ext=(-100, -200, -300), max_ext=(100, 200, 300),
                    centre=(1000, 2000, 3000), flags=1)]))
        self.assertIsNotNone(p)
        self.assertEqual(len(p.waypoints), 1)
        w = p.waypoints[0]
        self.assertEqual(w.index, 0)
        self.assertEqual(w.min_extents, (-100, -200, -300))
        self.assertEqual(w.max_extents, (100, 200, 300))
        self.assertEqual(w.centre, (1000, 2000, 3000))
        self.assertEqual(w.flags, 1)
        self.assertEqual(w.links, [])
        self.assertEqual(w.mod_links, [])

    def test_volume_size_matches_game(self):
        """One volume costs 48 bytes before its links.

        Verified against shipped chunks: 16 (chunk header) + 4 (count)
        + n*(48 + 8*links) + 4 bytes per module link (padded name +
        flags) + 8 trailing spares. A one-volume, link-less chunk is
        therefore exactly 80 bytes including its header.
        """
        self.assertEqual(len(_volume()), 48 + 4)
        # Link count is part of the 52; each link adds 8.
        self.assertEqual(len(_volume(links=[(1, 0), (2, 0)])), 52 + 2 * 8)
        # Module link count is also inside the 52; "mod_a" + NUL is one
        # 4-byte word, then 4 bytes of flags, and the count field itself
        # is 4 bytes past the fixed part.
        self.assertEqual(len(_volume(mod_links=[("mod_a", 7)])),
                         52 + 4 + 4 + 4)
        # Payload = 4 (count) + volumes + 8 (trailing spares).
        self.assertEqual(len(_payload([_volume()])), 4 + 52 + 8)
        # The game's own accounting: 16-byte chunk header + payload.
        self.assertEqual(16 + len(_payload([_volume()])), 80)

    def test_links_are_parsed(self):
        p = parse_waypoint(_payload([
            _volume(links=[(1, 0), (5, 4)])]))
        self.assertEqual([(lk.index, lk.flags) for lk in p.waypoints[0].links],
                         [(1, 0), (5, 4)])

    def test_module_links_are_parsed(self):
        p = parse_waypoint(_payload([
            _volume(mod_links=[("corridor", 4), ("lift", 0)])]))
        self.assertEqual(p.waypoints[0].mod_links,
                         [("corridor", 4), ("lift", 0)])

    def test_trailing_spares_are_read(self):
        p = parse_waypoint(_payload([_volume()], spare1=11, spare2=22))
        self.assertEqual((p.spare1, p.spare2), (11, 22))

    def test_indices_are_sequential(self):
        p = parse_waypoint(_payload([_volume(), _volume(), _volume()]))
        self.assertEqual([w.index for w in p.waypoints], [0, 1, 2])

    def test_zero_waypoints(self):
        p = parse_waypoint(struct.pack("<i", 0) + struct.pack("<ii", 0, 0))
        self.assertIsNotNone(p)
        self.assertEqual(p.waypoints, [])

    def test_short_payload_returns_none(self):
        self.assertIsNone(parse_waypoint(b""))
        self.assertIsNone(parse_waypoint(struct.pack("<i", 1)))

    def test_negative_count_returns_none(self):
        self.assertIsNone(parse_waypoint(struct.pack("<i", -1) + b"\x00" * 8))

    def test_absurd_count_returns_none(self):
        """A corrupt count must not be trusted (allocation guard)."""
        self.assertIsNone(parse_waypoint(
            struct.pack("<i", MAX_WAYPOINTS + 1) + b"\x00" * 8))

    def test_truncated_volume_returns_none(self):
        """Count promises two volumes, payload holds one and a half."""
        body = struct.pack("<i", 2) + _volume() + _volume()[:20]
        self.assertIsNone(parse_waypoint(body))

    def test_negative_link_count_returns_none(self):
        body = (struct.pack("<i", 1)
                + struct.pack("<iii", 0, 0, 0) * 3
                + _pack_i32(0, 0)
                + struct.pack("<i", -4))
        self.assertIsNone(parse_waypoint(body))

    def test_link_count_beyond_payload_returns_none(self):
        body = (struct.pack("<i", 1)
                + struct.pack("<iii", 0, 0, 0) * 3
                + _pack_i32(0, 0)
                + struct.pack("<i", 99))
        self.assertIsNone(parse_waypoint(body))


class TestAlienGroundSplit(unittest.TestCase):
    """The split rule the importer relies on."""

    def test_chunk_without_flag_is_all_alien(self):
        p = parse_waypoint(_payload([_volume(), _volume(), _volume()]))
        self.assertIsNone(first_ground_index(p.waypoints))
        self.assertEqual(len(split_alien_waypoints(p)), 3)

    def test_first_ground_flag_splits_the_list(self):
        p = parse_waypoint(_payload([
            _volume(),
            _volume(),
            _volume(flags=WAYPOINT_FLAG_FIRST_GROUND),
            _volume(),
        ]))
        self.assertEqual(first_ground_index(p.waypoints), 2)
        alien = split_alien_waypoints(p)
        self.assertEqual([w.index for w in alien], [0, 1])

    def test_ground_flag_on_first_volume_means_no_alien(self):
        p = parse_waypoint(_payload([
            _volume(flags=WAYPOINT_FLAG_FIRST_GROUND),
            _volume(),
        ]))
        self.assertEqual(first_ground_index(p.waypoints), 0)
        self.assertEqual(split_alien_waypoints(p), [])

    def test_user_centre_flag_does_not_affect_the_split(self):
        p = parse_waypoint(_payload([
            _volume(flags=WAYPOINT_FLAG_CENTRE_USER),
            _volume(flags=WAYPOINT_FLAG_CENTRE_USER
                    | WAYPOINT_FLAG_FIRST_GROUND),
        ]))
        self.assertEqual(len(split_alien_waypoints(p)), 1)
        self.assertTrue(p.waypoints[0].is_user_centre)
        self.assertTrue(p.waypoints[1].is_user_centre)


if __name__ == "__main__":
    unittest.main()
