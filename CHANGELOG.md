# Changelog

All notable changes to AvP RIF Importer are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

- Target renderer: **Eevee**. Cycles is out of scope.
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
- `bl_info` retained in `__init__.py` as fallback for Blender 3.x-4.1.
- Single-file version source: `_version.py` (`__version__`, PEP 396)
  plus `bl_info["version"]` literal; self-check in `register()` warns
  on mismatch.

[Unreleased]: https://github.com/AdiJager/BlendRIF/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/AdiJager/BlendRIF/releases/tag/v1.0.0