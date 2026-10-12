# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Texture index, path-first resolution and material naming.

The game identifies a texture by its stored path (`BitmapEntry.raw_name`,
e.g. `Common/Lights.RIM`), while several shipped levels reuse one file
name in different directories - 192 of the extracted texture names exist
under more than one path, so resolving by name alone silently picks the
wrong image. Everything here therefore resolves **by path first** and
treats the bare name as a last resort that is logged.

Lookup order for `resolve_texture`:

  1. the RIF path as stored (`envrnmts/towers03/lights.rim`),
  2. the RIF path with some other known prefix (`envrnmts/...`,
     `graphics/envrnmts/...`),
  3. the RIF path under the level's own directory
     (`<level>/envrnmts/towers03/lights.rim`),
  4. the bare file name, only when it maps to exactly one file;
     several candidates mean the result is ambiguous and is reported.

This module imports no bpy, so the whole resolution policy is unit
testable; `materials.py` turns the resolved path into Blender materials.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field

from .utils import log


# Prefixes that a RIF path may carry but the extracted tree may not.
PATH_PREFIXES = ("graphics/", "textures/", "texture/", "art/", "artwork/")

# Generic container directories that carry no identifying information in
# a material name.
GENERIC_DIRS = {"graphics", "textures", "texture", "art", "artwork"}

# Material name segments are ASCII-safe and bounded.
MAT_NAME_MAX = 60
_HASH_LEN = 6
_UNSAFE = re.compile(r"[^0-9a-z_]+")


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@dataclass
class TextureStats:
    """How the textures of one import were resolved (mutable, per import).

    Counting is per *bitmap*, not per polygon: `mark_seen` is called with a
    stable key (the RIF path or name) and returns False when that bitmap
    was already counted, so the summary reports decisions rather than
    every polygon that reused one.
    """
    exact: int = 0            # matched by a path candidate
    by_name_unique: int = 0   # no path hit, but the file name was unique
    ambiguous: int = 0        # several files share the name; one was picked
    missing: int = 0          # nothing matched
    ambiguous_examples: list = field(default_factory=list)
    missing_examples: list = field(default_factory=list)
    _seen: set = field(default_factory=set)

    @property
    def lookups(self) -> int:
        """Total number of resolution attempts."""
        return self.exact + self.by_name_unique + self.ambiguous + self.missing

    def mark_seen(self, key: str) -> bool:
        """Return False when this bitmap was already counted in this import."""
        if not key:
            return True
        if key in self._seen:
            return False
        self._seen.add(key)
        return True

    def record_ambiguous(self, raw: str, picked: str, n: int) -> None:
        """Count an ambiguous name hit and remember a few examples."""
        self.ambiguous += 1
        if len(self.ambiguous_examples) < 5:
            self.ambiguous_examples.append(f"{raw or '?'} -> {picked} "
                                           f"({n} candidates)")

    def record_missing(self, raw: str, name: str) -> None:
        """Count a texture that could not be resolved at all."""
        self.missing += 1
        if len(self.missing_examples) < 8:
            self.missing_examples.append(f"{raw or name or '?'}")


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TextureIndex:
    """Lookup tables over the extracted texture tree.

    `by_path` is keyed by each PNG's path relative to the tree, lower
    cased, forward slashes, without the extension, and additionally
    without a leading generic prefix (`graphics/`) so a RIF path can hit
    it directly. `by_name` keeps every file per bare name so ambiguous
    names can be detected instead of guessed.
    """
    root: str = ""
    by_path: dict = field(default_factory=dict)
    by_name: dict = field(default_factory=dict)

    def __iter__(self):
        """Yield (by_path, by_name) so older tuple-unpacking callers work."""
        yield self.by_path
        yield self.by_name

    def __len__(self) -> int:
        """Number of index keys, for logging."""
        return len(self.by_path)

    @property
    def n_files(self) -> int:
        """How many PNG files back this index."""
        return sum(len(v) for v in self.by_name.values())

    @property
    def n_ambiguous_names(self) -> int:
        """How many file names exist under more than one path."""
        return sum(1 for v in self.by_name.values() if len(v) > 1)

    def candidates(self, name: str) -> list:
        """Every PNG whose bare name matches, extension variants included.

        The extracted file keeps the game extension (`lights.rim.png`),
        so a lookup for `lights` also has to consider `lights.rim`.
        """
        low = name.lower()
        out: list[str] = []
        seen: set[str] = set()
        for key in (low, f"{low}.rim"):
            for full in self.by_name.get(key, []):
                if full not in seen:
                    seen.add(full)
                    out.append(full)
        return out


