"""Capture a real PMM independent batch and strictly compare DX9/DX11 replays."""
import argparse
import os
from pathlib import Path
import subprocess
from analyze_rhi_real_batch import analyze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui", required=True, type=Path)
    parser.add_argument("--application", required=True, type=Path)
    parser.add_argument("--dx9-test", required=True, type=Path)
    parser.add_argument("--replay", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    for mode in ("model_textures_native", "model_textures_combined", "model_textures_combined_add"):
        directory = args.evidence.resolve() / mode
        directory.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, MDS_RHI_REAL_BATCH_CAPTURE="1", MDS_RHI_SHADER_INPUTS="1",
                   MDS_RHI_GUI_MODE=mode, MDS_RHI_EVIDENCE_DIR=str(directory))
        # Require this invocation's capture; never accept stale output.
        capture = directory / "real_batch.capture"
        capture.unlink(missing_ok=True)
        result = subprocess.run([str(args.gui), str(args.application), str(args.dx9_test)], env=env, timeout=180)
        if result.returncode:
            return result.returncode
        if not capture.is_file():
            raise RuntimeError(f"No current capture from {mode}")
        for variant, flags in (("profile-single", []),
                               ("profile-msaa", ["--msaa", "--srgb-resolve"])):
            result = subprocess.run([str(args.replay), *flags, str(capture), str(directory / variant)], timeout=60)
            if result.returncode:
                return result.returncode
            if analyze(directory / variant)["status"] != "PASS":
                return 2
        # The capture-only GUI must keep the application on the legacy path.
        report = (directory / "model_batch.same_frame").read_text()
        if "actualAdapterApplied=0 " not in report or "status=PASS " not in report:
            raise RuntimeError(f"Application legacy-path gate failed in {mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
