"""T-t2: double-import safety for Stage 1 tagging (B-dup).

Regression guard for the fix in stages_geometry.run_stage_geometry:
after process_shape creates a new mesh, avp_tag must be written to
the object that THIS import placed into the geometry collection, not
to whatever bpy.data.objects.get(name) happens to return. On a
second import the fresh object gets a '.001' suffix in Blender's
global object table, so a global-name lookup reaches back to the
first import's mesh - Stage 1c (which matches by avp_tag) then only
ever sees the stale copies.

These tests exercise the fix's lookup mechanism (collection-scoped
objects.get) directly, without invoking the operator, so they stay
fast and are not affected by the dependency graph.
"""

from __future__ import annotations

import unittest

import bpy


# --------------------------------------------------------------- helpers

def _apply_tag_like_stage1(geometry_collection, name, tag):
    """Mirror of the double-import-safe tagging block in stages_geometry."""
    obj = geometry_collection.objects.get(name)
    if obj is not None and tag:
        obj["avp_tag"] = tag
    return obj


class _BlenderFixture(unittest.TestCase):
    """Base class: creates and tears down a private collection + objects."""

    def setUp(self):
        self._collections = []
        self._objects = []
        self._meshes = []

    def tearDown(self):
        # Objects first (do_unlink unlinks from every collection), then
        # meshes, then the collections themselves.
        for obj in self._objects:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
        for mesh in self._meshes:
            try:
                bpy.data.meshes.remove(mesh)
            except (ReferenceError, RuntimeError):
                pass
        for col in self._collections:
            try:
                bpy.data.collections.remove(col)
            except (ReferenceError, RuntimeError):
                pass

    def _new_collection(self, name):
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
        self._collections.append(col)
        return col

    def _new_object(self, name, collection):
        mesh = bpy.data.meshes.new(name)
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        self._meshes.append(mesh)
        self._objects.append(obj)
        return obj


# -------------------------------------------------------------- lookups

class TestCollectionLookupOnSecondImport(_BlenderFixture):
    def test_suffixed_object_is_distinct(self):
        col = self._new_collection("t2_col_a")
        first = self._new_object("crate", col)
        # Second creation with the same base name: Blender auto-renames.
        second = self._new_object("crate", col)
        self.assertNotEqual(first.name, second.name)
        self.assertTrue(second.name.startswith("crate."))
        self.assertIsNot(first, second)

    def test_collection_lookup_returns_new_object(self):
        col = self._new_collection("t2_col_b")
        first = self._new_object("crate", col)
        second = self._new_object("crate", col)
        self.assertIs(col.objects.get(first.name), first)
        self.assertIs(col.objects.get(second.name), second)

    def test_bpy_data_lookup_hits_first_import(self):
        # Documents why stages_geometry uses the collection lookup:
        # bpy.data.objects.get("crate") returns the FIRST import's mesh
        # after a second import, because Blender renamed the new object.
        col = self._new_collection("t2_col_c")
        first = self._new_object("crate", col)
        second = self._new_object("crate", col)
        self.assertIs(bpy.data.objects.get("crate"), first)
        self.assertIsNot(bpy.data.objects.get("crate"), second)


# ------------------------------------------------------------- tagging

class TestTagLandsOnFreshObject(_BlenderFixture):
    def test_second_import_gets_its_own_tag(self):
        col = self._new_collection("t2_col_d")

        # --- First import: process_shape would return "crate". ---
        first = self._new_object("crate", col)
        _apply_tag_like_stage1(col, first.name, "crate_A")
        self.assertEqual(first.get("avp_tag"), "crate_A")

        # --- Second import: process_shape would return "crate.001". ---
        second = self._new_object("crate", col)
        self.assertNotEqual(first.name, second.name)
        _apply_tag_like_stage1(col, second.name, "crate_A")

        # Both objects carry the tag and stay distinct - the fix does
        # not clobber the first import's mesh with a second-import tag.
        self.assertIsNot(first, second)
        self.assertEqual(first.get("avp_tag"), "crate_A")
        self.assertEqual(second.get("avp_tag"), "crate_A")

    def test_stage1c_style_iteration_finds_both(self):
        # Simulates Stage 1c's by_tag construction on a scene that has
        # been through two imports into the same collection.
        col = self._new_collection("t2_col_e")
        a = self._new_object("mesh", col)
        b = self._new_object("mesh", col)
        _apply_tag_like_stage1(col, a.name, "bone_1")
        _apply_tag_like_stage1(col, b.name, "bone_2")

        by_tag = {}
        for obj in col.objects:
            tag = obj.get("avp_tag")
            if tag:
                by_tag[str(tag).lower()] = obj
        self.assertIn("bone_1", by_tag)
        self.assertIn("bone_2", by_tag)
        self.assertIs(by_tag["bone_1"], a)
        self.assertIs(by_tag["bone_2"], b)


if __name__ == "__main__":
    unittest.main()