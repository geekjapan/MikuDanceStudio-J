# Shared by the wave 2 scripts. Source it; do not run it.
root=$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)
# The main checkout, even when called from a slice worktree.
main_root=$(dirname "$(git -C "$root" rev-parse --path-format=absolute --git-common-dir)")
slices=${SLICES:-$main_root/tools/orchestrate/slices.tsv}

die() { echo "$(basename "$0"): $*" >&2; exit 1; }

# field <id> <column>: columns are 2 wave, 3 depends, 4 host, 5 model, 6 license, 7 owned.
field() {
  local v
  v=$(awk -F'\t' -v id="$1" -v c="$2" '!/^#/ && $1 == id { print $c; found = 1 } END { exit !found }' "$slices") ||
    die "no slice '$1' in $slices"
  echo "$v"
}

worktree() { echo "$main_root/.claude/worktrees/w2-$1"; }
