"""Require exact native DX9 8x history replay, before and after material 13."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def validate(directory):
    lines = (directory / "history_replay.dx9").read_text(encoding="utf-8").splitlines()
    prefix = next((line for line in lines if line.startswith("PREFIX ")), "")
    gate = next((line for line in lines if line.startswith("GATE ")), "")
    draws = [line for line in lines if line.startswith("DRAW ")]
    states = [line for line in lines if line.startswith("STATE ")]
    if not lines or "BEGIN samples=8 quality=0 " not in lines[0]:
        raise RuntimeError("Missing actual 8x MSAA boundary")
    if len(draws) != 49 or len(states) != len(draws):
        raise RuntimeError("Incomplete sample.pmm prefix, including accessory subsets")
    if any("vbVersion=" not in line or "ibVersion=" not in line for line in draws):
        raise RuntimeError("Unversioned geometry")
    if ("PREFIX status=PASS " not in prefix or "beforeDifferentPixels=0 " not in prefix
            or "GATE status=PASS afterDifferentPixels=0 " not in gate
            or any("status=FAIL" in line or "status=BLOCKED" in line for line in lines)):
        raise RuntimeError(f"History replay failed: {prefix}; {gate}")
    before = (directory / "history_replay.before.bgra").read_bytes()
    rebuilt = (directory / "history_replay.rebuilt.bgra").read_bytes()
    after = (directory / "history_replay.actual_after.bgra").read_bytes()
    replayed = (directory / "history_replay.replayed_after.bgra").read_bytes()
    if not before or before != rebuilt or after != replayed or before == after:
        raise RuntimeError("Binary images contradict exact replay acceptance")
    native = (directory / "model_batch.same_frame").read_text()
    if "status=PASS " not in native or "actualAdapterApplied=0 " not in native:
        raise RuntimeError("Original application draw was changed")
    return {"acceptance": "PASS", "draws": len(draws), "beforeDifferentPixels": 0,
            "afterDifferentPixels": 0, "perSampleReadback": False,
            "depthStencilVerification": "selected_draw_functional",
            "dx11Replay": "NOT_RUN"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("gui", "application", "dx9-test", "evidence"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--probe", type=Path, help="Require three consecutive native 8x capability checks")
    parser.add_argument("--trace", action="store_true", help="Capture every preceding draw boundary")
    args = parser.parse_args()
    root = args.evidence.resolve()
    if args.probe:
        checks = []
        root.mkdir(parents=True, exist_ok=True)
        for index in range(3):
            result = subprocess.run([str(args.probe), str(root / f"capability-{index + 1}")],
                                    timeout=60, capture_output=True, text=True)
            checks.append({"attempt": index + 1, "exit": result.returncode,
                           "stdout": result.stdout, "stderr": result.stderr})
            if result.returncode:
                report = {"acceptance": "UNAVAILABLE" if result.returncode == 77 else "FAIL",
                          "stage": "native_8x_preflight", "checks": checks,
                          "applicationRuns": 0, "dx11Replay": "NOT_RUN"}
                (root / "preflight.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                print(json.dumps(report))
                return result.returncode
        (root / "preflight.json").write_text(json.dumps({"acceptance": "PASS", "checks": checks}, indent=2) + "\n", encoding="utf-8")
    for mode in ("opaque", "translucent"):
        directory = root / mode
        directory.mkdir(parents=True, exist_ok=True)
        for file in directory.glob("history_replay.*"):
            file.unlink()
        env = dict(os.environ, MDS_RHI_HISTORY_REPLAY="1", MDS_RHI_REAL_BATCH_CAPTURE="1",
                   MDS_RHI_GUI_MATERIAL="13", MDS_RHI_GUI_MODE="model",
                   MDS_RHI_EVIDENCE_DIR=str(directory))
        env.pop("MDS_RHI_REPLAY_SINGLE_SAMPLE_CONTROL", None)
        env.pop("MDS_RHI_HISTORY_REDUCE", None)
        env.pop("MDS_RHI_HISTORY_ISOLATE", None)
        env.pop("MDS_RHI_HISTORY_TRACE", None)
        if args.trace:
            env["MDS_RHI_HISTORY_TRACE"] = "1"
        env.pop("MDS_RHI_SCENE_HISTORY", None)
        env.pop("MDS_RHI_HISTORY_TRANSLUCENT", None)
        if mode == "translucent":
            env["MDS_RHI_HISTORY_TRANSLUCENT"] = "1"
        result = subprocess.run([str(args.gui), str(args.application), str(args.dx9_test)],
                                env=env, timeout=180)
        if result.returncode:
            # Always replace stale acceptance, including early fixture/device
            # failures; 77 is explicit unavailability, never a successful gate.
            acceptance = {"acceptance": "UNAVAILABLE" if result.returncode == 77 else "FAIL",
                          "guiExit": result.returncode, "reason": "GUI fixture/diagnostic did not complete",
                          "dx11Replay": "NOT_RUN"}
            (directory / "acceptance.json").write_text(json.dumps(acceptance, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(acceptance))
            return result.returncode
        try:
            acceptance = validate(directory)
        except (OSError, RuntimeError) as error:
            acceptance = {"acceptance": "FAIL", "reason": str(error), "dx11Replay": "NOT_RUN"}
        (directory / "acceptance.json").write_text(json.dumps(acceptance, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(acceptance))
        if acceptance["acceptance"] != "PASS":
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
