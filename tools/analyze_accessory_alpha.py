"""Analyze alpha observations, retaining incomplete runs as partial evidence."""
import argparse
import csv
import json
import math
import struct
from pathlib import Path


def load(root, name):
    path = root / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def repeat_exact(rows, keys):
    grouped = {}
    for row in rows:
        key = tuple(row[k] for k in keys)
        grouped.setdefault(key, []).append(row)
    return bool(grouped) and all(len(group) == 3 and {r["repeat"] for r in group} == {"0", "1", "2"}
        and all({k: v for k, v in r.items() if k != "repeat"} ==
                {k: v for k, v in group[0].items() if k != "repeat"} for r in group)
        for group in grouped.values())


def analyze(root):
    floats = load(root, "float_stages.csv")
    byte_rows = load(root, "byte_controls.csv")
    constants = load(root, "constant_alpha.csv")
    summary = root / "summary.txt"
    complete = summary.exists() and len(floats) == 162 and len(byte_rows) == 72 and len(constants) == 225
    index = {(r["mode"], r["repeat"], r["point"]): r for r in floats}
    points = []
    for p in range(6):
        key = str(p)
        sample = index.get(("sample0", "0", key))
        product = index.get(("alpha_product", "0", key))
        fixed = index.get(("fixed_function_float", "0", key))
        diffuse = index.get(("diffuse", "0", key))
        if not all((sample, product, fixed, diffuse)):
            continue
        alpha = float(product["dx9Alpha"])
        scaled = f32(alpha * 255)
        rounded = math.floor(f32(scaled + .5))
        points.append({"point": p, "x": int(sample["x"]), "y": int(sample["y"]),
            "sampleAlpha": float(sample["dx9Alpha"]), "materialAlpha": .5,
            "interpolatedDiffuseAlpha": float(diffuse["dx9Alpha"]),
            "productAlpha": alpha, "byteScaleFloat32": scaled, "nearestByteCandidate": rounded,
            "floorByteCandidate": math.floor(scaled), "normalizedRef1Candidate": alpha >= f32(1 / 255),
            "sampleBitsExact": sample["dx9AlphaBits"] == sample["dx11AlphaBits"],
            "diffuseBitsExact": diffuse["dx9AlphaBits"] == diffuse["dx11AlphaBits"],
            "productBitsExact": product["dx9AlphaBits"] == product["dx11AlphaBits"],
            "fixedProductBitsExact": fixed["dx9AlphaBits"] == product["dx9AlphaBits"]})
    fits = {}
    if constants:
        predicates = {7: lambda a, b: a >= b, 3: lambda a, b: a == b, 6: lambda a, b: a != b}
        for backend in ("dx9", "dx11"):
            for model in ("normalized_float", "nearest_byte", "floor_byte", "observed_target_byte"):
                mismatches = []
                for row in constants:
                    # Fit measured pixel alpha, not the material source value:
                    # perspective interpolation can perturb a constant by 1 ULP.
                    alpha = float(row[backend + "FloatAlpha"])
                    scale = f32(alpha * 255)
                    value, reference = (alpha, f32(1 / 255)) if model == "normalized_float" else (
                        int(row[backend + "Alpha"]) if model == "observed_target_byte" else
                        math.floor(f32(scale + .5)) if model == "nearest_byte" else math.floor(scale), 1)
                    expected = predicates[int(row["comparison"])](value, reference)
                    if expected != (row[backend + "PassRef1"] == "1"):
                        mismatches.append({"inputBits": row["inputBits"], "comparison": row["comparison"], "repeat": row["repeat"]})
                fits[backend + ":" + model] = {"mismatches": len(mismatches), "first": mismatches[:4]}
    return {"directory": str(root), "complete": complete,
        "rows": {"floats": len(floats), "bytes": len(byte_rows), "constants": len(constants)},
        "repeatExact": {"floats": repeat_exact(floats, ("mode", "point")),
                        "bytes": repeat_exact(byte_rows, ("mode", "point")),
                        "constants": repeat_exact(constants, ("inputBits", "comparison", "point"))},
        "points": points, "constantComparisonModels": fits,
        "productionActivation": False, "imageAcceptance": False}


def references(root):
    data = load(root, "reference_scan.csv")
    groups = []
    for reference in sorted({int(r["reference"]) for r in data}):
        rows = [r for r in data if int(r["reference"]) == reference]
        bracket = {}
        for backend in ("dx9", "dx11"):
            first = next((r for r in rows if r["repeat"] == "0" and r[backend + "Pass"] == "1"), None)
            previous = next((r for r in rows if first and r["repeat"] == "0" and int(r["step"]) == int(first["step"]) - 1), None)
            bracket[backend] = {
                "firstPassingStep": int(first["step"]) if first else None,
                "firstPassingInputByte": float(first.get("bytePosition", reference - 1 + int(first["step"]) / 16)) if first else None,
                "leftBracketAvailable": previous is not None,
                "inputByteBracket": [float(previous.get("bytePosition", reference - 1 + int(previous["step"]) / 16)),
                                     float(first.get("bytePosition", reference - 1 + int(first["step"]) / 16))] if previous else None,
                "observedAlphaBracket": [float(previous[backend + "FloatAlpha"]),
                                         float(first[backend + "FloatAlpha"])] if previous else None,
                "passVsTargetByteMismatches": sum((int(r[backend + "Byte"]) >= reference) != (r[backend + "Pass"] == "1") for r in rows),
            }
        groups.append({"reference": reference, "rows": len(rows), "brackets": bracket})
    return {"directory": str(root), "complete": (root / "summary.txt").exists() and len(data) == 255,
            "repeatExact": repeat_exact(data, ("reference", "step")), "groups": groups}


def same_reference_measurements(left, right):
    # Older coarse captures lack the derived bytePosition column. Compare
    # actual inputAlpha and all observed values; never omit measured fields.
    fields = ("reference", "step", "inputAlpha", "repeat", "dx9FloatAlpha",
              "dx11FloatAlpha", "dx9Byte", "dx11Byte", "dx9Pass", "dx11Pass")
    a, b = load(left, "reference_scan.csv"), load(right, "reference_scan.csv")
    return bool(a) and len(a) == len(b) and all(
        {k: x[k] for k in fields} == {k: y[k] for k in fields} for x, y in zip(a, b))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--output", type=Path, help="Write a UTF-8 JSON artifact without shell redirection.")
    parser.add_argument("--references", type=Path)
    parser.add_argument("--compare-references", type=Path)
    args = parser.parse_args()
    result = analyze(args.directory)
    if args.compare:
        result["other"] = analyze(args.compare)
        result["architectureExact"] = all(load(args.directory, name) == load(args.compare, name)
            for name in ("float_stages.csv", "byte_controls.csv", "constant_alpha.csv"))
    if args.references:
        result["references"] = references(args.references)
    if args.compare_references:
        if not args.references:
            parser.error("--compare-references requires --references")
        result["otherReferences"] = references(args.compare_references)
        result["referenceArchitectureExact"] = same_reference_measurements(args.references, args.compare_references)
    serialized = json.dumps(result, indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
