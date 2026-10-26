#!/usr/bin/env bash
# Write licenses/mingw-runtime/: for each MinGW runtime DLL that tools/vkd3d/build.sh copies
# beside the Windows vkd3d-shader DLL, the Debian copyright file of the package that DLL comes
# from, in the image build.sh builds in.
#
# Usage: mingw-copyright.sh   (needs tools/vkd3d/build.sh windows; MDS_VKD3D_OUT as there)
set -euo pipefail

repo="$(cd "$(dirname "$0")/../.." && pwd)"
tmp="${TMPDIR:-/tmp}"
bin="${MDS_VKD3D_OUT:-${tmp%/}/mds-vkd3d}/windows/bin"
image="$(sed -n 's/^IMAGE="\([^"]*\)".*/\1/p' "$repo/tools/vkd3d/build.sh")"
dlls=""
for f in "$bin"/*.dll; do case "${f##*/}" in libvkd3d-shader*) ;; *) dlls="$dlls ${f##*/}" ;; esac; done
[ -n "$dlls" ] || { echo "mingw-copyright.sh: no runtime DLL in $bin" >&2; exit 1; }
out="$repo/licenses/mingw-runtime"
rm -rf "$out"; mkdir -p "$out"

docker run --rm -v "$out:/out" "$image" bash -euc '
  apt-get update -qq >/dev/null
  apt-get install -y -qq --no-install-recommends gcc-mingw-w64-x86-64 >/dev/null 2>&1
  for dll in '"$dlls"'; do
    f=$(x86_64-w64-mingw32-gcc -print-file-name=$dll)
    pkg=$(dpkg -S "$(readlink -f "$f")" | cut -d: -f1)
    ver=$(dpkg-query -W -f="\${Version}" "$pkg")
    cp "/usr/share/doc/$pkg/copyright" "/out/$pkg.copyright"
    echo "$dll	$pkg	$ver	$pkg.copyright" >> /out/dlls.tsv
  done'
cat "$out/dlls.tsv"
