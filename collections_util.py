# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Collection creation and Blender-version-aware Auto Smooth."""

from __future__ import annotations

import bpy

from .config import COLLECTION_GROUPS, OPTIONAL_COLLECTION_GROUPS
from .utils import log


def create_import_collections(base: str, enable_optional: set[str] | None = None):
    """Create the top-level collection plus one subcollection per group."""
    # enable_optional is a set of COLLECTION_GROUPS keys that should be
    # created despite being listed in OPTIONAL_COLLECTION_GROUPS. Any
    # optional group not present in the set is skipped entirely, so
    # debug features do not leave empty clutter in the Outliner when
    # disabled.
    enabled = enable_optional or set()
    main = bpy.data.collections.new(base)
    bpy.context.scene.collection.children.link(main)
    result = {"__main__": main}
    for key, suffix in COLLECTION_GROUPS.items():
        # Skip optional groups that the caller did not explicitly enable.
        if key in OPTIONAL_COLLECTION_GROUPS and key not in enabled:
            continue
        sub = bpy.data.collections.new(f"{base}_{suffix}")
        main.children.link(sub)
        result[key] = sub
    return result


def apply_auto_smooth(collection, angle_rad: float) -> int:
    """Apply smooth shading + Auto Smooth at angle_rad; returns mesh count."""
    meshes = [o for o in collection.objects if o.type == 'MESH' and o.data]
    if not meshes:
        return 0

    # Blender <4.1 exposes mesh.use_auto_smooth; 4.1+ uses a modifier op.
    if hasattr(meshes[0].data, "use_auto_smooth"):
        for obj in meshes:
            mesh = obj.data
            for p in mesh.polygons:
                p.use_smooth = True
            mesh.use_auto_smooth = True
            mesh.auto_smooth_angle = angle_rad
        return len(meshes)

    # 4.1+ path: select all meshes, run the operator, restore selection.
    prev_selected = list(bpy.context.selected_objects)
    prev_active = bpy.context.view_layer.objects.active
    try:
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        for obj in meshes:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.shade_auto_smooth(angle=angle_rad)
    except RuntimeError as e:
        log.warning(f"  Auto Smooth failed: {e}")
        return 0
    finally:
        try:
            bpy.ops.object.select_all(action='DESELECT')
        except RuntimeError:
            pass
        for o in prev_selected:
            try:
                o.select_set(True)
            except (ReferenceError, RuntimeError):
                pass
        try:
            bpy.context.view_layer.objects.active = prev_active
        except (ReferenceError, RuntimeError):
            pass
    return len(meshes)