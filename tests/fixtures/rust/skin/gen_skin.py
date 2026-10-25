#!/usr/bin/env python3
"""Write the mds-skin fixtures: skin.pmx, skin.pmd and the case file cases.txt.

Python standard library only, with no clock, no randomness and no libm call,
as tools/fixtures/gen_fixtures.py. Rotations come from integer quaternions, so
every matrix entry is a rational number rounded once to float32.

    python3 -I tests/fixtures/rust/skin/gen_skin.py --write
    python3 -I tests/fixtures/rust/skin/gen_skin.py --check

skin_dup.pmx and skin_uv4.pmx reuse its vertices and bones: bone morphs that
name a bone twice, and four additional UVs with a morph of every UV kind.

skin.pmx (PMX 2.0, two additional UVs) has BDEF1, BDEF2, BDEF4 and SDEF
vertices, bone references of -1, three materials whose edge sizes decide the
material of shared vertices, and vertex, UV, additional UV, material
(multiply, add, all materials), bone and group morphs. Two vertices become
QDEF in cases.txt, after loading: the C++ loader reads PMX 2.0 only, which
has no QDEF. skin.pmd has a base morph, two vertex morphs, a weight over 127,
a bone index of 0xFFFF and vertices without an edge.

cases.txt runs several poses and morph weight sets on chain8.pmx, chain8.pmd,
morph4.pmx (tests/fixtures/rust) and the two models here. Its format is in
tools/skin_check/skin_check.cpp.
"""
import argparse
import struct
import sys
from fractions import Fraction as F
from pathlib import Path

HERE = Path(__file__).resolve().parent


def u8(*v):
    return bytes(v)


def u16(*v):
    return struct.pack("<%dH" % len(v), *v)


def i16(*v):
    return struct.pack("<%dh" % len(v), *v)


def u32(*v):
    return struct.pack("<%dI" % len(v), *v)


def i32(*v):
    return struct.pack("<%di" % len(v), *v)


def f32(*v):
    return struct.pack("<%df" % len(v), *[float(x) for x in v])


def utf16(text):
    raw = text.encode("utf-16-le")
    return u32(len(raw)) + raw


def sjis(text, size):
    raw = text.encode("cp932")
    assert len(raw) < size, text
    return raw + b"\0" * (size - len(raw))


def bits(x):
    return "%08x" % struct.unpack("<I", struct.pack("<f", float(x)))[0]


# ---------------------------------------------------------------------------
# skin.pmx. Index sizes are all 1 byte (bone and morph indices signed).
# ---------------------------------------------------------------------------

PMX_BONES = [  # (name, parent, position)
    ("root", -1, (0.0, 0.0, 0.0)),
    ("center", 0, (0.0, 1.0, 0.0)),
    ("arm", 1, (1.0, 1.0, 0.0)),
    ("tip", 2, (2.0, 1.0, 0.0)),
]

