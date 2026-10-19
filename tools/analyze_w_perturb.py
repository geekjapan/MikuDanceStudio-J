"""Validate preassigned W-coefficient perturbations and depth hypotheses."""
import argparse
import csv
import json
from pathlib import Path
import struct
from analyze_perspective_case10 import vertices
from generate_sensitive_depth_matrices import dot


MODES = ("production", "shared_clip", "native_dot", "native_ordered", "native_dot_w",
         "cpu_sequential", "cpu_double", "cpu_paired", "cpu_fused")
POINTS = ((36, 46), (20, 42))


def read_csv(path):
    with path.open(newline="") as file:
        return list(csv.DictReader(file))


def bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def load(directory):
    cases = read_csv(directory / "perturbations.csv")
    expected_cases = [(coefficient, offset) for coefficient in (3, 7, 15)
                      for offset in (0, -1, 1, -2, 2, -4, 4) if offset or coefficient == 3]
    if len(cases) != 19:
        raise ValueError("incomplete perturbation set")
    measurements = read_csv(directory / "measurements.csv")
    indexed = {}
    for row in measurements:
        prefix, mode = row["variant"].split("_", 1)
        key = int(prefix[1:]), mode, int(row["x"]), int(row["y"])
        if prefix[0] != "p" or key in indexed or row["repeatExact"] != "1":
            raise ValueError("invalid, duplicate or unstable measurement")
        indexed[key] = row
    if indexed.keys() != {(case, mode, x, y) for case in range(19) for mode in MODES for x, y in POINTS}:
        raise ValueError("incomplete measurement matrix")
    base = struct.unpack("<16f", (directory / "combined_matrix.bin").read_bytes())
    object_vertices = vertices(directory / "object.bin")
    base_raw = vertices(directory / "raw.clip")
    cpu_clip_matches = {rule: 0 for rule in ("sequential", "double", "paired", "fused")}
    signatures = {rule: [] for rule in cpu_clip_matches}
    w_changes = []
    per_case = []
    for number, (case, expected) in enumerate(zip(cases, expected_cases)):
        coefficient, offset = expected
        split = "calibration" if abs(offset) <= 1 else "holdout"
        if int(case["case"]) != number or int(case["coefficient"]) != coefficient or int(case["offset"]) != offset or case["split"] != split:
            raise ValueError("perturbation order or preassigned split changed")
        matrix = struct.unpack("<16f", (directory / f"p{number}.matrix").read_bytes())
        if any(bits(matrix[k]) != bits(base[k]) for k in range(16) if k != coefficient):
            raise ValueError("more than one coefficient was changed")
        if int(case["baseBits"]) != bits(base[coefficient]) or int(case["newBits"]) != bits(matrix[coefficient]):
            raise ValueError("metadata coefficient bits do not match binary")
        if bits(matrix[coefficient]) != bits(base[coefficient]) + offset * (1 if base[coefficient] > 0 else -1):
            raise ValueError("incorrect float32 ULP perturbation")
        prefix = f"p{number}"
        raw = vertices(directory / f"{prefix}_shared_clip.clip")
        production_bytes = (directory / f"{prefix}_production_output.clip").read_bytes()
        if any(raw[n][k] != base_raw[n][k] for n in range(3) for k in range(3)):
            raise ValueError("raw clip X/Y/Z changed during W-only perturbation")
        if (directory / f"{prefix}_shared_clip-dx11.clip").read_bytes() != production_bytes:
            raise ValueError("shared clip did not retain production bits")
        for mode in ("production", "native_dot", "native_ordered", "native_dot_w"):
            if (directory / f"{prefix}_{mode}-dx11.clip").read_bytes() != production_bytes:
                raise ValueError("instruction-control DX11 output changed")
        for rule in cpu_clip_matches:
            candidate = vertices(directory / f"{prefix}_cpu_{rule}.clip")
            for n in range(3):
                expected_w = dot(object_vertices[n], matrix[3::4], rule)
                if candidate[n][:3] != raw[n][:3] or bits(candidate[n][3]) != bits(expected_w):
                    raise ValueError("CPU W candidate disagrees with prescribed arithmetic")
                cpu_clip_matches[rule] += bits(candidate[n][3]) == bits(raw[n][3])
                signatures[rule].append(bits(candidate[n][3]))
                if rule == "fused" and bits(candidate[n][3]) != bits(raw[n][3]):
                    w_changes.append({"case": number, "vertex": n,
                        "productionW": raw[n][3], "productionWBits": bits(raw[n][3]),
                        "cpuFusedW": candidate[n][3], "cpuFusedWBits": bits(candidate[n][3]),
                        "float32WStepDelta": bits(candidate[n][3])-bits(raw[n][3])})
        per_case.append({**case, "coordinates": [{"x": x, "y": y,
            "nativeBits": int(indexed[number, "production", x, y]["dx9Bits"]),
            "dx11Bits": int(indexed[number, "production", x, y]["dx11Bits"]),
            "nativeDotBits": int(indexed[number, "native_dot", x, y]["dx9Bits"]),
            "nativeWOnlyDotBits": int(indexed[number, "native_dot_w", x, y]["dx9Bits"])} for x, y in POINTS]})
    # The unperturbed case must reproduce the previous reduction, not just a
    # coincidental internally consistent new baseline.
    previous = read_csv(directory.parent.parent / "perspective-case10" / directory.name / "measurements.csv")
    for mode in MODES[:5]:
        for x, y in POINTS:
            old = next(row for row in previous if row["variant"] == mode and int(row["x"]) == x and int(row["y"]) == y)
            new = indexed[0, mode, x, y]
            if any(old[field] != new[field] for field in ("dx9Bits", "dx11Bits")):
                raise ValueError("unperturbed prior baseline did not reproduce")
    summaries = []
    for mode in MODES[1:]:
        summary = {"mode": mode}
        for split in ("calibration", "holdout"):
            comparisons = []
            for number, case in enumerate(cases):
                if case["split"] != split:
                    continue
                for x, y in POINTS:
                    native = int(indexed[number, "production", x, y]["dx9Bits"])
                    row = indexed[number, mode, x, y]
                    comparisons.append({"case": number, "x": x, "y": y,
                        "nativeMinusOriginalNativeSteps": int(row["dx9Bits"])-native,
                        "dx11MinusOriginalNativeSteps": int(row["dx11Bits"])-native,
                        "backendSteps": int(row["dx9Bits"])-int(row["dx11Bits"])})
            summary[split] = {"total": len(comparisons),
                "nativeMatches": sum(c["nativeMinusOriginalNativeSteps"] == 0 for c in comparisons),
                "dx11Matches": sum(c["dx11MinusOriginalNativeSteps"] == 0 for c in comparisons),
                "backendMatches": sum(c["backendSteps"] == 0 for c in comparisons),
                "comparisons": comparisons}
        summaries.append(summary)
        print(f"{mode}: native calibration={summary['calibration']['nativeMatches']}/14 "
              f"holdout={summary['holdout']['nativeMatches']}/24; backend="
              f"{summary['calibration']['backendMatches']+summary['holdout']['backendMatches']}/38")
    candidates = [summary for summary in summaries if summary["mode"].startswith("cpu_")]
    best = max(c["calibration"]["nativeMatches"] for c in candidates)
    shortlist = [c["mode"] for c in candidates if c["calibration"]["nativeMatches"] == best]
    groups = {}
    for rule, signature in signatures.items():
        groups.setdefault(tuple(signature), []).append(rule)
    result = {"cases": per_case, "measurements": len(measurements), "stableRepeats": True,
        "controls": summaries, "cpuWBitsMatchesProduction": cpu_clip_matches,
        "fusedCpuWChanges": w_changes,
        "cpuVertexComparisons": 57, "identicalCpuWGroups": list(groups.values()),
        "calibrationOnlyCpuShortlist": shortlist,
        "originalBackendDifferentThresholds": sum(row["dx9Bits"] != row["dx11Bits"] for key, row in indexed.items() if key[1] == "production"),
        "limit": "Reference bits are constant float32 ruler inputs, not raw D24 or native W output. Coincident quantized depths do not establish identical native W bits. Perturbation holdout offsets are fixed before measurements.",
        "fullSceneAcceptance": False}
    (directory / "analysis.json").write_text(json.dumps(result, indent=2)+"\n")
    print(f"cpuWBitsMatchesProduction={cpu_clip_matches}/57 shortlist={shortlist} identicalGroups={list(groups.values())}")
    return indexed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", type=Path, nargs="+")
    args = parser.parse_args()
    tables = [load(directory) for directory in args.directories]
    if len(tables) == 2:
        differences = sum(tables[0][key][field] != tables[1][key][field] for key in tables[0] for field in ("dx9Bits", "dx11Bits"))
        print(f"architectureThresholdDifferences={differences}/684")


if __name__ == "__main__":
    main()
