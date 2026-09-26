# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

from __future__ import annotations

from .rffl import RFFL_MAGIC, RFArchive, RFEntry, parse_rffl
from .ilbm import (
    BmhdInfo, IlbmImage,
    find_iff_start, parse_ilbm_at,
    decode_ilbm_body, ilbm_to_rgba,
)
from .unpacker import extract_all, unpack_rffl_recursive
from .png_writer import save_png

__all__ = [
    "RFFL_MAGIC", "RFArchive", "RFEntry", "parse_rffl",
    "BmhdInfo", "IlbmImage", "find_iff_start", "parse_ilbm_at",
    "decode_ilbm_body", "ilbm_to_rgba",
    "extract_all", "unpack_rffl_recursive",
    "save_png",
]