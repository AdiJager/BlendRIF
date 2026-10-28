# Changelog

All notable changes to AvP RIF Importer are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.3.2] - 2026-10-26

### Fixed

- **UVs now match the game.** The RIF stores UVs as integer texel
  indices of the bitmap a polygon uses, and the engine draws the texel
  centres with v measured from the top of the image
  (`Kshape.c` shifts the index into 16.16, `d3d_render.cpp` divides by
  the loaded image size and adds half a texel). The importer used to
  divide every UV by a fixed 128 and kept v unflipped, so textures were
  mirrored vertically and 256px bitmaps were tiled at the wrong scale.
  UVs are now converted per polygon with
  `u = (u + 0.5) / width`, `v = 1 - (v + 0.5) / height` using the actual
  size of the resolved texture (falling back to 128 when the bitmap has
  no file); the fixed `/128` scale is gone.

## [1.3.1] - 2026-10-20

### Changed

- **"Import Morph" lives in the Data section** next to the other
  opt-in import types, and its meshes go into a dedicated
  `<level>_Morphs` collection instead of the level geometry, so they
  can be hidden or deleted in one click and never mix with the visible
  mesh. The collection is only created when the option is on. Auto
  Smooth now covers the morph collection too.

## [1.3.0] - 2026-10-20

### Added

- **Morph target import** (`Data > Import Morph`, off by default).
  A shape that morphs carries `SHPMORPH` next to its own geometry; its
  `SUBSHAPE` children are the alternate meshes the game blends to
  (doors, hatches, the xenoborg morph room). With the option on, each
  target is imported as its own mesh placed with the parent shape's
  transform, marked `avp_type = "morph"` with `avp_morph_parent` and
  `avp_morph_index`, and it reuses the parent's materials. Off by
  default because the game never draws these as objects of their own:
  importing them adds hidden duplicates to every level. Targets whose
  parent shape has no placement in the level are skipped and counted.

## [1.2.0] - 2026-10-11

### Changed

