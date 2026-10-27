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
  # Reject ambient make/compiler injection before invoking any producer tool.
  for name in MAKEFILES MAKEFLAGS GNUMAKEFLAGS MFLAGS CPPFLAGS CFLAGS CXXFLAGS LDFLAGS \
      AR RANLIB BISON FLEX LD AS CONFIG_SITE CONFIG_SHELL BASH_ENV ENV \
      PKG_CONFIG PKG_CONFIG_PATH PKG_CONFIG_LIBDIR PKG_CONFIG_SYSROOT_DIR \
      CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH OBJC_INCLUDE_PATH GCC_EXEC_PREFIX COMPILER_PATH LIBRARY_PATH; do
    if [ -n "${!name:-}" ]; then
      printf 'build.sh: unsupported producer environment: %s\n' "$name" >&2
      printf '2\n' > "$record/build-exit-code"
      printf '{"schema":"mds-vkd3d-fresh-producer-v1","status":"failure","exit_code":2,"stages":[],"error":"unsupported producer environment"}\n' > "$record/producer-receipt.json"
      exit 2
    fi
    unset "$name"
  done
  export CONFIG_SITE=/dev/null
  case "${CC:-}" in ''|/usr/bin/gcc-13) ;; *) echo 'build.sh: unsupported producer CC' >&2; printf '2\n' > "$record/build-exit-code"; exit 2 ;; esac
  case "${1:-}" in windows|linux-native|--inside) ;; *) echo 'build.sh: unsupported recorded producer target' >&2; printf '2\n' > "$record/build-exit-code"; exit 2 ;; esac
fi

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }

save_record() {
  local build_status="$1"
  trap - EXIT
  mkdir -p "$record"
  if [ -z "${record_work:-}" ] && [ -f "$record/build-exit-code" ]; then exit "$build_status"; fi
  producer_stage final "$build_status" || build_status=1
  if [ -d "$record_work" ]; then
    python3 -I - "$record" "$record_work" <<'RETAIN_PY'
import json, shutil, sys
from pathlib import Path
record, work = map(Path, sys.argv[1:])
receipt = json.loads((record / 'producer-receipt.json').read_text())
frozen = next((stage['files'] for stage in receipt['stages'] if stage['stage'] == 'frozen'), None)
if frozen is None:
    shutil.copytree(work, record / 'work', symlinks=True)
else:
    # Keep frozen inputs and logs; libtool's output symlinks are not producer inputs.
    for name in [item['path'] for item in frozen] + ['make.log', 'configure.log', 'vkd3d-2.1/config.log']:
        source = work / name
        if source.is_file():
            target = record / 'work' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
RETAIN_PY
  fi
  if [ -d "$record_prefix" ]; then cp -a "$record_prefix" "$record/prefix"; fi
  printf '%s\n' "$build_status" > "$record/build-exit-code"
  exit "$build_status"
}


