# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Parser for RFFL fastfile archives (.ffl) used by AvP (1999).

Header layout (little-endian, 20 bytes):
    magic(4) "RFFL" | version(4) | num_files(4) | header_size(4) |
    data_size(4)
Per-entry layout inside the header region:
    offset(4) | length(4) | filename (NULL-terminated) | pad to 4 bytes
Offsets are relative to the start of the data region
(20 + header_size). This matches Ffread.cpp / FFREAD.HPP.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct

RFFL_MAGIC = b"RFFL"
RFFL_HEADER_SIZE = 20
_MAX_FILES = 100_000
_MAX_DIR_LEN = 10_000_000


@dataclass(frozen=True)
class RFEntry:
    """One file inside an RFFL archive."""
    offset: int
    length: int
    name: str


@dataclass(frozen=True)
class RFArchive:
    """Parsed RFFL header with the directory and the data region start."""
    num_files: int
    dir_len: int
    entries: tuple[RFEntry, ...]
    data_start: int


def parse_rffl(data: bytes) -> RFArchive | None:
    """Parse the RFFL header; returns None when data is not an archive."""
    if len(data) < RFFL_HEADER_SIZE or data[:4] != RFFL_MAGIC:
        return None
    num_files = struct.unpack_from("<I", data, 8)[0]
    dir_len = struct.unpack_from("<I", data, 12)[0]
    if num_files > _MAX_FILES or dir_len > _MAX_DIR_LEN:
        return None
    dir_start = RFFL_HEADER_SIZE
    dir_end = dir_start + dir_len
    if dir_end > len(data):
        return None

    entries: list[RFEntry] = []
    pos = dir_start
    for _ in range(num_files):
        if pos + 8 > dir_end:
            break
        offset = struct.unpack_from("<I", data, pos)[0]
        length = struct.unpack_from("<I", data, pos + 4)[0]
        pos += 8
        name_end = data.find(b"\x00", pos, dir_end)
        if name_end < 0:
            break
        name = data[pos:name_end].decode("ascii", errors="replace")
        pos = name_end + 1
        while (pos - dir_start) % 4 != 0 and pos < dir_end:
            pos += 1
        entries.append(RFEntry(offset=offset, length=length, name=name))

    return RFArchive(
        num_files=num_files,
        dir_len=dir_len,
        entries=tuple(entries),
        data_start=dir_end,
    )