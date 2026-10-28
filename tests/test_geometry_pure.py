"""Tests for the bpy-free helper functions in geometry.py.

geometry.py imports bpy at module level, so this file can only be imported
inside Blender. The skipUnless guard lets the rest of the test suite run
standalone if it ever needs to.

5.5.2: fixed the flagged-path expectation for uv_index_from_poly - the
correct formula is `((poly & 0xF000) << 4) | (poly >> 16)`, which shifts
the hi nibble from bits 12-15 up to bits 16-19, so a small nibble produces
a *large* index, not `nibble<<4 | hiword`.
"""

from __future__ import annotations

import unittest

try:
    import bpy  # noqa: F401
    _HAS_BPY = True
except ImportError:
    _HAS_BPY = False


@unittest.skipUnless(_HAS_BPY, "geometry.py requires bpy (run inside Blender)")
class TestPolyBitmapIndex(unittest.TestCase):
    def setUp(self):
        from avp_rif_importer.geometry import bitmap_index_from_poly
        self.f = bitmap_index_from_poly

    def test_zero(self):
        self.assertEqual(self.f(0), 0)

    def test_low_12_bits(self):
        # 0xFFF is the bitmap mask.
        self.assertEqual(self.f(0xFFF), 0xFFF)

    def test_high_bits_ignored(self):
        # Upper bits (uv flags + uv index + colour) do not affect bitmap idx.
        self.assertEqual(self.f(0xFFFF0000), 0)


@unittest.skipUnless(_HAS_BPY, "geometry.py requires bpy (run inside Blender)")
class TestPolyUvIndex(unittest.TestCase):
    def setUp(self):
        from avp_rif_importer.geometry import uv_index_from_poly
        self.f = uv_index_from_poly

    def test_zero(self):
        self.assertEqual(self.f(0), 0)

    def test_simple_high_bits(self):
        # No 0xF000 flag -> plain >> 16.
        # 0x00010000 -> 1
        self.assertEqual(self.f(0x00010000), 1)
        # 0x00050000 -> 5
        self.assertEqual(self.f(0x00050000), 5)

    def test_flagged_path_recombines_low_and_high(self):
        # With the 0x0000F000 nibble set, decoder expands it:
        #   idx = ((poly & 0xF000) << 4) | (poly >> 16)
        # 0xF000 << 4 = 0xF0000, so hi nibble N ends up at bits 16..19.
        # For poly = 0x00035000: hi nibble = 0x5, poly>>16 = 0x3
        #   idx = (0x5 << 16) | 0x3 = 0x50003 = 327683.
        poly = 0x00035000
        self.assertEqual(self.f(poly), 0x50003)

    def test_flagged_path_zero_hi_nibble_does_not_trigger_flag(self):
        # 0x0000F000 mask is zero when the hi nibble is zero, so we fall
        # through to the simple >> 16 branch even if other bits are set.
        self.assertEqual(self.f(0x00030000), 0x0003)

    def test_unsigned_not_negative(self):
        # Bit 31 must NOT make the index negative.
        result = self.f(0x80000000)
        self.assertGreaterEqual(result, 0)


@unittest.skipUnless(_HAS_BPY, "geometry.py requires bpy (run inside Blender)")
class TestIdentityQuat(unittest.TestCase):
    def setUp(self):
        from avp_rif_importer.geometry import is_identity_quat
        self.f = is_identity_quat

    def test_identity(self):
        self.assertTrue(self.f((0.0, 0.0, 0.0, 1.0)))

    def test_negative_identity(self):
        # q and -q are the same rotation -> treated as identity.
        self.assertTrue(self.f((0.0, 0.0, 0.0, -1.0)))

    def test_ninety_degree_rotation(self):
        import math
        s = math.sin(math.pi / 4)
        c = math.cos(math.pi / 4)
        self.assertFalse(self.f((0.0, 0.0, s, c)))

    def test_tiny_drift_still_identity(self):
        self.assertTrue(self.f((1e-9, 1e-9, 1e-9, 1.0)))


@unittest.skipUnless(_HAS_BPY, "geometry.py requires bpy (run inside Blender)")
class TestUvToBlender(unittest.TestCase):
    """UVs are texel indices; the engine uses texel centres and v from top."""

    def setUp(self):
        from avp_rif_importer.geometry import uv_to_blender
        self.f = uv_to_blender

    def test_texel_centre_and_flip(self):
        # Engine: tu = (u + 0.5) / w, tv = (v + 0.5) / h (from the top);
        # Blender's v points up, so it is 1 - tv.
        u, v = self.f(0.0, 0.0, 128.0, 128.0)
        self.assertAlmostEqual(u, 0.5 / 128.0)
        self.assertAlmostEqual(v, 1.0 - 0.5 / 128.0)

    def test_last_texel(self):
        u, v = self.f(127.0, 127.0, 128.0, 128.0)
        self.assertAlmostEqual(u, 127.5 / 128.0)
        self.assertAlmostEqual(v, 1.0 - 127.5 / 128.0)

    def test_bottom_of_texture_maps_to_low_v(self):
        # A texel at the top of the image (v=0) must end up at high Blender v.
        _, v_top = self.f(0.0, 0.0, 128.0, 128.0)
        _, v_bottom = self.f(0.0, 127.0, 128.0, 128.0)
        self.assertGreater(v_top, v_bottom)

    def test_scale_uses_the_given_texture_size(self):
        u128, _ = self.f(64.0, 0.0, 128.0, 128.0)
        u256, _ = self.f(64.0, 0.0, 256.0, 256.0)
        self.assertAlmostEqual(u128, 64.5 / 128.0)
        self.assertAlmostEqual(u256, 64.5 / 256.0)

    def test_tiling_uvs_are_kept(self):
        # UVs may exceed the texture (walls tile); no clamping.
        u, v = self.f(300.0, 260.0, 128.0, 128.0)
        self.assertGreater(u, 2.0)
        self.assertLess(v, 0.0)

    def test_zero_size_falls_back(self):
        u, v = self.f(0.0, 0.0, 0.0, 0.0)
        self.assertGreaterEqual(u, 0.0)
        self.assertGreaterEqual(v, 0.0)


@unittest.skipUnless(_HAS_BPY, "geometry.py requires bpy (run inside Blender)")
class TestPngDimensions(unittest.TestCase):
    """PNG size is read from the IHDR so UV scale follows the texture."""

    def test_missing_file_returns_none(self):
        from avp_rif_importer.geometry import png_dimensions
        self.assertIsNone(png_dimensions(""))
        self.assertIsNone(png_dimensions("/definitely/not/here.png"))

    def test_real_png(self):
        import os
        import struct
        import tempfile
        from avp_rif_importer.geometry import png_dimensions

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tex.png")
            with open(path, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n")
                f.write(struct.pack(">I", 13) + b"IHDR")
                f.write(struct.pack(">II", 64, 32))
                f.write(b"\x08\x02\x00\x00\x00")
            self.assertEqual(png_dimensions(path), (64, 32))

    def test_not_a_png_returns_none(self):
        import os
        import tempfile
        from avp_rif_importer.geometry import png_dimensions

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tex.png")
            with open(path, "wb") as f:
                f.write(b"not a png at all")
            self.assertIsNone(png_dimensions(path))


if __name__ == "__main__":
    unittest.main()