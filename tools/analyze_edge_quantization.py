"""Analyze measured conversion, coverage and empirical resolved-color controls.

Offset fits assume one uniform color over covered samples. They are constraints
on that model, not direct reads of sample positions or invocation locations.
"""
import argparse
import csv
import json
import math
from pathlib import Path


def rows(root, name):
    with (root / name).open(encoding="utf-8") as stream:
        return [{k: int(v) for k, v in row.items()} for row in csv.DictReader(stream)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("x64", type=Path)
    parser.add_argument("x86", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    names = ("quantization.csv", "coverage.csv", "edges.csv", "resolve.csv")
    different = [name for name in names if (args.x64/name).read_bytes() != (args.x86/name).read_bytes()]
    q, coverage, edges, resolve = [rows(args.x64, name) for name in names]
    thresholds = []
    for samples in (1, 8):
        for base in sorted({row["base"] for row in q}):
            for path in (0, 4, 5):
                sequence = sorted((row for row in q if row["samples"] == samples and row["base"] == base and row["path"] == path), key=lambda row: row["step"])
                high = next((row["step"] for row in sequence if row["R"] > base), None)
                thresholds.append({"samples": samples, "base": base, "path": path,
                                   "firstHigherStep": high, "stepSizeByte": 1/64,
                                   "valueAtHalf": sequence[32]["R"]})
    masks = {(row["axis"], row["step"], row["sample"]): row["coverageByte"] for row in coverage}
    bounds = []
    for axis in (0, 1):
        for sample in range(8):
            sequence = [masks[axis, step, sample] for step in range(65)]
            first = next((step for step, value in enumerate(sequence) if value), None)
            bounds.append({"axis": axis, "sample": sample, "firstCoveredStep": first,
                           "monotonic": all(not a or b for a, b in zip(sequence, sequence[1:])),
                           "coverageOffsetBracket": [-.5 + (first-1)/64, -.5 + first/64] if first else None})
    count = {(axis, step): sum(masks[axis, step, sample] != 0 for sample in range(8)) for axis in (0, 1) for step in range(65)}
    resolve_lookup = {(row["axis"], row["step"], row["source"]): row["R"] for row in resolve if row["samples"] == 8}
    empirical = {}
    for row in resolve:
        if row["samples"] == 8:
            key = (count[row["axis"], row["step"]], row["source"])
            empirical.setdefault(key, set()).add(row["R"])
    curves = [{"covered": k, "source": source, "outputs": sorted(values)} for (k, source), values in sorted(empirical.items())]
    white = [row for row in curves if row["source"] == 255]
    for row in white:
        fraction = row["covered"] / 8
        row["linearPrediction"] = round(fraction * 255)
        row["sRGBPrediction"] = round(255 * (12.92*fraction if fraction <= .0031308 else 1.055*fraction**(1/2.4)-.055))
    quant_lookup = {(row["base"], row["step"]): row["R"] for row in q if row["samples"] == 8 and row["path"] == 0}
    edge_lookup = {(row["axis"], row["step"], row["phase"], row["path"]): row for row in edges if row["samples"] == 8}
    fits = []
    for axis in (0, 1):
        for step in range(65):
            k = count[axis, step]
            if not 0 < k < 8:
                continue
            for path in (1, 2, 3):
                candidates = []
                for tick in range(-32, 33):
                    offset = tick / 64
                    error = mismatches = 0
                    for phase in range(8):
                        value = 124 + 4*offset + phase/8
                        base = math.floor(value)
                        fraction_step = round((value-base)*64)
                        coded = quant_lookup[base, fraction_step]
                        predicted = resolve_lookup[axis, step, coded]
                        observed = edge_lookup[axis, step, phase, path]["R" if axis == 0 else "G"]
                        error += abs(predicted-observed)
                        mismatches += predicted != observed
                    candidates.append({"offsetPixels": offset, "absoluteError": error, "differentPhases": mismatches})
                best = min(row["absoluteError"] for row in candidates)
                fits.append({"axis": axis, "step": step, "covered": k, "path": path,
                             "bestError": best, "bestCandidates": [row for row in candidates if row["absoluteError"] == best]})
    bracket_lookup = {(row["axis"], row["sample"]): row["coverageOffsetBracket"] for row in bounds}
    hypotheses = []
    for path in (1, 2, 3):
        group = [row for row in fits if row["path"] == path]
        center = lowest = 0
        for row in group:
            chosen = next(sample for sample in range(8) if masks[row["axis"], row["step"], sample])
            candidate = bracket_lookup[row["axis"], chosen][0]
            center += any(fit["offsetPixels"] == 0 for fit in row["bestCandidates"])
            lowest += any(fit["offsetPixels"] == candidate for fit in row["bestCandidates"])
        hypotheses.append({"path": path, "cases": len(group), "centerCompatible": center,
                           "lowestCoveredIndexAtBracketLowerBoundCompatible": lowest,
                           "interpretation": "compatibility only; not proof of sample selection or exact sample location"})
    result = {"crossArchitectureDifferentFiles": different,
              "quantizationThresholds": thresholds, "coverageBrackets": bounds,
              "empiricalResolve": curves, "whiteResolve": white,
              "offsetModel": "uniform covered-sample color with empirical constant-output conversion and resolve",
              "offsetFits": fits, "locationHypotheses": hypotheses, "sampleReadback": "resolved_mask_control_only"}
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("architectureDifferences", different)
    print("coverage brackets", bounds)
    print("white resolve", white)
    print("native thresholds", [row for row in thresholds if row["samples"] == 1 and row["path"] == 0])
    for path in (1, 2, 3):
        group = [row for row in fits if row["path"] == path]
        print("offset path", path, "cases", len(group), "exactFits", sum(row["bestError"] == 0 for row in group), "maxBestError", max(row["bestError"] for row in group))
    print("location hypotheses", hypotheses)
    print("centroid different rows", sum(any(edge_lookup[axis, step, phase, 1][c] != edge_lookup[axis, step, phase, 2][c] for c in ("B","G","R","A")) for axis in (0,1) for step in range(65) for phase in range(8)))
    return bool(different)


if __name__ == "__main__":
    raise SystemExit(main())
