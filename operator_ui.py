"""draw() body for the import operator - five named sections.

Split out of operator.py so the UI layout can be edited without
touching the pipeline. The function receives the operator instance and
its layout; it only touches EnumProperty/BoolProperty/FloatProperty
names that already live on the operator class.

Section "Materials" contains extract_ffl, which is enabled together
with import_materials (extracted textures are useless without
materials). The bridge enforces the same rule at runtime as a
safety net for scripted invocations.
"""

from __future__ import annotations


def draw_operator_panels(op, layout):
    """Draw the operator UI as five named sections."""
    layout.prop(op, "preset")
    layout.separator()

    box = layout.box()
    box.label(text="Geometry", icon='MESH_DATA')
    box.prop(op, "scale")
    box.prop(op, "pivot_mode")
    box.prop(op, "ext_rif_strategy")
    box.prop(op, "orphan_mode")
    box.prop(op, "auto_smooth")
    row = box.row()
    row.enabled = op.auto_smooth
    row.prop(op, "auto_smooth_angle")

    box = layout.box()
    box.label(text="Materials", icon='MATERIAL')
    box.prop(op, "import_materials")
    row = box.row(); row.enabled = op.import_materials
    row.prop(op, "bitmap_mode")
    row = box.row(); row.enabled = op.import_materials
    row.prop(op, "apply_matchimg")
    row = box.row(); row.enabled = op.import_materials
    row.prop(op, "use_clrlookp")
    row = box.row(); row.enabled = op.import_materials
    row.prop(op, "cull_backfaces")
    row = box.row(); row.enabled = op.import_materials
    row.prop(op, "extract_ffl")

    box = layout.box()
    box.label(text="Data", icon='OUTLINER_OB_EMPTY')
    box.prop(op, "import_dummy")
    box.prop(op, "import_placed_hier")
    box.prop(op, "import_avpgener")
    box.prop(op, "import_soundob2")
    box.prop(op, "import_avpstart")
    box.prop(op, "import_camorign")
    box.prop(op, "import_paths")
    box.prop(op, "import_lights")

    box = layout.box()
    box.label(text="Animation", icon='ANIM')
    box.prop(op, "animate_objects")
    row = box.row(); row.enabled = op.animate_objects
    row.prop(op, "animation_fps")
    box.prop(op, "animate_characters")
    row = box.row(); row.enabled = op.animate_characters
    row.prop(op, "char_anim_limit")

    box = layout.box()
    box.label(text="Debug", icon='CONSOLE')
    box.prop(op, "diagnostics_mode")
    box.prop(op, "mark_missing_ext")