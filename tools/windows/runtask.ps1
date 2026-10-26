# Run a .ps1 in the console session through a one-shot interactive scheduled
# task, wait for it, and return an SSH-safe exit code. OpenSSH runs in session 0, which
# cannot create a D3D9 device or drive the GUI.
# -Exclusive holds the machine-wide mutex Global\mds-console-input for the whole
# run. Use it for any lane that sends keyboard or mouse input, so two agents'
# GUI lanes never interleave.
# Usage: runtask.ps1 -Script <x.ps1> -Log <x.log> [-TimeoutSec 600] [-ScriptArgs '...'] [-Exclusive]
param([Parameter(Mandatory)][string]$Script, [Parameter(Mandatory)][string]$Log,
      [int]$TimeoutSec = 600, [string]$ScriptArgs = '', [switch]$Exclusive)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$name = 'mds-lane-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
$mutex = $null
$locked = $false
$created = $false
$running = $false
$wrap = Join-Path $env:TEMP "$name.cmd"
$exitCode = 1
try {
    if ($Exclusive) {
        $mutex = New-Object Threading.Mutex($false, 'Global\mds-console-input')
        try { [void]$mutex.WaitOne() } catch [Threading.AbandonedMutexException] { }
        $locked = $true
        "holding Global\mds-console-input"
    }
    New-Item -ItemType Directory -Force (Split-Path $Log) | Out-Null
    foreach ($path in @($Log, "$Log.done")) {
        if (Test-Path $path) { Remove-Item $path }
    }
    $line = "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"$Script`" $ScriptArgs > `"$Log`" 2>&1`r`necho %ERRORLEVEL% > `"$Log.done`"`r`n"
    [IO.File]::WriteAllText($wrap, $line, [Text.Encoding]::ASCII)
    schtasks /Create /TN $name /TR "`"$wrap`"" /SC ONCE /ST 00:00 /IT /RU $env:USERNAME /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "schtasks /Create failed: $LASTEXITCODE" }
    $created = $true
    schtasks /Run /TN $name | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "schtasks /Run failed: $LASTEXITCODE" }
    $running = $true
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path "$Log.done") -and $sw.Elapsed.TotalSeconds -lt $TimeoutSec) { Start-Sleep -Seconds 2 }
    if (-not (Test-Path "$Log.done")) { throw "TIMEOUT after $TimeoutSec s; task exit code: none" }
    $running = $false
    $status = (Get-Content -Raw "$Log.done").Trim()
    $result = 0
    if ($status -notmatch '^-?[0-9]+$' -or -not [int]::TryParse($status, [ref]$result)) {
        throw "Invalid task exit code: '$status'"
    }
    "task exit code: $result"
    $exitCode = $result
} catch {
    Write-Error $_ -ErrorAction Continue
} finally {
    if ($created) {
        if ($running) {
            try {
                schtasks /End /TN $name | Out-Null
                if ($LASTEXITCODE -ne 0) { throw "schtasks /End failed: $LASTEXITCODE" }
                $running = $false
            } catch {
                Write-Warning $_
                $exitCode = 1
                Write-Warning "Stop not confirmed. Retained task '$name'; wrapper '$wrap'; log '$Log'; completion '$Log.done'."
                Write-Warning "Recover with schtasks /End /TN $name. Confirm the task has stopped before schtasks /Delete /TN $name /F and removal of '$wrap'. Do not start another exclusive lane until then; the helper mutex is released on exit."
            }
        }
        if (-not $running) {
            try {
                schtasks /Delete /TN $name /F | Out-Null
                if ($LASTEXITCODE -ne 0) { throw "schtasks /Delete failed: $LASTEXITCODE" }
            } catch {
                Write-Warning $_
                if ($exitCode -eq 0) { $exitCode = 1 }
            }
        }
    }
    try {
        if (-not $running -and (Test-Path $wrap)) { Remove-Item $wrap }
    } catch {
        Write-Warning $_
        if ($exitCode -eq 0) { $exitCode = 1 }
    }
    if ($mutex) {
        try {
            if ($locked) { $mutex.ReleaseMutex() }
        } catch {
            Write-Warning $_
            if ($exitCode -eq 0) { $exitCode = 1 }
        } finally { $mutex.Dispose() }
    }
}
# POSIX and SSH expose only eight bits. Keep the full task result in the diagnostic.
if ($exitCode -lt 0 -or $exitCode -gt 255) { $exitCode = 1 }
exit $exitCode
