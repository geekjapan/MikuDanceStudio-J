#!/usr/bin/env python3
"""Write the deterministic MMD fixture files under tests/fixtures/rust (RM-1).

Python standard library only. Every file is built from the tables below, with
no clock, no randomness and no libm call, so every platform writes the same
bytes.

    python3 -I tools/fixtures/gen_fixtures.py --write [--dir DIR]
    python3 -I tools/fixtures/gen_fixtures.py --check [--dir DIR]

--check regenerates in memory and compares bytes with DIR. It prints
"fixtures: 8 files match" and exits 0, or names each drifted file and exits 1.

Encodings: names are Shift-JIS (cp932) in PMD, VMD, VPD and PMM, and UTF-16LE
in PMX (encoding byte 0). Layouts follow the portable readers on origin/next
(model_reader, vmd_format, vpd_format, pmm_scene_document) and what the MMD
port writes (src/io/pmm_save.cpp, vmd_save.cpp, vpd_file.cpp).
"""
import argparse
import struct
import sys
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "rust"

# ---------------------------------------------------------------------------
# Spec tables. SPEC drives the bytes; test_gen_fixtures.py checks the output
# against its own literal copies of the counts.
# ---------------------------------------------------------------------------

# 8 bones in a chain: (Shift-JIS name, English name, movable). Bone i has
# parent i-1 and sits at (0, i, 0).
CHAIN = [
    ("全ての親", "Root", True),
    ("センター", "Center", True),
    ("上半身", "Upper", False),
    ("首", "Neck", False),
    ("頭", "Head", False),
    ("髪1", "Hair1", False),
    ("髪2", "Hair2", False),
    ("髪3", "Hair3", False),
]
# The IK bone of chain8_ik.pmx: index 8, parent 0, target bone 7, links 6 and 5.
IK_BONE = ("髪ＩＫ", "HairIK", (0.0, 7.0, 1.0))
IK_TARGET = 7
IK_LINKS = (6, 5)

MORPHS = [  # morph4.pmx: (name, English name, panel, [(vertex, (dx, dy, dz))])
    ("まばたき", "Blink", 2, [(0, (0.0, -0.25, 0.0)), (1, (0.0, -0.25, 0.0))]),
    ("あ", "A", 3, [(2, (0.0, -0.5, 0.0)), (3, (0.0, -0.5, 0.0))]),
    ("い", "I", 3, [(2, (-0.25, 0.0, 0.0)), (3, (0.25, 0.0, 0.0))]),
    ("う", "U", 3, [(0, (0.125, 0.0, 0.0)), (3, (-0.125, 0.0, 0.0))]),
]

LAST_FRAME = 599


def key_frames(step):
    return list(range(0, LAST_FRAME, step)) + [LAST_FRAME]


# Bone key frames of the swing motion (frame 0 is the track head). Registered
# counts are 2, 7, 5, 6, 7, 9, 11, 21 for the chain and 3 for the IK bone.
# After the freed key below, bone 頭 holds 6 keys in swing600.pmm and in
# swing600.vmd, so the per-bone counts there are 2, 7, 5, 6, 6, 9, 11, 21, 3.
SWING_FRAMES = {
    "全ての親": key_frames(LAST_FRAME),
    "センター": key_frames(100),
    "上半身": key_frames(150),
    "首": key_frames(120),
    "頭": key_frames(100),
    "髪1": key_frames(75),
    "髪2": key_frames(60),
    "髪3": key_frames(30),
    "髪ＩＫ": [0, 300, LAST_FRAME],
}
# The key that is freed after registration: bone 頭, frame 300. Its pool record
# (index 34 of slot 0's bone pool, between 25 at frame 200 and 46 at frame 400)
# stays empty (frame 0), so the pool has a gap and the chain skips over it.
FREED = ("頭", 300)
PHYSICS_OFF = ("髪2", 120)  # this key carries physicsDisabled = 1
CURVED_BONE = "首"          # this bone's keys use a non-linear curve

MORPH_KEYS = {  # morph4 keys (frame, value); frame 0 is the head (value 0.0)
    "まばたき": [(100, 1.0), (110, 0.0), (400, 1.0), (410, 0.0)],
    "あ": [(50, 0.5), (150, 0.0), (300, 0.75), (450, 0.25)],
    "い": [(200, 1.0), (260, 0.0)],
    "う": [(30, 0.125), (500, 0.875)],
}

# IK / display track of slot 0 (frame, ik_enabled, outside-parent link of
# selector 2 as (model slot, bone)).
DISPLAY_KEYS = [(200, 0, (-1, 0)), (300, 1, (1, 1)), (450, 1, (1, 1))]

