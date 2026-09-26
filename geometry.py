# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 AdiJager

"""Geometry extraction and mesh construction.

Turns the raw SHPRAWVT / SHPPOLYS / SHPUVCRD payloads of a ShapeGroup
into a Blender mesh with materials, UVs and optional pivot centering.
The bit layout of poly_colour is non-obvious - see bitmap_index_from_poly
and uv_index_from_poly for the two decoders and their gotchas.
"""

from __future__ import annotations

import struct
import time

import bpy
from mathutils import Matrix

from .chunks import ShapeGroup
from .config import (
    POLY_SIZE, POLY_BITMAP_MASK, POLY_UV_HI_MASK, POLY_COLOR_MASK,
    CLRLOOKP_MAX,
)
from .utils import log
from .materials import get_material, find_tex, apply_matchimg_index


# Precompiled struct parsers - 20-30% faster than unpack_from per call.
_STRUCT_VERT = struct.Struct("<iii")
_STRUCT_POLY = struct.Struct("<iiIIiiii")
_STRUCT_UV_F = struct.Struct("<ff")
_STRUCT_UV_I = struct.Struct("<hh")
_STRUCT_I    = struct.Struct("<i")


def extract_vertices(data: bytes):
    """Parse a SHPRAWVT payload into a list of (x, y, z) tuples."""
    n = len(data) // _STRUCT_VERT.size
    return list(_STRUCT_VERT.iter_unpack(data[:n * _STRUCT_VERT.size]))


def extract_polygons(data: bytes):
    """Parse a SHPPOLYS payload into a list of polygon dictionaries."""
    out = []
    n = len(data) // POLY_SIZE
    unpack = _STRUCT_POLY.unpack_from
    for i in range(n):
        base = i * POLY_SIZE
        engine_type, normal_index, poly_flags, poly_colour, v0, v1, v2, v3 = \
            unpack(data, base)
        verts = []
        for v in (v0, v1, v2, v3):
            if v < 0:
                break
            verts.append(v)
        out.append({
            "num_verts": len(verts), "verts": verts,
            "engine_type": engine_type, "normal_index": normal_index,
            "poly_flags": poly_flags, "poly_colour": poly_colour,
            "poly_idx": i,
        })
    return out


def extract_uvs(data: bytes, int16_mode: bool = False):
    """Parse a SHPUVCRD payload into a list of per-poly UV lists."""
    out = []
    pos = 4
    unpack_i = _STRUCT_I.unpack_from
    unpack_uv = (_STRUCT_UV_I if int16_mode else _STRUCT_UV_F).unpack_from
    while pos + 4 <= len(data):
        nv = unpack_i(data, pos)[0]
        pos += 4
        if nv < 1 or nv > 4:
            break
        uvs = []
        for _ in range(nv):
            if pos + 8 > len(data):
                return out
            a, b = unpack_uv(data, pos)
            if int16_mode:
                uvs.append((a / 256.0, b / 256.0))
            else:
                uvs.append((a, b))
            pos += 8
        out.append(uvs)
    return out


def bitmap_index_from_poly(poly_colour: int) -> int:
    """Extract the bitmap table index from the packed poly_colour field."""
    return poly_colour & POLY_BITMAP_MASK


def uv_index_from_poly(poly_colour: int) -> int:
    """Extract the UV record index from the packed poly_colour field."""
    # Do not "simplify": poly_colour MUST be unsigned and the flagged
    # path shifts the hi nibble up by 4 bits, giving large indices by
    # design.
    if poly_colour & POLY_UV_HI_MASK:
        return ((poly_colour & POLY_UV_HI_MASK) << 4) | (poly_colour >> 16)
    return poly_colour >> 16


def quat_to_mat(qx, qy, qz, qw):
    """Convert a quaternion (x, y, z, w) to a 3x3 rotation matrix."""
    xx, yy, zz = qx*qx, qy*qy, qz*qz
    xy, xz, yz = qx*qy, qx*qz, qy*qz
    wx, wy, wz = qw*qx, qw*qy, qw*qz
    return Matrix(((1-2*(yy+zz), 2*(xy-wz), 2*(xz+wy)),
                   (2*(xy+wz), 1-2*(xx+zz), 2*(yz-wx)),
                   (2*(xz-wy), 2*(yz+wx), 1-2*(xx+yy))))


def is_identity_quat(q, eps: float = 1e-6) -> bool:
    """True if q represents the identity rotation (also accepts -identity)."""
    qx, qy, qz, qw = q
    return (abs(qx) < eps and abs(qy) < eps and abs(qz) < eps
            and abs(abs(qw) - 1.0) < eps)


