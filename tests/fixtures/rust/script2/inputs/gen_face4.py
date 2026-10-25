"""Writes face4.pmx: morph4.pmx of tools/fixtures/gen_fixtures.py with one
vertex morph on each of the four morph panels (1 eyebrow, 2 eye, 3 lip,
4 other), so the facial menus 226, 228 and 231 all find keys to delete.

    python3 -I tests/fixtures/rust/script2/inputs/gen_face4.py --write
    python3 -I tests/fixtures/rust/script2/inputs/gen_face4.py --check
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4] / "tools" / "fixtures"))
import gen_fixtures as g  # noqa: E402

MORPHS = [  # (name, English name, panel, [(vertex, (dx, dy, dz))])
    ("真面目", "Serious", 1, [(2, (0.0, 0.125, 0.0)), (3, (0.0, 0.125, 0.0))]),
    ("まばたき", "Blink", 2, [(0, (0.0, -0.25, 0.0)), (1, (0.0, -0.25, 0.0))]),
    ("あ", "A", 3, [(2, (0.0, -0.5, 0.0)), (3, (0.0, -0.5, 0.0))]),
    ("照れ", "Shy", 4, [(0, (0.125, 0.0, 0.0)), (1, (-0.125, 0.0, 0.0))]),
]


def build():
    # The "file" key stays morph4.pmx: build_pmx keys the vertex weights and
    # the bone tails on it.
    return g.build_pmx(dict(g.morph_model(), name="face4", name_en="face4",
                            comment="Synthetic fixture: one morph per panel",
                            morphs=MORPHS))


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