# (position, normal, uv, (add uv 1, add uv 2), weight, edge scale). Weight is
# (kind, bones, weights[, (C, R0, R1)]).
PMX_VERTICES = [
    ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0),
     ((0.1, 0.2, 0.3, 0.4), (0.5, 0.6, 0.7, 0.8)), (0, (0,), ()), 1.0),
    ((2.03, 1.11, 0.47), (0.6, 0.8, 0.0), (0.93, 0.07),
     ((1.0, 0.0, 0.25, 0.5), (0.0, 1.0, 0.0, 1.0)), (0, (3,), ()), 0.53),
    ((0.47, 1.03, 0.01), (0.0, 0.6, -0.8), (0.27, 0.51),
     ((0.0, 0.0, 0.0, 0.0), (0.13, 0.27, 0.39, 0.51)), (1, (1, 2), (0.73,)), 2.17),
    ((1.53, 0.97, -0.23), (-0.8, 0.0, 0.6), (0.49, 0.53),
     ((0.3, 0.3, 0.3, 0.3), (0.9, 0.8, 0.7, 0.6)), (1, (2, -1), (0.41,)), 1.0),
    ((1.01, 0.53, 0.27), (0.48, 0.6, 0.64), (0.77, 0.23),
     ((0.2, 0.4, 0.6, 0.8), (0.1, 0.3, 0.5, 0.7)),
     (2, (0, 1, 2, 3), (0.11, 0.23, 0.29, 0.37)), 1.0),
    ((1.77, 1.23, 0.03), (0.0, 0.0, -1.0), (0.13, 0.87),
     ((0.0, 1.0, 0.0, 1.0), (1.0, 0.0, 1.0, 0.0)),
     (2, (3, 2, 1, 0), (0.43, 0.31, 0.17, 0.09)), 1.51),
    ((1.03, 1.07, 0.51), (0.0, 1.0, 0.0), (0.37, 0.63),
     ((0.5, 0.5, 0.5, 0.5), (0.25, 0.25, 0.25, 0.25)),
     (3, (1, 2), (0.61,), ((1.01, 0.99, 0.03), (0.47, 1.03, -0.07), (1.53, 0.97, 0.11))), 1.0),
    ((1.53, 1.27, 0.13), (0.6, 0.0, 0.8), (0.63, 0.37),
     ((0.7, 0.1, 0.2, 0.9), (0.4, 0.4, 0.6, 0.6)),
     (3, (2, 3), (0.27,), ((1.51, 1.21, 0.09), (1.23, 1.03, 0.01), (2.07, 1.49, 0.27))), 1.0),
    ((1.27, 0.73, 0.01), (0.0, -1.0, 0.0), (0.87, 0.13),
     ((0.0, 0.5, 1.0, 0.5), (0.5, 0.0, 0.5, 1.0)),
     (3, (2, -1), (0.53,), ((0.99, 1.01, 0.03), (1.03, 0.47, 0.0), (0.97, 1.53, 0.0))), 0.0),
    ((0.23, 0.51, -0.49), (0.8, -0.6, 0.0), (0.0, 1.0),
     ((0.6, 0.6, 0.6, 0.6), (0.2, 0.2, 0.2, 0.2)), (1, (0, 1), (0.47,)), 1.0),
    ((1.03, 1.49, 0.07), (0.0, 0.8, 0.6), (1.0, 1.0),
     ((0.9, 0.9, 0.1, 0.1), (0.3, 0.6, 0.9, 0.3)),
     (2, (0, 1, 2, 3), (0.21, 0.27, 0.23, 0.29)), 1.0),
    ((1.97, 1.27, -0.51), (-0.6, 0.0, -0.8), (0.51, 0.03),
     ((0.4, 0.3, 0.2, 0.1), (0.8, 0.7, 0.6, 0.5)), (1, (0, 3), (1.0,)), 1.0),
]
QDEF_VERTICES = (9, 10)

PMX_MATERIALS = [  # (name, diffuse, specular, power, ambient, edge color, edge size, faces)
    ("mat0", (0.8, 0.6, 0.4, 1.0), (0.5, 0.5, 0.5), 5.0, (0.3, 0.2, 0.1),
     (0.2, 0.4, 0.6, 0.5), 1.0, (0, 1, 2, 2, 3, 4)),
    ("mat1", (0.1, 0.2, 0.3, 0.75), (0.9, 0.1, 0.1), 20.0, (0.05, 0.1, 0.15),
     (1.0, 0.0, 0.5, 1.0), 0.5, (4, 5, 6, 6, 7, 8)),
    ("mat2", (1.0, 1.0, 1.0, 0.5), (0.0, 0.0, 0.0), 1.0, (0.5, 0.5, 0.5),
     (0.0, 0.0, 0.0, 0.25), 0.5, (8, 9, 10, 10, 11, 0)),
]


def material_values(diffuse=(1, 1, 1, 1), specular=(1, 1, 1), power=1,
                    ambient=(1, 1, 1), edge=(1, 1, 1, 1), edge_size=1,
                    texture=(1, 1, 1, 1), sphere=(1, 1, 1, 1), toon=(1, 1, 1, 1)):
    return (*diffuse, *specular, power, *ambient, *edge, edge_size, *texture,
            *sphere, *toon)


ZERO28 = (0.0,) * 28

