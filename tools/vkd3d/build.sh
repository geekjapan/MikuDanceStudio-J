#!/usr/bin/env bash
# Build vkd3d-shader 2.1 as a shared library, for mds-shader to load at run time (gate G3).
#
# Usage: build.sh [macos|linux-native|linux-amd64|linux-arm64|windows|all]
#
#   macos        native build on this Mac (needs Xcode tools and bison >= 3, `brew install bison`)
#   linux-amd64, linux-arm64 build in a pinned debian:bookworm container for that platform
#   linux-native build on Linux, retaining configured source in work-linux-native (fresh output only)
#   windows      cross-build with mingw-w64 (x86_64-w64-mingw32) in the same container
#
# Output: ${TMPDIR:-/tmp}/mds-vkd3d/<target>/
#   lib/   libvkd3d-shader.1.dylib, libvkd3d-shader.so.1, or bin/libvkd3d-shader-1.dll
#   bin/   vkd3d-compiler (used by the reflection lane to print d3d-asm listings)
#   share/ the vkd3d LICENSE and COPYING files, which ship with the library (LGPL-2.1), the
#          patches of tools/vkd3d/patches/ applied to it (patches/)
# Point mds-shader at the library with MDS_VKD3D_LIB=<path to the library file>.
set -euo pipefail

VKD3D_URL=https://dl.winehq.org/vkd3d/source/vkd3d-2.1.tar.xz
VKD3D_SHA=7510146aff2adfb4ae07ab890701a607e5ff7c66e57100cfc9f630ec92eeda6a
VK_URL=https://github.com/KhronosGroup/Vulkan-Headers/archive/refs/tags/v1.4.309.tar.gz
VK_SHA=437925ada160d86ed763d29dcb9318c1bb0d024d7deaf77bc7c170b8eb6b6f10
SPV_URL=https://github.com/KhronosGroup/SPIRV-Headers/archive/refs/tags/vulkan-sdk-1.4.309.0.tar.gz
SPV_SHA=a96f8b4f2dfb18f7432e5c523e220ab0075372a9509e0c25fbff21c76af0de7c
IMAGE="debian@sha256:854dd8ab51d62866dbd8f5431d15ce77b12983a2a4a1e1fe43a2395dc7ef9f61" # debian:bookworm

here="$(cd "$(dirname "$0")" && pwd)"
tmp="${TMPDIR:-/tmp}"
root="${MDS_VKD3D_OUT:-${tmp%/}/mds-vkd3d}"
dl="$root/dl"
record="${MDS_VKD3D_RECORD_DIR:-}"
make_flags=()
if [ -n "$record" ]; then
  mkdir -p "$record"
  record="$(cd "$record" && pwd)"
  if [ -n "$(find "$record" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    echo "build.sh: record directory must be empty: $record" >&2
    exit 2
  fi
  make_flags=(V=1)
fi

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }

save_record() {
  local build_status="$1"
  trap - EXIT
  mkdir -p "$record"
  cp -a "$record_work" "$record/work"
  cp -a "$record_prefix" "$record/prefix"
  printf '%s\n' "$build_status" > "$record/build-exit-code"
  exit "$build_status"
}

fetch() { # url sha file
  if [ ! -f "$dl/$3" ] || [ "$(sha256 "$dl/$3")" != "$2" ]; then
    mkdir -p "$dl"
    curl -sSLf -o "$dl/$3.part" "$1"
    mv "$dl/$3.part" "$dl/$3"
  fi
  local got; got="$(sha256 "$dl/$3")"
  [ "$got" = "$2" ] || { echo "build.sh: $3 has sha256 $got, want $2" >&2; exit 1; }
}

