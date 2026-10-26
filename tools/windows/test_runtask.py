#!/usr/bin/env python3
"""Run the real PowerShell boundary with a stand-in scheduler, never a Windows host."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
PWSH = shutil.which("powershell" if os.name == "nt" else "pwsh")


def run_task(root, case):
    harness = root / "scheduler.ps1"
    harness.write_text(r'''
function schtasks {
    $op = $args[0]
    if ($op -notin @('/Create', '/Run', '/End', '/Delete')) { throw "Invalid scheduler operation '$op'" }
    Add-Content $env:TEST_CALLS ($args -join ' ')
    $global:LASTEXITCODE = 0
    if ($op -eq '/Create' -and $env:TEST_CASE -eq 'create-fail') {
        $global:LASTEXITCODE = 5
    }
    if ($op -eq '/Run') {
        switch ($env:TEST_CASE) {
            'run-fail' { $global:LASTEXITCODE = 6 }
            'timeout' { }
            'multiline' { Set-Content "$env:TEST_LOG.done" @('0', '0') }
            'malformed' { Set-Content "$env:TEST_LOG.done" '0 garbage' }
            'overflow' { Set-Content "$env:TEST_LOG.done" '99999999999999999999' }
            'empty' { Set-Content "$env:TEST_LOG.done" '' }
            'nonzero-cleanup-fail' { Set-Content "$env:TEST_LOG.done" '7' }
            'nonzero' { Set-Content "$env:TEST_LOG.done" '7' }
            default { Set-Content "$env:TEST_LOG.done" '0' }
        }
    }
    if ($op -eq '/Delete' -and $env:TEST_CASE -in @('cleanup-fail', 'nonzero-cleanup-fail')) {
        $global:LASTEXITCODE = 8
    }
}
& $env:TEST_RUNNER -Script (Join-Path $env:TEMP 'smoke.ps1') -Log $env:TEST_LOG -TimeoutSec 0 -Exclusive
exit $LASTEXITCODE
''')
    env = dict(os.environ, TEMP=str(root), USERNAME="stand-in",
               TEST_RUNNER=str(HERE / "runtask.ps1"), TEST_CASE=case,
               TEST_LOG=str(root / "smoke.log"), TEST_CALLS=str(root / "calls"))
    return subprocess.run([PWSH, "-NoProfile", "-File", str(harness)],
                          env=env, capture_output=True, text=True, timeout=20)


class TaskExit(unittest.TestCase):
    def test_terminal_status_and_cleanup(self):
        self.assertIsNotNone(PWSH, "PowerShell is required; scheduler remains a stand-in")
        for case, expected in (("success", 0), ("nonzero", 7), ("nonzero-cleanup-fail", 7), ("timeout", 1),
                               ("malformed", 1), ("multiline", 1), ("overflow", 1), ("empty", 1),
                               ("create-fail", 1), ("run-fail", 1), ("cleanup-fail", 1)):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "smoke.log.done").write_text("0\n")
                unrelated = root / "existing-directory"
                unrelated.mkdir()
                (unrelated / "keep").write_text("previous artifact")
                run = run_task(root, case)
                self.assertEqual(run.returncode, expected, run.stdout + run.stderr)
                calls = (root / "calls").read_text().splitlines()
                names = {line.split('/TN ')[1].split()[0] for line in calls}
                self.assertEqual(len(names), 1, calls)
                self.assertTrue(next(iter(names)).startswith('mds-lane-'), calls)
                self.assertEqual(any('/Delete ' in line for line in calls), case != 'create-fail', calls)
                self.assertEqual(any('/End ' in line for line in calls), case == 'timeout', calls)
                self.assertEqual((unrelated / "keep").read_text(), "previous artifact")
                self.assertFalse(list(root.glob('mds-lane-*.cmd')))
                self.assertIn('holding Global\\mds-console-input', run.stdout)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--stand-in":
        with tempfile.TemporaryDirectory() as tmp:
            result = run_task(Path(tmp), sys.argv[2])
            print(result.stdout, end='')
            print(result.stderr, end='', file=sys.stderr)
            sys.exit(result.returncode)
    unittest.main()