PMX_MORPHS = [  # (name, panel, kind, offsets)
    ("v0", 4, 1, [(0, (0.13, 0.0, 0.07)), (2, (0.01, 0.27, 0.0)), (6, (0.0, 0.03, 0.37)),
                  (9, (0.11, 0.13, 0.17))]),
    ("v1", 4, 1, [(2, (0.07, -0.03, 0.0)), (7, (0.0, -0.13, 0.01)), (10, (-0.19, 0.0, 0.23))]),
    ("uv", 4, 3, [(1, (0.13, 0.27, 0.0, 0.0)), (2, (-0.11, 0.03, 0.0, 0.0))]),
    ("adduv1", 4, 4, [(3, (0.1, 0.2, 0.3, 0.4)), (4, (-0.23, 0.01, 0.27, 0.03))]),
    ("adduv2", 4, 5, [(5, (0.51, -0.47, 0.53, -0.49))]),
    ("uv2", 4, 3, [(1, (0.07, 0.03, 0.0, 0.0)), (11, (0.01, -0.23, 0.0, 0.0))]),
    ("matmul", 4, 8, [(1, 0, material_values(
        diffuse=(0.5, 0.25, 2.0, 0.5), specular=(0.0, 0.5, 1.5), power=0.5,
        ambient=(2.0, 2.0, 0.5), edge=(0.5, 1.0, 1.5, 0.5), edge_size=3.0,
        texture=(0.5, 0.5, 0.5, 0.5)))]),
    ("matadd", 4, 8, [(-1, 1, (0.1, 0.05, -0.1, -0.25, 0.2, 0.2, 0.2, 10.0,
                               0.05, 0.05, 0.05, 0.3, -0.1, 0.1, 0.25, 0.5,
                               0.1, 0.1, 0.1, 0.1) + (0.0,) * 8),
                      (2, 1, ZERO28[:11] + (0.5, 0.5, 0.5, 0.5, 0.25) + (0.0,) * 12)]),
    ("bone", 4, 2, [(2, (0.125, 0.0, 0.0), (0.0, 0.0, 0.38268343, 0.9238795))]),
    ("bone2", 4, 2, [(2, (0.0, 0.25, 0.0), (0.0, 0.0, 0.0, 1.0)),
                     (3, (0.0, 0.0, -0.125), (0.0, 0.6, 0.0, -0.8))]),
    ("group", 4, 0, [(0, 0.3), (1, -0.7), (2, 1.3), (3, -0.9), (6, 0.45), (7, 1.7),
                     (8, 2.1), (9, 0.55), (10, 1.0)]),
]


def pmx_index(value):
    return struct.pack("<b", value)


def build_pmx(name, morphs, add_uv_count=2, vertices=None):
    vertices = PMX_VERTICES if vertices is None else vertices
    o = bytearray(b"PMX " + f32(2.0))
    o += u8(8, 0, add_uv_count, 1, 1, 1, 1, 1, 1)
    o += utf16(name) + utf16(name) + utf16("mds-skin fixture") + utf16("mds-skin fixture")
    o += u32(len(vertices))
    for pos, normal, uv, add_uv, weight, edge in vertices:
        o += f32(*pos, *normal, *uv)
        for extra in add_uv:
            o += f32(*extra)
        kind, bones, weights = weight[:3]
        o += u8(kind) + b"".join(pmx_index(b) for b in bones) + f32(*weights)
        if kind == 3:
            for point in weight[3]:
                o += f32(*point)
        o += f32(edge)
    faces = [i for m in PMX_MATERIALS for i in m[7]]
    o += u32(len(faces)) + u8(*faces)
    o += u32(0)  # textures
    o += u32(len(PMX_MATERIALS))
    for name, diffuse, specular, power, ambient, edge, edge_size, mfaces in PMX_MATERIALS:
        o += utf16(name) + utf16(name)
        o += f32(*diffuse, *specular, power, *ambient)
        o += u8(0x10) + f32(*edge, edge_size)
        o += pmx_index(-1) + pmx_index(-1) + u8(0, 1, 0)  # no textures, shared toon 0
        o += utf16("") + u32(len(mfaces))
    o += u32(len(PMX_BONES))
    for i, (name, parent, pos) in enumerate(PMX_BONES):
        o += utf16(name) + utf16(name) + f32(*pos) + pmx_index(parent) + i32(0)
        flags = 0x0002 | 0x0008 | 0x0010 | (0x0004 if i == 1 else 0)
        o += u16(flags) + f32(1.0, 0.0, 0.0)
    o += u32(len(morphs))
    for name, panel, kind, offsets in morphs:
        o += utf16(name) + utf16(name) + u8(panel, kind) + i32(len(offsets))
        for entry in offsets:
            if kind == 0:
                o += pmx_index(entry[0]) + f32(entry[1])
            elif kind == 1:
                o += u8(entry[0]) + f32(*entry[1])
            elif kind == 2:
                o += pmx_index(entry[0]) + f32(*entry[1], *entry[2])
            elif kind == 8:
                o += pmx_index(entry[0]) + u8(entry[1]) + f32(*entry[2])
            else:
                o += u8(entry[0]) + f32(*entry[1])
    frames = [("Root", 1, [(0, 0)]),
              ("表情", 1, [(1, k) for k in range(len(morphs))]),
              ("body", 0, [(0, 1), (0, 2), (0, 3)])]
    o += u32(len(frames))
    for name, special, entries in frames:
        o += utf16(name) + utf16(name) + u8(special) + i32(len(entries))
        for kind, index in entries:
            o += u8(kind) + pmx_index(index)
    o += u32(0)  # rigid bodies
    return bytes(o)


