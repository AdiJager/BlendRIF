"""Tests for parsers.lights (STDLIGHT).

The file was historically named *_lights_anim.py and also covered
OBJTRACK2; that parser moved to parsers/level_track.py under a new
name (parse_level_track) when the phantom OBJTRACK2 parser was
removed in 6.3.x. Only the STDLIGHT tests are kept here. The new
level-track parser is covered by tests/test_parsers_level_track.py
(or an equivalent module); if that file is not present yet, its
tests should be added there separately.
"""

from __future__ import annotations

import struct
import unittest

from avp_rif_importer.parsers.lights import parse_stdlight


def _make_stdlight(light_number=0, loc=(0, 0, 0), brightness=0,
                   spread=0, range_=0, colour=0xFFFFFF,
                   engine_flags=0, local_flags=0):
    data = bytearray(76)
    struct.pack_into("<i", data, 0, light_number)
    struct.pack_into("<iii", data, 4, *loc)
    struct.pack_into("<i", data, 52, brightness)
    struct.pack_into("<i", data, 56, spread)
    struct.pack_into("<i", data, 60, range_)
    struct.pack_into("<I", data, 64, colour)
    struct.pack_into("<i", data, 68, engine_flags)
    struct.pack_into("<i", data, 72, local_flags)
    return bytes(data)


class TestParseStdLight(unittest.TestCase):
    def test_basic(self):
        s = parse_stdlight(_make_stdlight(
            light_number=3, loc=(10, 20, 30), brightness=5000,
            spread=45, range_=100, colour=0x112233,
            engine_flags=0x40, local_flags=0x01))
        self.assertEqual(s.light_number, 3)
        self.assertEqual(s.location, (10, 20, 30))
        self.assertEqual(s.brightness, 5000)
        self.assertEqual(s.spread, 45)
        self.assertEqual(s.range, 100)
        self.assertEqual(s.colour, (0x11, 0x22, 0x33))
        self.assertEqual(s.engine_flags, 0x40)
        self.assertEqual(s.local_flags, 0x01)

    def test_colour_extraction(self):
        # 0xRRGGBB -> (R, G, B)
        s = parse_stdlight(_make_stdlight(colour=0xAABBCC))
        self.assertEqual(s.colour, (0xAA, 0xBB, 0xCC))

    def test_too_short_returns_none(self):
        self.assertIsNone(parse_stdlight(b"\x00" * 40))


if __name__ == "__main__":
    unittest.main()