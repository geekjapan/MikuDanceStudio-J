"""Execute PowerShell helpers with stand-in service/DirectSound boundaries; no Windows changes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
PWSH = shutil.which("pwsh")
HARNESS = r'''
$ErrorActionPreference = 'Stop'
. $env:TEST_HELPER
function Assert-CaptureAudioHost {}
$script:states = @{}
foreach ($name in @('AudioEndpointBuilder', 'Audiosrv')) {
    $script:states[$name] = [pscustomobject]@{ Name = $name; State = 'Stopped'; StartMode = 'Disabled' }
    if ($env:TEST_CASE -in @('ready', 'still_fail', 'probe_error')) { $script:states[$name].State = 'Running'; $script:states[$name].StartMode = 'Auto' }
}
$script:methods = @()
function Get-CimInstance {
    param($ClassName, $Filter, $OperationTimeoutSec, $ErrorAction)
    if ($OperationTimeoutSec -ne 15) { throw 'Missing bounded CIM timeout' }
    if ($ClassName -eq 'Win32_Service') {
        if ($env:TEST_CASE -eq 'inventory_error') { throw 'Stand-in service query failure' }
        foreach ($service in $script:states.Values) {
            if ($Filter -like '* OR *' -or $Filter -eq "Name='$($service.Name)'") {
                if ($env:TEST_CASE -ne 'missing' -or $service.Name -ne 'Audiosrv') { $service | Select-Object * }
            }
        }
    } elseif ($env:TEST_CASE -eq 'unsupported') { throw 'Stand-in unsupported inventory class' }
}
function Invoke-CimMethod {
    param($InputObject, $MethodName, $Arguments, $OperationTimeoutSec, $ErrorAction)
    if ($OperationTimeoutSec -ne 15) { throw 'Missing mutation timeout' }
    $script:methods += "$($InputObject.Name):$MethodName"
    if ($env:TEST_CASE -eq 'service_error') { return @{ ReturnValue = 2 } }
    if ($MethodName -eq 'ChangeStartMode' -and $Arguments.StartMode -eq 'Manual') { $script:states[$InputObject.Name].StartMode = 'Manual' }
    elseif ($MethodName -eq 'StartService') { $script:states[$InputObject.Name].State = 'Running' }
    else { throw 'Unauthorized service operation' }
    return @{ ReturnValue = 0 }
}
function Get-Service {
    param($Name, $ErrorAction)
    $controller = [pscustomobject]@{ Name = $Name }
    $controller | Add-Member ScriptMethod WaitForStatus {
        param($State, $Timeout)
        if ($State -ne 'Running' -or $Timeout.TotalSeconds -ne 15) { throw 'Unbounded service wait' }
        if ($env:TEST_CASE -eq 'wait_timeout') { throw 'Stand-in service wait timeout' }
    }
    $controller | Add-Member ScriptMethod Dispose {}
    return $controller
}
$script:probeCount = 0
function Invoke-CaptureDirectSound {
    param($Destination, $Phase)
    $script:probeCount++
    $status = if ($env:TEST_CASE -eq 'probe_error') { 'ERROR' }
        elseif ($env:TEST_CASE -eq 'ready' -or ($Phase -eq 'after' -and $env:TEST_CASE -ne 'still_fail')) { 'PASS' }
        else { 'FAIL' }
    return @{ status = $status; result = @{ hresult_signed = $(if ($status -eq 'PASS') { 0 } else { -2005401480 });
        hresult_hex = $(if ($status -eq 'PASS') { '0x00000000' } else { '0x88780078' }) }; phase = $Phase }
}
try { Initialize-CaptureAudio -Destination $env:TEST_RECEIPTS } catch { Write-Output $_; exit 1 }
finally { ConvertTo-Json -InputObject @($script:methods) | Set-Content (Join-Path $env:TEST_ROOT 'methods.json') }
'''

PROBE_HARNESS = r'''
$ErrorActionPreference = 'Stop'
. $env:TEST_HELPER
function Start-Process {
    param($FilePath, $ArgumentList, [switch]$PassThru, $WindowStyle, $RedirectStandardOutput, $RedirectStandardError)
    $sourcePath = $ArgumentList[-1].Trim('"')
    $source = Get-Content $sourcePath -Raw
    if ($source -notmatch 'DirectSoundCreate\(\[IntPtr\]::Zero, \[ref\]\$pointer, \[IntPtr\]::Zero\)' -or
        $source -notmatch 'Marshal\]::Release\(\$pointer\)') { throw 'Probe call or COM release missing' }
    # Replace only the native boundary. Execute the actual HRESULT formatter without loading dsound.dll.
    $replacement = @'
Add-Type -TypeDefinition @"
using System;
public static class CaptureDirectSound {
    public static int DirectSoundCreate(IntPtr device, out IntPtr sound, IntPtr outer) {
        sound = IntPtr.Zero;
        return CASE_HRESULT;
    }
}
"@
'@
    $hr = if ($env:TEST_CASE -eq 'success') { '0' } else { 'unchecked((int)0x88780078)' }
    $replacement = $replacement.Replace('CASE_HRESULT', $hr)
    $source = [regex]::Replace($source, '(?s)Add-Type -TypeDefinition @".*?"@', [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $replacement })
    $source | Set-Content $sourcePath
    & (Join-Path $PSHOME 'pwsh') -NoProfile -File $sourcePath > $RedirectStandardOutput 2> $RedirectStandardError
    $process = [pscustomobject]@{ Id = 123; ExitCode = 0; HasExited = ($env:TEST_CASE -ne 'timeout') }
    if ($env:TEST_CASE -eq 'nonzero') { $process.ExitCode = 7 }
    $process | Add-Member ScriptMethod WaitForExit { param($Milliseconds) return $this.HasExited }
    $process | Add-Member ScriptMethod Kill { $this.HasExited = $true; $this.ExitCode = -1; Set-Content (Join-Path $env:TEST_ROOT 'killed') 'owned' }
    $process | Add-Member ScriptMethod Dispose { Set-Content (Join-Path $env:TEST_ROOT 'disposed') 'owned' }
    return $process
}
Invoke-CaptureDirectSound -Destination $env:TEST_ROOT -Phase 'test' | ConvertTo-Json -Depth 8 | Set-Content $env:TEST_RECEIPTS
'''


class CaptureAudio(unittest.TestCase):
    def run_harness(self, code, case, root):
        self.assertIsNotNone(PWSH, 'PowerShell is required; no hardware or service test is implied')
        script = root / 'harness.ps1'
        script.write_text(code)
        return subprocess.run([PWSH, '-NoProfile', '-File', str(script)], capture_output=True, text=True,
                              env=dict(os.environ, TEST_HELPER=str(HERE / 'provision_capture_audio.ps1'),
                                       TEST_ROOT=str(root), TEST_RECEIPTS=str(root / 'receipts'), TEST_CASE=case), timeout=30)

    def test_service_and_probe_decisions(self):
        for case in ('ready', 'repair', 'still_fail', 'service_error', 'wait_timeout', 'missing',
                     'probe_error', 'inventory_error', 'unsupported'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                run = self.run_harness(HARNESS, case, root)
                receipt = json.loads((root / 'receipts/receipt.json').read_text(encoding='utf-8-sig'))
                success = case in ('ready', 'repair', 'unsupported')
                self.assertEqual(run.returncode, 0 if success else 1, run.stdout + run.stderr)
                self.assertEqual(receipt['status'].startswith('PASS'), success, receipt)
                self.assertEqual([p['phase'] for p in receipt['probes']], ['before', 'after'])
                methods = json.loads((root / 'methods.json').read_text(encoding='utf-8-sig'))
                if case in ('ready', 'still_fail', 'probe_error', 'inventory_error'):
                    self.assertEqual(methods, [])
                if case in ('repair', 'unsupported'):
                    self.assertEqual(methods, ['AudioEndpointBuilder:ChangeStartMode', 'AudioEndpointBuilder:StartService',
                                               'Audiosrv:ChangeStartMode', 'Audiosrv:StartService'])
                    self.assertTrue(all(x['status'] == 'PASS' for x in receipt['operations']))
                if case == 'unsupported':
                    self.assertEqual(receipt['before'][1]['status'], 'ERROR_OR_UNSUPPORTED')
                self.assertEqual(receipt['source_sha256'].lower(), hashlib.sha256((root / 'receipts/source.ps1').read_bytes()).hexdigest())
                self.assertEqual((root / 'receipts/source.ps1').read_bytes(), (HERE / 'provision_capture_audio.ps1').read_bytes())
                self.assertIn('unchanged application capture remains authoritative', receipt['activation'])

    def test_probe_hresult_and_owned_process_cleanup(self):
        for case in ('success', 'failure', 'nonzero', 'timeout'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                run = self.run_harness(PROBE_HARNESS, case, root)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                result = json.loads((root / 'receipts').read_text(encoding='utf-8-sig'))
                self.assertEqual(result['status'], {'success': 'PASS', 'failure': 'FAIL'}.get(case, 'ERROR'), result)
                self.assertEqual(result['timed_out'], case == 'timeout')
                self.assertEqual((root / 'killed').exists(), case == 'timeout')
                self.assertTrue((root / 'disposed').exists())
                if case in ('success', 'failure'):
                    self.assertEqual(result['result']['hresult_signed'], 0 if case == 'success' else -2005401480)
                    self.assertEqual(result['result']['hresult_hex'], '0x00000000' if case == 'success' else '0x88780078')
                self.assertIsNone(result['cleanup_error'])

    def test_host_guards_precede_writes(self):
        for name, value in (('GITHUB_ACTIONS', 'false'), ('RUNNER_ENVIRONMENT', 'self-hosted'),
                            ('RUNNER_OS', 'Linux'), ('RUNNER_ARCH', 'ARM64'), ('MDS_D3D9_CAPTURE', '0')):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                destination = Path(tmp) / 'receipts'
                env = dict(os.environ, GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted',
                           RUNNER_OS='Windows', RUNNER_ARCH='X64', MDS_D3D9_CAPTURE='1')
                env[name] = value
                run = subprocess.run([PWSH, '-NoProfile', '-File', str(HERE / 'provision_capture_audio.ps1'),
                                      '-Receipts', str(destination)], env=env, capture_output=True, text=True, timeout=10)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn('restricted to the ephemeral', run.stderr)
                self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
