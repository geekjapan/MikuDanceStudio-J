# MME pass-plan lane: runs mme_passplan.exe once per effect file and writes the
# plans plus a SHA256SUMS file.
#   <Out>\ray-mmd\<relative path>.plan.txt   every *.fx under -Corpus
#   <Out>\extra\<name>.fx.plan.txt           every *.fx in tests\fixtures\rust\mme\effects
# Needs build.ps1 (with tests on: the tool is built with them) first, and the
# console session for the D3D9 device:
#   runtask.ps1 -Script <checkout>\tools\oracle\mme_passplan.ps1 -Log <x.log>
#               -TimeoutSec 7200 -ScriptArgs '-Root <checkout> -Out <empty dir>'
# -Filter limits the run to relative paths that contain the text (debugging).
param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$Out,
      [string]$Corpus = 'C:\mds\corpus\ray-mmd', [string]$Filter = '', [int]$PerFileSec = 300)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'
$exe = "$Root\out\ci\build\Release\mme_passplan.exe"
$sets = @(
    @{ Label = 'ray-mmd'; Dir = $Corpus },
    @{ Label = 'extra'; Dir = "$Root\tests\fixtures\rust\mme\effects" })
New-Item -ItemType Directory -Force $Out | Out-Null
$ok = 0; $bad = 0
foreach ($set in $sets) {
    if (-not (Test-Path $set.Dir)) { "skip $($set.Label): $($set.Dir) not found"; continue }
    $dir = (Resolve-Path $set.Dir).Path.TrimEnd('\')
    $files = Get-ChildItem -Recurse -File -Filter *.fx $dir | ForEach-Object { $_.FullName.Substring($dir.Length + 1) }
    $files = [string[]]$files
    [Array]::Sort($files, [StringComparer]::Ordinal)
    foreach ($rel in $files) {
        if ($Filter -and -not $rel.Contains($Filter)) { continue }
        $plan = "$Out\$($set.Label)\$($rel.Replace('\', '/')).plan.txt"
        New-Item -ItemType Directory -Force (Split-Path $plan) | Out-Null
        $p = Start-Process $exe -ArgumentList @('--root', "`"$dir`"", '--out', "`"$plan`"", "`"$dir\$rel`"") `
            -PassThru -WindowStyle Hidden -WorkingDirectory $Out
        if (-not $p.WaitForExit($PerFileSec * 1000)) { $p.Kill(); $p.WaitForExit(); "TIMEOUT $($set.Label)/$rel" }
        if ($p.ExitCode -eq 0 -and (Test-Path $plan)) { $ok++ } else { $bad++; "FAIL exit=$($p.ExitCode) $($set.Label)/$rel" }
    }
}
"plans ok=$ok failed=$bad"
$rels = [string[]](Get-ChildItem -Recurse -File -Filter *.plan.txt $Out | ForEach-Object { $_.FullName.Substring($Out.Length + 1).Replace('\', '/') })
[Array]::Sort($rels, [StringComparer]::Ordinal)
$lines = [string[]]($rels | ForEach-Object { "$((Get-FileHash "$Out\$($_.Replace('/', '\'))" -Algorithm SHA256).Hash.ToLower())  $_" })
[IO.File]::WriteAllText("$Out\SHA256SUMS", (($lines -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
"SHA256SUMS lines=$($lines.Count)"
