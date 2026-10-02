"""Independently verify native real-batch reports and optionally export PNGs."""
import argparse
import json
from pathlib import Path


def analyze(directory):
    fields = dict(token.split("=", 1) for token in
                  (directory / "comparison.report").read_text().split())
    width, height = int(fields["width"]), int(fields["height"])
    a = (directory / "dx9.rgba").read_bytes()
    b = (directory / "dx11.rgba").read_bytes()
    if len(a) != width * height * 4 or len(a) != len(b):
        raise ValueError("Invalid RGBA target lengths")
    channels = pixels = maximum = changed9 = changed11 = 0
    baseline = (directory / "before.rgba").read_bytes() if (directory / "before.rgba").is_file() else bytes((48, 48, 48, 255)) * (width * height)
    if len(baseline) != len(a):
        raise ValueError("Invalid history color length")
    first = None
    for i in range(0, len(a), 4):
        pa, pb = a[i:i + 4], b[i:i + 4]
        changed9 += pa != baseline[i:i + 4]
        changed11 += pb != baseline[i:i + 4]
        pixels += pa != pb
        for channel, (x, y) in enumerate(zip(pa, pb)):
            channels += x != y
            maximum = max(maximum, abs(x - y))
            if x != y and first is None:
                first = {"x": i // 4 % width, "y": i // 4 // width,
                         "channel": "RGBA"[channel], "dx9": x, "dx11": y}
    recorded = tuple(int(fields[key]) for key in
                     ("differingPixels", "differingChannels", "maxError", "changedDX9", "changedDX11"))
    if recorded != (pixels, channels, maximum, changed9, changed11):
        raise ValueError("Report disagrees with raw target bytes")
    live9 = int(fields.get("liveDX9Differences", "0"))
    live11 = int(fields.get("liveDX11Differences", "0"))
    if fields.get("liveChecked") == "1":
        reference = (directory.parent / "history_live.rgba").read_bytes()
        if len(reference) != len(a):
            raise ValueError("Invalid application reference length")
        actual_live = (sum(a[i:i+4] != reference[i:i+4] for i in range(0, len(a), 4)),
                       sum(b[i:i+4] != reference[i:i+4] for i in range(0, len(b), 4)))
        if actual_live != (live9, live11):
            raise ValueError("Application reference counts disagree")
    status = "PASS" if not pixels and changed9 and changed11 and not live9 and not live11 else "BLOCKED"
    if fields["status"] != status:
        raise ValueError("Incorrect acceptance status")
    summary = {**fields, "firstDifference": first}
    (directory / "comparison.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--images", action="store_true", help="Requires Pillow; export both full targets and an enlarged crop")
    args = parser.parse_args()
    summary = analyze(args.directory)
    if args.images:
        from PIL import Image, ImageChops
        size = int(summary["width"]), int(summary["height"])
        a = Image.frombytes("RGBA", size, (args.directory / "dx9.rgba").read_bytes())
        b = Image.frombytes("RGBA", size, (args.directory / "dx11.rgba").read_bytes())
        a.save(args.directory / "dx9.png")
        b.save(args.directory / "dx11.png")
        background = Image.frombytes("RGBA", size, (args.directory / "before.rgba").read_bytes()).convert("RGB") if (args.directory / "before.rgba").is_file() else Image.new("RGB", size, (48, 48, 48))
        bounds = ImageChops.difference(a.convert("RGB"), background).getbbox()
        if bounds:
            x0, y0, x1, y1 = bounds
            box = max(0, x0 - 4), max(0, y0 - 4), min(size[0], x1 + 4), min(size[1], y1 + 4)
            ca, cb = a.crop(box).convert("RGB"), b.crop(box).convert("RGB")
            diff = ImageChops.difference(ca, cb)
            comparison = Image.new("RGB", (ca.width * 3, ca.height))
            for index, panel in enumerate((ca, cb, diff)):
                comparison.paste(panel, (index * ca.width, 0))
            comparison.resize((comparison.width * 16, comparison.height * 16), Image.Resampling.NEAREST).save(args.directory / "crop-dx9-dx11-difference.png")
    print(json.dumps(summary))
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
