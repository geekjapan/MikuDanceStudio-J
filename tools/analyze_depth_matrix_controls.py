"""Compare diagnostic matrix candidates with measured original DX9 thresholds."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import struct
import sys


MODES = {7: "wv_float", 8: "wv_double", 9: "wvp_left_float",
         10: "wvp_left_double", 11: "wvp_right_float", 12: "wvp_right_double",
         13: "wv_paired", 14: "wvp_left_paired", 15: "wvp_left_fused", 16: "wv_fused"}


def load_checked(directory):
    subprocess.run([sys.executable, str(Path(__file__).with_name("analyze_coplanar_depth.py")),
                    str(directory / "measurements.csv")], check=True, stdout=subprocess.DEVNULL)
    return json.loads((directory / "measurements.json").read_text())


def key(probe):
    return probe["pair"], probe["triangle"], probe["x"], probe["y"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--modes", type=int, choices=MODES, nargs="+", default=list(MODES))
    args = parser.parse_args()
    baseline = load_checked(args.reference / "coplanar-depth-hardware")
    original = {key(p): p for p in baseline["measuredThresholds"]}
    results = []
    for mode in args.modes:
        name = MODES[mode]
        data = load_checked(args.reference / f"coplanar-depth-hardware-{name}")
        with (args.reference / f"coplanar-depth-hardware-{name}" / "measurements.csv").open(newline="") as file:
            rows = list(csv.DictReader(file))
        image_rows = [r for r in rows if r["kind"].startswith(("pair", "range_"))]
        if len(image_rows) != 100:
            raise ValueError(f"{name}: incomplete pair control matrix")
        probe_rows = [r for r in rows if r["kind"] == "probe"]
        probes = {key(p): p for p in data["measuredThresholds"]}
        if not original.keys() <= probes.keys():
            raise ValueError(f"{name}: missing original validation coordinates")
        changes = {}
        for backend in ("dx9", "dx11"):
            deltas = Counter(probes[k][backend]["equalReferenceBits"] - p[backend]["equalReferenceBits"]
                             for k, p in original.items())
            changes[backend] = {"differentThresholds": sum(count for delta, count in deltas.items() if delta),
                                "referenceStepDeltas": dict(sorted(deltas.items()))}
        image_changes = {}
        for backend in ("Native", "DX11"):
            rows = [r for r in data["bakedVersusOriginalImages"] if r["comparison"] == backend]
            if len(rows) != 5:
                raise ValueError(f"{name}: incomplete original-image comparison")
            image_changes[backend] = {"changedPairs": sum(int(r["differentPixels"]) != 0 for r in rows),
                                      "sumChangedPixels": sum(int(r["differentPixels"]) for r in rows)}
        result = {"mode": mode, "name": name,
                  "matrixBytesSHA256": hashlib.sha256((args.reference / f"coplanar-depth-hardware-{name}" / "candidate_matrices.bin").read_bytes()).hexdigest(),
                  "originalThresholdsChecked": len(original), "thresholdChanges": changes,
                  "originalOrderPairImageChanges": image_changes,
                  "backendDifferingThresholds": data["differentThresholds"],
                  "pairImagesCompared": len(image_rows),
                  "backendMismatchingPairImages": sum(int(r["differentPixels"]) != 0 for r in image_rows),
                  "referenceProbeComparisons": len(probe_rows),
                  "backendDifferingReferenceProbes": sum(r["dx9"] != r["dx11"] for r in probe_rows),
                  "holdoutCoordinates": data["holdoutCoordinates"],
                  "originalOrderBackendMismatchingPairs": sum(int(r["differentPixels"]) != 0
                      for r in data["pairComparisons"] if r["comparison"] == "LessEqual" and r["order"] == "0"),
                  "matchesMeasuredOriginalDX9": not changes["dx9"]["differentThresholds"]
                      and not image_changes["Native"]["sumChangedPixels"],
                  "fullSceneAcceptance": False}
        results.append(result)
        print(f"{name}: originalDX9imageChanges={image_changes['Native']['sumChangedPixels']} "
              f"originalDX9thresholdChanges={changes['dx9']['differentThresholds']}/{len(original)} "
              f"backendThresholdDifferences={data['differentThresholds']}")
    output = args.reference / "matrix_controls.json"
    matrix_groups = {}
    for result in results:
        matrix_groups.setdefault(result["matrixBytesSHA256"], []).append(result["name"])
    coefficient_differences = []
    if 9 in args.modes and 11 in args.modes:
        left = (args.reference / "coplanar-depth-hardware-wvp_left_float" / "candidate_matrices.bin").read_bytes()
        right = (args.reference / "coplanar-depth-hardware-wvp_right_float" / "candidate_matrices.bin").read_bytes()
        if len(left) != 192 or len(right) != 192:
            raise ValueError("incorrect candidate matrix byte count")
        for index in range(48):
            at = index * 4
            if left[at:at + 4] != right[at:at + 4]:
                coefficient_differences.append({"matrix": ("world", "view", "projection")[index // 16],
                    "row": index % 16 // 4, "column": index % 4,
                    "leftFloat": struct.unpack_from("<f", left, at)[0],
                    "rightFloat": struct.unpack_from("<f", right, at)[0],
                    "leftBits": hex(struct.unpack_from("<I", left, at)[0]),
                    "rightBits": hex(struct.unpack_from("<I", right, at)[0])})
    output.write_text(json.dumps({"scope": "Five original-order ID pair images and all previously measured native coordinates; reference bits are float32 ruler inputs, not raw D24 codes. No DX9 vertex-output capture.",
                                 "identicalMatrixGroups": list(matrix_groups.values()),
                                 "wvpLeftRightCoefficientDifferences": coefficient_differences,
                                 "candidates": results}, indent=2) + "\n")
    for group in matrix_groups.values():
        print("identicalMatrixBytes=" + ",".join(group))
    for difference in coefficient_differences:
        print(f"parenthesizationCoefficient={difference}")
    print(f"output={output}")


if __name__ == "__main__":
    main()
