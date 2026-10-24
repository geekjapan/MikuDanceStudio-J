#!/usr/bin/env bash
# Run tools/rust/check.sh in a pinned Linux container.
# Usage: check-linux.sh [amd64|arm64|all]   (default: all)
set -euo pipefail

IMAGE="rust@sha256:48b7f435b8fc6378ce43b44f15e3a47fd8919b2825f835c39bd4bd3da50af5b8" # rust:1-bookworm
repo="$(cd "$(dirname "$0")/../.." && pwd)"
toolchain="$(sed -n 's/^channel *= *"\(.*\)"/\1/p' "$repo/rust/rust-toolchain.toml")"
[ -n "$toolchain" ] || { echo "check-linux.sh: no channel in rust-toolchain.toml" >&2; exit 2; }

run() {
  echo "== linux/$1 =="
  # The repo is read-only; build output goes to a path inside the container.
  docker run --rm --platform "linux/$1" \
    -v "$repo:/src:ro" -e CARGO_TARGET_DIR=/tmp/mds-target \
    -e TOOLCHAIN="$toolchain" -w /src "$IMAGE" \
    bash -euc 'rustup toolchain install "$TOOLCHAIN" --profile minimal -c rustfmt -c clippy >/dev/null
               tools/rust/check.sh'
}

case "${1:-all}" in
  amd64|arm64) run "$1" ;;
  all) run amd64; run arm64 ;;
  *) echo "usage: check-linux.sh [amd64|arm64|all]" >&2; exit 2 ;;
esac
