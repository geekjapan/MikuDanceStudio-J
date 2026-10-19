"""Separate measured normal/facing and material rounding in hardware lighting.

Predictions with native-measured facing are diagnostic dependency tests, not a
complete DX11 lighting replacement. Original and candidate failures are retained.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import struct

from analyze_accessory_isolation import tags, f32


def fl(value):
    return struct.unpack("<f", f32(value))[0]


def bits(value):
    return struct.unpack("<I", f32(value))[0]


def fused(a, b, c):
    # Same tested double product/add then float conversion as the diagnostic VS.
    # Not a claim of exact float FMA for all inputs.
    return fl(float(a)*float(b)+float(c))


def combine(d, a, e, ld, la, facing, mode=0):
    if mode == 1:
        d, a, e, ld, la = 1., 0., 0., 1., 0.
    if mode == 2:
        a = e = 0.
    if mode == 3:
        d = a = 0.
    if mode == 4:
        d = e = 0.
        la = -la
    if mode == 5:
        a = 0.
    if mode == 6:
        e = 0.
    scaled = fl(d*facing)
    with_emissive = fused(ld, scaled, e)
    return max(0., min(1., fused(a, la, with_emissive)))


def rows(path, count):
    with path.open(newline="") as file:
        result = list(csv.DictReader(file))
    if len(result) != count or any(None in row or any(v is None for v in row.values()) for row in result):
        raise ValueError(f"incomplete CSV: {path}")
    for row in result:
        for bit_key, value_key in (("bits", "value"), ("nativeBits", "native"), ("shaderBits", "shader"), ("candidateBits", "candidate"), ("roundedCombinedBits", "roundedCombined")):
            if bit_key in row and bits(row[value_key]) != int(row[bit_key]):
                raise ValueError(f"float value differs from bits: {path}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory
    archive = args.archive / "history_replay.reduction.draw2.state"
    state = archive.read_text().splitlines()
    material = tags(next(l for l in state if l.startswith("MATERIAL ")))
    light = tags(next(l for l in state if l.startswith("LIGHT_VALUES ")))
    source = {name: [fl(fields[f"f{k}"]) for k in range(count)] for name, fields, count in (("material", material, 17), ("light", light, 25))}
    metadata = json.loads((root / "inputs.json").read_text())
    if metadata["samples"] != 1 or metadata["repeats"] != 2 or metadata["nativeVP"] != "hardware":
        raise ValueError("unexpected native measurement mode")
    vb = (args.archive / "history_replay.reduction.draw2.vertices").read_bytes()
    ib = (args.archive / "history_replay.reduction.draw2.indices").read_bytes()
    draw = tags(state[0])
    for v in range(3):
        index = struct.unpack_from("<H", ib, (int(draw["start"])+197*3+v)*2)[0]
        expected = struct.unpack_from("<3f", vb, index*32+12)
        if struct.pack("<3f", *metadata["normals"][v]) != struct.pack("<3f", *expected):
            raise ValueError("real normal differs from source")
    independent = [[.2, .7, -.3], [-.5, .2, -.75], [.3, -.8, .4], [1, 2, -3], [-.15, .9, -.25], [.9, .1, -.6]]
    if any(struct.pack("<3f", *a) != struct.pack("<3f", *b) for a, b in zip(metadata["normals"][3:], independent)) or len(metadata["normals"]) != 9:
        raise ValueError("independent normals changed")
    stages = rows(root / "stages.csv", 9*9*4)
    probes = rows(root / "probes.csv", 9*20*4)
    materials = rows(root / "materials.csv", 6*2*3)
    axes = rows(root / "light_axes.csv", 6)
    matrix_axes = rows(root / "normal_matrix_axes.csv", 9)
    adjusted = rows(root / "normal_adjusted.csv", 9*4*4)
    s = {(int(r["case"]), int(r["stage"]), int(r["k"])): r for r in stages}
    p = {(int(r["case"]), int(r["mode"]), int(r["k"])): r for r in probes}
    adjusted_map = {(int(r["case"]), int(r["stage"]), int(r["k"])): r for r in adjusted}
    if set(adjusted_map) != {(n, stage, k) for n in range(9) for stage in (0, 1, 2, 4) for k in range(4)}:
        raise ValueError("incomplete rounded-matrix stage coordinates")
    if {(int(r["row"]), int(r["column"])) for r in matrix_axes} != {(i, j) for i in range(3) for j in range(3)}:
        raise ValueError("incomplete normal matrix coordinates")
    if len(s) != len(stages) or len(p) != len(probes):
        raise ValueError("duplicate capture coordinates")
    for row in probes+stages:
        if int(row["holdout"]) != (int(row["case"]) >= 6):
            raise ValueError("holdout membership changed")
    for row in adjusted:
        if int(row["holdout"]) != (int(row["case"]) >= 6):
            raise ValueError("rounded-matrix holdout membership changed")
    factor_differences = []
    normal_differences = []
    normal_axis_exact = {"rawTransformed": 0, "normalized": 0}
    adjusted_exact = {"rawTransformed": 0, "normalized": 0, "facing": 0, "color": 0}
    predictions = gpu_prediction_exact = native_prediction_exact = 0
    for n in range(9):
        facing_native = float(p[n, 1, 0]["native"])
        facing_gpu = float(p[n, 1, 0]["shader"])
        if bits(facing_gpu) != int(s[n, 4, 0]["bits"]):
            raise ValueError("instrumented facing differs from white-material control")
        if bits(facing_native) != bits(facing_gpu):
            factor_differences.append({"case": n, "holdout": n >= 6, "nativeBits": bits(facing_native), "shaderBits": bits(facing_gpu)})
        adjusted_exact["facing"] += int(adjusted_map[n, 4, 0]["bits"]) == bits(facing_native)
        for k in range(3):
            adjusted_exact["color"] += adjusted_map[n, 0, k]["bits"] == p[n, 0, k]["nativeBits"]
        for stage, first_mode in ((1, 14), (2, 7)):
            for k in range(3):
                plus, minus = (float(p[n, first_mode+k*2+sign, 0]["native"]) for sign in range(2))
                value = plus-minus
                name = "normalized" if stage == 2 else "rawTransformed"
                adjusted_exact[name] += bits(value) == int(adjusted_map[n, stage, k]["bits"])
                normal_axis_exact[name] += bits(value) == int(s[n, stage, k]["bits"])
                if bits(value) != int(s[n, stage, k]["bits"]):
                    normal_differences.append({"case": n, "stage": name, "component": k,
                                               "nativeAxisBits": bits(value), "shaderBits": int(s[n, stage, k]["bits"])})
        for mode in range(7):
            for k in range(3):
                d, a, e = (source["material"][k+off] for off in (0, 4, 12))
                ld, la = source["light"][k], source["light"][k+8]
                predicted_native = combine(d, a, e, ld, la, facing_native, mode)
                predicted_gpu = combine(d, a, e, ld, la, facing_gpu, mode)
                row = p[n, mode, k]
                predictions += 1
                native_prediction_exact += bits(predicted_native) == int(row["nativeBits"])
                gpu_prediction_exact += bits(predicted_gpu) == int(row["candidateBits"])
    # Independent, predetermined material inputs. Axial normals keep facing
    # exact, so this checks color arithmetic without fitting normal errors.
    palette = [[.03125, .125, .0625, 3.25, -.25], [.073, .19, .027, 1.37, -.17], [.21, .09, .041, .73, .23],
               [.37, .061, .003, 1.13, -.083], [.017, .137, .029, 7.19, -.071], [.29, .41, .13, .91, -.19]]
    material_exact = cpu_gpu_exact = production_material_differences = 0
    for row in materials:
        n, k, normalize = (int(row[key]) for key in ("case", "k", "normalize"))
        if int(row["holdout"]) != (n >= 3):
            raise ValueError("material holdout membership changed")
        coefficients = [float(row[key]) for key in ("diffuse", "ambient", "emissive", "lightDiffuse", "lightAmbient")]
        if [bits(v) for v in coefficients] != [bits(v) for v in palette[(n+k) % 6]]:
            raise ValueError("fixed material palette changed")
        factor = 1. if normalize else .75
        if int(row["nativeFactorBits"]) != bits(factor) or int(row["shaderFactorBits"]) != bits(factor):
            raise ValueError("independent material facing is not exact")
        predicted = combine(*coefficients, factor)
        cpu_gpu_exact += bits(predicted) == int(row["candidateBits"])
        material_exact += row["nativeBits"] == row["candidateBits"]
        production_material_differences += row["nativeBits"] != row["shaderBits"]
    if gpu_prediction_exact != predictions or cpu_gpu_exact != len(materials):
        raise ValueError("actual candidate GPU output differs from its declared arithmetic")
    report = {"sourceStateSHA256": hashlib.sha256(archive.read_bytes()).hexdigest(), "cases": 9, "modes": 20,
              "stageValues": len(stages), "nativeChannels": len(probes), "lightAxisChannelsExact": sum(r["nativeBits"] == r["shaderBits"] for r in axes),
              "normalAxisDifferences": normal_differences, "facingDifferences": factor_differences,
              "normalAxisExact": normal_axis_exact, "normalAxisTotalPerStage": 27,
              "normalMatrixAxes": {"nativePortableExact": sum(r["nativeBits"] == r["shaderBits"] for r in matrix_axes),
                                   "nativeRoundedCombinedExact": sum(r["nativeBits"] == r["roundedCombinedBits"] for r in matrix_axes), "total": 9},
              "roundedMatrixGpuVsNative": adjusted_exact,
              "materialOrderWithMeasuredNativeFacing": {"exact": native_prediction_exact, "total": predictions},
              "candidateGpuVsFixedCpu": {"exact": gpu_prediction_exact, "total": predictions},
              "independentMaterialOrder": {"exact": material_exact, "total": len(materials), "calibration": 18, "holdout": 18, "productionDifferentChannels": production_material_differences},
              "originalDifferentChannels": sum(r["nativeBits"] != r["shaderBits"] for r in probes),
              "candidateDifferentChannels": sum(r["nativeBits"] != r["candidateBits"] for r in probes),
              "applicationActivation": False}
    (root / "analysis.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))
    return 0 if native_prediction_exact == predictions and material_exact == len(materials) else 32


if __name__ == "__main__":
    raise SystemExit(main())
