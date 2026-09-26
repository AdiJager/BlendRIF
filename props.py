# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Custom property keys and enum values for objects created by the importer.

Centralised so typos become import errors instead of silent property name
drift. Every custom property uses an `avp_` prefix to avoid colliding with
other add-ons that share the same flat ID-property namespace.
"""

from __future__ import annotations

# --- Property keys ----------------------------------------------------
AVP_PROP_TYPE              = "avp_type"
AVP_PROP_NAME              = "avp_name"
AVP_PROP_TEXT              = "avp_text"
AVP_PROP_BBOX_MIN          = "avp_bbox_min"
AVP_PROP_BBOX_MAX          = "avp_bbox_max"
AVP_PROP_HIERARCHY_INDEX   = "avp_hierarchy_index"
AVP_PROP_ID                = "avp_id"
AVP_PROP_GENER_TYPE        = "avp_gener_type"
AVP_PROP_FLAGS             = "avp_flags"
AVP_PROP_SND_NAME          = "avp_snd_name"
AVP_PROP_WAV_NAME          = "avp_wav_name"
AVP_PROP_INNER_RANGE       = "avp_inner_range"
AVP_PROP_OUTER_RANGE       = "avp_outer_range"
AVP_PROP_MAX_VOLUME        = "avp_max_volume"
AVP_PROP_PITCH             = "avp_pitch"
AVP_PROP_PROBABILITY       = "avp_probability"
AVP_PROP_MODULE_ID         = "avp_module_id"
AVP_PROP_NUM_POINTS        = "avp_num_points"
AVP_PROP_BRIGHTNESS        = "avp_brightness"
AVP_PROP_SPREAD            = "avp_spread"
AVP_PROP_RANGE             = "avp_range"

# --- External-RIF debug marker props ----------------------------------
AVP_PROP_EXT_NAME          = "avp_ext_name"
AVP_PROP_SHAPE_IDX         = "avp_shape_idx"
AVP_PROP_PLACEHOLDER_VERTS = "avp_placeholder_verts"

# --- avp_type values --------------------------------------------------
AVP_TYPE_DUMMY         = "dummy"
AVP_TYPE_HIERARCHY     = "hierarchy"
AVP_TYPE_GENERATOR     = "generator"
AVP_TYPE_SOUND         = "sound"
AVP_TYPE_PLAYER_START  = "player_start"
AVP_TYPE_CAMERA_ORIGIN = "camera_origin"
AVP_TYPE_PATH          = "path"
AVP_TYPE_LIGHT         = "light"
AVP_TYPE_MISSING_EXT   = "missing_ext_rif"