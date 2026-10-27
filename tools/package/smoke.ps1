# The Windows twin of smoke.sh: unpack the package into a fresh folder and run the frame dumps
# there. Runs in the console session (tools/windows/runtask.ps1); package-windows.sh scores the
# PNGs on the Mac with compare.py.
# Usage: smoke.ps1 -Zip <archive.zip> -Root <checkout> -Dir <fresh folder>
param([Parameter(Mandatory)][string]$Zip, [Parameter(Mandatory)][string]$Root,
      [Parameter(Mandatory)][string]$Dir)
$ErrorActionPreference = 'Continue'
$frames = '0', '150', '300', '599'
$fx = "$Root\tests\fixtures\rust"
"== smoke $(Split-Path -Leaf $Zip) $(Get-Date -Format o) on $env:COMPUTERNAME, session $((Get-Process -Id $PID).SessionId)"
Remove-Item -Recurse -Force $Dir -ErrorAction SilentlyContinue
foreach ($d in 'app', 'scene', 'mme', 'out') { New-Item -ItemType Directory "$Dir\$d" | Out-Null }
tar.exe -x -f $Zip -C "$Dir\app" --strip-components=1
if ($LASTEXITCODE) { "unpack failed"; exit 1 }
foreach ($f in 'swing600.pmm', 'swing600-golden.pmm', 'chain8.pmd', 'chain8.pmx', 'chain8_ik.pmx', 'morph4.pmx') {
    Copy-Item "$fx\$f" "$Dir\scene\"
}
foreach ($f in "$fx\mmegold\anime.pmm", "$fx\mmegold\anime.fx", "$fx\chain8.pmx", "$fx\morph4.pmx",
               "$Root\rust\crates\mds-mmert\tests\data\blink.gif") {
    Copy-Item $f "$Dir\mme\"
}
(Get-Content "$fx\mmegold\anime.emm") -replace '^Pmd0 = .*anime\.fx', 'Pmd0 = anime.fx' |
    Set-Content -Encoding ASCII "$Dir\mme\anime.emm"

"== adapter (inferred: mds-app does not print it; its wgpu backend here is DX12)"
Get-CimInstance Win32_VideoController | % { "$($_.Name), driver $($_.DriverVersion)" }
Remove-Item Env:MDS_VKD3D_LIB -ErrorAction SilentlyContinue
Set-Location $Dir
foreach ($pmm in 'swing600', 'swing600-golden') {
    "== app\mds-app.exe --frame-dump scene\$pmm.pmm out $frames"
    & .\app\mds-app.exe --frame-dump "scene\$pmm.pmm" out @frames 2>&1 | % { "$_" }
    "exit $LASTEXITCODE"; if ($LASTEXITCODE) { exit 1 }
    foreach ($f in $frames) { "dumped out/$pmm-$f.png $((Get-Item "out\$pmm-$f.png").Length) bytes" }
}
# Without the library beside the exe the MME runtime does not start and the dump fails.
"== app\mds-app.exe --frame-dump mme\anime.pmm out 0 3 (MDS_VKD3D_LIB unset)"
& .\app\mds-app.exe --frame-dump mme\anime.pmm out 0 3 2>&1 | % { "$_" }
"exit $LASTEXITCODE"; if ($LASTEXITCODE) { exit 1 }
foreach ($f in '0', '3') { "dumped out/anime-$f.png $((Get-Item "out\anime-$f.png").Length) bytes" }
