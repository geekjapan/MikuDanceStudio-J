#!/usr/bin/env bash
# Usage: tools/orchestrate/check-ownership.sh <id>
# Fails if the slice worktree changed a path outside its owned set, counting
# commits since it left the base, uncommitted edits, and untracked files.
# rust/Cargo.lock is always allowed. BASE defaults to origin/main.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
[ $# -eq 1 ] || die "usage: check-ownership.sh <id>"
id=$1
wt=$(worktree "$id")
[ -d "$wt" ] || die "no worktree $wt"
IFS=, read -r -a owned <<<"$(field "$id" 7)"
base=$(git -C "$wt" merge-base HEAD "${BASE:-origin/main}")

bad=0
while IFS= read -r f; do
  [ -n "$f" ] && [ "$f" != rust/Cargo.lock ] || continue
  ok=0
  for p in "${owned[@]}"; do
    case $p in
      */) [[ $f == "$p"* ]] && ok=1 ;;
      *) [ "$f" = "$p" ] && ok=1 ;;
    esac
  done
  [ $ok = 1 ] || { echo "not owned by $id: $f" >&2; bad=1; }
done < <(git -C "$wt" diff --name-only "$base"; git -C "$wt" ls-files --others --exclude-standard)
[ $bad = 0 ] || exit 1
echo "ownership ok: $id"
