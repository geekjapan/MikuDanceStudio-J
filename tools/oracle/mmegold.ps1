# mmegold lane: renders the scenes of tests/fixtures/rust/mmegold with
# --mds-mme-dump, which writes an image and an MME probe per frame. Stages
# each PMM in <Out>\stage with its EMM, whose $(fixtures), $(mmegold), and
# $(corpus) become <Out>\stage\effects (tests\fixtures\rust\mme\effects),
# <Out>\stage\mmegold (the scenes' effects and blink.gif of mds-mmert), and
# <Out>\stage\ray-mmd (a copy of -Corpus without .git), so the probes name no
# host directory. The models and ray.x go next to the exe, where the app
# resolves the PMM's object paths.
# Runs everything twice into <Out>\run1 and <Out>\run2, prints the size and
# sha256 of every file of run1, and exits 1 when a run fails, a probe lists no
# effect, a TIME parameter is not the frame time, or the two runs differ.
# Needs build.ps1 first, and the console session for D3D9:
#   runtask.ps1 -Script <checkout>\tools\oracle\mmegold.ps1 -Log <x.log>
#               -ScriptArgs '-Root <checkout> -Out <empty dir>'
param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$Out,
      [string]$Corpus = 'C:\mds\corpus\ray-mmd')
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'
$exe = "$Root\out\ci\build\Release\MikuDanceStudio.exe"
$fixtures = "$Root\tests\fixtures\rust"
$mmegold = "$fixtures\mmegold"

$stage = "$Out\stage"
New-Item -ItemType Directory -Force $stage | Out-Null
robocopy "$fixtures\mme\effects" "$stage\effects" /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
robocopy $Corpus "$stage\ray-mmd" /MIR /XD .git /NFL /NDL /NJH /NJS /NP | Out-Null
if (-not (Test-Path "$stage\ray-mmd\Main\main.fx")) { "mmegold: no corpus at $Corpus"; exit 1 }
New-Item -ItemType Directory -Force "$stage\mmegold" | Out-Null
Copy-Item "$mmegold\*.fx", "$Root\rust\crates\mds-mmert\tests\data\blink.gif" "$stage\mmegold" -Force
foreach ($f in "$fixtures\chain8.pmx", "$fixtures\morph4.pmx", "$Corpus\ray.x") {
    Copy-Item $f (Split-Path $exe) -Force
}

# Keep in step with SCENES in gen_mmegold.py (gen_mmegold.py --frames).
$scenes = [ordered]@{
    'objects'   = @('0', '30')
    'post'      = @('0', '30')
    'offscreen' = @('0', '30')
    'timeofday' = @('0', '30')
    'main'      = @('0', '30')
    'control'   = @('0', '15', '30')
    'anime'     = @('0', '3', '4', '9', '30')
    'ray'       = @('0', '30')
}
foreach ($name in $scenes.Keys) {
    Copy-Item "$mmegold\$name.pmm" $stage -Force
    $emm = [IO.File]::ReadAllText("$mmegold\$name.emm").Replace('$(fixtures)', "$stage\effects").Replace('$(mmegold)', "$stage\mmegold").Replace('$(corpus)', "$stage\ray-mmd")
    [IO.File]::WriteAllText("$stage\$name.emm", $emm, [Text.Encoding]::ASCII)
}

function Run([string[]]$arguments, [string]$dir, [string]$tag) {
    $err = "$dir\$tag.err.txt"
    $p = Start-Process $exe -ArgumentList $arguments -Wait -PassThru -RedirectStandardError $err -WorkingDirectory $dir
    $text = (Get-Content $err) -join ' | '
    Remove-Item $err
    "$tag exit=$($p.ExitCode) $text"
    return $p.ExitCode
}

# A probe must list an effect, and each TIME parameter must hold the frame
# time of its "frame" line (non-edit mode, see trace_mode.cpp).
function CheckProbe([string]$path) {
    $lines = Get-Content $path
    $seconds = ($lines | Where-Object { $_ -like 'frame *' } | Select-Object -First 1).Split(' ')[2]
    if (-not ($lines | Where-Object { $_ -like 'effect *' })) { return "$path lists no effect" }
    foreach ($l in $lines | Where-Object { $_ -match '^param \S+ TIME ' }) {
        if ($l.Split(' ')[-1] -ne $seconds) { return "$path TIME is not ${seconds}: $l" }
    }
    return ''
}

$failed = $false
foreach ($run in 'run1', 'run2') {
    $dir = "$Out\$run"
    New-Item -ItemType Directory -Force $dir | Out-Null
    foreach ($name in $scenes.Keys) {
        $r = Run (@('--mds-mme-dump', "$stage\$name.pmm", $dir) + $scenes[$name]) $dir "$run $name"
        $failed = $failed -or ($r[-1] -ne 0); $r[0..($r.Count - 2)]
    }
    foreach ($probe in Get-ChildItem "$dir\*.mme.txt") {
        $problem = CheckProbe $probe.FullName
        if ($problem) { "probe: $problem"; $failed = $true }
    }
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
if ($failed) { 'mmegold: FAILED'; exit 1 }
'mmegold: two runs identical'
