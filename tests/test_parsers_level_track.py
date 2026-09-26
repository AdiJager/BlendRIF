"""Tests for parsers.level_track (OBJTRAK2).

Layout locked in from the AvP (1999) dev kit (track.c) and Derelict.RIF
hex dumps: 88 B payload for 1 section, 240 B for 3. Section = 76 B,
trailer = 8 B (flags + timer_start).

The parser is deliberately lenient on truncated streams ("parse what
fits") and strict on the header count (rejects negative and >MAX_SECTIONS).
These tests lock both behaviours in.

Note on MIN_PAYLOAD: it equals 4 + SECTION_SIZE + TAIL_SIZE (88 B), so
"header with zero sections" is impossible by construction - any payload
that passes the size guard already has room for exactly one section
plus the trailer. Tests below reflect that.
"""

from __future__ import annotations

import struct
import unittest

from avp_rif_importer.parsers.level_track import (
    parse_objtrak2,
    MAX_SECTIONS,
    MIN_PAYLOAD,
    SECTION_SIZE,
    TAIL_SIZE,
)


# --------------------------------------------------------------- helpers

def _section(qs=(1.0, 0.0, 0.0, 0.0),
             qe=(0.0, 1.0, 0.0, 0.0),
             ps=(0, 0, 0),
             pe=(100, 0, 0),
             oo=(1, 2, 3),
             tfs=10,
             spare=0):
    """Build one 76-byte OBJTRAK2 section."""
    return (
        struct.pack("<4f", *qs)
        + struct.pack("<4f", *qe)
        + struct.pack("<3i", *ps)
        + struct.pack("<3i", *pe)
        + struct.pack("<3i", *oo)
        + struct.pack("<i", tfs)
        + struct.pack("<i", spare)
    )


def _payload(num_sections, sections_bytes=b"", flags=0, timer_start=0):
    """Build a full OBJTRAK2 payload (header + sections + trailer),
    padded up to MIN_PAYLOAD so the parser's size guard passes."""
    body = (struct.pack("<i", num_sections)
            + sections_bytes
            + struct.pack("<ii", flags, timer_start))
    if len(body) < MIN_PAYLOAD:
        body += b"\x00" * (MIN_PAYLOAD - len(body))
    return body


# --------------------------------------------------------- layout sanity

class TestLayoutConstants(unittest.TestCase):
    def test_section_tail_min_payload(self):
        # track.c: section = 4*4 + 4*4 + 3*4 + 3*4 + 3*4 + 4 + 4 = 76 B.
        self.assertEqual(SECTION_SIZE, 76)
        self.assertEqual(TAIL_SIZE, 8)
        self.assertEqual(MIN_PAYLOAD, 4 + SECTION_SIZE + TAIL_SIZE)


# --------------------------------------------------------- well-formed

class TestParseObjtrak2WellFormed(unittest.TestCase):
    def test_single_section_roundtrip(self):
        sec = _section(
            qs=(1.0, 0.0, 0.0, 0.0),
            qe=(0.0, 1.0, 0.0, 0.0),
            ps=(-10, -20, -30),
            pe=(40, 50, 60),
            oo=(1, 2, 3),
            tfs=123,
            spare=456,
        )
        p = parse_objtrak2(_payload(1, sec, flags=0x12345678,
                                    timer_start=0x1234))
        self.assertIsNotNone(p)
        self.assertEqual(p.num_sections, 1)
        self.assertEqual(len(p.sections), 1)
        s = p.sections[0]
        self.assertEqual(s.quat_start, (1.0, 0.0, 0.0, 0.0))
        self.assertEqual(s.quat_end,   (0.0, 1.0, 0.0, 0.0))
        self.assertEqual(s.pivot_start, (-10, -20, -30))
        self.assertEqual(s.pivot_end,   (40, 50, 60))
        self.assertEqual(s.object_offset, (1, 2, 3))
        self.assertEqual(s.time_for_section, 123)
        self.assertEqual(s.spare, 456)
        self.assertEqual(p.flags, 0x12345678)
        self.assertEqual(p.timer_start, 0x1234)

    def test_three_sections(self):
        body = (_section(ps=(0, 0, 0), pe=(10, 0, 0)) +
                _section(ps=(10, 0, 0), pe=(20, 0, 0)) +
                _section(ps=(20, 0, 0), pe=(30, 0, 0)))
        p = parse_objtrak2(_payload(3, body, flags=1, timer_start=99))
        self.assertIsNotNone(p)
        self.assertEqual(p.num_sections, 3)
        self.assertEqual([s.pivot_start[0] for s in p.sections],
                         [0, 10, 20])
        self.assertEqual([s.pivot_end[0] for s in p.sections],
                         [10, 20, 30])

    def test_zero_sections_with_trailer(self):
        p = parse_objtrak2(_payload(0, b"", flags=7, timer_start=42))
        self.assertIsNotNone(p)
        self.assertEqual(p.num_sections, 0)
        self.assertEqual(p.sections, [])
        self.assertEqual(p.flags, 7)
        self.assertEqual(p.timer_start, 42)

    def test_zero_time_for_section(self):
        # Shipped RIFs commonly store 0 here; runtime derives the
        # duration from the surrounding track controller.
        p = parse_objtrak2(_payload(1, _section(tfs=0)))
        self.assertIsNotNone(p)
        self.assertEqual(p.sections[0].time_for_section, 0)

    def test_negative_pivot_values(self):
        p = parse_objtrak2(_payload(
            1, _section(ps=(-1, -2, -3), pe=(-4, -5, -6))))
        self.assertEqual(p.sections[0].pivot_start, (-1, -2, -3))
        self.assertEqual(p.sections[0].pivot_end,   (-4, -5, -6))


