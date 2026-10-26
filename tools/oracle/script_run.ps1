# Script lane (wave 3 slices script, script2, script3, script4): runs every
# tests\fixtures\rust\<Dir>\*.txt (Dir: script by default, script2, physscen,
# script2\pmm1, script3, script4) with --mds-script twice, into <Out>\run1\<name> and <Out>\run2\<name>, and
# compares the two runs file by file. Stages the fixtures next to the exe
# first (the scripts name their inputs relative to the exe directory).
# Needs build.ps1 first, and the console session for the D3D9 device:
#   runtask.ps1 -Script <checkout>\tools\oracle\script_run.ps1 -Log <x.log>
#               -ScriptArgs '-Root <checkout> -Out <empty dir>'
# -Filter runs only the scripts whose name contains the text. Staged next to the
# exe: tests\fixtures\rust\*, script\inputs\*, <Dir>\inputs\*, and for
# script2\pmm1 also tests\fixtures\rust\pmm1\*, for script3 also
# tests\fixtures\rust\vsq\*.vsq, for script4 also script3\inputs\* and the AVIs of
# rust\crates\mds-media\tests\fixtures\bgmovie.
param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$Out, [string]$Filter = '',
      [string]$Dir = 'script')
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'
$exeDir = "$Root\out\ci\build\Release"
$fixtures = "$Root\tests\fixtures\rust"
$stage = @($fixtures, "$fixtures\script\inputs", "$fixtures\$Dir\inputs")
if ($Dir -eq 'script2\pmm1') { $stage += "$fixtures\pmm1" }
if ($Dir -eq 'script3') { $stage += "$fixtures\vsq" }
if ($Dir -eq 'script4') { $stage += @("$fixtures\script3\inputs", "$Root\rust\crates\mds-media\tests\fixtures\bgmovie") }
foreach ($f in Get-ChildItem -File $stage -ErrorAction SilentlyContinue) {
    if ($f.Extension -in '.pmd', '.pmx', '.pmm', '.vmd', '.vpd', '.x', '.wav', '.png', '.bmp', '.vsq', '.vac', '.avi') {
        Copy-Item $f.FullName "$exeDir\$($f.Name)" -Force
    }
}
$scripts = Get-ChildItem -File "$fixtures\$Dir\*.txt" | Where-Object { $_.Name.Contains($Filter) } | Sort-Object Name
$failed = 0
foreach ($run in 'run1', 'run2') {
    foreach ($s in $scripts) {
        $dir = "$Out\$run\$($s.BaseName)"
        Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force $dir | Out-Null
        $err = "$Out\$run\$($s.BaseName).err.txt"
        $p = Start-Process "$exeDir\MikuDanceStudio.exe" -ArgumentList @('--mds-script', "`"$($s.FullName)`"", "`"$dir`"") `
            -Wait -PassThru -RedirectStandardError $err -WorkingDirectory $exeDir
        if ($p.ExitCode -ne 0) { $failed++ }
        "$run $($s.BaseName) exit=$($p.ExitCode) $((Get-Content -Encoding UTF8 $err | Select-Object -Last 2) -join ' | ')"
    }
}
$diff = 0
foreach ($s in $scripts) {
    $a = "$Out\run1\$($s.BaseName)"; $b = "$Out\run2\$($s.BaseName)"
    $names = @(Get-ChildItem -File $a, $b -ErrorAction SilentlyContinue | ForEach-Object Name | Sort-Object -Unique)
    foreach ($n in $names) {
        $ha = if (Test-Path "$a\$n") { (Get-FileHash "$a\$n" -Algorithm SHA256).Hash } else { 'missing' }
        $hb = if (Test-Path "$b\$n") { (Get-FileHash "$b\$n" -Algorithm SHA256).Hash } else { 'missing' }
        if ($ha -ne $hb) { $diff++; "DIFF $($s.BaseName)\$n run1=$ha run2=$hb" }
    }
    if (Test-Path "$a\manifest.tsv") { Get-Content "$a\manifest.tsv" | ForEach-Object { "$($s.BaseName): $_" } }
}
"scripts=$($scripts.Count) failed=$failed differing=$diff"
if ($failed -or $diff) { exit 1 }
