#!/usr/bin/env python3
"""Exercise the real PowerShell trust boundary with a stand-in child, no installation."""

import hashlib
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


def no_force_omits(location, attribute, windows):
    if windows:
        return "Hidden" in {part.strip() for part in (attribute or "").split(",")}
    return location.startswith("dot_file")


def discovered_entry(path, entries):
    matches = [entry for raw_path, entry in entries.items() if path.samefile(raw_path)]
    if len(matches) != 1:
        raise AssertionError(f"Expected one physical match for {str(path)!r}, got {len(matches)} in {entries!r}")
    return matches[0]


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



    def test_original_pinned_package_xml(self):
        self.assertIsNotNone(PWSH, "PowerShell is required")
        fixtures = HERE / "fixtures/vc90-9.0.30729.6161"
        digests = {
            "manifest.30729.6161.Microsoft_VC90_CRT_x64.QFE": "EBDC380C42F68788F5B85AA4E5879C6DD395A58DC33CA7608148C0B1FA563979",
            "manifest.30729.6161.Microsoft_VC90_OpenMP_x64.QFE": "776DA1EA32B3E6C6C994E46E9F3BAA5060A487BC118523CF5093D45E0667BC2C",
            "policy.30729.6161.policy_9_0_Microsoft_VC90_CRT_x64.QFE": "D564F6725C6A6DE3A450F8D93920F17D9DB7B8793469040D227D718ED26FD347",
            "policy.30729.6161.policy_9_0_Microsoft_VC90_OpenMP_x64.QFE": "1FB07274FF049A470A4923658F1A4F230167A5DBB5748E144B06DBB79F41EB4E",
        }
        for name, digest in digests.items():
            self.assertEqual(hashlib.sha256((fixtures / name).read_bytes()).hexdigest().upper(), digest)
        positive = ("package", "package_copies", "policy_only", "targets_only")
        negative = ("duplicate", "overlap_same_target", "overlap_conflict", "endpoint_overlap",
                    "namespace_reset", "namespace_foreign", "reference_reset", "redirect_reset",
                    "target_file_reset", "target_noInheritable_reset", "target_hash_reset",
                    "policy_hash_extension", "target_hash_wrong_parent", "target_dsig_outside_hash",
                    "version_overflow", "second_short_range", "missing_second_target",
                    "duplicate_reference", "wrong_hierarchy")
        for case in positive + negative:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifests = root / "WinSxS/Manifests"
                manifests.mkdir(parents=True)
                for family in ("CRT", "OpenMP"):
                    target_xml = (fixtures / f"manifest.30729.6161.Microsoft_VC90_{family}_x64.QFE").read_bytes()
                    policy_xml = (fixtures / f"policy.30729.6161.policy_9_0_Microsoft_VC90_{family}_x64.QFE").read_bytes()
                    first = b'oldVersion="9.0.20718.0-9.0.21022.8"'
                    second = b'oldVersion="9.0.30201.0-9.0.30729.6161"'
                    if case in ("duplicate", "overlap_same_target", "overlap_conflict", "endpoint_overlap"):
                        replacement = {
                            "duplicate": first,
                            "overlap_same_target": b'oldVersion="9.0.21022.0-9.0.30729.6161"',
                            "overlap_conflict": b'oldVersion="9.0.21022.0-9.0.30729.6161"',
                            "endpoint_overlap": b'oldVersion="9.0.21022.8-9.0.30729.6161"',
                        }[case]
                        policy_xml = policy_xml.replace(second, replacement)
                        if case == "overlap_conflict":
                            policy_xml = policy_xml.replace(replacement + b' newVersion="9.0.30729.6161"',
                                                            replacement + b' newVersion="9.0.9999.9"')
                    for control, element, namespace in (
                        ("namespace_reset", b"dependency", b""),
                        ("namespace_foreign", b"dependency", b"urn:invalid"),
                        ("reference_reset", b"dependentAssembly", b""),
                        ("redirect_reset", b"bindingRedirect", b""),
                    ):
                        if case == control:
                            policy_xml = policy_xml.replace(b"<" + element, b"<" + element + b' xmlns="' + namespace + b'"')
                    for control, element in (("target_file_reset", b"file"),
                                             ("target_noInheritable_reset", b"noInheritable")):
                        if case == control:
                            target_xml = target_xml.replace(b"<" + element, b"<" + element + b' xmlns=""')
                    if case == "target_hash_reset":
                        target_xml = target_xml.replace(b'xmlns:asmv2="urn:schemas-microsoft-com:asm.v2"', b'xmlns:asmv2="urn:invalid"')
                    if case == "policy_hash_extension":
                        policy_xml = policy_xml.replace(b"</assembly>", b'<file name="bad"><h:hash xmlns:h="urn:schemas-microsoft-com:asm.v2"/></file></assembly>')
                    if case == "target_hash_wrong_parent":
                        target_xml = target_xml.replace(b"<file ", b"<wrapper ").replace(b"</file>", b"</wrapper>")
                    if case == "target_dsig_outside_hash":
                        target_xml = target_xml.replace(b"</assembly>", b'<d:DigestValue xmlns:d="http://www.w3.org/2000/09/xmldsig#">bad</d:DigestValue></assembly>')
                    if case == "version_overflow":
                        policy_xml = policy_xml.replace(second, b'oldVersion="9.0.30201.0-9.0.65536.1"')
                    if case == "second_short_range":
                        policy_xml = policy_xml.replace(second, b'oldVersion="9.0-9.0.30729.6161"')
                    if case == "missing_second_target":
                        policy_xml = policy_xml.replace(second + b' newVersion="9.0.30729.6161"', second)
                    if case == "duplicate_reference":
                        reference = next(line for line in policy_xml.splitlines() if b'name="Microsoft.VC90.' in line)
                        policy_xml = policy_xml.replace(reference, reference + reference)
                    if case == "wrong_hierarchy":
                        policy_xml = policy_xml.replace(b"dependency>", b"wrapper>")
                    if case == "policy_only":
                        target_xml = (f'<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">'
                                      f'<assemblyIdentity type="win32" name="Microsoft.VC90.{family}" '
                                      'version="9.0.30729.6161" processorArchitecture="amd64" '
                                      'publicKeyToken="1fc8b3b9a1e18e3b"/></assembly>').encode()
                    if case == "targets_only":
                        policy_xml = b"\n".join(line for line in policy_xml.splitlines() if second not in line)
                    base = f"amd64_microsoft.vc90.{family}_1fc8b3b9a1e18e3b_9.0.30729.6161_none_test"
                    (root / "WinSxS" / base).mkdir()
                    (manifests / (base + ".manifest")).write_bytes(target_xml)
                    policy = root / f"WinSxS/Policies/amd64_policy.9.0.microsoft.vc90.{family}_test/9.0.30729.6161.policy"
                    policy.parent.mkdir(parents=True)
                    policy.write_bytes(policy_xml)
                    if case == "package_copies":
                        (manifests / f"amd64_policy.9.0.microsoft.vc90.{family}_test.manifest").write_bytes(policy_xml)
                receipts = root / "receipts"
                receipts.mkdir()
                run = subprocess.run([PWSH, "-NoProfile", "-Command",
                                      ". $env:TEST_HELPER; Get-Vc90PolicyEvidence -Destination $env:TEST_RECEIPTS"],
                                     env=dict(os.environ, WINDIR=tmp, TEST_HELPER=str(HERE / "provision_capture_vc90.ps1"),
                                              TEST_RECEIPTS=str(receipts)),
                                     capture_output=True, text=True, timeout=15)
                evidence = json.loads((receipts / "policy.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(run.returncode, 0 if case in positive else 1, run.stdout + run.stderr)
                self.assertEqual(evidence["status"], "POLICY_AND_TARGET_PRESENT" if case in positive else "UNPROVEN")
                self.assertIn("NOT_EVALUATED", evidence["activation"])
                self.assertEqual(len(evidence["assemblies"]), 6 if case == "package_copies" else 4)
                for record in evidence["assemblies"]:
                    self.assertEqual(Path(record["source"]).read_bytes(), Path(record["copy"]).read_bytes())
                    self.assertEqual(hashlib.sha256(Path(record["copy"]).read_bytes()).hexdigest().upper(), record["sha256"])
                if case in positive:
                    self.assertFalse(evidence["errors"])
                    self.assertEqual([len(c["matches"]) for c in evidence["compatibility"]],
                                     [2, 2] if case == "package_copies" else [1, 1])
                    policies = [r for r in evidence["assemblies"] if r["type"] == "win32-policy"]
                    self.assertTrue(all(len(r["redirects"]) == (1 if case == "targets_only" else 2) for r in policies))
                else:
                    self.assertTrue(evidence["errors"])


    def check_discovery(self, location, attribute=None, invalid=False, missing_target=False, enumeration_error=False):
        self.assertIsNotNone(PWSH, "PowerShell is required")
        fixtures = HERE / "fixtures/vc90-9.0.30729.6161"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifests = root / "WinSxS/Manifests"
            manifests.mkdir(parents=True)
            marked = []
            for family in ("CRT", "OpenMP"):
                base = f"amd64_microsoft.vc90.{family}_1fc8b3b9a1e18e3b_9.0.30729.6161_none_test"
                if not missing_target or family != "OpenMP":
                    (root / "WinSxS" / base).mkdir()
                manifest = manifests / (base + ".manifest")
                manifest.write_bytes((fixtures / f"manifest.30729.6161.Microsoft_VC90_{family}_x64.QFE").read_bytes())
                if location == "target_manifest":
                    marked.append(manifest)
                if location == "policy_manifest":
                    policy = manifests / f"amd64_policy.9.0.microsoft.vc90.{family}_test.manifest"
                else:
                    store = root / "WinSxS" if location.endswith("root") else root / "WinSxS/Policies"
                    policy = store / f"amd64_policy.9.0.microsoft.vc90.{family}_test/9.0.30729.6161.policy"
                    policy.parent.mkdir(parents=True, exist_ok=True)
                    if location.startswith("dot_file"):
                        policy = policy.with_name(".hidden.policy")
                policy.write_bytes(b"not XML" if invalid else
                                   (fixtures / f"policy.30729.6161.policy_9_0_Microsoft_VC90_{family}_x64.QFE").read_bytes())
                if location.startswith("policy_dir"):
                    marked.append(policy.parent)
                elif location != "target_manifest":
                    marked.append(policy)
            receipts = root / "receipts"
            receipts.mkdir()
            harness = r'''
. $env:TEST_HELPER
if ($env:TEST_ATTRIBUTE) {
    $attribute = [Enum]::Parse([IO.FileAttributes], $env:TEST_ATTRIBUTE)
    foreach ($path in (ConvertFrom-Json $env:TEST_MARKED)) {
        $item = Get-Item -LiteralPath $path -Force
        $item.Attributes = $item.Attributes -bor $attribute
        if (((Get-Item -LiteralPath $path -Force).Attributes -band $attribute) -ne $attribute) {
            throw "Attribute was not applied to $path"
        }
    }
}
if ($env:TEST_ENUMERATION_ERROR -eq 'yes') {
    function Get-ChildItem {
        param($Path, $Filter, [switch]$File, [switch]$Directory, [switch]$Force)
        if ($Directory -and $Path -eq (Join-Path $env:WINDIR 'WinSxS') -and $Filter -like '*vc90.crt_*') {
            throw 'Injected relevant enumeration failure'
        }
        Microsoft.PowerShell.Management\Get-ChildItem @PSBoundParameters
    }
}
Get-Vc90PolicyEvidence -Destination $env:TEST_RECEIPTS
'''
            script = root / "discovery.ps1"
            script.write_text(harness)
            env = dict(os.environ, WINDIR=tmp, TEST_HELPER=str(HERE / "provision_capture_vc90.ps1"),
                       TEST_RECEIPTS=str(receipts), TEST_MARKED=json.dumps([str(p) for p in marked]),
                       TEST_ATTRIBUTE=attribute or "", TEST_ENUMERATION_ERROR="yes" if enumeration_error else "no")
            if (attribute or location.startswith("dot_file")) and not (invalid or missing_target):
                baseline = root / "without-force.ps1"
                baseline.write_text((HERE / "provision_capture_vc90.ps1").read_text()
                                    .replace("-File -Force)", "-File)").replace("-Directory -Force)", "-Directory)"))
                baseline_receipts = root / "without-force-receipts"
                baseline_receipts.mkdir()
                old = subprocess.run([PWSH, "-NoProfile", "-File", str(script)],
                                     env=dict(env, TEST_HELPER=str(baseline), TEST_RECEIPTS=str(baseline_receipts)),
                                     capture_output=True, text=True, timeout=15)
                omitted = no_force_omits(location, attribute, os.name == "nt")
                self.assertEqual(old.returncode, 1 if omitted else 0,
                                 "unexpected discovery without -Force: " + old.stdout + old.stderr)
                old_evidence = json.loads((baseline_receipts / "policy.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(old_evidence["status"], "UNPROVEN" if omitted else "POLICY_AND_TARGET_PRESENT")
                if omitted:
                    self.assertLess(len(old_evidence["assemblies"]), 4)
                else:
                    self.assertEqual(len(old_evidence["assemblies"]), 4)
                    self.assertFalse(old_evidence["errors"])
            run = subprocess.run([PWSH, "-NoProfile", "-File", str(script)], env=env,
                                 capture_output=True, text=True, timeout=15)
            evidence = json.loads((receipts / "policy.json").read_text(encoding="utf-8-sig"))
            failed = invalid or missing_target or enumeration_error
            self.assertEqual(run.returncode, 1 if failed else 0, run.stdout + run.stderr)
            self.assertEqual(evidence["status"], "UNPROVEN" if failed else "POLICY_AND_TARGET_PRESENT")
            discovery = json.loads((receipts / "discovery.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(discovery, evidence["discovery"])
            self.assertTrue(all(q["force"] is True for q in discovery))
            entries = {e["path"]: e for q in discovery for e in q["entries"]}
            self.assertEqual(len(evidence["assemblies"]), 4)
            for record in evidence["assemblies"]:
                entry = entries[record["source"]]
                self.assertEqual(entry["name"], Path(record["source"]).name)
                self.assertEqual(entry["size"], Path(record["source"]).stat().st_size)
                self.assertFalse(entry["directory"])
                self.assertEqual(Path(record["source"]).read_bytes(), Path(record["copy"]).read_bytes())
                self.assertEqual(hashlib.sha256(Path(record["copy"]).read_bytes()).hexdigest().upper(), record["sha256"])
            for path in marked:
                entry = discovered_entry(path, entries)
                if attribute:
                    for part in attribute.split(","):
                        part = part.strip()
                        self.assertIn(part, entry["attributes"])
                        self.assertTrue(entry["attributes_value"] & (2 if part == "Hidden" else 4))
            if enumeration_error:
                self.assertTrue(any(q["error"] and 'Injected' in q["error"] for q in discovery))
                self.assertTrue(evidence["errors"])
                self.assertTrue(all(c["matches"] for c in evidence["compatibility"]))
            if invalid:
                self.assertTrue(evidence["errors"])
                self.assertEqual(sum(not r["valid"] for r in evidence["assemblies"]), 2)
            if missing_target:
                self.assertFalse(evidence["compatibility"][1]["matches"])

    @unittest.skipUnless(os.name == "nt", "SKIP: real Windows Hidden/System filesystem attributes require Windows")
    def test_windows_hidden_system_discovery(self):
        for attribute in ("Hidden", "System"):
            for location in ("target_manifest", "policy_manifest", "policy_dir_root", "policy_dir_Policies",
                             "policy_file_root", "policy_file_Policies"):
                with self.subTest(attribute=attribute, location=location):
                    self.check_discovery(location, attribute)
            with self.subTest(attribute=attribute, case="malformed relevant policy"):
                self.check_discovery("policy_file_Policies", attribute, invalid=True)
            with self.subTest(attribute=attribute, case="missing target"):
                self.check_discovery("policy_file_Policies", attribute, missing_target=True)

    @unittest.skipUnless(os.name == "nt", "SKIP: real Windows combined Hidden/System attributes require Windows")
    def test_windows_combined_hidden_system_discovery(self):
        self.check_discovery("policy_file_Policies", "Hidden, System")

    def test_discovery_observation_and_fail_closed(self):
        for location in ("dot_file_root", "dot_file_Policies"):
            with self.subTest(location=location):
                self.check_discovery(location)
        self.check_discovery("policy_file_Policies", enumeration_error=True)


class DiscoveryIdentity(unittest.TestCase):
    def test_physical_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "policy.xml"
            path.write_text("policy")
            alias = root / "alias.xml"
            os.link(path, alias)
            entry = {"path": str(alias), "attributes": "Archive"}
            self.assertIs(discovered_entry(path, {str(alias): entry}), entry)
            other = root / "other"
            other.mkdir()
            self.assertEqual(discovered_entry(root, {str(other / ".."): {"directory": True}}),
                             {"directory": True})
            nonmatching = other / path.name
            nonmatching.write_text("policy")
            with self.assertRaises(AssertionError):
                discovered_entry(path, {str(nonmatching): entry})
            with self.assertRaises(AssertionError):
                discovered_entry(path, {})
            with self.assertRaises(FileNotFoundError):
                discovered_entry(path, {str(root / "missing.xml"): entry})

    def test_no_force_platform_expectations(self):
        for windows, location, attribute, omitted in (
            (True, "dot_file_root", None, False),
            (True, "dot_file_Policies", None, False),
            (True, "policy_file_root", "System", False),
            (True, "policy_file_root", "Hidden", True),
            (True, "policy_dir_root", "Hidden,System", True),
            (False, "dot_file_root", None, True),
            (False, "dot_file_Policies", None, True),
        ):
            with self.subTest(windows=windows, location=location, attribute=attribute):
                self.assertEqual(no_force_omits(location, attribute, windows), omitted)

    @unittest.skipUnless(os.name == "nt", "SKIP: real Windows short/long path identity requires Windows")
    def test_windows_short_long_identity(self):
        import ctypes
        with tempfile.TemporaryDirectory(prefix="vc90 identity ") as tmp:
            root = Path(tmp)
            path = root / "long policy filename.xml"
            path.write_text("policy")
            get_short_path = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
            get_short_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
            get_short_path.restype = ctypes.c_uint
            for existing in (root, path):
                buffer = ctypes.create_unicode_buffer(32768)
                length = get_short_path(str(existing), buffer, len(buffer))
                self.assertGreater(length, 0, ctypes.get_last_error())
                self.assertLess(length, len(buffer))
                if buffer.value.casefold() == str(existing).casefold():
                    self.skipTest("SKIP: Windows volume did not provide a distinct short path")
                entry = {"path": str(existing)}
                self.assertIs(discovered_entry(Path(buffer.value), {str(existing): entry}), entry)
                self.assertIs(discovered_entry(existing, {buffer.value: entry}), entry)


if __name__ == "__main__":
    unittest.main()
