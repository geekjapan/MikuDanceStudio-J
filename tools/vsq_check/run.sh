#!/bin/sh
# Build the VSQ check against the real sources and run it on every fixture.
# Usage: tools/vsq_check/run.sh [--update]
#   Without --update the dumps are compared with the committed ones in
#   tests/fixtures/rust/vsq/expected and any difference fails. With --update
#   they are rewritten.
# Needs clang++ (Apple clang 21 / LLVM clang 16+; -ftrivial-auto-var-init).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
fix=$root/tests/fixtures/rust/vsq
out=${TMPDIR:-/tmp}/vsq_check
rm -rf "$out/work" "$out/got"
mkdir -p "$out/work" "$out/got"

# ReadBeWord and ReadFixedString live in a file with the whole app behind it;
# lift just those two bodies so the check still runs the real code.
{
  echo '#include <Windows.h>'
  echo '#include <io.h>'
  echo 'namespace mikudancestudio {'
  awk '/^int (ReadBeWord|ReadFixedString)\(/{p=1} p{print} p&&/^}/{p=0}' \
    "$root/src/model/model_query_helpers.cpp"
  echo '}'
} > "$out/read_helpers.cpp"

# MSVC x64 evaluates in SSE without fused multiply-add, and a local that is
# read before it is written holds zero here so the run is repeatable.
${CXX:-clang++} -std=c++17 -O1 -g -fshort-wchar -D_M_X64 -D_WIN64 \
  -ffp-contract=off -ftrivial-auto-var-init=zero -Wno-format-security \
  -I"$here/shim" -I"$root/include" \
  "$here/vsq_check.cpp" "$root/src/io/vsq_load.cpp" "$out/read_helpers.cpp" \
  -o "$out/vsq_check"

# cases.tsv: <file> <model>, written by the fixture generator.
while read -r file model; do
  case $file in ''|'#'*) continue ;; esac
  stem=${file%.vsq}
  cp "$fix/$file" "$out/work/$file"
  for lang in jp en; do
    "$out/vsq_check" "$out/work/$file" "$model" "$lang" \
      "$out/got/$stem@$model.$lang"
  done
  # The .txt does not depend on the language; keep one.
  cmp "$out/got/$stem@$model.jp.txt" "$out/got/$stem@$model.en.txt"
  mv "$out/got/$stem@$model.jp.txt" "$out/got/$stem@$model.txt"
  rm "$out/got/$stem@$model.en.txt"
done < "$fix/cases.tsv"

if [ "${1:-}" = "--update" ]; then
  rm -rf "$fix/expected"
  mkdir "$fix/expected"
  cp "$out/got/"* "$fix/expected/"
  echo "updated $(ls "$fix/expected" | wc -l | tr -d ' ') files in tests/fixtures/rust/vsq/expected"
else
  diff -r "$fix/expected" "$out/got"
  echo "vsq_check: $(ls "$out/got" | wc -l | tr -d ' ') files match tests/fixtures/rust/vsq/expected"
fi