def build_skin_pmx():
    return build_pmx("skin", PMX_MORPHS)


# skin_dup.pmx: the bone morph table of the C++ loader skips a bone only when
# an earlier morph moves it, so a bone named twice in one morph gets a second,
# unused record. Same bones, vertices and materials as skin.pmx.
DUP_MORPHS = [
    ("dupself", 4, 2, [(2, (0.125, 0.0, 0.0), (0.0, 0.0, 0.38268343, 0.9238795)),
                       (2, (0.0, 0.25, 0.0), (0.0, 0.6, 0.0, 0.8)),
                       (3, (0.0, 0.0, -0.125), (0.0, 0.0, 0.0, 1.0))]),
    ("dupother", 4, 2, [(3, (0.25, 0.0, 0.0), (0.38268343, 0.0, 0.0, 0.9238795)),
                        (1, (0.0, 0.5, 0.0), (0.0, 0.0, 0.0, 1.0))]),
    ("dupboth", 4, 2, [(1, (0.0, 0.0, 0.5), (0.0, 0.0, 0.6, 0.8)),
                       (1, (0.5, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)),
                       (0, (0.0, 0.125, 0.0), (0.0, 0.38268343, 0.0, 0.9238795)),
                       (0, (0.0, 0.0, 0.25), (0.6, 0.0, 0.0, 0.8))]),
    ("group", 4, 0, [(0, 0.5), (2, -1.5)]),
]


def build_dup_pmx():
    return build_pmx("skin_dup", DUP_MORPHS)


# skin_uv4.pmx: four additional UVs and a morph of each UV kind 3..7 (kind 7 is
# additional UV 4), the last one named by a group morph and by two morphs on a
# shared vertex.
def four_uvs(vertex):
    pos, normal, uv, extra, weight, edge = vertex
    return (pos, normal, uv, extra + (extra[0][::-1], extra[1][::-1]), weight, edge)


UV4_VERTICES = [four_uvs(v) for v in PMX_VERTICES]
UV4_MORPHS = [
    ("uv", 4, 3, [(1, (0.13, 0.27, 0.0, 0.0))]),
    ("adduv1", 4, 4, [(3, (0.1, 0.2, 0.3, 0.4))]),
    ("adduv2", 4, 5, [(5, (0.51, -0.47, 0.53, -0.49))]),
    ("adduv3", 4, 6, [(2, (0.25, 0.5, -0.25, -0.5)), (7, (1.0, 0.0, 0.0, 1.0))]),
    ("adduv4", 4, 7, [(2, (0.125, -0.25, 0.5, 0.75)), (4, (-0.5, 0.0, 0.25, 0.0)),
                      (11, (0.03, 0.07, 0.11, 0.13))]),
    ("adduv4b", 4, 7, [(4, (0.25, 0.25, -0.125, 0.5)), (6, (0.0, -1.0, 0.0, 1.0))]),
    ("group", 4, 0, [(4, 0.5), (5, -0.75), (3, 1.25)]),
]


def build_uv4_pmx():
    return build_pmx("skin_uv4", UV4_MORPHS, 4, UV4_VERTICES)


# ---------------------------------------------------------------------------
# skin.pmd
# ---------------------------------------------------------------------------

