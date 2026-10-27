#!/usr/bin/env python3
"""Exercise the real PowerShell trust boundary with a stand-in child, no installation."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
PWSH = shutil.which("pwsh")

HARNESS = r'''
$ErrorActionPreference = 'Stop'
. $env:TEST_HELPER
function Invoke-WebRequest {
    param($Uri, $OutFile, $TimeoutSec, [switch]$PassThru)
    [IO.File]::WriteAllBytes($OutFile, [byte[]]::new($(if ($env:TEST_CASE -eq 'size') { 1 } else { 5211080 })))
}
function Get-FileHash {
    param($Path, $Algorithm)
    @{ Hash = $(if ($env:TEST_CASE -eq 'hash') { 'BAD' } else { 'C5E273A4A16AB4D5471E91C7477719A2F45DDADB76C7F98A38FA5074A6838654' }) }
}
function Get-AuthenticodeSignature {
    param($FilePath)
    $certificate = [pscustomobject]@{ Subject = 'CN=Microsoft Corporation'; Thumbprint = 'stand-in' }
    $certificate | Add-Member ScriptMethod GetNameInfo { param($Kind, $Issuer) $(if ($env:TEST_CASE -eq 'signer') { 'Someone Else' } else { 'Microsoft Corporation' }) }
    [pscustomobject]@{ Status = $(if ($env:TEST_CASE -eq 'signature') { 'NotTrusted' } else { 'Valid' })
        StatusMessage = 'STAND-IN; not Windows trust'; SignerCertificate = $certificate; TimeStamperCertificate = $null }
}
function Start-Process {
    param($FilePath, $ArgumentList, [switch]$PassThru, $WindowStyle, $RedirectStandardOutput, $RedirectStandardError)
    @($FilePath) + $ArgumentList | ConvertTo-Json | Set-Content $env:TEST_COMMAND
    Microsoft.PowerShell.Management\Start-Process -FilePath $env:TEST_PYTHON `
        -ArgumentList @('"' + $env:TEST_CHILD + '"') -PassThru `
        -RedirectStandardOutput $RedirectStandardOutput -RedirectStandardError $RedirectStandardError
}
function Get-Vc90PolicyEvidence {
    param($Destination)
    @{ status = 'STAND_IN_POLICY'; activation = 'NOT_EVALUATED' } | ConvertTo-Json | Set-Content (Join-Path $Destination 'policy.json')
    if ($env:TEST_CASE -eq 'policy') { throw 'Stand-in policy compatibility is unproven' }
}
try {
    Install-CaptureVc90 -Destination $env:TEST_RECEIPTS -ArchiveDirectory $env:TEST_ROOT -TimeoutSeconds 1
} catch { Write-Output $_; exit 1 }
'''


class ProvisionBoundary(unittest.TestCase):
    def test_untrusted_failed_and_timed_out_installers(self):
        self.assertIsNotNone(PWSH, "PowerShell is required; installer remains a stand-in")
        for case in ("size", "hash", "signature", "signer", "timeout", "nonzero", "policy", "success"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "harness.ps1").write_text(HARNESS)
                (root / "child.py").write_text(
                    "import os, pathlib, time\n"
                    "pathlib.Path(os.environ['TEST_MARKER']).write_text('started')\n"
                    "print('installer stdout', flush=True)\n"
                    "print('installer stderr', file=__import__('sys').stderr, flush=True)\n"
                    "if os.environ['TEST_CASE'] == 'timeout': time.sleep(60)\n"
                    "raise SystemExit(7 if os.environ['TEST_CASE'] == 'nonzero' else 0)\n")
                env = dict(os.environ, TEST_CASE=case, TEST_ROOT=tmp,
                           TEST_HELPER=str(HERE / "provision_capture_vc90.ps1"),
                           TEST_RECEIPTS=str(root / "receipts"), TEST_PYTHON=sys.executable,
                           TEST_CHILD=str(root / "child.py"), TEST_MARKER=str(root / "started"),
                           TEST_COMMAND=str(root / "command.json"))
                run = subprocess.run([PWSH, "-NoProfile", "-File", str(root / "harness.ps1")],
                                     env=env, capture_output=True, text=True, timeout=20)
                receipt = json.loads((root / "receipts/receipt.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(run.returncode, 0 if case == "success" else 1, run.stdout + run.stderr)
                self.assertEqual(receipt["activation"], "NOT_EVALUATED")
                executed = case in ("timeout", "nonzero", "policy", "success")
                self.assertEqual(receipt["process_started"], executed, receipt)
                self.assertEqual((root / "started").exists(), executed, receipt)
                self.assertEqual(receipt["timed_out"], case == "timeout", receipt)
                self.assertIsNone(receipt["cleanup_error"], receipt)
                if case != "success":
                    self.assertEqual(receipt["status"], "FAIL", receipt)
                if executed:
                    self.assertIn("installer stdout", (root / "receipts/stdout.txt").read_text())
                    self.assertIn("installer stderr", (root / "receipts/stderr.txt").read_text())
                    command = json.loads((root / "command.json").read_text(encoding="utf-8-sig"))
                    self.assertEqual(command[1:4], ["/qn", "/norestart", "/l"])
                if case == "nonzero":
                    self.assertEqual(receipt["returncode"], 7, receipt)
                if case == "timeout":
                    self.assertIsNotNone(receipt["returncode"], receipt)
                    probe = subprocess.run([PWSH, "-NoProfile", "-Command",
                                            f"if (Get-Process -Id {receipt['pid']} -ErrorAction SilentlyContinue) {{ exit 1 }}"],
                                           capture_output=True, timeout=10)
                    self.assertEqual(probe.returncode, 0, "owned child was not reaped")


    def test_installed_policy_requires_both_redirects_and_targets(self):
        self.assertIsNotNone(PWSH, "PowerShell is required")
        for case in ("compatible", "range", "target", "architecture"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifests = root / "WinSxS/Manifests"
                manifests.mkdir(parents=True)
                for name in ("CRT", "OpenMP"):
                    base = f"amd64_microsoft.vc90.{name}_1fc8b3b9a1e18e3b_9.0.30729.6161_none_test"
                    target = root / "WinSxS" / base
                    if case != "target" or name != "OpenMP":
                        target.mkdir()
                    (manifests / (base + ".manifest")).write_text(
                        '<assembly xmlns="urn:schemas-microsoft-com:asm.v1">'
                        f'<assemblyIdentity name="Microsoft.VC90.{name}" processorArchitecture="amd64" '
                        'type="win32" publicKeyToken="1fc8b3b9a1e18e3b" version="9.0.30729.6161"/></assembly>')
                    policy = root / "WinSxS" / f"amd64_policy.9.0.microsoft.vc90.{name}_test"
                    policy.mkdir()
                    old = "9.0.30729.0-9.0.30729.6161" if case == "range" else "9.0.21022.0-9.0.30729.6161"
                    arch = "x86" if case == "architecture" else "amd64"
                    (policy / "9.0.30729.6161.policy").write_text(
                        '<assembly xmlns="urn:schemas-microsoft-com:asm.v1">'
                        f'<assemblyIdentity name="policy.9.0.Microsoft.VC90.{name}" processorArchitecture="{arch}" '
                        'type="win32-policy" publicKeyToken="1fc8b3b9a1e18e3b" version="9.0.30729.6161"/>'
                        '<dependency><dependentAssembly>'
                        f'<assemblyIdentity name="Microsoft.VC90.{name}" processorArchitecture="amd64" '
                        'type="win32" publicKeyToken="1fc8b3b9a1e18e3b"/>'
                        f'<bindingRedirect oldVersion="{old}" newVersion="9.0.30729.6161"/>'
                        '</dependentAssembly></dependency></assembly>')
                receipts = root / "receipts"
                receipts.mkdir()
                env = dict(os.environ, WINDIR=tmp, TEST_HELPER=str(HERE / "provision_capture_vc90.ps1"),
                           TEST_RECEIPTS=str(receipts))
                run = subprocess.run([PWSH, "-NoProfile", "-Command",
                                      ". $env:TEST_HELPER; Get-Vc90PolicyEvidence -Destination $env:TEST_RECEIPTS"],
                                     env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(run.returncode, 0 if case == "compatible" else 1, run.stdout + run.stderr)
                evidence = json.loads((receipts / "policy.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(evidence["status"], "POLICY_AND_TARGET_PRESENT" if case == "compatible" else "UNPROVEN")
                self.assertEqual(len(evidence["assemblies"]), 4)
                self.assertEqual(len(list(receipts.glob("installed-*.xml"))), 4)
                self.assertIn("NOT_EVALUATED", evidence["activation"])


if __name__ == "__main__":
    unittest.main()
