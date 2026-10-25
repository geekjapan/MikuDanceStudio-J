# Run a .ps1 in the console session through a one-shot interactive scheduled
# task, wait for it, and print the exit code. OpenSSH runs in session 0, which
# cannot create a D3D9 device or drive the GUI.
# -Exclusive holds the machine-wide mutex Global\mds-console-input for the whole
# run. Use it for any lane that sends keyboard or mouse input, so two agents'
# GUI lanes never interleave.
# Usage: runtask.ps1 -Script <x.ps1> -Log <x.log> [-TimeoutSec 600] [-ScriptArgs '...'] [-Exclusive]
param([Parameter(Mandatory)][string]$Script, [Parameter(Mandatory)][string]$Log,
      [int]$TimeoutSec = 600, [string]$ScriptArgs = '', [switch]$Exclusive)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'
$name = 'mds-lane-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
$mutex = $null
if ($Exclusive) {
    $mutex = New-Object Threading.Mutex($false, 'Global\mds-console-input')
    try { [void]$mutex.WaitOne() } catch [Threading.AbandonedMutexException] { }
    "holding Global\mds-console-input"
}
try {
    $wrap = Join-Path $env:TEMP "$name.cmd"
    New-Item -ItemType Directory -Force (Split-Path $Log) | Out-Null
    Remove-Item $Log, "$Log.done" -ErrorAction SilentlyContinue
    $line = "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"$Script`" $ScriptArgs > `"$Log`" 2>&1`r`necho %ERRORLEVEL% > `"$Log.done`"`r`n"
    [IO.File]::WriteAllText($wrap, $line, [Text.Encoding]::ASCII)
    schtasks /Create /TN $name /TR "`"$wrap`"" /SC ONCE /ST 00:00 /IT /RU $env:USERNAME /F 2>$null | Out-Null
    schtasks /Run /TN $name | Out-Null
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path "$Log.done") -and $sw.Elapsed.TotalSeconds -lt $TimeoutSec) { Start-Sleep -Seconds 2 }
    if (-not (Test-Path "$Log.done")) { "TIMEOUT after $TimeoutSec s"; schtasks /End /TN $name | Out-Null }
    schtasks /Delete /TN $name /F | Out-Null
    Remove-Item $wrap -ErrorAction SilentlyContinue
    "task exit code: " + $(if (Test-Path "$Log.done") { (Get-Content "$Log.done").Trim() } else { 'none' })
} finally {
    if ($mutex) { $mutex.ReleaseMutex(); $mutex.Dispose() }
}
