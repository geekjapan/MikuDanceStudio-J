# Build the Windows package of mds-app on the Windows host: x86_64-pc-windows-msvc, once with the
# default features and once with dxopenni, which the package ships. package-windows.sh runs it.
# Usage: package.ps1 -Root <checkout> -Vkd3d <dir of libvkd3d-shader-1.dll and its runtime DLLs>
#                    -Out <dir> -Name <archive name without .zip>
param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$Vkd3d,
      [Parameter(Mandatory)][string]$Out, [Parameter(Mandatory)][string]$Name)
. "$Root\tools\windows\env.ps1"
$ErrorActionPreference = 'Continue'
Set-Location "$Root\rust"
"== package $Name  $(Get-Date -Format o)"
git rev-parse HEAD
rustc -V
$env:CARGO_TARGET_DIR = "$Out\target"
# The C runtime links statically (Bullet's cc build follows the target feature), so the package
# needs no Visual C++ redistributable.
$env:RUSTFLAGS = '-C target-feature=+crt-static'
foreach ($f in 'default', 'dxopenni') {
    $cargo = @('build', '--release', '--locked', '-p', 'mds-app')
    if ($f -ne 'default') { $cargo += @('--features', $f) }
    "== cargo $cargo"
    & cargo @cargo
    "cargo exit $LASTEXITCODE"; if ($LASTEXITCODE) { exit 10 }
    Copy-Item "$Out\target\release\mds-app.exe" "$Out\mds-app-$f.exe" -Force
    "== dumpbin /dependents mds-app-$f.exe"
    dumpbin /nologo /dependents "$Out\mds-app-$f.exe" | Select-String '\.dll' | % { $_.Line.Trim() }
}

$stage = "$Out\stage\$Name"
Remove-Item -Recurse -Force "$Out\stage" -ErrorAction SilentlyContinue
New-Item -ItemType Directory $stage | Out-Null
Copy-Item "$Out\mds-app-dxopenni.exe" "$stage\mds-app.exe"
Copy-Item "$Vkd3d\*.dll" $stage
Copy-Item -Recurse "$Root\licenses" "$stage\licenses"
$sha = git rev-parse HEAD
@"
MikuDanceStudio (mds-app), windows-x86_64, built from MikuDanceStudio-J $sha.

  mds-app.exe [<file.pmm>]                                 the editor window
  mds-app.exe --frame-dump <file.pmm> <out-dir> <frame>... PNG frames, no window

libvkd3d-shader-1.dll beside mds-app.exe is vkd3d-shader 2.1, which MME effects need, and
libgcc_s_seh-1.dll is the MinGW runtime it was built with. This build has the dxopenni feature:
the MoCap menu loads Data\DxOpenNI.dll, which is not included. licenses\ has the license texts
(licenses\README.md); licenses\FORK.md says which parts are MIT and which are license pending.
Build and runtime notes: docs/PACKAGING.md of the repository.
"@ -replace "`r?`n", "`r`n" | Set-Content -Encoding ASCII "$stage\README.txt"
$zip = "$Out\$Name.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
# bsdtar writes the zip with / separators, which every unzip reads.
tar.exe -a -c -f $zip -C "$Out\stage" $Name
"tar exit $LASTEXITCODE"; if ($LASTEXITCODE) { exit 11 }
"archive $zip $((Get-Item $zip).Length) bytes"
Get-ChildItem $stage | % { "  $($_.Name)`t$(if ($_.PSIsContainer) { 'dir' } else { $_.Length })" }
"== done $(Get-Date -Format o)"
