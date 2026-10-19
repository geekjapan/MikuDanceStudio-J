"""Validate shared-clip and component controls for perspective holdout case 10."""
import argparse
import csv
import json
from pathlib import Path
import struct
from analyze_sensitive_depth import clip_plane, fbits


VARIANTS = ("production", "shared_clip", "native_dot", "native_ordered",
            "native_reverse", "native_paired", "native_dot_z", "native_dot_w",
            "native_dot_zw", "native_dot_xy", "cycle1", "cycle2", "reverse",
            "homogeneous2", "homogeneous8", "ndc", "short_edge1", "short_edge2")
POINTS = ((36, 46), (20, 42))


def vertices(path):
    data = path.read_bytes()
    if len(data) != 48:
        raise ValueError(f"incorrect vertex count: {path}")
    return list(struct.iter_unpack("<4f", data))


def load(directory):
    with (directory / "measurements.csv").open(newline="") as file:
        rows = list(csv.DictReader(file))
    indexed = {}
    for row in rows:
        key = row["variant"], int(row["x"]), int(row["y"])
        if key in indexed or row["repeatExact"] != "1":
            raise ValueError("duplicate measurement or unstable boundary")
        indexed[key] = row
    if indexed.keys() != {(variant, x, y) for variant in VARIANTS for x, y in POINTS}:
        raise ValueError("incomplete control matrix")
    if (directory / "production_output.clip").read_bytes() != (directory / "shared_clip-dx11.clip").read_bytes():
        raise ValueError("shared-clip path did not preserve production clip bits")
    production = vertices(directory / "production_output.clip")
    raw = vertices(directory / "raw.clip")
    original_thresholds = list(csv.DictReader((directory.parent.parent / "perspective-depth" / directory.name / "thresholds.csv").open(newline="")))
    for x, y in POINTS:
        reference = next(row for row in original_thresholds if row["case"] == "10" and row["mode"] == "left_sequential" and int(row["x"]) == x and int(row["y"]) == y)
        measured = indexed["production", x, y]
        if measured["dx9Bits"] != reference["dx9ThresholdBits"] or measured["dx11Bits"] != reference["dx11ThresholdBits"]:
            raise ValueError("original sensitive-experiment threshold did not reproduce")
    summaries = []
    for name in VARIANTS:
        observed = vertices(directory / f"{name}-dx11.clip")
        source = vertices(directory / f"{name}.clip")
        if name.startswith("native_") and observed != production:
            raise ValueError("DX11 side of native instruction control changed")
        controls = []
        for x, y in POINTS:
            row = indexed[name, x, y]
            baseline = indexed["shared_clip", x, y]
            plane = clip_plane(observed, x, y)
            base_plane = clip_plane(production, x, y)
            controls.append({"x": x, "y": y, "dx9Bits": int(row["dx9Bits"]), "dx11Bits": int(row["dx11Bits"]),
                "backendReferenceStepDelta": int(row["dx9Bits"])-int(row["dx11Bits"]),
                "nativeVersusSharedClipReferenceSteps": int(row["dx9Bits"])-int(baseline["dx9Bits"]),
                "doublePlane": plane, "doublePlaneDeltaVersusProduction": plane-base_plane,
                "doublePlaneDeltaInReferenceSteps": (plane-base_plane)/2**-24,
                "roundedDoublePlaneBitsMinusDX11Reference": fbits(plane)-int(row["dx11Bits"])})
        summaries.append({"variant": name, "observedDX11ClipBitsMatchProduction": (directory / f"{name}-dx11.clip").read_bytes() == (directory / "production_output.clip").read_bytes(), "coordinates": controls})
        print(f"{name}: backendDeltas={[c['backendReferenceStepDelta'] for c in controls]} "
              f"idealPlaneChangesInSteps={[round(c['doublePlaneDeltaInReferenceSteps'], 4) for c in controls]}")
        if name in ("homogeneous2", "homogeneous8"):
            scale = int(name.removeprefix("homogeneous"))
            if any(observed[n][k] != production[n][k]*scale or source[n][k] != raw[n][k]*scale for n in range(3) for k in range(4)):
                raise ValueError("homogeneous power-of-two scaling was not exact")
    result = {"measurements": len(rows), "productionClipBypassBitsExact": True,
        "repeatExact": True, "controls": summaries,
        "limit": "No native fixed-function clip output is captured. Programmable dp4 and partial-component controls reproduce depth relations; CPU double planes only quantify input rounding and geometry changes, not a native raster model.",
        "fullSceneAcceptance": False}
    (directory / "analysis.json").write_text(json.dumps(result, indent=2)+"\n")
    return indexed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", type=Path, nargs="+")
    args = parser.parse_args()
    tables = [load(directory) for directory in args.directories]
    if len(tables) == 2:
        differences = sum(tables[0][key][field] != tables[1][key][field] for key in tables[0] for field in ("dx9Bits", "dx11Bits"))
        print(f"architectureThresholdDifferences={differences}/72")


if __name__ == "__main__":
    main()
