# accgold lane: dumps every .x and .vac file of tests/fixtures/rust/accessory
# with --mds-mesh-dump (format: src/tools/mesh_dump.cpp), hosted by the empty
# scene of tests/fixtures/rust/script/expected/empty/empty.pmm. Runs twice into
# <Out>\run1 and <Out>\run2, prints the size and sha256 of every file of run1,
# and exits 1 when a run fails or the two runs differ.
# Needs build.ps1 first, and the console session for D3D9:
#   runtask.ps1 -Script <checkout>\tools\oracle\accgold.ps1 -Log <x.log>
#               -ScriptArgs '-Root <checkout> -Out <empty dir>'
param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$Out)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'
$exe = "$Root\out\ci\build\Release\MikuDanceStudio.exe"
$pmm = "$Root\tests\fixtures\rust\script\expected\empty\empty.pmm"
$inputs = Get-ChildItem "$Root\tests\fixtures\rust\accessory\*" -Include '*.x', '*.vac' |
          Sort-Object Name | % { $_.FullName }

$failed = $false
foreach ($run in 'run1', 'run2') {
    $dir = "$Out\$run"
    New-Item -ItemType Directory -Force $dir | Out-Null
    $err = "$Out\$run.err.txt"
    $p = Start-Process $exe -ArgumentList (@('--mds-mesh-dump', $pmm, $dir) + $inputs) -Wait -PassThru `
                       -RedirectStandardError $err -WorkingDirectory $dir
    "$run exit=$($p.ExitCode) $((Get-Content $err) -join ' | ')"
    Remove-Item $err
    $failed = $failed -or ($p.ExitCode -ne 0)
}

foreach ($f in Get-ChildItem "$Out\run1" -File | Sort-Object Name) {
    $h1 = (Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLower()
    $other = "$Out\run2\$($f.Name)"
    $h2 = if (Test-Path $other) { (Get-FileHash $other -Algorithm SHA256).Hash.ToLower() } else { 'missing' }
    $same = if ($h1 -eq $h2) { 'same' } else { $failed = $true; 'DIFFERS' }
    "$($f.Name) $($f.Length) $h1 $same"
}
$count = (Get-ChildItem "$Out\run1" -File).Count
if ($count -ne $inputs.Count -or (Get-ChildItem "$Out\run2" -File).Count -ne $count) {
    "expected $($inputs.Count) dumps per run"; $failed = $true
}
if ($failed) { 'accgold: FAILED'; exit 1 }
'accgold: two runs identical'
