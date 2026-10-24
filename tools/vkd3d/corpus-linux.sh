#!/usr/bin/env bash
# Build mds-shader in a pinned Linux container and run `mds-shader corpus` there, with the
# vkd3d-shader library from build.sh and the Mesa lavapipe Vulkan driver for --wgpu-check.
#
# Usage: corpus-linux.sh <amd64|arm64> [mds-shader corpus options...]
# Needs: tools/vkd3d/build.sh linux-<arch>, and the corpus at ${TMPDIR:-/tmp}/mds-corpus/ray-mmd.
# Paths print as ray-mmd/... and res/assets/..., as on the host.
set -euo pipefail

IMAGE="rust@sha256:48b7f435b8fc6378ce43b44f15e3a47fd8919b2825f835c39bd4bd3da50af5b8" # rust:1-bookworm
arch="${1:-}"; shift || true
case "$arch" in amd64|arm64) ;; *) echo "usage: corpus-linux.sh <amd64|arm64> [options...]" >&2; exit 2 ;; esac

repo="$(cd "$(dirname "$0")/../.." && pwd)"
tmp="${TMPDIR:-/tmp}"
out="${MDS_VKD3D_OUT:-${tmp%/}/mds-vkd3d}"
corpus="${tmp%/}/mds-corpus/ray-mmd"
lib="$out/linux-$arch/lib/libvkd3d-shader.so.1"
[ -f "$lib" ] || { echo "corpus-linux.sh: $lib missing; run tools/vkd3d/build.sh linux-$arch" >&2; exit 1; }
[ -d "$corpus" ] || { echo "corpus-linux.sh: $corpus missing" >&2; exit 1; }
toolchain="$(sed -n 's/^channel *= *"\(.*\)"/\1/p' "$repo/rust/rust-toolchain.toml")"
# Build output persists between runs, per architecture.
mkdir -p "$out/target-$arch" "$out/cargo-$arch"

docker run --rm --platform "linux/$arch" \
  -v "$repo:/src:ro" -v "$out/linux-$arch:/vkd3d:ro" -v "$corpus:/corpus/ray-mmd:ro" \
  -v "$out/target-$arch:/target" -v "$out/cargo-$arch:/usr/local/cargo/registry" \
  -e CARGO_TARGET_DIR=/target -e TOOLCHAIN="$toolchain" -e MDS_VKD3D_LIB=/vkd3d/lib/libvkd3d-shader.so.1 \
  -w /src "$IMAGE" bash -euc '
    apt-get update -qq >/dev/null
    apt-get install -y -qq --no-install-recommends mesa-vulkan-drivers libvulkan1 >/dev/null 2>&1
    rustup toolchain install "$TOOLCHAIN" --profile minimal >/dev/null 2>&1
    (cd rust && cargo build -q --locked --release -p mds-shader)
    echo "== $(uname -m), $(ldd --version | head -1)"
    # The corpus mount mirrors the host layout, so labels match the host run.
    cd /src && /target/release/mds-shader corpus "$@" /corpus/ray-mmd res/assets
  ' corpus-linux "$@"