# A receipt is evidence of this finite producer, not an attestation of its runner.
producer_stage() {
  [ -n "$record" ] || return 0
  python3 -I - "$record" "$record_work" "$here" "$dl" "$1" "${2:-}" <<'PRODUCER_PY'
import hashlib, json, os, sys
from pathlib import Path
record, work, here, dl = map(Path, sys.argv[1:5])
stage, status = sys.argv[5:7]
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def manifest():
    result = []
    for directory, dirs, files in os.walk(work, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            if path.is_symlink():
                raise RuntimeError('symlink producer input: ' + str(path))
            if name in files and not name.endswith('.log'):
                result.append({'path': path.relative_to(work).as_posix(), 'sha256': digest(path),
                               'executable': bool(path.stat().st_mode & 0o111)})
    return sorted(result, key=lambda item: item['path'])
receipt_path = record / 'producer-receipt.json'
if stage == 'final' and not receipt_path.exists():
    receipt_path.write_text(json.dumps({'schema': 'mds-vkd3d-fresh-producer-v1', 'status': 'failure',
                                'exit_code': int(status), 'stages': []}) + '\n')
    sys.exit(0)
receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {
    'schema': 'mds-vkd3d-fresh-producer-v1', 'status': 'incomplete',
    'recipe_sha256': digest(here / 'build.sh'),
    'archives': {name: digest(dl / name) for name in
                 ('vkd3d-2.1.tar.xz', 'vulkan-headers.tar.gz', 'spirv-headers.tar.gz')},
    'patches': {p.name: digest(p) for p in sorted((here / 'patches').glob('*.patch'))},
    'original_work_root': str(work), 'retained_work_root': 'work',
    'include_roots': [{'original': str(work / name), 'retained': 'work/' + name} for name in
                      ('vkd3d-2.1', 'vkd3d-2.1/include', 'vkd3d-2.1/include/private',
                       'hdr/include', 'spv/include', 'vkd3d-2.1/libs/vkd3d-shader')],
    'stages': []}
try:
    if stage == 'final':
        receipt['status'] = 'success' if status == '0' else 'failure'
        receipt['exit_code'] = int(status)
        receipt['make_commands'] = [json.loads(line) for line in (record / 'make-commands.jsonl').read_text().splitlines()] if (record / 'make-commands.jsonl').exists() else []
    else:
        if work.resolve() != work or any((work / name).resolve() != work / name for name in
                                       ('vkd3d-2.1', 'hdr/include', 'spv/include')):
            raise RuntimeError('producer roots must be physical and contained')
        stages = receipt['stages']
        if stage in ('compiled', 'installed'):
            frozen = next(item['files'] for item in stages if item['stage'] == 'frozen')
            current = []
            for item in frozen:
                path = work / item['path']
                if path.resolve() != path or not path.is_file():
                    raise RuntimeError('missing or symlink frozen producer input: ' + item['path'])
                current.append({'path': item['path'], 'sha256': digest(path),
                                'executable': bool(path.stat().st_mode & 0o111)})
        else:
            current = manifest()
        if stage == 'frozen':
            configured = next(item['files'] for item in stages if item['stage'] == 'configured')
            generated = {'vkd3d-2.1/' + name for name in (
                'include/private/spirv_grammar.h', 'include/private/vkd3d_version.h',
                'libs/vkd3d-shader/hlsl.tab.c', 'libs/vkd3d-shader/hlsl.tab.h',
                'libs/vkd3d-shader/hlsl.yy.c', 'libs/vkd3d-shader/preproc.tab.c',
                'libs/vkd3d-shader/preproc.tab.h', 'libs/vkd3d-shader/preproc.yy.c')}
            actual = {item['path']: item for item in current}
            if set(actual) - {item['path'] for item in configured} - generated:
                raise RuntimeError('unexpected input added during generation')
            if any(actual.get(item['path']) != item for item in configured if item['path'] not in generated):
                raise RuntimeError('non-generated producer input changed during generation')
        if stage in ('compiled', 'installed'):
            frozen = next(item['files'] for item in stages if item['stage'] == 'frozen')
            actual = {item['path']: item for item in current}
            if any(actual.get(item['path']) != item for item in frozen):
                raise RuntimeError('frozen producer input changed during ' + stage)
            current = frozen
        receipt['stages'].append({'stage': stage, 'files': current})
except Exception as error:
    receipt['status'] = 'failure'
    receipt['error'] = str(error)
    raise
finally:
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
PRODUCER_PY
}

producer_make() {
  if [ -n "$record" ]; then
    python3 -I - "$record/make-commands.jsonl" "$@" <<'MAKE_ARGV_PY'
import json, sys
with open(sys.argv[1], 'a') as stream:
    stream.write(json.dumps(sys.argv[2:]) + '\n')
MAKE_ARGV_PY
  fi
  make "$@"
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
  if [ -n "$record" ]; then
    record_work="$work"
    record_prefix="$prefix"
    trap 'save_record $?' EXIT
    for path in "$work" "$prefix"; do
      [ ! -e "$path" ] && [ ! -L "$path" ] || { echo "build.sh: producer output must be fresh: $path" >&2; exit 2; }
    done
  fi
  rm -rf "$work" "$prefix"
  mkdir -p "$work/hdr" "$prefix"
  if [ -n "$record" ]; then
    work="$(cd "$work" && pwd -P)"
    prefix="$(cd "$prefix" && pwd -P)"
    record_work="$work"
    record_prefix="$prefix"
  fi
  tar -xf "$dl/vkd3d-2.1.tar.xz" -C "$work"
  tar -xzf "$dl/vulkan-headers.tar.gz" -C "$work/hdr" --strip-components=1
  mkdir -p "$work/spv"
  tar -xzf "$dl/spirv-headers.tar.gz" -C "$work/spv" --strip-components=1
  local src="$work/vkd3d-2.1"
  if [ -n "$record" ]; then
    record_work="$work"
    record_prefix="$prefix"
    cp "$0" "$record/build.sh"
    uname -a > "$record/host.txt"
    if command -v dpkg-query >/dev/null; then dpkg-query -W > "$record/packages.txt"; fi
  fi
  # Our fixes (LGPL-2.1, like vkd3d), applied in name order for every target.
  for p in "$here"/patches/*.patch; do
    [ -e "$p" ] || continue
    patch -p1 -s -d "$src" -i "$p" || { echo "build.sh: $(basename "$p") does not apply" >&2; exit 1; }
  done
  producer_stage prepared
  # The tarball ships headers generated from the .idl files. Keep make from regenerating them
  # with widl, which these hosts lack.
  touch "$src"/include/*.h
  ( cd "$src"
    if [ -n "$record" ]; then
      # Configure and all make/generator children receive only this audited environment.
      for name in $(compgen -e); do
        case "$name" in PATH|HOME|TMPDIR|LANG|LC_ALL|CC|CONFIG_SITE) ;; *) unset "$name" ;; esac
      done
    fi
    local configure_flags=()
    if [ -n "$record" ]; then
      configure_flags=(--disable-dependency-tracking)
      make_flags=(-f "$src/Makefile" V=1)
    fi
    if [ -n "$record" ]; then
      printf '%s\0' ./configure "${configure_flags[@]}" --prefix="$prefix" --disable-tests --disable-static --disable-doxygen-doc \
        --without-ncurses --without-xcb --without-opengl SONAME_LIBVULKAN=unused-libvulkan \
        "CPPFLAGS=-I$work/hdr/include -I$work/spv/include" "$@" > "$record/configure-argv.nul"
      env | LC_ALL=C sort | sed -n '/^\(CONFIG_SITE\|CC\|CFLAGS\|CPPFLAGS\|LDFLAGS\|AR\|RANLIB\|BISON\|FLEX\)=/p' > "$record/build-environment.txt"
    fi
    ./configure "${configure_flags[@]}" --prefix="$prefix" --disable-tests --disable-static --disable-doxygen-doc \
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
    producer_stage configured
    exe=""; case "$*" in *mingw32*) exe=.exe ;; esac
    local generated_flags=()
    if [ -n "$record" ]; then
      generated_flags=(libs/vkd3d-shader/hlsl.tab.c libs/vkd3d-shader/hlsl.yy.c
                       libs/vkd3d-shader/preproc.tab.c libs/vkd3d-shader/preproc.yy.c)
    fi
    # The generated headers that `make all` would build first through BUILT_SOURCES.
    producer_make "${make_flags[@]}" include/private/spirv_grammar.h include/private/vkd3d_version.h \
      libs/vkd3d-shader/hlsl.tab.h libs/vkd3d-shader/preproc.tab.h "${generated_flags[@]}" >"$work/make.log" 2>&1 \
      || { tail -40 "$work/make.log"; exit 1; }
    producer_stage frozen
    # Under qemu user emulation (linux-amd64 on an arm64 host) the LTO link cannot use the
    # parallel make's jobserver, so link again without -j when the parallel build fails.
    producer_make "${make_flags[@]}" -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)" libvkd3d-shader.la "vkd3d-compiler$exe" \
      >>"$work/make.log" 2>&1 \
      || producer_make "${make_flags[@]}" libvkd3d-shader.la "vkd3d-compiler$exe" >>"$work/make.log" 2>&1 \
      || { tail -40 "$work/make.log"; exit 1; }
    producer_stage compiled
    producer_make "${make_flags[@]}" install-libLTLIBRARIES install-binPROGRAMS lib_LTLIBRARIES=libvkd3d-shader.la \
      "bin_PROGRAMS=vkd3d-compiler$exe" >>"$work/make.log" 2>&1 || { tail -40 "$work/make.log"; exit 1; }
    producer_stage installed
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
  local record_packages=""
  if [ -n "$record" ] && [ "$target" = windows ]; then record_packages=python3; fi
  local record_mount=()
  if [ -n "$record" ]; then record_mount=(-v "$record:/record" -e MDS_VKD3D_RECORD_DIR=/record); fi
  docker run --rm "${record_mount[@]}" --platform "$platform" -v "$here:/tools:ro" -v "$dl:/dl:ro" -v "$root:/out" \
    -e MDS_VKD3D_OUT=/out -e IN_CONTAINER=1 "$IMAGE" bash -euc "
      apt-get update -qq >/dev/null
      apt-get install -y -qq --no-install-recommends build-essential bison flex pkg-config \
        libjson-perl ca-certificates xz-utils $record_packages $( [ "$target" = windows ] && echo gcc-mingw-w64-x86-64 ) >/dev/null
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

if [ -n "$record" ]; then
  record_work="${record_work:-}"
  record_prefix="${record_prefix:-}"
  trap 'save_record $?' EXIT
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
