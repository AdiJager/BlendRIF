"""Tests for parsers.bitmaps: BMPLSTST, MATCHIMG, CLRLOOKP."""

from __future__ import annotations

import struct
import unittest

from avp_rif_importer.parsers.bitmaps import (
    parse_bitmap_list, parse_image_descriptor, parse_matchimg, parse_clrlookp,
    ImageDescriptor, MatchImgRule,
)
from avp_rif_importer.materials import (
    build_matchimg_index, apply_matchimg_index, apply_matchimg_rule,
)

from ._helpers import cstr, pad4, make_bmplstst


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
        """One ImageDescriptor: flags + 3 spares + 3 strings, 4-byte aligned."""
        return pad4(struct.pack("<i", flags) + b"\x00" * 12 +
                    cstr(filename) + cstr(rifname) + cstr(fixrifname))

    def test_single_rule(self):
        load = self._descriptor(0, "new.bmp", "new", "")
        old = self._descriptor(0, "old.bmp", "old", "")
        payload = (b"\x00" * 8 +
                   struct.pack("<i", 0) +      # flags
                   struct.pack("<i", 1) +      # listsize
                   b"\x00" * 12 +              # rule preamble
                   load + old)
        m = parse_matchimg(payload)
        self.assertIsNotNone(m)
        self.assertEqual(m.flags, 0)
        self.assertEqual(len(m.rules), 1)
        self.assertEqual(m.rules[0].load.filename, "new.bmp")
        self.assertEqual(m.rules[0].insteadof.filename, "old.bmp")
        self.assertEqual(m.rules[0].load.rifname, "new")

    def test_two_rules_are_read_in_order(self):
        first = (self._descriptor(0, "a.bmp", "s1", "") +
                 self._descriptor(0, "b.bmp", "s2", ""))
        second = (self._descriptor(0, "c.bmp", "s3", "") +
                  self._descriptor(0, "d.bmp", "s4", ""))
        payload = (b"\x00" * 8 + struct.pack("<i", 0) +
                   struct.pack("<i", 2) + b"\x00" * 12 + first +
                   b"\x00" * 12 + second)
        m = parse_matchimg(payload)
        self.assertEqual([r.insteadof.filename for r in m.rules],
                         ["b.bmp", "d.bmp"])
        self.assertEqual([r.load.filename for r in m.rules],
                         ["a.bmp", "c.bmp"])

    def test_empty_descriptor_strings_are_allowed(self):
        """Shipped rules carry empty rifname/fixrifname fields."""
        load = self._descriptor(0, "10.bmp", "explode", "")
        old = self._descriptor(0, "9.bmp", "", "")
        payload = (b"\x00" * 8 + struct.pack("<i", 0) + struct.pack("<i", 1) +
                   b"\x00" * 12 + load + old)
        m = parse_matchimg(payload)
        self.assertEqual(m.rules[0].insteadof.filename, "9.bmp")
        self.assertEqual(m.rules[0].insteadof.rifname, "")
        self.assertEqual(m.rules[0].load.rifname, "explode")

    def test_truncated_rule_returns_none(self):
        load = self._descriptor(0, "a.bmp", "s1", "")
        payload = (b"\x00" * 8 + struct.pack("<i", 0) + struct.pack("<i", 1) +
                   b"\x00" * 12 + load)
        self.assertIsNone(parse_matchimg(payload))

    def test_absurd_rule_count_returns_none(self):
        payload = (b"\x00" * 8 + struct.pack("<i", 0) +
                   struct.pack("<i", 10 ** 6))
        self.assertIsNone(parse_matchimg(payload))

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


class TestMatchImgIndex(unittest.TestCase):
    """Substitution lookup: rule choice and the load path it implies."""

    @staticmethod
    def _rules(*triples):
        """Build rules from (load_name, load_rim, instead_name, instead_rim)."""
        return [MatchImgRule(
            load=ImageDescriptor(flags=0, filename=ln, rifname=lr,
                                 fixrifname=""),
            insteadof=ImageDescriptor(flags=0, filename=in_, rifname=ir,
                                      fixrifname=""))
            for ln, lr, in_, ir in triples]

    def test_no_rules_leaves_the_name_alone(self):
        self.assertEqual(apply_matchimg_index("grille", {}), "grille")
        self.assertIsNone(apply_matchimg_rule("grille", "", {}))

    def test_unmatched_name_is_unchanged(self):
        idx = build_matchimg_index(self._rules(("new.bmp", "x", "old.bmp", "x")))
        self.assertEqual(apply_matchimg_index("other", idx), "other")

    def test_replacement_returns_load_basename_and_path(self):
        idx = build_matchimg_index(
            self._rules(("Env\\new.bmp", "new", "old.bmp", "old")))
        name, path = apply_matchimg_rule("old", "Envrnmts\\Old.bmp", idx)
        self.assertEqual(name, "new")
        self.assertEqual(path, "Env\\new.bmp")

    def test_rule_whose_rim_matches_wins(self):
        idx = build_matchimg_index(self._rules(
            ("fallback.bmp", "", "tex.bmp", ""),
            ("area52.bmp", "area52", "tex.bmp", "area52"),
            ("towers.bmp", "towers03", "tex.bmp", "towers03"),
        ))
        name, path = apply_matchimg_rule("tex", "Envrnmts/Towers03/Tex.bmp", idx)
        self.assertEqual(path, "towers.bmp")
        self.assertEqual(name, "towers")

    def test_other_rim_rule_is_still_used_as_last_resort(self):
        idx = build_matchimg_index(self._rules(
            ("only.bmp", "somewhere", "tex.bmp", "somewhere")))
        name, path = apply_matchimg_rule("tex", "Elsewhere/Tex.bmp", idx)
        self.assertEqual(path, "only.bmp")

    def test_apply_index_returns_the_load_basename(self):
        idx = build_matchimg_index(self._rules(("1.bmp", "explode", "10.bmp", "")))
        self.assertEqual(apply_matchimg_index("10", idx), "1")


if __name__ == "__main__":
    unittest.main()