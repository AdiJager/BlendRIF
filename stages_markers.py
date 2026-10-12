# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Stage 2 (lights) and Stage 3 (marker empties / path curves).

Both stages take frozen dataclass configs rather than an operator
instance, so they are unit-testable without a mock operator and their
dependencies on operator state are visible in the signature.
"""

from __future__ import annotations

from dataclasses import dataclass

from .utils import log
from .empties import (
    create_lights_from_lightset, create_dummy_empties,
    create_placed_hierarchy_empties, create_avpgener_empties,
    create_sound_empties, create_avpstart_empties,
    create_camorign_empties, create_path_curves, create_waypoint_objects,
)


@dataclass(frozen=True)
class StageLightsConfig:
    """Operator-derived toggles consumed by Stage 2."""
    import_lights: bool
    scale: float


@dataclass(frozen=True)
class StageMarkersConfig:
    """Operator-derived toggles consumed by Stage 3."""
    import_dummy: bool
    import_placed_hier: bool
    import_avpgener: bool
    import_soundob2: bool
    import_avpstart: bool
    import_camorign: bool
    import_paths: bool
    import_waypoints: bool
    scale: float


def run_stage_lights(cfg: StageLightsConfig, scan, counters, base, cols):
    """Create one Blender light per STDLIGHT record."""
    if not (cfg.import_lights and scan.lightset_list):
        return
    log.info("")
    log.info("--- Stage 2: Lights ---")
    n = 0
    for ls in scan.lightset_list:
        n += create_lights_from_lightset(ls, base, cfg.scale,
                                         cols["lights"])
    counters.lights = n
    log.info(f"Created {n} light(s)")


def run_stage_markers(cfg: StageMarkersConfig, scan, counters, base, cols):
    """Create empties / curves for every enabled marker category."""
    log.info("")
    log.info("--- Stage 3: Markers ---")
    if cfg.import_dummy and scan.dummies:
        counters.dum = create_dummy_empties(
            scan.dummies, base, cfg.scale, cols["dummies"])
        log.info(f"  DUMMYOBJ: {counters.dum}")
    if cfg.import_placed_hier and scan.placed:
        counters.ph = create_placed_hierarchy_empties(
            scan.placed, base, cfg.scale, cols["hierarchies"])
        log.info(f"  PLACHIER: {counters.ph}")
    if cfg.import_avpgener and scan.avpgener_list:
        counters.gen = create_avpgener_empties(
            scan.avpgener_list, base, cfg.scale, cols["generators"])
        log.info(f"  AVPGENER: {counters.gen}")
    if cfg.import_soundob2 and scan.sound_list:
        counters.snd = create_sound_empties(
            scan.sound_list, base, cfg.scale, cols["sounds"])
        log.info(f"  SOUNDOB2: {counters.snd}")
    if cfg.import_avpstart and scan.pstart_list:
        counters.ps = create_avpstart_empties(
            scan.pstart_list, base, cfg.scale, cols["player_starts"])
        log.info(f"  AVPSTART: {counters.ps}")
    if cfg.import_camorign and scan.camorign_list:
        counters.cam = create_camorign_empties(
            scan.camorign_list, base, cfg.scale, cols["camera_origins"])
        log.info(f"  CAMORIGN: {counters.cam}")
    if cfg.import_paths and scan.path_list:
        # Patrol paths are lists of AI modules: the curve is drawn through
        # each module's OBJHEAD1 position, not through the point records.
        obj_by_index = {oh.index_num: oh for oh in scan.all_obj_headers}
        counters.path = create_path_curves(
            scan.path_list, base, cfg.scale, cols["paths"], obj_by_index)
        log.info(f"  AVPPATH2: {counters.path}")
    if cfg.import_waypoints and scan.waypoint_groups:
        counters.waypoints = create_waypoint_objects(
            scan.waypoint_groups, base, cfg.scale, cols["waypoints"])
        n_mod = sum(1 for g in scan.waypoint_groups if g.alien)
        log.info(f"  WAYPOINT: {counters.waypoints} Alien volume(s) "
                 f"in {n_mod} module(s)")