# The VMD carries all three camera keys. swing600.pmm keeps only the first:
# the mds_scene_cli re-save check (no --trace) adds 1 to that key's fov and
# expects the fov at frame 5 to be exactly settings fov + 1, on every re-save
# too. Any later camera key would interpolate the fov away from that value.
# camera3.pmm keeps all three keys, so it loads and traces (--trace) but fails
# that re-save check (exit 6). It is for camera interpolation coverage only.
CAMERA_KEYS = [  # (frame, distance, eye, rotation, fov)
    (0, -45.0, (0.0, 10.0, 0.0), (0.0, 0.0, 0.0), 30),
    (200, -30.0, (0.0, 8.0, 0.0), (0.25, 0.5, 0.0), 35),
    (400, -45.0, (0.0, 10.0, 0.0), (0.0, -0.5, 0.0), 30),
]
CAMERA_CURVE = (40, 20, 90, 110)  # x1, y1, x2, y2 of the sparse camera keys
LIGHT_KEYS = [  # (frame, color, direction)
    (0, (0.625, 0.625, 0.625), (-0.5, -1.0, 0.5)),
    (300, (0.75, 0.5, 0.25), (0.5, -1.0, -0.5)),
]
# camera3.pmm adds a third light key to the two of swing600.pmm.
LIGHT3_KEYS = LIGHT_KEYS + [(450, (0.5, 0.75, 1.0), (0.0, -1.0, 1.0))]
SHADOW_KEYS = [(0, 1, 8875.0), (300, 2, 5000.0)]

PMM_MODELS = [  # slot order of swing600.pmm
    "chain8_ik.pmx",
    "morph4.pmx",
    "chain8.pmx",
    "chain8.pmd",
]

FILE_NAMES = [
    "chain8.pmd",
    "chain8.pmx",
    "chain8_ik.pmx",
    "morph4.pmx",
    "swing600.vmd",
    "pose.vpd",
    "swing600.pmm",
    "camera3.pmm",
]

# ---------------------------------------------------------------------------
# Byte helpers
# ---------------------------------------------------------------------------


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


def sjis(text, size):
    """Shift-JIS text zero-padded to size bytes (at least one NUL stays)."""
    raw = text.encode("cp932")
    assert len(raw) < size, text
    return raw + b"\0" * (size - len(raw))


def sjis_str(text):
    """Length-prefixed Shift-JIS string as the PMM writes it."""
    raw = text.encode("cp932")
    assert len(raw) < 256
    return u8(len(raw)) + raw


def utf16(text):
    raw = text.encode("utf-16-le")
    return u32(len(raw)) + raw


# ---------------------------------------------------------------------------
# Model specs. One dict per model file; PMD, PMX and PMM all derive from it.
# ---------------------------------------------------------------------------


def strip_vertices(bone_count):
    """Two vertices per bone height: (x, y, z, bone) for a flat strip."""
    verts = []
    for i in range(bone_count):
        verts.append(((-0.5, float(i), 0.0), i))
        verts.append(((0.5, float(i), 0.0), i))
    return verts


def strip_indices(bone_count):
    out = []
    for i in range(bone_count - 1):
        a, b, c, d = 2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 3
        out += [a, b, c, b, d, c]
    return out


def chain_model(file, with_ik, pmx_sizes):
    bones = []
    for i, (jp, en, movable) in enumerate(CHAIN):
        bones.append(dict(jp=jp, en=en, parent=i - 1, pos=(0.0, float(i), 0.0),
                          movable=movable, ik=False))
    if with_ik:
        jp, en, pos = IK_BONE
        bones.append(dict(jp=jp, en=en, parent=0, pos=pos, movable=False,
                          ik=True))
    rigids = []
    for i, (jp, en, _) in enumerate(CHAIN):
        rigids.append(dict(
            jp=jp, bone=i, group=0 if i == 0 else 1,
            mask=0xFFFF if i == 0 else 0xFFFF & ~2,
            shape=0 if i == 0 else 2,
            size=(0.25, 0.0, 0.0) if i == 0 else (0.25, 0.5, 0.0),
            pos=(0.0, float(i), 0.0), rot=(0.0, 0.0, 0.0),
            mass=1.0, lin=0.5, ang=0.5, rest=0.0, fric=0.5,
            mode=0 if i < 5 else (1 if i < 7 else 2)))
    joints = []
    for i in range(len(CHAIN) - 1):
        joints.append(dict(
            jp="%s-%s" % (CHAIN[i][0], CHAIN[i + 1][0]), a=i, b=i + 1,
            pos=(0.0, i + 0.5, 0.0), rot=(0.0, 0.0, 0.0),
            pos_min=(0.0, 0.0, 0.0), pos_max=(0.0, 0.0, 0.0),
            rot_min=(-0.5, -0.5, -0.5), rot_max=(0.5, 0.5, 0.5),
            spring_pos=(0.0, 0.0, 0.0), spring_rot=(10.0, 10.0, 10.0)))
    n = len(CHAIN)
    return dict(
        file=file, name="chain8", name_en="chain8",
        comment="Synthetic fixture: 8 bone chain",
        bones=bones, morphs=[], rigids=rigids, joints=joints,
        verts=strip_vertices(n), indices=strip_indices(n),
        groups=[("ボディ", "Body", [1, 2, 3, 4]), ("髪", "Hair", [5, 6, 7])],
        texture="chain.png" if file.endswith(".pmx") else "",
        pmx_sizes=pmx_sizes)


