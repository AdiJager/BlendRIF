# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

bl_info = {
    "name": "Aliens vs Predator RIF Importer",
    "author": "AdiJager",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "File > Import > Aliens vs Predator RIF (.rif)",
    "description": "Import Aliens vs Predator (1999) RIF assets: "
                   "levels, models, textures, lights, markers and "
                   "character skeletons",
    "category": "Import-Export",
}

# Blender add-on entry point. bl_info must contain only literals -
# Blender parses it with ast.literal_eval *before* importing this
# module. Keep bl_info["version"], _version.py and
# blender_manifest.toml in sync manually.
#
# Captured at import time: under Blender 4.2+ extensions the loader
# does not expose bl_info inside register() / unregister(), so the
# self-check reads _BL_INFO_VERSION instead. Legacy installs still
# use bl_info for metadata, and the value here is identical.
_BL_INFO_VERSION = tuple(bl_info["version"])

import bpy

from . import operator as _operator

classes = _operator.classes


def _check_version_consistency():
    """Warn when bl_info["version"] and _version.py diverge."""
    try:
        from ._version import __version__ as _vt
    except ImportError as e:
        import warnings
        warnings.warn(
            f"avp_rif_importer: could not read _version.py ({e}); "
            f"version self-check disabled.",
            RuntimeWarning,
        )
        return
    _vt_tuple = tuple(int(p) for p in _vt.split(".") if p.isdigit())
    if _BL_INFO_VERSION != _vt_tuple:
        import warnings
        warnings.warn(
            f"avp_rif_importer: bl_info['version']="
            f"{_BL_INFO_VERSION} does not match "
            f"_version.py {_vt!r}. Update both to keep the "
            f"add-on metadata consistent.",
            RuntimeWarning,
        )


def register():
    """Register operator classes and the File > Import menu entry."""
    _check_version_consistency()
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