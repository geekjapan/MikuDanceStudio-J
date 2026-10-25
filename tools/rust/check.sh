#!/usr/bin/env bash
# Format, lint, and test the Rust workspace. Exit non-zero on the first failure.
set -euo pipefail

cd "$(dirname "$0")/../../rust"

cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test --no-run
# Test runs from parallel worktrees share the GPU; under heavy load the corpus
# tests got whole runs killed. Builds stay parallel, runs take turns.
lock="${TMPDIR:-/tmp}/mds-rust-test.lock"
if command -v lockf >/dev/null; then
  lockf -k "$lock" cargo test
elif command -v flock >/dev/null; then
  flock "$lock" cargo test
else
  cargo test
fi
