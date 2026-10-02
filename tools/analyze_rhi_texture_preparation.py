"""Inspect native probe artifacts without NumPy, Pillow or model assets.

Exit 0 means the artifacts were analyzed, not that the candidate passed parity.
candidateAccepted and floatReconstructionDifferences are separate conclusions.
"""

import argparse
import json
import math
from pathlib import Path
import re
import struct


def float32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def analyze(root, filter_value):
    report = (root / f"{filter_value}.report").read_text(encoding="utf-8")
    match = re.search(r" prepared=(\d+)x(\d+) ", report)
    if not match:
        raise ValueError("missing prepared dimensions")
    width, height = map(int, match.groups())
    if not 1 <= width <= 4096 or not 1 <= height <= 4096:
        raise ValueError("invalid prepared dimensions")
    count = width * height * 4
    candidate = (root / "candidate.rgba").read_bytes()
    native = (root / f"{filter_value}.rgba").read_bytes()
    floating = (root / f"{filter_value}.rgba32f").read_bytes()
    if len(candidate) != count or len(native) != count or len(floating) != count * 4:
        raise ValueError("artifact size differs from declared dimensions")
    thresholds = ((31, 15, 27, 11), (19, 3, 23, 7),
                  (25, 9, 29, 13), (21, 5, 17, 1))
    differences = []
    different_channels = reconstruction_differences = max_error = 0
    for at, ((value,), actual, proposed) in enumerate(
            zip(struct.iter_unpack("<f", floating), native, candidate)):
        if not math.isfinite(value):
            raise ValueError("non-finite native float channel")
        x, y = (at // 4) % width, at // 4 // width
        reconstructed = min(255, max(0, math.floor(float32(
            float32(value * 255.0) + thresholds[y % 4][x % 4] / 32.0))))
        reconstruction_differences += reconstructed != actual
        if proposed != actual:
            different_channels += 1
            max_error = max(max_error, abs(proposed - actual))
            if len(differences) < 16:
                differences.append({"x": x, "y": y, "channel": "RGBA"[at % 4],
                                    "candidate": proposed, "native": actual,
                                    "nativeBeforeQuantization": value * 255.0,
                                    "ditherThreshold": thresholds[y % 4][x % 4] / 32.0})
    declared = re.search(r" differentChannels=(\d+) ", report)
    if not declared or int(declared.group(1)) != different_channels:
        raise ValueError("reported difference count does not match actual bytes")
    raw_match = re.search(r" raw=(\d+)x(\d+) ", report)
    if not raw_match:
        raise ValueError("missing raw dimensions")
    raw_width, raw_height = map(int, raw_match.groups())
    if not 1 <= raw_width <= 4096 or not 1 <= raw_height <= 4096:
        raise ValueError("invalid raw dimensions")
    source = (root / "source.rgba").read_bytes()
    source_floats = (root / f"{filter_value}.source.rgba32f").read_bytes()
    if len(source) != raw_width * raw_height * 4 or len(source_floats) != len(source) * 4:
        raise ValueError("normalization artifact size differs from raw dimensions")
    division_differences = reciprocal_differences = 0
    for (value,), byte in zip(struct.iter_unpack("<f", source_floats), source):
        if not math.isfinite(value):
            raise ValueError("non-finite normalized native channel")
        division_differences += value != float32(byte / 255.0)
        reciprocal_differences += value != float32(byte * float32(1.0 / 255.0))
    return {"filter": filter_value, "width": width, "height": height,
            "candidateAccepted": different_channels == 0,
            "differentChannels": different_channels, "maxChannelError": max_error,
            "floatReconstructionDifferences": reconstruction_differences,
            "normalizationDivisionDifferences": division_differences,
            "normalizationReciprocalDifferences": reciprocal_differences,
            "firstDifferences": differences}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        results = [analyze(args.directory, value) for value in (4294967295, 524292)]
        print(json.dumps(results, indent=2))
    except (OSError, ValueError, OverflowError) as error:
        parser.exit(1, f"Invalid probe artifacts: {error}\n")


if __name__ == "__main__":
    main()
