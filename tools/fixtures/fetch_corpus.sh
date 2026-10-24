#!/usr/bin/env bash
# Fetch the ray-mmd corpus at a pinned commit, outside the repository.
#
#   tools/fixtures/fetch_corpus.sh
#
# Clones https://github.com/ray-cast/ray-mmd at commit
# 218a91cd1c53f49850b2772ebbcb98bf258e75b1 into ${TMPDIR:-/tmp}/mds-corpus/ray-mmd,
# then verifies that HEAD is that commit. A checkout that is already at the
# commit is left alone. Prints the corpus path on success; exits 1 on any
# mismatch. The corpus is never written inside the repository.
set -euo pipefail

URL="https://github.com/ray-cast/ray-mmd"
PIN="218a91cd1c53f49850b2772ebbcb98bf258e75b1"
BASE="${TMPDIR:-/tmp}/mds-corpus"
DEST="${BASE%/}/ray-mmd"

# Refuse a destination inside the repository that holds this script.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null || true)"
mkdir -p "$BASE"
REAL="$(cd "$BASE" && pwd -P)/ray-mmd"
if [ -n "$REPO" ]; then
    case "$REAL/" in
        "$REPO"/*) echo "fetch_corpus: $REAL is inside the repository $REPO" >&2; exit 1 ;;
    esac
fi

head_of() { git -C "$DEST" rev-parse HEAD 2>/dev/null || true; }

if [ "$(head_of)" = "$PIN" ]; then
    echo "fetch_corpus: already at $PIN"
else
    if [ -d "$DEST/.git" ]; then
        git -C "$DEST" fetch --depth 1 origin "$PIN"
    else
        if [ -e "$DEST" ] && [ -n "$(ls -A "$DEST")" ]; then
            echo "fetch_corpus: $DEST exists and is not a git checkout" >&2
            exit 1
        fi
        mkdir -p "$DEST"
        git -C "$DEST" init -q
        git -C "$DEST" remote add origin "$URL"
        git -C "$DEST" fetch --depth 1 origin "$PIN"
    fi
    git -C "$DEST" checkout -q --detach "$PIN"
fi

ACTUAL="$(head_of)"
if [ "$ACTUAL" != "$PIN" ]; then
    echo "fetch_corpus: HEAD is $ACTUAL, expected $PIN" >&2
    exit 1
fi
echo "fetch_corpus: verified $PIN"
echo "$DEST"
