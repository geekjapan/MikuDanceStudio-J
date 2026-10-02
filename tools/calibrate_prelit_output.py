"""Fit output rounding and effective ramp position to resolved probe images.

This does not read individual MSAA samples or identify pixel shader invocation rate.
"""
import argparse
import json
import math
from pathlib import Path


def read(root, samples, phase, path):
    data = (root / f"s{samples}-t1-w0-c{4 + phase}-m0-p{path}.bgra").read_bytes()
    if len(data) != 256 * 256 * 4:
        raise ValueError("unexpected image dimensions")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    # All points well inside the first triangle, with room for all MSAA samples.
    coordinates = [(x, y) for y in range(80, 121, 3) for x in range(80, 141, 3)]
    rules = {"floor": math.floor, "half_up": lambda x: math.floor(x + .5),
             "ties_even": round}
    result = {"interpretation": "effective location from full-coverage resolved ramps; not per-sample readback",
              "pointsPerPhase": len(coordinates), "fits": [], "constantBlue": []}
    for samples in (1, 8):
        for path in (3, 5, 6, 7):
            images = [read(args.root, samples, phase, path) for phase in range(8)]
            result["constantBlue"].append({"samples": samples, "path": path,
                                          "phaseValuesAt96_96": [im[(96 * 256 + 96) * 4] for im in images]})
            for channel, axis, origin in ((2, 0, 32.25), (1, 1, 35.5)):
                candidates = []
                for name, rule in rules.items():
                    for step in range(-8, 9):
                        offset = step / 16
                        different = error = 0
                        for phase, image in enumerate(images):
                            for x, y in coordinates:
                                observed = image[(y * 256 + x) * 4 + channel]
                                expected = rule((x, y)[axis] - origin + phase / 8 + offset)
                                different += observed != expected
                                error += abs(observed - expected)
                        candidates.append({"rule": name, "offsetPixels": offset,
                                           "differentChannels": different, "totalAbsoluteError": error})
                best = min(row["totalAbsoluteError"] for row in candidates)
                result["fits"].append({"samples": samples, "path": path,
                                      "channel": "R" if channel == 2 else "G",
                                      "bestError": best,
                                      "bestCandidates": [row for row in candidates if row["totalAbsoluteError"] == best]})
    result["interpolatedVersusVPOS"] = []
    for samples in (1, 8):
        coverage = (args.root / f"s{samples}-t1-w0-c0-m0-p0.bgra").read_bytes()
        for phase in range(8):
            a, b = read(args.root, samples, phase, 3), read(args.root, samples, phase, 7)
            differences = [at for at in range(0, len(a), 4) if a[at:at+4] != b[at:at+4]]
            full = sum(coverage[at:at+4] == bytes((192, 128, 64, 255)) for at in differences)
            result["interpolatedVersusVPOS"].append({"samples": samples, "phase": phase,
                "differentPixels": len(differences), "combinedFullCoverage": full})
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    for row in result["constantBlue"]:
        print(row)
    for row in result["fits"]:
        print("FIT", "samples=" + str(row["samples"]), "path=" + str(row["path"]), row["channel"], "error=" + str(row["bestError"]), "candidates=" + str(len(row["bestCandidates"])))


if __name__ == "__main__":
    main()