PMD_BONES = [("root", -1, (0.0, 0.0, 0.0)), ("center", 0, (0.0, 1.0, 0.0)),
             ("arm", 1, (1.0, 1.0, 0.0))]
PMD_VERTICES = [  # (position, normal, uv, bones, weight, edge disabled)
    ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0), (0, 1), 100, 0),
    ((0.53, 1.07, 0.01), (0.6, 0.8, 0.0), (0.27, 0.51), (1, 2), 73, 0),
    ((1.01, 0.97, 0.53), (0.0, 0.6, -0.8), (0.49, 0.23), (2, 1), 37, 1),
    ((1.51, 1.23, 0.03), (-0.8, 0.0, 0.6), (0.77, 0.73), (2, 0xFFFF), 29, 0),
    ((0.27, 0.73, -0.23), (0.0, 0.0, -1.0), (0.99, 0.51), (0, 2), 200, 0),
    ((1.23, 0.51, 0.27), (0.48, 0.6, 0.64), (0.13, 0.97), (1, 1), 0, 1),
]
PMD_INDICES = (0, 1, 2, 2, 3, 4, 4, 5, 0)
# Morph 0 is the base: absolute positions of the morphed vertices (vertex 4's
# differs from the vertex record). The other morphs index the base list.
PMD_MORPHS = [
    ("base", 0, [(1, (0.53, 1.07, 0.01)), (2, (1.01, 0.97, 0.53)), (4, (0.31, 0.71, -0.19))]),
    ("m1", 3, [(0, (0.03, 0.27, -0.01)), (2, (0.13, 0.07, 0.0))]),
    ("m2", 3, [(1, (-0.23, 0.01, 0.13)), (0, (0.07, 0.0, 0.51))]),
]


def build_skin_pmd():
    o = bytearray(b"Pmd" + f32(1.0))
    o += sjis("skin", 20) + sjis("mds-skin fixture", 256)
    o += u32(len(PMD_VERTICES))
    for pos, normal, uv, bones, weight, no_edge in PMD_VERTICES:
        o += f32(*pos, *normal, *uv) + u16(*bones) + u8(weight, no_edge)
    o += u32(len(PMD_INDICES)) + u16(*PMD_INDICES)
    o += u32(1)
    o += f32(0.8, 0.6, 0.4, 1.0, 5.0, 0.5, 0.5, 0.5, 0.25, 0.25, 0.25)
    o += u8(0, 1) + u32(len(PMD_INDICES)) + sjis("", 20)
    o += u16(len(PMD_BONES))
    for i, (name, parent, pos) in enumerate(PMD_BONES):
        o += sjis(name, 20) + i16(parent) + u16(0) + u8(1 if i == 1 else 0) + u16(0) + f32(*pos)
    o += u16(0)  # IK chains
    o += u16(len(PMD_MORPHS))
    for name, panel, offsets in PMD_MORPHS:
        o += sjis(name, 20) + u32(len(offsets)) + u8(panel)
        for index, delta in offsets:
            o += u32(index) + f32(*delta)
    o += u8(0)  # facial display entries
    o += u8(0)  # bone groups
    o += u32(0)  # bone frames
    o += u8(0)  # no English section
    for i in range(10):
        o += sjis("toon%02d.bmp" % (i + 1), 100)
    o += u32(0) + u32(0)  # rigid bodies, joints
    return bytes(o)


# ---------------------------------------------------------------------------
# cases.txt
# ---------------------------------------------------------------------------


def rotation(q):
    """Row-vector (D3DX) rotation matrix of the integer quaternion q, exact."""
    x, y, z, w = map(F, q)
    n = x * x + y * y + z * z + w * w
    return [
        [1 - 2 * (y * y + z * z) / n, 2 * (x * y + z * w) / n, 2 * (x * z - y * w) / n],
        [2 * (x * y - z * w) / n, 1 - 2 * (x * x + z * z) / n, 2 * (y * z + x * w) / n],
        [2 * (x * z + y * w) / n, 2 * (y * z - x * w) / n, 1 - 2 * (x * x + y * y) / n],
    ]


