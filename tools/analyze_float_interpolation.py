"""Decode raw single-sample DX9 outputs and compare architectures."""
import argparse
import json
from pathlib import Path
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("x64", type=Path)
    parser.add_argument("x86", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = {"architectureDifferentImages": [], "values": [],
              "interpretation": "RGBA float / BGRA byte; target changes may change internal precision"}
    for fmt, layout, size in ((21, "4B", 4), (113, "4e", 8), (116, "4f", 16)):
        for axis in (0, 1):
            x, y = (0, 28) if axis == 0 else (28, 0)
            for path in range(7):
                name = f"f{fmt}-a{axis}-p{path}.raw"
                data = (args.x64 / name).read_bytes()
                if len(data) != 64 * 64 * size:
                    raise ValueError("unexpected dimensions: " + name)
                if data != (args.x86 / name).read_bytes():
                    result["architectureDifferentImages"].append(name)
                values = list(struct.unpack_from("<" + layout, data, (y * 64 + x) * size))
                result["values"].append({"format": fmt, "axis": axis, "path": path,
                    "channels": values, "byteUnits": [v * 255 for v in values] if fmt != 21 else values})
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("imagesCompared=42 architectureDifferences=" + str(len(result["architectureDifferentImages"])))
    return bool(result["architectureDifferentImages"])


if __name__ == "__main__":
    raise SystemExit(main())
