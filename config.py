# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Constants, enums and lookup tables shared across the add-on.

Contains no bpy imports, so everything here is unit-testable standalone.
Enum classes inherit from str so they compare equal to the raw string
values used by bpy.props.EnumProperty.
"""

from __future__ import annotations

from enum import Enum


# --- RIF format constants ---------------------------------------------
MAX_DEPTH = 11
RIF_IDENTIFIER = b"REBCRIF1"
HUFFMAN_HEADER_SIZE = 8 + 8 + MAX_DEPTH * 4 + 256
POLY_SIZE = 36

# --- Polygon colour (uint32) bit layout --------------------------------
POLY_BITMAP_MASK = 0x00000FFF
POLY_UV_HI_MASK  = 0x0000F000
POLY_COLOR_MASK  = 0x000000FF
CLRLOOKP_MAX     = 31.0

# --- Object flags ------------------------------------------------------
OBJECT_FLAG_BASE_OBJECT   = 0x00000100
OBJECT_FLAG_MODULE_OBJECT = 0x00000200
OBJECT_FLAG_PLACED_OBJECT = 0x00000400

# --- Material defaults applied to every imported Principled BSDF -------
MAGENTA = (1.0, 0.0, 1.0, 1.0)
MAT_ROUGHNESS = 1.0
MAT_SPECULAR  = 0.0

RIF_ALIASES = {
    "Pack":            ["Medbox01", "Medbox", "MedicalBox", "MedPack", "Medkit"],
    "Pulrak":          ["Pulam", "Pulse", "PulseRifle", "PulseAmmo"],
    "Smrtammo":        ["Smrtam01"],
    "Miniammo":        ["Miniamo"],
    "Grenammo":        ["grenam01"],
    "Armour7":         ["Armour01", "acarmr"],
    "Missammo":        ["missile"],
    "Dropship":        ["dropshiplowpoly"],
    "Secdesk":         ["desk1"],
    "Heater":          ["heater1"],
    "Spaceship bulb":  ["bulb"],
    "Cylinder":        ["ncylinder"],
    "Drum":            ["ndrum", "cdrum", "bdrum"],
    "Tupbox":          ["ntupbox", "fntupbox"],
    "Cup":             ["ncup", "fncup"],
    "Monitor":         ["almonitor", "almonitor2", "almonitor3",
                        "almonitor4", "almonitor5"],
    # Flamethrower ammo canister. FLAM01 is the correct file but was
    # authored at a different scale than the level's placeholder copy;
    # with ExtRif=AUTO the strategy picks whichever has more verts, which
    # may or may not be the placeholder. Switch to "Prefer placeholder"
    # if the imported object looks wrong-scaled.
    "Flmeammo":        ["flam01"],
}


# ---------------------------------------------------------------------------
# Enums (str subclasses so they compare equal to bpy string values)
# ---------------------------------------------------------------------------

class OrphanMode(str, Enum):
    """What to do with shapes that have no matching OBJHEAD1."""
    SKIP   = "SKIP"
    ORIGIN = "ORIGIN"
    INFER  = "INFER"


class PivotMode(str, Enum):
    """How to handle object pivots on import."""
    ROTATED_ONLY = "ROTATED_ONLY"
    NONE         = "NONE"
    ALL          = "ALL"


class ExtRifStrategy(str, Enum):
    """How to choose between placeholder and external SHPEXTFL shape."""
    AUTO               = "auto"
    PREFER_EXT         = "prefer_ext"
    PREFER_PLACEHOLDER = "prefer_placeholder"


# ---------------------------------------------------------------------------
# Enum item lists consumed by bpy.props.EnumProperty
# ---------------------------------------------------------------------------

BITMAP_MODES = [("LO12", "LO12", ""), ("HI12", "HI12", "")]

UV_SCALES = [
    ("0.0078125",  "/128",  ""),
    ("0.00390625", "/256",  ""),
    ("0.015625",   "/64",   ""),
    ("1.0",        "1.0",   ""),
]

UV_DATA_TYPES = [("FLOAT", "Float", ""), ("INT16", "Int16", "")]

PIVOT_MODES = [
    (PivotMode.ROTATED_ONLY.value, "Rotated only",
     "Center only objects whose quaternion is non-identity - the pivot is moved "
     "to the geometry center. This matches the game's pivot behavior for rotating "
     "entities. Objects without rotation keep the pivot stored in the RIF file."),
    (PivotMode.NONE.value, "None",
     "Do not center anything - keep the pivot exactly as stored in the RIF file. "
     "Use this if you want to reproduce the raw coordinates."),
    (PivotMode.ALL.value, "All",
     "Center every object regardless of rotation. Useful for debugging or when "
     "the pivot in the file is clearly wrong."),
]

EXT_RIF_STRATEGIES = [
    (ExtRifStrategy.AUTO.value, "Auto", ""),
    (ExtRifStrategy.PREFER_EXT.value, "Prefer ext", ""),
    (ExtRifStrategy.PREFER_PLACEHOLDER.value, "Prefer placeholder", ""),
]

ORPHAN_MODES = [
    (OrphanMode.SKIP.value, "Skip (like the game)",
     "Shapes without OBJHEAD1 - the game does not render them "
     "(fragments / morph targets)"),
    (OrphanMode.ORIGIN.value, "Keep at (0,0,0)",
     "Keep all shapes even without position - for debugging"),
    (OrphanMode.INFER.value, "Try to infer",
     "Try to match orphan by name or index to the nearest object"),
]

COLLECTION_GROUPS = {
    "geometry":       "Geometry",
    "dummies":        "Dummies",
    "hierarchies":    "Hierarchies",
    "generators":     "Generators",
    "sounds":         "Sounds",
    "player_starts":  "PlayerStarts",
    "camera_origins": "CameraOrigins",
    "paths":          "Paths",
    "lights":         "Lights",
    "animations":     "Animations",
    # Debug aid: empty markers at pivots of unresolved SHPEXTFL refs.
    "missing_ext":    "MissingExtRif",
}

# Subcollections that are only created when the corresponding feature is
# enabled (e.g. debug-only groups). Keys match COLLECTION_GROUPS; the
# value here is the set of keys create_import_collections() skips unless
# the caller passes them in enable_optional.
OPTIONAL_COLLECTION_GROUPS = {"missing_ext"}