# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Stage 0: parse a decoded RIF stream into a ScanResult.

Pure parsing + logging, no bpy, so it can be unit-tested outside
Blender. RifScanner collects every structure the later import stages
need in one pass over the chunk stream.

Level name is resolved by _find_level_name, which walks the chunk tree
but skips SHPEXTFL subtrees entirely. RIFFNAME appears in two places
with different meanings - at/near the root it is the level name,
inside SHPEXTFL it is the filename of an external shape RIF. A naive
DFS returns whichever comes first, which produces the wrong level
name for files whose first container is a SHAPES blob full of SHPEXTFL
refs. Files with no resolvable level RIFFNAME fall back to the caller-
supplied basename.

id_to_objs is a MULTI-map (shape_id -> list[ObjHead]). A level that
reuses one shape across N RBOBJECTS (e.g. corridor lamps, wall
lights) produces one Blender object per placement entry, each at its
own transform; the previous one-to-one map collapsed duplicates and
imported the shape only once.

_scan_char_hierarchy walks the recursive OBJCHIER tree inside
REBINFF2 and collects one CharBone per OBJHIERD leaf, each with its
own ObjAllSequences. Character RIFs (avp_huds/hnpc*.rif) are the only
ones with this structure; level RIFs return early. find_all_chunks is
not used here - it both drops real OBJHIERD chunks and picks up false
OBJCHIER matches from OBANALLS payloads (each frame is 36 B, so byte
patterns collide).

Level track animations (OBJTRAK2) are collected into objtrak_list;
the parser lives in parsers/level_track.py and the baker in
level_baker.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .chunks import (
    parse_chunks, find_all_chunks, walk_chunks,
    collect_rebshape, collect_rbobject,
)
from .chunk_ids import Chunk
from .utils import log
from .materials import build_matchimg_index
from .parsers.bitmaps import parse_bitmap_list, parse_matchimg, parse_clrlookp
from .parsers.shapes import parse_shphead1, parse_objhead1
from .parsers.markers import parse_plachidt
from .parsers.char_anim import (
    parse_objchier_tree, CharBone, ObjAllSequences,
)


def _find_level_name(decoded: bytes, resync_max: int) -> str | None:
    """Return the level's own RIFFNAME, ignoring SHPEXTFL refs, or None."""
    # RIFFNAME appears twice with different meanings: at/near the root
    # it is the level name, inside SHPEXTFL it is the filename of an
    # external shape RIF. A naive DFS surfaces whichever comes first,
    # which is wrong for files whose first top-level chunk is a
    # container full of SHPEXTFL refs (hnpcmarine.RIF -> "missile").
    # Walk the tree but skip SHPEXTFL subtrees entirely; return the
    # first RIFFNAME found anywhere else.
    skip = {Chunk.SHPEXTFL}

    def _walk(data: bytes, depth: int) -> str | None:
        if depth > 6:
            return None
        chunks = parse_chunks(data, quiet=True, resync_max=resync_max)
        if chunks is None:
            return None
        # Prefer RIFFNAME at this level before descending.
        for cid, cdata in chunks:
            if cid == Chunk.RIFFNAME:
                name = cdata.split(b'\x00')[0].decode(
                    'ascii', errors='replace')
                if name:
                    return name
        # Then descend, skipping SHPEXTFL subtrees.
        for cid, cdata in chunks:
            if cid in skip:
                continue
            found = _walk(cdata, depth + 1)
            if found:
                return found
        return None

    return _walk(decoded, 0)


