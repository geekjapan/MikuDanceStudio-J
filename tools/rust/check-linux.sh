#!/usr/bin/env bash
# Run tools/rust/check.sh in a pinned Linux container.
# Usage: check-linux.sh [amd64|arm64|all]   (default: all)
# The mds-shader tests load vkd3d-shader, so this needs tools/vkd3d/build.sh linux-<arch>
# for each architecture it runs. The library is mounted from ${MDS_VKD3D_OUT:-${TMPDIR:-/tmp}/mds-vkd3d}.
set -euo pipefail

IMAGE="rust@sha256:48b7f435b8fc6378ce43b44f15e3a47fd8919b2825f835c39bd4bd3da50af5b8" # rust:1-bookworm
repo="$(cd "$(dirname "$0")/../.." && pwd)"
toolchain="$(sed -n 's/^channel *= *"\(.*\)"/\1/p' "$repo/rust/rust-toolchain.toml")"
[ -n "$toolchain" ] || { echo "check-linux.sh: no channel in rust-toolchain.toml" >&2; exit 2; }
tmp="${TMPDIR:-/tmp}"
vkd3d_out="${MDS_VKD3D_OUT:-${tmp%/}/mds-vkd3d}"

# The mds-fx corpus tests read the ray-mmd checkout; without it they fail with their own hint.
corpus_mount=()
[ -d "${tmp%/}/mds-corpus/ray-mmd" ] && corpus_mount=(-v "${tmp%/}/mds-corpus:/corpus:ro" -e MDS_CORPUS=/corpus)

need_lib() {
  [ -f "$vkd3d_out/linux-$1/lib/libvkd3d-shader.so.1" ] || {
    echo "check-linux.sh: $vkd3d_out/linux-$1/lib/libvkd3d-shader.so.1 missing; run tools/vkd3d/build.sh linux-$1" >&2
    exit 1
  }
}

run() {
  echo "== linux/$1 =="
  # The repo is read-only; build output goes to a path inside the container.
  docker run --rm --platform "linux/$1" \
    -v "$repo:/src:ro" -v "$vkd3d_out/linux-$1:/vkd3d:ro" -e CARGO_TARGET_DIR=/tmp/mds-target \
    "${corpus_mount[@]}" -e TOOLCHAIN="$toolchain" -e MDS_VKD3D_LIB=/vkd3d/lib/libvkd3d-shader.so.1 -w /src "$IMAGE" \
    bash -euc 'rustup toolchain install "$TOOLCHAIN" --profile minimal -c rustfmt -c clippy >/dev/null
               tools/rust/check.sh'
}

case "${1:-all}" in
  amd64|arm64) need_lib "$1"; run "$1" ;;
  all) need_lib amd64; need_lib arm64; run amd64; run arm64 ;;
  *) echo "usage: check-linux.sh [amd64|arm64|all]" >&2; exit 2 ;;
esac
