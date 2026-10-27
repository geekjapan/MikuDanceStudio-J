#!/usr/bin/env python3
"""Bounded, isolated capture of the unchanged Windows app. No fallback renderer."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

TIMEOUT = 90
SOURCES = (
    "CMakeLists.txt", ".github/workflows/windows-build.yml",
    ".github/workflows/native-d3d9-capture.yml", "tools/oracle/d3d9_capture.py",
    "tools/oracle/d3d9_capability.cpp", "tools/oracle/test_d3d9_capture.py",
    "tools/oracle/golden2.ps1", "src/render/d3d_init.cpp", "src/tools/trace_mode.cpp",
)
ASSETS = (
    "tests/fixtures/rust/chain8.pmd", "tests/fixtures/rust/chain8.pmx",
    "tests/fixtures/rust/golden2/shadow_floor.x",
    "tests/fixtures/rust/golden2/selfshadow.pmm",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_report(out, report):
    temporary = out / "report.json.tmp"
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(out / "report.json")


def copy_checked(source, target, manifest):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite {target}")
    entry = {"source": str(source), "copy": str(target), "sha256": None}
    manifest.append(entry)
    try:
        expected = digest(source)
    except OSError as error:
        entry["initial_error"] = str(error)
        raise
    entry["sha256"] = expected
    shutil.copy2(source, target)
    actual = digest(target)
    if actual != expected:
        raise ValueError(f"Copy hash mismatch: {source} -> {target}")


def run_command(command, directory, timeout=TIMEOUT):
    if not 0 < timeout <= TIMEOUT:
        raise ValueError("Native process timeout must be in (0, 90] seconds")
    directory.mkdir(parents=True, exist_ok=False)
    result = {"command": [str(x) for x in command], "cwd": str(directory),
              "timeout_seconds": timeout, "status": "FAIL", "returncode": None,
              "process_started": False, "started_utc": datetime.now(timezone.utc).isoformat()}
    start = time.monotonic()
    process = None
    with (directory / "stdout.txt").open("wb") as stdout, (directory / "stderr.txt").open("wb") as stderr:
        try:
            process = subprocess.Popen(result["command"], cwd=directory, stdout=stdout, stderr=stderr)
            result["process_started"] = True
            result["returncode"] = process.wait(timeout=timeout)
            result["status"] = "PASS" if result["returncode"] == 0 else "FAIL"
            result["cause"] = "completed" if result["returncode"] == 0 else "nonzero exit"
        except subprocess.TimeoutExpired:
            result.update(status="TIMEOUT", cause=f"{timeout}-second bound exceeded")
        except OSError as error:
            result["cause"] = f"process launch failed: {error}" if process is None else f"process wait failed: {error}"
            if process is None:
                result["startup_error"] = {"type": type(error).__name__, "message": str(error),
                                           "errno": error.errno, "winerror": getattr(error, "winerror", None)}
        except subprocess.SubprocessError as error:
            result["cause"] = f"process wait failed: {error}"
        finally:
            if process is not None:
                try:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=10)
                    result["returncode"] = process.returncode
                except (OSError, subprocess.SubprocessError) as error:
                    result["cleanup_error"] = str(error)
                    if result["status"] == "PASS":
                        result.update(status="FAIL", cause="Process cleanup failed")
    result["finished_utc"] = datetime.now(timezone.utc).isoformat()
    result["elapsed_seconds"] = round(time.monotonic() - start, 3)
    (directory / "command.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def activation_diagnostics(original, directory):
    """Read only matching SideBySide events; never start or stop a global trace."""
    directory.mkdir(parents=True, exist_ok=False)
    diagnostic = {"status": "INCOMPLETE", "kind": "SideBySide activation events",
                  "original_command": original["command"], "original_cwd": original["cwd"],
                  "original_startup_error": original["startup_error"], "commands": [],
                  "retry": False, "event_count": 0,
                  "documentation": "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/wevtutil"}
    try:
        executable = original["command"][0]
        quote = "'" if "'" not in executable else '"'
        if quote in executable:
            raise ValueError("Cannot safely represent executable path in event XPath")
        start = datetime.fromisoformat(original["started_utc"])
        end = datetime.fromisoformat(original["finished_utc"]) + timedelta(seconds=2)
        stamp = lambda value: value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        query = (f"*[System[Provider[@Name='SideBySide'] and "
                 f"TimeCreated[@SystemTime >= '{stamp(start)}' and @SystemTime <= '{stamp(end)}']] "
                 f"and EventData[Data={quote}{executable}{quote}]]")
        diagnostic["query"] = query
        tool = Path(os.environ["SystemRoot"]) / "System32" / "wevtutil.exe"
        for name, arguments in (("help", ["/?"]), ("query-help", ["qe", "/?"])):
            diagnostic["commands"].append(run_command([tool, *arguments], directory / name, 10))
        for attempt in range(3):
            result = run_command([tool, "qe", "Application", f"/q:{query}", "/rd:true",
                                  "/c:8", "/f:xml", "/uni:true", "/e:Events"],
                                 directory / f"events-{attempt}", 10)
            diagnostic["commands"].append(result)
            if result["status"] != "PASS":
                diagnostic["cause"] = "SideBySide event query failed; see command and streams"
                break
            events = ET.parse(directory / f"events-{attempt}" / "stdout.txt").getroot()
            if events.tag != "Events":
                raise ValueError("Expected the Events query wrapper")
            ns = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
            matches = []
            for event in events.findall("e:Event", ns):
                provider = event.find("e:System/e:Provider", ns)
                created = event.find("e:System/e:TimeCreated", ns)
                if provider is None or provider.get("Name") != "SideBySide" or created is None:
                    continue
                timestamp = created.get("SystemTime", "")
                parsed = re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(\d+))?(?:Z|\+00:00)", timestamp)
                if parsed is None:
                    continue
                try:
                    logged = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if not start <= logged <= end:
                    continue
                # datetime truncates submicrosecond precision from Windows event timestamps.
                if logged == end and any(digit != "0" for digit in (parsed.group(1) or "")[6:]):
                    continue
                if any(data.text == executable and len(data) == 0
                       for data in event.findall("e:EventData/e:Data", ns)):
                    matches.append(event)
            if matches:
                message = run_command([tool, "qe", "Application", f"/q:{query}", "/rd:true",
                                       "/c:8", "/f:text", "/l:en-US", "/uni:true"],
                                      directory / "messages", 10)
                diagnostic["commands"].append(message)
                diagnostic["message_status"] = message["status"]
                diagnostic.update(status="COLLECTED" if message["status"] == "PASS" else "INCOMPLETE", event_count=len(matches),
                                  evidence=f"events-{attempt}/stdout.txt",
                                  cause="Matching activation events retained; dependency diagnosis requires inspecting event data and messages/stdout.txt")
                break
            if attempt < 2:
                time.sleep(1)
        else:
            diagnostic["cause"] = "No matching SideBySide event was available within the bounded query attempts"
    except (OSError, ValueError, KeyError, ET.ParseError, subprocess.SubprocessError) as error:
        diagnostic["cause"] = f"Activation diagnostics failed: {error}"
    finally:
        (directory / "diagnostic.json").write_text(json.dumps(diagnostic, indent=2) + "\n", encoding="utf-8")
    return diagnostic


def validate_outputs(out):
    for frame in (0, 30):
        path = out / "frames" / f"selfshadow-{frame}.png"
        data = path.read_bytes()
        if len(data) < 45 or data[-12:] != b"\0\0\0\0IEND\xaeB`\x82" or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR" or struct.unpack(">II", data[16:24]) != (640, 360):
            raise ValueError(f"Missing or invalid 640x360 PNG: {path}")
    edge = (out / "edge" / "selfshadow.edge.txt").read_text(encoding="utf-8")
    if not edge.startswith("mds-edge-probe 1\n"):
        raise ValueError("Invalid edge probe header")
    for frame in (0, 30):
        if not any(line.startswith(f"{frame} shadow ") for line in edge.splitlines()):
            raise ValueError(f"Missing frame {frame} shadow probe")


def capture(root, build, out, prepare=False):
    root, build, out = root.resolve(), build.resolve(), out.resolve()
    if out == root or root in out.parents and not out.is_relative_to(root / "out"):
        raise ValueError("Output inside checkout must be under out/")
    out.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "status": "FAIL", "cause": "capture not executed",
              "source_root": str(root), "build": str(build), "host": platform.platform(),
              "python": sys.version, "commands": [], "copies": [],
              "github": {key: os.environ.get(key) for key in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_JOB", "RUNNER_OS", "RUNNER_ARCH")},
              "device_evidence": "capability/stdout.txt records standalone HAL/SWVP; app selection is unchanged HWVP/SWVP/REF and is not instrumented",
              "equivalence": "No RTX3090/native golden hardware equivalence claim; HAL may be a software/translation adapter. No substitute renderer requested."}
    if (out / "runtime").exists():
        raise FileExistsError("Refusing to reuse an existing runtime/capture directory")
    if (out / "source").exists():
        previous = json.loads((out / "report.json").read_text(encoding="utf-8"))
        if previous.get("cause") != "prepared; native capture has not run":
            raise ValueError("Existing output is not a prepared capture")
        report["copies"] = previous["copies"]
        report["commands"] = previous["commands"]
    save_report(out, report)
    try:
        for entry in report["copies"]:
            if digest(Path(entry["source"])) != entry["sha256"] or digest(Path(entry["copy"])) != entry["sha256"]:
                raise ValueError(f"Prepared source hash changed: {entry['source']}")
        provenance = out / "source"
        if not provenance.exists():
            for relative in SOURCES + ASSETS:
                copy_checked(root / relative, provenance / relative, report["copies"])
            identity = run_command(["git", "-C", root, "rev-parse", "HEAD"], out / "source-identity")
            report["commands"].append(identity)
            if identity["status"] != "PASS":
                raise ValueError("Cannot identify source revision")
        if prepare:
            report["cause"] = "prepared; native capture has not run"
        else:
            stage = out / "runtime"
            stage.mkdir(exist_ok=False)
            for name in ("MikuDanceStudio.exe", "d3d9_capability.exe"):
                copy_checked(build / name, stage / name, report["copies"])
            for source in sorted(build.glob("*.dll")):
                copy_checked(source, stage / source.name, report["copies"])
            for relative in ASSETS:
                copy_checked(root / relative, stage / Path(relative).name, report["copies"])
            save_report(out, report)
            pmm = stage / "selfshadow.pmm"
            commands = (
                ("capability", [stage / "d3d9_capability.exe"]),
                ("frames", [stage / "MikuDanceStudio.exe", "--mds-frame-dump", pmm, out / "frames", "0", "30"]),
                ("edge", [stage / "MikuDanceStudio.exe", "--mds-edge-probe", pmm, out / "edge" / "selfshadow.edge.txt", "0", "30"]),
            )
            for name, command in commands:
                result = run_command(command, out / name)
                report["commands"].append(result)
                save_report(out, report)
                if os.name == "nt" and result.get("startup_error", {}).get("winerror") == 14001:
                    try:
                        diagnostic = activation_diagnostics(result, out / "activation" / name)
                    except (OSError, ValueError, subprocess.SubprocessError) as error:
                        diagnostic = {"status": "INCOMPLETE", "cause": str(error), "retry": False}
                    report.setdefault("activation_diagnostics", []).append(diagnostic)
                    save_report(out, report)
            if any(command["status"] != "PASS" for command in report["commands"]):
                raise ValueError("Native command failed/unsupported or timed out; see retained command and stdout/stderr files")
            capability = (out / "capability" / "stdout.txt").read_text(encoding="utf-8", errors="replace")
            if "diagnostic_result=supported;" not in capability:
                raise ValueError("Missing strict native capability result")
            validate_outputs(out)
            report.update(status="PASS", cause="Capability and unchanged-app frame/edge capture completed; not a parity result")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report.update(status="FAIL", cause=str(error), original_error=str(error))
    finally:
        checks = []
        for entry in report["copies"]:
            for role in ("source", "copy"):
                check = {"role": role, "path": entry[role],
                         "initial_sha256": entry["sha256"], "final_sha256": None}
                if "initial_error" in entry:
                    check["initial_error"] = entry["initial_error"]
                try:
                    check["final_sha256"] = digest(Path(entry[role]))
                    check["status"] = ("unchanged" if check["final_sha256"] == entry["sha256"]
                                       else "changed" if entry["sha256"] else "no_initial_hash")
                except OSError as error:
                    check.update(status="missing" if isinstance(error, FileNotFoundError) else "unreadable",
                                 error=str(error))
                checks.append(check)
        closure_failed = any(check["status"] != "unchanged" for check in checks)
        report["closure"] = {"status": "FAIL" if closure_failed else "PASS",
                             "tracked_copies": len(report["copies"]), "checks": checks}
        if closure_failed:
            report.update(status="FAIL", cause=report.get("original_error", report["cause"]) +
                          "; Source or staged file closure failed; see closure checks")
        report["files"] = []
        for path in sorted(out.rglob("*")):
            if path.is_file() and path.name not in ("report.json", "report.json.tmp"):
                entry = {"path": str(path.relative_to(out))}
                try:
                    entry.update(bytes=path.stat().st_size, sha256=digest(path))
                except OSError as error:
                    entry["error"] = str(error)
                    report.update(status="FAIL", cause=report["cause"] +
                                  f"; Artifact hash failed: {path}: {error}")
                report["files"].append(entry)
        save_report(out, report)
    return 0 if report["status"] == "PASS" or report["cause"] == "prepared; native capture has not run" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--build", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    return capture(args.root, args.build, args.out, args.prepare)


if __name__ == "__main__":
    sys.exit(main())
