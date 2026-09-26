# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Runtime version string used by log output and diagnostics.

Must stay in sync with bl_info["version"] in __init__.py and the
version field in blender_manifest.toml. The add-on's self-check warns
at import time if the values diverge; this file exists only because
Blender parses __init__.py's bl_info as an AST literal before
importing the module, so bpy.props / expressions cannot live there.
"""

from __future__ import annotations

# PEP 396 name, read by __init__.py's self-check.
__version__ = "1.0.0"
# Alias consumed by operator.py for log output.
__version_str__ = __version__