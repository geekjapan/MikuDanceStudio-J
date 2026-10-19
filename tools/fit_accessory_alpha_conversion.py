"""Test explicit arithmetic hypotheses on saved observations, with held-out refs.

No GPU access, fitted offsets, production shader changes or tolerance changes.
Counts use unique observations rather than counting three repeats as new data.
"""
import argparse
import csv
import hashlib
import itertools
import json
import math
import struct
from pathlib import Path

from analyze_accessory_alpha import load, repeat_exact

TRAIN = {1, 17, 127}
VALIDATE = {2, 254}


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def bits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def value(u):
    return struct.unpack("<f", struct.pack("<I", u))[0]


def quantize(x, representation):
    if representation == "double":
        return x
    x = f32(x)
    if representation == "float32":
        return x
    if representation == "half_even":
        return struct.unpack("<e", struct.pack("<e", x))[0]
    kind, precision, rounding = representation.split(":")
    precision = int(precision)
    if kind == "fixed":
        scaled = math.ldexp(x, precision)
        integer = math.floor(scaled) if rounding == "truncate" else round(scaled)
        return math.ldexp(integer, -precision)
    # Positive float32 with reduced mantissa. Keep the full exponent range;
    # this differs from IEEE half and is explicitly labelled as a hypothesis.
    u = bits(x)
    shift = 23 - precision
    integer, remainder = divmod(u, 1 << shift)
    if rounding == "even" and (remainder > 1 << (shift - 1) or
                                remainder == 1 << (shift - 1) and integer & 1):
        integer += 1
    return value(integer << shift)


def predict(alpha, candidate):
    a = quantize(max(0., min(1., alpha)), candidate["input"])
    product = quantize(a * 255., candidate["multiply"])
    final = candidate["final"]
    if final == "floor":
        result = math.floor(product)
    elif final == "even":
        result = round(product)
    else:
        result = math.floor(quantize(product + .5, candidate["addition"]))
    return max(0, min(255, result))


def observations(root):
    inputs = [(root / "accessory-alpha-scan-retry-x64" / "constant_alpha.csv", "constant"),
              (root / "accessory-alpha-references-recovered-x64" / "reference_scan.csv", "coarse"),
              (root / "accessory-alpha-reference-fine-x64" / "reference_scan.csv", "fine")]
    result, hashes = [], {}
    for path, scope in inputs:
        records = load(path.parent, path.name)
        keys = ("inputBits", "comparison", "point") if scope == "constant" else ("reference", "step")
        if not (path.parent / "summary.txt").exists() or not repeat_exact(records, keys):
            raise ValueError(f"Incomplete or unstable observations: {path}")
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        for row in records:
            if row["repeat"] != "0":
                continue
            ref = 1 if scope == "constant" else int(row["reference"])
            comparison = int(row["comparison"]) if scope == "constant" else 7
            result.append({"scope": scope, "reference": ref, "comparison": comparison,
                           "alpha": float(row["dx9FloatAlpha"]),
                           "byte": int(row["dx9Alpha" if scope == "constant" else "dx9Byte"]),
                           "accepted": row["dx9PassRef1" if scope == "constant" else "dx9Pass"] == "1"})
    return result, hashes


def metrics(candidate, data):
    byte_errors = predicate_errors = 0
    for row in data:
        predicted = predict(row["alpha"], candidate)
        actual = {7: predicted >= row["reference"], 3: predicted == row["reference"],
                  6: predicted != row["reference"]}[row["comparison"]]
        byte_errors += predicted != row["byte"]
        predicate_errors += actual != row["accepted"]
    return byte_errors, predicate_errors


