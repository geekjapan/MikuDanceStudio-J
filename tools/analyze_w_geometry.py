"""Evaluate the fixed W hypotheses on independent nonzero-Z geometry."""
import argparse
import csv
import json
from pathlib import Path
import struct
from analyze_w_perturb import MODES, bits, read_csv
from analyze_perspective_case10 import vertices
from generate_sensitive_depth_matrices import dot


POINTS = ((36, 46), (20, 42), (28, 44))


def load(directory, fixture=None, gpu=False):
    fixture = fixture or directory.parent / "fixtures.bin"
    manifest = json.loads(fixture.with_suffix(".json").read_text())
    fixture_bytes = fixture.read_bytes()
    if fixture_bytes[:8] != b"WGEOM001" or len(fixture_bytes) != 12+12*112 or struct.unpack_from("<I", fixture_bytes, 8)[0] != 12:
        raise ValueError("incorrect independent fixture format")
    expected_cases = manifest["cases"]
    if len(expected_cases) != 12 or manifest["points"] != [list(point) for point in POINTS]:
        raise ValueError("incorrect independent case/coordinate manifest")
    indexed = {}
    rows = read_csv(directory / "measurements.csv")
    for row in rows:
        prefix, mode = row["variant"].split("_", 1)
        key = int(prefix[1:]), mode, int(row["x"]), int(row["y"])
        if not prefix.startswith("g") or key in indexed or row["repeatExact"] != "1":
            raise ValueError("invalid or unstable measurement")
        indexed[key] = row
    modes = MODES + (("gpu_shader",) if gpu else ())
    if indexed.keys() != {(case, mode, x, y) for case in range(12) for mode in modes for x, y in POINTS}:
        raise ValueError("incomplete independent geometry matrix")
    signatures = {rule: [] for rule in ("sequential", "double", "paired", "fused")}
    bit_matches = dict.fromkeys(signatures, 0)
    w_min, w_max = float("inf"), 0.
    for number, case in enumerate(expected_cases):
        if case["id"] != number or case["split"] != ("calibration" if number < 6 else "holdout"):
            raise ValueError("preassigned geometry split changed")
        matrix_bytes = (directory / f"g{number}.matrix").read_bytes()
        object_bytes = (directory / f"g{number}.object").read_bytes()
        if matrix_bytes+object_bytes != fixture_bytes[12+number*112:12+(number+1)*112]:
            raise ValueError("measured input differs from fixed binary fixture")
        if struct.pack("<28f", *(case["matrix"]+[v for p in case["objects"] for v in p])) != matrix_bytes+object_bytes:
            raise ValueError("JSON/binary independent fixture mismatch")
        matrix = struct.unpack("<16f", matrix_bytes)
        objects = vertices(directory / f"g{number}.object")
        if not all(v != 0 for v in matrix[3::4]) or any(any(v == 0 for v in p) for p in objects):
            raise ValueError("four nonzero W terms are not exercised")
        if any(p[3] != 1 for p in objects):
            raise ValueError("object W convention changed")
        raw = vertices(directory / f"g{number}_shared_clip.clip")
        if any(p[2] != 3 or p[3] <= 0 for p in raw):
            raise ValueError("constant clip Z/positive W control changed")
        w_min = min(w_min, *(p[3] for p in raw))
        w_max = max(w_max, *(p[3] for p in raw))
        production = (directory / f"g{number}_production_output.clip").read_bytes()
        for mode in MODES[:5]:
            if (directory / f"g{number}_{mode}-dx11.clip").read_bytes() != production:
                raise ValueError("DX11 clip output changed in the native instruction control")
        per_case_signatures = []
        for rule in signatures:
            candidate = vertices(directory / f"g{number}_cpu_{rule}.clip")
            candidate_w = []
            for n in range(3):
                expected = dot(objects[n], matrix[3::4], rule)
                if candidate[n][:3] != raw[n][:3] or bits(candidate[n][3]) != bits(expected) or bits(expected) != bits(case["cpuW"][rule][n]):
                    raise ValueError("independent CPU W kernel or held-fixed components disagree")
                candidate_w.append(bits(expected))
                signatures[rule].append(bits(expected))
                bit_matches[rule] += bits(expected) == bits(raw[n][3])
            per_case_signatures.append(tuple(candidate_w))
        if len(set(per_case_signatures)) < 3 or per_case_signatures[0] in (per_case_signatures[2], per_case_signatures[3]):
            raise ValueError("selected independent geometry does not distinguish candidates")
        if gpu:
            captured = vertices(directory / f"g{number}_gpu_shader.clip")
            fused = vertices(directory / f"g{number}_cpu_fused.clip")
            if struct.pack("<12f", *(v for p in captured for v in p)) != struct.pack("<12f", *(v for p in fused for v in p)):
                raise ValueError("GPU candidate W/held-fixed XYZ differs from CPU fused candidate")
            if (directory / f"g{number}_gpu_final.clip").read_bytes() != (directory / f"g{number}_gpu_shader-dx11.clip").read_bytes():
                raise ValueError("GPU candidate final position differs from shared candidate passthrough")
            for x, y in POINTS:
                if indexed[number, "gpu_shader", x, y]["dx9Bits"] != indexed[number, "production", x, y]["dx9Bits"]:
                    raise ValueError("GPU candidate comparison changed original native threshold")
    summaries = []
    for mode in modes[1:]:
        summary = {"mode": mode}
        for split, case_numbers in (("calibration", range(6)), ("holdout", range(6, 12))):
            comparisons = []
            for case in case_numbers:
                for x, y in POINTS:
                    row = indexed[case, mode, x, y]
                    native = int(indexed[case, "production", x, y]["dx9Bits"])
                    comparisons.append({"case": case, "x": x, "y": y,
                        "nativeMinusOriginalNativeSteps": int(row["dx9Bits"])-native,
                        "dx11MinusOriginalNativeSteps": int(row["dx11Bits"])-native,
                        "backendStepDelta": int(row["dx9Bits"])-int(row["dx11Bits"])})
            summary[split] = {"total": len(comparisons),
                "nativeMatches": sum(c["nativeMinusOriginalNativeSteps"] == 0 for c in comparisons),
                "dx11Matches": sum(c["dx11MinusOriginalNativeSteps"] == 0 for c in comparisons),
                "backendMatches": sum(c["backendStepDelta"] == 0 for c in comparisons), "comparisons": comparisons}
        summaries.append(summary)
        print(f"{mode}: native calibration={summary['calibration']['nativeMatches']}/18 "
              f"holdout={summary['holdout']['nativeMatches']}/18; backend="
              f"{summary['calibration']['backendMatches']+summary['holdout']['backendMatches']}/36")
    groups = {}
    for rule, values in signatures.items():
        groups.setdefault(tuple(values), []).append(rule)
    result = {"measurements": len(rows), "stableRepeats": True,
        "fixedHypothesis": "cpu_fused from the preceding W perturbation, not selected again on these data",
        "controls": summaries, "cpuWBitsMatchesProduction": bit_matches,
        "cpuVertexComparisons": 36, "identicalCpuWGroups": list(groups.values()),
        "clipZConstant": 3, "observedPositiveWRange": [w_min, w_max],
        "originalBackendDifferentThresholds": sum(row["dx9Bits"] != row["dx11Bits"] for key, row in indexed.items() if key[1] == "production"),
        "limit": "Independent synthetic four-term W geometries with constant clip Z; depth ruler bits are not native W output or raw D24. The fused candidate is evaluated unchanged regardless of its matches.",
        "fullSceneAcceptance": False}
    if gpu:
        result["gpuVerification"] = {"cpuFmaWBitsExact": 36, "heldXYZBitsExact": 36,
            "finalPositionMatchesSharedCandidate": 36, "nativeReferenceUnchanged": True,
            "implementation": "double product/add rounded to float after each term, tested inputs only"}
    (directory / "analysis.json").write_text(json.dumps(result, indent=2)+"\n")
    print(f"CPU W bits matching production={bit_matches}/36 identicalGroups={list(groups.values())}")
    return indexed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", type=Path, nargs="+")
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--gpu", action="store_true")
    args = parser.parse_args()
    tables = [load(directory, args.fixtures, args.gpu) for directory in args.directories]
    if len(tables) == 2:
        if tables[0].keys() != tables[1].keys():
            raise ValueError("architecture measurement sets differ")
        differences = sum(tables[0][key][field] != tables[1][key][field] for key in tables[0] for field in ("dx9Bits", "dx11Bits"))
        print(f"architectureThresholdDifferences={differences}/{len(tables[0])*2}")


if __name__ == "__main__":
    main()