@dataclass
class ScanResult:
    """Everything the importer reads from a decoded RIF before bpy is touched."""
    level_name: str = "Unknown"
    bmp_names: dict = field(default_factory=dict)
    matchimg_index: dict = field(default_factory=dict)
    clrlookp_table: list | None = None
    shapes: list = field(default_factory=list)          # list[ShapeGroup]
    shape_headers: list = field(default_factory=list)   # list[ShpHead|None]
    objects: list = field(default_factory=list)         # list[ObjectGroup]
    # Multi-map, one entry per unique shape_id, each holding every
    # ObjHead that references it. All placements are preserved.
    id_to_objs: dict = field(default_factory=dict)      # int -> list[ObjHead]
    obj_by_tag: dict = field(default_factory=dict)      # str -> ObjHead
    all_obj_headers: list = field(default_factory=list) # list[ObjHead]
    dummies: list = field(default_factory=list)
    placed: list = field(default_factory=list)
    placed_positions: dict = field(default_factory=dict)
    n_plach_hit: int = 0
    avpgener_list: list = field(default_factory=list)
    sound_list: list = field(default_factory=list)
    pstart_list: list = field(default_factory=list)
    camorign_list: list = field(default_factory=list)
    path_list: list = field(default_factory=list)
    lightset_list: list = field(default_factory=list)
    # Level track system (doors / lifts / rotating fans / platforms).
    # Raw payloads as returned by find_all_chunks; parsing lives in
    # parsers/level_track.py (chunk id is OBJTRAK2, no "C").
    objtrak_list: list = field(default_factory=list)
    # Character skeleton + animation. char_bones is a flat list in DFS
    # pre-order (parent before child); each bone carries parent_name
    # and its own ObjAllSequences. char_bones_by_name is a lowercased
    # lookup used by Stage 1c to parent meshes. char_anims is a flat
    # list of every ObjAllSequences seen (one per animated bone), used
    # by Stage 4b for NLA baking.
    char_root_name: str = ""
    char_bones: list = field(default_factory=list)         # list[CharBone]
    char_anims: list = field(default_factory=list)         # list[ObjAllSequences]
    char_bones_by_name: dict = field(default_factory=dict) # str -> CharBone


