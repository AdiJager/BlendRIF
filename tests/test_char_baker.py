"""T-t1: tests for char_baker pure-math helpers and the cross-version
Action FCurve iterator.

Covers:
  * _sequence_frame_numbers  - uniform frame distribution across
                               sequence_time at a given fps, including
                               the canonical-time override used to keep
                               parent and child on the same Blender grid
  * _frame_local_matrix      - root vs child axis conversion; the fix
                               from 6.3.0 (child passes through
                               unconverted, root gets R_axis)
  * _rest_world_matrix       - OBJHEAD1 (pos, quat) -> Blender world 4x4
  * _iter_action_fcurves     - 3.x-5.x Action access (layered + legacy)

bake_character_nla itself is an integration surface (needs a live
scene, meshes, collections, NLA API). The pure helpers below are
covered so the compositing math stays locked in independently of the
operator. The NLA strip setup (track.new / strips.new) is a thin,
well-documented Blender-API shim and is not exercised here.

AnimFrame / AnimSequence are duck-typed with SimpleNamespace: the
helpers under test only read attributes (frames, sequence_time,
transform, orientation, flags), so coupling to the parser's dataclass
constructor would add noise without adding coverage. If the real
dataclasses gain meaningful behaviour these tests need to change; for
now they pin the *math*, not the container.
"""

from __future__ import annotations

import types
import unittest

import bpy
from mathutils import Matrix

from avp_rif_importer.char_baker import (
    _frame_local_matrix,
    _iter_action_fcurves,
    _rest_world_matrix,
    _sequence_frame_numbers,
)


# --------------------------------------------------------------- helpers

def _frame(orientation=(0.0, 0.0, 0.0, 1.0),
           transform=(0.0, 0.0, 0.0),
           at_frame_no=-1,
           flags=0):
    """Duck-typed AnimFrame: helpers read .orientation/.transform."""
    return types.SimpleNamespace(
        orientation=orientation,
        transform=transform,
        at_frame_no=at_frame_no,
        flags=flags,
    )


def _seq(frames, sequence_number=0, sub_sequence_number=0,
         sequence_time=1000):
    """Duck-typed AnimSequence: _sequence_frame_numbers reads
    .frames and .sequence_time only."""
    return types.SimpleNamespace(
        frames=frames,
        sequence_number=sequence_number,
        sub_sequence_number=sub_sequence_number,
        sequence_time=sequence_time,
    )


def _assert_vec(test, actual, expected, places=6):
    test.assertAlmostEqual(actual[0], expected[0], places=places)
    test.assertAlmostEqual(actual[1], expected[1], places=places)
    test.assertAlmostEqual(actual[2], expected[2], places=places)


def _assert_mat3(test, actual, expected, places=6):
    for i in range(3):
        for j in range(3):
            test.assertAlmostEqual(actual[i][j], expected[i][j],
                                   places=places)


# ------------------------------------------------------ _sequence_frame_numbers

