#!/bin/sh
# Build the C++ pose chain against the real sources and write its dump of the
# cases in tests/fixtures/pose_cases.txt.
# Usage: rust/crates/mds-kinect/tests/cxx/run.sh [out]   (default: stdout)
# Needs clang++ with AddressSanitizer and cargo (for the math library).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../../../.." && pwd)
fixtures=$here/../fixtures
out=${TMPDIR:-/tmp}/kinect_check
mkdir -p "$out"
cargo build --quiet --release --offline --manifest-path "$here/ffi/Cargo.toml" \
  --target-dir "$out/target"
# The x64 layout of the Windows build: _M_X64/_WIN64 select it, and
# -fshort-wchar gives the 2-byte wchar_t the layout asserts. MSVC x64 rounds
# every float operation, so no multiply-add may be fused.
flags="-std=c++17 -O2 -g -fsanitize=address -ffp-contract=off -fno-strict-aliasing
  -fshort-wchar -D_M_X64 -D_WIN64 -Wno-unknown-pragmas -I$here/shim -I$root/include
  -include $here/shim/crt_math.h"
objs=
for src in "$here/harness.cpp" "$root/src/model/model_init.cpp" \
    "$root/src/features/audio_pose_helpers.cpp" "$root/src/features/dialog_helpers.cpp"; do
  obj="$out/$(basename "$src" .cpp).o"
  # shellcheck disable=SC2086
  ${CXX:-clang++} $flags -c "$src" -o "$obj"
  objs="$objs $obj"
done
# shellcheck disable=SC2086
${CXX:-clang++} -fsanitize=address $objs "$out/target/release/libkinect_check_ffi.a" \
  -o "$out/pose_check"
ASAN_OPTIONS=detect_leaks=0 "$out/pose_check" "$fixtures/pose_cases.txt" >"${1:-/dev/stdout}"
