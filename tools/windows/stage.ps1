# Copy the fixture models next to MikuDanceStudio.exe. The app resolves PMM
# model paths from the exe directory.
# Usage: stage.ps1 -Root C:\mds\w2-<id>\repo
param([Parameter(Mandatory)][string]$Root)
$dir = "$Root\out\ci\build\Release"
foreach ($f in 'chain8.pmd', 'chain8.pmx', 'chain8_ik.pmx', 'morph4.pmx') {
    Copy-Item "$Root\tests\fixtures\rust\$f" "$dir\$f" -Force
}
Get-ChildItem "$dir\*.pm*" | % Name