def normalize_path(raw_name: str) -> str:
    """Normalise a RIF texture path to an index key (no prefix, no extension).

    `Common/Lights.RIM` -> `common/lights`. A trailing `.rim`/`.bmp`
    extension is dropped, which is what the extracted tree's file names
    (`lights.rim.png`) collapse to as well.
    """
    if not raw_name:
        return ""
    p = raw_name.replace('\\', '/').strip().lower()
    p = os.path.splitext(p)[0]
    for pref in PATH_PREFIXES:
        if p.startswith(pref):
            p = p[len(pref):]
            break
    return p.lstrip('/')


def _path_candidates(key: str, level_hint: str = "") -> list:
    """Ordered index keys to try for one normalised RIF path.

    Every base form is tried as it is, with `graphics/` prefixed (the
    extracted tree keeps that directory) and with a `.rim` suffix: the
    RIF stores `Common/Lights.RIM` while the extracted file is
    `lights.rim.png`, and stripping extensions from both sides would
    otherwise drop the extension twice and never match.
    """
    if not key:
        return []
    bases = [key, f"{key}.rim"]
    if level_hint:
        bases += [f"{level_hint.lower()}/{key}",
                  f"{level_hint.lower()}/{key}.rim"]
    cands: list[str] = []
    for b in bases:
        cands.append(b)
        cands.append(f"graphics/{b}")
        for pref in PATH_PREFIXES:
            cands.append(f"{pref}{b}")
    seen: set[str] = set()
    out = []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


# ---------------------------------------------------------------------------
# Index construction
# ---------------------------------------------------------------------------

# Keyed by (absolute root, mtime); invalidates when the directory changes.
_INDEX_CACHE: dict[tuple, TextureIndex] = {}


def build_texture_index(root: str) -> TextureIndex:
    """Walk `root` once and return the cached texture index."""
    if not os.path.isdir(root):
        return TextureIndex(root=root)

    try:
        mtime = os.path.getmtime(root)
    except OSError:
        mtime = 0.0

    cache_key = (os.path.abspath(root), mtime)
    hit = _INDEX_CACHE.get(cache_key)
    if hit is not None:
        return hit

    by_path: dict[str, str] = {}
    by_name: dict[str, list] = {}
    for dirpath, _dirnames, files in os.walk(root):
        for f in files:
            if not f.lower().endswith(".png"):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, root).replace(os.sep, '/').lower()
            rel_key = os.path.splitext(rel)[0]
            by_path[rel_key] = full
            for pref in PATH_PREFIXES:
                if rel_key.startswith(pref):
                    by_path.setdefault(rel_key[len(pref):], full)
            by_name.setdefault(os.path.splitext(f)[0].lower(), []).append(full)

    idx = TextureIndex(root=os.path.abspath(root), by_path=by_path,
                       by_name=by_name)
    _INDEX_CACHE[cache_key] = idx
    return idx


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TextureResolution:
    """Outcome of resolving one bitmap reference."""
    png: str | None = None        # absolute PNG path, or None
    source_path: str = ""         # tree-relative path of the PNG
    via: str = ""                 # path | path-variant | level | name | miss

    def __bool__(self) -> bool:
        """True when a PNG was found."""
        return self.png is not None


