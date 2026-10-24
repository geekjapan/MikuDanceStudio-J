#!/usr/bin/env bash
# Build the C++ L1 oracle (mds_scene_cli) from a commit of `next`.
# Usage: build_l1.sh <sha>
# Prints the binary path and its sha256. A second run with the same commit
# reuses the build.
set -euo pipefail

[ $# -eq 1 ] || { echo "usage: build_l1.sh <sha>" >&2; exit 2; }
repo="$(cd "$(dirname "$0")/../.." && pwd)"
sha="$(git -C "$repo" rev-parse --verify --quiet "$1^{commit}")" \
  || { echo "build_l1.sh: unknown commit: $1" >&2; exit 2; }

root="${TMPDIR:-/tmp}/mds-oracle/$sha"
src="$root/src"
build="$root/build"

sha256() { shasum -a 256 "$1" | cut -d' ' -f1; }

find_bin() { find "$build" -type f \( -name mds_scene_cli -o -name mds_scene_cli.exe \) | head -n 1; }

bin="$([ -d "$build" ] && find_bin || true)"
if [ -n "$bin" ] && [ -e "$root/.built" ]; then
  echo "reusing build for $sha" >&2
else
  rm -rf "$root"
  mkdir -p "$src"
  # A file, not a pipe: tar can stop before git finishes, and pipefail then
  # ends the script on SIGPIPE with no message.
  git -C "$repo" archive -o "$root/src.tar" "$sha"
  tar -x -C "$src" -f "$root/src.tar"
  rm "$root/src.tar"
  cmake -S "$src" -B "$build" -DMIKUDANCESTUDIO_FORMATS_ONLY=ON -DCMAKE_BUILD_TYPE=Release >&2
  cmake --build "$build" --target mds_scene_cli --parallel >&2
  bin="$(find_bin)"
  [ -n "$bin" ] || { echo "build_l1.sh: mds_scene_cli was not built" >&2; exit 1; }
  touch "$root/.built"
fi

echo "binary: $bin"
echo "sha256: $(sha256 "$bin")"