class TestSequenceFrameNumbers(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(_sequence_frame_numbers(_seq([]), 30), [])

    def test_single_frame_returns_one(self):
        self.assertEqual(
            _sequence_frame_numbers(_seq([_frame()]), 30), [1])

    def test_zero_sequence_time_sequential(self):
        # seq_ms <= 0 falls back to 1, 2, ..., n irrespective of fps.
        seq = _seq([_frame() for _ in range(5)], sequence_time=0)
        self.assertEqual(_sequence_frame_numbers(seq, 60),
                         [1, 2, 3, 4, 5])
        self.assertEqual(_sequence_frame_numbers(seq, 24),
                         [1, 2, 3, 4, 5])

    def test_negative_sequence_time_sequential(self):
        seq = _seq([_frame(), _frame()], sequence_time=-5)
        self.assertEqual(_sequence_frame_numbers(seq, 30), [1, 2])

    def test_uniform_spread_60fps_1000ms_3frames(self):
        # total = round(1000/1000 * 60) = 60; [1, 1+30, 1+60].
        seq = _seq([_frame() for _ in range(3)], sequence_time=1000)
        self.assertEqual(_sequence_frame_numbers(seq, 60), [1, 31, 61])

    def test_uniform_spread_30fps_500ms_2frames(self):
        # total = round(500/1000 * 30) = 15; [1, 16].
        seq = _seq([_frame(), _frame()], sequence_time=500)
        self.assertEqual(_sequence_frame_numbers(seq, 30), [1, 16])

    def test_uniform_spread_60fps_1000ms_4frames(self):
        # total = 60; [1, 21, 41, 61].
        seq = _seq([_frame() for _ in range(4)], sequence_time=1000)
        self.assertEqual(_sequence_frame_numbers(seq, 60),
                         [1, 21, 41, 61])

    def test_total_frames_never_below_one(self):
        # Tiny sequence_time with many frames: total_frames floors at
        # 1 (max(1, round(...))), so the last frame lands on 1+1=2.
        # The intermediate frames collapse onto frame 1 because
        # round(i * 1 / (n-1)) is 0 for i in {0, 1} under banker's
        # rounding (round(0.5) == 0 in Python 3).
        seq = _seq([_frame() for _ in range(3)], sequence_time=1)
        self.assertEqual(_sequence_frame_numbers(seq, 30), [1, 1, 2])

    def test_canonical_time_overrides_sequence_time(self):
        # Shipped RIFs disagree per bone; caller passes the max so
        # parent and child share the same grid. Here 500 ms at 30 fps
        # wins over the sequence's own 999 ms.
        seq = _seq([_frame(), _frame()], sequence_time=999)
        self.assertEqual(
            _sequence_frame_numbers(seq, 30, canonical_time_ms=500),
            [1, 16])

    def test_canonical_zero_falls_back_to_sequential(self):
        seq = _seq([_frame(), _frame(), _frame()], sequence_time=1000)
        self.assertEqual(
            _sequence_frame_numbers(seq, 60, canonical_time_ms=0),
            [1, 2, 3])

    def test_canonical_none_uses_sequence_time(self):
        seq = _seq([_frame(), _frame()], sequence_time=500)
        self.assertEqual(
            _sequence_frame_numbers(seq, 30, canonical_time_ms=None),
            [1, 16])

    def test_at_frame_no_is_ignored(self):
        # at_frame_no is an AvP tick (or -1 sentinel) and must not
        # influence the output; frames are spread from sequence_time.
        seq = _seq([
            _frame(at_frame_no=100),
            _frame(at_frame_no=200),
            _frame(at_frame_no=300),
        ], sequence_time=1000)
        self.assertEqual(_sequence_frame_numbers(seq, 60), [1, 31, 61])


# --------------------------------------------------------- _frame_local_matrix

class TestFrameLocalMatrixRootVsChild(unittest.TestCase):
    """Root vs child axis conversion - the 6.3.0 convention."""

    def test_root_translation_axis_converted(self):
        # apply_axis(1,2,3) = (1, 3, -2).
        M = _frame_local_matrix(_frame(transform=(1.0, 2.0, 3.0)),
                                scale=1.0, is_root=True)
        _assert_vec(self, M.translation, (1.0, 3.0, -2.0))

    def test_child_translation_passes_through(self):
        M = _frame_local_matrix(_frame(transform=(1.0, 2.0, 3.0)),
                                scale=1.0, is_root=False)
        _assert_vec(self, M.translation, (1.0, 2.0, 3.0))

    def test_scale_multiplies_root_translation(self):
        M = _frame_local_matrix(_frame(transform=(1.0, 2.0, 3.0)),
                                scale=10.0, is_root=True)
        _assert_vec(self, M.translation, (10.0, 30.0, -20.0))

    def test_scale_multiplies_child_translation(self):
        M = _frame_local_matrix(_frame(transform=(1.0, 2.0, 3.0)),
                                scale=10.0, is_root=False)
        _assert_vec(self, M.translation, (10.0, 20.0, 30.0))

    def test_zero_translation_is_zero_for_both(self):
        M_root = _frame_local_matrix(_frame(), scale=5.0, is_root=True)
        M_child = _frame_local_matrix(_frame(), scale=5.0, is_root=False)
        _assert_vec(self, M_root.translation, (0.0, 0.0, 0.0))
        _assert_vec(self, M_child.translation, (0.0, 0.0, 0.0))

    def test_child_identity_quat_is_identity_rotation(self):
        # Child quaternions pass through unconverted; identity stays
        # identity. This is what lets the parent's world rotation do
        # the axis conversion for the whole subtree.
        M = _frame_local_matrix(_frame(orientation=(0.0, 0.0, 0.0, 1.0)),
                                scale=1.0, is_root=False)
        _assert_mat3(self, M.to_3x3(), (
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        ))

    def test_root_identity_quat_becomes_axis_rotation(self):
        # Root gets R_x(-90 deg). Matrix:
        #   [1, 0, 0]
        #   [0, 0, 1]
        #   [0,-1, 0]
        M = _frame_local_matrix(_frame(orientation=(0.0, 0.0, 0.0, 1.0)),
                                scale=1.0, is_root=True)
        _assert_mat3(self, M.to_3x3(), (
            (1.0,  0.0, 0.0),
            (0.0,  0.0, 1.0),
            (0.0, -1.0, 0.0),
        ))

    def test_root_and_child_differ_on_mixed_transform(self):
        # Pick a transform where the axis map changes a component:
        # apply_axis(0,1,0) = (0, 0, -1).
        f = _frame(transform=(0.0, 1.0, 0.0),
                   orientation=(0.0, 0.0, 0.0, 1.0))
        root = _frame_local_matrix(f, scale=1.0, is_root=True)
        child = _frame_local_matrix(f, scale=1.0, is_root=False)
        _assert_vec(self, root.translation, (0.0, 0.0, -1.0))
        _assert_vec(self, child.translation, (0.0, 1.0, 0.0))
        # And rotations differ too (root carries R_axis).
        self.assertNotAlmostEqual(root.to_3x3()[1][2],
                                  child.to_3x3()[1][2], places=6)


# ------------------------------------------------------------ _rest_world_matrix

class TestRestWorldMatrix(unittest.TestCase):
    """OBJHEAD1 (pos, quat) -> world 4x4. Always axis-converted."""

    def test_translation_axis_converted(self):
        M = _rest_world_matrix((1, 2, 3), (0.0, 0.0, 0.0, 1.0),
                               scale=1.0)
        _assert_vec(self, M.translation, (1.0, 3.0, -2.0))

    def test_scale_multiplies_translation(self):
        M = _rest_world_matrix((1, 2, 3), (0.0, 0.0, 0.0, 1.0),
                               scale=2.0)
        _assert_vec(self, M.translation, (2.0, 6.0, -4.0))

    def test_negative_translation(self):
        # apply_axis(-1,-2,-3) = (-1, -3, 2).
        M = _rest_world_matrix((-1, -2, -3), (0.0, 0.0, 0.0, 1.0),
                               scale=1.0)
        _assert_vec(self, M.translation, (-1.0, -3.0, 2.0))

    def test_identity_quat_gives_axis_rotation(self):
        M = _rest_world_matrix((0, 0, 0), (0.0, 0.0, 0.0, 1.0),
                               scale=1.0)
        _assert_mat3(self, M.to_3x3(), (
            (1.0,  0.0, 0.0),
            (0.0,  0.0, 1.0),
            (0.0, -1.0, 0.0),
        ))

    def test_quat_xyzw_ordering(self):
        # OBJHEAD1 stores quaternions as (x, y, z, w). A 180-deg Y
        # rotation is xyzw = (0, 1, 0, 0). After R_axis premultiplication
        # the composite must NOT be the identity - if the parser fed
        # wxyz instead, this would come out identity for an unrelated
        # reason. Cheap sanity on the field order.
        M = _rest_world_matrix((0, 0, 0), (0.0, 1.0, 0.0, 0.0),
                               scale=1.0)
        rot = M.to_3x3()
        is_identity = (abs(rot[0][0] - 1.0) < 1e-9
                       and abs(rot[1][1] - 1.0) < 1e-9
                       and abs(rot[2][2] - 1.0) < 1e-9)
        self.assertFalse(is_identity)

    def test_zero_translation_zero_scale(self):
        M = _rest_world_matrix((0, 0, 0), (0.0, 0.0, 0.0, 1.0),
                               scale=0.0)
        _assert_vec(self, M.translation, (0.0, 0.0, 0.0))


# --------------------------------------------------------- _iter_action_fcurves

class _ActionFixture(unittest.TestCase):
    """Creates and tears down a private object + action pair."""

    def setUp(self):
        self._objects = []
        self._meshes = []
        self._actions = []

    def tearDown(self):
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
        for action in self._actions:
            try:
                bpy.data.actions.remove(action)
            except (ReferenceError, RuntimeError):
                pass

    def _new_obj_with_action(self, name):
        mesh = bpy.data.meshes.new(name)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        self._meshes.append(mesh)
        self._objects.append(obj)
        obj.animation_data_create()
        action = bpy.data.actions.new(f"{name}_action")
        self._actions.append(action)
        obj.animation_data.action = action
        return obj, action

    def _new_bare_action(self, name):
        action = bpy.data.actions.new(name)
        self._actions.append(action)
        return action


class TestIterActionFcurves(_ActionFixture):
    def test_empty_action_yields_nothing(self):
        action = self._new_bare_action("t1_empty_action")
        self.assertEqual(list(_iter_action_fcurves(action)), [])

    def test_keyframed_location_yields_fcurves(self):
        obj, action = self._new_obj_with_action("t1_loc")
        obj.location = (1.0, 2.0, 3.0)
        obj.keyframe_insert("location", frame=1)
        fcurves = list(_iter_action_fcurves(action))
        self.assertGreater(len(fcurves), 0)

    def test_keyframed_fcurves_report_location_data_path(self):
        obj, action = self._new_obj_with_action("t1_path")
        obj.keyframe_insert("location", frame=1)
        paths = {fc.data_path for fc in _iter_action_fcurves(action)}
        self.assertIn("location", paths)

    def test_quaternion_keyframes_are_visible(self):
        obj, action = self._new_obj_with_action("t1_quat")
        obj.rotation_mode = 'QUATERNION'
        obj.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        obj.keyframe_insert("rotation_quaternion", frame=1)
        paths = {fc.data_path for fc in _iter_action_fcurves(action)}
        self.assertIn("rotation_quaternion", paths)

    def test_location_and_quaternion_yield_multiple_fcurves(self):
        obj, action = self._new_obj_with_action("t1_multi")
        obj.rotation_mode = 'QUATERNION'
        obj.location = (1.0, 2.0, 3.0)
        obj.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        obj.keyframe_insert("location", frame=1)
        obj.keyframe_insert("rotation_quaternion", frame=1)
        fcurves = list(_iter_action_fcurves(action))
        # location is 3 components, quaternion is 4 -> at least 7.
        self.assertGreaterEqual(len(fcurves), 7)

    def test_iterator_is_reusable(self):
        # Calling twice must yield the same count (no destructive
        # state in the helper on either Blender path).
        obj, action = self._new_obj_with_action("t1_reuse")
        obj.keyframe_insert("location", frame=1)
        first = list(_iter_action_fcurves(action))
        second = list(_iter_action_fcurves(action))
        self.assertEqual(len(first), len(second))
        self.assertGreater(len(first), 0)


if __name__ == "__main__":
    unittest.main()