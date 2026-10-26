#!/usr/bin/env python3
"""Exercise both shell smoke gates with local stand-ins; no build, GPU or host access."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent


class SmokeGate(unittest.TestCase):
    def test_comparator_status_and_log(self):
        for script in ("smoke.sh", "package-windows.sh"):
            cases = [(0, "golden rule: pass", None),
                     (1, "golden rule: FAIL", None),
                     (2, "comparison interrupted", None)]
            if script == "package-windows.sh":
                cases.extend((0, "golden rule: pass", case)
                             for case in ("nonzero", "positive-256", "negative-256"))
            for status, message, task_failure in cases:
                with self.subTest(script=script, status=status, task_failure=task_failure), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    package = root / "tools/package"
                    package.mkdir(parents=True)
                    shutil.copy2(HERE / script, package / script)
                    (root / "VERSION").write_text("test\n")
                    fx = root / "tests/fixtures/rust"
                    (fx / "mmegold").mkdir(parents=True)
                    for name in ("swing600.pmm", "swing600-golden.pmm", "chain8.pmd", "chain8.pmx",
                                 "chain8_ik.pmx", "morph4.pmx", "mmegold/anime.pmm", "mmegold/anime.fx"):
                        (fx / name).touch()
                    (fx / "mmegold/anime.emm").write_text("Pmd0 = anime.fx\n")
                    blink = root / "rust/crates/mds-mmert/tests/data/blink.gif"
                    blink.parent.mkdir(parents=True)
                    blink.touch()
                    out = root / "output"
                    (out / "vkd3d/windows/bin").mkdir(parents=True)
                    (out / "vkd3d/windows/bin/libvkd3d-shader-1.dll").touch()
                    stage = root / "stage/mds-app-test-macos"
                    stage.mkdir(parents=True)
                    self.executable(stage / "mds-app", '''#!/usr/bin/env bash
set -eu
stem="$(basename "$2" .pmm)"
out="$3"; shift 3
for frame in "$@"; do echo png >"$out/$stem-$frame.png"; done
''')
                    archive = out / "mds-app-test-macos.tar.gz"
                    subprocess.run(["tar", "-czf", str(archive), "-C", str(stage.parent), stage.name], check=True)
                    mocks = root / "bin"
                    mocks.mkdir()
                    self.executable(mocks / "python3", '''#!/usr/bin/env bash
echo "$COMPARE_MESSAGE"
echo "comparator diagnostic" >&2
exit "$COMPARE_STATUS"
''')
                    self.executable(mocks / "system_profiler", "#!/bin/sh\necho 'Chipset Model: mock'\n")
                    self.executable(mocks / "git", '''#!/bin/sh
case "$*" in
  *"--abbrev-ref HEAD") echo test ;;
  *"--short HEAD") echo abcdef ;;
esac
''')
                    self.executable(mocks / "ssh", '''#!/bin/sh
case "$*" in
  *runtask.ps1*)
    if [ -n "$TASK_FAILURE" ]; then
      exec "$REAL_PYTHON" -I "$TASK_TEST" --stand-in "$TASK_FAILURE"
    fi ;;
esac
exit 0
''')
                    self.executable(mocks / "scp", '''#!/usr/bin/env bash
dest="${@: -1}"
case "$dest" in
  *:*) ;;
  */) echo mock >"${dest}mds-app-test-abcdef-windows-x86_64.zip" ;;
  *) echo mock >"$dest" ;;
esac
''')
                    env = dict(os.environ, PATH=f"{mocks}:{os.environ['PATH']}",
                               MDS_PACKAGE_OUT=str(out), MDS_VKD3D_OUT=str(out / "vkd3d"),
                               COMPARE_STATUS=str(status), COMPARE_MESSAGE=message,
                               TASK_FAILURE=task_failure or "", REAL_PYTHON=sys.executable,
                               TASK_TEST=str(HERE.parent / "windows/test_runtask.py"))
                    args = ["bash", str(package / script)]
                    if script == "smoke.sh":
                        args.append(str(archive))
                    # The real PowerShell stand-in has its own 20-second child deadline.
                    run = subprocess.run(args, env=env, capture_output=True, text=True,
                                         timeout=30 if task_failure else 10)
                    log = out / ("smoke-macos.log" if script == "smoke.sh" else "smoke-windows.log")
                    if task_failure:
                        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
                        code = {"nonzero": 7, "positive-256": 256, "negative-256": -256}[task_failure]
                        self.assertIn(f"task exit code: {code}", run.stdout)
                        self.assertFalse(log.exists(), "failed smoke must stop before golden comparison")
                        continue
                    self.assertTrue(log.is_file(), run.stdout + run.stderr)
                    self.assertIn(message, log.read_text())
                    self.assertEqual(run.returncode == 0, status == 0, run.stdout + run.stderr)
                    self.assertIn("comparator diagnostic", log.read_text())

    @staticmethod
    def executable(path, content):
        path.write_text(content)
        path.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
