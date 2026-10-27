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
    "src/main/winmain.cpp", "src/window/ui_init.cpp", "src/window/window_init.cpp",
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


class DialogWindows:
    """PID-scoped Win32 observations and bounded real button messages."""

    def __init__(self):
        self.deadline = time.monotonic() + 30
        import ctypes
        from ctypes import wintypes as w
        self.c, self.w = ctypes, w
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        signatures = {
            "EnumWindows": ([self.callback, w.LPARAM], w.BOOL),
            "EnumChildWindows": ([w.HWND, self.callback, w.LPARAM], w.BOOL),
            "GetWindowThreadProcessId": ([w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
            "GetClassNameW": ([w.HWND, w.LPWSTR, ctypes.c_int], ctypes.c_int),
            "GetDlgCtrlID": ([w.HWND], ctypes.c_int),
            "GetWindowTextW": ([w.HWND, w.LPWSTR, ctypes.c_int], ctypes.c_int),
            "GetWindowLongW": ([w.HWND, ctypes.c_int], ctypes.c_long),
            "GetParent": ([w.HWND], w.HWND),
            "GetWindow": ([w.HWND, w.UINT], w.HWND),
            "GetMenu": ([w.HWND], w.HMENU),
            "IsWindowVisible": ([w.HWND], w.BOOL),
            "IsWindowEnabled": ([w.HWND], w.BOOL),
            "GetWindowRect": ([w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
            "SendMessageTimeoutW": ([w.HWND, w.UINT, w.WPARAM, w.LPARAM, w.UINT,
                                     w.UINT, ctypes.POINTER(ctypes.c_size_t)], w.LPARAM),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, result

    def api_call(self, api, hwnd, *arguments, message=None, flags=None, timeout=None):
        start = time.monotonic()
        if start >= self.deadline:
            raise ValueError("GUI observation deadline exceeded")
        self.c.set_last_error(0)
        function = getattr(self.api, api)
        returned = function(*arguments) if api == "EnumWindows" else function(hwnd, *arguments)
        last_error = self.c.get_last_error()
        end = time.monotonic()
        context = {"api": api, "stage": getattr(self, "stage", "message"),
                   "hwnd": hwnd, "window": next((dict(item) for item in getattr(self, "records", [])
                                                   if item["hwnd"] == hwnd), None),
                   "message": message, "flags": flags, "timeout_ms": timeout,
                   "start_monotonic": start, "end_monotonic": end,
                   "return": returned, "last_error": last_error}
        return returned, context

    def api_error(self, context):
        error = OSError(f"{context['api']} failed: hwnd={context['hwnd']}, "
                        f"message={context['message']}, last_error={context['last_error']}")
        error.api_error = context
        error.partial_windows = getattr(self, "records", [])
        return error

    def message(self, hwnd, message, parameter=0):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("GUI observation deadline exceeded")
        self.stage = {13: "dialog body", 0: "main responsiveness", 0xF5: "button command"}.get(message, "message")
        timeout = max(1, min(200, int(remaining * 1000)))
        result = self.c.c_size_t()
        returned, context = self.api_call(
            "SendMessageTimeoutW", hwnd, message, 4096 if message == 13 else 0,
            parameter, 0x22, timeout, self.c.byref(result),
            message=message, flags=0x22, timeout=timeout)
        if not returned:
            # lpdwResult is not a message result when the API failed.
            raise self.api_error(context)
        return result.value

    def snapshot(self, pid):
        self.records = records = []
        errors = []
        top_level = True
        self.stage = "top-level metadata"

        def read(hwnd, _):
            try:
                owner = self.w.DWORD()
                tid, context = self.api_call("GetWindowThreadProcessId", hwnd, self.c.byref(owner))
                if not tid:
                    raise self.api_error(context)
                if owner.value != pid:
                    return True
                if len(records) >= 256:
                    raise ValueError("Window enumeration exceeded 256-window bound")
                record = {"hwnd": hwnd, "pid": owner.value, "tid": tid,
                          "class": None, "top_level": top_level, "text": None,
                          "id": None, "parent": None, "owner": None,
                          "visible": None, "enabled": None, "menu": None, "rect": None}
                records.append(record)
                name = self.c.create_unicode_buffer(256)
                returned, context = self.api_call("GetClassNameW", hwnd, name, len(name))
                if not returned:
                    raise self.api_error(context)
                record["class"] = name.value
                for key, api, arguments in (
                    ("parent", "GetParent", ()), ("owner", "GetWindow", (4,)),
                    ("visible", "IsWindowVisible", ()), ("enabled", "IsWindowEnabled", ())):
                    returned, context = self.api_call(api, hwnd, *arguments)
                    if not returned and context["last_error"]:
                        raise self.api_error(context)
                    record[key] = bool(returned) if key in ("visible", "enabled") else returned or 0
                if not top_level:
                    returned, context = self.api_call("GetDlgCtrlID", hwnd)
                    if not returned and context["last_error"]:
                        raise self.api_error(context)
                    record["id"] = returned
                if name.value.lower() == "static":
                    returned, context = self.api_call("GetWindowLongW", hwnd, -16)
                    if not returned and context["last_error"]:
                        raise self.api_error(context)
                    record["style"] = returned
            except (OSError, ValueError) as error:
                errors.append(error)
                return False
            return True

        try:
            callback = self.callback(read)
            returned, context = self.api_call("EnumWindows", None, callback, 0)
            if errors:
                raise errors[0]
            if not returned:
                raise self.api_error(context)
            top = list(records)
            top_level = False
            self.stage = "child metadata"
            for window in top:
                self.api_call("EnumChildWindows", window["hwnd"], callback, 0)
                if errors:
                    raise errors[0]
            if time.monotonic() >= self.deadline:
                raise ValueError("GUI observation deadline exceeded")
            if any(window["top_level"] and window["visible"] and
                   window["class"] not in ("#32770", "Polygon Movie Maker") for window in records):
                raise ValueError("Unexpected visible top-level window")
            dialogs = [window for window in records if window["class"] == "#32770"]
            if dialogs:
                if len(dialogs) != 1:
                    raise ValueError("Ambiguous GUI dialogs")
                dialog = dialogs[0]
                if not dialog["top_level"] or not dialog["visible"] or not dialog["enabled"]:
                    raise ValueError("Unexpected hidden, disabled or child dialog")
                children = [window for window in records if not window["top_level"]
                            and window["parent"] == dialog["hwnd"]]
                statics = [window for window in children if window["class"].lower() == "static"]
                buttons = [window for window in children if window["class"].lower() == "button"]
                if (len(statics) != 1 or not statics[0]["visible"] or
                    statics[0]["style"] & 0x1f not in (0, 1, 2, 11, 12) or
                    len(buttons) != 1 or buttons[0]["id"] != 1 or
                    not buttons[0]["visible"] or not buttons[0]["enabled"]):
                    raise ValueError("Unexpected dialog Static or IDOK metadata")
                self.stage = "dialog caption"
                text = self.c.create_unicode_buffer(4096)
                returned, context = self.api_call("GetWindowTextW", dialog["hwnd"], text, len(text))
                if not returned and context["last_error"]:
                    raise self.api_error(context)
                dialog["text"] = text.value
                if dialog["text"] != "":
                    raise ValueError("Unexpected dialog title")
                self.stage = "dialog body"
                self.message(statics[0]["hwnd"], 13, self.c.addressof(text))
                statics[0]["text"] = text.value
            else:
                self.stage = "main readiness"
                mains = [window for window in top if window["class"] == "Polygon Movie Maker"
                         and window["visible"] and window["enabled"]]
                if len(mains) == 1 and any(not window["top_level"] and
                                          window["parent"] == mains[0]["hwnd"] for window in records):
                    main = mains[0]
                    returned, context = self.api_call("GetMenu", main["hwnd"])
                    if not returned and context["last_error"]:
                        raise self.api_error(context)
                    main["menu"] = bool(returned)
                    if main["menu"]:
                        rect = self.w.RECT()
                        returned, context = self.api_call("GetWindowRect", main["hwnd"], self.c.byref(rect))
                        if not returned:
                            raise self.api_error(context)
                        main["rect"] = [rect.left, rect.top, rect.right, rect.bottom]
            return records
        except (OSError, ValueError) as error:
            error.partial_windows = records
            raise


def observe_recoverable_dialog(executable, pmm, directory, timeout=30):
    if not 0 < timeout <= 30:
        raise ValueError("GUI observation timeout must be in (0, 30] seconds")
    directory.mkdir(parents=True, exist_ok=False)
    result = {"status": "FAIL", "command": [str(executable), str(pmm)],
              "cwd": str(directory), "exe_sha256": digest(executable), "pid": None, "process_started": False,
              "timeout_seconds": timeout, "started_utc": datetime.now(timezone.utc).isoformat(),
              "observations": [], "button_commands": 0, "cleanup": {},
              "claim": "Normal GUI window continuation only; no rendering, frames, audio or playback proof"}
    process = None
    start = time.monotonic()
    try:
        if os.name != "nt":
            raise OSError("Native Windows GUI observation requires Windows")
        windows = DialogWindows()
        windows.deadline = start + timeout
        with (directory / "stdout.txt").open("wb") as stdout, (directory / "stderr.txt").open("wb") as stderr:
            process = subprocess.Popen(result["command"], cwd=directory, stdout=stdout, stderr=stderr)
            result["pid"] = process.pid
            result["process_started"] = True
            dialog_hwnd, ready_since = None, None
            while time.monotonic() - start < timeout:
                if process.poll() is not None:
                    raise ValueError("GUI process exited before continuation observation")
                facts = windows.snapshot(process.pid)
                result["observations"].append({"elapsed_seconds": round(time.monotonic() - start, 3),
                                               "windows": facts})
                if any(window["pid"] != process.pid for window in facts):
                    raise ValueError("Window snapshot contains wrong PID")
                if any(window.get("top_level") and window["visible"] and
                       window["class"] not in ("#32770", "Polygon Movie Maker") for window in facts):
                    raise ValueError("Unexpected visible top-level window")
                dialogs = [window for window in facts if window["class"] == "#32770"]
                if dialogs:
                    if result["button_commands"]:
                        raise ValueError("Repeated or unresolved dialog after the one OK command")
                    if len(dialogs) != 1:
                        raise ValueError("Ambiguous GUI dialogs")
                    dialog = dialogs[0]
                    children = [window for window in facts if not window.get("top_level")
                                and window["parent"] == dialog["hwnd"]]
                    texts = [window for window in children if window["class"].lower() == "static" and window["text"]]
                    buttons = [window for window in children if window["class"].lower() == "button"]
                    if (dialog["text"] != "" or not dialog["visible"] or not dialog["enabled"] or
                        [window["text"] for window in texts] != ["Cannot make DirectSound!!"] or
                        len(buttons) != 1 or buttons[0]["id"] != 1 or
                        not buttons[0]["visible"] or not buttons[0]["enabled"]):
                        raise ValueError("Unexpected dialog text, title or IDOK control")
                    # Re-read immediately before the single real BM_CLICK; never synthesize a return value.
                    if windows.snapshot(process.pid) != facts:
                        raise ValueError("Dialog changed before OK command")
                    dialog_hwnd = dialog["hwnd"]
                    result["dialog"] = dialog
                    result["button"] = buttons[0]
                    result["button_commands"] = 1
                    result["button_command"] = {"hwnd": buttons[0]["hwnd"], "message": "BM_CLICK",
                                                "message_id": 0xF5, "status": "ATTEMPTED"}
                    windows.message(buttons[0]["hwnd"], 0xF5)
                    result["button_command"]["status"] = "COMPLETED"
                elif result["button_commands"]:
                    main = [window for window in facts if window["class"] == "Polygon Movie Maker"
                            and window["visible"] and window["enabled"] and window["menu"] and window["rect"]
                            and window["rect"][2] > window["rect"][0]
                            and window["rect"][3] > window["rect"][1]]
                    if len(main) == 1 and any(not window.get("top_level") and window["parent"] == main[0]["hwnd"] for window in facts):
                        windows.message(main[0]["hwnd"], 0)  # WM_NULL responsiveness, not a render claim.
                        ready_since = ready_since or time.monotonic()
                        if time.monotonic() - ready_since >= 2:
                            if process.poll() is not None:
                                raise ValueError("GUI process exited at continuation observation")
                            result.update(status="OBSERVED", cause="Single IDOK command followed by responsive visible main UI for two seconds",
                                          main_window=main[0], dialog_hwnd=dialog_hwnd)
                            break
                    else:
                        ready_since = None
                time.sleep(0.2)
            else:
                raise ValueError("GUI continuation observation timed out")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result.update(status="FAIL", cause=str(error))
        if hasattr(error, "api_error"):
            result["api_error"] = error.api_error
        if hasattr(error, "partial_windows"):
            result["partial_windows"] = error.partial_windows
    finally:
        if process is not None:
            try:
                result["cleanup"]["pid"] = process.pid
                result["cleanup"]["terminated_owned_process"] = process.poll() is None
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)
                result["cleanup"]["returncode"] = process.returncode
            except (OSError, subprocess.SubprocessError) as error:
                result["cleanup"]["error"] = str(error)
                result.update(status="FAIL", cause="Job-owned process cleanup failed")
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        result["elapsed_seconds"] = round(time.monotonic() - start, 3)
        for name in ("stdout.txt", "stderr.txt"):
            (directory / name).touch(exist_ok=True)
        (directory / "observation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
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


def capture(root, build, out, prepare=False, observe_dialog=False):
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
            if observe_dialog:
                try:
                    report["recoverable_dialog_observation"] = observe_recoverable_dialog(
                        stage / "MikuDanceStudio.exe", pmm, out / "recoverable-dialog")
                except (OSError, ValueError, subprocess.SubprocessError) as error:
                    report["recoverable_dialog_observation"] = {"status": "FAIL", "cause": str(error)}
                save_report(out, report)
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
    parser.add_argument("--observe-recoverable-dialog", action="store_true")
    args = parser.parse_args()
    return capture(args.root, args.build, args.out, args.prepare, args.observe_recoverable_dialog)


if __name__ == "__main__":
    sys.exit(main())
