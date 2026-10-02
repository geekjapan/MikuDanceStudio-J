"""Audit the real 8x-MSAA prefix; return 2 until exact history replay exists."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("gui", "application", "dx9-test", "probe", "evidence"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    directory = args.evidence.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(args.probe), str(directory / "capabilities")], timeout=60)
    if result.returncode:
        return result.returncode
    env = dict(os.environ, MDS_RHI_MSAA_REPLAY_AUDIT="1", MDS_RHI_REAL_BATCH_CAPTURE="1",
               MDS_RHI_GUI_MATERIAL="13", MDS_RHI_GUI_MODE="model", MDS_RHI_EVIDENCE_DIR=str(directory))
    env.pop("MDS_RHI_SCENE_HISTORY", None)
    env.pop("MDS_RHI_HISTORY_TRANSLUCENT", None)
    for name in ("msaa_replay.prefix", "model_batch.same_frame", "real_batch.capture"):
        (directory / name).unlink(missing_ok=True)
    result = subprocess.run([str(args.gui), str(args.application), str(args.dx9_test)], env=env, timeout=180)
    if result.returncode:
        return result.returncode
    lines = (directory / "msaa_replay.prefix").read_text().splitlines()
    begin = dict(item.split("=", 1) for item in lines[0].split()[1:])
    gate = dict(item.split("=", 1) for item in lines[-1].split()[1:])
    if begin.get("samples") != "8" or gate.get("material") != "13" or gate.get("indices") != "336":
        raise RuntimeError("Unexpected scene / selected batch / sample count")
    if gate.get("completeDrawReplay") != "0" or int(gate["otherDraws"]) < 1 or int(gate["modelDraws"]) < 1:
        raise RuntimeError("Missing conservative replay-boundary evidence")
    native = (directory / "model_batch.same_frame").read_text()
    if "status=PASS " not in native or "actualAdapterApplied=0 " not in native or "multisample=8 " not in native:
        raise RuntimeError("Original DX9 diagnostic failed or renderer changed")
    result = {"acceptance": "BLOCKED", "reason": "Exact per-sample transfer unavailable; complete preceding draw replay not implemented",
              "nativeDx9Probe": "PASS", "dx11SceneComparison": "NOT_RUN", "prefix": gate,
              "resolvedHistoryUsedAsMsaa": False}
    (directory / "msaa-history-gate.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
