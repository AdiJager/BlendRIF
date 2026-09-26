"""Shared byte-builders for synthetic RIF structures.

Everything here builds bytes; nothing imports bpy. Test modules combine
these helpers with the parsers they exercise.
"""

from __future__ import annotations

import struct


def cstr(s: str) -> bytes:
    """ASCII string + NUL terminator."""
    return s.encode('ascii') + b'\x00'


def pad4(data: bytes) -> bytes:
    """Pad to the next 4-byte boundary with zeros."""
    return data + b'\x00' * ((-len(data)) % 4)


def make_chunk(cid: str, payload: bytes) -> bytes:
    """Build one chunk: 8-byte ID (padded) + int32 size + payload.

    `size` includes the 12-byte header, matching parse_chunks' contract.
    """
    cid_bytes = cid.encode('ascii')[:8].ljust(8, b'\x00')
    total = 12 + len(payload)
    return cid_bytes + struct.pack("<i", total) + payload


def make_chunk_raw(cid_bytes: bytes, payload: bytes) -> bytes:
    """Same as make_chunk but caller supplies the raw 8-byte ID field.

    Useful for building malformed IDs (padding, wrong length) in
    negative tests.
    """
    assert len(cid_bytes) == 8
    total = 12 + len(payload)
    return cid_bytes + struct.pack("<i", total) + payload


def make_bmplstst(entries) -> bytes:
    """Build a BMPLSTST payload.

    entries: list of (index, flags, d1, raw_name).
      - index: uint32
      - flags: uint32
      - d1:    uint32, version = d1 & 0xFFFFF, enum_id = (d1 >> 20) & 0xFFF
      - raw_name: game path string (backslashes or forward slashes)
    """
    out = bytearray()
    out += struct.pack("<I", len(entries))
    for idx, flags, d1, name in entries:
        out += struct.pack("<III", flags, idx, d1)
        out += b'\x00' * 8          # reserved
        out += cstr(name)
        while len(out) % 4:
            out += b'\x00'
    return bytes(out)