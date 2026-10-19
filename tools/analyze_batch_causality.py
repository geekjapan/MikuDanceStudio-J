"""Validate runtime UV/specular cross-feeds; report evidence, not image acceptance."""
import argparse
import csv
import hashlib
import json
import math
import struct
from collections import defaultdict
from pathlib import Path


def read_csv(path):
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f"empty evidence: {path}")
    return rows


def color(row, prefix, byte=False):
    return tuple((int if byte else float)(row[prefix + c]) for c in "RGBA")


def observation(row):
    return {"nativeFloat": color(row, "native"), "candidateFloat": color(row, "candidate"),
            "nativeRGBA": color(row, "nativeByte", True), "candidateRGBA": color(row, "candidateByte", True)}


def ulp_distance(left, right):
    def ordered(value):
        bits = struct.unpack("<I", struct.pack("<f", value))[0]
        return (~bits & 0xffffffff) if bits & 0x80000000 else bits | 0x80000000
    return abs(ordered(left) - ordered(right))


def measure(stages):
    summary = (stages / "summary.txt").read_text()
    if "complete=1" not in summary or "runtimeConstants=1" not in summary or "repeats=3" not in summary:
        raise ValueError("probe is incomplete")
    metadata = dict(token.split("=", 1) for token in (stages / "metadata.txt").read_text().split() if "=" in token)
    groups = defaultdict(list)
    for row in read_csv(stages / "controls.csv"):
        key = tuple(row[k] for k in ("geometry", "queryX", "queryY", "mode", "x", "y"))
        groups[key].append(row)
    focus = {}
    for key, rows in groups.items():
        if len(rows) != 3 or {row["repeat"] for row in rows} != {"0", "1", "2"}:
            raise ValueError(f"incomplete repeats: {key}")
        values = [observation(row) for row in rows]
        if any(value != values[0] for value in values[1:]):
            raise ValueError(f"unstable output: {key}")
        if not all(math.isfinite(f) for prefix in ("nativeFloat", "candidateFloat") for f in values[0][prefix]):
            raise ValueError(f"nonfinite observation: {key}")
        geometry, qx, qy, mode, x, y = key
        if (qx, qy) == (x, y):
            if values[0]["nativeFloat"][3] != 1 or values[0]["candidateFloat"][3] != 1:
                raise ValueError(f"query lost coverage: {key}")
            focus.setdefault((geometry, int(x), int(y)), {})[mode] = values[0]
    gates = read_csv(stages / "gates.csv")
    if len(gates) != 6 or any(row[field] != "1" for row in gates for field in (
            "nativeExplicitByteExact", "candidateExplicitByteExact", "nativeExplicitFloatExact", "candidateExplicitFloatExact")):
        raise ValueError("explicit PS does not preserve original FF/measured output")
    required = {"live", "uv9_grad9", "uv11_grad9", "uv9_grad11", "uv11_grad11", "uv9_zero", "uv11_zero",
                "final_uv9", "final_uv11", "final_sample9", "final_sample11", "final_spec9", "final_spec11",
                "final_sample9_spec9", "final_sample9_spec11", "final_sample11_spec9", "final_sample11_spec11",
                "final_all9", "final_all11"}
    if len(focus) != 6 or {key[0] for key in focus} != {"saved", "independent"}:
        raise ValueError("expected three queries on each geometry")
    reports = []
    for (geometry, x, y), modes in focus.items():
        archived_names = {"archived_" + name for name in ("uv9_grad9", "uv11_grad9", "uv9_grad11", "uv11_grad11", "uv9_zero", "uv11_zero")}
        if set(modes) != (required | archived_names if geometry == "independent" else required):
            raise ValueError(f"missing cross-feed: {geometry}/{x}/{y}")
        sample_names = ("uv9_grad9", "uv11_grad9", "uv9_grad11", "uv11_grad11", "uv9_zero", "uv11_zero")
        sample_exact = all(modes[m]["nativeFloat"] == modes[m]["candidateFloat"] for m in sample_names)
        gradients_matter = any(modes[f"uv{uv}_grad9"][side] != modes[f"uv{uv}_zero"][side]
                               for uv in (9, 11) for side in ("nativeFloat", "candidateFloat"))
        gradient_crossfeed_changes = any(modes[f"uv{uv}_grad9"][side] != modes[f"uv{uv}_grad11"][side]
                                         for uv in (9, 11) for side in ("nativeFloat", "candidateFloat"))
        uv_changes_sample = any(modes["uv9_grad9"][side] != modes["uv11_grad9"][side]
                               for side in ("nativeFloat", "candidateFloat"))
        fixed_uv_byte_exact = all(modes[m]["nativeRGBA"] == modes[m]["candidateRGBA"] for m in ("final_uv9", "final_uv11"))
        fixed_sample_byte_exact = all(modes[m]["nativeRGBA"] == modes[m]["candidateRGBA"] for m in ("final_sample9", "final_sample11"))
        live_diff = modes["live"]["nativeRGBA"] != modes["live"]["candidateRGBA"]
        fixed_spec_still_diff = all(modes[m]["nativeRGBA"] != modes[m]["candidateRGBA"] for m in ("final_spec9", "final_spec11"))
        constant_math_exact = all(modes[m]["nativeFloat"] == modes[m]["candidateFloat"] and
                                  modes[m]["nativeRGBA"] == modes[m]["candidateRGBA"] for m in ("final_all9", "final_all11"))
        causal_uv = live_diff and sample_exact and uv_changes_sample and fixed_uv_byte_exact and fixed_sample_byte_exact and fixed_spec_still_diff
        reports.append({"geometry": geometry, "pixel": [x, y], "sameUVAndGradientsSampleExact": sample_exact,
                        "gradientsAffectSampling": gradients_matter, "gradientCrossfeedChangesSample": gradient_crossfeed_changes,
                        "uvCrossfeedChangesSample": uv_changes_sample, "fixedUVByteExact": fixed_uv_byte_exact,
                        "fixedSampleByteExact": fixed_sample_byte_exact, "fixedSpecularStillDiffers": fixed_spec_still_diff,
                        "constantColorMathExact": constant_math_exact, "uvExplainsObservedByteMismatch": causal_uv, "controls": modes})
    saved = next(r for r in reports if r["geometry"] == "saved" and r["pixel"] == [int(metadata["x"]), int(metadata["y"])])
    uv = [row for row in read_csv(stages / "observations.csv")
          if row["geometry"] == "saved" and row["mode"] == "uv0" and [int(row["x"]), int(row["y"])] == saved["pixel"]]
    if len(uv) != 1:
        raise ValueError("missing unique saved UV observation")
    saved["uv0UlpDistance"] = [ulp_distance(float(uv[0]["native" + c]), float(uv[0]["candidate" + c])) for c in "RG"]
    geometry_invariant = all(q["controls"]["archived_" + mode] == saved["controls"][mode]
                             for q in reports if q["geometry"] == "independent"
                             for mode in ("uv9_grad9", "uv11_grad9", "uv9_grad11", "uv11_grad11", "uv9_zero", "uv11_zero"))
    if not geometry_invariant:
        raise ValueError("archived constant UV/gradient sampling changed with generated geometry")
    return {"status": "DIAGNOSTIC_EVIDENCE_VALID", "diagnosticOnly": True, "imageAcceptance": False,
            "productionActivation": False, "repeats": 3, "geometryCount": 2, "queryCount": len(focus),
            "archivedUVGeometryInvariant": geometry_invariant,
            "validatedPixelGroups": len(groups), "textureHash": metadata["textureHash"],
            "evidenceSHA256": {name: hashlib.sha256((stages / name).read_bytes()).hexdigest()
                               for name in ("observations.csv", "controls.csv", "gates.csv", "summary.txt")},
            "savedFocus": saved, "queries": reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--failure", type=Path, help="saved application's differing RGBA pixel CSV")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = measure(args.input)
    if args.compare:
        other = measure(args.compare)
        result["crossArchitectureExact"] = result == other
        if not result["crossArchitectureExact"]:
            raise ValueError("same archived input differs across architectures")
    if args.failure:
        pixel = result["savedFocus"]["pixel"]
        failures = [row for row in read_csv(args.failure) if [int(row["x"]), int(row["y"])] == pixel]
        if len(failures) != 1:
            raise ValueError("saved failure does not contain the unique query pixel")
        live = result["savedFocus"]["controls"]["live"]
        if (live["nativeRGBA"] != color(failures[0], "native", True) or
                live["candidateRGBA"] != color(failures[0], "candidate", True)):
            raise ValueError("causal baseline differs from the saved application's failure")
        result["savedFailureMatchesLive"] = True
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    saved = result["savedFocus"]
    print(json.dumps({"status": result["status"], "pixel": saved["pixel"],
                      "sameUVAndGradientsSampleExact": saved["sameUVAndGradientsSampleExact"],
                      "uvExplainsObservedByteMismatch": saved["uvExplainsObservedByteMismatch"],
                      "constantColorMathExact": saved["constantColorMathExact"],
                      "crossArchitectureExact": result.get("crossArchitectureExact")}))


if __name__ == "__main__":
    main()