def build_mesh(shape: ShapeGroup, base, name, scale, bitmaps, tex_index,
               bm_mode, uv_scale, mat_cache,
               transform=None, do_center=False, clrlookp_table=None,
               matchimg_index=None, uv_int16_mode=False,
               level_hint: str = "",
               mat_timing: list | None = None,
               import_materials: bool = True,
               cull_backfaces: bool = True):
    """Build a Blender mesh from a ShapeGroup; returns (mesh, mats, loc) or None."""
    if mat_timing is not None:
        mat_timing[0] = 0.0

    if shape.raw_verts is None or shape.polys is None:
        return None
    verts = extract_vertices(shape.raw_verts)
    polys = extract_polygons(shape.polys)
    if not verts or not polys:
        return None
    nv = len(verts)

    uvs = []
    if shape.uvcrds is not None:
        uvs = extract_uvs(shape.uvcrds, int16_mode=uv_int16_mode)

    new_verts = [transform(v) for v in verts] if transform else \
                [(float(v[0]), float(v[1]), float(v[2])) for v in verts]

    faces, fmat, fuv = [], [], []
    mat_lookup, mat_names, mat_objs = {}, [], []

    for poly in polys:
        if poly["num_verts"] < 3:
            continue
        v = poly["verts"]
        if not all(0 <= x < nv for x in v):
            continue

        poly_colour = poly["poly_colour"]
        bmp_idx = bitmap_index_from_poly(poly_colour)
        uv_idx = uv_index_from_poly(poly_colour)

        slot = 0
        if import_materials:
            entry = bitmaps.get(bmp_idx) if bitmaps else None
            tex_base = entry.name if entry is not None else None
            tex_raw = entry.raw_name if entry is not None else ""
            if tex_base:
                tex_base = apply_matchimg_index(tex_base, matchimg_index)

            png = find_tex(tex_index, tex_base, tex_raw, level_hint) \
                if tex_base else None

            # Untextured polygons get a CLRLOOKP debug tint, if available.
            debug_color = None
            if not tex_base and clrlookp_table:
                color_idx = poly_colour & POLY_COLOR_MASK
                if color_idx < len(clrlookp_table):
                    ci = clrlookp_table[color_idx]
                    debug_color = ((ci & 0x1F) / CLRLOOKP_MAX,
                                   ((ci >> 5) & 0x1F) / CLRLOOKP_MAX,
                                   ((ci >> 10) & 0x1F) / CLRLOOKP_MAX, 1.0)

            mat_name = (f"{base}_{tex_base}" if tex_base
                        else f"{base}_unknown_{bmp_idx}")
            if mat_name not in mat_lookup:
                if mat_timing is not None:
                    _t_mat = time.perf_counter()
                if debug_color:
                    m = get_material(mat_name, None, mat_cache,
                                     color=debug_color,
                                     cull_backfaces=cull_backfaces)
                else:
                    m = get_material(mat_name, png, mat_cache,
                                     raw_name=tex_raw, level_hint=level_hint,
                                     cull_backfaces=cull_backfaces)
                if mat_timing is not None:
                    mat_timing[0] += time.perf_counter() - _t_mat
                mat_lookup[mat_name] = len(mat_names)
                mat_names.append(m.name)
                mat_objs.append(m)
            slot = mat_lookup[mat_name]

        puv = uvs[uv_idx] if 0 <= uv_idx < len(uvs) else []

        # Triangles stay as one face; quads become two triangles.
        if poly["num_verts"] == 3:
            faces.append((v[0], v[1], v[2]))
            fmat.append(slot)
            fuv.append(puv[:3] if len(puv) >= 3 else [])
        elif poly["num_verts"] == 4:
            faces.append((v[0], v[1], v[2]))
            fmat.append(slot)
            fuv.append([puv[0], puv[1], puv[2]] if len(puv) >= 4 else
                       (puv[:3] if len(puv) >= 3 else []))
            faces.append((v[0], v[2], v[3]))
            fmat.append(slot)
            fuv.append([puv[0], puv[2], puv[3]] if len(puv) >= 4 else
                       (puv[:3] if len(puv) >= 3 else []))

    if not faces:
        return None
    mesh = bpy.data.meshes.new(name)
    try:
        mesh.from_pydata(new_verts, [], faces)
        mesh.update()
    except (ValueError, RuntimeError) as e:
        log.error(f"    from_pydata FAILED: {e}")
        bpy.data.meshes.remove(mesh)
        return None

    if import_materials:
        for m in mat_objs:
            mesh.materials.append(m)
        for p, s in zip(mesh.polygons, fmat):
            if s < len(mesh.materials):
                p.material_index = s

    if mesh.polygons:
        uv_layer = mesh.uv_layers.new(name="UVMap")
        flat_uvs = []
        ext = flat_uvs.extend
        for puv in fuv:
            if len(puv) == 3:
                u0, v0 = puv[0]
                u1, v1 = puv[1]
                u2, v2 = puv[2]
                ext((u0 * uv_scale, v0 * uv_scale,
                     u1 * uv_scale, v1 * uv_scale,
                     u2 * uv_scale, v2 * uv_scale))
            else:
                ext((0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        uv_layer.data.foreach_set("uv", flat_uvs)

    # Optional pivot centering: move the geometry's center to the object origin.
    obj_loc = (0.0, 0.0, 0.0)
    if do_center and mesh.vertices:
        xs = [v.co.x for v in mesh.vertices]
        ys = [v.co.y for v in mesh.vertices]
        zs = [v.co.z for v in mesh.vertices]
        cx = (min(xs) + max(xs)) / 2.0
        cy = (min(ys) + max(ys)) / 2.0
        cz = (min(zs) + max(zs)) / 2.0
        for v in mesh.vertices:
            v.co.x -= cx
            v.co.y -= cy
            v.co.z -= cz
        mesh.update()
        obj_loc = (cx, cy, cz)

    return mesh, mat_names, obj_loc