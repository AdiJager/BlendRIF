"""Tests for chunks.parse_chunks / find_all_chunks / walk_chunks and the
typed collectors collect_rebshape / collect_rbobject (A5, 5.7.0)."""

from __future__ import annotations

import unittest

from avp_rif_importer.chunks import (
    parse_chunks, find_all_chunks, walk_chunks,
    collect_rebshape, collect_rbobject,
    ShapeGroup, ObjectGroup,
)
from avp_rif_importer.chunk_ids import Chunk

from ._helpers import make_chunk


class TestParseChunks(unittest.TestCase):
    def test_single_chunk(self):
        stream = make_chunk("TEST", b"hello")
        self.assertEqual(parse_chunks(stream), [("TEST", b"hello")])

    def test_multiple_chunks(self):
        stream = make_chunk("ONE", b"a") + make_chunk("TWO", b"bb")
        self.assertEqual(parse_chunks(stream),
                         [("ONE", b"a"), ("TWO", b"bb")])

    def test_empty_payload(self):
        stream = make_chunk("EMPTY", b"")
        self.assertEqual(parse_chunks(stream), [("EMPTY", b"")])

    def test_stream_shorter_than_12_bytes_returns_none(self):
        self.assertIsNone(parse_chunks(b"\x00" * 5))

    def test_trailing_tolerance(self):
        stream = make_chunk("TEST", b"x") + b"\x00\x00\x00"
        self.assertEqual(parse_chunks(stream), [("TEST", b"x")])

    def test_trailing_too_long_returns_none(self):
        stream = make_chunk("TEST", b"x") + b"\x00" * 100
        self.assertIsNone(parse_chunks(stream))


class TestResync(unittest.TestCase):
    def test_resync_skips_garbage(self):
        stream = b"\xff\xff\xff" + make_chunk("GOOD", b"payload")
        self.assertEqual(parse_chunks(stream), [("GOOD", b"payload")])

    def test_resync_disabled_returns_none(self):
        stream = b"\xff\xff\xff" + make_chunk("GOOD", b"payload")
        self.assertIsNone(parse_chunks(stream, resync_max=0))

    def test_negative_size_rejected(self):
        import struct
        bad = b"CHUNK\x00\x00\x00" + struct.pack("<i", -5)
        self.assertIsNone(parse_chunks(bad, resync_max=0))


class TestFindAllChunks(unittest.TestCase):
    def test_top_level_match(self):
        stream = make_chunk("TARGET", b"payload")
        self.assertEqual(find_all_chunks(stream, "TARGET"), [b"payload"])

    def test_nested_match(self):
        inner = make_chunk("TARGET", b"deep")
        outer = make_chunk("CONTAINER", inner)
        self.assertEqual(find_all_chunks(outer, "TARGET"), [b"deep"])

    def test_multiple_matches(self):
        stream = (make_chunk("TARGET", b"1") +
                  make_chunk("OTHER",  b"x") +
                  make_chunk("TARGET", b"2"))
        self.assertEqual(find_all_chunks(stream, "TARGET"), [b"1", b"2"])

    def test_no_match_returns_empty(self):
        stream = make_chunk("OTHER", b"x")
        self.assertEqual(find_all_chunks(stream, "TARGET"), [])


class TestWalkChunks(unittest.TestCase):
    def test_collects_siblings_at_stop_condition(self):
        inner = (make_chunk(Chunk.SHPHEAD1, b"A") +
                 make_chunk(Chunk.SHPRAWVT, b"B"))
        stream = make_chunk("CONTAINER", inner)
        groups = walk_chunks(stream,
                             lambda ids: Chunk.SHPRAWVT in ids)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][Chunk.SHPHEAD1], [b"A"])
        self.assertEqual(groups[0][Chunk.SHPRAWVT], [b"B"])

    def test_multiple_groups(self):
        g1 = (make_chunk(Chunk.SHPHEAD1, b"1") +
              make_chunk(Chunk.SHPRAWVT, b"a"))
        g2 = (make_chunk(Chunk.SHPHEAD1, b"2") +
              make_chunk(Chunk.SHPRAWVT, b"b"))
        stream = make_chunk("C1", g1) + make_chunk("C2", g2)
        groups = walk_chunks(stream, lambda ids: Chunk.SHPRAWVT in ids)
        self.assertEqual(len(groups), 2)

    def test_no_match_returns_empty(self):
        stream = make_chunk("EMPTY", b"")
        groups = walk_chunks(stream, lambda ids: "NEVER" in ids)
        self.assertEqual(groups, [])


class TestCollectRebshape(unittest.TestCase):
    """A5, 5.7.0: collect_rebshape returns list[ShapeGroup]."""

    def test_full_shape(self):
        inner = (make_chunk(Chunk.SHPHEAD1, b"HEAD") +
                 make_chunk(Chunk.SHPRAWVT, b"VERTS") +
                 make_chunk(Chunk.SHPPOLYS, b"POLYS") +
                 make_chunk(Chunk.SHPUVCRD, b"UVS") +
                 make_chunk(Chunk.SHPEXTFL, b"EXT"))
        stream = make_chunk("CONTAINER", inner)
        groups = collect_rebshape(stream)
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertIsInstance(g, ShapeGroup)
        self.assertEqual(g.head, b"HEAD")
        self.assertEqual(g.raw_verts, b"VERTS")
        self.assertEqual(g.polys, b"POLYS")
        self.assertEqual(g.uvcrds, b"UVS")
        self.assertEqual(g.ext_fl, b"EXT")

    def test_orphan_shape_no_head(self):
        # SHPRAWVT without SHPHEAD1 -> still collected, head is None.
        inner = make_chunk(Chunk.SHPRAWVT, b"VERTS")
        stream = make_chunk("CONTAINER", inner)
        groups = collect_rebshape(stream)
        self.assertEqual(len(groups), 1)
        self.assertIsNone(groups[0].head)
        self.assertEqual(groups[0].raw_verts, b"VERTS")

    def test_missing_optional_chunks_become_none(self):
        inner = (make_chunk(Chunk.SHPHEAD1, b"H") +
                 make_chunk(Chunk.SHPRAWVT, b"V"))
        stream = make_chunk("CONTAINER", inner)
        g = collect_rebshape(stream)[0]
        self.assertIsNone(g.polys)
        self.assertIsNone(g.uvcrds)
        self.assertIsNone(g.ext_fl)

    def test_no_shapes_returns_empty(self):
        stream = make_chunk("EMPTY", b"")
        self.assertEqual(collect_rebshape(stream), [])


class TestCollectRbobject(unittest.TestCase):
    """A5, 5.7.0: collect_rbobject returns list[ObjectGroup]."""

    def test_single_object(self):
        inner = make_chunk(Chunk.OBJHEAD1, b"OBJ")
        stream = make_chunk("CONTAINER", inner)
        groups = collect_rbobject(stream)
        self.assertEqual(len(groups), 1)
        self.assertIsInstance(groups[0], ObjectGroup)
        self.assertEqual(groups[0].head, b"OBJ")

    def test_multiple_objects(self):
        stream = (make_chunk("C1", make_chunk(Chunk.OBJHEAD1, b"O1")) +
                  make_chunk("C2", make_chunk(Chunk.OBJHEAD1, b"O2")))
        groups = collect_rbobject(stream)
        self.assertEqual([g.head for g in groups], [b"O1", b"O2"])

    def test_no_objects_returns_empty(self):
        stream = make_chunk("EMPTY", b"")
        self.assertEqual(collect_rbobject(stream), [])


if __name__ == "__main__":
    unittest.main()