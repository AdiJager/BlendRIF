# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Pure bytes->dataclass parsers.

Nothing here imports bpy. Each parser takes a bytes payload (the inside
of a chunk) and returns a dataclass, or None on malformed input. The one
exception is parse_bitmap_list, which always returns a dict (possibly
empty) so callers can safely call .update() on the result.

char_anim is deliberately NOT re-exported here: it is a large, deeply
nested tree-walker (OBJCHIER + OBANALLS) that callers import directly
via `from .parsers.char_anim import ...`, which keeps this module's
namespace small.
"""

from .shapes import (
    ShpHead, ObjHead, ShpExtFl,
    parse_shphead1, parse_objhead1, parse_shpextfl,
)
from .bitmaps import (
    BitmapEntry, ImageDescriptor, MatchImgRule, MatchImg, ClrLookp,
    parse_bitmap_list, parse_image_descriptor, parse_matchimg, parse_clrlookp,
)
from .lights import StdLight, parse_stdlight
from .level_track import TrackSection, LevelTrack, parse_objtrak2
from .markers import (
    DumObj, PlachId, AvpGener, SoundOb2, AvpStart, CamOrign,
    PathPoint, AvpPath2,
    parse_dumobjdt, parse_dumobjtx, parse_plachidt,
    parse_avpgener, parse_soundob2, parse_avpstart,
    parse_camorign, parse_avppath2,
)

__all__ = [
    # shapes
    "ShpHead", "ObjHead", "ShpExtFl",
    "parse_shphead1", "parse_objhead1", "parse_shpextfl",
    # bitmaps
    "BitmapEntry", "ImageDescriptor", "MatchImgRule", "MatchImg", "ClrLookp",
    "parse_bitmap_list", "parse_image_descriptor", "parse_matchimg",
    "parse_clrlookp",
    # lights
    "StdLight", "parse_stdlight",
    # level tracks
    "TrackSection", "LevelTrack", "parse_objtrak2",
    # markers
    "DumObj", "PlachId", "AvpGener", "SoundOb2", "AvpStart", "CamOrign",
    "PathPoint", "AvpPath2",
    "parse_dumobjdt", "parse_dumobjtx", "parse_plachidt",
    "parse_avpgener", "parse_soundob2", "parse_avpstart",
    "parse_camorign", "parse_avppath2",
]