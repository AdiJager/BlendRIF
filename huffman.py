# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""RIF Huffman decompression for REBCRIF1-compressed payloads.

Takes the raw bytes of a .RIF file and returns the uncompressed chunk
stream that every later import stage consumes. The compressed format is
a canonical Huffman code with a fixed 328-byte header:
    magic(8) + cs(4) + us(4) + counts[11](44) + ba[256]
`counts` is a histogram of code lengths, `ba` is the symbol alphabet in
canonical order.

`sum(counts)` is the alphabet size (typically 256 or 257), not a byte
count, and must not be compared with `us` (the uncompressed size in
bytes).
"""

from __future__ import annotations

import struct

from .config import MAX_DEPTH, HUFFMAN_HEADER_SIZE
from .utils import log


# LSB-first bitstream: reverse every byte so we can consume MSB-first.
_REVERSE = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def read_huffman_header(data: bytes):
    """Parse the fixed-size REBCRIF1 header into (cs, us, counts, ba)."""
    # Caller has already validated the magic; skip it.
    offset = 8
    cs, us = struct.unpack_from("<ii", data, offset)
    offset += 8
    counts = list(struct.unpack_from(f"<{MAX_DEPTH}i", data, offset))
    offset += MAX_DEPTH * 4
    ba = list(data[offset:offset + 256])
    return cs, us, counts, ba


# ---------------------------------------------------------------------------
# Code table
# ---------------------------------------------------------------------------

def build_lookup(counts, ba):
    """Build a {(length, code): symbol} table from the header."""
    # Canonical order: shortest codes first, ba consumed from index 255 down.
    lookup = {}
    code = 0
    sym_idx = 255
    for length in range(1, MAX_DEPTH + 1):
        for _ in range(counts[length - 1]):
            if 0 <= sym_idx < 256:
                lookup[(length, code)] = ba[sym_idx]
            sym_idx -= 1
            code += 1
        code <<= 1
    return lookup


# ---------------------------------------------------------------------------
# Bitstream
# ---------------------------------------------------------------------------

def huffman_decode(compressed: bytes, lookup, uncompressed_size: int):
    """Decode `compressed` into `uncompressed_size` bytes; returns (bytes, truncated)."""
    output = bytearray()
    buf = 0
    bit_count = 0
    pos = 0
    truncated = False
    while len(output) < uncompressed_size and pos <= len(compressed):
        # Top up to MAX_DEPTH bits - always enough to match one code.
        while bit_count < MAX_DEPTH and pos < len(compressed):
            buf = (buf << 8) | _REVERSE[compressed[pos]]
            bit_count += 8
            pos += 1
        if bit_count == 0:
            truncated = True
            break
        # Try shortest codes first; the code is prefix-free.
        matched = False
        for depth in range(1, min(bit_count, MAX_DEPTH) + 1):
            shift = bit_count - depth
            code = (buf >> shift) & ((1 << depth) - 1)
            if (depth, code) in lookup:
                output.append(lookup[(depth, code)])
                buf &= (1 << shift) - 1
                bit_count = shift
                matched = True
                break
        if not matched:
            truncated = True
            break
    return bytes(output), truncated


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def decompress_rif(raw: bytes) -> bytes:
    """Decompress a REBCRIF1 payload; raises ValueError on malformed input."""
    if len(raw) < HUFFMAN_HEADER_SIZE:
        raise ValueError(
            f"RIF too short for Huffman header: {len(raw)} < {HUFFMAN_HEADER_SIZE}")

    cs, us, counts, ba = read_huffman_header(raw)

    # Negative sizes are never legitimate - fail fast with a clear message.
    if cs < 0:
        raise ValueError(f"Invalid compressed size: cs={cs}")
    if us < 0:
        raise ValueError(f"Invalid uncompressed size: us={us}")
    if HUFFMAN_HEADER_SIZE + cs > len(raw):
        raise ValueError(
            f"Compressed stream truncated: cs={cs}, "
            f"have={len(raw) - HUFFMAN_HEADER_SIZE}")

    payload = raw[HUFFMAN_HEADER_SIZE:HUFFMAN_HEADER_SIZE + cs]
    data, truncated = huffman_decode(payload, build_lookup(counts, ba), us)
    # Partial output is still usable - log and return what we have.
    if truncated or len(data) != us:
        log.warning(
            "    Huffman decode incomplete "
            f"(got {len(data)}/{us} bytes, cs={cs}, sum(counts)={sum(counts)})")
    return data