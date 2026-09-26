# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Stage 4 (OBJTRAK2 level tracks) and Stage 4b (character NLA bake).

OBJTRAK2 is the level-track system used for doors, lifts, rotating
fans and moving platforms. Payload layout confirmed from track.c in
the developer kit and from Derelict.RIF hex dumps; see
parsers/level_track.py for the structure and level_baker.py for the
baking math.

Stage 4b drives char_baker.bake_character_nla, which reads OBANALLS
sequences off character bones and installs one NLA track per
(bone, sequence) pair.

Both stages take frozen dataclass configs so the operator type does
not leak into the animation layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from .char_baker import bake_character_nla
from .level_baker import bake_level_tracks
from .utils import log


@dataclass(frozen=True)
class StageLevelAnimConfig:
    """Operator-derived toggles consumed by Stage 4."""
    animate_objects: bool
    scale: float
    animation_fps: int


@dataclass(frozen=True)
class StageCharAnimConfig:
    """Operator-derived toggles consumed by Stage 4b."""
    animate_characters: bool
    scale: float
    animation_fps: int
    char_anim_limit: int


def run_stage_level_animations(cfg: StageLevelAnimConfig, scan, counters,
                               base, cols):
    """Bake OBJTRAK2 level tracks as NLA strips on dedicated empties."""
    if not (cfg.animate_objects and scan.objtrak_list):
        return
    log.info("")
    log.info(f"--- Stage 4: Animations (OBJTRAK2, "
             f"{len(scan.objtrak_list)} track(s)) ---")
    n_tracks, n_strips, max_frame = bake_level_tracks(
        scan, base, cols, cfg.scale,
        fps=cfg.animation_fps,
        section_seconds=1.0,
    )
    counters.anims = n_tracks
    if n_tracks:
        log.info(f"  Baked {n_tracks} level track(s), "
                 f"frame range 1..{max_frame}")
    else:
        log.info("  No level tracks baked")


def run_stage_char_animations(cfg: StageCharAnimConfig, scan, counters, cols):
    """Bake OBANALLS sequences as NLA tracks per bone."""
    if not (cfg.animate_characters and scan.char_anims):
        return
    log.info("")
    log.info(f"--- Stage 4b: Character Animations "
             f"({len(scan.char_anims)} bone anim set(s)) ---")
    limit = cfg.char_anim_limit
    if limit > 0:
        log.info(f"  Sequence limit per bone: {limit}")
    else:
        log.info("  Sequence limit per bone: all")
    n_bones, n_strips = bake_character_nla(
        scan, cols, cfg.scale, fps=cfg.animation_fps,
        limit_sequences=limit)
    counters.char_anim_bones = n_bones
    counters.char_anim_strips = n_strips