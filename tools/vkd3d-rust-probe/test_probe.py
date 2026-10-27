import contextlib
import io
import json
import os
from pathlib import Path
import signal
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

    def test_extern_inventory_preserves_all_abis_and_unresolved_symbols(self):
        inventory = probe.extern_inventory(['unsafe extern "C" {\n    fn ordinary();\n}\nunsafe extern "win64" {\n    fn callback();\n}\nunsafe extern "sysv64" {\n    fn other();\n}\npub unsafe extern "win64" fn translated() {}\npub unsafe extern "C" fn ordinary() {}\n'])
        self.assertEqual(inventory['declared'], ['callback', 'ordinary', 'other'])
        self.assertEqual(inventory['defined'], ['ordinary', 'translated'])
        self.assertEqual(inventory['unresolved_declared'], ['callback', 'other'])
        self.assertEqual(inventory['by_abi']['win64']['defined'], ['translated'])

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

    def test_translation_only_is_distinct_and_still_rejects_failed_translation(self):
        result = self.result()
        result.pop('stable_build')
        result['translation_only'] = True
        self.assertEqual(probe.outcome(result), 'translation_only_success')
        result['transpile']['exit_code'] = 101
        self.assertEqual(probe.outcome(result), 'translation_failure')

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

    def test_interruption_and_exception_kill_and_reap_owned_child(self):
        spawn = subprocess.Popen
        for exception in (KeyboardInterrupt, RuntimeError):
            with self.subTest(exception=exception.__name__), tempfile.TemporaryDirectory() as directory:
                children = []
                def record_child(*args, **kwargs):
                    child = spawn(*args, **kwargs)
                    children.append(child)
                    return child
                try:
                    with patch.object(probe.subprocess, "Popen", side_effect=record_child):
                        with patch.object(probe.time, "sleep", side_effect=exception):
                            with self.assertRaises(exception):
                                probe.run([sys.executable, "-c", "import time; time.sleep(60)"],
                                          Path(directory) / "interrupted.log", timeout=5)
                    self.assertEqual(len(children), 1)
                    with self.assertRaises(ProcessLookupError):
                        os.kill(children[0].pid, 0)
                    with self.assertRaises(ChildProcessError):
                        os.waitpid(children[0].pid, os.WNOHANG)
                finally:
                    for child in children:
                        if child.poll() is None:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait()

    def test_cli_signals_leave_checkpoint_and_no_child(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=signum), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = self.source_fixture(root)
                pid_file = root / "child.pid"
                compiler = root / "clang"
                compiler.write_text(f"#!{sys.executable}\nimport os,time\nfrom pathlib import Path\nPath({str(pid_file)!r}).write_text(str(os.getpid()))\ntime.sleep(60)\n")
                compiler.chmod(0o755)
                artifacts = root / "result"
                process = subprocess.Popen([sys.executable, probe.__file__, "--source", str(source),
                                            "--artifacts", str(artifacts), "--clang", str(compiler),
                                            "--c2rust", str(root / "c2rust"), "--filter", r'hlsl[.]c$'],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 5
                    while not pid_file.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(pid_file.exists(), "fixture compiler did not start")
                    os.kill(process.pid, signum)
                    _, stderr = process.communicate(timeout=3)
                    self.assertNotEqual(process.returncode, 0, stderr.decode())
                    with self.assertRaises(ProcessLookupError):
                        os.kill(int(pid_file.read_text()), 0)
                    self.assertEqual(json.loads((artifacts / "result.json").read_text())["status"], "incomplete")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()
                    if pid_file.exists():
                        try:
                            os.kill(int(pid_file.read_text()), signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def source_fixture(self, root):
        source = root / "source"
        for subdirectory in ("libs/vkd3d-shader", "libs/vkd3d-common", "include"):
            (source / subdirectory).mkdir(parents=True)
        for name in ("hlsl.c", "hlsl.tab.c", "hlsl.yy.c", "vkd3d_shader_main.c"):
            (source / "libs/vkd3d-shader" / name).write_text("/* Copyright fixture. GNU Lesser General Public License. */\nvoid fixture(void) {}\n")
        (source / "libs/vkd3d-common/debug.c").touch()
        (source / "include/config.h").write_text("#define HAVE_CONFIG_H 1\n")
        (source / "LICENSE").write_text("LGPL-2.1-or-later fixture\n")
        return source

    def test_existing_artifact_root_rejects_stale_success_before_tools(self):
        for stale_output in (False, True):
            with self.subTest(stale_output=stale_output), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = self.source_fixture(root)
                artifacts = root / "result"
                artifacts.mkdir()
                stale = artifacts / "rust/src/hlsl.rs"
                if stale_output:
                    stale.parent.mkdir(parents=True)
                    stale.write_text('pub unsafe extern "C" fn stale() {}\n')
                    (artifacts / "rust/Cargo.toml").write_text('[package]\nname="stale"\nversion="0.0.0"\n')
                def no_output(command, log, **kwargs):
                    log.write_text("fake tool returned zero without output\n")
                    return {"command": command, "exit_code": 0, "log": str(log)}
                arguments = ["probe.py", "--source", str(source), "--artifacts", str(artifacts),
                             "--c2rust", str(root / "bin/c2rust"), "--clang", "/usr/bin/clang", "--filter", r'hlsl[.]c$']
                with patch.object(sys, "argv", arguments), patch.object(probe, "run", side_effect=no_output) as tool:
                    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                        with self.assertRaises(SystemExit) as error:
                            probe.main()
                    self.assertEqual(error.exception.code, 2)
                    tool.assert_not_called()
                self.assertFalse((artifacts / "result.json").exists())
                if stale_output:
                    self.assertEqual(stale.read_text(), 'pub unsafe extern "C" fn stale() {}\n')

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
                    self.assertIn("--emit-variadic-inventory", command)
                    self.assertNotIn("--emit-c-decl-map", command)
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
