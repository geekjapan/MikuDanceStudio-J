param([switch]$Execute)
$ErrorActionPreference = 'Stop'
$exportRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\exports')).ProviderPath
$rootPrefix = $exportRoot.TrimEnd('\') + '\'
$planPath = Join-Path $exportRoot 'cleanup-plan-20261014.csv'
$policy = Get-Content -LiteralPath (Join-Path $exportRoot 'cleanup-plan-20261014.json') -Raw | ConvertFrom-Json
if ($policy.Root -ne $exportRoot) { throw 'Plan belongs to another exports directory.' }
$plan = @(Import-Csv -LiteralPath $planPath)
foreach ($entry in $plan) {
    $target = [IO.Path]::GetFullPath((Join-Path $exportRoot $entry.RelativePath))
    if (-not $target.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Path outside exports: $target" }
    $top = ($entry.RelativePath -split '\\')[0]
    if ($policy.PreservedRoots -contains $top) { throw "Protected evidence: $target" }
    $image = [IO.Path]::GetExtension($target) -eq '.bgra'
    $archive = [IO.Path]::GetDirectoryName($target) -eq $exportRoot -and ($target.EndsWith('.tar') -or $target.EndsWith('.tar.gz'))
    if (-not ($image -or $archive)) { throw "Unexpected cleanup target: $target" }
    if (-not (Test-Path -LiteralPath $target)) { continue }
    $item = Get-Item -LiteralPath $target
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Length -ne [long]$entry.Length) { throw "Target changed: $target" }
    $parent = $item.Directory
    while ($parent.FullName -ne $exportRoot) {
        if ($parent.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point in target path: $target" }
        $parent = $parent.Parent
    }
}
$bytes = ($plan | Measure-Object -Property Length -Sum).Sum
Write-Output "Plan: $($plan.Count) files, $([math]::Round($bytes / 1GB, 3)) logical GiB. Physical reclaim depends on compression. Protected roots, reports and CPU inputs are retained."
if (-not $Execute) { Write-Output 'Dry run only. Use -Execute to apply this reviewed plan.'; return }
$before = (Get-PSDrive -Name ([IO.Path]::GetPathRoot($exportRoot).Substring(0, 1))).Free
$deleted = 0; $freed = [long]0; $failures = @()
foreach ($entry in $plan) {
    $target = [IO.Path]::GetFullPath((Join-Path $exportRoot $entry.RelativePath))
    if (-not (Test-Path -LiteralPath $target)) { continue }
    try {
        Remove-Item -LiteralPath $target -Force -ErrorAction Stop
        $deleted++; $freed += [long]$entry.Length
        if ($deleted % 5000 -eq 0) { Write-Output "Deleted: $deleted files." }
    } catch { $failures += [pscustomobject]@{Path=$entry.RelativePath;Error=$_.Exception.Message} }
}
$after = (Get-PSDrive -Name ([IO.Path]::GetPathRoot($exportRoot).Substring(0, 1))).Free
$result = [pscustomobject]@{
    Date=[DateTime]::UtcNow.ToString('o');Root=$exportRoot;DeletedFiles=$deleted
    DeletedLogicalBytes=$freed;DeletedLogicalGiB=[math]::Round($freed / 1GB, 3)
    DriveFreeBefore=$before;DriveFreeAfter=$after;ReclaimedDriveGiB=[math]::Round(($after-$before) / 1GB, 3)
    Errors=$failures;Plan=$planPath
}
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $exportRoot 'cleanup-result-20261014.json') -Encoding UTF8
$result | Format-List
if ($failures.Count) { throw "Failed to delete $($failures.Count) files. See cleanup-result-20261014.json." }
