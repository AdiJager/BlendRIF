# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Little-endian binary reader for AvP RIF structures.

Replaces `offset += 4; struct.unpack_from(...)` chains with one call per
field. Raises struct.error on short reads so callers can keep a single
try/except clause.

strz() lands exactly at `size` (not `size + 1`) when a string is not
NUL-terminated, so a subsequent read from the same position is safe.
"""

from __future__ import annotations

import struct


class BinaryReader:
    """Sequential little-endian reader over an immutable bytes buffer."""

    __slots__ = ("data", "pos", "size")

    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos
        self.size = len(data)

    # --- internals ----------------------------------------------------
    def _need(self, n: int) -> None:
        """Raise struct.error if fewer than n bytes remain."""
        if self.pos + n > self.size:
            raise struct.error(
                f"short read at offset {self.pos} "
                f"(need {n}, have {self.size - self.pos})")

    # --- scalars ------------------------------------------------------
    def i16(self) -> int:
        """Read a signed 16-bit integer."""
        self._need(2); v = struct.unpack_from("<h", self.data, self.pos)[0]
        self.pos += 2; return v

    def u16(self) -> int:
        """Read an unsigned 16-bit integer."""
        self._need(2); v = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2; return v

    def i32(self) -> int:
        """Read a signed 32-bit integer."""
        self._need(4); v = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4; return v

    def u32(self) -> int:
        """Read an unsigned 32-bit integer."""
        self._need(4); v = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4; return v

    def f32(self) -> float:
        """Read a 32-bit float."""
        self._need(4); v = struct.unpack_from("<f", self.data, self.pos)[0]
        self.pos += 4; return v

    def f64(self) -> float:
        """Read a 64-bit float."""
        self._need(8); v = struct.unpack_from("<d", self.data, self.pos)[0]
        self.pos += 8; return v

    # --- small tuples -------------------------------------------------
    def i32x3(self) -> tuple[int, int, int]:
        """Read three consecutive i32 values."""
        self._need(12); v = struct.unpack_from("<iii", self.data, self.pos)
        self.pos += 12; return v

    def i32x9(self) -> tuple[int, ...]:
        """Read nine consecutive i32 values (e.g. a 3x3 matrix)."""
        self._need(36); v = struct.unpack_from("<9i", self.data, self.pos)
        self.pos += 36; return v

    def f32x4(self) -> tuple[float, float, float, float]:
        """Read four consecutive f32 values (e.g. a quaternion)."""
        self._need(16); v = struct.unpack_from("<ffff", self.data, self.pos)
        self.pos += 16; return v

    def f64x3(self) -> tuple[float, float, float]:
        """Read three consecutive f64 values."""
        self._need(24); v = struct.unpack_from("<ddd", self.data, self.pos)
        self.pos += 24; return v

    # --- strings / alignment ------------------------------------------
    def strz(self) -> str:
        """Read a NUL-terminated ASCII string."""
        end = self.data.find(b'\x00', self.pos)
        if end < 0:
            s = self.data[self.pos:].decode('ascii', errors='ignore')
            self.pos = self.size
            return s
        s = self.data[self.pos:end].decode('ascii', errors='ignore')
        self.pos = end + 1
        return s

    def align4(self) -> None:
        """Advance pos to the next multiple of 4."""
        self.pos = (self.pos + 3) & ~3

    # --- explicit positioning -----------------------------------------
    def skip(self, n: int) -> None:
        """Advance pos by n bytes; raises on short reads."""
        self._need(n); self.pos += n

    def seek(self, pos: int) -> None:
        """Set pos to an absolute offset."""
        self.pos = pos

    def remaining(self) -> int:
        """Number of bytes left between pos and the end of the buffer."""
        return self.size - self.pos