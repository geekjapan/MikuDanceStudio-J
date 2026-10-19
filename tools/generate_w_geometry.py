"""Choose independent four-term W fixtures using CPU discrimination only."""
import argparse
import json
from pathlib import Path
import random
import struct
from generate_sensitive_depth_matrices import f32, dot, RULES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rng = random.Random(20261004)
    cases = []
    for attempt in range(100000):
        column = [f32(rng.uniform(-.6, .6)) for _ in range(3)] + [f32(rng.uniform(3.9, 4.1))]
        if any(abs(v) < .05 for v in column[:3]):
            continue
        shape = f32(rng.uniform(.85, .98))
        objects = [[-shape, -shape, f32(rng.uniform(.2, 1.)), 1.],
                   [-shape, shape, f32(rng.uniform(.2, 1.)), 1.],
                   [shape, -shape, f32(rng.uniform(.2, 1.)), 1.]]
        outputs = {rule: [dot(p, column, rule) for p in objects] for rule in RULES}
        if len({tuple(values) for values in outputs.values()}) < 3:
            continue
        if outputs["sequential"] == outputs["paired"] or outputs["sequential"] == outputs["fused"]:
            continue
        # CPU-only conservative coverage and depth checks for all candidates.
        covered = True
        for values in outputs.values():
            if not all(3.25 < w < 4.9 for w in values):
                covered = False
                break
            screen = [((3.5*p[0]/w+1)*32, (1-3.5*p[1]/w)*32) for p, w in zip(objects, values)]
            a, b, c = screen
            den = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            for x, y in ((36, 46), (20, 42), (28, 44)):
                u = ((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/den
                v = ((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/den
                if min(u, v, 1-u-v) < .04:
                    covered = False
        if not covered:
            continue
        matrix = [0.] * 16
        matrix[0] = matrix[5] = 3.5
        matrix[14] = 3. # Clip Z is exact/constant; all four terms contribute only to W.
        for index, value in zip((3, 7, 11, 15), column):
            matrix[index] = value
        cases.append({"id": len(cases), "split": "calibration" if len(cases) < 6 else "holdout",
                      "attempt": attempt, "matrix": matrix, "objects": objects, "cpuW": outputs})
        if len(cases) == 12:
            break
    if len(cases) != 12:
        raise ValueError("insufficient CPU-discriminating geometry")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(b"WGEOM001"+struct.pack("<I", 12)+b"".join(
        struct.pack("<28f", *(case["matrix"] + [v for p in case["objects"] for v in p])) for case in cases))
    args.output.with_suffix(".json").write_text(json.dumps({"seed": 20261004,
        "selection": "CPU W bit discrimination, visibility and coverage only; no GPU residuals.",
        "points": [[36, 46], [20, 42], [28, 44]], "cases": cases}, indent=2)+"\n")
    print(f"cases=12 calibration=6 holdout=6 output={args.output}")


if __name__ == "__main__":
    main()
