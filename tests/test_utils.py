"""Tests for utils.apply_axis, utils.sanitize, utils._safe_name."""

from __future__ import annotations

import unittest

from avp_rif_importer.utils import apply_axis, sanitize, _safe_name


class TestApplyAxis(unittest.TestCase):
    def test_basic_mapping(self):
        # AvP (Y-up) -> Blender (Z-up), handedness preserved by negating Y.
        self.assertEqual(apply_axis(1, 2, 3), (1, 3, -2))

    def test_origin(self):
        self.assertEqual(apply_axis(0, 0, 0), (0, 0, 0))

    def test_x_axis_unchanged(self):
        self.assertEqual(apply_axis(1, 0, 0), (1, 0, 0))

    def test_handedness_is_not_mirrored(self):
        # If handedness were flipped, (0, 1, 0) would map to (0, 0, 1),
        # not (0, 0, -1).
        self.assertEqual(apply_axis(0, 1, 0), (0, 0, -1))


class TestSanitize(unittest.TestCase):
    def test_removes_special_chars(self):
        self.assertEqual(sanitize("hello world!"), "helloworld")

    def test_keeps_alnum_dash_underscore(self):
        self.assertEqual(sanitize("a-b_c123"), "a-b_c123")

    def test_empty_and_none(self):
        self.assertEqual(sanitize(""), "")
        self.assertEqual(sanitize(None), "")

    def test_truncates_to_max(self):
        self.assertEqual(len(sanitize("a" * 200)), 40)
        self.assertEqual(len(sanitize("a" * 200, max_len=10)), 10)


class TestSafeName(unittest.TestCase):
    def test_with_name(self):
        self.assertEqual(_safe_name("base", "dummy", "MyName", 0),
                         "base_dummy_MyName")

    def test_without_name_uses_index(self):
        self.assertEqual(_safe_name("base", "dummy", "", 7),
                         "base_dummy_007")

    def test_name_with_invalid_chars(self):
        self.assertEqual(_safe_name("base", "dummy", "My Name!", 0),
                         "base_dummy_MyName")


if __name__ == "__main__":
    unittest.main()