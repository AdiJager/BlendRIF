"""Tests for the morph-target parsers (SHPMORPH / SUBSHAPE / SUBSHPHD).

A REBSHAPE that morphs carries SHPMORPH next to its own geometry. The
payload holds one SUBSHAPE per morph target plus a FRMMORPH frame list;
only the target geometry is parsed, and the importer imports it only
when the (default-off) "Import Morph" option is enabled.

Layout locked in from SHPCHUNK.CPP and the shipped levels: SUBSHAPE
holds SUBSHPHD (44 B header), SHPCENTR, SHPRAWVT, SHPVNORM, SHPPNORM,
SHPPOLYS and SHPUVCRD.
"""

from __future__ import annotations

import struct
import unittest

from avp_rif_importer.parsers.shapes import (
    parse_subshphead,
    parse_shpmorph,
    SubShapeHead,
    SUBSHPHD_SIZE,
)
from avp_rif_importer.chunk_ids import Chunk

from ._helpers import cstr, make_chunk


def _subshphead(flags=0, file_id=0, num_verts=4, num_polys=1, radius=1.5,
                max_e=(10, 20, 30), min_e=(-10, -20, -30)):
    """Build one 44-byte SUBSHPHD payload."""
    return (struct.pack("<iiii", flags, file_id, num_verts, num_polys)
            + struct.pack("<f", radius)
            + struct.pack("<6i", max_e[0], min_e[0], max_e[1], min_e[1],
                          max_e[2], min_e[2]))


def _subshape(file_id=7, num_verts=4, num_polys=2):
    """Build one SUBSHAPE chunk with a header and (dummy) geometry."""
    head = _subshphead(file_id=file_id, num_verts=num_verts,
                       num_polys=num_polys)
    raw = struct.pack("<i", num_verts) + b"\x01" * (12 * num_verts)
    polys = struct.pack("<i", num_polys) + b"\x02" * (36 * num_polys)
    uvs = struct.pack("<i", num_verts) + b"\x03" * (8 * num_verts)
    return make_chunk(Chunk.SUBSHAPE, (
        make_chunk(Chunk.SUBSHPHD, head)
        + make_chunk("SHPCENTR", struct.pack("<4i", 0, 0, 0, 0))
        + make_chunk(Chunk.SHPRAWVT, raw)
        + make_chunk(Chunk.SHPPOLYS, polys)
        + make_chunk(Chunk.SHPUVCRD, uvs)
    ))


def _shpmorph_payload(num_frames=1, subs=1):
    """Build the payload of one SHPMORPH chunk."""
    frames = b"".join(
        struct.pack("<4i", 0, 65536, 1, -1) for _ in range(num_frames)
    )
    body = make_chunk(Chunk.FRMMORPH, frames)
    body += b"".join(_subshape(file_id=10 + i) for i in range(subs))
    return body


def _shpmorph_chunk(num_frames=1, subs=1):
    """Build one complete SHPMORPH chunk (header included)."""
    return make_chunk(Chunk.SHPMORPH, _shpmorph_payload(num_frames, subs))


class TestParseSubShapeHead(unittest.TestCase):
    """The 44-byte sub-shape header carries counts and extents."""

    def test_fields(self):
        data = _subshphead(flags=3, file_id=1234, num_verts=8, num_polys=5,
                           radius=2.5, max_e=(1, 2, 3), min_e=(-1, -2, -3))
        h = parse_subshphead(data)
        self.assertIsNotNone(h)
        self.assertIsInstance(h, SubShapeHead)
        self.assertEqual(h.flags, 3)
        self.assertEqual(h.file_id_num, 1234)
        self.assertEqual(h.num_verts, 8)
        self.assertEqual(h.num_polys, 5)
        self.assertAlmostEqual(h.radius, 2.5)
        self.assertEqual(h.max_extents, (1, 2, 3))
        self.assertEqual(h.min_extents, (-1, -2, -3))

    def test_size_matches_the_game(self):
        self.assertEqual(len(_subshphead()), SUBSHPHD_SIZE)
        self.assertEqual(SUBSHPHD_SIZE, 44)

    def test_too_short_returns_none(self):
        self.assertIsNone(parse_subshphead(b"\x00" * 20))
        self.assertIsNone(parse_subshphead(b""))


