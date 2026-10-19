"""Classify the saved draw-23 one-channel mismatch without fitting it.

The stage capture is deliberately diagnostic: it compares the native DX9
fixed-function vertex outputs with the DX11 compatibility shader at one saved
pixel, then records pixel-center and sampler controls.  It never relaxes the
image gate or changes a production shader.
"""
import argparse
import csv
import json
import math
import struct
from pathlib import Path


def rows(path):
    with path.open(newline="") as stream:
        result = list(csv.DictReader(stream))
    if not result:
        raise ValueError(f"empty CSV: {path}")
    return result


def vector(row, prefix):
    return tuple(float(row[f"{prefix}{channel}"]) for channel in "RGBA")


def delta(left, right):
    return max(abs(a - b) for a, b in zip(left, right))


def changed(left, right):
    return any(a != b for a, b in zip(left, right))


def bool_field(row, name):
    value = row[name].strip().lower()
    if value in {"1", "true"}:
        return True
    if value in {"0", "false"}:
        return False
    raise ValueError(f"invalid boolean {name}: {value}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stages", type=Path, required=True)
    parser.add_argument("--failure", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    metadata = dict(token.split("=", 1) for token in (args.stages / "metadata.txt").read_text().split() if "=" in token)
    failure = rows(args.failure)[0]
    focus = (int(metadata["x"]), int(metadata["y"]))
    if focus != (int(failure["x"]), int(failure["y"])):
        raise ValueError("stage focus differs from saved failure")
    native_bytes = tuple(int(failure[f"native{c}"]) for c in "RGBA")
    candidate_bytes = tuple(int(failure[f"candidate{c}"]) for c in "RGBA")
    if native_bytes == candidate_bytes:
        raise ValueError("saved failure is not different")

    stage_rows = rows(args.stages / "stages.csv")
    modes = ("diffuse", "specular", "coordinate0", "coordinate1", "sample0", "sample1", "pre_specular", "final")
    observations = {}
    for mode in modes:
        group = [row for row in stage_rows if row["mode"] == mode]
        if len(group) != 3 or len({(vector(row, "native"), vector(row, "candidate")) for row in group}) != 1:
            raise ValueError(f"unstable or incomplete stage: {mode}")
        first = group[0]
        observations[mode] = {
            "native": vector(first, "native"),
            "candidate": vector(first, "candidate"),
            "changed": changed(vector(first, "native"), vector(first, "candidate")),
            "maxAbsDelta": delta(vector(first, "native"), vector(first, "candidate")),
        }

    first_difference = next((mode for mode in modes if observations[mode]["changed"]), None)
    if first_difference != "specular":
        raise ValueError(f"unexpected first varying difference: {first_difference}")
    if observations["diffuse"]["changed"] or observations["coordinate1"]["changed"]:
        raise ValueError("reference stages changed unexpectedly")
    if not observations["coordinate0"]["changed"] or not observations["sample0"]["changed"]:
        raise ValueError("expected normal-coordinate / Toon sample difference is absent")
    if observations["sample1"]["changed"]:
        raise ValueError("second texture sample unexpectedly differs")

    center_rows = rows(args.stages / "pixel_center.csv")
    center = {}
    for row in center_rows:
        key = (row["mode"], float(row["offset"]))
        if key in center:
            raise ValueError(f"duplicate center row: {key}")
        center[key] = row
    for mode in ("coordinate0", "sample0", "sample1", "final"):
        for offset in (0.0, 0.5):
            if (mode, offset) not in center:
                raise ValueError(f"missing center control: {mode}/{offset}")
    # At the saved point the half-pixel-compatible viewport has coverage;
    # removing the offset moves this compact triangle away from the point.
    center_half = center["final", 0.5]
    center_integer = center["final", 0.0]
    half_candidate = tuple(float(center_half[f"candidate{c}"]) for c in "RGBA")
    integer_candidate = tuple(float(center_integer[f"candidate{c}"]) for c in "RGBA")
    pixel_center = {
        "halfOffsetCandidate": half_candidate,
        "integerOffsetCandidate": integer_candidate,
        "halfOffsetHasCoverage": half_candidate[3] != 0.0,
        "integerOffsetHasCoverage": integer_candidate[3] != 0.0,
        "halfOffsetKnownDifferentPixels": int(center_half["knownDifferentPixels"]),
        "integerOffsetKnownDifferentPixels": int(center_integer["knownDifferentPixels"]),
        "halfOffsetFocusDifferent": bool_field(center_half, "focusDifferent"),
        "integerOffsetFocusDifferent": bool_field(center_integer, "focusDifferent"),
        "conclusion": "viewport_half_pixel_offset_required",
    }
    if not pixel_center["halfOffsetHasCoverage"] or pixel_center["integerOffsetHasCoverage"]:
        raise ValueError("pixel-center control did not isolate coverage")
    if not pixel_center["halfOffsetFocusDifferent"] or not pixel_center["integerOffsetFocusDifferent"]:
        raise ValueError("pixel-center control did not report the saved focus")

    sample_rows = rows(args.stages / "sampling_precision.csv")
    sampling = {}
    for row in sample_rows:
        key = row["mode"]
        if key in sampling:
            raise ValueError(f"duplicate sampling row: {key}")
        sampling[key] = row
    if set(sampling) != {"captured", "point", "linear_mip_point", "linear_mip_linear"}:
        raise ValueError("incomplete sampler control")
    captured = tuple(float(sampling["captured"][f"candidate{c}"]) for c in "RGBA")
    point = tuple(float(sampling["point"][f"candidate{c}"]) for c in "RGBA")
    sampling_result = {
        "capturedCandidate": captured,
        "pointCandidate": point,
        "pointChangesSample": changed(captured, point),
        "capturedNativeCandidateDelta": float(sampling["captured"]["maxAbsDelta"]),
        "capturedKnownDifferentPixels": int(sampling["captured"]["knownDifferentPixels"]),
        "capturedFocusDifferent": bool_field(sampling["captured"], "focusDifferent"),
        "conclusion": "sampler_filter_changes_value_but_does_not_explain_native_candidate_delta",
    }
    if not sampling_result["pointChangesSample"]:
        raise ValueError("point sampler did not change the diagnostic sample")
    if float(sampling["captured"]["maxAbsDelta"]) == 0.0:
        raise ValueError("captured sampler unexpectedly matched DX9")
    if not sampling_result["capturedFocusDifferent"] or sampling_result["capturedKnownDifferentPixels"] == 0:
        raise ValueError("captured sampler did not differ inside the viewport")

    result = {
        "status": "PASS",
        "diagnosticOnly": True,
        "draw": 23,
        "triangle": int(metadata["triangle"]),
        "pixel": list(focus),
        "savedNativeRGBA": list(native_bytes),
        "savedCandidateRGBA": list(candidate_bytes),
        "stageObservations": observations,
        "firstObservedDifference": first_difference,
        "pixelCenter": pixel_center,
        "sampling": sampling_result,
        "conclusion": (
            "native_and_candidate_geometry_reach_the_pixel; the first varying mismatch is "
            "specular interpolation, followed by a normal-coordinate ULP and Toon sample; "
            "the second texture sample is exact. Preserve the native interpolation path and "
            "do not enable the adapter from this diagnostic."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "pixel": result["pixel"],
                      "firstObservedDifference": first_difference,
                      "coordinate0Delta": observations["coordinate0"]["maxAbsDelta"],
                      "toonSampleDelta": observations["sample0"]["maxAbsDelta"],
                      "secondSampleExact": not observations["sample1"]["changed"],
                      "pixelCenter": pixel_center["conclusion"]}))


if __name__ == "__main__":
    main()