def morph_model():
    bones = [
        dict(jp="センター", en="Center", parent=-1, pos=(0.0, 0.0, 0.0),
             movable=True, ik=False),
        dict(jp="上半身", en="Upper", parent=0, pos=(0.0, 1.0, 0.0),
             movable=False, ik=False),
    ]
    verts = [((-0.5, 0.0, 0.0), 0), ((0.5, 0.0, 0.0), 0),
             ((-0.5, 1.0, 0.0), 1), ((0.5, 1.0, 0.0), 1)]
    rigids = [dict(jp="センター", bone=0, group=0, mask=0xFFFF, shape=1,
                   size=(0.5, 0.5, 0.5), pos=(0.0, 0.5, 0.0),
                   rot=(0.0, 0.0, 0.0), mass=0.0, lin=0.0, ang=0.0, rest=0.0,
                   fric=0.5, mode=0)]
    return dict(
        file="morph4.pmx", name="morph4", name_en="morph4",
        comment="Synthetic fixture: 4 vertex morphs",
        bones=bones, morphs=MORPHS, rigids=rigids, joints=[],
        verts=verts, indices=[0, 1, 2, 1, 3, 2],
        groups=[("ボディ", "Body", [1])], texture="",
        pmx_sizes=dict(vertex=1, texture=1, material=1, bone=1, morph=1,
                       rigid=1, uv=1))


MODELS = {
    "chain8.pmd": chain_model("chain8.pmd", False, None),
    "chain8.pmx": chain_model("chain8.pmx", False,
                              dict(vertex=2, texture=1, material=1, bone=1,
                                   morph=1, rigid=1, uv=0)),
    "chain8_ik.pmx": chain_model("chain8_ik.pmx", True,
                                 dict(vertex=1, texture=1, material=1, bone=2,
                                      morph=1, rigid=2, uv=0)),
    "morph4.pmx": morph_model(),
}


def ik_sources(model):
    return [i for i, b in enumerate(model["bones"]) if b["ik"]]


def selector_sources(model):
    """Outside-parent selectors: slot 0 is the root, then Move and IK bones."""
    return [-1] + [i for i, b in enumerate(model["bones"])
                   if b["movable"] or b["ik"]]


# ---------------------------------------------------------------------------
# PMD
# ---------------------------------------------------------------------------


def build_pmd(m):
    o = bytearray(b"Pmd" + f32(1.0))
    o += sjis(m["name"], 20) + sjis(m["comment"], 256)
    o += u32(len(m["verts"]))
    for pos, bone in m["verts"]:
        o += f32(*pos, 0.0, 0.0, 1.0, pos[0] + 0.5, pos[1] / 8.0)
        o += u16(bone, bone) + u8(100, 0)
    o += u32(len(m["indices"])) + u16(*m["indices"])
    o += u32(1)  # one material over every face
    o += f32(0.75, 0.75, 0.75, 1.0, 5.0, 0.5, 0.5, 0.5, 0.25, 0.25, 0.25)
    o += u8(0, 1) + u32(len(m["indices"])) + sjis(m["texture"], 20)
    bones = m["bones"]
    o += u16(len(bones))
    for i, b in enumerate(bones):
        tail = i + 1 if i + 1 < len(bones) else 0
        o += sjis(b["jp"], 20) + i16(b["parent"]) + u16(tail)
        o += u8(1 if b["movable"] else 0) + u16(0) + f32(*b["pos"])
    o += u16(0)  # IK chains
    o += u16(0)  # morphs
    o += u8(0)   # face display targets
    o += u8(len(m["groups"]))
    for jp, _, _ in m["groups"]:
        o += sjis(jp, 50)
    frames = [(bone, g + 1) for g, (_, _, members) in enumerate(m["groups"])
              for bone in members]
    o += u32(len(frames))
    for bone, g in frames:
        o += u16(bone) + u8(g)
    o += u8(1)  # English section present
    o += sjis(m["name_en"], 20) + sjis(m["comment"], 256)
    for b in bones:
        o += sjis(b["en"], 20)
    for _, en, _ in m["groups"]:
        o += sjis(en, 50)
    for i in range(10):
        o += sjis("toon%02d.bmp" % (i + 1), 100)
    o += u32(len(m["rigids"]))
    for r in m["rigids"]:
        o += sjis(r["jp"], 20) + i16(r["bone"]) + u8(r["group"])
        o += u16(r["mask"]) + u8(r["shape"])
        o += f32(*r["size"], *r["pos"], *r["rot"], r["mass"], r["lin"],
                 r["ang"], r["rest"], r["fric"]) + u8(r["mode"])
    o += u32(len(m["joints"]))
    for j in m["joints"]:
        o += sjis(j["jp"], 20) + u32(j["a"], j["b"])
        o += f32(*j["pos"], *j["rot"], *j["pos_min"], *j["pos_max"],
                 *j["rot_min"], *j["rot_max"], *j["spring_pos"],
                 *j["spring_rot"])
    return bytes(o)


