"""Tests for parsers.bitmaps: BMPLSTST, MATCHIMG, CLRLOOKP."""

from __future__ import annotations

import struct
import unittest

from avp_rif_importer.parsers.bitmaps import (
    parse_bitmap_list, parse_image_descriptor, parse_matchimg, parse_clrlookp,
)

from ._helpers import cstr, make_bmplstst


class TestParseBitmapList(unittest.TestCase):
    def test_single_entry(self):
        payload = make_bmplstst([(5, 0, 0, "Tex\\Stone.png")])
        result = parse_bitmap_list(payload)
        self.assertEqual(set(result.keys()), {5})
        e = result[5]
        self.assertEqual(e.name, "Stone")
        self.assertEqual(e.raw_name, "Tex\\Stone.png")
        self.assertEqual(e.version, 0)
        self.assertEqual(e.enum_id, 0)

    def test_version_and_enum_from_d1(self):
        # d1 = 0x00123000 -> enum_id = 1, version = 0x23000
        payload = make_bmplstst([(0, 0, 0x00123000, "x.png")])
        e = parse_bitmap_list(payload)[0]
        self.assertEqual(e.version, 0x23000)
        self.assertEqual(e.enum_id, 1)

    def test_multiple_entries(self):
        payload = make_bmplstst([
            (0, 0, 0, "a.png"),
            (7, 0, 0, "b.png"),
            (3, 0, 0, "c.png"),
        ])
        result = parse_bitmap_list(payload)
        self.assertEqual(set(result.keys()), {0, 3, 7})

    def test_forward_slash_in_path(self):
        payload = make_bmplstst([(0, 0, 0, "tex/sub/file.png")])
        e = parse_bitmap_list(payload)[0]
        self.assertEqual(e.name, "file")

    def test_empty_payload_returns_empty_dict(self):
        self.assertEqual(parse_bitmap_list(b""), {})
        self.assertEqual(parse_bitmap_list(b"\x00\x00"), {})


class TestParseImageDescriptor(unittest.TestCase):
    def test_basic(self):
        payload = (struct.pack("<i", 0xAB) + b"\x00" * 12 +
                   cstr("a.png") + cstr("b.rif") + cstr("c.rif"))
        d, offset = parse_image_descriptor(payload, 0)
        self.assertIsNotNone(d)
        self.assertEqual(d.flags, 0xAB)
        self.assertEqual(d.filename, "a.png")
        self.assertEqual(d.rifname, "b.rif")
        self.assertEqual(d.fixrifname, "c.rif")
        self.assertEqual(offset, len(payload))


class TestParseMatchImg(unittest.TestCase):
    @staticmethod
    def _descriptor(flags, filename, rifname, fixrifname):
        return (struct.pack("<i", flags) + b"\x00" * 12 +
                cstr(filename) + cstr(rifname) + cstr(fixrifname))

    def test_single_rule(self):
        load = self._descriptor(0, "new.png", "new.rif", "")
        old = self._descriptor(0, "old.png", "old.rif", "")
        payload = (b"\x00" * 8 +
                   struct.pack("<i", 0) +      # flags
                   struct.pack("<i", 1) +      # listsize
                   b"\x00" * 12 +              # rule preamble
                   load + old)
        m = parse_matchimg(payload)
        self.assertIsNotNone(m)
        self.assertEqual(m.flags, 0)
        self.assertEqual(len(m.rules), 1)
        self.assertEqual(m.rules[0].load.filename, "new.png")
        self.assertEqual(m.rules[0].insteadof.filename, "old.png")

    def test_too_short_returns_none(self):
        self.assertIsNone(parse_matchimg(b"\x00" * 8))

    def test_zero_rules(self):
        payload = (b"\x00" * 8 +
                   struct.pack("<i", 0) +
                   struct.pack("<i", 0))
        m = parse_matchimg(payload)
        self.assertEqual(m.rules, [])


class TestParseClrLookp(unittest.TestCase):
    def test_filename_variant(self):
        payload = (struct.pack("<i", 1) + b"\x00" * 28 +
                   cstr("some.pal"))
        c = parse_clrlookp(payload)
        self.assertEqual(c.flags, 1)
        self.assertEqual(c.filename, "some.pal")
        self.assertEqual(c.table, [])

    def test_table_variant(self):
        payload = (struct.pack("<i", 0) + b"\x00" * 28 +
                   bytes([1, 2, 3, 4]))
        c = parse_clrlookp(payload)
        self.assertEqual(c.flags, 0)
        self.assertEqual(c.filename, "")
        self.assertEqual(c.table, [1, 2, 3, 4])

    def test_too_short_returns_none(self):
        self.assertIsNone(parse_clrlookp(b"\x00"))


if __name__ == "__main__":
    unittest.main()