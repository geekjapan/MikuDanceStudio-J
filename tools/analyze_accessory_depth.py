"""Compare completed x64/x86 measurements; completion is not image acceptance."""
import argparse
import csv
import json
from pathlib import Path


def rows(directory, name):
    with (directory / name).open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("x64", type=Path)
    parser.add_argument("x86", type=Path)
    parser.add_argument("--alpha-x64", type=Path, required=True)
    parser.add_argument("--alpha-x86", type=Path, required=True)
    args = parser.parse_args()
    names = ("thresholds.csv", "history_thresholds.csv", "vertices.csv",
             "calibration.csv", "controls.csv", "history_controls.csv",
             "queries.csv", "history_queries.csv")
    measurements = {name: rows(args.x64, name) for name in names}
    exact = all(measurements[name] == rows(args.x86, name) for name in names)
    alpha = rows(args.alpha_x64, "alpha_controls.csv")
    alpha_exact = alpha == rows(args.alpha_x86, "alpha_controls.csv")
    if not exact or not alpha_exact:
        raise ValueError("Architectures differ; inspect CSV evidence before concluding.")
    expected_counts = {"thresholds.csv": 24, "history_thresholds.csv": 12,
                       "vertices.csv": 32, "calibration.csv": 90,
                       "controls.csv": 36, "history_controls.csv": 36,
                       "queries.csv": 3288, "history_queries.csv": 768}
    if any(len(measurements[name]) != count for name, count in expected_counts.items()) or len(alpha) != 96:
        raise ValueError("Incomplete or unexpected measurement scope.")
    for directory in (args.x64, args.x86):
        summary = dict(item.split("=", 1) for item in (directory / "summary.txt").read_text().split())
        if summary.get("thresholdRepeatExact") != "1" or summary.get("vertexRepeatExact") != "1":
            raise ValueError("Fresh GPU repeat checks did not complete.")
    if any(r["gpuBits"] != r["cpuFusedBits"] for r in measurements["vertices.csv"]):
        raise ValueError("Production DX11 vertex observation differs from CPU prediction.")
    if any(r["dx9"] != r["expected"] or r["dx11"] != r["expected"] for r in measurements["calibration.csv"]):
        raise ValueError("Independent depth ruler calibration failed.")
    result = {
        "architectureMeasurementsExact": exact, "architectureAlphaControlsExact": alpha_exact,
        "perArchitectureCounts": expected_counts, "alphaControlRows": len(alpha),
        "isolatedDepthBackendDifferences": sum(r["floatBitDelta"] != "0" for r in measurements["thresholds.csv"]),
        "historyDepthBackendDifferences": sum(r["floatBitDelta"] != "0" for r in measurements["history_thresholds.csv"]),
        "historyD24TickDeltas": {str(after): [int(r["d24TickDelta"]) for r in measurements["history_thresholds.csv"] if r["afterDraw"] == str(after)] for after in (65, 66)},
        "alphaReferenceOne": [r for r in alpha if r["mode"] == "isolated65" and r["reference"] == "1" and r["repeat"] == "0"],
        "rawD24Readback": False, "nativeFixedVertexCapture": False,
        "productionActivation": False, "imageAcceptance": False,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
