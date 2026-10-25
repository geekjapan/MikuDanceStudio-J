#!/usr/bin/env python3
"""Write the PMM 0001 fixtures for the mds-formats v1 reader.

Python standard library only, no clock and no randomness. The byte helpers,
the chain8 model and the key-pool linking come from
tools/fixtures/gen_fixtures.py, which this file imports and does not change.

    python3 -I tests/fixtures/rust/pmm1/gen_pmm1.py --write
    python3 -I tests/fixtures/rust/pmm1/gen_pmm1.py --check

The scenes follow the order src/io/pmm_load_v1.cpp reads them: the 30-byte
header, six option bytes, the selected slot and model count, one 20-byte name
per model, the model blocks, the camera, light and accessory sections, the
configuration block, and the read-gated tail. A 0001 model block names a PMD
file and carries no bone, morph or IK table, so each scene names the PMDs
written next to it.

  v1_rig.pmm        one model with bone, morph and display keys, a camera
                    with a parent, a light, and the whole tail
  v1_scene.pmm      one model, camera and light keys, two accessories with
                    keys, wave, AVI and picture records, and no tail
  v1_multi.pmm      three models stored in slot order 5, 1, 3, one accessory,
                    and a tail that stops at a gate byte of 0
  v1_noparent.pmm   a tail whose camera parent is -1: the C++ then skips the
                    parent key list, the portable reader on next does not
  v1_edge.pmm       a free (frame 0) sparse record and a group flag count
                    that differs from the PMD
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "tools" / "fixtures"))
import gen_fixtures as g  # noqa: E402
from gen_fixtures import Key, f32, i16, i32, sjis, u8, u16, u32  # noqa: E402

LINEAR = bytes(g.linear_lanes(*g.LINEAR))

# ---------------------------------------------------------------------------
# Model files
# ---------------------------------------------------------------------------

# rig3.pmd: bone (name, English, kind, parent) with kind 1 = move, 2 = IK.
RIG3_BONES = [("センター", "Center", 1, -1), ("上半身", "Upper", 0, 0),
              ("腕", "Arm", 0, 1), ("腕ＩＫ", "ArmIK", 2, 0)]
RIG3_IK = (3, 2, [1], 5, 0.5)  # bone, target, links, iterations, max angle
RIG3_MORPHS = [("base", "base", 0, [(0, (0.0, 0.0, 0.0)), (3, (0.0, 0.0, 0.0))]),
               ("まばたき", "Blink", 2, [(0, (0.0, -0.25, 0.0))]),
               ("あ", "A", 3, [(1, (0.0, -0.5, 0.0))])]
RIG3_GROUP = ("ボディ", "Body")
# What each PMD loads into the model record (src/model/pmd_load.cpp): bone,
# morph (the base morph included) and IK counts, and the display group count:
# the file's groups, two fixed ones, one more for a non-empty face list.
RIG3 = dict(file="rig3.pmd", bones=4, morphs=3, ik=1, groups=1 + 2 + 1)
CHAIN8 = dict(file="chain8.pmd", bones=8, morphs=0, ik=0, groups=2 + 2)


def build_rig3():
    n = len(RIG3_BONES)
    verts = g.strip_vertices(n)
    indices = g.strip_indices(n)
    o = bytearray(b"Pmd" + f32(1.0))
    o += sjis("rig3", 20) + sjis("PMM 0001 fixture model", 256)
    o += u32(len(verts))
    for pos, bone in verts:
        o += f32(*pos, 0.0, 0.0, 1.0, pos[0] + 0.5, pos[1] / 8.0)
        o += u16(bone, bone) + u8(100, 0)
    o += u32(len(indices)) + u16(*indices)
    o += u32(1)
    o += f32(0.75, 0.75, 0.75, 1.0, 5.0, 0.5, 0.5, 0.5, 0.25, 0.25, 0.25)
    o += u8(0, 1) + u32(len(indices)) + sjis("", 20)
    o += u16(n)
    for i, (jp, _, kind, parent) in enumerate(RIG3_BONES):
        tail = i + 1 if i + 1 < n else 0
        o += sjis(jp, 20) + i16(parent) + u16(tail) + u8(kind) + u16(0)
        o += f32(0.0, float(i), 0.0)
    bone, target, links, iterations, angle = RIG3_IK
    o += u16(1) + u16(bone, target) + u8(len(links)) + u16(iterations) + f32(angle)
    o += u16(*links)
    o += u16(len(RIG3_MORPHS))
    for jp, _, panel, offsets in RIG3_MORPHS:
        o += sjis(jp, 20) + i32(len(offsets)) + u8(panel)
        for vertex, delta in offsets:
            o += u32(vertex) + f32(*delta)
    o += u8(2) + u16(0, 1)  # face display list
    o += u8(1) + sjis(RIG3_GROUP[0], 50)
    frames = [(1, 1), (2, 1)]
    o += u32(len(frames))
    for bone, group in frames:
        o += u16(bone) + u8(group)
    o += u8(1) + sjis("rig3", 20) + sjis("PMM 0001 fixture model", 256)
    for _, en, _, _ in RIG3_BONES:
        o += sjis(en, 20)
    for _, en, _, _ in RIG3_MORPHS[1:]:
        o += sjis(en, 20)
    o += sjis(RIG3_GROUP[1], 50)
    for i in range(10):
        o += sjis("toon%02d.bmp" % (i + 1), 100)
    o += u32(0) + u32(0)  # rigid bodies, joints
    return bytes(o)


# ---------------------------------------------------------------------------
# 0001 key records
# ---------------------------------------------------------------------------


def links(k):
    return u32(k.frame, k.prev, k.next)


def pack_bone(k):  # 57 bytes: the 0002 record without the physics byte
    t = k.fields["table"]
    o = links(k)
    for lane in range(4):
        o += bytes([t[lane], t[lane + 4], t[lane + 8], t[lane + 12]])
    return o + f32(*k.fields["pos"], *k.fields["quat"]) + u8(k.fields["alloc"])


def pack_morph(k):
    return links(k) + f32(k.fields["value"]) + u8(k.fields["alloc"])


def pack_display(k):  # the 0002 record without the selector pairs
    return links(k) + u8(k.fields["vis"]) + bytes(k.fields["ik"]) + u8(k.fields["alloc"])


def pack_camera(k):  # 70 bytes: the 0002 record without parent model and bone
    f = k.fields
    o = links(k) + f32(f["distance"], *f["eye"], *f["rot"]) + f["curve"]
    return o + u8(f["persp"]) + i32(f["fov"]) + u8(f["sel"])


def pack_light(k):
    f = k.fields
    return links(k) + f32(*f["color"], *f["direction"]) + u8(f["sel"])


def pack_shadow(k):
    f = k.fields
    return links(k) + u8(f["mode"]) + f32(f["distance"]) + u8(f["sel"])


def pack_accessory(k):
    f = k.fields
    o = links(k) + u8(f["ov"]) + i32(f["pm"], f["pb"]) + f32(*f["pos"], *f["rot"])
    return o + f32(f["scale"]) + u8(f["shadow"], f["sel"])


def track(heads, sparse, pack, free=0):
    """Dense heads, then the sparse keys linked as the C++ pool links them.
    free: that many extra records with frame 0 (free pool records) appended."""
    chains, pool = g.link_tracks(len(heads), sparse)
    g.apply_links(chains, heads, pool)
    top = max(pool, default=len(heads) - 1)
    for i in range(free):
        pool[top + 1 + i] = Key(0, **dict(heads[0].fields))
    return g.track_bytes(heads, pool, pack)


# ---------------------------------------------------------------------------
# Model block
# ---------------------------------------------------------------------------


def bone_pose_bytes(count):
    o = b""
    for i in range(count):
        # Components 3 and 7 differ: the second one is the stored rotation x.
        o += f32(0.25 * i, 0.0, -0.5, 0.0625 * (i + 1), 0.0, 0.125, 1.0, 0.5 + 0.125 * i)
        o += u8(2 if i == 2 else i % 2, 1 if i == 1 else 0)
    return o


def model_block(slot, counts, v1_name, cfg):
    nb, nm, nk = counts["bones"], counts["morphs"], counts["ik"]
    o = u8(slot) + sjis(v1_name, 20) + sjis(counts["file"], 256)
    o += u8(cfg["combo"], cfg["load"]) + i32(cfg["bone"]) + i32(*cfg["morphs4"])
    o += u8(len(cfg["group_flags"])) + bytes(cfg["group_flags"])
    o += i32(cfg["list_pos"]) + u32(cfg["max_frame"])

    heads, sparse = [], []
    for b in range(nb):
        keys = []
        for f in cfg["bone_frames"].get(b, [0]):
            pos, quat = g.swing_pose(b, f)
            pos[0] += 0.125 * (b + 1) if f else 0.0
            table = g.CURVED if (b == 1 and f) else LINEAR
            keys.append(Key(f, pos=pos, quat=quat, table=bytes(table),
                            alloc=2 if (b, f) == (0, 10) else 1))
        heads.append(keys[0])
        sparse.append(keys[1:])
    o += track(heads, sparse, pack_bone, cfg.get("free", 0))

    heads, sparse = [], []
    for m in range(nm):
        keys = [Key(f, value=0.125 * (m + 1) * (f % 5), alloc=1)
                for f in cfg["morph_frames"].get(m, [0])]
        heads.append(keys[0])
        sparse.append(keys[1:])
    o += track(heads, sparse, pack_morph)

    ik = [cfg["ik"]] * nk
    heads = [Key(0, vis=1, ik=ik, alloc=1)]
    sparse = [[Key(f, vis=v, ik=ik, alloc=1) for f, v in cfg["display_frames"]]]
    o += track(heads, sparse, pack_display)

    o += bone_pose_bytes(nb)
    o += f32(*[0.25 * (m + 1) for m in range(nm)])
    o += bytes(cfg["ik_pose"][:nk])
    return o


RIG_CFG = dict(
    combo=2, load=1, bone=1, morphs4=(1, 2, 0, -1), group_flags=[1, 0, 1, 2],
    list_pos=7, max_frame=600,
    bone_frames={0: [0, 10, 30], 1: [0, 20], 2: [0, 5, 40, 41]},
    morph_frames={1: [0, 15, 25], 2: [0, 7]},
    ik=1, ik_pose=[2], display_frames=[(12, 0), (24, 1)],
)
CHAIN_CFG = dict(
    combo=1, load=1, bone=0, morphs4=(0, 0, 0, 0), group_flags=[1, 1, 0, 1],
    list_pos=0, max_frame=100, bone_frames={0: [0, 9], 2: [0, 12, 13]},
    morph_frames={}, ik=1, ik_pose=[], display_frames=[],
)


# ---------------------------------------------------------------------------
# Scene sections
# ---------------------------------------------------------------------------


def header(models, options, selected):
    o = b"Polygon Movie maker 0001" + b"\0" * 6
    o += i32(1280, 720, 244) + f32(30.0) + bytes(options)
    o += u8(selected, len(models))
    for _, name in models:
        o += sjis(name, 20)
    return o


def curve(i):
    # Six channels of four rows, a different value in every cell.
    return bytes((i * 11 + 7 * ch + 3 * row + 5) % 128 for ch in range(6) for row in range(4))


def camera_section(frames, state_persp=1):
    head = Key(0, distance=-45.0, eye=(0.0, 10.0, 0.0), rot=(0.0, 3.125, 0.0),
               curve=curve(0), persp=1, fov=30, sel=0)
    keys = [Key(f, distance=-45.0 + 0.5 * i, eye=(0.0, 10.0 + i, 0.0),
                rot=(0.0, 3.125, 0.25 * i), curve=curve(i + 1),
                persp=2 if i == 0 else 1, fov=30 + 5 * i, sel=1 + i % 2)
            for i, f in enumerate(frames)]
    state = f32(0.0, 10.0, 0.0, 0.25, -0.5, -45.0, 0.5, 0.75, 0.0) + u8(state_persp)
    return track([head], [keys], pack_camera) + state


def light_section(frames):
    head = Key(0, color=(0.625, 0.625, 0.625), direction=(-0.5, -1.0, 0.5), sel=0)
    keys = [Key(f, color=(0.75, 0.5, 0.25 * (i + 1)), direction=(0.5, -1.0, -0.5),
                sel=i % 3) for i, f in enumerate(frames)]
    return (track([head], [keys], pack_light)
            + f32(0.625, 0.625, 0.625, -0.5, -1.0, 0.5))


def accessory_section(selected, scroll, accs):
    """accs: (slot, list name, name, path, order, key frames, state)."""
    o = u8(selected) + i32(scroll) + u8(len(accs))
    for _, list_name, *_ in accs:
        o += sjis(list_name, 100)
    for slot, _, name, path, order, frames, s in accs:
        head = Key(0, ov=s["ov"], pm=-1, pb=0, pos=(0.0, 0.0, 0.0),
                   rot=(0.0, 0.0, 0.0), scale=1.0, shadow=1, sel=0)
        keys = [Key(f, ov=0x2D + 2 * i, pm=s["pm"], pb=i, pos=(float(i), 1.0, 2.0),
                    rot=(0.0, 0.5 * i, 0.0), scale=1.5, shadow=2 - i % 2, sel=i % 2)
                for i, f in enumerate(frames)]
        o += u8(slot) + sjis(name, 100) + sjis(path, 256) + u8(order)
        o += track([head], [keys], pack_accessory)
        o += u8(s["ov"]) + i32(s["pm"], s["pb"])
        o += f32(0.0, 0.25, 0.5, 1.25, 1.0, 2.0, 3.0) + u8(s["shadow"])
    return o


def config_section(cur, wave, avi, picture, view):
    o = i32(cur, 0, 30, 1) + u8(2, 1, 0, 3) + i32(0, 600)
    o += u8(wave[0]) + sjis(wave[1], 256)
    o += i32(avi[0], avi[1]) + f32(avi[2]) + sjis(avi[3], 256) + u32(avi[4])
    o += i32(picture[0], picture[1]) + f32(picture[2]) + sjis(picture[3], 256)
    o += u8(picture[4])
    return o + u8(*view[:3]) + f32(view[3]) + i32(view[4])


NO_WAVE = (0, "")
NO_AVI = (0, 0, 1.0, "", 0)
NO_PICTURE = (0, 0, 1.0, "", 0)
VIEW = (1, 1, 0, 30.0, 0)


def shadow_track(frames):
    head = Key(0, mode=2, distance=0.015625, sel=0)
    keys = [Key(f, mode=1, distance=0.0078125 * (i + 1), sel=1) for i, f in enumerate(frames)]
    return track([head], [keys], pack_shadow)


BASIS = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.5, 1.0, 1.5, 1.0)


def full_tail(models, accessories):
    """Every section of the tail; per-model values come in slot order."""
    n = models
    o = i32(2) + f32(0.5) + bytes([1] * n) + bytes([3] * accessories)
    o += f32(1.5) + u8(1)                                    # edge scale, blend
    o += u8(1) + f32(*[2.5 + i for i in range(n)])           # per-model edge scale
    o += u8(1) + u8(1) + f32(12.0) + i32(7) + f32(0.0, -1.0, 0.5) + u8(1)
    o += u8(1) + u8(2) + f32(0.015625) + bytes([1, 0, 2][:n] + [1] * max(0, n - 3))
    o += u8(1) + shadow_track([20])
    o += u8(1) + i32(10, 20, 30)
    o += u8(1) + u8(2)                                       # black background
    o += (u8(1) + i32(3, 2) + i32(2) + i32(1, 3, 1) + i32(2, 3, 3)
          + i32(3, 2))                                       # camera parents
    o += u8(1) + f32(*BASIS) + u8(1, 2)
    o += u8(1) + u8(5)                                       # floor
    o += u8(1) + bytes([4 + i for i in range(n)])            # display order
    return o


def multi_tail():
    o = i32(3) + f32(0.25) + bytes([1, 0, 1]) + bytes([1])
    o += f32(0.75) + u8(0)
    o += u8(1) + f32(1.25, 2.0, 3.0)
    o += u8(1) + u8(0) + f32(9.5) + i32(3) + f32(0.0, -1.0, 0.0) + u8(0)
    o += u8(1) + u8(0) + f32(0.03125) + bytes([1, 0, 1])
    return o + u8(0)


def noparent_tail(n):
    o = i32(1) + f32(0.0) + bytes([0] * n)
    o += f32(1.0) + u8(0)
    o += u8(1) + f32(1.0)
    o += u8(1) + u8(2) + f32(9.5) + i32(10) + f32(0.0, -1.0, 0.0) + u8(0)
    o += u8(1) + u8(0) + f32(0.01125) + bytes([1] * n)
    o += u8(1) + shadow_track([])
    o += u8(1) + i32(0, 0, 0)
    o += u8(1) + u8(0)
    o += u8(1) + i32(-1, 0)
    o += u8(1) + f32(*BASIS) + u8(0, 1)
    o += u8(1) + u8(7)
    return o + u8(1) + bytes([4] * n)


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------


def v1_rig():
    o = header([(3, "rig3")], [1, 0, 2, 1, 0, 1], 3)
    o += model_block(3, RIG3, "rig3", RIG_CFG)
    o += camera_section([100, 200]) + light_section([150])
    o += accessory_section(0, 0, [])
    o += config_section(20, NO_WAVE, NO_AVI, NO_PICTURE, VIEW)
    return o + full_tail(1, 0)


def v1_scene():
    acc = accessory_section(4, 3, [
        (4, "cube", "cube", "cube.x", 1, [10, 40], dict(ov=0x2C, pm=-1, pb=0, shadow=1)),
        (1, "sphere", "sphere", "sphere.x", 0, [25], dict(ov=0x4B, pm=0, pb=2, shadow=2)),
    ])
    o = header([(0, "chain8")], [0, 0, 0, 0, 0, 0], 0)
    o += model_block(0, CHAIN8, "chain8", CHAIN_CFG)
    o += camera_section([50, 120, 300], state_persp=0) + light_section([30, 90]) + acc
    return o + config_section(0, (1, "voice.wav"), (3, 4, 0.5, "", 1),
                              (5, 6, 2.0, "bg.bmp", 1), (0, 2, 1, 1000.0, 2))


def v1_multi():
    cfg5 = dict(RIG_CFG, combo=3, bone=2, group_flags=[0, 0, 1, 1])
    cfg3 = dict(RIG_CFG, combo=1, bone=0, group_flags=[1, 1, 1, 0], ik=0)
    o = header([(5, "rig3"), (1, "chain8"), (3, "rig3")], [1, 1, 1, 1, 1, 1], 1)
    o += model_block(5, RIG3, "rig3 five", cfg5)
    o += model_block(1, CHAIN8, "chain8 one", CHAIN_CFG)
    o += model_block(3, RIG3, "rig3 three", cfg3)
    o += camera_section([]) + light_section([])
    o += accessory_section(7, 0, [
        (7, "box", "box", "cube.x", 2, [5], dict(ov=0x64, pm=3, pb=1, shadow=0)),
    ])
    o += config_section(5, NO_WAVE, NO_AVI, NO_PICTURE, VIEW)
    return o + multi_tail()


def v1_noparent():
    o = header([(0, "chain8")], [1, 1, 1, 1, 1, 1], 0)
    o += model_block(0, CHAIN8, "chain8", CHAIN_CFG)
    o += camera_section([]) + light_section([]) + accessory_section(0, 0, [])
    o += config_section(0, NO_WAVE, NO_AVI, NO_PICTURE, VIEW)
    return o + noparent_tail(1)


def v1_edge():
    cfg = dict(CHAIN_CFG, free=1, group_flags=[1, 0, 1, 0, 1, 1])
    o = header([(0, "chain8")], [1, 1, 1, 1, 1, 1], 0)
    o += model_block(0, CHAIN8, "chain8", cfg)
    o += camera_section([]) + light_section([]) + accessory_section(0, 0, [])
    return o + config_section(0, NO_WAVE, NO_AVI, NO_PICTURE, VIEW)


def generate():
    return {
        "chain8.pmd": g.build_pmd(g.MODELS["chain8.pmd"]),
        "rig3.pmd": build_rig3(),
        "v1_rig.pmm": v1_rig(),
        "v1_scene.pmm": v1_scene(),
        "v1_multi.pmm": v1_multi(),
        "v1_noparent.pmm": v1_noparent(),
        "v1_edge.pmm": v1_edge(),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write the files")
    mode.add_argument("--check", action="store_true", help="compare with the files")
    args = ap.parse_args(argv)
    files = generate()
    if args.write:
        for name, data in files.items():
            (HERE / name).write_bytes(data)
        print("pmm1: wrote %d files, %d bytes" % (len(files), sum(map(len, files.values()))))
        return 0
    drift = [n for n, d in files.items()
             if not (HERE / n).is_file() or (HERE / n).read_bytes() != d]
    for n in drift:
        print("pmm1: DRIFT " + n, file=sys.stderr)
    if drift:
        return 1
    print("pmm1: %d files match" % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
