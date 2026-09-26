"""Import presets and their update callback.

PRESET_ITEMS is the EnumProperty item list; apply_preset is the update
callback that rewrites every other operator property per preset.

Caveat: Blender does NOT fire an update callback on class construction,
so the operator's own `default=` values must be correct on their own.
apply_preset only fires when the user actually changes the dropdown.
"""

from __future__ import annotations

import math


PRESET_ITEMS = [
    ("DEFAULT", "Default",
     "Balanced defaults: everything imported, Auto Smooth on, orphans skipped"),
    ("FAST", "Fast (geometry only)",
     "Import only geometry - skip materials, markers, lights, animations "
     "and Auto Smooth"),
    ("DEBUG", "Debug",
     "Raw import: no auto smooth, orphans kept at origin, no pivot fix, "
     "no MATCHIMG/CLRLOOKP, missing SHPEXTFL marked with empties"),
]


def apply_preset(self, context):
    """Update callback: rewrite all other operator properties per the preset."""
    p = self.preset
    if p == "DEFAULT":
        self.auto_smooth = True
        self.animate_objects = True
        self.animate_characters = True
        self.char_anim_limit = 0
        self.import_dummy = True
        self.import_placed_hier = True
        self.import_avpgener = True
        self.import_soundob2 = True
        self.import_avpstart = True
        self.import_camorign = True
        self.import_paths = True
        self.import_lights = True
        self.import_materials = True
        self.apply_matchimg = True
        self.use_clrlookp = True
        self.cull_backfaces = True
        self.diagnostics_mode = False
        self.mark_missing_ext = False
        self.orphan_mode = "SKIP"
        self.pivot_mode = "ROTATED_ONLY"
        self.ext_rif_strategy = "auto"
    elif p == "FAST":
        self.auto_smooth = False
        self.animate_objects = False
        self.animate_characters = False
        self.char_anim_limit = 0
        self.import_dummy = False
        self.import_placed_hier = False
        self.import_avpgener = False
        self.import_soundob2 = False
        self.import_avpstart = False
        self.import_camorign = False
        self.import_paths = False
        self.import_lights = False
        self.import_materials = False
        self.apply_matchimg = False
        self.use_clrlookp = False
        self.cull_backfaces = True    # irrelevant when materials off
        self.diagnostics_mode = False
        self.mark_missing_ext = False
        self.orphan_mode = "SKIP"
        self.pivot_mode = "ROTATED_ONLY"
        self.ext_rif_strategy = "auto"
    elif p == "DEBUG":
        self.auto_smooth = False
        self.animate_objects = False
        self.animate_characters = True
        self.char_anim_limit = 0
        self.import_dummy = True
        self.import_placed_hier = True
        self.import_avpgener = True
        self.import_soundob2 = True
        self.import_avpstart = True
        self.import_camorign = True
        self.import_paths = True
        self.import_lights = True
        self.import_materials = True
        self.apply_matchimg = False
        self.use_clrlookp = False
        self.cull_backfaces = False
        self.diagnostics_mode = False
        self.mark_missing_ext = True
        self.orphan_mode = "ORIGIN"
        self.pivot_mode = "NONE"
        self.ext_rif_strategy = "auto"