"""Summarize measured native depth comparisons; never infer raw D24 bits."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import re
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("measurements", type=Path)
    args = parser.parse_args()
    with args.measurements.open(newline="") as file:
        rows = list(csv.DictReader(file))
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("malformed CSV row")
    grouped = defaultdict(list)
    for row in rows:
        if row["kind"] == "probe":
            bits = int(row["referenceBits"])
            depth = struct.unpack("<f", struct.pack("<I", bits))[0]
            if depth != float(row["referenceFloat"]):
                raise ValueError("reported float/bit pattern differs")
            grouped[(row["pair"], row["triangle"], row["x"], row["y"])].append(row)
    probes = []
    for (pair, triangle, x, y), group in sorted(grouped.items()):
        measured = {}
        for backend in ("dx9", "dx11"):
            equal = sorted(int(row["offset"]) for row in group if row["comparison"] == "Equal" and row[backend] == "G")
            less = sorted(int(row["offset"]) for row in group if row["comparison"] == "Less" and row[backend] == "G")
            all_less = sorted(int(row["offset"]) for row in group if row["comparison"] == "Less")
            if len(equal) != 1 or less != [offset for offset in all_less if offset < equal[0]]:
                raise ValueError(f"{pair}/{triangle}/{x},{y}: no unique monotone threshold for {backend}")
            reference = next(row for row in group if int(row["offset"]) == equal[0])
            measured[backend] = {"equalReferenceBits": int(reference["referenceBits"]),
                                 "equalReferenceFloat": float(reference["referenceFloat"]),
                                 "offsetFromDoubleProjectionCenter": equal[0],
                                 "lastAcceptedLessOffset": max(less) if less else None}
        probes.append({"pair": pair, "triangle": int(triangle), "x": int(x), "y": int(y),
                       **measured,
                       "dx9MinusDx11ReferenceSteps": measured["dx9"]["equalReferenceBits"] - measured["dx11"]["equalReferenceBits"]})
    calibrations = [row for row in rows if row["kind"] == "calibration"]
    if len(calibrations) != 15:
        raise ValueError("reference calibration is incomplete")
    for row in calibrations:
        offset = int(row["offset"])
        passed = offset < 0 if row["comparison"] == "Less" else offset == 0 if row["comparison"] == "Equal" else offset <= 0
        if row["dx9"] != ("G" if passed else "R") or row["dx11"] != row["dx9"] or int(row["differentPixels"]) != 0:
            raise ValueError("reference calibration failed")
    pair_rows = [row for row in rows if row["kind"] == "pair" and row["repeat"] == "0"]
    cycles = [row for row in rows if row["kind"].startswith("cycle_delta")]
    ranges = [row for row in rows if row["kind"].startswith("range_")]
    baked = [row for row in rows if row["kind"] == "bake_change"]
    holdouts = [row for row in rows if row["kind"] == "holdout"]
    paired = defaultdict(list)
    for probe in probes:
        paired[(probe["pair"], probe["x"], probe["y"])].append(probe)
    relations = []
    for (pair, x, y), group in paired.items():
        first_triangle, second_triangle = (int(value) for value in pair.split("_"))
        if {probe["triangle"] for probe in group} != {first_triangle, second_triangle}:
            raise ValueError("incomplete triangle-pair thresholds")
        first = next(probe for probe in group if probe["triangle"] == first_triangle)
        second = next(probe for probe in group if probe["triangle"] == second_triangle)
        relations.append({"pair": pair, "x": x, "y": y,
                          "firstMinusSecondDX9ReferenceSteps": first["dx9"]["equalReferenceBits"] - second["dx9"]["equalReferenceBits"],
                          "firstMinusSecondDX11ReferenceSteps": first["dx11"]["equalReferenceBits"] - second["dx11"]["equalReferenceBits"]})
    # A separate two-surface render checks the reference-probe prediction.
    # This only validates the measured coordinates, not an interpolation model
    # at new coordinates or another driver.
    native_log = args.measurements.parent.parent / "history_replay.dx9"
    region = re.search(r"PORTABLE_REGION x=(\d+) y=(\d+) width=(\d+) height=(\d+)", native_log.read_text())
    if not region:
        raise ValueError("missing reference target dimensions")
    x, y, w, h = (int(value) for value in region.groups())
    width, height = x + w, y + h
    images = {}
    for relation in relations:
        if not (x <= relation["x"] < width and y <= relation["y"] < height):
            raise ValueError("measurement coordinate outside viewport")
        at = (relation["y"] * width + relation["x"]) * 4
        for backend, suffix in (("DX9", "native"), ("DX11", "dx11")):
            key = relation["pair"], backend
            if key not in images:
                images[key] = (args.measurements.parent / f"{relation['pair']}-{suffix}.rgba").read_bytes()
                if len(images[key]) != width * height * 4:
                    raise ValueError("incorrect pair image dimensions")
            expected = b"\xff\x00\x00\xff" if relation[f"firstMinusSecond{backend}ReferenceSteps"] < 0 else b"\x00\xff\x00\xff"
            if images[key][at:at + 4] != expected:
                raise ValueError("measured threshold does not predict surface-selection image")
    result = {
        "referenceCalibrationComparisons": len(calibrations), "referenceCalibrationPass": True,
        "referenceFloat32Step": 2 ** -24, "d24CodeStep": 1 / (2 ** 24 - 1),
        "rawDepthBitsReadBack": False,
        "limit": "Equal/Less classify attachment relations using representable constant reference depth. The equality reference bits are float32 input bits, not raw native D24 attachment codes. CPU double projection centers the scan only.",
        "measuredThresholds": probes,
        "surfaceRelations": relations,
        "surfaceChoicePredictionsChecked": len(relations) * 2,
        "differentThresholds": sum(probe["dx9MinusDx11ReferenceSteps"] != 0 for probe in probes),
        "depthDisabledImagesExact": all(int(row["differentPixels"]) == 0 for row in pair_rows if row["comparison"] == "DepthDisabled"),
        "pairComparisons": pair_rows, "cyclicChanges": cycles, "depthRangeComparisons": ranges,
        "bakedVersusOriginalImages": baked, "holdoutCoordinates": holdouts,
        "fullSceneAcceptance": False,
    }
    output = args.measurements.with_suffix(".json")
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"thresholds={len(probes)} differing={result['differentThresholds']} referenceCalibration=PASS output={output}")
    for probe in probes:
        print(f"pair={probe['pair']} triangle={probe['triangle']} pixel={probe['x']},{probe['y']} dx9MinusDx11Steps={probe['dx9MinusDx11ReferenceSteps']}")


if __name__ == "__main__":
    main()