def skin_matrix(bind, q=(0, 0, 0, 1), move=(0, 0, 0), scale=1):
    """T(-bind) * R * scale * T(bind + move): a bone turned about its bind position."""
    r = [[F(scale) * e for e in row] for row in rotation(q)]
    p = [F(c) for c in bind]
    last = [-(p[0] * r[0][c] + p[1] * r[1][c] + p[2] * r[2][c]) + p[c] + F(move[c])
            for c in range(3)]
    return [*r[0], 0, *r[1], 0, *r[2], 0, *last, 1]


def world(q=(0, 0, 0, 1), move=(0, 0, 0)):
    return skin_matrix((0, 0, 0), q, move)


CHAIN_BIND = [(0.0, float(i), 0.0) for i in range(8)]
MORPH4_BIND = [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
PMX_BIND = [b[2] for b in PMX_BONES]
PMD_BIND = [b[2] for b in PMD_BONES]


def case(name, camera=(0, 10, -45), fov=30, edge=1, shadow=0, world_m=None,
         morphs=(), bones=()):
    lines = ["case " + name]
    lines.append("world " + " ".join(bits(v) for v in (world_m or world())))
    lines.append("camera " + " ".join(bits(v) for v in (*camera, fov)))
    lines.append("edge " + bits(edge))
    lines.append("shadow %d" % shadow)
    for index, weight in morphs:
        lines.append("morph %d %s" % (index, bits(weight)))
    for index, matrix in bones:
        lines.append("bone %d %s" % (index, " ".join(bits(v) for v in matrix)))
    lines.append("end")
    return lines


NEG_ZERO = [-1.0, -0.0, -0.0, 0.0, -0.0, 1.0, -0.0, 0.0, -0.0, -0.0, -1.0, 0.0,
            0.0, -0.0, 0.0, 1.0]


def cases():
    out = ["# Written by gen_skin.py. Format: tools/skin_check/skin_check.cpp."]
    out.append("model chain8.pmx")
    out += case("rest")
    out += case("swing", camera=(3.1, 12.3, -30.7), fov=45, edge=0.53, shadow=1,
                world_m=world((0, 1, 0, 3), (1.03, 0, -2.07)),
                bones=[(i, skin_matrix(CHAIN_BIND[i], (1, 2, i, 7), (0.01, 0.27 * i, 0.03)))
                       for i in range(8)])
    out += case("scaled", camera=(-5.3, 2.1, 20.9), fov=21, edge=2.03,
                bones=[(i, skin_matrix(CHAIN_BIND[i], (0, i, 1, 5), scale=1 + i / 7))
                       for i in range(1, 8, 2)])
    out.append("model chain8.pmd")
    out += case("rest")
    out += case("swing", camera=(3.1, 12.3, -30.7), fov=45, edge=0.53,
                world_m=world((0, 1, 0, 3), (1.03, 0, -2.07)),
                bones=[(i, skin_matrix(CHAIN_BIND[i], (1, 2, i, 7), (0.01, 0.27 * i, 0.03)))
                       for i in range(8)])
    out.append("model morph4.pmx")
    out += case("rest")
    out += case("weights", fov=35, shadow=1,
                morphs=[(0, 1.0), (1, 0.53), (2, -0.27), (3, 0.87)],
                bones=[(1, skin_matrix(MORPH4_BIND[1], (2, 1, 0, 6), (0, 0, 0.51)))])
    out += case("over", camera=(0.3, 1.7, -10.1), edge=1.47,
                morphs=[(0, 2.03), (3, -1.07)],
                bones=[(0, skin_matrix(MORPH4_BIND[0], (0, 0, 1, 2), (0.53, 0, 0))),
                       (1, skin_matrix(MORPH4_BIND[1], (1, 1, 1, 1)))])
    out.append("model skin/skin.pmx")
    out.append("qdef " + " ".join(map(str, QDEF_VERTICES)))
    out += case("rest")
    out += case("direct", camera=(4.1, 3.3, -12.7), fov=40, edge=0.77, shadow=1,
                world_m=world((1, 0, 0, 4), (0, 0.51, 0)),
                morphs=[(0, 1.0), (1, 0.53), (2, 0.71), (3, 1.0), (4, -0.47), (5, 1.0),
                        (6, 0.53), (7, 1.0), (8, 1.0), (9, 0.73)],
                bones=[(1, skin_matrix(PMX_BIND[1], (0, 0, 1, 3), (0, 0.13, 0))),
                       (2, skin_matrix(PMX_BIND[2], (1, 2, 0, 4), (0.27, 0, 0.01))),
                       (3, skin_matrix(PMX_BIND[3], (0, 1, 1, 1), (0, 0, -0.53)))])
    out += case("group", camera=(-2.3, 6.1, -20.3), fov=25, edge=1.27,
                morphs=[(10, 0.73), (6, 0.29)],
                bones=[(0, skin_matrix(PMX_BIND[0], (0, 1, 0, 8))),
                       (2, skin_matrix(PMX_BIND[2], (3, 0, 1, 2), scale=1.27)),
                       (3, skin_matrix(PMX_BIND[3], (1, 1, 0, -2), (0.51, 0.47, 0)))])
    out += case("mixed", camera=(1.1, 1.3, -5.7), fov=60, shadow=1,
                morphs=[(10, -0.51), (7, 0.47), (0, 0.27), (8, -1.0)],
                bones=[(1, skin_matrix(PMX_BIND[1], (2, 0, 0, 5))),
                       (2, skin_matrix(PMX_BIND[2], (0, 0, 1, 1)))])
    out += case("negzero", bones=[(i, NEG_ZERO) for i in range(4)])
    out.append("model skin/skin.pmd")
    out += case("rest")
    out += case("pose", camera=(2.3, 4.1, -15.3), fov=40, edge=1.53,
                world_m=world((0, 0, 1, 6), (0, -1.07, 0)),
                morphs=[(0, 1.0), (1, 1.0), (2, 0.53)],
                bones=[(1, skin_matrix(PMD_BIND[1], (1, 0, 0, 3), (0, 0.27, 0))),
                       (2, skin_matrix(PMD_BIND[2], (0, 1, 2, 4)))])
    out += case("weights", fov=20,
                morphs=[(1, -0.47), (2, 2.03)],
                bones=[(0, skin_matrix(PMD_BIND[0], (0, 0, 1, 1), (1.01, 0, 0))),
                       (2, skin_matrix(PMD_BIND[2], (1, 1, 0, 3), scale=0.77))])
    out += case("negzero", bones=[(i, NEG_ZERO) for i in range(3)])
    out.append("model skin/skin_dup.pmx")
    out += case("rest")
    out += case("self", morphs=[(0, 0.73)])
    out += case("across", morphs=[(0, 1.0), (1, 0.53), (2, -0.47)],
                bones=[(1, skin_matrix(PMX_BIND[1], (0, 0, 1, 3), (0, 0.13, 0)))])
    out += case("group", morphs=[(3, 0.87), (1, 0.29)])
    out += case("all", morphs=[(0, 1.0), (1, 1.0), (2, 1.0), (3, 1.0)])
    out.append("model skin/skin_uv4.pmx")
    out += case("rest")
    out += case("uv4", morphs=[(4, 0.73)])
    out += case("shared", camera=(1.1, 1.3, -5.7), fov=60, shadow=1,
                morphs=[(0, 0.3), (1, 0.5), (2, 0.7), (3, 0.9), (4, 1.0), (5, -0.53)],
                bones=[(1, skin_matrix(PMX_BIND[1], (2, 0, 0, 5)))])
    out += case("group", morphs=[(6, 0.71), (5, 0.37)])
    return ("\n".join(out) + "\n").encode()


def generate():
    return {"skin.pmx": build_skin_pmx(), "skin.pmd": build_skin_pmd(),
            "skin_dup.pmx": build_dup_pmx(), "skin_uv4.pmx": build_uv4_pmx(),
            "cases.txt": cases()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate the files")
    mode.add_argument("--check", action="store_true",
                      help="compare regenerated bytes with the files")
    args = ap.parse_args(argv)
    files = generate()
    if args.write:
        for name, data in files.items():
            (HERE / name).write_bytes(data)
        print("skin fixtures: wrote %d files" % len(files))
        return 0
    drift = [n for n, d in files.items()
             if not (HERE / n).is_file() or (HERE / n).read_bytes() != d]
    for name in drift:
        print("skin fixtures: DRIFT %s" % name, file=sys.stderr)
    if drift:
        return 1
    print("skin fixtures: %d files match" % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
