"""Tests for textures: path-first resolution, stats and material naming.

The policy under test: a texture is identified by its stored game path; a
bare file name is used only when it maps to exactly one file, and every
ambiguous or missing lookup is counted and reported. Material names are
derived from the texture path so two textures never share one.

The resolution tests run against a real temporary texture tree, so the
index keys are the ones the importer builds from disk (a PNG named
`lights.rim.png` yields the key `common/lights.rim`).
"""

from __future__ import annotations

import os
import tempfile
import unittest

from avp_rif_importer.textures import (
    TextureStats, TextureResolution,
    build_texture_index, normalize_path, resolve_texture,
    material_name, disambiguate_name, GENERIC_DIRS,
)

# Relative layout of the fake extracted texture tree.
TREE = (
    "graphics/common/lights.rim.png",
    "graphics/envrnmts/towers03/lights.rim.png",
    "graphics/huds/alien/hand.rim.png",
    "graphics/stat101/common/panel.png",
)


class _TreeMixin:
    """Create the temporary texture tree once per test class."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = cls._tmp.name
        for rel in TREE:
            full = os.path.join(cls.root, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as fh:
                fh.write(b"\x89PNG\r\n\x1a\n")
        cls.idx = build_texture_index(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()


class TestNormalizePath(unittest.TestCase):
    """RIF paths and extracted file names must normalise to the same key."""

    def test_backslashes_and_case(self):
        self.assertEqual(normalize_path(r"Common\Lights.RIM"), "common/lights")

    def test_generic_prefix_is_stripped(self):
        self.assertEqual(normalize_path("graphics/HUDs/Alien/a.bmp"), "huds/alien/a")
        self.assertEqual(normalize_path("textures/common/x.png"), "common/x")

    def test_extension_is_dropped_once(self):
        # Extracted files keep the game extension: lights.rim.png.
        self.assertEqual(normalize_path("common/lights.rim"), "common/lights")

    def test_empty(self):
        self.assertEqual(normalize_path(""), "")


class TestResolveTexture(_TreeMixin, unittest.TestCase):
    """Resolution order: exact path, path variants, level, unique name."""

    def test_path_wins_over_name(self):
        """Two files share the name; the stored path must decide."""
        res = resolve_texture(self.idx, "lights",
                              "Envrnmts/Towers03/Lights.RIM")
        self.assertTrue(res)
        self.assertEqual(res.via, "path")
        self.assertIn("towers03", res.png)
        self.assertEqual(res.source_path,
                         "graphics/envrnmts/towers03/lights.rim.png")

    def test_other_path_of_the_same_name(self):
        res = resolve_texture(self.idx, "lights", "Common/Lights.RIM")
        self.assertTrue(res)
        self.assertIn("common", res.png)

    def test_prefix_variant_matches(self):
        """RIF path without graphics/ still hits the extracted tree."""
        res = resolve_texture(self.idx, "hand", "HUDs/Alien/Hand.RIM")
        self.assertTrue(res)
        self.assertEqual(res.via, "path")

    def test_level_hint_prefix(self):
        res = resolve_texture(self.idx, "panel", "common/panel.RIM",
                              level_hint="Stat101")
        self.assertTrue(res)
        self.assertEqual(res.via, "level")

    def test_unique_name_fallback_is_used(self):
        """A raw path that no longer exists still resolves by unique name."""
        res = resolve_texture(self.idx, "hand", "Old/Path/Hand.BMP")
        self.assertTrue(res)
        self.assertEqual(res.via, "name")
        self.assertIn("hand.rim.png", res.png)

    def test_ambiguous_name_is_reported_and_still_resolves(self):
        stats = TextureStats()
        res = resolve_texture(self.idx, "lights", "Nowhere/Lights.RIM",
                              stats=stats)
        self.assertTrue(res)
        self.assertEqual(stats.ambiguous, 1)
        self.assertEqual(stats.lookups, 1)
        self.assertEqual(len(stats.ambiguous_examples), 1)

    def test_missing_is_counted(self):
        stats = TextureStats()
        res = resolve_texture(self.idx, "nosuchtex", "Nope/Nosuchtex.RIM",
                              stats=stats)
        self.assertFalse(res)
        self.assertIsNone(res.png)
        self.assertEqual(stats.missing, 1)
        self.assertEqual(len(stats.missing_examples), 1)

    def test_exact_hits_are_counted(self):
        stats = TextureStats()
        resolve_texture(self.idx, "hand", "HUDs/Alien/Hand.RIM", stats=stats)
        self.assertEqual(stats.exact, 1)
        self.assertEqual(stats.by_name_unique, 0)

    def test_legacy_tuple_index_still_works(self):
        legacy = (self.idx.by_path, self.idx.by_name)
        res = resolve_texture(legacy, "hand", "HUDs/Alien/Hand.RIM")
        self.assertTrue(res)

    def test_empty_name_and_path(self):
        res = resolve_texture(self.idx, "", "")
        self.assertFalse(res)
        self.assertIsInstance(res, TextureResolution)


class TestBuildIndex(_TreeMixin, unittest.TestCase):
    """The index derives path and name keys from the tree on disk."""

    def test_missing_root_returns_empty_index(self):
        idx = build_texture_index("/definitely/not/here")
        self.assertEqual(len(idx), 0)
        self.assertEqual(idx.n_files, 0)

    def test_keys_and_counts(self):
        self.assertEqual(self.idx.n_files, len(TREE))
        self.assertIn("graphics/common/lights.rim", self.idx.by_path)
        # The stripped variant is what RIF paths hit.
        self.assertIn("common/lights.rim", self.idx.by_path)
        self.assertEqual(self.idx.n_ambiguous_names, 1)   # lights

    def test_paths_point_at_existing_files(self):
        for full in self.idx.by_path.values():
            self.assertTrue(os.path.isfile(full), full)

    def test_cache_is_reused(self):
        self.assertIs(build_texture_index(self.root), self.idx)


class TestMaterialNaming(unittest.TestCase):
    """Material names come from the texture path and stay unique."""

    def test_name_from_path(self):
        self.assertEqual(
            material_name("Stat101", "graphics/common/lights.rim.png"),
            "Stat101_common_lights")
        self.assertEqual(
            material_name("Derelict",
                          "graphics/envrnmts/towers03/lights.rim.png"),
            "Derelict_envrnmts_towers03_lights")

    def test_different_paths_different_names(self):
        a = material_name("Stat101", "graphics/common/lights.rim.png")
        b = material_name("Stat101", "graphics/envrnmts/towers03/lights.rim.png")
        self.assertNotEqual(a, b)

    def test_same_path_same_name(self):
        a = material_name("Stat101", "graphics/common/lights.rim.png")
        b = material_name("Stat101", "graphics/common/lights.rim.png")
        self.assertEqual(a, b)

    def test_generic_dirs_are_dropped(self):
        self.assertNotIn("graphics", material_name("X", "graphics/a/b.png"))

    def test_only_generic_dirs_falls_back(self):
        name = material_name("X", "graphics/a.png", fallback="a")
        self.assertTrue(name.startswith("X_"))
        self.assertNotIn("graphics", name)

    def test_odd_characters_are_sanitised(self):
        name = material_name("L", "graphics/envrnmts/mission pack/07 128.rim.png")
        self.assertTrue(name.replace("_", "").isalnum(), name)
        self.assertNotIn(" ", name)

    def test_long_paths_are_bounded_and_unique(self):
        deep = "graphics/" + "/".join(f"dir{i:02d}" for i in range(12)) + "/t.png"
        name = material_name("Level", deep)
        self.assertLessEqual(len(name), 60)
        other = deep.replace("t.png", "u.png")
        self.assertNotEqual(name, material_name("Level", other))

    def test_disambiguate_is_deterministic(self):
        a = disambiguate_name("X_lights", "graphics/common/lights.rim.png")
        b = disambiguate_name("X_lights", "graphics/common/lights.rim.png")
        c = disambiguate_name("X_lights", "graphics/envrnmts/lights.rim.png")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_generic_dirs_constant_is_lowercase(self):
        self.assertEqual(GENERIC_DIRS, {d.lower() for d in GENERIC_DIRS})


if __name__ == "__main__":
    unittest.main()