# Configure and build vkd3d-shader and vkd3d-compiler only; libvkd3d needs a Vulkan loader and
# is not used. Runs on the host for macOS and inside the container for Linux and Windows.
#   build_in <work dir> <install prefix> [configure args...]
build_in() {
  local work="$1" prefix="$2"; shift 2
  rm -rf "$work" "$prefix"
  mkdir -p "$work/hdr" "$prefix"
  tar -xf "$dl/vkd3d-2.1.tar.xz" -C "$work"
  tar -xzf "$dl/vulkan-headers.tar.gz" -C "$work/hdr" --strip-components=1
  mkdir -p "$work/spv"
  tar -xzf "$dl/spirv-headers.tar.gz" -C "$work/spv" --strip-components=1
  local src="$work/vkd3d-2.1"
  if [ -n "$record" ]; then
    record_work="$work"
    record_prefix="$prefix"
    trap 'save_record $?' EXIT
    cp "$0" "$record/build.sh"
    uname -a > "$record/host.txt"
    if command -v dpkg-query >/dev/null; then dpkg-query -W > "$record/packages.txt"; fi
  fi
  # Our fixes (LGPL-2.1, like vkd3d), applied in name order for every target.
  for p in "$here"/patches/*.patch; do
    [ -e "$p" ] || continue
    patch -p1 -s -d "$src" -i "$p" || { echo "build.sh: $(basename "$p") does not apply" >&2; exit 1; }
  done
  # The tarball ships headers generated from the .idl files. Keep make from regenerating them
  # with widl, which these hosts lack.
  touch "$src"/include/*.h
  ( cd "$src"
    if [ -n "$record" ]; then
      printf '%s\0' ./configure --prefix="$prefix" --disable-tests --disable-static --disable-doxygen-doc \
        --without-ncurses --without-xcb --without-opengl SONAME_LIBVULKAN=unused-libvulkan \
        "CPPFLAGS=-I$work/hdr/include -I$work/spv/include" "$@" > "$record/configure-argv.nul"
      env | LC_ALL=C sort | sed -n '/^\(CC\|CFLAGS\|CPPFLAGS\|LDFLAGS\|AR\|RANLIB\|BISON\|FLEX\)=/p' > "$record/build-environment.txt"
    fi
    ./configure --prefix="$prefix" --disable-tests --disable-static --disable-doxygen-doc \
      --without-ncurses --without-xcb --without-opengl \
      SONAME_LIBVULKAN=unused-libvulkan CPPFLAGS="-I$work/hdr/include -I$work/spv/include" "$@" >"$work/configure.log" 2>&1 \
      || { tail -30 "$work/configure.log"; exit 1; }
    if [ -n "$record" ]; then
      local compiler
      compiler=$(sed -n 's/^CC = //p' Makefile)
      compiler=$(command -v "$compiler")
      printf '%s\n' "$compiler" > "$record/compiler-path.txt"
      sha256 "$compiler" > "$record/compiler-sha256.txt"
      for flag in --version -v -dumpmachine -dumpfullversion -dumpspecs; do
        "$compiler" "$flag" > "$record/compiler${flag}.txt" 2>&1
      done
      for tool in cc1 collect2 lto1 lto-wrapper ld as ar ranlib; do
        local tool_path
        tool_path=$("$compiler" -print-prog-name="$tool")
        tool_path=$(command -v "$tool_path" || true)
        [ -z "$tool_path" ] || { printf '%s %s\n' "$(sha256 "$tool_path")" "$tool_path"; }
      done > "$record/compiler-tools-sha256.txt"
      for tool in bison flex make; do "$tool" --version; done > "$record/generator-versions.txt" 2>&1
    fi
    exe=""; case "$*" in *mingw32*) exe=.exe ;; esac
    # The generated headers that `make all` would build first through BUILT_SOURCES.
    make "${make_flags[@]}" include/private/spirv_grammar.h include/private/vkd3d_version.h \
      libs/vkd3d-shader/hlsl.tab.h libs/vkd3d-shader/preproc.tab.h >"$work/make.log" 2>&1 \
      || { tail -40 "$work/make.log"; exit 1; }
    # Under qemu user emulation (linux-amd64 on an arm64 host) the LTO link cannot use the
    # parallel make's jobserver, so link again without -j when the parallel build fails.
    make "${make_flags[@]}" -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)" libvkd3d-shader.la "vkd3d-compiler$exe" \
      >>"$work/make.log" 2>&1 \
      || make "${make_flags[@]}" libvkd3d-shader.la "vkd3d-compiler$exe" >>"$work/make.log" 2>&1 \
      || { tail -40 "$work/make.log"; exit 1; }
    make "${make_flags[@]}" install-libLTLIBRARIES install-binPROGRAMS lib_LTLIBRARIES=libvkd3d-shader.la \
      "bin_PROGRAMS=vkd3d-compiler$exe" >>"$work/make.log" 2>&1 || { tail -40 "$work/make.log"; exit 1; }
    mkdir -p "$prefix/share/vkd3d" "$prefix/include/vkd3d"
    cp LICENSE COPYING AUTHORS "$prefix/share/vkd3d/"
    mkdir -p "$prefix/share/vkd3d/patches"
    cp "$here"/patches/*.patch "$prefix/share/vkd3d/patches/"
    cp include/vkd3d_shader.h include/vkd3d_types.h "$prefix/include/vkd3d/" )
  rm -f "$prefix"/lib/*.la "$prefix"/bin/*.la
  case "$*" in *mingw32*) copy_mingw_runtime "$prefix/bin" ;; esac
  if [ -n "$record" ] && [[ "$*" == *mingw32* ]]; then
    x86_64-w64-mingw32-objdump -p "$prefix"/bin/*.dll "$prefix"/bin/*.exe > "$record/imports.txt"
  fi
  echo "built $prefix"
  find "$prefix" -name '*vkd3d-shader*' -o -name 'vkd3d-compiler*' | sort
}

# Copy the mingw runtime DLLs that the built DLL and EXE import (libgcc_s, and libwinpthread
# for the posix thread model) next to them, so the library loads on a Windows host without
# MinGW. Asks the same compiler that linked them, then follows the copied DLLs' imports too.
copy_mingw_runtime() { # bin dir
  local bin="$1" queue dll f
  queue=$(ls "$bin"/*.dll "$bin"/*.exe)
  while [ -n "$queue" ]; do
    for dll in $(x86_64-w64-mingw32-objdump -p $queue | sed -n 's/^[[:space:]]*DLL Name: //p' | sort -u); do
      f=$(x86_64-w64-mingw32-gcc -print-file-name="$dll")
      if [ "$f" != "$dll" ] && [ ! -e "$bin/$dll" ]; then cp "$f" "$bin/"; echo "$bin/$dll"; fi
    done > "$bin/.copied"
    queue=$(cat "$bin/.copied")
  done
  rm -f "$bin/.copied"
}

docker_build() { # platform target [configure args...]
  local platform="$1" target="$2"; shift 2
  local args="$*"
  local record_mount=()
  if [ -n "$record" ]; then record_mount=(-v "$record:/record" -e MDS_VKD3D_RECORD_DIR=/record); fi
  docker run --rm "${record_mount[@]}" --platform "$platform" -v "$here:/tools:ro" -v "$dl:/dl:ro" -v "$root:/out" \
    -e MDS_VKD3D_OUT=/out -e IN_CONTAINER=1 "$IMAGE" bash -euc "
      apt-get update -qq >/dev/null
      apt-get install -y -qq --no-install-recommends build-essential bison flex pkg-config \
        libjson-perl ca-certificates xz-utils $( [ "$target" = windows ] && echo gcc-mingw-w64-x86-64 ) >/dev/null
      bash /tools/build.sh --inside $target $args"
}

if [ "${1:-}" = "--inside" ]; then
  # Container entry point: build_in with the downloaded tarballs mounted at /dl.
  shift; target="$1"; shift
  dl=/dl
  build_in "/tmp/work-$target" "/tmp/prefix-$target" "$@"
  rm -rf "/out/$target"; mkdir -p "/out/$target"; cp -a "/tmp/prefix-$target/." "/out/$target/"
  exit 0
fi

if [ "${1:-}" = linux-native ]; then
  [ "$(uname -s)" = Linux ] || { echo "build.sh: linux-native requires Linux" >&2; exit 2; }
  for path in "$root/work-linux-native" "$root/linux-native"; do
    if [ -e "$path" ] || [ -L "$path" ]; then
      echo "build.sh: linux-native requires fresh output; refusing to replace $path" >&2
      exit 2
    fi
  done
fi

fetch "$VKD3D_URL" "$VKD3D_SHA" vkd3d-2.1.tar.xz
fetch "$VK_URL" "$VK_SHA" vulkan-headers.tar.gz
fetch "$SPV_URL" "$SPV_SHA" spirv-headers.tar.gz

macos() {
  [ "$(uname -s)" = Darwin ] || { echo "build.sh: the macos target builds on macOS only" >&2; exit 2; }
  local bison=""
  for b in "${BISON:-}" /opt/homebrew/opt/bison/bin/bison /usr/local/opt/bison/bin/bison bison; do
    [ -n "$b" ] && command -v "$b" >/dev/null && "$b" --version | head -1 | grep -qE ' [3-9]\.' && { bison="$(command -v "$b")"; break; }
  done
  [ -n "$bison" ] || { echo "build.sh: bison >= 3 is required (brew install bison)" >&2; exit 1; }
  build_in "$root/work-macos" "$root/macos" BISON="$bison"
}

case "${1:-host}" in
  host) if [ "$(uname -s)" = Darwin ]; then macos; else docker_build "linux/$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')" "linux-$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')"; fi ;;
  macos) macos ;;
  linux-native) build_in "$root/work-linux-native" "$root/linux-native" ;;
  linux-amd64) docker_build linux/amd64 linux-amd64 ;;
  linux-arm64) docker_build linux/arm64 linux-arm64 ;;
  windows) docker_build "linux/$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')" windows --host=x86_64-w64-mingw32 ;;
  all) macos; docker_build linux/amd64 linux-amd64; docker_build linux/arm64 linux-arm64
       docker_build "linux/$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')" windows --host=x86_64-w64-mingw32 ;;
  *) echo "usage: build.sh [macos|linux-native|linux-amd64|linux-arm64|windows|all]" >&2; exit 2 ;;
esac
