# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Small helpers shared across modules: logging, axis conversion, sanitising.

`log` is a module-level Logger that the operator configures once per
import via configure_logging(). configure_logging touches only our own
logger, never the root logger, because Blender and other add-ons share
it in the same session.
"""

from __future__ import annotations

import logging
import sys


log = logging.getLogger("avp_rif")


def configure_logging(level: int = logging.INFO) -> None:
    """Attach a stdout handler (once) and set the log level."""
    if not log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(handler)
        # Do not propagate to root - avoids double-printing under Blender.
        log.propagate = False
    log.setLevel(level)


def apply_axis(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Convert an AvP position (Y-up) to Blender (Z-up) preserving handedness."""
    # Negating Y (not Z) keeps the model from being mirrored.
    return (x, z, -y)


def world_pos(loc, scale: float) -> tuple[float, float, float]:
    """Convert an AvP position to Blender world coordinates and scale it."""
    x, y, z = apply_axis(*loc)
    return (x * scale, y * scale, z * scale)


def sanitize(s: str, max_len: int = 40) -> str:
    """Strip non-alphanumeric characters and truncate to max_len."""
    if not s:
        return ""
    return ''.join(c for c in s if c.isalnum() or c in '_-')[:max_len]


def _safe_name(base: str, prefix: str, name: str, idx: int) -> str:
    """Compose a `<base>_<prefix>_<sanitised name or idx>` object name."""
    clean = sanitize(name) if name else ""
    if clean:
        return f"{base}_{prefix}_{clean}"
    return f"{base}_{prefix}_{idx:03d}"