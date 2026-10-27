#!/usr/bin/env python3
"""Exercise actual subprocess boundaries without claiming Windows/GPU coverage."""

import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("capture", Path(__file__).with_name("d3d9_capture.py"))
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


MATCHING_EVENT = r'''<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System><Provider Name="SideBySide"/><EventID>33</EventID><Level>2</Level>
    <TimeCreated SystemTime="2026-10-27T04:00:00.0054321Z"/>
    <EventRecordID>42</EventRecordID><Channel>Application</Channel><Computer>stand-in</Computer>
  </System>
  <EventData><Data>stand-in dependency resolution failure</Data>
    <Data>C:\isolated\MikuDanceStudio.exe</Data></EventData>
</Event>'''


class CaptureBoundary(unittest.TestCase):
    def test_actual_exit_timeout_and_partial_streams(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, body, timeout, status, code in (
                ("success", "print('ok')", 10, "PASS", 0),
                ("nonzero", "import sys; print('partial', flush=True); print('cause', file=sys.stderr); sys.exit(7)", 10, "FAIL", 7),
                ("timeout", "import time; print('partial', flush=True); time.sleep(5)", 0.2, "TIMEOUT", None),
            ):
                with self.subTest(name=name):
                    result = capture.run_command([sys.executable, "-c", body], root / name, timeout)
                    self.assertEqual(result["status"], status)
                    if code is not None:
                        self.assertEqual(result["returncode"], code)
                    self.assertTrue((root / name / "stderr.txt").exists())
                    self.assertIn("ok" if name == "success" else "partial", (root / name / "stdout.txt").read_text())
                    self.assertEqual(json.loads((root / name / "command.json").read_text()), result)
            for timeout in (0, 91):
                with self.assertRaises(ValueError):
                    capture.run_command([sys.executable], root / "invalid", timeout)
            result = capture.run_command([root / "missing.exe"], root / "launch-error")
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("launch failed", result["cause"])

    def test_structured_activation_error_and_bounded_process_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            error = OSError(22, "stand-in activation failure")
            error.winerror = 14001
            with patch.object(capture.subprocess, "Popen", side_effect=error):
                result = capture.run_command(["unchanged.exe", "--original"], Path(tmp) / "startup")
            self.assertFalse(result["process_started"])
            self.assertEqual(result["startup_error"]["winerror"], 14001)
            self.assertEqual(result["startup_error"]["errno"], 22)
            self.assertIsNone(result["returncode"])
            self.assertEqual(result["command"], ["unchanged.exe", "--original"])
            self.assertEqual(result["timeout_seconds"], 90)
            process = unittest.mock.Mock()
            process.wait.side_effect = [capture.subprocess.TimeoutExpired("stand-in", 0.1),
                                        capture.subprocess.TimeoutExpired("stand-in cleanup", 10)]
            process.poll.return_value = None
            with patch.object(capture.subprocess, "Popen", return_value=process):
                result = capture.run_command(["stand-in"], Path(tmp) / "timeout", 0.1)
            self.assertEqual(result["status"], "TIMEOUT")
            self.assertIn("0.1-second bound", result["cause"])
            self.assertIn("cleanup_error", result)
            process.kill.assert_called_once_with()
            self.assertEqual(process.wait.call_args.kwargs, {"timeout": 10})

    def test_scoped_activation_events_with_standin_commands(self):
        original = {"command": [r"C:\isolated\MikuDanceStudio.exe", "--mds-frame-dump"],
                    "cwd": "original frames", "startup_error": {"winerror": 14001},
                    "started_utc": "2026-10-27T04:00:00+00:00",
                    "finished_utc": "2026-10-27T04:00:00.010000+00:00"}
        for outcome in ("events", "empty", "invalid", "failure", "timeout", "exception", "message-failure"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp) / "diagnostic"
                calls = []
                real_run = capture.run_command

                def stand_in_tool(command, target, timeout):
                    calls.append([str(value) for value in command])
                    if target.name.startswith("events"):
                        if outcome == "exception":
                            raise OSError("stand-in diagnostic exception")
                        if outcome == "failure":
                            body = "raise SystemExit(9)"
                        elif outcome == "timeout":
                            return real_run([sys.executable, "-c", "import time; time.sleep(5)"], target, 0.1)
                        else:
                            xml = f"<Events>{MATCHING_EVENT}</Events>"
                            if outcome == "empty":
                                xml = "<Events/>"
                            elif outcome == "invalid":
                                xml = "invalid XML"
                            body = f"import sys; sys.stdout.buffer.write({xml.encode('utf-16')!r})"
                    elif target.name == "messages" and outcome == "message-failure":
                        body = "raise SystemExit(8)"
                    else:
                        body = "print('stand-in tool help or dependency resolution failure message')"
                    return real_run([sys.executable, "-c", body], target, timeout)

                with patch.object(capture, "run_command", side_effect=stand_in_tool), patch.dict(os.environ, {"SystemRoot": "stand-in Windows"}), patch.object(capture.time, "sleep"):
                    result = capture.activation_diagnostics(original, directory)
                self.assertEqual(result["status"], "COLLECTED" if outcome == "events" else "INCOMPLETE")
                self.assertEqual(result["original_startup_error"], {"winerror": 14001})
                self.assertFalse(result["retry"])
                self.assertEqual(json.loads((directory / "diagnostic.json").read_text()), result)
                for command in calls:
                    self.assertTrue(command[0].endswith("wevtutil.exe"))
                    self.assertNotIn("stoptrace", command)
                    if "Application" in command:
                        query = next(value for value in command if value.startswith("/q:"))
                        self.assertIn("Provider[@Name='SideBySide']", query)
                        self.assertIn("EventData[Data='C:\\isolated\\MikuDanceStudio.exe']", query)
                        self.assertIn("2026-10-27T04:00:02.010Z", query)
                        self.assertIn("/c:8", command)
                self.assertLessEqual(len(calls), 5)
                if outcome == "timeout":
                    self.assertEqual(result["commands"][-1]["status"], "TIMEOUT")

    def test_main_validates_returned_activation_event_records(self):
        valid = MATCHING_EVENT
        namespace = ' xmlns="http://schemas.microsoft.com/win/2004/08/events/event"'
        provider = '<Provider Name="SideBySide"/>'
        cases = {
            "matching": (f"<Events>{valid}</Events>", 1),
            "empty": ("<Events/>", 0),
            "syntax": ("<Events>", 0),
            "wrong-root": (f"<Other>{valid}</Other>", 0),
            "unrelated-child": ("<Events><NotAnEvent/></Events>", 0),
            "event-as-wrapper": (valid, 0),
            "missing-namespace": (f'<Events>{valid.replace(namespace, "")}</Events>', 0),
            "wrong-namespace": (f'<Events>{valid.replace("/events/event", "/events/other")}</Events>', 0),
            "wrong-provider": (f'<Events>{valid.replace("SideBySide", "Unrelated")}</Events>', 0),
            "wrong-path": (f'<Events>{valid.replace("MikuDanceStudio.exe", "other.exe")}</Events>', 0),
            "partial-path": (f'<Events>{valid.replace("MikuDanceStudio.exe</Data>", "MikuDanceStudio.exe.extra</Data>")}</Events>', 0),
            "missing-provider": (f'<Events>{valid.replace(provider, "")}</Events>', 0),
            "missing-time": (f'<Events>{valid.replace("TimeCreated", "OtherTime")}</Events>', 0),
            "missing-data": (f'<Events>{valid.replace("EventData", "UserData")}</Events>', 0),
        }
        for label, stamp in (
            ("before", "2026-10-27T03:59:59.9999999Z"),
            ("after", "2026-10-27T04:00:02.011Z"),
            ("after-submicrosecond", "2026-10-27T04:00:02.0100001Z"),
            ("malformed-time", "not a timestamp"),
            ("invalid-date", "2026-02-30T04:00:00Z"),
            ("naive-time", "2026-10-27T04:00:00"),
            ("non-utc", "2026-10-27T05:00:00+01:00"),
            ("non-schema-time", "2026-10-27 04:00:00Z"),
        ):
            cases[label] = (f'<Events>{valid.replace("2026-10-27T04:00:00.0054321Z", stamp)}</Events>', 0)
        for label, stamp in (("lower-bound", "2026-10-27T04:00:00Z"),
                             ("upper-bound", "2026-10-27T04:00:02.0100000Z")):
            cases[label] = (f'<Events>{valid.replace("2026-10-27T04:00:00.0054321Z", stamp)}</Events>', 1)
        cases["mixed"] = (f'<Events>{valid}<NotAnEvent/>{valid.replace("SideBySide", "Unrelated")}'
                          f'{valid.replace("2026-10-27T04:00:00.0054321Z", "invalid")}{valid}</Events>', 2)
        for label, (xml, count) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root, out, build = (Path(tmp) / name for name in ("repo", "evidence", "build"))
                root.mkdir()
                build.mkdir()
                for name in capture.SOURCES + capture.ASSETS:
                    source = root / name
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_text("stand-in source")
                for name in ("MikuDanceStudio.exe", "d3d9_capability.exe"):
                    (build / name).write_text("stand-in executable")
                real_run = capture.run_command
                calls = []

                def stand_in_process(command, target, timeout=capture.TIMEOUT):
                    calls.append([str(value) for value in command])
                    if target.name == "frames":
                        error = OSError(22, "original activation failure")
                        error.winerror = 14001
                        with patch.object(capture.subprocess, "Popen", side_effect=error):
                            result = real_run(command, target, timeout)
                        result.update(command=[r"C:\isolated\MikuDanceStudio.exe", "--mds-frame-dump"],
                                      started_utc="2026-10-27T04:00:00+00:00",
                                      finished_utc="2026-10-27T04:00:00.010000+00:00")
                        return result
                    body = f"import sys; sys.stdout.buffer.write({xml.encode('utf-16')!r})" if target.name.startswith("events-") else "print('stand-in help or message')"
                    return real_run([sys.executable, "-c", body], target, timeout)

                argv = ["d3d9_capture.py", "--root", str(root), "--build", str(build), "--out", str(out)]
                with patch.object(capture, "os", SimpleNamespace(name="nt", environ=os.environ)), patch.dict(os.environ, {"SystemRoot": "stand-in Windows"}), patch.object(capture, "run_command", side_effect=stand_in_process), patch.object(capture.time, "sleep"), patch.object(sys, "argv", argv):
                    self.assertEqual(capture.main(), 1)
                report = json.loads((out / "report.json").read_text())
                diagnostic = report["activation_diagnostics"][0]
                self.assertEqual(diagnostic["status"], "COLLECTED" if count else "INCOMPLETE")
                self.assertEqual(diagnostic.get("event_count", 0), count)
                self.assertEqual(report["status"], "FAIL")
                self.assertEqual(report["commands"][2]["status"], "FAIL")
                self.assertEqual(report["commands"][2]["startup_error"]["winerror"], 14001)
                self.assertIn("original activation failure", report["commands"][2]["cause"])
                self.assertEqual(report["commands"][3]["status"], "PASS")
                self.assertEqual(report["cause"], report["original_error"])
                self.assertEqual(report["closure"]["status"], "PASS")
                self.assertEqual(len(report["closure"]["checks"]), 2 * len(report["copies"]))
                self.assertEqual((out / "activation/frames/events-0/stdout.txt").read_bytes(), xml.encode("utf-16"))
                self.assertTrue((out / "activation/frames/help/command.json").exists())
                self.assertTrue((out / "activation/frames/query-help/stdout.txt").exists())
                self.assertEqual((out / "activation/frames/messages/stdout.txt").exists(), bool(count))
                self.assertLessEqual(sum("wevtutil.exe" in call[0] for call in calls), 5)

    def test_activation_diagnostic_failure_preserves_capture_and_closure(self):
        for winerror, diagnostic_failure in ((14001, False), (14001, True), (2, False), (None, False)):
            with self.subTest(winerror=winerror, diagnostic_failure=diagnostic_failure), tempfile.TemporaryDirectory() as tmp:
                root, out, build = (Path(tmp) / name for name in ("repo", "evidence", "build"))
                root.mkdir()
                build.mkdir()
                for name in capture.SOURCES + capture.ASSETS:
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("stand-in source")
                for name in ("MikuDanceStudio.exe", "d3d9_capability.exe"):
                    (build / name).write_text("stand-in executable")
                real_run = capture.run_command

                def stand_in_process(command, directory):
                    if directory.name == "frames":
                        error = OSError(22, "first activation error")
                        error.winerror = winerror
                        with patch.object(capture.subprocess, "Popen", side_effect=error):
                            return real_run(command, directory)
                    return real_run([sys.executable, "-c", "print('stand-in')"], directory)

                diagnostic = {"status": "INCOMPLETE", "cause": "stand-in missing event", "retry": False}
                windows = SimpleNamespace(name="nt", environ=os.environ)
                with patch.object(capture, "os", windows), patch.object(capture, "run_command", side_effect=stand_in_process), patch.object(capture, "activation_diagnostics", side_effect=OSError("diagnostic failed") if diagnostic_failure else None, return_value=diagnostic) as diagnose:
                    self.assertEqual(capture.capture(root, build, out), 1)
                report = json.loads((out / "report.json").read_text())
                if winerror == 14001:
                    diagnose.assert_called_once()
                else:
                    diagnose.assert_not_called()
                self.assertEqual(len(report["commands"]), 4)
                self.assertEqual(report["commands"][2]["startup_error"]["winerror"], winerror)
                self.assertIn("first activation error", report["commands"][2]["cause"])
                self.assertEqual(report["commands"][3]["status"], "PASS")
                self.assertEqual(report["closure"]["status"], "PASS")
                self.assertEqual(len(report["closure"]["checks"]), 2 * len(report["copies"]))
                self.assertIn("Native command failed", report["original_error"])
                self.assertEqual(report["cause"], report["original_error"])
                if winerror == 14001:
                    self.assertEqual(report["activation_diagnostics"][0]["status"], "INCOMPLETE")
                else:
                    self.assertNotIn("activation_diagnostics", report)
                self.assertFalse((out / "frames" / "selfshadow-0.png").exists())

    def test_missing_asset_is_strict_failure_with_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out = Path(tmp) / "repo", Path(tmp) / "evidence"
            root.mkdir()
            for name in capture.SOURCES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("source")
            self.assertEqual(capture.capture(root, root / "build", out), 1)
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("chain8.pmd", report["cause"])
            self.assertEqual(report["commands"], [])
            self.assertEqual(len(report["copies"]), len(capture.SOURCES) + 1)
            self.assertEqual(report["closure"]["tracked_copies"], len(capture.SOURCES) + 1)
            self.assertEqual(len(report["closure"]["checks"]), 2 * (len(capture.SOURCES) + 1))
            missing = report["closure"]["checks"][-2]
            self.assertEqual(missing["status"], "missing")
            self.assertIsNone(missing["initial_sha256"])
            self.assertIn("initial_error", missing)
            self.assertTrue(report["files"])

    def test_prepared_hash_drift_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out = Path(tmp) / "repo", Path(tmp) / "evidence"
            root.mkdir()
            for name in capture.SOURCES + capture.ASSETS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("source")
            real_run = capture.run_command
            def stand_in_git(command, directory):
                return real_run([sys.executable, "-c", "print('fixture-revision')"], directory)
            with patch.object(capture, "run_command", side_effect=stand_in_git):
                self.assertEqual(capture.capture(root, root / "build", out, prepare=True), 0)
            original = out / "source" / capture.ASSETS[0]
            self.assertEqual(original.read_text(), "source")
            (root / capture.ASSETS[0]).write_text("changed")
            self.assertEqual(capture.capture(root, root / "build", out), 1)
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("Prepared source hash changed", report["cause"])
            self.assertFalse((out / "runtime").exists())
            self.assertEqual(original.read_text(), "source")

    def test_zero_exit_without_frames_is_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out, build = Path(tmp) / "repo", Path(tmp) / "evidence", Path(tmp) / "build"
            root.mkdir()
            build.mkdir()
            for name in capture.SOURCES + capture.ASSETS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("source")
            for name in ("MikuDanceStudio.exe", "d3d9_capability.exe"):
                (build / name).write_text("stand-in executable")
            real_run = capture.run_command
            def stand_in_process(command, directory):
                return real_run([sys.executable, "-c", "print('diagnostic_result=supported;')"], directory)
            with patch.object(capture, "run_command", side_effect=stand_in_process):
                self.assertEqual(capture.capture(root, build, out), 1)
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(len(report["commands"]), 4)
            self.assertTrue(all(command["status"] == "PASS" for command in report["commands"]))
            self.assertIn("selfshadow-0.png", report["cause"])
            self.assertTrue((out / "edge" / "stdout.txt").exists())
            with self.assertRaisesRegex(FileExistsError, "existing runtime"):
                capture.capture(root, build, out)

    def test_partial_staging_checks_known_files_after_setup_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out = Path(tmp) / "repo", Path(tmp) / "evidence"
            root.mkdir()
            for name in capture.SOURCES + capture.ASSETS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("source")
            real_run = capture.run_command
            with patch.object(capture, "run_command", side_effect=lambda command, directory:
                              real_run([sys.executable, "-c", "print('fixture-revision')"], directory)):
                self.assertEqual(capture.capture(root, root / "missing-build", out), 1)
            report = json.loads((out / "report.json").read_text())
            self.assertIn("MikuDanceStudio.exe", report["original_error"])
            self.assertIn(report["original_error"], report["cause"])
            self.assertEqual(len(report["closure"]["checks"]), 2 * len(report["copies"]))
            self.assertTrue(all(check["status"] == "unchanged" for check in report["closure"]["checks"][:-2]))
            self.assertTrue(all(check["status"] == "missing" for check in report["closure"]["checks"][-2:]))

    def test_final_closure_on_actual_process_failures_and_success(self):
        for role in ("source", "copy"):
            for failure in ("nonzero", "timeout", "outputs", "success"):
                for mutation in ("changed", "missing", "unreadable", "unchanged"):
                    with self.subTest(role=role, failure=failure, mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                        root, out, build = (Path(tmp).resolve() / name for name in ("repo", "evidence", "build"))
                        root.mkdir()
                        build.mkdir()
                        for name in capture.SOURCES + capture.ASSETS:
                            path = root / name
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_text("source")
                        for name in ("MikuDanceStudio.exe", "d3d9_capability.exe"):
                            (build / name).write_text("stand-in executable")
                        target = root / capture.ASSETS[0] if role == "source" else out / "runtime" / Path(capture.ASSETS[0]).name
                        initial = capture.digest(root / capture.ASSETS[0])
                        real_run = capture.run_command

                        def stand_in_process(command, directory):
                            body = "from pathlib import Path; import struct, time; print('diagnostic_result=supported;', flush=True); "
                            if directory.name == "frames":
                                body += f"target = Path({str(target)!r}); "
                                if mutation == "changed":
                                    body += "target.write_text('changed'); "
                                elif mutation == "missing":
                                    body += "target.unlink(); "
                                elif mutation == "unreadable":
                                    body += "target.unlink(); target.mkdir(); "
                                if failure == "nonzero":
                                    body += "raise SystemExit(7)"
                                elif failure == "timeout":
                                    body += "time.sleep(5)"
                                elif failure == "success":
                                    png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 640, 360) + b"\0" * 9 + b"\0\0\0\0IEND\xaeB`\x82"
                                    body += f"[Path('selfshadow-' + str(frame) + '.png').write_bytes({png!r}) for frame in (0, 30)]"
                            elif directory.name == "edge":
                                body += "Path('selfshadow.edge.txt').write_text('mds-edge-probe 1\\n0 shadow 2048 2048 1\\n30 shadow 2048 2048 1\\n')"
                            return real_run([sys.executable, "-c", body], directory,
                                            0.2 if failure == "timeout" and directory.name == "frames" else 10)

                        with patch.object(capture, "run_command", side_effect=stand_in_process):
                            self.assertEqual(capture.capture(root, build, out),
                                             0 if failure == "success" and mutation == "unchanged" else 1)
                        report = json.loads((out / "report.json").read_text())
                        self.assertEqual(report["status"], "PASS" if failure == "success" and mutation == "unchanged" else "FAIL")
                        self.assertEqual(report["closure"]["status"], "PASS" if mutation == "unchanged" else "FAIL")
                        checks = [check for check in report["closure"]["checks"]
                                  if check["path"] == str(target) and check["role"] == role]
                        self.assertTrue(checks)
                        for check in checks:
                            self.assertEqual(check["initial_sha256"], initial)
                            self.assertEqual(check["status"], mutation)
                            if mutation in ("changed", "unchanged"):
                                self.assertEqual(check["final_sha256"], capture.digest(target))
                            else:
                                self.assertIsNone(check["final_sha256"])
                                self.assertIn("error", check)
                        self.assertEqual(len(report["closure"]["checks"]), 2 * len(report["copies"]))
                        self.assertEqual(len(report["commands"]), 4)
                        if failure in ("nonzero", "timeout"):
                            self.assertIn("Native command failed", report["original_error"])
                            self.assertEqual(report["commands"][2]["status"], "TIMEOUT" if failure == "timeout" else "FAIL")
                        elif failure == "outputs":
                            self.assertIn("selfshadow-0.png", report["original_error"])
                        else:
                            self.assertNotIn("original_error", report)
                            self.assertTrue(all(command["status"] == "PASS" for command in report["commands"]))
                        if failure != "success":
                            self.assertIn(report["original_error"], report["cause"])
                        if mutation != "unchanged":
                            self.assertIn("closure failed", report["cause"])

    def test_copy_hash_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "asset", Path(tmp) / "stage" / "asset"
            source.write_bytes(b"fixture")
            manifest = []
            capture.copy_checked(source, target, manifest)
            self.assertEqual(capture.digest(source), capture.digest(target))
            self.assertEqual(manifest[0]["sha256"], capture.digest(source))
            with self.assertRaises(FileExistsError):
                capture.copy_checked(source, target, manifest)
            target.write_bytes(b"keep")
            self.assertEqual(source.read_bytes(), b"fixture")

    def test_output_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "frames").mkdir()
            (out / "edge").mkdir()
            with self.assertRaises(FileNotFoundError):
                capture.validate_outputs(out)
            png_header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 640, 360) + b"\0" * 9 + b"\0\0\0\0IEND\xaeB`\x82"
            for frame in (0, 30):
                (out / "frames" / f"selfshadow-{frame}.png").write_bytes(png_header)
            edge = out / "edge" / "selfshadow.edge.txt"
            edge.write_text("mds-edge-probe 1\n0 shadow 2048 2048 1\n")
            with self.assertRaisesRegex(ValueError, "frame 30"):
                capture.validate_outputs(out)
            edge.write_text(edge.read_text() + "30 shadow 2048 2048 1\n")
            capture.validate_outputs(out)
            (out / "frames" / "selfshadow-30.png").write_bytes(b"partial PNG")
            with self.assertRaisesRegex(ValueError, "invalid"):
                capture.validate_outputs(out)


if __name__ == "__main__":
    unittest.main()
