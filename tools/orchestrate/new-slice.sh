#!/usr/bin/env bash
# Usage: tools/orchestrate/new-slice.sh <id>
# Creates the worktree for slice <id> on branch w2-<id> from BASE (default
# origin/main) and prints its path. Running it again prints the same path.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
[ $# -eq 1 ] || die "usage: new-slice.sh <id>"
id=$1
wt=$(worktree "$id")
host=$(field "$id" 4)
if [ -d "$wt" ]; then echo "$wt"; exit 0; fi

if [ -z "${BASE:-}" ]; then git -C "$main_root" fetch -q origin main; fi
base=${BASE:-origin/main}
deps=$(field "$id" 3)
if [ "$deps" != - ]; then
  for d in ${deps//,/ }; do
    field "$d" 1 >/dev/null
    git -C "$main_root" log --merges --format=%s "$base" | grep "/w2-$d\$" >/dev/null ||
      die "slice $d is not merged into $base yet"
  done
fi
# The Windows host runs one slice at a time.
if [ "$host" = windows ]; then
  for other in $(awk -F'\t' '!/^#/ && $4 == "windows" { print $1 }' "$slices"); do
    [ "$other" = "$id" ] || [ ! -d "$(worktree "$other")" ] || die "windows slice $other is still open"
  done
fi

if git -C "$main_root" show-ref -q --verify "refs/heads/w2-$id"; then
  git -C "$main_root" worktree add -q "$wt" "w2-$id"
else
  git -C "$main_root" worktree add -q -b "w2-$id" "$wt" "$base"
fi
echo "$wt"