class TestParseShpMorph(unittest.TestCase):
    """SHPMORPH yields one ShapeGroup per SUBSHAPE target."""

    def test_single_target(self):
        groups = parse_shpmorph(_shpmorph_payload(num_frames=1, subs=1))
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertIsNotNone(g.head)
        self.assertIsNotNone(g.raw_verts)
        self.assertIsNotNone(g.polys)
        self.assertIsNotNone(g.uvcrds)
        self.assertIsNone(g.ext_fl)
        # The header is the SUBSHPHD payload and parses as such.
        head = parse_subshphead(g.head)
        self.assertEqual(head.file_id_num, 10)

    def test_two_targets_keep_order(self):
        groups = parse_shpmorph(_shpmorph_payload(subs=2))
        self.assertEqual(len(groups), 2)
        self.assertEqual([parse_subshphead(g.head).file_id_num
                          for g in groups], [10, 11])

    def test_frames_are_not_returned_as_targets(self):
        """The FRMMORPH frame list is metadata, not geometry."""
        groups = parse_shpmorph(_shpmorph_payload(num_frames=3, subs=1))
        self.assertEqual(len(groups), 1)

    def test_empty_payload(self):
        self.assertEqual(parse_shpmorph(b""), [])
        self.assertEqual(parse_shpmorph(make_chunk(
            "OTHERCHK", b"")), [])

    def test_garbage_payload_does_not_raise(self):
        # Not parseable as chunks at all.
        self.assertEqual(parse_shpmorph(b"\xff" * 32), [])

    def test_subshape_without_geometry_is_kept_but_empty(self):
        sub = make_chunk(Chunk.SUBSHAPE, make_chunk(
            Chunk.SUBSHPHD, _subshphead()))
        groups = parse_shpmorph(sub)
        self.assertEqual(len(groups), 1)
        self.assertIsNone(groups[0].raw_verts)
        self.assertIsNone(groups[0].polys)


class TestMorphInScan(unittest.TestCase):
    """The scanner groups morph targets with their parent shape."""

    def test_scan_finds_group_with_parent_tag(self):
        from avp_rif_importer.scan import RifScanner

        # SHPHEAD1 is 60 bytes of fixed fields plus version/count/names.
        head = (struct.pack("<i", 0) + b"\x00" * 16
                + struct.pack("<iiif", 77, 4, 1, 1.0) + b"\x00" * 24)
        head += struct.pack("<ii", 0, 1) + cstr("door")
        shape = make_chunk(Chunk.SHPHEAD1, head)
        shape += make_chunk(Chunk.SHPRAWVT, struct.pack("<i", 4) + b"\x00" * 48)
        shape += _shpmorph_chunk(subs=2)
        stream = make_chunk("REBINFF2", make_chunk("REBSHAPE", shape))

        scan = RifScanner(fallback_level_name="test").scan(stream)
        self.assertEqual(len(scan.morph_groups), 1)
        grp = scan.morph_groups[0]
        self.assertEqual(grp.parent_tag, "door")
        self.assertEqual(grp.parent_shape_id, 77)
        self.assertEqual(len(grp.subs), 2)

    def test_scan_without_morph_data(self):
        from avp_rif_importer.scan import RifScanner

        head = (struct.pack("<i", 0) + b"\x00" * 16
                + struct.pack("<iiif", 5, 0, 0, 1.0) + b"\x00" * 24)
        shape = make_chunk(Chunk.SHPHEAD1, head)
        stream = make_chunk("REBINFF2", make_chunk("REBSHAPE", shape))
        scan = RifScanner(fallback_level_name="test").scan(stream)
        self.assertEqual(scan.morph_groups, [])


class TestMorphCollectionGroup(unittest.TestCase):
    """The Morphs subcollection is registered and opt-in."""

    def test_group_and_optional_flag(self):
        from avp_rif_importer.config import (
            COLLECTION_GROUPS, OPTIONAL_COLLECTION_GROUPS,
        )
        self.assertEqual(COLLECTION_GROUPS.get("morphs"), "Morphs")
        self.assertIn("morphs", OPTIONAL_COLLECTION_GROUPS)


if __name__ == "__main__":
    unittest.main()

