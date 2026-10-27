#!/usr/bin/env python3
"""Exercise actual subprocess boundaries without claiming Windows/GPU coverage."""

import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("capture", Path(__file__).with_name("d3d9_capture.py"))
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


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
            self.assertEqual(len(report["copies"]), len(capture.SOURCES))
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
