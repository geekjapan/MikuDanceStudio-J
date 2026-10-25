#!/usr/bin/env python3
"""Write the golden2 scenes: PMM files, a textured skin model and the images.

Python standard library only, with no clock, no randomness and no libm call,
as tools/fixtures/gen_fixtures.py, whose byte helpers and key-pool layout this
reuses. Rotations are rational quaternions.

    python3 -I tests/fixtures/rust/golden2/gen_golden2.py --write
    python3 -I tests/fixtures/rust/golden2/gen_golden2.py --check

Every scene runs with physics mode 0 (no calculation), so a pose is its keys.
README.md says what each scene checks.
"""
import argparse
import struct
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "tools" / "fixtures"))
sys.path.insert(0, str(ROOT / "tests" / "fixtures" / "rust" / "skin"))
import gen_fixtures as g  # noqa: E402
import gen_skin  # noqa: E402

from gen_fixtures import f32, i32, sjis, sjis_str, u8, u32  # noqa: E402

LAST_FRAME = 60
PI = 3.14159265358979


def turn(axis, t):
    """Unit quaternion (x, y, z, w) about axis 0, 1 or 2; tan(angle / 4) = t."""
    den = 1.0 + t * t
    q = [0.0, 0.0, 0.0, (1.0 - t * t) / den]
    q[axis] = 2.0 * t / den
    return q


# ---------------------------------------------------------------------------
# Images. D3DX loads BMP and PNG; both are written uncompressed or with zlib.
# ---------------------------------------------------------------------------


def bmp24(width, height, pixel):
    """Bottom-up 24-bit BMP; pixel(x, y) -> (r, g, b) with y = 0 at the top."""
    row = (width * 3 + 3) & ~3
    data = bytearray()
    for y in range(height - 1, -1, -1):
        line = bytearray()
        for x in range(width):
            r, gr, b = pixel(x, y)
            line += bytes((b, gr, r))
        data += line + b"\0" * (row - len(line))
    header = b"BM" + struct.pack("<IHHI", 54 + len(data), 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(data),
                       2835, 2835, 0, 0)
    return header + info + bytes(data)


