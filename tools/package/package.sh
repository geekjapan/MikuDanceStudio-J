#!/usr/bin/env bash
# Build the mds-app package for macOS (here) or Linux (in a container) and write
# <out>/mds-app-<VERSION>-<commit>-<target>.tar.gz (docs/PACKAGING.md).
#
# Usage: package.sh <macos|linux-arm64|linux-amd64>
#   out: MDS_PACKAGE_OUT, else ${TMPDIR:-/tmp}/mds-package. The vkd3d-shader build is
#   MDS_VKD3D_OUT, else <out>/vkd3d (tools/vkd3d/build.sh runs when it is missing).
set -euo pipefail

IMAGE="rust@sha256:48b7f435b8fc6378ce43b44f15e3a47fd8919b2825f835c39bd4bd3da50af5b8" # rust:1-bookworm
target="${1:-}"
case "$target" in
  macos) lib=libvkd3d-shader.1.dylib ;;
  linux-arm64|linux-amd64) lib=libvkd3d-shader.so.1 ;;
  *) echo "usage: package.sh <macos|linux-arm64|linux-amd64>" >&2; exit 2 ;;
esac
repo="$(cd "$(dirname "$0")/../.." && pwd)"
tmp="${TMPDIR:-/tmp}"
out="${MDS_PACKAGE_OUT:-${tmp%/}/mds-package}"
export MDS_VKD3D_OUT="${MDS_VKD3D_OUT:-$out/vkd3d}"
mkdir -p "$out"

[ -f "$MDS_VKD3D_OUT/$target/lib/$lib" ] || "$repo/tools/vkd3d/build.sh" "$target"
python3 -I "$repo/tools/package/licenses.py"
if [ -n "$(git -C "$repo" status --porcelain -- licenses)" ]; then
  echo "package.sh: licenses/ differs from what licenses.py writes; commit it first" >&2
  git -C "$repo" status --short -- licenses | head >&2
  exit 1
fi

name="mds-app-$(tr -d '[:space:]' <"$repo/VERSION")-$(git -C "$repo" rev-parse --short HEAD)-$target"
target_dir="$out/target-$target"
case "$target" in
  macos)
    (cd "$repo/rust" && CARGO_TARGET_DIR="$target_dir" cargo build --release --locked -p mds-app) ;;
  linux-*)
    arch="${target#linux-}"
    toolchain="$(sed -n 's/^channel *= *"\(.*\)"/\1/p' "$repo/rust/rust-toolchain.toml")"
    mkdir -p "$target_dir" "$out/cargo-$arch"
    # Bullet needs clang (mds-bullet-sys/build.rs); cpal links ALSA.
    docker run --rm --platform "linux/$arch" -v "$repo:/src:ro" -v "$target_dir:/target" \
      -v "$out/cargo-$arch:/usr/local/cargo/registry" -e CARGO_TARGET_DIR=/target \
      -e TOOLCHAIN="$toolchain" -e CC=clang -e CXX=clang++ -w /src/rust "$IMAGE" bash -euc '
        apt-get update -qq >/dev/null
        apt-get install -y -qq --no-install-recommends clang pkg-config libasound2-dev >/dev/null 2>&1
        rustup toolchain install "$TOOLCHAIN" --profile minimal >/dev/null 2>&1
        cargo build --release --locked -p mds-app
        echo "built on $(uname -m), $(ldd --version | head -1)"' ;;
esac

stage="$out/stage/$name"
rm -rf "$stage"; mkdir -p "$stage"
cp "$target_dir/release/mds-app" "$stage/"
cp -L "$MDS_VKD3D_OUT/$target/lib/$lib" "$stage/$lib"
cp -R "$repo/licenses" "$stage/licenses"
cat >"$stage/README.txt" <<EOF
MikuDanceStudio (mds-app), $target, built from MikuDanceStudio-J $(git -C "$repo" rev-parse HEAD).

  ./mds-app [<file.pmm>]                                 the editor window
  ./mds-app --frame-dump <file.pmm> <out-dir> <frame>... PNG frames, no window

$lib beside mds-app is vkd3d-shader 2.1, which MME effects need. licenses/ has the license
texts (licenses/README.md); licenses/FORK.md says which parts are MIT and which are license
pending. Build and runtime notes: docs/PACKAGING.md of the repository.
EOF
tar -C "$out/stage" -czf "$out/$name.tar.gz" "$name"
echo "archive $out/$name.tar.gz $(wc -c <"$out/$name.tar.gz" | tr -d ' ') bytes"
tar -tzvf "$out/$name.tar.gz" | grep -v '/licenses/.*/' | awk '{print "  " $5 "\t" $NF}'
