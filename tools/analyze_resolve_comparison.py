"""Apply measured conversion and resolve controls to packed fixed/explicit draws."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from analyze_edge_quantization import rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("x64", type=Path)
    parser.add_argument("x86", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    names = ("quantization.csv", "coverage.csv", "edges.csv", "resolve.csv", "comparison.csv")
    arch = [name for name in names if (args.x64/name).read_bytes() != (args.x86/name).read_bytes()]
    coverage = rows(args.x64, "coverage.csv")
    covered = {(r["axis"], r["step"], r["sample"]): r["coverageByte"] != 0 for r in coverage}
    bounds = {}
    for axis in (0, 1):
        for sample in range(8):
            first = next(k for k in range(65) if covered[axis,k,sample])
            bounds[axis,sample] = -.5 + (first-1)/64
    empirical = defaultdict(set)
    for r in rows(args.x64, "resolve.csv"):
        if r["samples"] == 8:
            k = sum(covered[r["axis"],r["step"],s] for s in range(8))
            empirical[k,r["source"]].add(r["R"])
    inconsistent = [str(key) for key, values in empirical.items() if len(values) != 1]
    if inconsistent:
        raise ValueError("resolve depends on more than count/color: " + str(inconsistent))
    curve = {key: next(iter(values)) for key, values in empirical.items()}
    quant = {(r["base"],r["step"]): r["R"] for r in rows(args.x64,"quantization.csv") if r["samples"] == 8 and r["path"] == 0}
    data = rows(args.x64, "comparison.csv")
    index = {(r["samples"],r["axis"],r["step"],r["phase"],r["mask"],r["path"]): r for r in data}
    summary = []
    for samples in (1,8):
        for path in (7,8,9,10,11):
            for mask_kind in ("full","individual"):
                group = [r for r in data if r["samples"] == samples and r["path"] == path and bool(r["mask"]) == (mask_kind == "individual")]
                if not group:
                    continue
                summary.append({"samples": samples, "path": path, "maskKind": mask_kind,
                                "drawsCompared": len(group), "differentImages": sum(r["differentPixels"] != 0 for r in group),
                                "sumDifferentPixels": sum(r["differentPixels"] for r in group),
                                "maxChannel": max(r["maxChannel"] for r in group)})
    # Independent vertices-versus-pixel-stage control, at the observed pixel.
    stage_delta = sum(any(r[c] != index[r["samples"],r["axis"],r["step"],r["phase"],r["mask"],8][c] for c in ("B","G","R","A")) for r in data if r["path"] == 7)
    model = []
    inverse = []
    for path in (6,7,8):
        group = [r for r in data if r["samples"] == 8 and r["mask"] == 0 and r["path"] == path and 0 < sum(covered[r["axis"],r["step"],s] for s in range(8)) < 8]
        for hypothesis in ("pixel_center", "lowest_covered_index_at_bracket_lower_bound"):
            different = absolute = outside = bracket_incompatible = 0
            examples = []
            for r in group:
                axis, step = r["axis"],r["step"]
                samples_on = [s for s in range(8) if covered[axis,step,s]]
                offset = 0 if hypothesis == "pixel_center" else bounds[axis,samples_on[0]]
                origin_color = r["leftR" if axis == 0 else "topG"]
                boundary_color = r["rightR" if axis == 0 else "bottomG"]
                boundary = 30.5+step/64
                value = origin_color+(31+offset+.5)*(boundary_color-origin_color)/(boundary+.5)
                base = math.floor(value)
                # Quantization input is rounded to scan resolution; fit is not an exact arithmetic reconstruction.
                fraction = round((value-base)*64)
                if (base,fraction) not in quant:
                    outside += 1
                    continue
                coded = quant[base,fraction]
                predicted = curve[len(samples_on),coded]
                neighbors = {quant[base, math.floor((value-base)*64)], quant[base, math.ceil((value-base)*64)]}
                bracket_predictions = sorted({curve[len(samples_on), byte] for byte in neighbors})
                observed = r["R" if axis == 0 else "G"]
                bracket_incompatible += observed not in bracket_predictions
                different += predicted != observed
                absolute += abs(predicted-observed)
                if predicted != observed and len(examples) < 8:
                    examples.append({"axis": axis,"step": step,"phase": r["phase"],"predicted": predicted,"observed": observed,"coded": coded,"bracketPredictions": bracket_predictions})
            model.append({"path": path,"hypothesis": hypothesis,"channelsCompared": len(group)-outside,"outsideCalibration": outside,"differentChannels": different,"absoluteError": absolute,"bracketIncompatibleChannels": bracket_incompatible,"examples": examples})
        for r in group:
            k = sum(covered[r["axis"],r["step"],s] for s in range(8))
            output = r["R" if r["axis"] == 0 else "G"]
            candidates = [source for (count,source), value in curve.items() if count == k and 120 <= source <= 128 and value == output]
            inverse.append({"axis": r["axis"],"step":r["step"],"phase":r["phase"],"path":path,"covered":k,"observed":output,"compatibleSourceBytes": candidates})
    center = [r for r in data if r["path"] == 9 and r["mask"] == 0]
    center_index = {(r["samples"],r["axis"],r["step"],r["phase"]): r for r in center}
    center_consistency = sum(bool(r["differentPixels"]) != bool(center_index[8,r["axis"],r["step"],r["phase"]]["differentPixels"]) for r in center if r["samples"] == 1)
    result = {"pixelCenterControlDifferentCaseClassificationBetween1x8x":center_consistency,
              "crossArchitectureDifferentFiles": arch,"imageComparisons":summary,"fixedVS_explicitPS_vs_explicitVS_observedPixelDifferentCases":stage_delta,
              "predictionModel":"affine packed color; quantization sampled at 1/64 byte; empirical nonlinear resolve",
              "hypothesisResults":model,"inverseResolve":inverse,"vertexControlDifferentImages":sum(r["vertexControlDifferentPixels"]!=0 for r in data if r["path"]==8),
              "interpretation":"diagnostic predictions, not equivalent images, original per-sample readback, or proof of a sampling algorithm"}
    args.output.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print("architecture differences",arch)
    print("image comparisons",summary)
    print("stage control differing cases",stage_delta)
    for r in model:
        print({k:v for k,v in r.items() if k != "examples"})
    print("inverse unresolved",sum(not r["compatibleSourceBytes"] for r in inverse))
    return bool(arch)


if __name__ == "__main__":
    raise SystemExit(main())
