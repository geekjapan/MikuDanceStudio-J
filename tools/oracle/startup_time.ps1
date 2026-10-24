# Startup time of the app, from process start until its main window exists.
# RM-3 perf probe. Windows PowerShell 5.1 or PowerShell 7.
#
#   .\startup_time.ps1 -Exe trunk\MikuDanceStudio.exe,head\MikuDanceStudio.exe -Runs 5
#       Alternates the executables (trunk, head, trunk, head, ...), prints one
#       line per start and the median per executable. The rule of the perf box:
#       median(head) <= 1.05 * median(trunk).
#   .\startup_time.ps1 -Exe head\MikuDanceStudio.exe -Runs 3 -UntilExit `
#       -Arguments '--mds-trace','tests\fixtures\rust\swing600.pmm','$env:TEMP\l2.trace','600'
#       Times the trace mode until the process exits (it has no visible
#       window); the rule is under 30000 ms.
#
# Output: "exe=<path> run=<n> ms=<elapsed>" per start, then
# "median exe=<path> ms=<median>". Exit code 1 if any start timed out or, with
# -UntilExit, exited non-zero.
param(
    [Parameter(Mandatory = $true)][string[]]$Exe,
    [string[]]$Arguments = @(),
    [int]$Runs = 1,
    [int]$TimeoutMs = 60000,
    [switch]$UntilExit
)
$ErrorActionPreference = 'Stop'
$samples = @{}
foreach ($path in $Exe) { $samples[$path] = New-Object System.Collections.Generic.List[double] }
$failed = $false
for ($run = 1; $run -le $Runs; $run++) {
    foreach ($path in $Exe) {
        $clock = [System.Diagnostics.Stopwatch]::StartNew()
        if ($Arguments.Count -gt 0) {
            $process = Start-Process -FilePath $path -ArgumentList $Arguments -PassThru
        } else {
            $process = Start-Process -FilePath $path -PassThru
        }
        $done = $false
        while ($clock.ElapsedMilliseconds -lt $TimeoutMs) {
            $process.Refresh()
            if ($UntilExit) { $done = $process.HasExited } else { $done = $process.MainWindowHandle -ne [IntPtr]::Zero }
            if ($done) { break }
            Start-Sleep -Milliseconds 5
        }
        $elapsed = $clock.Elapsed.TotalMilliseconds
        if (-not $done) {
            Write-Output "exe=$path run=$run timeout after $TimeoutMs ms"
            $failed = $true
        } else {
            if ($UntilExit -and $process.ExitCode -ne 0) { $failed = $true }
            Write-Output ("exe={0} run={1} ms={2:N0}" -f $path, $run, $elapsed)
            $samples[$path].Add($elapsed)
        }
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
        $process.WaitForExit()
    }
}
foreach ($path in $Exe) {
    $sorted = @($samples[$path] | Sort-Object)
    if ($sorted.Count -gt 0) {
        $middle = [int][math]::Floor(($sorted.Count - 1) / 2)
        $median = if ($sorted.Count % 2 -eq 1) { $sorted[$middle] } else { ($sorted[$middle] + $sorted[$middle + 1]) / 2 }
        Write-Output ("median exe={0} ms={1:N0}" -f $path, $median)
    }
}
if ($failed) { exit 1 }
