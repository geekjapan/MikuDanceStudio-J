#!/usr/bin/env bash
# Usage: tools/orchestrate/integrate.sh <id>
# Merges BASE (default origin/main) into the finished slice branch w2-<id> and
# runs the gates. On success the branch merges into main without conflicts.
#   1. ownership: check-ownership.sh
#   2. Cargo.lock: on a conflict take the base's lock and let cargo add the
#      slice's packages back. Fail if a package the slice added to the lock
#      now resolves to another version than the one the slice tested.
#   3. tools/rust/check.sh, and scripts/format_sources.py --check when the
#      slice changed src/ or include/.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
[ $# -eq 1 ] || die "usage: integrate.sh <id>"
id=$1
wt=$(worktree "$id")
[ -d "$wt" ] || die "no worktree $wt"
cd "$wt"
[ -z "$(git status --porcelain)" ] || die "commit or discard the changes in $wt first"
if [ -z "${BASE:-}" ]; then git fetch -q origin main; fi
base=${BASE:-origin/main}

"$main_root/tools/orchestrate/check-ownership.sh" "$id"

versions() { awk '/^name = /{ n = $3 } /^version = /{ print n, $3 }' | tr -d '"' | sort -u; }
names() { cut -d' ' -f1 | sort -u; }
slice_lock=$(git show HEAD:rust/Cargo.lock | versions)
fork=$(git merge-base HEAD "$base")
introduced=$(comm -23 <(names <<<"$slice_lock") <(git show "$fork:rust/Cargo.lock" | versions | names))
slice_head=$(git rev-parse HEAD)

only() { awk 'NR == FNR { keep[$1]; next } $1 in keep' <(echo "$introduced") -; }
if ! git merge-base --is-ancestor "$base" HEAD; then
  if ! git merge -q --no-ff --no-commit "$base"; then
    conflicts=$(git diff --name-only --diff-filter=U)
    if [ "$conflicts" != rust/Cargo.lock ]; then
      git merge --abort
      die "conflicts outside Cargo.lock: $(echo $conflicts)"
    fi
    git checkout --theirs rust/Cargo.lock
  fi
  (cd rust && cargo metadata -q --format-version 1 >/dev/null)
  merged_lock=$(versions <rust/Cargo.lock)
  tested=$(comm -23 <(only <<<"$slice_lock") <(only <<<"$merged_lock"))
  if [ -n "$tested" ]; then
    git merge --abort
    die "after the merge cargo picks $(comm -13 <(only <<<"$slice_lock") <(only <<<"$merged_lock") | paste -sd, -)" \
      "but $id was tested with $(paste -sd, - <<<"$tested"); pin it or retest"
  fi
  git add rust/Cargo.lock
  git commit -q --no-edit
fi
(cd rust && cargo metadata -q --locked --format-version 1 >/dev/null)

tools/rust/check.sh
if [ -n "$(git diff --name-only "$fork" "$slice_head" -- src include)" ]; then
  uvx --from clang-format==23.1.0 python3 -I scripts/format_sources.py --check --clang-format clang-format
fi
echo "integrated: w2-$id at $(git rev-parse --short HEAD); push it and merge the PR"