# ---------------------------------------------------------------------------
# PMX 2.0, UTF-16LE
# ---------------------------------------------------------------------------


def pmx_index(value, size):
    return {1: struct.pack("<b", value), 2: struct.pack("<h", value),
            4: struct.pack("<i", value)}[size]


def pmx_vertex_index(value, size):
    return {1: u8(value), 2: u16(value), 4: u32(value)}[size]


def build_pmx(m):
    s = m["pmx_sizes"]
    bone_n = len(m["bones"])
    o = bytearray(b"PMX " + f32(2.0))
    o += u8(8, 0, s["uv"], s["vertex"], s["texture"], s["material"],
            s["bone"], s["morph"], s["rigid"])
    o += utf16(m["name"]) + utf16(m["name_en"])
    o += utf16(m["comment"]) + utf16(m["comment"])
    # vertices; the weight type cycles BDEF2 (chain) or BDEF1/2/4/SDEF (morph4)
    o += u32(len(m["verts"]))
    morph4 = m["file"] == "morph4.pmx"
    for k, (pos, bone) in enumerate(m["verts"]):
        o += f32(*pos, 0.0, 0.0, 1.0, pos[0] + 0.5, pos[1] / 8.0)
        for u in range(s["uv"]):
            o += f32(0.0, 0.25, 0.5, 0.75)
        nxt = min(bone + 1, bone_n - 1)
        kind = k % 4 if morph4 else 1
        if kind == 0:
            o += u8(0) + pmx_index(bone, s["bone"])
        elif kind == 1:
            o += u8(1) + pmx_index(bone, s["bone"]) + pmx_index(nxt, s["bone"])
            o += f32(0.75)
        elif kind == 2:
            o += u8(2) + b"".join(pmx_index(b, s["bone"])
                                  for b in (bone, nxt, bone, nxt))
            o += f32(0.5, 0.25, 0.125, 0.125)
        else:
            o += u8(3) + pmx_index(bone, s["bone"]) + pmx_index(nxt, s["bone"])
            o += f32(0.5, *pos, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        o += f32(1.0)  # edge scale
    o += u32(len(m["indices"]))
    for ix in m["indices"]:
        o += pmx_vertex_index(ix, s["vertex"])
    textures = [m["texture"]] if m["texture"] else []
    o += u32(len(textures))
    for t in textures:
        o += utf16(t)
    o += u32(1)  # one material over every face
    o += utf16("材質" if not morph4 else "材質1") + utf16("Mat")
    o += f32(0.75, 0.75, 0.75, 1.0, 0.5, 0.5, 0.5, 5.0, 0.25, 0.25, 0.25)
    o += u8(0x1E) + f32(0.0, 0.0, 0.0, 1.0, 1.0)
    o += pmx_index(0 if textures else -1, s["texture"])
    o += pmx_index(-1, s["texture"]) + u8(0, 1, 0)  # sphere mode, shared toon 0
    o += utf16("") + u32(len(m["indices"]))
    # bones
    o += u32(bone_n)
    for i, b in enumerate(m["bones"]):
        o += utf16(b["jp"]) + utf16(b["en"]) + f32(*b["pos"])
        o += pmx_index(b["parent"], s["bone"]) + i32(0)
        flags = 0x0002 | 0x0008 | 0x0010
        if b["movable"]:
            flags |= 0x0004
        if b["ik"]:
            flags |= 0x0020
        has_tail_bone = not b["ik"] and i + 1 < len(CHAIN) and m["file"] != "morph4.pmx"
        if has_tail_bone:
            flags |= 0x0001
        o += u16(flags)
        o += pmx_index(i + 1, s["bone"]) if has_tail_bone else f32(0.0, 1.0, 0.0)
        if b["ik"]:
            o += pmx_index(IK_TARGET, s["bone"]) + i32(10) + f32(0.5)
            o += i32(len(IK_LINKS))
            for link in IK_LINKS:
                limited = link == IK_LINKS[1]
                o += pmx_index(link, s["bone"]) + u8(1 if limited else 0)
                if limited:
                    o += f32(-1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    # morphs (all vertex morphs, type 1)
    o += u32(len(m["morphs"]))
    for jp, en, panel, offsets in m["morphs"]:
        o += utf16(jp) + utf16(en) + u8(panel, 1) + i32(len(offsets))
        for vertex, delta in offsets:
            o += pmx_vertex_index(vertex, s["vertex"]) + f32(*delta)
    # display frames: Root, Exp, then one per group
    frames = [("Root", "Root", 1, [(0, 0)])]
    frames.append(("表情", "Exp", 1, [(1, k) for k in range(len(m["morphs"]))]))
    for jp, en, members in m["groups"]:
        frames.append((jp, en, 0, [(0, b) for b in members]))
    o += u32(len(frames))
    for jp, en, special, entries in frames:
        o += utf16(jp) + utf16(en) + u8(special) + i32(len(entries))
        for kind, index in entries:
            size = s["morph"] if kind else s["bone"]
            o += u8(kind) + pmx_index(index, size)
    # rigid bodies and joints
    o += u32(len(m["rigids"]))
    for r in m["rigids"]:
        o += utf16(r["jp"]) + utf16(r["jp"]) + pmx_index(r["bone"], s["bone"])
        o += u8(r["group"]) + u16(r["mask"]) + u8(r["shape"])
        o += f32(*r["size"], *r["pos"], *r["rot"], r["mass"], r["lin"],
                 r["ang"], r["rest"], r["fric"]) + u8(r["mode"])
    o += u32(len(m["joints"]))
    for j in m["joints"]:
        o += utf16(j["jp"]) + utf16(j["jp"]) + u8(0)
        o += pmx_index(j["a"], s["rigid"]) + pmx_index(j["b"], s["rigid"])
        o += f32(*j["pos"], *j["rot"], *j["pos_min"], *j["pos_max"],
                 *j["rot_min"], *j["rot_max"], *j["spring_pos"],
                 *j["spring_rot"])
    return bytes(o)


# ---------------------------------------------------------------------------
# Motion data shared by VMD and PMM
# ---------------------------------------------------------------------------

LINEAR = (20, 20, 107, 107)  # x1, y1, x2, y2 of the default curve


def linear_lanes(x1, y1, x2, y2):
    """Curve table in PMM order (index = lane + 4 * group), same per lane."""
    return [v for v in (x1, y1, x2, y2) for _ in range(4)]


# A curve with a different value per lane, so a transposed table shows up.
CURVED = bytes([10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120,
                5, 15, 25, 35])


def wave(frame):
    """Triangle wave in [-1, 1], zero at frame 0, period 200."""
    u = frame % 200
    if u <= 50:
        return u / 50.0
    if u <= 150:
        return (100 - u) / 50.0
    return (u - 200) / 50.0


def swing_pose(bone_index, frame):
    """(position, quaternion) of a swing key. Only + - * / and sqrt are used."""
    s = wave(frame)
    pos = [0.0, 0.0, 0.0]
    quat = [0.0, 0.0, 0.0, 1.0]
    if bone_index == 0:
        pos[0] = 4.0 * s
    elif bone_index == 1:
        pos[1] = 0.5 * s
    if bone_index == 8:
        pos[2] = 1.0 * s
    elif bone_index >= 1:
        t = bone_index * s / 32.0
        den = 1.0 + t * t
        quat = [0.0, 0.0, 2.0 * t / den, (1.0 - t * t) / den]
    return pos, quat


def vmd_interp(table, physics_off):
    """64-byte VMD curve block, laid out as vmd_save.cpp writes it."""
    t = list(table) + [0, 0, 0]
    out = bytearray()
    for ch in range(4):
        if ch == 0:
            out += bytes(t[0:2]) + (u16(0x0F63) if physics_off else u16(0))
        else:
            out += bytes(t[ch:ch + 4])
        for g in (4, 8, 12):
            out += bytes(t[g + ch:g + ch + 4])
    assert len(out) == 64
    return bytes(out)


class Key:
    """One key of a track: frame plus payload fields."""

    def __init__(self, frame, **fields):
        self.frame = frame
        self.fields = fields
        self.prev = 0
        self.next = 0


def link_tracks(heads, tracks, freed=()):
    """Allocate pool records for keys sorted by (frame, track) and link them.

    heads: number of track heads (heads sit at pool indices 0..heads-1).
    tracks: per track, the non-head keys in frame order.
    freed: (track, position) keys released after allocation; the record stays
    empty and the chain skips it, which leaves a gap in the pool.
    Returns the chain (pool indices per track, head first) and a dict index ->
    Key for every non-head record.
    """
    pool = {}
    chains = [[t] for t in range(heads)]
    order = sorted((key.frame, t, pos) for t, keys in enumerate(tracks)
                   for pos, key in enumerate(keys))
    index = heads
    ids = {}
    for frame, t, pos in order:
        ids[(t, pos)] = index
        index += 1
    for t, keys in enumerate(tracks):
        for pos, key in enumerate(keys):
            if (t, pos) in freed:
                continue
            chains[t].append(ids[(t, pos)])
            pool[ids[(t, pos)]] = key
    return chains, pool


def apply_links(chains, heads_keys, pool):
    for t, chain in enumerate(chains):
        records = [heads_keys[t]] + [pool[i] for i in chain[1:]]
        for k, rec in enumerate(records):
            rec.prev = chain[k - 1] if k else 0
            rec.next = chain[k + 1] if k + 1 < len(chain) else 0


def track_bytes(heads_keys, pool, pack):
    """Dense head records, sparse count, then (index, record) pairs."""
    o = bytearray()
    for key in heads_keys:
        o += pack(key)
    o += i32(len(pool))
    for index in sorted(pool):
        o += i32(index) + pack(pool[index])
    return bytes(o)


def build_model_motion(model, slot):
    """Bone, morph and display tracks of one PMM model slot."""
    bones = model["bones"]
    bone_n = len(bones)
    is_swing = slot == 0
    bone_keys, bone_heads = [], []
    for i, b in enumerate(bones):
        frames = SWING_FRAMES[b["jp"]] if is_swing else [0]
        curved = b["jp"] == CURVED_BONE
        keys = []
        for f in frames:
            pos, quat = swing_pose(i, f)
            table = CURVED if (curved and f) else bytes(linear_lanes(*LINEAR))
            off = (b["jp"], f) == PHYSICS_OFF
            keys.append(Key(f, pos=pos, quat=quat, table=table, off=off))
        bone_heads.append(keys[0])
        bone_keys.append(keys[1:])
    freed = set()
    if is_swing:
        names = [b["jp"] for b in bones]
        t = names.index(FREED[0])
        pos = SWING_FRAMES[FREED[0]][1:].index(FREED[1])
        freed.add((t, pos))
    bone_chains, bone_pool = link_tracks(bone_n, bone_keys, freed)
    apply_links(bone_chains, bone_heads, bone_pool)

    morph_heads = [Key(0, value=0.0) for _ in model["morphs"]]
    morph_keys = [[Key(f, value=v) for f, v in MORPH_KEYS[m[0]]]
                  if slot == 1 else [] for m in model["morphs"]]
    morph_chains, morph_pool = link_tracks(len(morph_heads), morph_keys)
    apply_links(morph_chains, morph_heads, morph_pool)

    ik_n = len(ik_sources(model))
    sel_n = len(selector_sources(model))
    disp_head = Key(0, ik=[1] * ik_n, pairs=[(-1, 0)] * sel_n)
    disp_keys = []
    if is_swing:
        for f, ik, link in DISPLAY_KEYS:
            pairs = [(-1, 0)] * sel_n
            pairs[2] = link
            disp_keys.append(Key(f, ik=[ik] * ik_n, pairs=pairs))
    disp_chains, disp_pool = link_tracks(1, [disp_keys])
    apply_links(disp_chains, [disp_head], disp_pool)
    return dict(bone_heads=bone_heads, bone_pool=bone_pool,
                bone_chains=bone_chains, morph_heads=morph_heads,
                morph_pool=morph_pool, morph_chains=morph_chains,
                disp_head=disp_head, disp_pool=disp_pool)


# ---------------------------------------------------------------------------
# PMM v2
# ---------------------------------------------------------------------------


def pack_bone_key(k):
    o = u32(k.frame, k.prev, k.next)
    t = k.fields["table"]
    for lane in range(4):
        o += bytes([t[lane], t[lane + 4], t[lane + 8], t[lane + 12]])
    o += f32(*k.fields["pos"], *k.fields["quat"])
    return o + u8(1, 1 if k.fields["off"] else 0)


def pack_morph_key(k):
    return u32(k.frame, k.prev, k.next) + f32(k.fields["value"]) + u8(1)


def pack_display_key(k):
    o = u32(k.frame, k.prev, k.next) + u8(1) + bytes(k.fields["ik"])
    for model, bone in k.fields["pairs"]:
        o += i32(model, bone)
    return o + u8(1)


def pack_camera_key(k):
    f = k.fields
    o = u32(k.frame, k.prev, k.next) + f32(f["distance"], *f["eye"], *f["rot"])
    o += i32(-1, 0)  # parent model, parent bone
    x1, y1, x2, y2 = f["curve"]
    for _ in range(6):  # column-major: six channels, four rows each
        o += bytes([x1, y1, x2, y2])
    return o + u8(1) + i32(f["fov"]) + u8(0)


def pack_light_key(k):
    return (u32(k.frame, k.prev, k.next) + f32(*k.fields["color"],
            *k.fields["direction"]) + u8(0))


def pack_gravity_key(k):
    return (u32(k.frame, k.prev, k.next) + u8(1) + i32(10)
            + f32(9.8000002, 0.0, -1.0, 0.0) + u8(0))


def pack_shadow_key(k):
    return (u32(k.frame, k.prev, k.next) + u8(k.fields["mode"])
            + f32(k.fields["distance"]) + u8(0))


def global_track(keys, pack):
    """A single-head global track (camera, light, gravity, self shadow)."""
    head, rest = keys[0], keys[1:]
    chains, pool = link_tracks(1, [rest])
    apply_links(chains, [head], pool)
    return track_bytes([head], pool, pack)


def model_bytes(slot, model):
    motion = build_model_motion(model, slot)
    bones, morphs = model["bones"], model["morphs"]
    iks, sels = ik_sources(model), selector_sources(model)
    is_pmd = model["file"].endswith(".pmd")
    groups = len(model["groups"]) + (0 if is_pmd else 2)
    o = bytearray(u8(slot))
    o += sjis_str(model["name"]) + sjis_str(model["name_en"])
    o += sjis(model["file"], 256) + u8(groups)
    o += i32(len(bones))
    for b in bones:
        o += sjis_str(b["jp"])
    o += i32(len(morphs))
    for m in morphs:
        o += sjis_str(m[0])
    o += i32(len(iks)) + b"".join(i32(i) for i in iks)
    o += i32(len(sels)) + b"".join(i32(i) for i in sels)
    # selection state: draw order, load complete, selected bone, 4 morphs,
    # group flag count, group flags, bone list position, max frame
    o += u8(slot, 1) + i32(0) + i32(0, 0, 0, 0) + u8(groups) + u8(*[1] * groups)
    o += i32(0) + u32(LAST_FRAME)
    o += track_bytes(motion["bone_heads"], motion["bone_pool"], pack_bone_key)
    o += track_bytes(motion["morph_heads"], motion["morph_pool"],
                     pack_morph_key)
    o += track_bytes([motion["disp_head"]], motion["disp_pool"],
                     pack_display_key)
    for _ in bones:  # current pose at frame 0
        o += f32(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0) + u8(0, 0, 0)
    o += f32(*[0.0] * len(morphs))
    o += u8(*[1] * len(iks))
    for _ in sels:  # window start, window end, linked model, linked bone
        o += i32(0, 0, -1, 0)
    o += u8(1) + f32(1.0) + u8(1, 0)  # post load, edge scale, toon, display order
    return bytes(o), motion


def build_pmm(camera_keys=CAMERA_KEYS[:1], light_keys=LIGHT_KEYS):
    o = bytearray(b"Polygon Movie maker 0002" + b"\0" * 6)
    o += i32(1280, 720, 244) + f32(30.0) + u8(0, 1, 0, 0, 0, 0, 0)
    o += u8(0, len(PMM_MODELS))
    for slot, file in enumerate(PMM_MODELS):
        data, _ = model_bytes(slot, MODELS[file])
        o += data
    # camera
    cam = []
    for frame, dist, eye, rot, fov in camera_keys:
        curve = LINEAR if frame == 0 else CAMERA_CURVE
        cam.append(Key(frame, distance=dist, eye=eye, rot=rot, fov=fov,
                       curve=curve))
    o += global_track(cam, pack_camera_key)
    o += f32(0.0, 10.0, 0.0, 0.0, 0.0, -45.0, 0.0, 0.0, 0.0) + u8(1)
    # light
    light = [Key(f, color=c, direction=d) for f, c, d in light_keys]
    o += global_track(light, pack_light_key)
    o += f32(*light_keys[0][1], *light_keys[0][2])
    # accessories: none
    o += u8(0) + i32(0) + u8(0)
    # configuration
    o += i32(0, 0, LAST_FRAME, 0) + u8(0, 0, 0, 0) + i32(0, LAST_FRAME)
    o += u8(0) + b"\0" * 256                       # wave
    o += i32(0, 0) + f32(1.0) + b"\0" * 256 + u32(0)    # avi
    o += i32(0, 0) + f32(1.0) + b"\0" * 256 + u8(0)     # picture
    o += u8(0, 1, 1) + f32(30.0) + i32(0)          # view
    o += i32(0) + f32(0.0) + u8(1)                 # split order, shadow ambient, shadow blend
    # Physics mode 2, "on/off mode", the app default. 0 means no physics, and
    # the trace would never move a rigid body.
    o += u8(2) + f32(9.8000002) + i32(10)
    o += f32(0.0, -1.0, 0.0) + u8(1)               # physics
    # gravity track, self shadow state, self shadow track
    o += global_track([Key(0)], pack_gravity_key)
    o += u8(1) + f32(8875.0)
    shadow = [Key(f, mode=m, distance=d) for f, m, d in SHADOW_KEYS]
    o += global_track(shadow, pack_shadow_key)
    # appearance
    o += i32(0, 0, 0) + u8(0) + i32(-1, 0)
    o += f32(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    o += u8(0, 0, 1) + i32(LAST_FRAME)
    # tail: constant 1, then slot and frame-registration selection per model
    o += u8(1)
    for slot in range(len(PMM_MODELS)):
        o += u8(slot) + i32(0)
    return bytes(o)


# ---------------------------------------------------------------------------
# VMD 0002
# ---------------------------------------------------------------------------


def build_vmd():
    motion = build_model_motion(MODELS["chain8_ik.pmx"], 0)
    bones = MODELS["chain8_ik.pmx"]["bones"]
    o = bytearray(b"Vocaloid Motion Data 0002" + b"\0" * 5)
    o += sjis("chain8", 20)
    records = []  # pool order: heads, then sparse keys by index
    for t, key in enumerate(motion["bone_heads"]):
        records.append((t, key))
    for index in sorted(motion["bone_pool"]):
        t = next(t for t, c in enumerate(motion["bone_chains"]) if index in c)
        records.append((t, motion["bone_pool"][index]))
    o += u32(len(records))
    for t, key in records:
        o += sjis(bones[t]["jp"], 15) + u32(key.frame)
        o += f32(*key.fields["pos"], *key.fields["quat"])
        o += vmd_interp(key.fields["table"], key.fields["off"])
    morph_model = MODELS["morph4.pmx"]
    morph = build_model_motion(morph_model, 1)
    morph_records = [(t, k) for t, k in enumerate(morph["morph_heads"])]
    for index in sorted(morph["morph_pool"]):
        t = next(t for t, c in enumerate(morph["morph_chains"]) if index in c)
        morph_records.append((t, morph["morph_pool"][index]))
    o += u32(len(morph_records))
    for t, key in morph_records:
        o += sjis(morph_model["morphs"][t][0], 15) + u32(key.frame)
        o += f32(key.fields["value"])
    o += u32(len(CAMERA_KEYS))
    for frame, dist, eye, rot, fov in CAMERA_KEYS:
        x1, y1, x2, y2 = LINEAR if frame == 0 else CAMERA_CURVE
        o += u32(frame) + f32(dist, *eye, *rot)
        o += bytes([x1, x2, y1, y2]) * 6  # file order: x1, x2, y1, y2
        o += u32(fov) + u8(1)
    o += u32(len(LIGHT_KEYS))
    for frame, color, direction in LIGHT_KEYS:
        o += u32(frame) + f32(*color, *direction)
    o += u32(len(SHADOW_KEYS))
    for frame, mode, distance in SHADOW_KEYS:
        o += u32(frame) + u8(mode) + f32(distance)
    ik_keys = [(0, 1)] + [(f, ik) for f, ik, _ in DISPLAY_KEYS]
    o += u32(len(ik_keys))
    for frame, ik in ik_keys:
        o += u32(frame) + u8(1) + u32(1) + sjis(IK_BONE[0], 20) + u8(ik)
    return bytes(o)


# ---------------------------------------------------------------------------
# VPD (text, CRLF, Shift-JIS)
# ---------------------------------------------------------------------------

POSE = [  # (bone, translation, quaternion)
    ("センター", (0.0, 0.5, 0.0), (0.0, 0.0, 0.0, 1.0)),
    ("首", (0.0, 0.0, 0.0), (0.0, 0.0, 0.25, 0.96875)),
    ("髪3", (0.0, 0.0, 0.0), (0.0, 0.0, -0.5, 0.875)),
]


def build_vpd():
    def f(x):  # the value is a float32 on disk in MMD
        return "%f" % struct.unpack("<f", struct.pack("<f", x))[0]

    lines = ["Vocaloid Pose Data file", "",
             "chain8.osm;\t\t// 親ファイル名",
             "%d;\t\t\t\t// 総ポーズボーン数" % len(POSE), ""]
    for i, (name, trans, quat) in enumerate(POSE):
        lines += ["Bone%d{%s" % (i, name),
                  "  %s;\t\t\t\t// trans x,y,z" % ",".join(map(f, trans)),
                  "  %s;\t\t// Quaternion x,y,z,w" % ",".join(map(f, quat)),
                  "}", ""]
    return "\r\n".join(lines).encode("cp932") + b"\r\n"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def generate():
    """All fixture files as {name: bytes}, in FILE_NAMES order."""
    out = {
        "chain8.pmd": build_pmd(MODELS["chain8.pmd"]),
        "chain8.pmx": build_pmx(MODELS["chain8.pmx"]),
        "chain8_ik.pmx": build_pmx(MODELS["chain8_ik.pmx"]),
        "morph4.pmx": build_pmx(MODELS["morph4.pmx"]),
        "swing600.vmd": build_vmd(),
        "pose.vpd": build_vpd(),
        "swing600.pmm": build_pmm(),
        "camera3.pmm": build_pmm(CAMERA_KEYS, LIGHT3_KEYS),
    }
    assert list(out) == FILE_NAMES
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true",
                      help="regenerate the fixture files")
    mode.add_argument("--check", action="store_true",
                      help="compare regenerated bytes with the files")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR,
                    help="fixture directory (default: tests/fixtures/rust)")
    args = ap.parse_args(argv)
    files = generate()
    if args.write:
        args.dir.mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (args.dir / name).write_bytes(data)
        print("fixtures: wrote %d files, %d bytes" %
              (len(files), sum(map(len, files.values()))))
        return 0
    drift = []
    for name, data in files.items():
        path = args.dir / name
        if not path.is_file():
            drift.append("%s: missing" % name)
        elif path.read_bytes() != data:
            drift.append("%s: differs" % name)
    if drift:
        for line in drift:
            print("fixtures: DRIFT " + line, file=sys.stderr)
        return 1
    print("fixtures: %d files match" % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