def png_rgb(width, height, pixel):
    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body)))
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw += bytes(pixel(x, y))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def skin_texture(x, y):
    """16x16: four quadrants of distinct colors, so a UV shift is visible."""
    return [(224, 64, 64), (64, 160, 224), (64, 192, 96), (240, 208, 64)][
        (x // 8) + 2 * (y // 8)]


def cube_texture(x, y):
    return (32, 32, 160) if (x // 2 + y // 2) % 2 else (240, 240, 240)


def background(x, y):
    """640x360: 80-pixel checker over a horizontal ramp, a red frame line."""
    if x in (0, 639) or y in (0, 359):
        return (255, 0, 0)
    base = 64 + (x * 128) // 640
    return (base, 96, 192) if (x // 80 + y // 80) % 2 else (base, 192, 96)


# ---------------------------------------------------------------------------
# skin_tex.pmx: skin.pmx with one texture on every material, so that its UV
# morph moves the texture on screen. Everything else is gen_skin's bytes.
# ---------------------------------------------------------------------------

SKIN_TEXTURE = "skin_tex.bmp"


def build_skin_tex():
    base = gen_skin.build_skin_pmx()
    # Header: magic, version, 9 globals, then four UTF-16 strings.
    pos = 4 + 4 + 1 + 8
    for _ in range(4):
        pos += 4 + struct.unpack_from("<I", base, pos)[0]
    vertex_count = struct.unpack_from("<I", base, pos)[0]
    pos += 4
    for _ in range(vertex_count):
        kind = base[pos + 32 + 32]  # position, normal, uv, two add UVs
        pos += 32 + 32 + 1 + {0: 1 + 4 * 0, 1: 2 + 4, 2: 4 + 16, 3: 2 + 4 + 36}[kind] + 4
    faces = struct.unpack_from("<I", base, pos)[0]
    pos += 4 + faces
    assert base[pos:pos + 4] == u32(0)  # no textures
    out = bytearray(base[:pos]) + u32(1) + g.utf16(SKIN_TEXTURE)
    pos += 4
    count = struct.unpack_from("<I", base, pos)[0]
    out += base[pos:pos + 4]
    pos += 4
    for _ in range(count):
        start = pos
        for _ in range(2):
            pos += 4 + struct.unpack_from("<I", base, pos)[0]
        pos += 4 * 11 + 1 + 4 * 5
        out += base[start:pos]
        assert base[pos] == 0xFF  # texture index -1
        out += u8(0)
        pos += 1
        start = pos  # sphere index, sphere mode, toon flag, toon, memo, face count
        pos += 4
        pos += 4 + struct.unpack_from("<I", base, pos)[0] + 4
        out += base[start:pos]
    out += base[pos:]
    return bytes(out)


# The loader takes a model's texture directory from its path up to the last
# backslash (pmd_load.cpp); a bare file name leaves its first letter instead,
# and the texture does not load.
SKIN_SPEC = dict(
    file=".\\skin_tex.pmx", name="skin", name_en="skin",
    bones=[dict(jp=name, movable=(i == 1), ik=False)
           for i, (name, _, _) in enumerate(gen_skin.PMX_BONES)],
    morphs=[(m[0],) for m in gen_skin.PMX_MORPHS],
    groups=[None])  # the PMX has Root, the expression frame and one more


# ---------------------------------------------------------------------------
# PMM
# ---------------------------------------------------------------------------

IDENTITY = ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0])


class SceneModel:
    """A model slot: spec (gen_fixtures MODELS layout), bone and morph keys.

    bones: {bone index: [(frame, position, quaternion)]}, frame 0 first.
    morphs: {morph index: [(frame, weight)]}.
    """

    def __init__(self, spec, bones=None, morphs=None, edge_scale=1.0):
        self.spec = spec
        self.bones = bones or {}
        self.morphs = morphs or {}
        self.edge_scale = edge_scale


def model_bytes(slot, m):
    spec = m.spec
    bones, morphs = spec["bones"], spec["morphs"]
    table = bytes(g.linear_lanes(*g.LINEAR))
    bone_heads, bone_keys = [], []
    for i in range(len(bones)):
        keys = [g.Key(f, pos=list(p), quat=list(q), table=table, off=False)
                for f, p, q in m.bones.get(i, [(0,) + IDENTITY])]
        assert keys[0].frame == 0
        bone_heads.append(keys[0])
        bone_keys.append(keys[1:])
    bone_chains, bone_pool = g.link_tracks(len(bones), bone_keys)
    g.apply_links(bone_chains, bone_heads, bone_pool)

    morph_heads, morph_keys = [], []
    for i in range(len(morphs)):
        keys = [g.Key(f, value=v) for f, v in m.morphs.get(i, [(0, 0.0)])]
        assert keys[0].frame == 0
        morph_heads.append(keys[0])
        morph_keys.append(keys[1:])
    morph_chains, morph_pool = g.link_tracks(len(morphs), morph_keys)
    g.apply_links(morph_chains, morph_heads, morph_pool)

    iks, sels = g.ik_sources(spec), g.selector_sources(spec)
    disp_head = g.Key(0, ik=[1] * len(iks), pairs=[(-1, 0)] * len(sels))
    disp_chains, disp_pool = g.link_tracks(1, [[]])
    g.apply_links(disp_chains, [disp_head], disp_pool)

    groups = len(spec["groups"]) + (0 if spec["file"].endswith(".pmd") else 2)
    o = bytearray(u8(slot))
    o += sjis_str(spec["name"]) + sjis_str(spec["name_en"])
    o += sjis(spec["file"], 256) + u8(groups)
    o += i32(len(bones)) + b"".join(sjis_str(b["jp"]) for b in bones)
    o += i32(len(morphs)) + b"".join(sjis_str(n[0]) for n in morphs)
    o += i32(len(iks)) + b"".join(i32(i) for i in iks)
    o += i32(len(sels)) + b"".join(i32(i) for i in sels)
    o += u8(slot, 1) + i32(0) + i32(0, 0, 0, 0) + u8(groups) + u8(*[1] * groups)
    o += i32(0) + u32(LAST_FRAME)
    o += g.track_bytes(bone_heads, bone_pool, g.pack_bone_key)
    o += g.track_bytes(morph_heads, morph_pool, g.pack_morph_key)
    o += g.track_bytes([disp_head], disp_pool, g.pack_display_key)
    for k in bone_heads:  # current pose: the frame-0 keys
        o += f32(*k.fields["pos"], *k.fields["quat"]) + u8(0, 0, 0)
    o += f32(*[k.fields["value"] for k in morph_heads])
    o += u8(*[1] * len(iks))
    for _ in sels:
        o += i32(0, 0, -1, 0)
    # post load 0: normal blending (1 is additive)
    o += u8(0) + f32(m.edge_scale) + u8(1, 0)
    return bytes(o)


class Accessory:
    """An accessory with one key at frame 0. parent: (model slot, bone) or
    (-1, 0) for the ground."""

    def __init__(self, file, position, rotation=(0.0, 0.0, 0.0), scale=1.0,
                 parent=(-1, 0), shadow=1):
        self.file = file
        self.position, self.rotation, self.scale = position, rotation, scale
        self.parent, self.shadow = parent, shadow


def pack_accessory_key(k):
    a = k.fields["acc"]
    return (u32(k.frame, k.prev, k.next) + u8(1) + i32(*a.parent)
            + f32(*a.position, *a.rotation, a.scale) + u8(a.shadow, 0))


def accessory_bytes(accessories):
    o = bytearray(u8(0) + i32(0) + u8(len(accessories)))
    for a in accessories:
        o += sjis(a.file, 100)
    for slot, a in enumerate(accessories):
        o += u8(slot) + sjis(a.file, 100) + sjis(ACCESSORY_DIR + a.file, 256) + u8(slot)
        o += g.global_track([g.Key(0, acc=a)], pack_accessory_key)
        # opacity 1 and visible, parent, rotation, scale, position, shadow, additive
        o += u8(1) + i32(*a.parent) + f32(*a.rotation, a.scale, *a.position)
        o += u8(a.shadow, 0)
    return bytes(o)


# The loader resolves accessory paths with a directory part against the exe
# directory; the oracle stages every file next to the exe.
ACCESSORY_DIR = ".\\"


def build_pmm(models, camera_keys, light_keys, shadow_keys, perspective=1,
              ground_shadow=(0, 0.0, 1), accessories=(), picture=None):
    """camera_keys: (frame, distance, target, rotation, fov). light_keys:
    (frame, color, direction). shadow_keys: (frame, mode, distance).
    ground_shadow: (on, ambient, translucent). picture: file name or None."""
    o = bytearray(b"Polygon Movie maker 0002" + b"\0" * 6)
    o += i32(1280, 720, 244) + f32(30.0) + u8(0, 1, 0, 0, 0, 0, 0)
    o += u8(0, len(models))
    for slot, m in enumerate(models):
        o += model_bytes(slot, m)

    def camera_key(frame, dist, target, rot, fov):
        k = g.Key(frame, distance=dist, eye=target, rot=rot, fov=fov, curve=g.LINEAR)
        return k

    def pack_camera(k):  # gen_fixtures' record with the perspective byte set
        b = bytearray(g.pack_camera_key(k))
        b[-6] = perspective
        return bytes(b)
    o += g.global_track([camera_key(*c) for c in camera_keys], pack_camera)
    _, dist, target, rot, _ = camera_keys[0]
    o += f32(*target, 0.0, 0.0, dist, *rot) + u8(perspective)
    light = [g.Key(f, color=c, direction=d) for f, c, d in light_keys]
    o += g.global_track(light, g.pack_light_key)
    o += f32(*light_keys[0][1], *light_keys[0][2])
    o += accessory_bytes(accessories)
    o += i32(0, 0, LAST_FRAME, 0) + u8(0, 0, 0, 0) + i32(0, LAST_FRAME)
    o += u8(0) + b"\0" * 256                                  # wave
    o += i32(0, 0) + f32(1.0) + b"\0" * 256 + u32(0)          # avi
    o += i32(0, 0) + f32(1.0)                                 # picture
    o += sjis(ACCESSORY_DIR + picture if picture else "", 256) + u8(1 if picture else 0)
    o += u8(0, 1, ground_shadow[0]) + f32(30.0) + i32(0)      # view
    o += i32(0) + f32(ground_shadow[1]) + u8(ground_shadow[2])
    o += u8(0) + f32(9.8000002) + i32(10)                     # physics mode 0
    o += f32(0.0, -1.0, 0.0) + u8(1)
    o += g.global_track([g.Key(0)], g.pack_gravity_key)
    o += u8(shadow_keys[0][1]) + f32(shadow_keys[0][2])
    shadow = [g.Key(f, mode=m, distance=d) for f, m, d in shadow_keys]
    o += g.global_track(shadow, g.pack_shadow_key)
    o += i32(0, 0, 0) + u8(0) + i32(-1, 0)                    # appearance
    o += f32(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    o += u8(0, 0, 1) + i32(LAST_FRAME)
    o += u8(1)
    for slot in range(len(models)):
        o += u8(slot) + i32(0)
    return bytes(o)


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------

CHAIN = g.MODELS["chain8.pmx"]
CHAIN_PMD = g.MODELS["chain8.pmd"]
MORPH4 = g.MODELS["morph4.pmx"]
LIGHT = [(0, (0.625, 0.625, 0.625), (-0.5, -1.0, 0.5))]
# The orthographic camera of the golden scene (yaw pi faces the fronts of the
# models), turned down by the pitch so the ground shows.
PITCH = -0.375


def ortho_camera(distance=-30.0, target=(0.0, 4.0, 0.0), pitch=PITCH):
    return [(0, distance, target, (pitch, PI, 0.0), 30)]


def at(x, z=0.0):
    """The root bone keyed to stand at (x, 0, z)."""
    return {0: [(0, [x, 0.0, z], [0.0, 0.0, 0.0, 1.0])]}


def curled(x):
    """chain8 standing at x with its upper bones leaning toward the camera, so
    its top shades its foot."""
    bones = at(x)
    for i in range(2, 8):
        bones[i] = [(0, [0.0, 0.0, 0.0], turn(0, -0.125))]
    return bones


SHADOW_DEFAULT = 0.01125  # the app's default self-shadow distance (range 8875)
SHADOW_OFF = [(0, 0, SHADOW_DEFAULT)]

SCENES = {
    # Self-shadow mode 1 at frame 0 and mode 2 with a shorter distance at 30.
    "selfshadow": dict(
        models=[SceneModel(CHAIN, curled(-3.0)), SceneModel(CHAIN_PMD, curled(3.0))],
        camera_keys=ortho_camera(-16.0, (0.0, 3.0, 0.0)), light_keys=LIGHT,
        shadow_keys=[(0, 1, SHADOW_DEFAULT), (30, 2, 0.005)],
        frames=[0, 30]),
    # The projected ground shadow, opaque at frame 0 brightness; the light
    # turns by frame 30. Translucent shadow with ambient 0.5.
    "groundshadow": dict(
        models=[SceneModel(CHAIN, curled(-3.0)), SceneModel(MORPH4, at(3.0))],
        camera_keys=ortho_camera(-16.0, (0.0, 3.0, 0.0)), shadow_keys=SHADOW_OFF,
        light_keys=LIGHT + [(30, (0.625, 0.625, 0.625), (0.5, -1.0, 0.25))],
        ground_shadow=(1, 0.5, 1), frames=[0, 30]),
    # cube.x on bone 頭 of chain8 (which moves by frame 30) and a quad on the
    # ground.
    "accessory": dict(
        models=[SceneModel(CHAIN, {0: [(0, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]),
                                        (30, [3.0, 0.0, 0.0], turn(1, 0.25))]})],
        camera_keys=ortho_camera(), light_keys=LIGHT, shadow_keys=SHADOW_OFF,
        # The app scales an accessory by 10 times its scale value: cube.x
        # (2 units) becomes 1 unit, the unit quad 4 units, laid flat.
        accessories=[Accessory("cube.x", (0.0, 0.75, 0.0), (0.0, 0.5, 0.0), 0.05, (0, 4)),
                     Accessory("normals_uv.x", (-5.0, 0.05, -2.0), (PI / 2, 0.0, 0.0), 0.4)],
        frames=[0, 30]),
    # skin_tex.pmx with SDEF bones turned and vertex, UV and material morphs;
    # other weights and a bone morph at frame 30.
    "skin": dict(
        models=[SceneModel(SKIN_SPEC, {
            2: [(0, [0.0, 0.0, 0.0], turn(2, 0.125)), (30, [0.0, 0.0, 0.0], turn(1, 0.25))],
            3: [(0, [0.0, 0.0, 0.0], turn(1, -0.25)), (30, [0.0, 0.0, 0.0], turn(2, -0.125))],
        }, {
            0: [(0, 1.0), (30, 0.0)],   # v0
            1: [(0, 0.0), (30, 1.0)],   # v1
            2: [(0, 1.0), (30, 0.5)],   # uv
            5: [(0, 0.0), (30, 1.0)],   # uv2
            6: [(0, 0.5), (30, 0.0)],   # matmul
            7: [(0, 0.0), (30, 1.0)],   # matadd
            8: [(0, 0.0), (30, 1.0)],   # bone
        }, edge_scale=2.0)],
        camera_keys=[(0, -6.0, (1.0, 1.0, 0.0), (-0.25, PI, 0.0), 30)],
        light_keys=LIGHT, shadow_keys=SHADOW_OFF, perspective=0, frames=[0, 30]),
    # The background picture behind one model.
    "background": dict(
        models=[SceneModel(CHAIN, at(0.0))],
        camera_keys=ortho_camera(), light_keys=LIGHT, shadow_keys=SHADOW_OFF,
        picture="background.png", frames=[0]),
    # A perspective camera over models at three depths; the camera moves in by
    # frame 30 and widens its view angle.
    "perspective": dict(
        models=[SceneModel(CHAIN, at(-6.0, -6.0)), SceneModel(CHAIN_PMD, at(0.0, 0.0)),
                SceneModel(MORPH4, at(6.0, 6.0))],
        camera_keys=[(0, -45.0, (0.0, 4.0, 0.0), (PITCH, PI, 0.0), 30),
                     (30, -30.0, (0.0, 4.0, 0.0), (PITCH, PI + 0.5, 0.0), 45)],
        light_keys=LIGHT, shadow_keys=SHADOW_OFF, perspective=0, frames=[0, 30]),
}


def generate():
    out = {}
    for name, scene in SCENES.items():
        args = {k: v for k, v in scene.items() if k != "frames"}
        out[name + ".pmm"] = build_pmm(**args)
    out["skin_tex.pmx"] = build_skin_tex()
    out[SKIN_TEXTURE] = bmp24(16, 16, skin_texture)
    out["cube.bmp"] = bmp24(8, 8, cube_texture)
    out["background.png"] = png_rgb(640, 360, background)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--frames", action="store_true",
                      help="print '<scene> <frame>...' per scene for the oracle")
    args = ap.parse_args(argv)
    if args.frames:
        for name, scene in SCENES.items():
            print(name, *scene["frames"])
        return 0
    files = generate()
    if args.write:
        for name, data in files.items():
            (HERE / name).write_bytes(data)
        print("golden2: wrote %d files" % len(files))
        return 0
    drift = [n for n, d in files.items()
             if not (HERE / n).is_file() or (HERE / n).read_bytes() != d]
    for n in drift:
        print("golden2: DRIFT " + n, file=sys.stderr)
    if drift:
        return 1
    print("golden2: %d files match" % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
