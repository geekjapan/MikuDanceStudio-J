"""Strict live-history acceptance for the larger independent PMM material batch."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import struct
import subprocess
from analyze_rhi_real_batch import analyze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("gui", "application", "dx9-test", "replay", "evidence"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    result = subprocess.run([str(args.replay), "--history-support"], timeout=30)
    if result.returncode:
        return result.returncode
    summary = {}
    for name, translucent in (("original", False), ("translucent", True)):
        directory = args.evidence.resolve() / name
        directory.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, MDS_RHI_SCENE_HISTORY="1", MDS_RHI_REAL_BATCH_CAPTURE="1",
                   MDS_RHI_GUI_MATERIAL="13", MDS_RHI_GUI_MODE="model",
                   MDS_RHI_EVIDENCE_DIR=str(directory))
        env.pop("MDS_RHI_HISTORY_TRANSLUCENT", None)
        if translucent:
            env["MDS_RHI_HISTORY_TRANSLUCENT"] = "1"
        for file in ("real_batch.capture", "history_live.rgba", "model_batch.same_frame"):
            (directory / file).unlink(missing_ok=True)
        result = subprocess.run([str(args.gui), str(args.application), str(args.dx9_test)], env=env, timeout=180)
        if result.returncode:
            return result.returncode
        capture = directory / "real_batch.capture"
        payload = capture.read_bytes()
        header = struct.unpack_from("<17I", payload)
        if header[:2] != (0x3142444D, 5) or header[5] != 13 or header[7] != 336 or header[12] != 0 or header[14] != 1 or header[16] != 0:
            raise RuntimeError("Incorrect history capture / source vertex-processing mode")
        width, height = header[10:12]
        prior_color = payload[-width * height * 8:-width * height * 4]
        depth = struct.unpack_from(f"<{width * height}I", payload, len(payload) - width * height * 4)
        occupied = sum((value & 0xffffff) != 0xffffff for value in depth)
        stencil = Counter(value >> 24 for value in depth)
        if not occupied or not any(stencil):
            raise RuntimeError("History contains no depth/stencil content")
        row = {"width": width, "height": height, "priorDepthPixels": occupied,
               "stencilHistogram": dict(stencil), "comparisons": {}}
        for variant, flags in (("history", []), ("no-depth", ["--no-depth"]), ("no-blend", ["--no-blend"])):
            result = subprocess.run([str(args.replay), *flags, str(capture), str(directory / variant)], timeout=60)
            if result.returncode:
                return result.returncode
            fields = analyze(directory / variant)
            if fields["status"] != "PASS" or (directory / variant / "before.rgba").read_bytes() != prior_color:
                raise RuntimeError("Backend or history baseline mismatch")
            row["comparisons"][variant] = fields
        normal = (directory / "history/dx9.rgba").read_bytes()
        for control in ("no-depth", "no-blend"):
            altered = (directory / control / "dx9.rgba").read_bytes()
            row[control + "EffectPixels"] = sum(normal[i:i+4] != altered[i:i+4] for i in range(0, len(normal), 4))
            row[control + "RgbEffectPixels"] = sum(normal[i:i+3] != altered[i:i+3] for i in range(0, len(normal), 4))
        if not row["no-depthRgbEffectPixels"] or (translucent and not row["no-blendRgbEffectPixels"]):
            raise RuntimeError("No observed occlusion / translucent blend effect")
        native = (directory / "model_batch.same_frame").read_text()
        if "status=PASS " not in native or "actualAdapterApplied=0 " not in native:
            raise RuntimeError("Native diagnostic gate failed or renderer changed")
        summary[name] = row
    (args.evidence / "history-acceptance.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("Live-history PASS: larger batch, actual application reference, occlusion and translucent blend controls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
