# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Final summary log + Blender report() calls for the import.

Reads counters from ImportStats / ImportCounters and warning state from
ImportContext, formats the multi-line SUMMARY block, and forwards up to
5 warnings to Blender's report system. No side effects beyond logging
and op.report().
"""

from __future__ import annotations

import math

from .config import MAT_ROUGHNESS, MAT_SPECULAR
from .utils import log


def print_summary(op, scan, state, counters, ctx):
    """Log the final multi-line summary and report warnings / info."""
    stats = state["stats"]
    ext_stats = state["ext_stats"]
    timings = state["timings"]
    smooth_deg = math.degrees(op.auto_smooth_angle)

    n_placements = len(scan.all_obj_headers)

    log.info("")
    log.info("=" * 70)
    log.info("SUMMARY:")
    log.info(f"  Collection:           {state['cols']['__main__'].name}")
    log.info(f"  Preset:               {op.preset}")
    log.info(f"  Shapes in RIF:        {len(scan.shapes)}")
    log.info(f"  Placements in RIF:    {n_placements}")
    log.info(f"  Objects created:      {stats.ok}")
    log.info(f"    from placements:    {stats.placements_ok}")
    if stats.orphan_ok:
        log.info(f"    from orphans:       {stats.orphan_ok}")
    log.info(f"  Skipped (no shape):   {stats.skipped_no_shape}")
    log.info(f"  Skipped (no geometry): {stats.skipped_nogeom}")
    log.info(f"  Orphan shapes:        {stats.orphan_skipped}  "
             f"[mode: {op.orphan_mode}]")

    total_ext = ext_stats['with_extfl']
    n_ok = ext_stats['resolved']
    n_pref = ctx.placeholder_preferred_count
    n_miss = ctx.placeholder_fallback_count + ctx.empty_missing_count
    breakdown = f"OK: {n_ok}"
    if n_pref:
        breakdown += f", placeholder-preferred: {n_pref}"
    if n_miss:
        breakdown += f", unresolved: {n_miss}"
    log.info(f"  SHPEXTFL:             {total_ext} ({breakdown})")

    if op.mark_missing_ext:
        log.info(f"  Missing SHPEXTFL marks: {ctx.missing_ext_count}")
    log.info(f"  PLACHIDT:             {scan.n_plach_hit}")
    log.info(f"  Import Materials:     "
             f"{'ON' if op.import_materials else 'OFF'}")
    log.info(f"  Backface Culling:     "
             f"{'ON' if op.cull_backfaces else 'OFF'}")
    log.info(f"  Materials:            roughness={MAT_ROUGHNESS}, "
             f"specular={MAT_SPECULAR}")
    log.info(f"  Auto Smooth:          {'ON' if op.auto_smooth else 'OFF'}"
             + (f" ({counters.smooth} meshes, {smooth_deg:.1f} deg)"
                if op.auto_smooth else ""))
    log.info(f"  Lights:               {counters.lights}")
    log.info(f"  Markers:              dum={counters.dum}, ph={counters.ph}, "
             f"gen={counters.gen}, snd={counters.snd}, "
             f"ps={counters.ps}, cam={counters.cam}, "
             f"path={counters.path}")
    log.info(f"  Animations (level):   {counters.anims}")
    if counters.hier_bones:
        log.info(f"  Char hierarchy:       {counters.hier_parented}/"
                 f"{counters.hier_bones} bones parented")
    if counters.char_anim_strips:
        log.info(f"  Char animations:      {counters.char_anim_bones} "
                 f"bone(s), {counters.char_anim_strips} NLA strip(s)")

    if timings:
        log.info("")
        log.info("  Timings:")
        for label, dt in timings.items():
            log.info(f"    {label:<18} {dt:6.2f}s")
        total = sum(timings.values())
        log.info(f"    {'total':<18} {total:6.2f}s")

    log.info("")
    log.info(f"  Warnings:             {len(ctx.warnings)}")
    for w in ctx.warnings:
        log.warning(f"    [WARN] {w}")
    log.info("=" * 70)

    for w in ctx.warnings[:5]:
        op.report({'WARNING'}, w)
    if len(ctx.warnings) > 5:
        op.report({'WARNING'},
                  f"... and {len(ctx.warnings) - 5} more warnings")

    op.report({'INFO'},
              f"Objects: {stats.ok}, "
              f"Skipped: no_shape={stats.skipped_no_shape}, "
              f"nogeom={stats.skipped_nogeom}, "
              f"orphans={stats.orphan_skipped}")