def resolve_texture(tex_index, name: str, raw_name: str = "",
                    level_hint: str = "",
                    stats: TextureStats | None = None) -> TextureResolution:
    """Resolve one bitmap to a PNG, path first, bare name last.

    `name` is the bitmap basename from BMPLSTST (used for the name
    fallback), `raw_name` its stored game path (the authoritative key).
    Ambiguous and missing results are counted in `stats` and logged.
    """
    if isinstance(tex_index, tuple):        # tolerate the legacy 2-tuple
        tex_index = TextureIndex(by_path=tex_index[0], by_name=tex_index[1])

    # Count each bitmap once per import, however many polygons use it.
    counting = stats is not None and stats.mark_seen(raw_name or name)

    key = normalize_path(raw_name)
    if key:
        for cand in _path_candidates(key, level_hint):
            full = tex_index.by_path.get(cand)
            if full is not None:
                # Compare on the resolved key, so a `.rim` suffix or a
                # `graphics/` prefix does not turn the RIF's own path
                # into a "variant".
                resolved = cand
                for pref in ("graphics/",) + PATH_PREFIXES:
                    if resolved.startswith(pref):
                        resolved = resolved[len(pref):]
                        break
                keys = {key, f"{key}.rim"}
                level_keys = ({f"{level_hint.lower()}/{key}",
                               f"{level_hint.lower()}/{key}.rim"}
                              if level_hint else set())
                if resolved in level_keys:
                    via = "level"
                elif resolved in keys:
                    via = "path"
                else:
                    via = "path-variant"
                if counting:
                    stats.exact += 1
                return TextureResolution(png=full,
                                         source_path=_relpath(full, tex_index),
                                         via=via)

    if not name:
        if counting:
            stats.record_missing(raw_name, name)
        log.warning(f"    [TEX] no path and no name for {raw_name!r}")
        return TextureResolution()

    cands_all = tex_index.candidates(name)
    if len(cands_all) == 1:
        if counting:
            stats.by_name_unique += 1
        if key:
            log.info(f"    [TEX] {raw_name or name}: no path match, using the "
                     f"only file named {name!r}")
        return TextureResolution(png=cands_all[0],
                                 source_path=_relpath(cands_all[0], tex_index),
                                 via="name")
    if len(cands_all) > 1:
        picked = sorted(cands_all)[0]
        rel = _relpath(picked, tex_index)
        if counting:
            stats.record_ambiguous(raw_name or name, rel, len(cands_all))
        log.warning(f"    [TEX] {raw_name or name}: {len(cands_all)} files "
                    f"share the name {name!r}; using {rel}")
        return TextureResolution(png=picked, source_path=rel, via="name")

    if counting:
        stats.record_missing(raw_name, name)
    log.warning(f"    [TEX] {raw_name or name}: no texture file found")
    return TextureResolution()


def _relpath(png: str, tex_index: TextureIndex) -> str:
    """Tree-relative path of a PNG, for names and properties."""
    if not tex_index.root:
        return os.path.basename(png)
    try:
        return os.path.relpath(png, tex_index.root).replace(os.sep, '/')
    except ValueError:                        # different drive on Windows
        return os.path.basename(png)


# ---------------------------------------------------------------------------
# Material naming
# ---------------------------------------------------------------------------

# Extensions that appear inside a texture's name once the extracted tree
# appended `.png` (`lights.rim.png`), so names stay tool-agnostic.
GAME_EXTENSIONS = (".rim", ".bmp", ".pcx", ".iff", ".lbm", ".tga", ".png",
                   ".jpg", ".jpeg")


def material_name(base: str, texture_path: str, fallback: str = "") -> str:
    """Build a deterministic material name from a texture's path.

    `graphics/common/lights.rim.png` with base `Stat101` becomes
    `Stat101_common_lights`: generic container directories and the game
    extension are dropped. The result is bounded, and `disambiguate_name`
    is available for the rare case of two paths collapsing to one name.
    """
    rel = texture_path.replace('\\', '/').lower()
    parts = [p for p in rel.split('/') if p]
    if parts:
        leaf = parts[-1]
        for ext in (".png", ".jpg", ".jpeg"):
            if leaf.endswith(ext):
                leaf = leaf[: -len(ext)]
                break
        for ext in GAME_EXTENSIONS:
            if leaf.endswith(ext):
                leaf = leaf[: -len(ext)]
                break
        parts[-1] = leaf
    parts = [p for p in parts if p not in GENERIC_DIRS]
    suffix = "_".join(parts) if parts else (fallback or "texture")
    clean = _UNSAFE.sub("_", suffix.replace(" ", "_")).strip("_")
    name = f"{base}_{clean}" if clean else f"{base}_texture"
    if len(name) > MAT_NAME_MAX:
        digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:_HASH_LEN]
        name = f"{name[:MAT_NAME_MAX - _HASH_LEN - 1]}_{digest}"
    return name


def disambiguate_name(name: str, texture_path: str) -> str:
    """Append a short path hash so two textures never share a name."""
    digest = hashlib.sha1(texture_path.replace('\\', '/').lower()
                          .encode("utf-8")).hexdigest()[:_HASH_LEN]
    return f"{name}_{digest}"

