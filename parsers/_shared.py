# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Helpers shared by more than one parser."""

from __future__ import annotations


def align4(offset: int) -> int:
    """Round offset up to the next multiple of 4."""
    return (offset + 3) & ~3


def read_cstr(data: bytes, offset: int) -> tuple[str, int]:
    """Read a NUL-terminated ASCII string; returns (string, offset_after_nul)."""
    end = data.find(b'\x00', offset)
    if end < 0:
        return data[offset:].decode('ascii', errors='ignore'), len(data)
    return data[offset:end].decode('ascii', errors='ignore'), end + 1