# --------------------------------------------------------------- reject

class TestParseObjtrak2Rejection(unittest.TestCase):
    def test_empty_input(self):
        self.assertIsNone(parse_objtrak2(b""))

    def test_shorter_than_min_payload(self):
        # 4 B num + 8 B trailer = 12 B, below MIN_PAYLOAD (88).
        self.assertIsNone(parse_objtrak2(
            struct.pack("<i", 0) + struct.pack("<ii", 0, 0)))
        # One byte short of MIN_PAYLOAD.
        self.assertIsNone(parse_objtrak2(b"\x00" * (MIN_PAYLOAD - 1)))

    def test_negative_num_sections(self):
        bad = struct.pack("<i", -1) + b"\x00" * (MIN_PAYLOAD - 4)
        self.assertIsNone(parse_objtrak2(bad))

    def test_implausible_num_sections(self):
        bad = (struct.pack("<i", MAX_SECTIONS + 1)
               + b"\x00" * (MIN_PAYLOAD - 4))
        self.assertIsNone(parse_objtrak2(bad))

    def test_header_only_below_min_payload_rejected(self):
        # Not a real scenario, but locks the invariant: anything smaller
        # than MIN_PAYLOAD is rejected before num_sections is even read.
        self.assertIsNone(parse_objtrak2(struct.pack("<i", MAX_SECTIONS)))

    def test_max_sections_accepted_with_partial_payload(self):
        # MAX_SECTIONS is a legal count - it must NOT be rejected. With
        # only MIN_PAYLOAD bytes we can fit exactly 1 section + trailer,
        # so the parser returns num_sections=MAX_SECTIONS but a short
        # sections list ("parse what fits"). Header-only is impossible
        # by construction: MIN_PAYLOAD already accounts for 1 section.
        bad = (struct.pack("<i", MAX_SECTIONS)
               + b"\x00" * (MIN_PAYLOAD - 4))
        p = parse_objtrak2(bad)
        self.assertIsNotNone(p)
        self.assertEqual(p.num_sections, MAX_SECTIONS)
        self.assertEqual(len(p.sections), 1)
        self.assertEqual(p.sections[0].pivot_end, (0, 0, 0))


# ----------------------------------------------------------- truncation

class TestParseObjtrak2Truncation(unittest.TestCase):
    def test_fewer_sections_than_declared(self):
        # Header claims 3, only 1 whole section fits before the tail.
        sec = _section(ps=(0, 0, 0), pe=(7, 7, 7))
        payload = (struct.pack("<i", 3)
                   + sec
                   + b"\x00" * 2                    # partial 2nd section
                   + struct.pack("<ii", 11, 22))    # trailer
        if len(payload) < MIN_PAYLOAD:
            payload += b"\x00" * (MIN_PAYLOAD - len(payload))
        p = parse_objtrak2(payload)
        self.assertIsNotNone(p)
        self.assertEqual(p.num_sections, 3)
        self.assertEqual(len(p.sections), 1)
        self.assertEqual(p.sections[0].pivot_end, (7, 7, 7))

    def test_partial_section_dropped(self):
        # Header claims 2, only 1 whole section is present.
        sec = _section(pe=(99, 99, 99))
        payload = (struct.pack("<i", 2)
                   + sec
                   + b"\x00" * 4)
        if len(payload) < MIN_PAYLOAD:
            payload += b"\x00" * (MIN_PAYLOAD - len(payload))
        p = parse_objtrak2(payload)
        self.assertIsNotNone(p)
        self.assertEqual(p.num_sections, 2)
        self.assertEqual(len(p.sections), 1)
        self.assertEqual(p.sections[0].pivot_end, (99, 99, 99))

    def test_trailer_from_leftover_bytes(self):
        # 2 declared, exactly 1 section + 8 stray bytes; the parser
        # reads those 8 as flags/timer_start. Documents the lenient
        # behaviour: no exception, no None, just best-effort trailer.
        sec = _section(pe=(1, 2, 3))
        payload = (struct.pack("<i", 2)
                   + sec
                   + struct.pack("<ii", 0xAA, 0xBB))
        p = parse_objtrak2(payload)
        self.assertIsNotNone(p)
        self.assertEqual(len(p.sections), 1)
        self.assertEqual(p.flags, 0xAA)
        self.assertEqual(p.timer_start, 0xBB)


if __name__ == "__main__":
    unittest.main()