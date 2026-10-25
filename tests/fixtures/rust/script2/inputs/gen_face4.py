"""Writes face4.pmx: morph4.pmx of tools/fixtures/gen_fixtures.py with one
morph on each of the four morph panels (1 eyebrow, 2 eye, 3 lip, 4 other).
The facial menus 225, 226, 228 and 231 select morphs by MorphRecord::type,
which the PMX loader fills with the morph kind (src/model/pmx_load.cpp), not
the panel: 231 takes kind 1 (vertex), 228 kind 2 (bone), 225 and 226 kind 3
(UV). So the eyebrow and eye morphs are vertex morphs, the lip morph あ is a
UV morph, and the other morph 照れ is a bone morph, and each menu finds keys.

    python3 -I tests/fixtures/rust/script2/inputs/gen_face4.py --write
    python3 -I tests/fixtures/rust/script2/inputs/gen_face4.py --check
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4] / "tools" / "fixtures"))
import gen_fixtures as g  # noqa: E402

# (name, English name, panel, kind, [(index, values)]). build_pmx writes
# every morph as a vertex morph with one index and the values as floats, so a
# UV offset (vertex, 4 floats) and a bone offset (bone, translation and
# quaternion) come out right once the kind byte is patched (both index sizes
# are 1 byte in morph4.pmx).
MORPHS = [
    ("真面目", "Serious", 1, 1, [(2, (0.0, 0.125, 0.0)), (3, (0.0, 0.125, 0.0))]),
    ("まばたき", "Blink", 2, 1, [(0, (0.0, -0.25, 0.0)), (1, (0.0, -0.25, 0.0))]),
    ("あ", "A", 3, 3, [(2, (0.0, 0.25, 0.0, 0.0)), (3, (0.0, 0.25, 0.0, 0.0))]),
    ("照れ", "Shy", 4, 2, [(1, (0.0, 0.25, 0.0, 0.0, 0.0, 0.0, 1.0))]),
]


def build():
    # The "file" key stays morph4.pmx: build_pmx keys the vertex weights and
    # the bone tails on it.
    morphs = [(jp, en, panel, offsets) for jp, en, panel, _, offsets in MORPHS]
    data = bytearray(g.build_pmx(dict(g.morph_model(), name="face4", name_en="face4",
                                      comment="Synthetic fixture: one morph per panel",
                                      morphs=morphs)))
    for jp, en, panel, kind, offsets in MORPHS:
        head = g.utf16(jp) + g.utf16(en) + g.u8(panel, 1) + g.i32(len(offsets))
        at = data.find(head)
        assert at >= 0 and data.find(head, at + 1) < 0
        data[at + len(head) - 5] = kind
    return bytes(data)


def main():
    out = HERE / "face4.pmx"
    data = build()
    if sys.argv[1:] == ["--write"]:
        out.write_bytes(data)
    elif sys.argv[1:] == ["--check"]:
        if not out.exists() or out.read_bytes() != data:
            sys.exit("face4.pmx differs from gen_face4.py")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
