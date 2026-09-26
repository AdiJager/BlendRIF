# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""PNG writer that uses only Blender's image API.

The AvP RIF Importer stays self-contained: no PIL, no numpy, no
external tools. Images are created in bpy.data, filled via
foreach_set() for speed, saved, and removed in a finally block.

Pixel order note: Blender's Image.pixels is bottom-up internally,
but new images written with foreach_set() and saved as PNG keep the
order they were given (top-down, same as ILBM). If a future test
shows vertically flipped output, reverse the rows before foreach_set.
"""

from __future__ import annotations

import os

import bpy

from ..utils import log


def save_png(path: str, rgba_bytes: bytes, width: int, height: int) -> bool:
    """Save RGBA bytes as a PNG via bpy.data.images. True on success."""
    if width <= 0 or height <= 0:
        log.warning(f"PNG save skipped: invalid size {width}x{height}")
        return False
    expected = width * height * 4
    if len(rgba_bytes) != expected:
        log.warning(f"PNG save skipped: expected {expected} bytes, "
                    f"got {len(rgba_bytes)}")
        return False

    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    img = None
    try:
        img = bpy.data.images.new("_tmp_ffl", width=width, height=height,
                                  alpha=True)
        # Convert 0..255 -> 0.0..1.0 in one list comprehension; Blender
        # copies it verbatim into the image buffer.
        pixels = [b / 255.0 for b in rgba_bytes]
        img.pixels.foreach_set(pixels)
        img.filepath_raw = path
        img.file_format = 'PNG'
        img.save()
        return True
    except Exception as e:
        log.warning(f"PNG save failed for {path}: {e}")
        return False
    finally:
        if img is not None:
            try:
                bpy.data.images.remove(img)
            except Exception:
                pass