class RifScanner:
    """Walk a decoded RIF buffer and collect every structure the importer needs."""

    def __init__(self, *, diagnostics_mode: bool = False,
                 apply_matchimg: bool = True,
                 use_clrlookp: bool = True,
                 import_materials: bool = True,
                 fallback_level_name: str | None = None):
        self.diagnostics_mode = diagnostics_mode
        self.apply_matchimg = apply_matchimg
        self.use_clrlookp = use_clrlookp
        self.import_materials = import_materials
        # Used only when the file has no resolvable level RIFFNAME at
        # all (some shape RIFs and hud RIFs omit it). Callers pass the
        # file's basename so the log / level_hint stay meaningful.
        self.fallback_level_name = fallback_level_name
        # Diagnostics: disable resync so unexpected separators surface.
        self._resync_max = 0 if diagnostics_mode else 64

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def scan(self, decoded: bytes) -> ScanResult:
        """Run every per-section scanner in order and return the ScanResult."""
        scan = ScanResult()
        rm = self._resync_max
        self._scan_header(decoded, scan, rm)
        self._scan_shapes(decoded, scan, rm)
        self._scan_markers(decoded, scan, rm)
        self._scan_specials(decoded, scan, rm)
        self._scan_tracks(decoded, scan, rm)
        self._scan_char_hierarchy(decoded, scan, rm)
        self._log_scan_summary(scan)
        return scan

    # ------------------------------------------------------------------
    # Per-section scanners
    # ------------------------------------------------------------------

    def _scan_header(self, decoded, scan, resync_max):
        """Read RIFFNAME, BMPNAMES, MATCHIMG and CLRLOOKP."""
        level = _find_level_name(decoded, resync_max)
        if level is not None:
            scan.level_name = level
            log.info(f"Level: {level}")
        elif self.fallback_level_name:
            scan.level_name = self.fallback_level_name
            log.info(f"Level: {scan.level_name} "
                     f"(fallback - no level RIFFNAME in file)")
        else:
            log.info(f"Level: {scan.level_name} "
                     f"(no level RIFFNAME; keeping default)")

        all_bmp = find_all_chunks(decoded, Chunk.BMPNAMES, max_depth=8,
                                  resync_max=resync_max)
        for bd in all_bmp:
            scan.bmp_names.update(parse_bitmap_list(bd))
        log.info(f"BMPNAMES: {len(scan.bmp_names)} bitmap(s)")

        if self.apply_matchimg and self.import_materials:
            rules = []
            for mi in find_all_chunks(decoded, Chunk.MATCHIMG, max_depth=8,
                                      resync_max=resync_max):
                p = parse_matchimg(mi)
                if p:
                    rules.extend(p.rules)
            scan.matchimg_index = build_matchimg_index(rules)
            log.info(f"MATCHIMG: {len(rules)} rule(s)")

        if self.use_clrlookp and self.import_materials:
            for cl in find_all_chunks(decoded, Chunk.CLRLOOKP, max_depth=8,
                                      resync_max=resync_max):
                p = parse_clrlookp(cl)
                if p and p.table:
                    scan.clrlookp_table = p.table
                    log.info(f"CLRLOOKP: table of {len(p.table)} colors")
                    break

    def _scan_shapes(self, decoded, scan, resync_max):
        """Read SHAPES and RBOBJECTS; build the id/tag lookup tables."""
        # Every ObjHead that references a shape_id is appended to
        # id_to_objs[shape_id] - never collapsed. obj_by_tag stays
        # one-to-one; tags are unique in practice (each level shows
        # by_tag == total object count), and the tag fallback is only
        # used for orphan-shape inference.
        scan.shapes = collect_rebshape(decoded, resync_max=resync_max)
        scan.objects = collect_rbobject(decoded, resync_max=resync_max)
        log.info(f"SHAPES: {len(scan.shapes)}, RBOBJECTS: {len(scan.objects)}")

        scan.shape_headers = [
            parse_shphead1(g.head) if g.head else None
            for g in scan.shapes
        ]

        for og in scan.objects:
            if og.head is None:
                continue
            oh = parse_objhead1(og.head)
            if oh is None:
                continue
            scan.all_obj_headers.append(oh)
            if oh.shape_id >= 0:
                scan.id_to_objs.setdefault(oh.shape_id, []).append(oh)
            if oh.tag:
                scan.obj_by_tag.setdefault(oh.tag.lower(), oh)

    def _scan_markers(self, decoded, scan, resync_max):
        """Read DUMMYOBJ / PLACHIER groups and PLACHIDT position records."""
        scan.dummies = walk_chunks(decoded,
                                   lambda ids: Chunk.DUMOBJDT in ids,
                                   resync_max=resync_max)
        scan.placed = walk_chunks(decoded,
                                  lambda ids: Chunk.PLACHIDT in ids,
                                  resync_max=resync_max)

        for p in scan.placed:
            dt = p.get(Chunk.PLACHIDT, [])
            if not dt:
                continue
            pi = parse_plachidt(dt[0])
            if not pi:
                continue
            rec = {"location": pi.location, "orientation": pi.orientation,
                   "name": pi.name, "id": pi.id,
                   "hierarchy_index": pi.hierarchy_index}
            if pi.name:
                scan.placed_positions[("tag", pi.name.lower())] = rec
            scan.placed_positions[("id", pi.id[0])] = rec
            scan.n_plach_hit += 1
        log.info(f"DUMMYOBJ: {len(scan.dummies)}, PLACHIER: {len(scan.placed)}")
        log.info(f"PLACHIDT: {scan.n_plach_hit} record(s)")

    def _scan_specials(self, decoded, scan, resync_max):
        """Collect AVPGENER / SOUNDOB2 / AVPSTART / CAMORIGN / AVPPATH2."""
        for so in find_all_chunks(decoded, Chunk.SPECLOBJ, max_depth=8,
                                  resync_max=resync_max):
            sub = parse_chunks(so, quiet=True)
            if sub is None:
                continue
            for cid, cdata in sub:
                if cid == Chunk.AVPGENER:
                    scan.avpgener_list.append(cdata)
                elif cid == Chunk.SOUNDOB2:
                    scan.sound_list.append(cdata)
                elif cid == Chunk.AVPSTART:
                    scan.pstart_list.append(cdata)
                elif cid == Chunk.CAMORIGN:
                    scan.camorign_list.append(cdata)
                elif cid == Chunk.AVPPATH2:
                    scan.path_list.append(cdata)

        log.info(f"AVPGENER: {len(scan.avpgener_list)}, "
                 f"SOUNDOB2: {len(scan.sound_list)}")
        log.info(f"AVPSTART: {len(scan.pstart_list)}, "
                 f"CAMORIGN: {len(scan.camorign_list)}, "
                 f"AVPPATH2: {len(scan.path_list)}")

    def _scan_tracks(self, decoded, scan, resync_max):
        """Collect LIGHTSET and OBJTRAK2 chunk payloads."""
        # OBJTRAK2 is the level-track system (doors, rotators, lifts,
        # moving platforms), completely separate from character
        # animation. The payload is parsed later in
        # parsers/level_track.py.
        scan.lightset_list = find_all_chunks(decoded, Chunk.LIGHTSET,
                                             max_depth=8,
                                             resync_max=resync_max)
        log.info(f"LIGHTSET: {len(scan.lightset_list)}")
        scan.objtrak_list = find_all_chunks(decoded, Chunk.OBJTRAK2,
                                            max_depth=8,
                                            resync_max=resync_max)
        log.info(f"OBJTRAK2: {len(scan.objtrak_list)}")

    def _scan_char_hierarchy(self, decoded, scan, resync_max):
        """Walk the OBJCHIER tree; collect bones, anims and root name."""
        # The whole skeleton lives inside the REBINFF2 wrapper, so
        # descend one level and hand the payload to the recursive
        # walker. Wrapper OBJCHIER nodes without their own OBJHIERD are
        # transparent - the walker handles that internally. Returns
        # silently on level RIFs, which have no OBJCHIER at all.
        top = parse_chunks(decoded, quiet=True, resync_max=resync_max)
        if top is None:
            return
        tree_payload = None
        for cid, cdata in top:
            if cid in ("REBINFF2", "REBCRIF1"):
                tree_payload = cdata
                break
        if tree_payload is None:
            tree_payload = decoded

        bones, anims = parse_objchier_tree(tree_payload)
        if not bones:
            return

        scan.char_bones = bones
        scan.char_anims = anims
        scan.char_bones_by_name = {b.name.lower(): b for b in bones}

        name_payloads = find_all_chunks(decoded, Chunk.OBHIERNM,
                                        max_depth=12, resync_max=resync_max)
        if name_payloads:
            scan.char_root_name = name_payloads[0].split(b'\x00')[0].decode(
                'ascii', errors='replace')

        log.info(f"CHAR: bones={len(bones)}, anims={len(anims)}, "
                 f"root={scan.char_root_name!r}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _log_scan_summary(self, scan):
        """Emit a short human-readable summary of what was collected."""
        log.info("")
        log.info("--- Scan summary ---")
        log.info(f"  Level:     {scan.level_name}")
        log.info(f"  Shapes:    {len(scan.shapes)}")
        n_unique_ids = len(scan.id_to_objs)
        log.info(f"  Objects:   {len(scan.objects)}  "
                 f"(unique_shape_ids={n_unique_ids}, by_tag={len(scan.obj_by_tag)})")
        log.info(f"  Dummies:   {len(scan.dummies)}")
        log.info(f"  Placed:    {len(scan.placed)}  "
                 f"(records={scan.n_plach_hit})")
        log.info(f"  Bitmaps:   {len(scan.bmp_names)}")
        if scan.objtrak_list:
            log.info(f"  Tracks:    {len(scan.objtrak_list)} OBJTRAK2")
        if scan.char_bones:
            log.info(f"  Char:      bones={len(scan.char_bones)}  "
                     f"anim_sets={len(scan.char_anims)}  "
                     f"root={scan.char_root_name!r}")
        log.info("")