def candidates():
    floating = ["double", "float32", "half_even"] + [
        f"mantissa:{p}:{mode}" for p in (8, 10, 12, 16, 20) for mode in ("truncate", "even")]
    inputs = floating + [f"fixed:{p}:{mode}" for p in (8, 10, 12, 16) for mode in ("truncate", "even")]
    products = floating + [f"fixed:{p}:{mode}" for p in (0, 2, 4, 8, 12) for mode in ("truncate", "even")]
    additions = floating + [f"fixed:{p}:{mode}" for p in (0, 2, 4, 8) for mode in ("truncate", "even")]
    for i, m in itertools.product(inputs, products):
        for final in ("floor", "even"):
            yield {"input": i, "multiply": m, "addition": "double", "final": final}
        for a in additions:
            yield {"input": i, "multiply": m, "addition": a, "final": "add_half_floor"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Fresh output directory required.")
    data, hashes = observations(args.evidence)
    train = [r for r in data if r["reference"] in TRAIN]
    validation = [r for r in data if r["reference"] in VALIDATE]
    all_candidates = list(candidates())
    scores = [{"id": n, **c, "trainByteErrors": metrics(c, train)[0],
               "trainPredicateErrors": metrics(c, train)[1]} for n, c in enumerate(all_candidates)]
    best = min((r["trainByteErrors"], r["trainPredicateErrors"]) for r in scores)
    # Freeze shortlist using training results only. Validation cannot change it.
    shortlisted = [r["id"] for r in scores if (r["trainByteErrors"], r["trainPredicateErrors"]) == best]
    for row in scores:
        row["validationByteErrors"], row["validationPredicateErrors"] = metrics(row, validation)
    args.output.mkdir(parents=True)
    with (args.output / "candidate_errors.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(scores[0]))
        writer.writeheader()
        writer.writerows(scores)
    selected = [scores[n] for n in shortlisted]
    # Preserve candidates that agree on saved data but disagree on new inputs.
    # Choose representatives by the union of saved and independent probe-grid
    # predictions, not merely the saved observations.
    grid = [(ref, f32((ref - 1 + step / 64.) / 255.))
            for ref in (3, 7, 31, 63, 191, 253) for step in range(1, 64)]
    representatives = {}
    for n in shortlisted:
        key = (tuple(predict(r["alpha"], all_candidates[n]) for r in data),
               tuple(predict(alpha, all_candidates[n]) for _, alpha in grid))
        representatives.setdefault(key, n)
    # Search unused reference values and input fractions, never tuning a rule.
    probes = []
    for ref, alpha in grid:
        predictions = {str(n): predict(alpha, all_candidates[n]) for n in representatives.values()}
        baseline = predict(alpha, {"input": "float32", "multiply": "float32", "addition": "float32", "final": "add_half_floor"})
        if len(set(predictions.values())) > 1 or any(v != baseline for v in predictions.values()):
            probes.append({"reference": ref, "inputAlpha": alpha, "inputBits": bits(alpha),
                           "baseline": baseline, "predictedBytes": predictions})
    chosen = []
    for ref in (3, 7, 31, 63, 191, 253):
        group = [p for p in probes if p["reference"] == ref]
        # Prefer actual disagreement between the training-best candidates.
        group.sort(key=lambda p: (-len(set(p["predictedBytes"].values())), p["inputBits"]))
        chosen.extend(group[:2])
    with (args.output / "probe_inputs.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=("case", "reference", "inputBits"))
        writer.writeheader()
        for n, p in enumerate(chosen):
            writer.writerow({"case": n, "reference": p["reference"], "inputBits": p["inputBits"]})
    summary = {"trainingReferences": sorted(TRAIN), "validationReferences": sorted(VALIDATE),
               "trainingRows": len(train), "validationRows": len(validation),
               "repeatCounting": "one per distinct observation; repeats checked separately",
               "candidateCount": len(scores), "bestTrainingErrors": list(best),
               "shortlistFrozenBeforeValidation": True, "shortlist": selected,
               "predictionClassRepresentatives": list(representatives.values()),
               "independentProbes": chosen, "sourceSha256": hashes,
               "productionActivation": False, "imageAcceptance": False}
    (args.output / "analysis.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k in (
        "candidateCount", "bestTrainingErrors", "trainingRows", "validationRows", "predictionClassRepresentatives")}, indent=2))
    print(f"shortlist={len(selected)} independentProbes={len(chosen)}")


if __name__ == "__main__":
    main()
