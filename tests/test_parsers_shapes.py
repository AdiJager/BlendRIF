"""Tests for parsers.shapes: SHPHEAD1, OBJHEAD1, SHPEXTFL.

5.7.0 (A5): parse_shpextfl now takes the raw SHPEXTFL payload directly
(was: the parent shape dict). The "no extfl key" test moved to a
"parse an empty payload" test, since the None-check is the caller's job.
"""

from __future__ import annotations

import struct
import unittest

from avp_rif_importer.chunk_ids import Chunk
from avp_rif_importer.parsers.shapes import (
    parse_shphead1, parse_objhead1, parse_shpextfl,
)

from ._helpers import make_chunk, make_bmplstst


def _make_shphead1(flags=0, lock_user="", file_id_num=0, num_verts=0,
                   num_polys=0, radius=0.0, version_no=0, obj_names=None):
    data = bytearray(68)
    struct.pack_into("<i", data, 0, flags)
    lock = lock_user.encode('ascii')[:15]
    data[4:4 + len(lock)] = lock
    struct.pack_into("<i", data, 20, file_id_num)
    struct.pack_into("<i", data, 24, num_verts)
    struct.pack_into("<i", data, 28, num_polys)
    struct.pack_into("<f", data, 32, radius)
    struct.pack_into("<i", data, 60, version_no)
    names = obj_names or []
    struct.pack_into("<i", data, 64, len(names))
    out = bytes(data)
    for nm in names:
        out += nm.encode('ascii') + b'\x00'
    return out


def _make_objhead1(flags=0, pos=(0, 0, 0), quat=(0.0, 0.0, 0.0, 1.0),
                   index_num=0, shape_id=-1, name=""):
    name_b = name.encode('ascii') + b'\x00'
    data = bytearray(60 + len(name_b))
    struct.pack_into("<i", data, 0, flags)
    struct.pack_into("<iii", data, 20, *pos)
    struct.pack_into("<ffff", data, 32, *quat)
    struct.pack_into("<i", data, 48, index_num)
    struct.pack_into("<i", data, 56, shape_id)
    data[60:60 + len(name_b)] = name_b
    return bytes(data)


class TestParseShpHead1(unittest.TestCase):
    def test_minimal(self):
        data = _make_shphead1()
        h = parse_shphead1(data)
        self.assertIsNotNone(h)
        self.assertEqual(h.flags, 0)
        self.assertEqual(h.file_id_num, 0)
        self.assertEqual(h.obj_names, [])
        self.assertEqual(h.tag, "")

    def test_all_fields(self):
        data = _make_shphead1(
            flags=0x100, lock_user="admin", file_id_num=42,
            num_verts=100, num_polys=50, radius=1.5, version_no=3,
            obj_names=["Player", "Weapon"])
        h = parse_shphead1(data)
        self.assertEqual(h.flags, 0x100)
        self.assertEqual(h.lock_user, "admin")
        self.assertEqual(h.file_id_num, 42)
        self.assertEqual(h.num_verts, 100)
        self.assertEqual(h.num_polys, 50)
        self.assertAlmostEqual(h.radius, 1.5)
        self.assertEqual(h.version_no, 3)
        self.assertEqual(h.num_as_obj, 2)
        self.assertEqual(h.obj_names, ["Player", "Weapon"])
        self.assertEqual(h.tag, "Player")

    def test_too_short_returns_none(self):
        self.assertIsNone(parse_shphead1(b"\x00" * 30))


class TestParseObjHead1(unittest.TestCase):
    def test_minimal(self):
        data = _make_objhead1()
        h = parse_objhead1(data)
        self.assertIsNotNone(h)
        self.assertEqual(h.flags, 0)
        self.assertEqual(h.pos, (0, 0, 0))
        self.assertEqual(h.shape_id, -1)
        self.assertEqual(h.tag, "")

    def test_full(self):
        data = _make_objhead1(
            flags=0x400, pos=(10, 20, 30),
            quat=(0.0, 0.0, 0.0, 1.0), index_num=7, shape_id=12,
            name="Alien01")
        h = parse_objhead1(data)
        self.assertEqual(h.flags, 0x400)
        self.assertEqual(h.pos, (10, 20, 30))
        self.assertEqual(h.index_num, 7)
        self.assertEqual(h.shape_id, 12)
        self.assertEqual(h.tag, "Alien01")

    def test_quaternion_normalized(self):
        data = _make_objhead1(quat=(0.0, 0.0, 0.0, 2.0))
        h = parse_objhead1(data)
        self.assertAlmostEqual(h.quat[3], 1.0)

    def test_zero_quaternion_falls_back_to_identity(self):
        data = _make_objhead1(quat=(0.0, 0.0, 0.0, 0.0))
        h = parse_objhead1(data)
        self.assertEqual(h.quat, (0.0, 0.0, 0.0, 1.0))

    def test_too_short_returns_none(self):
        self.assertIsNone(parse_objhead1(b"\x00" * 30))


class TestParseShpExtFl(unittest.TestCase):
    def test_empty_payload(self):
        # 5.7.0: caller is responsible for the `ext_fl is not None` check.
        result = parse_shpextfl(b"")
        self.assertIsNone(result.riff_name)
        self.assertEqual(result.bitmaps, {})

    def test_garbage_payload(self):
        # parse_chunks returns [] for empty bytes and None for garbage.
        # Either way ShpExtFl must be empty, never raise.
        result = parse_shpextfl(b"\xff" * 40)
        self.assertIsNone(result.riff_name)
        self.assertEqual(result.bitmaps, {})

    def test_with_riffname_and_bitmaps(self):
        inner = make_chunk(Chunk.RIFFNAME, b"Weapons.rif\x00")
        inner += make_chunk(Chunk.BMPLSTST,
                            make_bmplstst([(5, 0, 0x7, "Tex\\pulse.png")]))
        result = parse_shpextfl(inner)
        self.assertEqual(result.riff_name, "Weapons.rif")
        self.assertEqual(set(result.bitmaps.keys()), {5})
        self.assertEqual(result.bitmaps[5].name, "pulse")

    def test_riffname_only(self):
        inner = make_chunk(Chunk.RIFFNAME, b"Only.rif\x00")
        result = parse_shpextfl(inner)
        self.assertEqual(result.riff_name, "Only.rif")
        self.assertEqual(result.bitmaps, {})


if __name__ == "__main__":
    unittest.main()