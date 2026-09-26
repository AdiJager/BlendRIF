"""Tests for parsers.markers: DUMOBJ / PLACHID / AVPGENER / SOUNDOB2 /
AVPSTART / CAMORIGN / AVPPATH2.
"""

from __future__ import annotations

import struct
import unittest

from avp_rif_importer.parsers.markers import (
    parse_dumobjdt, parse_dumobjtx, parse_plachidt, parse_avpgener,
    parse_soundob2, parse_avpstart, parse_camorign, parse_avppath2,
)

from ._helpers import cstr, pad4


def _make_dumobjdt(name="", loc=(0, 0, 0), quat=(0.0, 0.0, 0.0, 1.0),
                   min_ext=(0, 0, 0), max_ext=(0, 0, 0)):
    out = pad4(cstr(name))
    out += struct.pack("<iii", *loc)
    out += struct.pack("<ffff", *quat)
    out += struct.pack("<iii", *min_ext)
    out += struct.pack("<iii", *max_ext)
    return out


def _make_plachidt(name="", hier_idx=0, loc=(0, 0, 0),
                   quat=(0.0, 0.0, 0.0, 1.0), id=(0, 0), n_extra=0):
    out = pad4(cstr(name))
    out += struct.pack("<i", hier_idx)
    out += struct.pack("<iii", *loc)
    out += struct.pack("<ffff", *quat)
    out += struct.pack("<ii", *id)
    out += struct.pack("<i", n_extra)
    return out


def _make_avpgener(loc=(0, 0, 0), orient=0, gtype=0, flags=0,
                   texid=0, subtype=0, name=""):
    out = struct.pack("<iii", *loc)
    out += struct.pack("<i", orient)
    out += struct.pack("<i", gtype)
    out += struct.pack("<i", flags)
    out += bytes([texid, subtype, 0, 0])   # pad to offset 28
    out += cstr(name)
    return out


def _make_soundob2(pos=(0, 0, 0), inner=0, outer=0, max_vol=0, pitch=0,
                   flags=0, probability=0, snd="", wav=""):
    out = struct.pack("<iii", *pos)
    out += struct.pack("<iiiiii", inner, outer, max_vol, pitch, flags,
                       probability)
    # Now at offset 36; strz starts at 40 -> 4 bytes padding.
    out += b"\x00" * 4
    out += cstr(snd)
    out = pad4(out)
    out += cstr(wav)
    return out


def _make_avpstart(loc=(0, 0, 0), mat=(0,) * 9, module_id=(0, 0)):
    out = struct.pack("<iii", *loc)
    out += b"\x00" * (12 - len(out))       # pad to offset 12
    out += struct.pack("<9i", *mat)
    out += struct.pack("<ii", *module_id)
    return out


def _make_camorign(loc=(0.0, 0.0, 0.0), mat=(0,) * 9):
    out = struct.pack("<ddd", *loc)
    out += struct.pack("<9i", *mat)
    return out


def _make_path_point(module=0, loc=(0, 0, 0), flags=0):
    return (struct.pack("<i", module) +
            struct.pack("<iii", *loc) +
            struct.pack("<i", flags) +
            b"\x00" * 4)


def _make_avppath2(name="", path_id=0, flags=0, points=()):
    out = pad4(cstr(name))
    out += struct.pack("<i", path_id)
    out += struct.pack("<i", flags)
    out += struct.pack("<i", 0)             # spare2
    out += struct.pack("<i", len(points))
    for p in points:
        out += p
    return out


class TestParseDumObjDt(unittest.TestCase):
    def test_basic(self):
        d = parse_dumobjdt(_make_dumobjdt(
            name="Spawn01", loc=(1, 2, 3),
            min_ext=(-5, -5, -5), max_ext=(5, 5, 5)))
        self.assertEqual(d.name, "Spawn01")
        self.assertEqual(d.location, (1, 2, 3))
        self.assertEqual(d.min_extents, (-5, -5, -5))
        self.assertEqual(d.max_extents, (5, 5, 5))

    def test_zero_quaternion(self):
        d = parse_dumobjdt(_make_dumobjdt(
            name="x", quat=(0.0, 0.0, 0.0, 0.0)))
        self.assertEqual(d.orientation, (0.0, 0.0, 0.0, 1.0))

    def test_too_short_returns_none(self):
        self.assertIsNone(parse_dumobjdt(b"\x00" * 10))


