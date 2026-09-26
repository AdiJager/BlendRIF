"""Tests for the RIF Huffman decoder.

The decoder consumes a canonical code table that lives inside the REBCRIF1
header (histogram `counts` + symbol alphabet `ba`). To test round-trip we
need a small encoder - see _encode() below.
"""

from __future__ import annotations

import struct
import unittest

from avp_rif_importer.config import MAX_DEPTH, HUFFMAN_HEADER_SIZE
from avp_rif_importer.huffman import (
    read_huffman_header, build_lookup, decompress_rif,
)


def _reverse_bits(b: int) -> int:
    return int(f"{b:08b}"[::-1], 2)


def _build_rif_bytes(cs: int, us: int, counts, ba) -> bytes:
    return (
        b"REBCRIF1" +
        struct.pack("<ii", cs, us) +
        struct.pack(f"<{MAX_DEPTH}i", *counts) +
        bytes(ba)
    )


def _encode(message: bytes, lookup) -> bytes:
    """Encode `message` using the canonical code table described by `lookup`.

    The decoder reads bits MSB-first from a bit buffer that is filled by
    bit-reversing each input byte, so we pack MSB-first and then reverse
    every output byte.
    """
    code_table = {sym: (length, code) for (length, code), sym in lookup.items()}
    bits = []
    for sym in message:
        length, code = code_table[sym]
        for i in range(length - 1, -1, -1):
            bits.append((code >> i) & 1)
    while len(bits) % 8:
        bits.append(0)
    out = bytearray()
    for i in range(0, len(bits), 8):
        b = 0
        for j in range(8):
            b = (b << 1) | bits[i + j]
        out.append(_reverse_bits(b))
    return bytes(out)


def _make_rif(message: bytes, counts, ba) -> bytes:
    lookup = build_lookup(counts, ba)
    compressed = _encode(message, lookup)
    return _build_rif_bytes(len(compressed), len(message), counts, ba) \
           + compressed


def _alphabet(symbols):
    """Return (counts, ba) for a flat 1-bit-per-symbol alphabet."""
    n = len(symbols)
    counts = [n] + [0] * (MAX_DEPTH - 1)
    ba = [0] * 256
    for i, sym in enumerate(symbols):
        ba[255 - i] = sym
    return counts, ba


class TestReadHeader(unittest.TestCase):
    def test_roundtrip_of_header_fields(self):
        counts = [3] + [0] * (MAX_DEPTH - 1)
        ba = [0] * 256
        ba[255] = ord('A')
        ba[254] = ord('B')
        ba[253] = ord('C')
        raw = _build_rif_bytes(cs=99, us=42, counts=counts, ba=ba)
        cs, us, c, b = read_huffman_header(raw)
        self.assertEqual(cs, 99)
        self.assertEqual(us, 42)
        self.assertEqual(c, counts)
        self.assertEqual(b, ba)


class TestBuildLookup(unittest.TestCase):
    def test_single_symbol(self):
        counts = [1] + [0] * (MAX_DEPTH - 1)
        ba = [0] * 256
        ba[255] = 0xAB
        self.assertEqual(build_lookup(counts, ba), {(1, 0): 0xAB})

    def test_two_symbols_length_1(self):
        counts = [2] + [0] * (MAX_DEPTH - 1)
        ba = [0] * 256
        ba[255] = ord('X')
        ba[254] = ord('Y')
        self.assertEqual(build_lookup(counts, ba),
                         {(1, 0): ord('X'), (1, 1): ord('Y')})

    def test_asymmetric_1_and_2(self):
        counts = [1, 2] + [0] * (MAX_DEPTH - 2)
        ba = [0] * 256
        ba[255] = ord('A')
        ba[254] = ord('B')
        ba[253] = ord('C')
        # A -> code 0 (length 1); B -> code 10 (length 2); C -> code 11.
        self.assertEqual(build_lookup(counts, ba),
                         {(1, 0): ord('A'), (2, 2): ord('B'), (2, 3): ord('C')})


class TestRoundtrip(unittest.TestCase):
    def test_two_symbols(self):
        counts, ba = _alphabet([ord('A'), ord('B')])
        self.assertEqual(decompress_rif(_make_rif(b"ABAB", counts, ba)),
                         b"ABAB")

    def test_three_symbols_asymmetric(self):
        counts = [1, 2] + [0] * (MAX_DEPTH - 2)
        ba = [0] * 256
        ba[255] = ord('A')
        ba[254] = ord('B')
        ba[253] = ord('C')
        self.assertEqual(
            decompress_rif(_make_rif(b"AABBACAB", counts, ba)),
            b"AABBACAB")

    def test_empty_message(self):
        counts = [1] + [0] * (MAX_DEPTH - 1)
        ba = [0] * 256
        ba[255] = 0
        raw = _build_rif_bytes(0, 0, counts, ba)
        self.assertEqual(decompress_rif(raw), b"")

    def test_single_repeated_symbol(self):
        counts, ba = _alphabet([ord('Z')])
        self.assertEqual(
            decompress_rif(_make_rif(b"ZZZZZZZZ", counts, ba)),
            b"ZZZZZZZZ")


class TestTruncation(unittest.TestCase):
    def test_claiming_more_us_than_encodable(self):
        # Encode 4 bytes, then pretend uncompressed size is 20.
        counts, ba = _alphabet([ord('A'), ord('B')])
        lookup = build_lookup(counts, ba)
        compressed = _encode(b"ABAB", lookup)
        raw = _build_rif_bytes(len(compressed), 20, counts, ba) + compressed
        decoded = decompress_rif(raw)
        self.assertLess(len(decoded), 20)


class TestValidation(unittest.TestCase):
    def test_too_short(self):
        with self.assertRaises(ValueError):
            decompress_rif(b"\x00" * 10)

    def test_negative_cs(self):
        counts = [1] + [0] * (MAX_DEPTH - 1)
        with self.assertRaises(ValueError):
            decompress_rif(_build_rif_bytes(-1, 0, counts, [0] * 256))

    def test_negative_us(self):
        counts = [1] + [0] * (MAX_DEPTH - 1)
        with self.assertRaises(ValueError):
            decompress_rif(_build_rif_bytes(0, -1, counts, [0] * 256))

    def test_cs_exceeds_payload(self):
        counts = [1] + [0] * (MAX_DEPTH - 1)
        raw = _build_rif_bytes(1000, 0, counts, [0] * 256) + b"x" * 5
        with self.assertRaises(ValueError):
            decompress_rif(raw)


if __name__ == "__main__":
    unittest.main()