- **Converted further towards the Extensions platform requirements.**
  `bl_info` was dropped from `__init__.py` (the manifest is the single
  source of metadata, as the manual's conversion guide asks) and the
  undocumented `tracker` key was removed from the manifest, which keeps
  only documented fields. Verified against every rule on the "How to
  Create Extensions" page: manifest fields, tag list, permission
  wording, `[build]` patterns, package contents and relative imports.
- **Textures are resolved by path, and materials are named after them.**
  The bitmap's stored game path now decides which file is loaded
  (accepting the tree's `graphics/` prefix and the `.rim` extension),
  the bare file name is only used when exactly one file carries it, and
  every ambiguous or missing lookup is counted and printed in the import
  summary. 3,328 of the 3,342 bitmap references in the shipped levels
  resolve by path; the 14 that cannot are `Common/weapon01`, `Common/
  extrs09` and `Common/EdObjects5`, which no archive contains. Material
  names are derived from the texture path (`Stat101_Common_Lights`,
  `Stat101_Envrnmts_Towers03_Lights`), so the two different `lights.rim`
  textures can no longer alias onto one material, and each material
  records its source path in `avp_tex_path`. Two textures that would
  nonetheless collide get a deterministic path hash appended.
- **MATCHIMG rules are parsed and applied correctly.** The
  `ImageDescriptor` record was being read without its 4-byte alignment
  padding, so most rules decoded as garbage or were missed; all 50
  chunks and 2,128 rules now parse, and a substitution uses the rule's
  own path (the engine's behaviour) instead of its bare file name,
  preferring the rule whose RIM name matches the bitmap.

## [1.1.0] - 2026-10-11

### Added

- **Waypoint import** (`Data > Import Waypoints`, off by default). Each
  AI module's Alien navigation volumes (`WAYPOINT` chunks inside
  `MODULEDT`) are imported as cube empties sized to the volume, placed
  at the volume's aim point, with the links to neighbouring volumes
  stored as `avp_wp_link_indices` / `avp_wp_link_flags` properties.
  Objects land in a `<level>_Waypoints` subcollection that is only
  created when the option is on. The ground/marine half of the same
  chunk is not imported: it was superseded by `AVPPATH2` patrol paths
  before release and none of the 664 retail chunks carries the
  `WaypointFlag_FirstGroundWaypoint` marker.

### Fixed

- **AI patrol paths (`Data > Import AVPPATH2`) are placed correctly.**
  A path is an ordered list of AI modules, not of coordinates: the
  per-point location field is zero in all 1116 retail points, and the
  game walks from module to module using each module's world position.
  The curve is now built through the referenced modules' `OBJHEAD1`
  positions instead of through the point records (which stacked every
  point at the level origin). Points whose module has no `OBJHEAD1` in
  the file are skipped, and each path object now carries
  `avp_module_index`, `avp_point_flags` and `avp_flags`.
- Paths whose stored name is empty are imported instead of dropped (one
  such path exists in `Nost03.RIF`), a truncated point list makes the
  parser return "malformed" instead of silently shortening the path, and
  `PathFlag_LoopPath` now actually closes the curve (the cyclic flag was
  being set on the curve datablock instead of the spline).

### Changed

- **Packaging**: the Extensions ZIP is now produced by Blender itself
  (`blender --command extension build`) instead of a hand-rolled zip, so
  the package contains only what the add-on needs at run time (`docs/`,
  `tests/` and `tools/` are excluded in the manifest). Both build
  targets land in `builds/` and carry the version in their file names:
  `avp_rif_importer-<version>.zip` and
  `avp_rif_importer-<version>-legacy.zip`.
- **Versioning**: Blender owns extension versioning, so the import-time
  `_check_version_consistency` self-check was removed; `bl_info`,
  `blender_manifest.toml` and `_version.py` are still updated together
  by hand.

## [1.0.0] - 2026-09-25

Initial public release.

### Added

**Formats**
- Import of AvP (1999, Rebellion) `.RIF` files:
  - `REBCRIF1` - Huffman-compressed container
  - `REBINFF2` - raw container
- Recursive chunk parser with size and bounds validation.

**Geometry**
- Shape geometry (`OBJSHPGRP` / SHAPES subtree): vertex positions,
  polygon colours (unsigned), UV indices, bitmap list, per-shape
  material slots.
- Material creation from bitmap lists with texture assignment.
  `SHPEXTFL` local bitmaps take priority over `ext_bitmaps`.
- Object placements (`RBOBJECTS`) mapped N:N onto imported shapes.

**Character rigs**
- Character hierarchy (`OBJCHIER`) parsing via `parse_objchier_tree`.
  Hierarchy is nesting-based; wrapper chunks without `OBJHIERD` are
  transparent.
- Armature construction with per-bone head/tail derived from shape
  vertices.

**Animation**
- Character animation (`OBANALLS`) baking to Blender Actions.
  Frames are bone-local; root uses `apply_axis(trans)` plus
  axis-mapped quaternion, children use direct translation and
  quaternion.
- Level track animation (`OBJTRAK2`) with pivot travel and
  Catmull-Rom interpolation (76-byte sections, 8-byte trailer).
- NLA track creation with default unmute by
  `(sequence_number, sub_sequence_number)`.

**Extras**
- Marker import (level spawn and camera markers).
- Light import.
- FFL texture extraction (`ffl_extractor/` + `ffl_bridge.py`):
  locates `fastfile/*.ffl`, unpacks ILBM/ByteRun1 to PNG in
  `fastfile/_ffl_unpacked/`, reuses cache on repeat imports.
  `Snd*.ffl` and non-RFFL archives are skipped.

**UI**
- `File -> Import -> Aliens vs Predator RIF (.rif)` operator with
  presets and per-category toggles (geometry, materials, rig,
  animation, markers, lights, FFL extract).
- Import summary panel with counts and timings.

### Notes

- Target renderer: **Eevee**.
- Requires Blender 3.0 or newer. Blender 4.4+ layered Actions
  supported via API fallback; legacy `Action.fcurves` (3.x-5.x)
  also supported.
- Axis conversion `apply_axis(x, y, z) = (x, z, -y)` converts AvP
  Z-up to Blender Z-up throughout.
- AvP `.RIF` uses a Huffman codec. `sum(counts)` in the header
  equals alphabet size (~257), not `us` (byte size).
- `parse_chunks` validates `size >= 12` and bounds before recursing;
  invalid chunks return `None` with `log.debug` (normal recursive
  path can produce false positives).

### Testing

- 184 unit tests, all green. Coverage:
  - binary reader, chunk parser, Huffman codec
  - parsers: shapes, bitmaps, markers, lights, char_anim, level_track
  - pure helpers: geometry, utils, `char_baker` FCurve iteration
  - hardening (sanity caps, rollback, chunk bounds)
  - double-import safety (collection lookup vs
    `bpy.data.objects.get`)

### Packaging

- `blender_manifest.toml` for Blender 4.2+ Extensions platform.
- `bl_info` retained in `__init__.py` as fallback for Blender 3.x-4.1
  (removed again in 1.2.0 - the manifest is the single source of
  metadata).
- Single-file version source: `_version.py` (`__version__`, PEP 396)
  plus `bl_info["version"]` literal; a self-check in `register()` warned
  on mismatch (removed again in 1.1.0 - Blender owns extension
  versioning).

[Unreleased]: https://github.com/AdiJager/BlendRIF/compare/v1.3.2...HEAD
[1.3.2]: https://github.com/AdiJager/BlendRIF/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/AdiJager/BlendRIF/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/AdiJager/BlendRIF/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/AdiJager/BlendRIF/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/AdiJager/BlendRIF/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/AdiJager/BlendRIF/releases/tag/v1.0.0