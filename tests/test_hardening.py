"""R1/R3 hardening tests: parse_obanalls sanity caps and parse_chunks
chunk-size validation."""

from __future__ import annotations

import struct
import unittest

from avp_rif_importer.chunks import parse_chunks
from avp_rif_importer.parsers.char_anim import parse_obanalls, FRAME_SIZE


def _obanalls(num_sequences, sequences=b""):
    return struct.pack("<i", num_sequences) + sequences


def _seq_header(n_frames, seq_num=0, sub_num=0, seq_time=100):
    return struct.pack("<iiii", n_frames, seq_num, sub_num, seq_time)


def _seq(n_frames, seq_num=0, sub_num=0, seq_time=100, frames=None):
    hdr = _seq_header(n_frames, seq_num, sub_num, seq_time)
    if frames is None:
        frames = b"\x00" * (n_frames * FRAME_SIZE)
    return hdr + frames


class TestParseObanallsLimits(unittest.TestCase):
    def test_zero_sequences_ok(self):
        p = parse_obanalls(_obanalls(0))
        self.assertIsNotNone(p)
        self.assertEqual(p.num_sequences, 0)
        self.assertEqual(p.sequences, [])

    def test_implausible_num_sequences_rejected(self):
        # 0x7FFFFFFF cannot possibly fit; must bail immediately.
        bad = struct.pack("<i", 0x7FFFFFFF)
        self.assertIsNone(parse_obanalls(bad))

    def test_negative_num_sequences_rejected(self):
        self.assertIsNone(parse_obanalls(struct.pack("<i", -1)))

    def test_implausible_num_frames_rejected(self):
        # Header only - the parser must reject the count before any
        # frame bytes are read, so the test builds no frames at all
        # (allocating 0x7FFFFFFF * 36 B would blow up the test runner).
        payload = _obanalls(1, _seq_header(0x7FFFFFFF))
        self.assertIsNone(parse_obanalls(payload))

    def test_truncated_frames_rejected(self):
        # 1 sequence claims 10 frames but only 2 are present.
        payload = _obanalls(1, _seq(10, frames=b"\x00" * (2 * FRAME_SIZE)))
        self.assertIsNone(parse_obanalls(payload))

    def test_well_formed_still_parses(self):
        payload = _obanalls(1, _seq(1, seq_num=2, sub_num=3, seq_time=500))
        p = parse_obanalls(payload)
        self.assertIsNotNone(p)
        self.assertEqual(p.num_sequences, 1)
        self.assertEqual(len(p.sequences), 1)
        s = p.sequences[0]
        self.assertEqual(s.sequence_number, 2)
        self.assertEqual(s.sub_sequence_number, 3)
        self.assertEqual(s.sequence_time, 500)
        self.assertEqual(len(s.frames), 1)


def _chunk(cid: str, payload: bytes) -> bytes:
    cid_b = cid.encode("ascii")[:8].ljust(8, b"\x00")
    return cid_b + struct.pack("<i", 12 + len(payload)) + payload


class TestParseChunksSizeValidation(unittest.TestCase):
    def test_size_below_12_returns_none(self):
        # id + size=4 (which is < 12) - no payload.
        data = b"ABCD\x00\x00\x00\x00" + struct.pack("<i", 4)
        self.assertIsNone(parse_chunks(data, quiet=True))

    def test_size_exceeds_stream_returns_none(self):
        # Header declares 212 B but only 8 B of payload follow.
        cid_b = b"ABCD\x00\x00\x00\x00"
        data = cid_b + struct.pack("<i", 212) + b"\x00" * 8
        self.assertIsNone(parse_chunks(data, quiet=True))

    def test_valid_chunk_still_parses(self):
        data = _chunk("ABCD", b"hello")
        chunks = parse_chunks(data, quiet=True)
        self.assertIsNotNone(chunks)
        self.assertEqual(chunks, [("ABCD", b"hello")])


if __name__ == "__main__":
    unittest.main()