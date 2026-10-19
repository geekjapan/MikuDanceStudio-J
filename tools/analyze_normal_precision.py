"""Validate fixed-matrix normal dot/normalization hardware observations.

All comparisons are bit-exact. Native signed-axis responses are controlled
raster measurements, not captures of private fixed-function vertex registers.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import struct

from analyze_accessory_isolation import tags, fnv, f32
from generate_sensitive_depth_matrices import dot


def fl(x):
    return struct.unpack("<f", f32(x))[0]


def bits(x):
    return struct.unpack("<I", f32(x))[0]


def load(path, keys, expected):
    with path.open(newline="") as file:
        data = list(csv.DictReader(file))
    if len(data) != len(expected) or any(None in r or any(v is None for v in r.values()) for r in data):
        raise ValueError(f"incomplete CSV: {path}")
    mapped = {tuple(int(r[k]) for k in keys): r for r in data}
    if set(mapped) != set(expected):
        raise ValueError(f"incomplete/duplicate coordinates: {path}")
    for r in data:
        if bits(r["value"]) != int(r["bits"]) or not math.isfinite(float(r["value"])):
            raise ValueError(f"float bits/value mismatch: {path}")
        if "holdout" in r and int(r["holdout"]) != (int(r["case"]) >= 6):
            raise ValueError("holdout membership changed")
    return mapped


def exact(a, b):
    return int(a["bits"]) == int(b["bits"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--previous", type=Path, required=True, help="preceding lighting-rounding observations")
    args = parser.parse_args()
    root = args.directory
    manifest = json.loads((root / "manifest.json").read_text())
    expected_manifest = {"cases": 15, "holdoutCases": 9, "samples": 1, "nativeHardwareVP": True,
                         "nativeSpatialConstant": True, "nativeRepeats": 3, "gpuRepeats": 2, "matrixPreflight": True, "productionActivation": False}
    if manifest != expected_manifest:
        raise ValueError("unexpected measurement preflight")
    inputs = load(root / "inputs.csv", ("case", "k"), [(n, k) for n in range(15) for k in range(3)])
    matrix = load(root / "matrix.csv", ("row", "column"), [(i, j) for i in range(3) for j in range(3)])
    fixed = load(root / "fixed.csv", ("case", "stage", "k"), [(n, s, k) for n in range(15) for s in range(3) for k in range(4)])
    native = load(root / "native_explicit.csv", ("case", "stage", "k"), [(n, s, k) for n in range(15) for s in range(5) for k in range(4)])
    gpu = load(root / "gpu.csv", ("case", "policy", "stage", "k"), [(n, p, s, k) for n in range(15) for p in range(6) for s in range(7) for k in range(4)])
    coordinates = [(n, path, stage, k) for n in range(15) for path, stages in ((0, range(5)), (1, range(4)), (2, [1])) for stage in stages for k in range(4)]
    shared = load(root / "shared_raw.csv", ("case", "path", "stage", "k"), coordinates)
    state_path = args.archive / "history_replay.reduction.draw2.state"
    lines = state_path.read_text().splitlines()
    draw = tags(lines[0])
    if any(int(draw[k]) != v for k, v in {"fvf": 274, "stride": 32, "count": 232, "start": 6, "base": 0, "offset": 0}.items()):
        raise ValueError("unexpected archived geometry")
    vb = (args.archive / "history_replay.reduction.draw2.vertices").read_bytes()
    ib = (args.archive / "history_replay.reduction.draw2.indices").read_bytes()
    normals = [[float(inputs[n, k]["value"]) for k in range(3)] for n in range(15)]
    for n in range(3):
        index = struct.unpack_from("<H", ib, (6+197*3+n)*2)[0]
        if struct.pack("<3f", *normals[n]) != vb[index*32+12:index*32+24]:
            raise ValueError("real normal changed")
    independent = [[.2, .7, -.3], [-.5, .2, -.75], [.3, -.8, .4], [1, 2, -3], [-.15, .9, -.25], [.9, .1, -.6],
                   [.13, .37, -.91], [-.83, .11, -.47], [.007, -.015, .019], [.25, 1.75, -2.5], [-1.33, -.27, .51], [.61, .73, -.89]]
    if any(struct.pack("<3f", *a) != struct.pack("<3f", *b) for a, b in zip(normals[3:], independent)):
        raise ValueError("fixed independent normals changed")
    with (args.previous / "normal_matrix_axes.csv").open(newline="") as file:
        preceding_matrix = list(csv.DictReader(file))
    if len(preceding_matrix) != 9:
        raise ValueError("incomplete preceding normal matrix")
    for r in preceding_matrix:
        key = int(r["row"]), int(r["column"])
        if matrix[key]["bits"] != r["nativeBits"] or matrix[key]["bits"] != r["roundedCombinedBits"]:
            raise ValueError("normal matrix not held fixed")
    with (args.previous / "normal_adjusted.csv").open(newline="") as file:
        adjusted = {(int(r["case"]), int(r["stage"]), int(r["k"])): r for r in csv.DictReader(file)}
    with (args.previous / "probes.csv").open(newline="") as file:
        preceding_native = {(int(r["case"]), int(r["mode"]), int(r["k"])): r for r in csv.DictReader(file)}
    for n in range(9):
        for s, old in ((0, 1), (1, 2), (5, 4)):
            for k in range(3 if s < 2 else 1):
                if not exact(gpu[n, 0, s, k], adjusted[n, old, k]):
                    raise ValueError("baseline stage instrumentation changed preceding output")
        for s, mode in ((0, 14), (1, 7)):
            for k in range(3):
                plus = float(preceding_native[n, mode+2*k, 0]["native"])
                minus = float(preceding_native[n, mode+2*k+1, 0]["native"])
                if bits(plus-minus) != int(fixed[n, s, k]["bits"]):
                    raise ValueError("reusable native renderer changed preceding axis response")
        if fixed[n, 2, 0]["bits"] != preceding_native[n, 1, 0]["nativeBits"]:
            raise ValueError("native facing changed")
    instructions = []
    for stage in range(5):
        text = (root / f"native-stage{stage}.asm").read_text().rstrip("\x00")
        dp3 = len(re.findall(r"^\s*dp3\s", text, re.M))
        rsq = len(re.findall(r"^\s*rsq\s", text, re.M))
        nrm = len(re.findall(r"^\s*nrm\s", text, re.M))
        # The facing-only compiler folds dot/rsq/mul into legacy NRM.
        # The separately observed length/reciprocal/normal stages retain the
        # literal instructions and independently verify that boundary.
        if "vs_3_0" not in text or dp3 != (3 if stage == 0 else 4) or rsq != (1 if stage in (2, 3) else 0) or nrm != (1 if stage == 4 else 0):
            raise ValueError("native shader no longer exposes intended dp3/rsq chain")
        instructions.append({"stage": stage, "dp3": dp3, "rsq": rsq, "nrm": nrm})
    # CPU rule is fixed. Products/sums round at every step (fused X,Y,Z),
    # validated against actual GPU values, never substituted as measurements.
    cpu_verified = 0
    reciprocal_math_differences = []
    length_cpu_hypotheses = {"fusedXYZ": 0, "separateFloatXYZ": 0, "doubleSumThenFloat": 0}
    for n in range(15):
        obj = normals[n]+[0.]
        raw = []
        for k in range(3):
            column = [float(matrix[i, k]["value"]) for i in range(3)]+[0.]
            expected = dot(obj, column, "fused")
            if bits(expected) != int(native[n, 0, k]["bits"]):
                raise ValueError("native dp3 differs from fused X/Y/Z definition")
            for p in range(1, 6):
                if bits(expected) != int(gpu[n, p, 0, k]["bits"]):
                    raise ValueError("actual GPU normal transform differs from fixed CPU definition")
                cpu_verified += 1
            raw.append(expected)
        length = dot(raw+[0.], raw+[0.], "fused")
        alternatives = {"fusedXYZ": length, "separateFloatXYZ": dot(raw+[0.], raw+[0.], "sequential"),
                        "doubleSumThenFloat": dot(raw+[0.], raw+[0.], "double")}
        for name, value in alternatives.items():
            length_cpu_hypotheses[name] += bits(value) == int(native[n, 1, 0]["bits"])
        if bits(length) != int(native[n, 1, 0]["bits"]):
            raise ValueError("native squared length differs from declared fused dot")
        for p in range(1, 6):
            if bits(length) != int(gpu[n, p, 2, 0]["bits"]):
                raise ValueError("GPU squared length differs from native on fixed raw input")
        reciprocal = float(native[n, 2, 0]["value"])
        for k in range(3):
            if bits(fl(raw[k]*reciprocal)) != int(native[n, 3, k]["bits"]):
                raise ValueError("native normalization multiply boundary changed")
            for p in range(1, 6):
                value = fl(raw[k]*float(gpu[n, p, 3, 0]["value"]))
                if bits(value) != int(gpu[n, p, 1, k]["bits"]):
                    raise ValueError("GPU normalization differs from observed multiply/rsqrt stages")
        mathematical = fl(1/math.sqrt(length))
        if bits(mathematical) != int(gpu[n, 4, 3, 0]["bits"]):
            raise ValueError("tested double refinement differs from rounded mathematical result")
        if bits(mathematical) != bits(reciprocal):
            reciprocal_math_differences.append({"case": n, "holdout": n >= 6, "nativeRsqrtBits": bits(reciprocal), "roundedMathematicalBits": bits(mathematical)})
    shared_exact = {"raw": 0, "length": 0, "reciprocal": 0, "normalized": 0}
    for n in range(15):
        for stage, name in enumerate(shared_exact):
            for k in range(3):
                if not exact(shared[n, 0, stage, k], shared[n, 1, stage, k]):
                    raise ValueError("same raw input disagrees across APIs")
                if not exact(shared[n, 0, stage, k], native[n, stage, k]):
                    raise ValueError("raw bypass changed original programmable stage")
                shared_exact[name] += 1
        for k in range(3):
            if not exact(shared[n, 2, 1, k], native[n, 3, k]):
                raise ValueError("identity-world fixed-function normalization differs from shared programmable input")
    with (root / "toward.csv").open(newline="") as file:
        toward = list(csv.DictReader(file))
    if len(toward) != 3 or [int(r["k"]) for r in toward] != [0, 1, 2]:
        raise ValueError("incomplete light-vector observations")
    for r in toward:
        if bits(r["native"]) != int(r["nativeBits"]) or bits(r["explicitInput"]) != int(r["explicitInputBits"]):
            raise ValueError("light vector bits/value disagree")
    policies = {}
    for p in range(6):
        policies[p] = {"rawExact": sum(exact(gpu[n, p, 0, k], fixed[n, 0, k]) for n in range(15) for k in range(3)),
                       "normalizedExact": sum(exact(gpu[n, p, 1, k], fixed[n, 1, k]) for n in range(15) for k in range(3)),
                       "lengthExact": sum(exact(gpu[n, p, 2, 0], native[n, 1, 0]) for n in range(15)),
                       "reciprocalExact": sum(exact(gpu[n, p, 3, 0], native[n, 2, 0]) for n in range(15)),
                       "facingExact": sum(exact(gpu[n, p, 5, 0], fixed[n, 2, 0]) for n in range(15)),
                       "holdoutNormalizedExact": sum(exact(gpu[n, p, 1, k], fixed[n, 1, k]) for n in range(6, 15) for k in range(3))}
    native_controls = {"raw": sum(exact(native[n, 0, k], fixed[n, 0, k]) for n in range(15) for k in range(3)),
                       "normalized": sum(exact(native[n, 3, k], fixed[n, 1, k]) for n in range(15) for k in range(3)),
                       "facing": sum(exact(native[n, 4, 0], fixed[n, 2, 0]) for n in range(15))}
    if native_controls != {"raw": 45, "normalized": 45, "facing": 15}:
        raise ValueError("explicit native shader does not reproduce fixed-function observations")
    report = {"sourceVertexHash": fnv(vb), "sourceIndexHash": fnv(ib), "sourceStateSHA256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
              "matrixHeldNativeExact": 9, "nativeInstructions": instructions, "cases": 15, "holdoutCases": 9,
              "nativeExplicitVsFixed": native_controls, "actualGpuFusedRawCpuValuesVerified": cpu_verified,
              "squaredLengthCpuHypothesesExact": length_cpu_hypotheses,
              "sharedRawExact": shared_exact, "policies": policies, "refinedVsMathematicalExact": 15,
              "nativeRsqrtVsMathematicalDifferences": reciprocal_math_differences,
              "lightAxisObservationDifferences": sum(r["nativeBits"] != r["explicitInputBits"] for r in toward),
              "nativeRepeats": 3, "gpuRepeats": 2, "fullSceneAccepted": False, "productionActivation": False}
    (root / "analysis.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))
    return 0 if all(policies[p]["rawExact"] == 45 and policies[p]["normalizedExact"] == 45 and policies[p]["facingExact"] == 15 for p in (1, 2, 3)) else 32


if __name__ == "__main__":
    raise SystemExit(main())
