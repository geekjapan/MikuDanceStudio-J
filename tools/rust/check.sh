#!/usr/bin/env bash
# Format, lint, and test the Rust workspace. Exit non-zero on the first failure.
set -euo pipefail

cd "$(dirname "$0")/../../rust"

cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
