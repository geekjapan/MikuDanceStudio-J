#!/bin/sh
# Build tools/skin_check against the real loaders and skinning sources and
# write its dump of the cases in tests/fixtures/rust/skin/cases.txt.
# Usage: tools/skin_check/run.sh [out]   (default: stdout)
# Needs clang++ with AddressSanitizer and cargo (for the math library).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
out=${TMPDIR:-/tmp}/skin_check
mkdir -p "$out"
cargo build --quiet --release --offline --manifest-path "$here/ffi/Cargo.toml" \
  --target-dir "$out/target"
# The x64 layout of the Windows build: _M_X64/_WIN64 select it, and
# -fshort-wchar gives the 2-byte wchar_t the layout asserts. MSVC x64 rounds
# every float operation, so no multiply-add may be fused.
flags="-std=c++17 -O2 -g -fsanitize=address -ffp-contract=off -fno-strict-aliasing
  -fshort-wchar -D_M_X64 -D_WIN64 -Wno-unknown-pragmas -I$here/shim -I$root/include"
objs=
for src in "$here/skin_check.cpp" "$root/src/model/model_init.cpp" \
    "$root/src/model/pmd_load.cpp" "$root/src/model/pmx_load.cpp" \
    "$root/src/model/model_skinning.cpp" "$root/src/model/morph_apply.cpp"; do
  obj="$out/$(basename "$src" .cpp).o"
  extra=
  [ "$(basename "$src")" = morph_apply.cpp ] && extra="-include $here/shim/crt_math.h"
  # shellcheck disable=SC2086
  ${CXX:-clang++} $flags $extra -c "$src" -o "$obj"
  objs="$objs $obj"
done
# shellcheck disable=SC2086
${CXX:-clang++} -fsanitize=address $objs "$out/target/release/libskin_check_ffi.a" \
  -o "$out/skin_check"
ASAN_OPTIONS=detect_leaks=0 "$out/skin_check" "$root/tests/fixtures/rust" \
  "$root/tests/fixtures/rust/skin/cases.txt" >"${1:-/dev/stdout}"
