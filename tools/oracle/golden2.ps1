# golden2 lane: renders the scenes of tests/fixtures/rust/golden2 with
# --mds-frame-dump and writes their edge probes (--mds-edge-probe), plus the
# edge probe of tests/fixtures/rust/swing600-golden.pmm. Runs everything twice
# into <Out>\run1 and <Out>\run2, prints the size and sha256 of every file of
# run1, and exits 1 when a run fails or the two runs differ.
# Needs build.ps1 first, and the console session for D3D9:
#   runtask.ps1 -Script <checkout>\tools\oracle\golden2.ps1 -Log <x.log>
#               -ScriptArgs '-Root <checkout> -Out <empty dir>'
param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$Out)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'
$exe = "$Root\out\ci\build\Release\MikuDanceStudio.exe"
$exeDir = Split-Path $exe
$fixtures = "$Root\tests\fixtures\rust"
$golden2 = "$fixtures\golden2"

# The app resolves model, accessory, and picture paths from the exe directory.
$stage = @('chain8.pmd', 'chain8.pmx', 'chain8_ik.pmx', 'morph4.pmx' | % { "$fixtures\$_" }) +
         @('skin_tex.pmx', 'skin_tex.bmp', 'cube.bmp', 'background.png' | % { "$golden2\$_" }) +
         @('cube.x', 'normals_uv.x' | % { "$fixtures\accessory\$_" })
foreach ($f in $stage) { Copy-Item $f $exeDir -Force }

# Keep in step with SCENES in gen_golden2.py (gen_golden2.py --frames).
$scenes = [ordered]@{
    'selfshadow'   = @('0', '30')
    'groundshadow' = @('0', '30')
    'accessory'    = @('0', '30')
    'skin'         = @('0', '30')
    'background'   = @('0')
    'perspective'  = @('0', '30')
}

function Run([string[]]$arguments, [string]$dir, [string]$tag) {
    $err = "$dir\$tag.err.txt"
    $p = Start-Process $exe -ArgumentList $arguments -Wait -PassThru -RedirectStandardError $err -WorkingDirectory $dir
    $text = (Get-Content $err) -join ' | '
    Remove-Item $err
    "$tag exit=$($p.ExitCode) $text"
    return $p.ExitCode
}

$failed = $false
foreach ($run in 'run1', 'run2') {
    $dir = "$Out\$run"
    New-Item -ItemType Directory -Force $dir | Out-Null
    foreach ($name in $scenes.Keys) {
        $pmm = "$golden2\$name.pmm"
        $frames = $scenes[$name]
        $r = Run (@('--mds-frame-dump', $pmm, $dir) + $frames) $dir "$run $name dump"
        $failed = $failed -or ($r[-1] -ne 0); $r[0..($r.Count - 2)]
        $r = Run (@('--mds-edge-probe', $pmm, "$dir\$name.edge.txt") + $frames) $dir "$run $name probe"
        $failed = $failed -or ($r[-1] -ne 0); $r[0..($r.Count - 2)]
    }
    $r = Run @('--mds-edge-probe', "$fixtures\swing600-golden.pmm", "$dir\swing600-golden.edge.txt", '0', '150', '300', '599') $dir "$run swing600-golden probe"
    $failed = $failed -or ($r[-1] -ne 0); $r[0..($r.Count - 2)]
}

foreach ($f in Get-ChildItem "$Out\run1" -File | Sort-Object Name) {
    $h1 = (Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLower()
    $other = "$Out\run2\$($f.Name)"
    $h2 = if (Test-Path $other) { (Get-FileHash $other -Algorithm SHA256).Hash.ToLower() } else { 'missing' }
    $same = if ($h1 -eq $h2) { 'same' } else { $failed = $true; 'DIFFERS' }
    "$($f.Name) $($f.Length) $h1 $same"
}
if ((Get-ChildItem "$Out\run2" -File).Count -ne (Get-ChildItem "$Out\run1" -File).Count) {
    'run1 and run2 hold different file counts'; $failed = $true
}
if ($failed) { 'golden2: FAILED'; exit 1 }
'golden2: two runs identical'