class TestParseDumObjTx(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(parse_dumobjtx(b"some text\x00more"), "some text")

    def test_no_nul(self):
        self.assertEqual(parse_dumobjtx(b"unterminated"), "unterminated")


class TestParsePlachIdt(unittest.TestCase):
    def test_basic(self):
        p = parse_plachidt(_make_plachidt(
            name="hier01", hier_idx=3, loc=(10, 20, 30),
            id=(7, 8), n_extra=2))
        self.assertEqual(p.name, "hier01")
        self.assertEqual(p.hierarchy_index, 3)
        self.assertEqual(p.location, (10, 20, 30))
        self.assertEqual(p.id, (7, 8))
        self.assertEqual(p.num_extra, 2)

    def test_empty_name_returns_none(self):
        self.assertIsNone(parse_plachidt(_make_plachidt(name="")))


class TestParseAvpGener(unittest.TestCase):
    def test_basic(self):
        g = parse_avpgener(_make_avpgener(
            loc=(100, 200, 300), orient=15, gtype=2, flags=0x80,
            texid=4, subtype=1, name="ItemSpawn"))
        self.assertEqual(g.location, (100, 200, 300))
        self.assertEqual(g.orientation, 15)
        self.assertEqual(g.type, 2)
        self.assertEqual(g.flags, 0x80)
        self.assertEqual(g.texid, 4)
        self.assertEqual(g.subtype, 1)
        self.assertEqual(g.name, "ItemSpawn")

    def test_too_short_returns_none(self):
        self.assertIsNone(parse_avpgener(b"\x00" * 10))


class TestParseSoundOb2(unittest.TestCase):
    def test_basic(self):
        s = parse_soundob2(_make_soundob2(
            pos=(1, 2, 3), inner=100, outer=200, max_vol=90,
            pitch=100, flags=1, probability=50,
            snd="ambient_01", wav="amb01.wav"))
        self.assertEqual(s.position, (1, 2, 3))
        self.assertEqual(s.inner, 100)
        self.assertEqual(s.outer, 200)
        self.assertEqual(s.max_volume, 90)
        self.assertEqual(s.pitch, 100)
        self.assertEqual(s.flags, 1)
        self.assertEqual(s.probability, 50)
        self.assertEqual(s.snd_name, "ambient_01")
        self.assertEqual(s.wav_name, "amb01.wav")

    def test_too_short_returns_none(self):
        self.assertIsNone(parse_soundob2(b"\x00" * 20))


class TestParseAvpStart(unittest.TestCase):
    def test_basic(self):
        mat = tuple(range(9))
        a = parse_avpstart(_make_avpstart(
            loc=(5, 6, 7), mat=mat, module_id=(11, 22)))
        self.assertEqual(a.location, (5, 6, 7))
        self.assertEqual(a.matrix, mat)
        self.assertEqual(a.module_id, (11, 22))

    def test_too_short_returns_none(self):
        self.assertIsNone(parse_avpstart(b"\x00" * 10))


class TestParseCamOrign(unittest.TestCase):
    def test_basic(self):
        mat = tuple(range(9))
        c = parse_camorign(_make_camorign(
            loc=(1.5, 2.5, 3.5), mat=mat))
        self.assertAlmostEqual(c.location[0], 1.5)
        self.assertAlmostEqual(c.location[1], 2.5)
        self.assertAlmostEqual(c.location[2], 3.5)
        self.assertEqual(c.matrix, mat)

    def test_too_short_returns_none(self):
        self.assertIsNone(parse_camorign(b"\x00" * 20))


class TestParseAvpPath2(unittest.TestCase):
    def test_basic(self):
        points = [
            _make_path_point(module=1, loc=(10, 0, 0), flags=0),
            _make_path_point(module=2, loc=(20, 0, 0), flags=1),
        ]
        p = parse_avppath2(_make_avppath2(
            name="patrol01", path_id=5, flags=0, points=points))
        self.assertEqual(p.name, "patrol01")
        self.assertEqual(p.id, 5)
        self.assertEqual(p.path_length, 2)
        self.assertEqual(len(p.points), 2)
        self.assertEqual(p.points[0].loc, (10, 0, 0))
        self.assertEqual(p.points[1].flags, 1)

    def test_zero_points(self):
        p = parse_avppath2(_make_avppath2(name="x"))
        self.assertEqual(p.points, [])

    def test_empty_name_returns_none(self):
        self.assertIsNone(parse_avppath2(_make_avppath2(name="")))


if __name__ == "__main__":
    unittest.main()