# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Canonical chunk ID strings.

Using named constants instead of raw string literals makes typos visible
in the IDE and easier to grep. Chunk.X is a plain str, so it can be used
interchangeably with string literals in comparisons.
"""

from __future__ import annotations


class Chunk:
    """RIF chunk IDs as named constants."""

    # --- shape containers ---------------------------------------------
    SHPHEAD1 = "SHPHEAD1"
    SHPRAWVT = "SHPRAWVT"
    SHPPOLYS = "SHPPOLYS"
    SHPUVCRD = "SHPUVCRD"
    SHPEXTFL = "SHPEXTFL"

    # --- bitmaps / textures -------------------------------------------
    BMPLSTST = "BMPLSTST"
    BMPNAMES = "BMPNAMES"
    MATCHIMG = "MATCHIMG"
    CLRLOOKP = "CLRLOOKP"

    # --- object placement ---------------------------------------------
    OBJHEAD1 = "OBJHEAD1"
    RIFFNAME = "RIFFNAME"

    # --- markers ------------------------------------------------------
    DUMOBJDT = "DUMOBJDT"
    DUMOBJTX = "DUMOBJTX"
    PLACHIDT = "PLACHIDT"
    PLHISEQU = "PLHISEQU"
    SPECLOBJ = "SPECLOBJ"
    AVPGENER = "AVPGENER"
    SOUNDOB2 = "SOUNDOB2"
    AVPSTART = "AVPSTART"
    CAMORIGN = "CAMORIGN"
    AVPPATH2 = "AVPPATH2"

    # --- lights / animation -------------------------------------------
    LIGHTSET  = "LIGHTSET"
    STDLIGHT  = "STDLIGHT"

    # --- character hierarchy / animation (avp_huds/hnpc*.rif) ---------
    # Character RIFs store a skeletal hierarchy as OBJCHIER containers
    # (recursive) with OBJHIERD leaves (parent_idx + name). OBHIERNM at
    # the root holds the human-readable skeleton name. NOTE: OBHIERNM
    # is 8 chars, no "J" after OB.
    OBJCHIER  = "OBJCHIER"
    OBJHIERD  = "OBJHIERD"
    OBHIERNM  = "OBHIERNM"

    # Compact animation format: one chunk holds ALL sequences + frames
    # for a single body-part object. See animobs.cpp.
    OBANALLS  = "OBANALLS"

    # Extended per-sequence animation format. Same data as OBANALLS but
    # split into one OBANSEQC per sequence, each with its own header
    # and per-frame chunks. Not parsed by the importer (OBANALLS is
    # enough); listed here so hex-dump diagnostics do not flag them as
    # unknown.
    OBANSEQS  = "OBANSEQS"
    OBANSEQC  = "OBANSEQC"
    OBASEQHD  = "OBASEQHD"
    OBASEQFR  = "OBASEQFR"
    OBASEQTM  = "OBASEQTM"
    OBASEQSP  = "OBASEQSP"
    OBASEQFL  = "OBASEQFL"

    # --- level animation (avp_rifs/*.rif) -----------------------------
    # Door / rotator / elevator system. Completely separate from
    # character animation; no source code available. The chunk ID is
    # OBJTRAK2 (no "C"). Payload layout is parsed in
    # parsers/level_track.py; see scan.py _scan_tracks for the
    # collection step.
    OBJTRAK2  = "OBJTRAK2"
    VIOBJECT  = "VIOBJECT"
    VOBJPROP  = "VOBJPROP"
    MODULEDT  = "MODULEDT"
    ADJMDLEP  = "ADJMDLEP"
    VMDARRAY  = "VMDARRAY"


# Byte-stream magics
RIF_MAGIC  = b"REBCRIF1"
INFF_MAGIC = b"REBINFF2"