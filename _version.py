# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Runtime version string used by log output and diagnostics.

The installed version is the `version` field of blender_manifest.toml;
this string exists so the import log and diagnostics can report it
without reading the manifest at runtime. Update both together when the
version changes.
"""

from __future__ import annotations

# PEP 396 name. Also the value reported in the import log.
__version__ = "1.3.2"
# Alias consumed by operator.py for log output.
__version_str__ = __version__
