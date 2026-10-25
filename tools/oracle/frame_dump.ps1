# Golden image lane: renders frames 0, 150, 300, and 599 of
# tests/fixtures/rust/swing600-golden.pmm with --mds-frame-dump and prints the
# size and sha256 of each PNG.
# Needs build.ps1 and stage.ps1 first, and the console session for D3D9:
#   runtask.ps1 -Script <checkout>\tools\oracle\frame_dump.ps1 -Log <x.log>
#               -ScriptArgs '-Root <checkout> -Out <empty dir>'
param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$Out)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'
$exe = "$Root\out\ci\build\Release\MikuDanceStudio.exe"
New-Item -ItemType Directory -Force $Out | Out-Null
foreach ($name in @('swing600-golden')) {
    $err = "$Out\$name.err.txt"
    $arguments = @('--mds-frame-dump', "$Root\tests\fixtures\rust\$name.pmm", $Out, '0', '150', '300', '599')
    $p = Start-Process $exe -ArgumentList $arguments -Wait -PassThru -RedirectStandardError $err -WorkingDirectory $Out
    "$name exit=$($p.ExitCode) stderr=$((Get-Content $err) -join ' | ')"
}
Get-ChildItem "$Out\*.png" | Sort-Object Name | ForEach-Object {
    "$($_.Name) $($_.Length) $((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower())"
}
