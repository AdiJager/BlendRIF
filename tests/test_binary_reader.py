"""Tests for BinaryReader and read_cstr."""

from __future__ import annotations

import struct
import unittest

from avp_rif_importer.binary_reader import BinaryReader
from avp_rif_importer.parsers._shared import read_cstr


class TestScalars(unittest.TestCase):
    def test_i16_u16(self):
        r = BinaryReader(struct.pack("<hH", -1, 65535))
        self.assertEqual(r.i16(), -1)
        self.assertEqual(r.u16(), 65535)

    def test_i32_u32(self):
        r = BinaryReader(struct.pack("<iI", -2, 0xDEADBEEF))
        self.assertEqual(r.i32(), -2)
        self.assertEqual(r.u32(), 0xDEADBEEF)

    def test_f32_f64(self):
        r = BinaryReader(struct.pack("<fd", 1.5, 2.25))
        self.assertEqual(r.f32(), 1.5)
        self.assertEqual(r.f64(), 2.25)


class TestTuples(unittest.TestCase):
    def test_i32x3(self):
        r = BinaryReader(struct.pack("<iii", 1, 2, 3))
        self.assertEqual(r.i32x3(), (1, 2, 3))

    def test_i32x9(self):
        r = BinaryReader(struct.pack("<9i", *range(9)))
        self.assertEqual(r.i32x9(), tuple(range(9)))

    def test_f32x4(self):
        r = BinaryReader(struct.pack("<ffff", 1.0, 2.0, 3.0, 4.0))
        self.assertEqual(r.f32x4(), (1.0, 2.0, 3.0, 4.0))

    def test_f64x3(self):
        r = BinaryReader(struct.pack("<ddd", 1.1, 2.2, 3.3))
        a, b, c = r.f64x3()
        self.assertAlmostEqual(a, 1.1)
        self.assertAlmostEqual(b, 2.2)
        self.assertAlmostEqual(c, 3.3)


class TestStrings(unittest.TestCase):
    def test_strz_terminated(self):
        r = BinaryReader(b"hello\x00world\x00")
        self.assertEqual(r.strz(), "hello")
        self.assertEqual(r.strz(), "world")

    def test_strz_no_terminator(self):
        r = BinaryReader(b"trailing")
        self.assertEqual(r.strz(), "trailing")
        self.assertEqual(r.pos, 8)

    def test_strz_non_ascii_ignored(self):
        r = BinaryReader(b"ab\xff\xfecd\x00")
        self.assertEqual(r.strz(), "abcd")


class TestPositioning(unittest.TestCase):
    def test_seek_and_align4(self):
        r = BinaryReader(b"\x00" * 16)
        r.seek(3)
        r.align4()
        self.assertEqual(r.pos, 4)

    def test_skip(self):
        r = BinaryReader(b"\x00" * 16)
        r.skip(5)
        self.assertEqual(r.pos, 5)

    def test_remaining(self):
        r = BinaryReader(b"\x00" * 10)
        r.skip(3)
        self.assertEqual(r.remaining(), 7)


class TestShortRead(unittest.TestCase):
    def test_i32_at_boundary_raises(self):
        r = BinaryReader(b"\x00\x00")
        with self.assertRaises(struct.error):
            r.i32()

    def test_skip_beyond_end_raises(self):
        r = BinaryReader(b"\x00")
        with self.assertRaises(struct.error):
            r.skip(5)


class TestReadCstr(unittest.TestCase):
    def test_basic(self):
        s, off = read_cstr(b"hello\x00world", 0)
        self.assertEqual(s, "hello")
        self.assertEqual(off, 6)

    def test_returns_next_offset(self):
        s, off = read_cstr(b"abc\x00def\x00", 4)
        self.assertEqual(s, "def")
        self.assertEqual(off, 8)

    def test_no_nul_returns_rest(self):
        s, off = read_cstr(b"abcdef", 0)
        self.assertEqual(s, "abcdef")
        self.assertEqual(off, 6)

    def test_at_end(self):
        s, off = read_cstr(b"\x00", 0)
        self.assertEqual(s, "")
        self.assertEqual(off, 1)


if __name__ == "__main__":
    unittest.main()