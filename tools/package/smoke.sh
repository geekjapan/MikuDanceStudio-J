#!/usr/bin/env bash
# Unpack a package from package.sh into a fresh folder and run it there: the frame dump of
# tests/fixtures/rust/swing600.pmm, the dump of swing600-golden.pmm scored against the golden
# images (compare.py), and the MME scene mmegold/anime through the packaged vkd3d-shader.
# macOS runs here; Linux runs in a fresh debian:bookworm container on Mesa lavapipe (no GPU).
#
# Usage: smoke.sh <archive.tar.gz>    Log: <out>/smoke-<target>.log (out as in package.sh)
set -euo pipefail

IMAGE="debian@sha256:854dd8ab51d62866dbd8f5431d15ce77b12983a2a4a1e1fe43a2395dc7ef9f61" # debian:bookworm
FRAMES="0 150 300 599"

if [ "${1:-}" = "--inside" ]; then
  # The run itself, on the host or in the container: <smoke dir> <backend> <adapter command>.
  # A failing dump stops it (set -e), so each "exit 0" line is a dump that succeeded.
  cd "$2"
  echo "== adapter (inferred: mds-app does not print it; its wgpu backend here is $3)"
  eval "$4" || echo "adapter query failed"
  unset MDS_VKD3D_LIB
  for pmm in swing600 swing600-golden; do
    echo "== app/mds-app --frame-dump scene/$pmm.pmm out $FRAMES"
    ./app/mds-app --frame-dump "scene/$pmm.pmm" out $FRAMES
    echo "exit 0"
    for f in $FRAMES; do echo "dumped out/$pmm-$f.png $(wc -c <"out/$pmm-$f.png") bytes"; done
  done
  # Without the library beside the exe the MME runtime does not start and the dump fails.
  echo "== app/mds-app --frame-dump mme/anime.pmm out 0 3 (MDS_VKD3D_LIB unset)"
  ./app/mds-app --frame-dump mme/anime.pmm out 0 3
  echo "exit 0"
  for f in 0 3; do echo "dumped out/anime-$f.png $(wc -c <"out/anime-$f.png") bytes"; done
  exit 0
fi

archive="${1:-}"
[ -f "$archive" ] || { echo "usage: smoke.sh <archive.tar.gz>" >&2; exit 2; }
repo="$(cd "$(dirname "$0")/../.." && pwd)"
here="$repo/tools/package"
fx="$repo/tests/fixtures/rust"
name="$(basename "$archive" .tar.gz)"
target="${name##*-}"; case "$name" in *-linux-*) target="linux-$target" ;; esac
out="$(cd "$(dirname "$archive")" && pwd)"
dir="$out/smoke-$target"
log="$out/smoke-$target.log"
rm -rf "$dir"; mkdir -p "$dir/app" "$dir/scene" "$dir/mme" "$dir/out"
tar -xzf "$archive" -C "$dir/app" --strip-components=1
cp "$fx"/swing600.pmm "$fx"/swing600-golden.pmm "$fx"/chain8.pmd "$fx"/chain8.pmx \
  "$fx"/chain8_ik.pmx "$fx"/morph4.pmx "$dir/scene/"
cp "$fx"/mmegold/anime.pmm "$fx"/mmegold/anime.fx "$fx"/chain8.pmx "$fx"/morph4.pmx \
  "$repo/rust/crates/mds-mmert/tests/data/blink.gif" "$dir/mme/"
sed 's/^Pmd0 = .*anime\.fx/Pmd0 = anime.fx/' "$fx/mmegold/anime.emm" >"$dir/mme/anime.emm"
grep -q '^Pmd0 = anime.fx' "$dir/mme/anime.emm"

{
  echo "== smoke $name $(date -u +%FT%TZ) on $(uname -sm)"
  case "$target" in
    macos)
      cp "$0" "$dir/run.sh"
      bash "$dir/run.sh" --inside "$dir" Metal \
        "system_profiler SPDisplaysDataType | grep -E 'Chipset Model|Metal'" ;;
    linux-*)
      cp "$0" "$dir/run.sh"
      docker run --rm --platform "linux/${target#linux-}" -v "$dir:/smoke" "$IMAGE" bash -euc '
        apt-get update -qq >/dev/null
        apt-get install -y -qq --no-install-recommends libasound2 libvulkan1 mesa-vulkan-drivers \
          vulkan-tools >/dev/null 2>&1
        echo "container: $(uname -m), $(ldd --version | head -1)"
        bash /smoke/run.sh --inside /smoke Vulkan "vulkaninfo --summary 2>/dev/null | grep -E \"deviceName|driverName|driverInfo|deviceType\""' ;;
  esac
  echo "== compare.py out golden swing600-golden $FRAMES"
  python3 -I "$here/compare.py" "$dir/out" "$fx/golden" swing600-golden $FRAMES || true
} 2>&1 | tee "$log"
grep -q '^golden rule' "$log"
