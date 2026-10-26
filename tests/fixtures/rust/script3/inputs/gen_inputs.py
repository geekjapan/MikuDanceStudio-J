"""Writes the inputs of the script3 scripts:

  lips.pmd   chain8.pmd of tools/fixtures/gen_fixtures.py with a base morph
             and the lip sync morphs あ, い, う, お (lip panel, with English
             names), all four in the facial display list. The VSQ lip sync
             needs the four (src/io/vsq_load.cpp), and the English name
             dialog edits morph names only on a model with facial frames.
  tri2.x     ../../script/inputs/tri.x under another name, so a scene holds
             two accessories that the accessory combo tells apart.
  tri2.vac   a .vac that names tri2.x with a scale, position, rotation, and
             the shadow off.
  toonx.bmp  a 2x2 24-bit BMP for the toon texture dialog, which accepts a
             name only when the texture loads from the model's folder.

    python3 -I tests/fixtures/rust/script3/inputs/gen_inputs.py --write
    python3 -I tests/fixtures/rust/script3/inputs/gen_inputs.py --check
"""
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4] / "tools" / "fixtures"))
import gen_fixtures as g  # noqa: E402

# (name, English name, [(vertex, offset)]) on the lip panel (3). The base
# morph holds the vertices; the others index into it.
LIP_MORPHS = [
    ("あ", "a", [(0, (0.0, -0.25, 0.0)), (1, (0.0, -0.25, 0.0))]),
    ("い", "i", [(0, (-0.125, 0.0, 0.0)), (1, (0.125, 0.0, 0.0))]),
    ("う", "u", [(0, (0.125, 0.0, 0.0)), (1, (-0.125, 0.0, 0.0))]),
    ("お", "o", [(0, (0.0, -0.125, 0.0)), (1, (0.0, -0.125, 0.0))]),
]
BASE_VERTICES = [14, 15]  # the top edge of the strip


def build_lips_pmd():
    m = dict(g.chain_model("lips.pmd", False, None), name="lips", name_en="lips",
             comment="Synthetic fixture: chain8 with lip morphs")
    o = bytearray(b"Pmd" + g.f32(1.0))
    o += g.sjis(m["name"], 20) + g.sjis(m["comment"], 256)
    o += g.u32(len(m["verts"]))
    for pos, bone in m["verts"]:
        o += g.f32(*pos, 0.0, 0.0, 1.0, pos[0] + 0.5, pos[1] / 8.0)
        o += g.u16(bone, bone) + g.u8(100, 0)
    o += g.u32(len(m["indices"])) + g.u16(*m["indices"])
    o += g.u32(1)
    o += g.f32(0.75, 0.75, 0.75, 1.0, 5.0, 0.5, 0.5, 0.5, 0.25, 0.25, 0.25)
    o += g.u8(0, 1) + g.u32(len(m["indices"])) + g.sjis(m["texture"], 20)
    bones = m["bones"]
    o += g.u16(len(bones))
    for i, b in enumerate(bones):
        tail = i + 1 if i + 1 < len(bones) else 0
        o += g.sjis(b["jp"], 20) + g.i16(b["parent"]) + g.u16(tail)
        o += g.u8(1 if b["movable"] else 0) + g.u16(0) + g.f32(*b["pos"])
    o += g.u16(0)  # IK chains
    o += g.u16(1 + len(LIP_MORPHS))
    o += g.sjis("base", 20) + g.u32(len(BASE_VERTICES)) + g.u8(0)
    for v in BASE_VERTICES:
        pos = m["verts"][v][0]
        o += g.u32(v) + g.f32(*pos)
    for jp, _, offsets in LIP_MORPHS:
        o += g.sjis(jp, 20) + g.u32(len(offsets)) + g.u8(3)
        for index, d in offsets:
            o += g.u32(index) + g.f32(*d)
    o += g.u8(len(LIP_MORPHS))
    for i in range(len(LIP_MORPHS)):
        o += g.u16(i + 1)
    o += g.u8(len(m["groups"]))
    for jp, _, _ in m["groups"]:
        o += g.sjis(jp, 50)
    frames = [(bone, n + 1) for n, (_, _, members) in enumerate(m["groups"])
              for bone in members]
    o += g.u32(len(frames))
    for bone, n in frames:
        o += g.u16(bone) + g.u8(n)
    o += g.u8(1)  # English section present
    o += g.sjis(m["name_en"], 20) + g.sjis(m["comment"], 256)
    for b in bones:
        o += g.sjis(b["en"], 20)
    for _, en, _ in LIP_MORPHS:
        o += g.sjis(en, 20)
    for _, en, _ in m["groups"]:
        o += g.sjis(en, 50)
    for i in range(10):
        o += g.sjis("toon%02d.bmp" % (i + 1), 100)
    o += g.u32(len(m["rigids"]))
    for r in m["rigids"]:
        o += g.sjis(r["jp"], 20) + g.i16(r["bone"]) + g.u8(r["group"])
        o += g.u16(r["mask"]) + g.u8(r["shape"])
        o += g.f32(*r["size"], *r["pos"], *r["rot"], r["mass"], r["lin"],
                   r["ang"], r["rest"], r["fric"]) + g.u8(r["mode"])
    o += g.u32(len(m["joints"]))
    for j in m["joints"]:
        o += g.sjis(j["jp"], 20) + g.u32(j["a"], j["b"])
        o += g.f32(*j["pos"], *j["rot"], *j["pos_min"], *j["pos_max"],
                   *j["rot_min"], *j["rot_max"], *j["spring_pos"],
                   *j["spring_rot"])
    return bytes(o)


def build_bmp():
    # Rows bottom up, 3 bytes per pixel padded to 4 bytes per row.
    rows = b"".join(bytes([0, 0, 255, 255, 255, 255, 0, 0]) for _ in range(2))
    header = b"BM" + struct.pack("<IHHI", 14 + 40 + len(rows), 0, 0, 14 + 40)
    info = struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 24, 0, len(rows), 2835, 2835, 0, 0)
    return header + info + rows


def outputs():
    tri = (HERE.parents[1] / "script" / "inputs" / "tri.x").read_bytes()
    vac = b"tri2\r\ntri2.x\r\n1.5\r\n1.0,2.0,-3.0\r\n0.5,0.25,0.0\r\n\r\n1\r\n"
    return {
        "lips.pmd": build_lips_pmd(),
        "tri2.x": tri,
        "tri2.vac": vac,
        "toonx.bmp": build_bmp(),
    }


def main():
    if sys.argv[1:] not in (["--write"], ["--check"]):
        sys.exit(__doc__)
    for name, data in outputs().items():
        out = HERE / name
        if sys.argv[1] == "--write":
            out.write_bytes(data)
        elif not out.exists() or out.read_bytes() != data:
            sys.exit("%s differs from gen_inputs.py" % name)


if __name__ == "__main__":
    main()
