#!/bin/sh
# Build and run the keyframe-pool check against the real sources.
# Usage: tools/keypool_check/run.sh [depth]   (default depth 4)
# Needs clang++ with AddressSanitizer (Apple clang 21 / LLVM clang 16+).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
out=${TMPDIR:-/tmp}/keypool_check
mkdir -p "$out"
# x64 layout on a non-Windows host: _M_X64/_WIN64 pick the x64 ABI and
# -fshort-wchar matches the 2-byte Windows wchar_t the layout asserts.
${CXX:-clang++} -std=c++17 -O2 -g -fsanitize=address -fsanitize-recover=address \
  -fshort-wchar -D_M_X64 -D_WIN64 -I"$here/shim" -I"$root/include" \
  "$here/keypool_check.cpp" \
  "$root/src/model/key_registrars.cpp" \
  "$root/src/model/model_keyframe_edit.cpp" \
  "$root/src/model/model_init.cpp" \
  -o "$out/keypool_check"
ASAN_OPTIONS=halt_on_error=0:detect_leaks=0:suppress_equal_pcs=0 \
  "$out/keypool_check" "$@" 2>"$out/asan.log"
