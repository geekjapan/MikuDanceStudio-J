#!/usr/bin/env bash
# Build and smoke-test the Windows package from this Mac on the Windows host
# (tools/windows/README.md): send the committed branch as a git bundle and the vkd3d-shader DLLs,
# run package.ps1 over ssh and smoke.ps1 in the console session, fetch the zip, the log and the
# PNGs, and score the PNGs with compare.py.
#
# Usage: package-windows.sh   (env: MDS_WINDOWS_HOST, default nanoha-lan; MDS_WINDOWS_DIR,
#        default C:\mds\w2-package; out and MDS_VKD3D_OUT as in package.sh)
set -euo pipefail

repo="$(cd "$(dirname "$0")/../.." && pwd)"
tmp="${TMPDIR:-/tmp}"
out="${MDS_PACKAGE_OUT:-${tmp%/}/mds-package}"
export MDS_VKD3D_OUT="${MDS_VKD3D_OUT:-$out/vkd3d}"
host="${MDS_WINDOWS_HOST:-nanoha-lan}"
win="${MDS_WINDOWS_DIR:-C:\\mds\\w2-package}"
fwd="${win//\\//}"
branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD)"
name="mds-app-$(tr -d '[:space:]' <"$repo/VERSION")-$(git -C "$repo" rev-parse --short HEAD)-windows-x86_64"
vk="$MDS_VKD3D_OUT/windows/bin"
FRAMES="0 150 300 599"

[ -z "$(git -C "$repo" status --porcelain)" ] || { echo "package-windows.sh: commit first" >&2; exit 1; }
[ -f "$vk/libvkd3d-shader-1.dll" ] || "$repo/tools/vkd3d/build.sh" windows
remote_ps() { ssh "$host" "powershell -NoProfile -ExecutionPolicy Bypass $*"; }

git -C "$repo" bundle create "$out/w2-package.bundle" "$branch"
ssh "$host" "if not exist $win\\vkd3d mkdir $win\\vkd3d"
scp -q "$out/w2-package.bundle" "$host:$fwd/w2-package.bundle"
for f in "$vk"/*.dll; do scp -q "$f" "$host:$fwd/vkd3d/"; done
ssh "$host" "if exist $win\\repo\\.git (git -C $win\\repo fetch -q $win\\w2-package.bundle $branch && git -C $win\\repo reset -q --hard FETCH_HEAD) else (git clone -q -b $branch $win\\w2-package.bundle $win\\repo)"

remote_ps -File "$win\\repo\\tools\\package\\package.ps1" -Root "$win\\repo" -Vkd3d "$win\\vkd3d" \
  -Out "$win\\out" -Name "$name" | tee "$out/package-windows.log"
remote_ps -File "$win\\repo\\tools\\windows\\runtask.ps1" -Script "$win\\repo\\tools\\package\\smoke.ps1" \
  -Log "$win\\smoke.log" -TimeoutSec 1800 \
  -ScriptArgs "\"-Zip $win\\out\\$name.zip -Root $win\\repo -Dir $win\\smoke\""

rm -rf "$out/smoke-windows"; mkdir -p "$out/smoke-windows/out"
scp -q "$host:$fwd/out/$name.zip" "$out/"
scp -q "$host:$fwd/smoke.log" "$out/smoke-windows/smoke.log"
scp -q "$host:$fwd/smoke/out/*.png" "$out/smoke-windows/out/"
{
  tr -d '\r' <"$out/smoke-windows/smoke.log"
  echo "== compare.py out golden swing600-golden $FRAMES (on $(uname -sm))"
  python3 -I "$repo/tools/package/compare.py" "$out/smoke-windows/out" \
    "$repo/tests/fixtures/rust/golden" swing600-golden $FRAMES || true
} | tee "$out/smoke-windows.log"
echo "archive $out/$name.zip $(wc -c <"$out/$name.zip" | tr -d ' ') bytes"
grep -q '^golden rule' "$out/smoke-windows.log"
