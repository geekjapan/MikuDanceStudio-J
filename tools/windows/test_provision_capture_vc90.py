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
        positive = ("root_control", "policies_location", "manifest_location", "all_stores",
                    "multiple_versions", "disjoint_redirects", "single_version", "explicit_namespace",
                    "optional_stores_absent", "unrelated_files", "target_noInheritable")
        negative = ("range", "target", "architecture", "namespace_reset", "namespace_empty",
                    "mixed_identity", "mixed_redirect", "duplicate_identity", "duplicate_reference",
                    "conflicting_redirect", "conflicting_dependencies", "duplicate_redirect", "cross_copy_conflict", "missing_manifestVersion",
                    "wrong_manifestVersion", "target_manifestVersion", "target_duplicate_identity",
                    "target_namespace", "short_old", "short_versions", "short_new", "short_policy",
                    "overflow_old", "overflow_new", "overflow_target", "negative_version",
                    "nondigit_version", "reversed_range", "extra_range", "spaced_range",
                    "wrong_hierarchy", "nested_redirect", "missing_reference", "missing_redirect",
                    "missing_token", "wrong_reference", "missing_type", "missing_version",
                    "target_mismatch", "wrong_root", "malformed_xml")
        for case in positive + negative:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifests = root / "WinSxS/Manifests"
                manifests.mkdir(parents=True)
                expected_records = 0
                for name in ("CRT", "OpenMP"):
                    version = "9.0" if case == "short_versions" else "9.0.30729.6161"
                    base = f"amd64_microsoft.vc90.{name}_1fc8b3b9a1e18e3b_{version}_none_test"
                    target = root / "WinSxS" / base
                    if case != "target" or name != "OpenMP":
                        target.mkdir()
                    definition = (f'<assemblyIdentity name="Microsoft.VC90.{name}" processorArchitecture="amd64" '
                                  f'type="win32" publicKeyToken="1fc8b3b9a1e18e3b" version="{version}"/>')
                    target_xml = ('<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">'
                                  + definition + '<file name="runtime.dll"/></assembly>')
                    if case == "target_noInheritable":
                        target_xml = target_xml.replace(definition, '<noInheritable/>' + definition)
                    if case == "target_manifestVersion":
                        target_xml = target_xml.replace(' manifestVersion="1.0"', '')
                    if case == "target_duplicate_identity":
                        target_xml = target_xml.replace(definition, definition + definition)
                    if case == "target_namespace":
                        target_xml = target_xml.replace('<assemblyIdentity ', '<assemblyIdentity xmlns="" ')
                    if case == "overflow_target":
                        target_xml = target_xml.replace(version, "9.0.65536.1")
                    if case == "target_mismatch":
                        target_xml = target_xml.replace(version, "9.0.30729.6160")
                    (manifests / (base + ".manifest")).write_text(target_xml)
                    expected_records += 1
                    identity = (f'<assemblyIdentity name="policy.9.0.Microsoft.VC90.{name}" '
                                'processorArchitecture="amd64" type="win32-policy" '
                                'publicKeyToken="1fc8b3b9a1e18e3b" version="9.0.30729.6161"/>')
                    reference = (f'<assemblyIdentity name="Microsoft.VC90.{name}" processorArchitecture="amd64" '
                                 'type="win32" publicKeyToken="1fc8b3b9a1e18e3b"/>')
                    old = {
                        "range": "9.0.30729.0-9.0.30729.6161", "short_old": "9.0-9.0.30729.6161",
                        "short_versions": "9.0-10.0", "overflow_old": "9.0.21022.0-9.0.65536.1",
                        "reversed_range": "9.0.30729.6161-9.0.21022.0", "extra_range": "9.0.0.0-9.0.1.0-9.0.2.0",
                        "spaced_range": "9.0.21022.0 -9.0.30729.6161", "single_version": "9.0.21022.8",
                    }.get(case, "9.0.21022.0-9.0.30729.6161")
                    redirect = f'<bindingRedirect oldVersion="{old}" newVersion="{version}"/>'
                    policy_xml = ('<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">'
                                  + identity + '<dependency><dependentAssembly>' + reference + redirect
                                  + '</dependentAssembly></dependency></assembly>')
                    if case == "architecture":
                        policy_xml = policy_xml.replace('processorArchitecture="amd64"', 'processorArchitecture="x86"', 1)
                    if case in ("namespace_reset", "namespace_empty"):
                        policy_xml = policy_xml.replace('<dependency>', '<dependency xmlns="' + ("urn:invalid" if case == "namespace_reset" else "") + '">')
                    if case == "mixed_identity":
                        policy_xml = policy_xml.replace(reference, reference.replace('<assemblyIdentity ', '<assemblyIdentity xmlns="urn:invalid" '))
                    if case == "mixed_redirect":
                        policy_xml = policy_xml.replace('<bindingRedirect ', '<bindingRedirect xmlns="urn:invalid" ')
                    if case == "duplicate_identity":
                        policy_xml = policy_xml.replace(identity, identity + identity.replace('amd64', 'x86'))
                    if case == "duplicate_reference":
                        policy_xml = policy_xml.replace(reference, reference + reference)
                    if case in ("conflicting_redirect", "conflicting_dependencies", "duplicate_redirect", "disjoint_redirects"):
                        second = ('<bindingRedirect oldVersion="' + ("9.0.40000.0-9.0.40000.1" if case == "disjoint_redirects" else old)
                                  + '" newVersion="9.0.9999.9"/>')
                        if case in ("disjoint_redirects", "conflicting_dependencies"):
                            policy_xml = policy_xml.replace('</dependency>', '</dependency><dependency><dependentAssembly>'
                                                            + reference + second + '</dependentAssembly></dependency>')
                        else:
                            policy_xml = policy_xml.replace(redirect, redirect + (redirect if case == "duplicate_redirect" else second))
                    if case in ("missing_manifestVersion", "wrong_manifestVersion"):
                        policy_xml = policy_xml.replace(' manifestVersion="1.0"', '' if case == "missing_manifestVersion" else ' manifestVersion="2.0"')
                    if case == "short_new":
                        policy_xml = policy_xml.replace('newVersion="' + version + '"', 'newVersion="9.0"')
                    if case in ("short_policy", "missing_version"):
                        policy_xml = policy_xml.replace(' version="9.0.30729.6161"', ' version="9.0"' if case == "short_policy" else '')
                    for control, bad in (("overflow_new", "9.0.65536.1"), ("negative_version", "9.0.-1.1"), ("nondigit_version", "9.0.a.1")):
                        if case == control:
                            policy_xml = policy_xml.replace('newVersion="' + version + '"', f'newVersion="{bad}"')
                    if case == "wrong_hierarchy":
                        policy_xml = policy_xml.replace('<dependency>', '<wrapper>').replace('</dependency>', '</wrapper>')
                    if case == "nested_redirect":
                        policy_xml = policy_xml.replace(redirect, '<wrapper>' + redirect + '</wrapper>')
                    if case == "missing_reference":
                        policy_xml = policy_xml.replace(reference, '')
                    if case == "missing_redirect":
                        policy_xml = policy_xml.replace(redirect, '')
                    if case == "missing_token":
                        policy_xml = policy_xml.replace(' publicKeyToken="1fc8b3b9a1e18e3b"', '')
                    if case == "missing_type":
                        policy_xml = policy_xml.replace(' type="win32-policy"', '')
                    if case == "wrong_reference":
                        policy_xml = policy_xml.replace(reference, reference.replace(name, "Other"))
                    if case == "wrong_root":
                        policy_xml = policy_xml.replace('<assembly ', '<wrapper ').replace('</assembly>', '</wrapper>')
                    if case == "malformed_xml":
                        policy_xml = policy_xml[:-1]
                    if case == "explicit_namespace":
                        policy_xml = policy_xml.replace('<dependency>', '<dependency xmlns="urn:schemas-microsoft-com:asm.v1">')
                    stores = ("root", "Policies", "Manifests") if case == "all_stores" else (
                        ("Policies",) if case in ("policies_location", "multiple_versions", "cross_copy_conflict") else
                        ("Manifests",) if case in ("manifest_location", "optional_stores_absent") else ("root",))
                    for store in stores:
                        if store == "Manifests":
                            path = manifests / f"amd64_policy.9.0.microsoft.vc90.{name}_test.manifest"
                        else:
                            parent = root / "WinSxS" if store == "root" else root / "WinSxS/Policies"
                            path = parent / f"amd64_policy.9.0.microsoft.vc90.{name}_test/9.0.30729.6161.policy"
                            path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(policy_xml)
                        expected_records += 1
                        if case in ("multiple_versions", "cross_copy_conflict"):
                            other = policy_xml.replace('newVersion="' + version + '"', 'newVersion="9.0.9999.9"')
                            if case == "multiple_versions":
                                other = other.replace('version="9.0.30729.6161"', 'version="9.0.9999.9"')
                            path.with_name("9.0.9999.9.policy").write_text(other)
                            expected_records += 1
                            if case == "multiple_versions":
                                other_base = base.replace(version, "9.0.9999.9")
                                (root / "WinSxS" / other_base).mkdir()
                                (manifests / (other_base + ".manifest")).write_text(target_xml.replace(version, "9.0.9999.9"))
                                expected_records += 1
                    if case == "unrelated_files":
                        (manifests / f"amd64_microsoft.vc90.{name}Extra_bad.manifest").write_text("not XML")
                        unrelated = root / "WinSxS/Policies/amd64_policy.9.0.microsoft.vc90.Unrelated_bad"
                        unrelated.mkdir(parents=True, exist_ok=True)
                        (unrelated / "bad.policy").write_text("not XML")
                        # Relevant directories contain catalogs too; discovery must only read policy files.
                        path.with_name("bad.cat").write_text("not XML")
                receipts = root / "receipts"
                receipts.mkdir()
                env = dict(os.environ, WINDIR=tmp, TEST_HELPER=str(HERE / "provision_capture_vc90.ps1"),
                           TEST_RECEIPTS=str(receipts))
                run = subprocess.run([PWSH, "-NoProfile", "-Command",
                                      ". $env:TEST_HELPER; Get-Vc90PolicyEvidence -Destination $env:TEST_RECEIPTS"],
                                     env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(run.returncode, 0 if case in positive else 1, run.stdout + run.stderr)
                evidence = json.loads((receipts / "policy.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(evidence["status"], "POLICY_AND_TARGET_PRESENT" if case in positive else "UNPROVEN")
                self.assertEqual(len(evidence["assemblies"]), expected_records)
                self.assertEqual(len(list(receipts.glob("installed-*.xml"))), expected_records)
                self.assertEqual(len({r["copy"] for r in evidence["assemblies"]}), expected_records)
                for record in evidence["assemblies"]:
                    self.assertEqual(Path(record["source"]).read_bytes(), Path(record["copy"]).read_bytes())
                self.assertIn("NOT_EVALUATED", evidence["activation"])
                self.assertNotIn("selected_policy", evidence)
                if case in ("all_stores", "multiple_versions"):
                    self.assertEqual([len(c["matches"]) for c in evidence["compatibility"]],
                                     [3, 3] if case == "all_stores" else [2, 2])
                if case == "all_stores":
                    for family in ("CRT", "OpenMP"):
                        copies = [r for r in evidence["assemblies"] if r["name"].lower() == f"policy.9.0.microsoft.vc90.{family}".lower()]
                        self.assertEqual(len({r["sha256"] for r in copies}), 1)


if __name__ == "__main__":
    unittest.main()
