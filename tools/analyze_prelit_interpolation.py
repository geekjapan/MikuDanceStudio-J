"""Compare exported prelit probe images; no GPU or third-party dependency."""
import argparse
from collections import Counter
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("x64", type=Path)
    parser.add_argument("x86", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    files = sorted(args.x64.glob("s*-p[0-7].bgra"))
    if not files:
        parser.error("no baseline probe images")
    arch_differences = []
    for file in files:
        other = args.x86 / file.name
        if not other.exists() or file.read_bytes() != other.read_bytes():
            arch_differences.append(file.name)
    rows = []
    for file in sorted(args.x64.glob("s*-m0-p0.bgra")):
        tag = file.stem[:-3]
        fixed = file.read_bytes()
        coverage_tag = tag.split("-c")[0] + "-c0-m0-p0.bgra"
        coverage = (args.x64 / coverage_tag).read_bytes()
        if len(fixed) != 256 * 256 * 4:
            parser.error("unexpected image dimensions")
        for path in (1, 2, 3, 4):
            explicit = (args.x64 / (tag + f"-p{path}.bgra")).read_bytes()
            histogram = Counter()
            different = full = 0
            first = None
            for at in range(0, len(fixed), 4):
                a, b = fixed[at:at + 4], explicit[at:at + 4]
                if a == b:
                    continue
                different += 1
                # Combined coverage; does not distinguish a shared primitive edge.
                full += coverage[at:at + 4] == bytes((192, 128, 64, 255))
                histogram.update(int(y) - int(x) for x, y in zip(a, b) if x != y)
                if first is None:
                    first = {"x": at // 4 % 256, "y": at // 4 // 256,
                             "fixedBGRA": list(a), "explicitBGRA": list(b)}
            rows.append({"tag": tag, "path": path, "differentPixels": different,
                         "combinedFullCoverage": full, "signedChannelDeltaHistogram": dict(histogram),
                         "firstDifference": first})
    result = {"imagesCompared": len(files), "crossArchitectureDifferentImages": arch_differences,
              "comparisons": rows, "sampleReadback": "resolved_mask_control_only"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"images={len(files)} architectureDifferences={len(arch_differences)}")
    for row in rows:
        if row["path"] == 1 and row["differentPixels"]:
            print(row["tag"], "differentPixels=" + str(row["differentPixels"]),
                  "combinedFullCoverage=" + str(row["combinedFullCoverage"]))
    return bool(arch_differences)


if __name__ == "__main__":
    raise SystemExit(main())
