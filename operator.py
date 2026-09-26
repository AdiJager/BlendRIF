# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Blender operator: thin orchestrator over the import pipeline.

The operator itself only declares Blender properties (they MUST live
inline - Blender does not materialise bpy.props.* declared outside
the class body) and drives the stages. Every stage's actual work lives
in a dedicated module:

    stages_geometry.py   Stage 1 (geometry) + Stage 1c (char hierarchy)
    stages_markers.py    Stage 2 (lights) + Stage 3 (marker empties)
    stages_animation.py  Stage 4 (OBJTRAK2 level tracks) + Stage 4b
                         (character NLA bake)
    level_baker.py       OBJTRAK2 -> NLA strips on dedicated empties
    summary.py           final SUMMARY block + report() calls
    operator_ui.py       draw() body
    presets.py           PRESET_ITEMS + apply_preset
    operator_stats.py    ImportStats + ImportCounters
    ffl_bridge.py        optional extraction of fastfile/*.ffl

Conventions:
  - OBJHEAD1.pos / .quat are ABSOLUTE (world) rest transforms.
  - OBANALLS frames are BONE-LOCAL relative to the parent; see
    char_baker.py for the composition math.
  - OBJTRAK2 sections are piecewise-linear keyframes with slerp;
    see parsers/level_track.py and level_baker.py.
  - Geometry stage fetches new objects from the collection it just
    linked into (not bpy.data.objects by name) so a second import of
    the same RIF does not tag the wrong mesh.

Stage functions receive frozen dataclass configs (StageLightsConfig,
StageMarkersConfig, StageLevelAnimConfig, StageCharAnimConfig) built
here, so the Stage layer is testable without a mock operator.

execute() snapshots scene.render.fps before running the pipeline and
restores it if an unexpected exception is raised mid-import. Stage 4
sets the FPS to animation_fps intentionally; leaving it set after a
crash would silently change the preview speed of every later import
in the same session.
"""

from __future__ import annotations

import logging
import math
import os
import time

import bpy

from ._version import __version_str__
from .discovery import discover_paths
from .ffl_bridge import ensure_textures
from .rif_loader import load_rif_auto, build_rif_index
from .utils import log, configure_logging
from .config import (
    BITMAP_MODES, PIVOT_MODES, EXT_RIF_STRATEGIES, ORPHAN_MODES,
    MAT_ROUGHNESS, MAT_SPECULAR,
    OrphanMode, PivotMode, ExtRifStrategy,
)
from .collections_util import create_import_collections, apply_auto_smooth
from .materials import build_tex_index
from .scan import RifScanner
from .shape_processor import ImportContext

from .presets import PRESET_ITEMS, apply_preset
from .operator_stats import ImportStats, ImportCounters
from .operator_ui import draw_operator_panels
from .summary import print_summary
from .stages_geometry import run_stage_geometry, run_stage_char_hierarchy
from .stages_markers import (
    run_stage_lights, run_stage_markers,
    StageLightsConfig, StageMarkersConfig,
)
from .stages_animation import (
    run_stage_level_animations, run_stage_char_animations,
    StageLevelAnimConfig, StageCharAnimConfig,
)


# Legacy UV-related values. These were once user-visible operator
# properties; they are now fixed constants so ImportContext keeps a
# stable shape regardless of UI state.
_UV_SCALE = 0.0078125    # /128
_UV_INT16 = False        # always float
_USE_ROTATION = True     # always apply rotation


class IMPORT_OT_avp_rif(bpy.types.Operator):
    """Import an AvP (1999) .RIF file into the current scene."""

    bl_idname = "import_scene.avp_rif"
    bl_label = "Import AvP RIF"
    bl_options = {'REGISTER', 'UNDO'}

    # --- preset ---------------------------------------------------------
    preset: bpy.props.EnumProperty(
        name="Preset",
        items=PRESET_ITEMS,
        default="DEFAULT",
        update=apply_preset,
        description="Quick configuration bundle. Picking a preset overwrites "
                    "the settings below; you can still tweak them afterwards.")

    # --- file selection -------------------------------------------------
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.rif;*.RIF",
                                          options={'HIDDEN'})

    # === Geometry =======================================================
    scale: bpy.props.FloatProperty(
        name="Scale World", default=0.001, min=0.0001, max=1000.0,
        precision=3,
        description="Scale factor applied to all positions and geometry. "
                    "AvP uses integer units roughly equal to 1/1024 m, so 0.001 "
                    "gives a scene close to real-world size")
    pivot_mode: bpy.props.EnumProperty(
        name="Pivot Mode",
        items=[(m[0], m[1], m[2]) for m in PIVOT_MODES], default="ROTATED_ONLY",
        description="How to handle object pivots.\n"
                    "Rotated only: only re-center objects with non-identity rotation.\n"
                    "None: keep the pivot as stored in the RIF file.\n"
                    "All: re-center every object (debug)")
    ext_rif_strategy: bpy.props.EnumProperty(
        name="External RIF",
        items=[(m[0], m[1], m[2]) for m in EXT_RIF_STRATEGIES], default="auto",
        description="How to choose between the placeholder shape inside this RIF "
                    "and a shape from an external RIF referenced by SHPEXTFL.\n"
                    "Auto: pick whichever has more vertices.\n"
                    "Prefer ext: always use the external shape.\n"
                    "Prefer placeholder: always use the placeholder")
    orphan_mode: bpy.props.EnumProperty(
        name="Orphan Shapes",
        items=[(m[0], m[1], m[2]) for m in ORPHAN_MODES], default="SKIP",
        description="What to do with shapes that have no matching OBJHEAD1 "
                    "(the game does not render them):\n"
                    "Skip: do not import them (matches game behavior).\n"
                    "Keep at origin: import them at (0,0,0) for debugging.\n"
                    "Infer: try to guess their position from nearby objects")
    auto_smooth: bpy.props.BoolProperty(
        name="Auto Smooth", default=True,
        description="After import, apply Auto Smooth to all imported meshes so "
                    "faces below the angle threshold are shaded smooth and hard "
                    "edges are kept above it. Disable to import flat-shaded meshes")
    auto_smooth_angle: bpy.props.FloatProperty(
        name="Auto Smooth Angle",
        default=math.radians(60.0),
        min=0.0,
        max=math.radians(180.0),
        subtype='ANGLE',
        description="Angle threshold for Auto Smooth. Faces whose angle between "
                    "neighbours exceeds this value keep a hard edge")

    # === Materials ======================================================
    import_materials: bpy.props.BoolProperty(
        name="Import Materials", default=True,
        description="Create Blender materials and load textures for imported "
                    "geometry. Disable for a fast geometry-only import that "
                    "skips all texture and material work")
    bitmap_mode: bpy.props.EnumProperty(
        name="Bitmap Mode",
        items=[(m[0], m[1], m[2]) for m in BITMAP_MODES], default="LO12",
        description="Which bitmap LOD to use for material lookup: "
                    "LO12 = low-resolution textures, HI12 = high-resolution")
    apply_matchimg: bpy.props.BoolProperty(
        name="Use MATCHIMG", default=True,
        description="Apply MATCHIMG texture substitution rules found in the RIF "
                    "(swaps one texture for another at import time)")
    use_clrlookp: bpy.props.BoolProperty(
        name="Use CLRLOOKP", default=True,
        description="Use the CLRLOOKP color palette to tint polygons that have "
                    "no texture reference. Without this they fall back to magenta")
    cull_backfaces: bpy.props.BoolProperty(
        name="Backface Culling", default=True,
        description="Hide back-facing polygons on imported materials, matching "
                    "the AvP engine (id-tech derivative). Designer/helper "
                    "geometry with inverted normals - e.g. Lockdown4's "
                    "VAULTLEVELS room copy, Colony floor signs - is invisible "
                    "in-game; without culling it shows through walls and "
                    "Z-fights with real surfaces. Turn OFF to inspect that "
                    "geometry in Blender (result will not match the game). "
                    "Only affects Eevee (Material Preview / Render); Cycles "
                    "ignores use_backface_culling")
    extract_ffl: bpy.props.BoolProperty(
        name="Extract FFL", default=True,
        description="When Import Materials is ON, look for a 'fastfile' "
                    "directory near the RIF and extract its .ffl texture "
                    "archives to 'fastfile/_ffl_unpacked/' if the latter "
                    "is missing or empty. Subsequent imports reuse the "
                    "cached PNG files. Skipped when Import Materials is "
                    "OFF, since extracted textures would be unused")

    # === Data ===========================================================
    import_dummy: bpy.props.BoolProperty(
        name="Import DUMMYOBJ", default=True,
        description="Import DUMMYOBJ entries as empties. These mark attachment "
                    "points, spawn locations and other reference points used by "
                    "the level")
    import_placed_hier: bpy.props.BoolProperty(
        name="Import PLACHIER", default=True,
        description="Import PLACHIER hierarchy markers as empties. These describe "
                    "placed objects and their parent hierarchy")
    import_avpgener: bpy.props.BoolProperty(
        name="Import AVPGENER", default=True,
        description="Import AVPGENER marker generators as empties. These define "
                    "where the game spawns dynamic entities (items, enemies)")
    import_soundob2: bpy.props.BoolProperty(
        name="Import SOUNDOB2", default=True,
        description="Import SOUNDOB2 sound emitters as empties with their sound "
                    "name, radius and volume as custom properties")
    import_avpstart: bpy.props.BoolProperty(
        name="Import AVPSTART", default=True,
        description="Import AVPSTART player start positions as empties")
    import_camorign: bpy.props.BoolProperty(
        name="Import CAMORIGIN", default=True,
        description="Import CAMORIGN camera origins as empties. These are used "
                    "by the level's scripted camera sequences")
    import_paths: bpy.props.BoolProperty(
        name="Import AVPPATH2", default=True,
        description="Import AVPPATH2 AI patrol paths as curve objects so you "
                    "can inspect them in the viewport")
    import_lights: bpy.props.BoolProperty(
        name="Import LIGHTSET", default=True,
        description="Import STDLIGHT entries from LIGHTSET as Blender point/spot "
                    "lights with color, brightness and range mapped from the RIF")

    # === Animation ======================================================
    animate_objects: bpy.props.BoolProperty(
        name="Animate Level Tracks", default=True,
        description="Import OBJTRAK2 level-track animations (doors, lifts, "
                    "rotating fans, moving platforms) as NLA strips on "
                    "dedicated Empty objects. One Empty per track; each "
                    "section becomes a linear keyframe pair")
    animation_fps: bpy.props.IntProperty(
        name="FPS", default=60, min=1, max=120,
        description="Frames per second used when converting AvP animation "
                    "timing into Blender keyframes. AvP's native animation "
                    "tick is 60 Hz, so 60 matches the game's playback "
                    "speed. Also synced to scene.render.fps, so changing "
                    "this value changes preview speed for both character "
                    "and level animations")
    animate_characters: bpy.props.BoolProperty(
        name="Animate Characters", default=True,
        description="Bake OBANALLS character animation sequences (avp_huds/"
                    "hnpc*.rif) as NLA tracks on the bone objects. One NLA "
                    "track is created per sequence per bone; the first "
                    "non-trivial sequence of each bone is left unmuted so "
                    "pressing Play animates the creature. See char_baker.py "
                    "for the axis and parent-compensation math")
    char_anim_limit: bpy.props.IntProperty(
        name="Sequences per Bone", default=0, min=0, max=100,
        description="How many sequences to bake per bone. 0 = all "
                    "sequences in the file (recommended), N > 0 = the first N. "
                    "A RIF with 39 bones and 7 sequences each produces 273 "
                    "NLA tracks if set to 0 - use this to keep the Outliner "
                    "manageable while previewing")

    # === Debug ==========================================================
    diagnostics_mode: bpy.props.BoolProperty(
        name="Diagnostic Mode", default=False,
        description="Only parse and log the structure of the RIF - do not create "
                    "any Blender data. Also disables chunk-stream resync so that "
                    "unexpected separators are reported rather than hidden")
    mark_missing_ext: bpy.props.BoolProperty(
        name="Mark Missing SHPEXTFL", default=False,
        description="Create an empty marker at the position of every SHPEXTFL "
                    "reference that could not be resolved to an external RIF. "
                    "Markers go into a dedicated '<level>_MissingExtRif' "
                    "subcollection so they can be hidden with one click. Useful "
                    "for finding the spot in-game and checking what the level "
                    "originally had there. The subcollection is only created "
                    "when this option is enabled")

    def draw(self, context):
        """Delegate UI drawing to operator_ui.draw_operator_panels."""
        draw_operator_panels(self, self.layout)

    def execute(self, context):
        """Run the import pipeline; return {'FINISHED'} or {'CANCELLED'}."""
        configure_logging(logging.DEBUG if self.diagnostics_mode
                          else logging.INFO)
        # Snapshot FPS before running. Stage 4 changes it on purpose
        # (AvP's native tick is 60 Hz), so a successful import leaves it
        # modified; only a failed import rolls back to the pre-import
        # value so the preview speed of later imports is unaffected.
        saved_fps = context.scene.render.fps

        try:
            return self._run_pipeline(context, saved_fps)
        except Exception as e:                              # noqa: BLE001
            log.exception(f"Import failed: {type(e).__name__}: {e}")
            if context.scene.render.fps != saved_fps:
                context.scene.render.fps = saved_fps
                log.info(f"Restored scene FPS to {saved_fps} "
                         f"(import did not complete)")
            self.report({'ERROR'}, f"Import failed: {type(e).__name__}: {e}")
            return {'CANCELLED'}

    def _run_pipeline(self, context, saved_fps):
        """Pipeline body, wrapped by execute() so it can roll back FPS."""
        smooth_deg = math.degrees(self.auto_smooth_angle)

        log.info("")
        log.info("=" * 70)
        log.info(f"AvP RIF Importer {__version_str__}")
        log.info(f"FILE: {os.path.basename(self.filepath)}")
        log.info(f"Preset={self.preset}")
        log.info(f"Scale={self.scale}, Orphan={self.orphan_mode}, "
                 f"Pivot={self.pivot_mode}")
        log.info(f"Import Materials={'ON' if self.import_materials else 'OFF'}")
        log.info(f"Auto Smooth={'ON' if self.auto_smooth else 'OFF'}"
                 + (f" ({smooth_deg:.1f} deg)" if self.auto_smooth else ""))
        log.info(f"Materials: roughness={MAT_ROUGHNESS}, specular={MAT_SPECULAR}")
        log.info(f"Backface Culling: "
                 f"{'ON' if self.cull_backfaces else 'OFF'}")
        log.info(f"Extract FFL: {'ON' if self.extract_ffl else 'OFF'}")
        log.info(f"Diagnostics: {'ON' if self.diagnostics_mode else 'OFF'}")
        log.info(f"Mark Missing SHPEXTFL: "
                 f"{'ON' if self.mark_missing_ext else 'OFF'}")
        log.info("=" * 70)

        try:
            with open(self.filepath, 'rb') as f:
                raw = f.read()
        except OSError as e:
            self.report({'ERROR'}, f"Read error: {e}")
            return {'CANCELLED'}

        # Optionally extract fastfile/*.ffl -> fastfile/_ffl_unpacked/
        # before discover_paths looks for the texture directory. Skipped
        # when extract_ffl is off, when Import Materials is off, or when
        # the cache already contains PNG files.
        ffl_result = ensure_textures(
            self.filepath,
            enabled=self.extract_ffl,
            materials=self.import_materials,
        )
        log.info(f"FFL extract: {ffl_result.status} - {ffl_result.message}")

        discovered = discover_paths(self.filepath)
        log.info(f"Shape RIFs: {discovered.shape_rifs or '(not found)'}")
        log.info(f"Textures:   {discovered.textures or '(not found)'}")

        decoded = load_rif_auto(raw, verbose=True)
        if decoded is None:
            self.report({'ERROR'}, "Unknown format")
            return {'CANCELLED'}

        base = os.path.splitext(os.path.basename(self.filepath))[0]

        scanner = RifScanner(
            diagnostics_mode=self.diagnostics_mode,
            apply_matchimg=self.apply_matchimg,
            use_clrlookp=self.use_clrlookp,
            import_materials=self.import_materials,
            fallback_level_name=base,
        )
        scan = scanner.scan(decoded)

        if self.diagnostics_mode:
            self.report({'INFO'}, "Diagnostics complete.")
            return {'FINISHED'}

        optional = {"missing_ext"} if self.mark_missing_ext else set()
        cols = create_import_collections(base, enable_optional=optional)
        log.info(f"Created collection: {cols['__main__'].name}")

        if self.import_materials and discovered.textures:
            t = time.perf_counter()
            tex_idx = build_tex_index(discovered.textures)
            dt_tex = time.perf_counter() - t
            n_rel = len(tex_idx[0])
            n_base = len(tex_idx[1])
            log.info(f"Textures: {n_rel} lookup key(s), "
                     f"{n_base} unique basename(s) "
                     f"({dt_tex*1000:.0f} ms)")
        elif not self.import_materials:
            tex_idx = ({}, {})
            log.info("Textures: (skipped - Import Materials is OFF)")
        else:
            tex_idx = ({}, {})
            log.info("Textures: (skipped - no _ffl_unpacked directory found)")

        rif_dirs: list[str] = []
        if discovered.shape_rifs:
            rif_dirs.append(discovered.shape_rifs)
        rif_dirs.append(os.path.dirname(os.path.abspath(self.filepath)))
        seen_dirs: set[str] = set()
        rif_dirs = [d for d in rif_dirs
                    if not (d in seen_dirs or seen_dirs.add(d))]
        t = time.perf_counter()
        rif_index = build_rif_index(rif_dirs)
        dt_idx = time.perf_counter() - t
        log.info(f"RIF index: {len(rif_index)} file(s) "
                 f"from {len(rif_dirs)} dir(s) ({dt_idx*1000:.0f} ms)")
        for d in rif_dirs:
            log.info(f"  + {d}")

        ext_stats = {"with_extfl": 0, "resolved": 0}

        ctx = ImportContext(
            base=base, scale=self.scale,
            bmp_names=scan.bmp_names, tex_idx=tex_idx,
            bm_mode=self.bitmap_mode, uv_scale=_UV_SCALE,
            uv_int16_mode=_UV_INT16,
            mat_cache={}, matchimg_index=scan.matchimg_index,
            rif_index=rif_index, ext_cache={}, ext_stats=ext_stats,
            pivot_mode=PivotMode(self.pivot_mode),
            ext_strategy=ExtRifStrategy(self.ext_rif_strategy),
            use_rotation=_USE_ROTATION,
            clrlookp_table=scan.clrlookp_table,
            orphan_mode=OrphanMode(self.orphan_mode),
            placed_positions=scan.placed_positions,
            all_objects=scan.all_obj_headers,
            level_hint=scan.level_name,
            import_materials=self.import_materials,
            cull_backfaces=self.cull_backfaces,
            mark_missing_ext=self.mark_missing_ext,
            missing_ext_collection=cols.get("missing_ext"),
            character_mode=bool(scan.char_bones),
        )

        stats = ImportStats()
        counters = ImportCounters()
        state = {
            "cols": cols,
            "stats": stats,
            "ext_stats": ext_stats,
            "timings": {},
        }

        t = time.perf_counter()
        sub_timings = run_stage_geometry(scan, ctx, stats, cols["geometry"])
        state["timings"]["Stage 1 Geometry"] = time.perf_counter() - t
        if sub_timings:
            state["timings"]["  1a Parse"] = sub_timings["parse"]
            state["timings"]["  1b Mesh"] = sub_timings["mesh"]
            state["timings"]["  1c Materials"] = sub_timings["mat"]

        t = time.perf_counter()
        run_stage_char_hierarchy(scan, base, cols, counters, self.scale)
        if scan.char_bones:
            state["timings"]["Stage 1c CharHier"] = time.perf_counter() - t

        if self.auto_smooth and stats.ok > 0:
            log.info("")
            log.info(f"--- Stage 1b: Auto Smooth ({smooth_deg:.1f} deg) ---")
            t = time.perf_counter()
            counters.smooth = apply_auto_smooth(cols["geometry"],
                                                self.auto_smooth_angle)
            state["timings"]["Stage 1b AutoSmooth"] = time.perf_counter() - t
            log.info(f"Applied Auto Smooth to {counters.smooth} mesh(es)")

        t = time.perf_counter()
        run_stage_lights(
            StageLightsConfig(import_lights=self.import_lights,
                              scale=self.scale),
            scan, counters, base, cols,
        )
        if scan.lightset_list and self.import_lights:
            state["timings"]["Stage 2 Lights"] = time.perf_counter() - t

        t = time.perf_counter()
        run_stage_markers(
            StageMarkersConfig(
                import_dummy=self.import_dummy,
                import_placed_hier=self.import_placed_hier,
                import_avpgener=self.import_avpgener,
                import_soundob2=self.import_soundob2,
                import_avpstart=self.import_avpstart,
                import_camorign=self.import_camorign,
                import_paths=self.import_paths,
                scale=self.scale,
            ),
            scan, counters, base, cols,
        )
        state["timings"]["Stage 3 Markers"] = time.perf_counter() - t

        t = time.perf_counter()
        run_stage_level_animations(
            StageLevelAnimConfig(
                animate_objects=self.animate_objects,
                scale=self.scale,
                animation_fps=self.animation_fps,
            ),
            scan, counters, base, cols,
        )
        if scan.objtrak_list and self.animate_objects:
            state["timings"]["Stage 4 Animations"] = time.perf_counter() - t

        t = time.perf_counter()
        run_stage_char_animations(
            StageCharAnimConfig(
                animate_characters=self.animate_characters,
                scale=self.scale,
                animation_fps=self.animation_fps,
                char_anim_limit=self.char_anim_limit,
            ),
            scan, counters, cols,
        )
        if scan.char_anims and self.animate_characters:
            state["timings"]["Stage 4b CharAnim"] = time.perf_counter() - t

        print_summary(self, scan, state, counters, ctx)
        return {'FINISHED'}

    def invoke(self, context, event):
        """Open the file selector instead of running execute() directly."""
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class IMPORT_OT_avp_rif_menu(bpy.types.Operator):
    """Thin wrapper operator that invokes the main importer from the menu."""

    bl_idname = "import_scene.avp_rif_menu"
    bl_label = "Aliens vs Predator RIF (.rif)"

    def execute(self, context):
        """Open the main importer's file selector."""
        bpy.ops.import_scene.avp_rif('INVOKE_DEFAULT')
        return {'FINISHED'}


def menu_func_import(self, context):
    """Append the add-on entry to File > Import."""
    self.layout.operator(IMPORT_OT_avp_rif_menu.bl_idname,
                         text="Aliens vs Predator RIF (.rif)")


classes = (IMPORT_OT_avp_rif, IMPORT_OT_avp_rif_menu)