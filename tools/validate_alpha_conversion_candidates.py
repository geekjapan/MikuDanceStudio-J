"""Score the frozen CPU shortlist against generated independent GPU fixtures."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from analyze_accessory_alpha import load, repeat_exact
from fit_accessory_alpha_conversion import predict


def read(root):
    with (root / "independent.csv").open(encoding="utf-8", newline="") as source:
        data = list(csv.DictReader(source))
    summary = dict(item.split("=", 1) for item in (root / "summary.txt").read_text().split() if "=" in item)
    if summary.get("complete") != "1" or len(data) != int(summary["rows"]) or not repeat_exact(data, ("geometry", "case", "comparison")):
        raise ValueError(f"Incomplete or unstable independent evidence: {root}")
    return data


def errors(candidate, data):
    byte_errors = comparison_errors = 0
    for row in data:
        q = predict(float(row["dx9FloatAlpha"]), candidate)
        ref = int(row["reference"])
        accepted = {7: q >= ref, 3: q == ref, 6: q != ref}[int(row["comparison"])]
        byte_errors += q != int(row["dx9Byte"])
        comparison_errors += accepted != (row["dx9Pass"] == "1")
    return byte_errors, comparison_errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis", type=Path)
    parser.add_argument("x64", type=Path)
    parser.add_argument("x86", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--real-evidence", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Fresh output file required.")
    original = json.loads(args.analysis.read_text(encoding="utf-8"))
    left, right = read(args.x64), read(args.x86)
    if left != right:
        raise ValueError("Independent observations differ between architectures.")
    data = [r for r in left if r["repeat"] == "0"]
    probes = {str(n): p for n, p in enumerate(original["independentProbes"])}
    expected_keys = {(str(g), case, str(c), str(repeat)) for g in range(2)
                     for case in probes for c in (7, 3, 6) for repeat in range(3)}
    observed_keys = {(r["geometry"], r["case"], r["comparison"], r["repeat"]) for r in left}
    if expected_keys != observed_keys or len(left) != len(expected_keys) or any(
            int(r["inputBits"]) != probes[r["case"]]["inputBits"] or
            int(r["reference"]) != probes[r["case"]]["reference"] for r in left):
        raise ValueError("Fixture inputs do not match the frozen discrimination plan.")
    scores = []
    real = []
    if args.real_evidence:
        stages = load(args.real_evidence, "float_stages.csv")
        colors = load(args.real_evidence, "byte_controls.csv")
        for point in range(6):
            alpha = next(r for r in stages if r["mode"] == "alpha_product" and r["repeat"] == "0" and r["point"] == str(point))
            byte = next(r for r in colors if r["mode"] == "production_no_alpha_test" and r["repeat"] == "0" and r["point"] == str(point))
            gate = next(r for r in colors if r["mode"] == "production_ref1" and r["repeat"] == "0" and r["point"] == str(point))
            real.append({"dx9FloatAlpha": alpha["dx9Alpha"], "reference": "1", "comparison": "7",
                         "dx9Byte": byte["dx9Alpha"], "dx9Pass": "1" if int(gate["dx9R"]) != 0 else "0"})
    for candidate in original["shortlist"]:
        a, b = errors(candidate, data)
        c, d = errors(candidate, real)
        scores.append({**candidate, "independentByteErrors": a, "independentComparisonErrors": b,
                       "realByteErrors": c, "realComparisonErrors": d})
    passed = [s for s in scores if s["validationByteErrors"] == s["validationPredicateErrors"] ==
              s["independentByteErrors"] == s["independentComparisonErrors"] == s["realByteErrors"] == s["realComparisonErrors"] == 0]
    baseline = {"input": "float32", "multiply": "float32", "addition": "float32", "final": "add_half_floor"}
    result = {"architectureExact": True, "repeatExact": True, "rowsPerArchitecture": len(left),
              "uniqueIndependentObservations": len(data), "frozenShortlistCount": len(scores),
              "heldoutAndIndependentZeroErrorCount": len(passed), "scores": scores,
              "frozenProbeInputsExact": True,
              "realPoints": len(real),
              "baselineIndependentErrors": list(errors(baseline, data)),
              "sourceSha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                  (args.analysis, args.x64 / "independent.csv", args.x86 / "independent.csv")},
              "productionActivation": False, "imageAcceptance": False}
    if args.real_evidence:
        for name in ("float_stages.csv", "byte_controls.csv"):
            path = args.real_evidence / name
            result["sourceSha256"][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("scores", "sourceSha256")}, indent=2))


if __name__ == "__main__":
    main()
