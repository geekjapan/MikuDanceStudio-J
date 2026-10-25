#!/bin/sh
# Build the oracle for the PMM 0001 reader of rust/crates/mds-formats and
# write its dump of each oracle fixture in tests/fixtures/rust/pmm1.
#
# Usage: tools/pmm1_check/run.sh [out dir]
#   (default out dir: tests/fixtures/rust/pmm1/expected)
# Env:   PMM1_NEXT  commit of origin/next to build the portable reader from
#                   (default 9ef4817)
# Needs: cmake and a C++17 compiler (the build_l1.sh requirements).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
fixtures=$root/tests/fixtures/rust/pmm1
out=${1:-$fixtures/expected}
next=${PMM1_NEXT:-9ef4817}

built=$("$root/tools/oracle/build_l1.sh" "$next")
bin=$(echo "$built" | sed -n 's/^binary: //p')
build=$(dirname "$bin")
src=$(dirname "$build")/src
lib=$(find "$build" -name libmikudancestudio_formats.a | head -n 1)
[ -n "$lib" ] || { echo "pmm1_check: formats library not found under $build" >&2; exit 1; }

tool=${TMPDIR:-/tmp}/pmm1_dump
${CXX:-c++} -std=c++17 -O1 -I"$src/include" "$here/dump.cpp" "$lib" -o "$tool"

mkdir -p "$out"
# v1_noparent.pmm takes the branch of tail gate 9 where main and the portable
# reader differ, and v1_edge.pmm holds records the portable dump does not
# model; both are checked by the Rust tests alone.
for scene in v1_rig v1_scene v1_multi; do
  "$tool" "$fixtures" "$scene.pmm" >"$out/$scene.dump"
  echo "$scene.dump $(shasum -a 256 "$out/$scene.dump" | cut -d' ' -f1)"
done
