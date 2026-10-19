"""Generate asset-free cancellation fixtures, without looking at GPU results."""
import argparse
import json
from pathlib import Path
import random
import struct


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def dot(a, b, rule):
    products = [f32(x*y) for x, y in zip(a, b)]
    if rule == "double":
        return f32(sum(x*y for x, y in zip(a, b)))
    if rule == "fused":
        value = 0.0
        for x, y in zip(a, b):
            # Float32 operands' product and sum are exact enough in binary64
            # for these bounded generated values; C++ validates via std::fma.
            value = f32(x*y+value)
        return value
    if rule == "paired":
        return f32(f32(products[0]+products[1])+f32(products[2]+products[3]))
    value = 0.0
    for product in products:
        value = f32(value+product)
    return value


def multiply(a, b, rule):
    return [dot(a[row*4:row*4+4], b[col::4], rule) for row in range(4) for col in range(4)]


IDENTITY = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]
RULES = ("sequential", "double", "paired", "fused")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--perspective", action="store_true")
    args = parser.parse_args()
    rng = random.Random(20261003)
    cases = []
    for attempt in range(20000):
        world, view, projection = [list(IDENTITY) for _ in range(3)]
        world[12:15] = [f32(rng.uniform(-12000, 12000)) for _ in range(3)]
        view[2], view[6], view[10] = [f32(rng.uniform(-.002, .002)), f32(rng.uniform(-.002, .002)), f32(rng.uniform(.002, .008))] if not args.perspective else [f32(rng.uniform(-.4, .4)), f32(rng.uniform(-.4, .4)), f32(rng.uniform(.2, .8))]
        view[12], view[13] = -world[12], -world[13]
        view[14] = f32((4 if args.perspective else .5)-sum(world[12+k]*view[2+k*4] for k in range(3)))
        # Non-power-of-two scaling makes coefficient combination order observable.
        if args.perspective:
            near, far = f32(rng.uniform(.7, 1.1)), f32(rng.uniform(25, 80))
            projection[0] = projection[5] = 4.
            projection[10] = f32(far/(far-near))
            projection[14] = f32(-near*projection[10])
            projection[11], projection[15] = 1., 0.
        else:
            projection[10] = f32(rng.uniform(.75, 1.25))
            projection[14] = f32(.5-.5*projection[10])
        variants = [multiply(multiply(world, view, rule), projection, rule) for rule in RULES]
        variants += [multiply(world, multiply(view, projection, rule), rule) for rule in RULES[:2]]
        depths = [f32(m[14]/m[15]) for m in variants]
        if len(set(depths)) < 3 or max(depths)-min(depths) < (2**-21 if not args.perspective else 2**-20):
            continue
        if not all(all(.2 < (m[14]+x*m[2]+y*m[6])/(m[15]+x*m[3]+y*m[7]) < .95
            and m[15]+x*m[3]+y*m[7]>0 for x,y in ((-.8,-.8),(-.8,.8),(.8,-.8))) for m in variants):
            continue
        cases.append({"id": len(cases), "split": "calibration" if len(cases)<6 else "holdout",
                      "attempt": attempt, "world": world, "view": view, "projection": projection,
                      "candidateCenterDepths": depths})
        if len(cases) == 12:
            break
    if len(cases) != 12:
        raise ValueError("insufficient discriminating fixtures")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes((b"SDEP0002" if args.perspective else b"SDEP0001")+struct.pack("<I", len(cases))+
        b"".join(struct.pack("<48f", *(c["world"]+c["view"]+c["projection"])) for c in cases))
    args.output.with_suffix(".json").write_text(json.dumps({"seed": 20261003, "perspective": args.perspective,
        "selection": "CPU coefficient discrimination and visible depth bounds only; GPU results are never used to choose cases.",
        "rules": RULES, "cases": cases}, indent=2)+"\n")
    print(f"cases={len(cases)} calibration=6 holdout=6 output={args.output}")


if __name__ == "__main__":
    main()
