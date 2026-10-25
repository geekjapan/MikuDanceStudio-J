#!/bin/sh
# Build the real WAV loading sources against shim headers and dump what they
# compute for every *.wav in a directory.
# Usage: tools/wave_check/run.sh <wav-dir>   (the dump goes to stdout)
# Needs clang++ (Apple clang or LLVM clang 16+).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
out=${TMPDIR:-/tmp}/wave_check
mkdir -p "$out"
# -fshort-wchar matches the 2-byte Windows wchar_t; _M_X64/_WIN64 pick the
# x64 layout of the audio context (the C++ computes the waveform in x64 floats).
${CXX:-clang++} -std=c++17 -O0 -g -w -fsanitize=address \
  -fshort-wchar -D_M_X64 -D_WIN64 -I"$here/shim" -I"$root/include" \
  "$here/wave_check.cpp" \
  "$root/src/media/wave_data_chunk.cpp" \
  "$root/src/media/wave_audio.cpp" \
  "$root/src/app/subsystem_init.cpp" \
  -o "$out/wave_check"
"$out/wave_check" "$@"
