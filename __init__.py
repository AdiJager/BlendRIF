# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Blender add-on entry point.

An Extensions install (Blender 4.2+) takes everything from
blender_manifest.toml, which sits next to this file, so there is no
bl_info dictionary here: the manifest is the single source of metadata
(see the manual, "Converting a Legacy Add-on into an Extension").

All imports inside the package are relative, so the module works both as
`avp_rif_importer` (legacy install) and as
`bl_ext.<repository>.avp_rif_importer` (extensions install) without
referring to either name.
"""

import bpy

from . import operator as _operator

classes = _operator.classes


def register():
    """Register operator classes and the File > Import menu entry."""
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(_operator.menu_func_import)


def unregister():
    """Undo everything register() set up."""
    bpy.types.TOPBAR_MT_file_import.remove(_operator.menu_func_import)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
