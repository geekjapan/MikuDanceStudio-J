param([string]$Receipts)
$ErrorActionPreference = 'Stop'

function Assert-CaptureAudioHost {
    if (-not $IsWindows -or $env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or
        $env:RUNNER_OS -cne 'Windows' -or $env:RUNNER_ARCH -cne 'X64' -or $env:MDS_D3D9_CAPTURE -cne '1' -or
        [Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -ne 'X64') {
        throw 'Audio preparation is restricted to the ephemeral GitHub-hosted Windows x64 capture job'
    }
}

function Get-CaptureAudioInventory {
    $result = @()
    foreach ($query in @(
        @{ class = 'Win32_Service'; filter = "Name='AudioEndpointBuilder' OR Name='Audiosrv'"; properties = @('Name', 'State', 'StartMode') },
        @{ class = 'Win32_SoundDevice'; filter = $null; properties = @('Name', 'DeviceID', 'Status', 'ConfigManagerErrorCode') },
        @{ class = 'Win32_PnPEntity'; filter = "PNPClass='AudioEndpoint'"; properties = @('Name', 'DeviceID', 'Status', 'ConfigManagerErrorCode') }
    )) {
        $entry = [ordered]@{ class = $query.class; filter = $query.filter; properties = $query.properties; timeout_seconds = 15; status = 'ERROR_OR_UNSUPPORTED'; records = @(); error = $null }
        try {
            $arguments = @{ ClassName = $query.class; OperationTimeoutSec = 15; ErrorAction = 'Stop' }
            if ($query.filter) { $arguments.Filter = $query.filter }
            $entry.records = @(Get-CimInstance @arguments | Select-Object -Property $query.properties)
            $entry.status = if ($entry.records.Count) { 'COLLECTED' } else { 'EMPTY' }
        } catch { $entry.error = [string]$_ }
        $result += $entry
    }
    return $result
}

function Invoke-CaptureDirectSound {
    param([string]$Destination, [string]$Phase)
    $source = @'
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class CaptureDirectSound {
    [DllImport("dsound.dll", ExactSpelling=true, CallingConvention=CallingConvention.StdCall)]
    public static extern int DirectSoundCreate(IntPtr device, out IntPtr sound, IntPtr outer);
}
"@
$pointer = [IntPtr]::Zero
try {
    $hr = [CaptureDirectSound]::DirectSoundCreate([IntPtr]::Zero, [ref]$pointer, [IntPtr]::Zero)
    [ordered]@{ hresult_signed = $hr; hresult_hex = ('0x{0:X8}' -f $hr); status = $(if ($hr -lt 0) { 'FAIL' } else { 'PASS' })
        interface_returned = ($pointer -ne [IntPtr]::Zero) } | ConvertTo-Json -Compress
} finally {
    if ($pointer -ne [IntPtr]::Zero) { [void][Runtime.InteropServices.Marshal]::Release($pointer) }
}
'@
    $sourcePath = Join-Path $Destination "$Phase-probe.ps1"
    $source | Set-Content $sourcePath -Encoding utf8
    $command = @((Join-Path $PSHOME 'pwsh.exe'), '-NoProfile', '-NonInteractive', '-File', $sourcePath)
    $receipt = [ordered]@{ command = $command; source_sha256 = (Get-FileHash $sourcePath -Algorithm SHA256).Hash
        call = 'dsound.dll!DirectSoundCreate(NULL, out interface, NULL)'; timeout_seconds = 20
        started_utc = [DateTime]::UtcNow.ToString('o'); process_started = $false; pid = $null; returncode = $null
        timed_out = $false; cleanup_error = $null; status = 'ERROR'; result = $null; error = $null }
    $process = $null
    try {
        $process = Start-Process -FilePath $command[0] -ArgumentList @('-NoProfile', '-NonInteractive', '-File', ('"{0}"' -f $sourcePath)) `
            -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Destination "$Phase-stdout.txt") `
            -RedirectStandardError (Join-Path $Destination "$Phase-stderr.txt")
        $receipt.process_started = $true
        $receipt.pid = $process.Id
        if (-not $process.WaitForExit(20000)) { $receipt.timed_out = $true; throw 'DirectSound probe exceeded 20 seconds' }
        $receipt.returncode = $process.ExitCode
        if ($process.ExitCode -ne 0) { throw "DirectSound probe process exit $($process.ExitCode)" }
        $receipt.result = Get-Content (Join-Path $Destination "$Phase-stdout.txt") -Raw | ConvertFrom-Json
        if ($receipt.result.status -notin @('PASS', 'FAIL')) { throw 'Invalid DirectSound probe result' }
        $receipt.status = $receipt.result.status
    } catch { $receipt.error = [string]$_ } finally {
        if ($process) {
            try {
                if (-not $process.HasExited) {
                    $process.Kill()
                    if (-not $process.WaitForExit(10000)) { throw 'Owned DirectSound probe did not exit after termination' }
                }
                $receipt.returncode = $process.ExitCode
            } catch { $receipt.cleanup_error = [string]$_; $receipt.status = 'ERROR' } finally { $process.Dispose() }
        }
        $receipt.finished_utc = [DateTime]::UtcNow.ToString('o')
    }
    return $receipt
}

function Initialize-CaptureAudio {
    param([string]$Destination)
    Assert-CaptureAudioHost
    if (-not $Destination) { throw 'Receipts directory is required' }
    New-Item -ItemType Directory $Destination -ErrorAction Stop | Out-Null
    Copy-Item $PSCommandPath (Join-Path $Destination 'source.ps1') -ErrorAction Stop
    $receipt = [ordered]@{ schema = 1; status = 'FAIL'; started_utc = [DateTime]::UtcNow.ToString('o')
        source = $PSCommandPath; source_copy = 'source.ps1'; github_sha = $env:GITHUB_SHA; github_run_id = $env:GITHUB_RUN_ID
        source_sha256 = (Get-FileHash $PSCommandPath -Algorithm SHA256).Hash
        command = @($PSCommandPath, '-Receipts', $Destination); services = @('AudioEndpointBuilder', 'Audiosrv')
        before = @(); after = @(); probes = @(); operations = @(); errors = @()
        activation = 'NOT_EVALUATED; unchanged application capture remains authoritative' }
    try {
        $receipt.before = @(Get-CaptureAudioInventory)
        $receipt.probes += Invoke-CaptureDirectSound -Destination $Destination -Phase 'before'
        if ($receipt.probes[0].status -eq 'FAIL') {
            foreach ($name in $receipt.services) {
                $operation = [ordered]@{ name = $name; commands = @(); initial = $null; final = $null; change_startmode_returnvalue = $null; startservice_returnvalue = $null; status = 'FAIL'; error = $null }
                try {
                    $service = Get-CimInstance -ClassName Win32_Service -Filter "Name='$name'" -OperationTimeoutSec 15 -ErrorAction Stop
                    if (-not $service) { throw "Existing service $name is missing; no installation permitted" }
                    $operation.initial = $service | Select-Object Name, State, StartMode
                    if ($service.StartMode -eq 'Disabled') {
                        $operation.commands += "Invoke-CimMethod Win32_Service/$name ChangeStartMode StartMode=Manual OperationTimeoutSec=15"
                        $change = Invoke-CimMethod -InputObject $service -MethodName ChangeStartMode -Arguments @{ StartMode = 'Manual' } -OperationTimeoutSec 15 -ErrorAction Stop
                        $operation.change_startmode_returnvalue = $change.ReturnValue
                        if ($change.ReturnValue -ne 0) { throw "ChangeStartMode returned $($change.ReturnValue)" }
                    }
                    if ($service.State -eq 'Stopped') {
                        $operation.commands += "Invoke-CimMethod Win32_Service/$name StartService OperationTimeoutSec=15"
                        $start = Invoke-CimMethod -InputObject $service -MethodName StartService -OperationTimeoutSec 15 -ErrorAction Stop
                        $operation.startservice_returnvalue = $start.ReturnValue
                        if ($start.ReturnValue -notin @(0, 10)) { throw "StartService returned $($start.ReturnValue)" }
                    }
                    $operation.commands += "Get-Service $name WaitForStatus Running timeout=15s"
                    $controller = Get-Service -Name $name -ErrorAction Stop
                    try { $controller.WaitForStatus('Running', [TimeSpan]::FromSeconds(15)) } finally { $controller.Dispose() }
                    $operation.final = Get-CimInstance -ClassName Win32_Service -Filter "Name='$name'" -OperationTimeoutSec 15 -ErrorAction Stop |
                        Select-Object Name, State, StartMode
                    if ($operation.final.State -ne 'Running') { throw "$name is not Running after bounded wait" }
                    $operation.status = 'PASS'
                } catch { $operation.error = [string]$_; $receipt.errors += [string]$_ }
                $receipt.operations += $operation
            }
        }
        $receipt.probes += Invoke-CaptureDirectSound -Destination $Destination -Phase 'after'
        $receipt.after = @(Get-CaptureAudioInventory)
        foreach ($snapshot in @($receipt.before, $receipt.after)) {
            $services = @($snapshot | Where-Object { $_.class -eq 'Win32_Service' })
            if ($services.Count -ne 1 -or $services[0].status -ne 'COLLECTED' -or $services[0].records.Count -ne 2) {
                $receipt.errors += 'Could not collect both existing audio services'
            }
        }
        if ($receipt.probes[-1].status -ne 'PASS' -or $receipt.probes[0].status -eq 'ERROR' -or $receipt.errors.Count) {
            throw 'Audio environment remains unproven; inspect probe HRESULT, service operations and inventories'
        }
        $receipt.status = 'PASS; DirectSound probe only'
    } catch { $receipt.errors += [string]$_; throw } finally {
        $receipt.finished_utc = [DateTime]::UtcNow.ToString('o')
        $receipt | ConvertTo-Json -Depth 12 | Set-Content (Join-Path $Destination 'receipt.json') -Encoding utf8
    }
}

if ($MyInvocation.InvocationName -ne '.') { Initialize-CaptureAudio -Destination $Receipts }
