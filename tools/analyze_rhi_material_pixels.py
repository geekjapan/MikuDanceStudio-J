"""Verify native material probe reports against their raw 32x32 RGBA targets."""
import argparse
import json
from pathlib import Path


def analyze(directory):
    results = []
    reports = sorted(directory.glob("*.report"))
    if not reports:
        raise ValueError(f"No reports in {directory}")
    for report in reports:
        fields = dict(token.split("=", 1) for token in report.read_text().split())
        a = report.with_name(report.stem + "-dx9.rgba").read_bytes()
        b = report.with_name(report.stem + "-dx11.rgba").read_bytes()
        if len(a) != 32 * 32 * 4 or len(b) != len(a):
            raise ValueError(f"Invalid target size: {report}")
        differences = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        pixels = len({i // 4 for i in differences})
        maximum = max((abs(a[i] - b[i]) for i in differences), default=0)
        expected = (1024, pixels, len(differences), maximum)
        recorded = tuple(int(fields[key]) for key in
                         ("pixels", "differingPixels", "differingChannels", "maxError"))
        if recorded != expected or fields["status"] != ("BLOCKED" if differences else "PASS"):
            raise ValueError(f"Report disagrees with target bytes: {report}")
        first = None
        if differences:
            i = differences[0]
            first = {"x": i // 4 % 32, "y": i // 4 // 32,
                     "channel": "RGBA"[i % 4], "dx9": a[i], "dx11": b[i]}
        results.append({**fields, "firstDifference": first})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = analyze(args.directory)
    summary = {"cases": results,
               "passed": sum(row["status"] == "PASS" for row in results),
               "blocked": sum(row["status"] == "BLOCKED" for row in results)}
    if args.output:
        args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(results)} target pairs: {summary['passed']} PASS, {summary['blocked']} BLOCKED")
    return 2 if summary["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
