import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import probe
import validate


class ProbeTests(unittest.TestCase):
    def result(self):
        return {"status": "success", "syntax": [{"exit_code": 0}],
                "transpile": {"exit_code": 0}, "complete_translation": True,
                "input_sha256": {"libs/vkd3d-shader/hlsl.c": "fixture"},
                "stable_build": {"exit_code": 0}}

    def test_status_distinguishes_missing_timeout_translation_and_compiler_failures(self):
        self.assertEqual(probe.outcome({}), "incomplete")
        cases = [({"exit_code": 124, "timed_out": True}, "incomplete"),
                 ({"exit_code": -9}, "incomplete"),
                 ({"exit_code": 1}, "translation_failure")]
        for translation, expected in cases:
            with self.subTest(translation=translation):
                result = self.result()
                result["transpile"] = translation
                self.assertEqual(probe.outcome(result), expected)
        result = self.result()
        result["stable_build"]["exit_code"] = 101
        self.assertEqual(probe.outcome(result), "compiler_failure")
        result["prototype_build"] = {"exit_code": 0}
        self.assertEqual(probe.outcome(result), "prototype_success")

    def test_partial_or_placeholder_output_cannot_pass(self):
        result = self.result()
        result["complete_translation"] = False
        self.assertEqual(probe.outcome(result), "incomplete")
        result["invalid_output_markers"] = ["compile_error! fixture"]
        self.assertEqual(probe.outcome(result), "translation_failure")

    def test_completed_process_records_resources_and_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "command.log"
            result = probe.run([sys.executable, "-c", "print('completed')"], log, timeout=5)
            self.assertEqual(result["exit_code"], 0)
            self.assertGreater(result["max_rss_bytes"], 0)
            self.assertGreater(result["wall_seconds"], 0)
            self.assertEqual(log.read_text().strip(), "completed")

    def test_timeout_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            result = probe.run([sys.executable, "-c", "import time; time.sleep(60)"],
                               Path(directory) / "timeout.log", timeout=0.1)
            self.assertEqual(result["exit_code"], 124)
            self.assertLess(result["process_exit_code"], 0)
            self.assertTrue(result["timed_out"])
            self.assertLess(result["wall_seconds"], 5)

    def test_timeout_stops_spawned_children(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / "orphan-wrote-file"
            child = f"import time; from pathlib import Path; time.sleep(0.7); Path({str(sentinel)!r}).touch()"
            parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(60)"
            result = probe.run([sys.executable, "-c", parent], Path(directory) / "timeout.log", timeout=0.2)
            self.assertTrue(result["timed_out"])
            time.sleep(0.8)
            self.assertFalse(sentinel.exists())

    def test_hosted_validation_requires_stable_complete_expected_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            result = self.result()
            for status, code in (("success", 0), ("prototype_success", 1), ("incomplete", 1)):
                with self.subTest(status=status):
                    candidate = json.loads(json.dumps(result))
                    candidate["status"] = status
                    if status == "prototype_success":
                        candidate["stable_build"]["exit_code"] = 101
                        candidate["prototype_build"] = {"exit_code": 0}
                    elif status == "incomplete":
                        candidate["complete_translation"] = False
                    path.write_text(json.dumps(candidate))
                    with patch.object(sys, "argv", ["validate.py", str(path), "--expected-unit", "hlsl.c"]):
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(validate.main(), code)
            path.write_text(json.dumps(result))
            with patch.object(sys, "argv", ["validate.py", str(path), "--expected-unit", "hlsl.yy.c"]):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(validate.main(), 1)

    def test_linux_native_preserves_existing_output_before_download(self):
        script = Path(__file__).resolve().parents[1] / "vkd3d/build.sh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bin").mkdir()
            uname = root / "bin/uname"
            uname.write_text("#!/bin/sh\nprintf 'Linux\\n'\n")
            uname.chmod(0o755)
            existing = root / "work-linux-native"
            existing.mkdir()
            sentinel = existing / "user-data"
            sentinel.write_text("preserve")
            env = dict(os.environ, MDS_VKD3D_OUT=str(root), PATH=str(root / "bin") + os.pathsep + os.environ["PATH"])
            result = subprocess.run(["bash", str(script), "linux-native"], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("refusing to replace", result.stderr)
            self.assertEqual(sentinel.read_text(), "preserve")
            self.assertFalse((root / "dl").exists())
            uname.write_text("#!/bin/sh\nprintf 'Darwin\\n'\n")
            result = subprocess.run(["bash", str(script), "linux-native"], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires Linux", result.stderr)
            self.assertFalse((root / "dl").exists())

    def test_configured_source_layout_and_selected_parser_are_discovered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "prepared/work-linux-native/vkd3d-2.1"
            for subdirectory in ("libs/vkd3d-shader", "libs/vkd3d-common", "include"):
                (source / subdirectory).mkdir(parents=True)
            for name in ("hlsl.c", "hlsl.tab.c", "hlsl.yy.c", "vkd3d_shader_main.c"):
                (source / "libs/vkd3d-shader" / name).write_text("/* Copyright fixture. GNU Lesser General Public License. */\nvoid fixture(void) {}\n")
            (source / "libs/vkd3d-common/debug.c").touch()
            (source / "include/config.h").write_text("#define HAVE_CONFIG_H 1\n")
            (source / "LICENSE").write_text("LGPL-2.1-or-later fixture\n")
            artifacts = root / "result"

            def fake_tool(command, log, **kwargs):
                log.write_text("fixture tool\n")
                if "--emit-build-files" in command:
                    output = artifacts / "rust"
                    (output / "src").mkdir(parents=True)
                    (output / "src/hlsl_tab.rs").write_text('pub unsafe extern "C" fn fixture() {}\n')
                    (output / "Cargo.toml").write_text('[package]\nname="fixture"\nversion="0.0.0"\n')
                else:
                    self.assertTrue((artifacts / "source/include/config.h").is_file())
                return {"command": command, "exit_code": 0, "log": str(log)}

            arguments = ["probe.py", "--source", str(source), "--artifacts", str(artifacts),
                         "--c2rust", str(root / "bin/c2rust"), "--clang", "/usr/bin/clang",
                         "--filter", r'hlsl[.]tab[.]c$']
            with patch.object(sys, "argv", arguments), patch.object(probe, "run", fake_tool):
                with contextlib.redirect_stdout(io.StringIO()):
                    probe.main()
            result = json.loads((artifacts / "result.json").read_text())
            self.assertEqual(result["translation_units"], 1)
            self.assertEqual(result["translated_sources"], ["libs/vkd3d-shader/hlsl.tab.c"])
            self.assertEqual(result["status"], "success")
            self.assertTrue((artifacts / "externs.json").is_file())
            self.assertIn("Copyright fixture", (artifacts / "rust/src/hlsl_tab.rs").read_text())


if __name__ == "__main__":
    unittest.main()
