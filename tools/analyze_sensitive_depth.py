"""Evaluate cancellation hypotheses on fixed calibration and holdout fixtures."""
import argparse
import csv
import json
from pathlib import Path
import struct


MODES = ("original", "left_sequential", "left_double", "left_paired",
         "left_fused", "right_sequential", "right_double")
POINTS = ((20, 42), (36, 46))


def fbits(value):
    return struct.unpack("<I", struct.pack("<f", float(value)))[0]


def round32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def clip_plane(clip, x, y, round_z=False):
    vertices = [((v[0]/v[3]+1)*32-.5, (1-v[1]/v[3])*32-.5,
                 round32(v[2]/v[3]) if round_z else v[2]/v[3]) for v in clip]
    a, b, c = vertices
    denominator = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
    if denominator == 0:
        raise ValueError("degenerate saved clip plane")
    u = ((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/denominator
    v = ((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/denominator
    return u*a[2]+v*b[2]+(1-u-v)*c[2]


def load(directory):
    fixture = json.loads((directory.parent / "fixtures.json").read_text())
    perspective = fixture.get("perspective", False)
    modes = MODES + (("shared_camera", "shared_ndc_float", "shared_ndc_double") if perspective else ())
    with (directory / "thresholds.csv").open(newline="") as file:
        rows = list(csv.DictReader(file))
    indexed = {}
    for row in rows:
        key = int(row["case"]), row["mode"], int(row["x"]), int(row["y"])
        if key in indexed or row["dx9Equal"] != "G" or row["dx11Equal"] != "G" or row["repeatExact"] != "1":
            raise ValueError("duplicate measurement, invalid equality or unstable repetition")
        if row["split"] != ("calibration" if key[0] < 6 else "holdout"):
            raise ValueError("incorrect preassigned split")
        indexed[key] = row
    expected = {(case, mode, x, y) for case in range(12) for mode in modes for x, y in POINTS}
    if indexed.keys() != expected:
        raise ValueError(f"incomplete measurement matrix: {len(indexed)}/{len(expected)}")
    with (directory / "coefficients.csv").open(newline="") as file:
        coefficients = list(csv.DictReader(file))
    if len(coefficients) != 72:
        raise ValueError("incomplete coefficient table")
    for case in fixture["cases"]:
        generated = case["candidateCenterDepths"]
        measured_rows = [next(row for row in coefficients if int(row["case"]) == case["id"] and row["mode"] == mode) for mode in MODES[1:]]
        measured = [float(row["z3"])/float(row["w3"]) for row in measured_rows]
        if [fbits(v) for v in generated] != [fbits(v) for v in measured]:
            raise ValueError("generator and C++ candidate rounding disagree")
    results = []
    for mode in MODES[1:]:
        result = {"mode": mode}
        for split, cases in (("calibration", range(6)), ("holdout", range(6, 12))):
            comparisons = []
            for case in cases:
                for x, y in POINTS:
                    original = indexed[case, "original", x, y]
                    candidate = indexed[case, mode, x, y]
                    comparisons.append({"case": case, "x": x, "y": y,
                        "dx9CandidateMinusOriginalSteps": int(candidate["dx9ThresholdBits"]) - int(original["dx9ThresholdBits"]),
                        "dx11CandidateMinusOriginalDX9Steps": int(candidate["dx11ThresholdBits"]) - int(original["dx9ThresholdBits"]),
                        "candidateBackendDelta": int(candidate["dx9ThresholdBits"]) - int(candidate["dx11ThresholdBits"])})
            result[split] = {"comparisons": comparisons,
                "nativeMatches": sum(v["dx9CandidateMinusOriginalSteps"] == 0 for v in comparisons),
                "dx11MatchesOriginalNative": sum(v["dx11CandidateMinusOriginalDX9Steps"] == 0 for v in comparisons),
                "backendMatches": sum(v["candidateBackendDelta"] == 0 for v in comparisons), "total": len(comparisons)}
        results.append(result)
        print(f"{mode}: native calibration={result['calibration']['nativeMatches']}/12 holdout={result['holdout']['nativeMatches']}/12; "
              f"DX11-to-original-native holdout={result['holdout']['dx11MatchesOriginalNative']}/12")
    # Choose only using calibration, then report preassigned holdout unchanged.
    best = max(result["calibration"]["nativeMatches"] for result in results)
    shortlist = [r["mode"] for r in results if r["calibration"]["nativeMatches"] == best]
    shared = {}
    for mode in modes[7:]:
        data = [indexed[case, mode, x, y] for case in range(12) for x, y in POINTS]
        shared[mode] = {"backendMatches": sum(r["dx9ThresholdBits"] == r["dx11ThresholdBits"] for r in data),
            "dx11MatchesOriginalDX11": sum(r["dx11ThresholdBits"] == indexed[int(r["case"]), "original", int(r["x"]), int(r["y"])]["dx11ThresholdBits"] for r in data),
            "dx9MatchesOriginalDX9": sum(r["dx9ThresholdBits"] == indexed[int(r["case"]), "original", int(r["x"]), int(r["y"])]["dx9ThresholdBits"] for r in data),
            "total": len(data)}
        print(f"{mode}: {shared[mode]}")
    if perspective and shared["shared_camera"]["dx11MatchesOriginalDX11"] != 24:
        raise ValueError("bit-preserving camera control changed DX11 depth")
    ndc_equal = all((directory / f"case{case}-shared_ndc_float-clip.bin").read_bytes() ==
                    (directory / f"case{case}-shared_ndc_double-clip.bin").read_bytes() for case in range(12)) if perspective else None
    clip_validation = {}
    quotient_models = []
    if perspective:
        minimum_w, maximum_w = float("inf"), 0.
        for case in range(12):
            original_bytes = (directory / f"case{case}-original-clip.bin").read_bytes()
            if len(original_bytes) != 48 or (directory / f"case{case}-shared_camera-clip.bin").read_bytes() != original_bytes:
                raise ValueError("camera control did not preserve saved clip bits")
            original = list(struct.iter_unpack("<4f", original_bytes))
            if not all(v[3] > 0 for v in original) or len({v[3] for v in original}) < 2:
                raise ValueError("fixture does not exercise varying positive W")
            minimum_w = min(minimum_w, *(v[3] for v in original))
            maximum_w = max(maximum_w, *(v[3] for v in original))
            for mode in ("shared_ndc_float", "shared_ndc_double"):
                converted_bytes = (directory / f"case{case}-{mode}-clip.bin").read_bytes()
                if len(converted_bytes) != 48:
                    raise ValueError("invalid NDC clip capture size")
                converted = list(struct.iter_unpack("<4f", converted_bytes))
                if not all(v[3] == 1. and fbits(v[2]) == fbits(source[2]/source[3]) for v, source in zip(converted, original)):
                    raise ValueError("CPU shared NDC Z does not equal correctly rounded Z/W")
            combined = list(struct.iter_unpack("<4f", (directory / f"case{case}-left_sequential-clip.bin").read_bytes()))
            ndc = list(struct.iter_unpack("<4f", (directory / f"case{case}-shared_ndc_float-clip.bin").read_bytes()))
            for x, y in POINTS:
                for mode, observed in (("original", original), ("left_sequential", combined)):
                    precise = clip_plane(observed, x, y)
                    rounded_z = clip_plane(observed, x, y, round_z=True)
                    row = indexed[case, mode, x, y]
                    quotient_models.append({"case": case, "x": x, "y": y, "mode": mode,
                        "doubleVertexQuotientPlane": precise,
                        "roundedVertexZOnlyPlane": rounded_z,
                        "roundedZOnlyDelta": rounded_z-precise,
                        "modelRoundedFloatBitsMinusDX11Reference": fbits(precise)-int(row["dx11ThresholdBits"]),
                        "dx9ReferenceBits": int(row["dx9ThresholdBits"]),
                        "dx11ReferenceBits": int(row["dx11ThresholdBits"]),
                        "sharedNdcPlane": clip_plane(ndc, x, y) if mode == "original" else None})
        clip_validation = {"cameraClipBitsPreserved": True, "varyingPositiveWAllCases": True,
                           "minimumW": minimum_w, "maximumW": maximum_w,
                           "cpuNdcDivisionVerifiedVertices": 36}
    result = {"measurements": len(rows), "repeatExact": True, "perspective": perspective,
        "sharedInputs": shared, "ndcFloatDoubleClipBitsIdentical": ndc_equal,
        "clipValidation": clip_validation,
        "diagnosticQuotientPlanes": quotient_models,
        "quotientPlaneLimit": "CPU double barycentric planes and rounded Z controls diagnose representation changes; they are not a fitted GPU interpolation model or raw D24 predictions.",
        "calibrationShortlist": shortlist, "candidates": results,
        "originalBackendDifferingThresholds": sum(r["dx9ThresholdBits"] != r["dx11ThresholdBits"] for r in rows if r["mode"] == "original"),
        "candidateBackendDifferingThresholds": sum(r["dx9ThresholdBits"] != r["dx11ThresholdBits"] for r in rows if r["mode"] in MODES[1:]),
        "limit": "Threshold bits encode constant float32 reference planes, not raw D24 attachment bits or native vertex outputs. These are deliberately sensitive synthetic matrices, not a PMM acceptance or universal driver model.",
        "fullSceneAcceptance": False}
    (directory / "analysis.json").write_text(json.dumps(result, indent=2)+"\n")
    print(f"calibrationShortlist={shortlist} output={directory / 'analysis.json'}")
    return indexed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", type=Path, nargs="+")
    args = parser.parse_args()
    tables = [load(directory) for directory in args.directories]
    if len(tables) == 2:
        differences = sum(tables[0][key][field] != tables[1][key][field]
            for key in tables[0] for field in ("dx9ThresholdBits", "dx11ThresholdBits"))
        print(f"architectureThresholdDifferences={differences}/{len(tables[0])*2}")


if __name__ == "__main__":
    main()
