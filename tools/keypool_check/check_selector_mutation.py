#!/usr/bin/env python3
"""Require ASan to catch removal of the real display-selector bounds guard."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

GUARD = """                if (bone < 0 || static_cast<std::uint32_t>(bone) >= mdl::Mdl(m)->boneCount)
                    continue;
"""


def remove_guard(source):
    if source.count(GUARD) != 1:
        raise ValueError("expected exactly one production display-selector guard; update the mutation")
    return source.replace(GUARD, "", 1)


def require_detection(status, log, asan):
    if status != 1:
        raise ValueError(f"expected verifier violation exit 1, got {status}")
    if "paste display key at frame 0" not in log or "VIOLATION" not in log:
        raise ValueError("missing shortest display-paste violation")
    # Linux may summarize strcmp; bind the fault stack and summary to one report.
    for report in re.split(r"(?m)(?=^==\d+==(?:ERROR|WARNING):)", asan):
        if not re.match(r"==\d+==ERROR: AddressSanitizer: heap-buffer-overflow\b", report):
            continue
        fault_stack = report.split("\n\n", 1)[0]
        if re.search(
            r"(?m)^ +#\d+ [^\n]*\bRegisterDisplayKeyFromRecord\([^\n]*[ /]key_registrars\.cpp:\d+\b",
            fault_stack,
        ) and re.search(r"(?m)^SUMMARY: AddressSanitizer: heap-buffer-overflow\b", report):
            return
    raise ValueError("missing symbolized ASan selector-source heap-buffer-overflow")


def main():
    if len(sys.argv) != 2:
        raise ValueError("usage: check_selector_mutation.py ARTIFACT_DIRECTORY")
    root = Path(__file__).resolve().parents[2]
    artifacts = Path(sys.argv[1]).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    original = (root / "src/model/key_registrars.cpp").read_text()
    mutated = remove_guard(original)
    # Mutate only a disposable copy: interruption never leaves the checkout changed.
    with tempfile.TemporaryDirectory(prefix="keypool-selector-") as temporary:
        copy = Path(temporary) / "repo"
        for directory in ("include", "src/model", "tools/keypool_check"):
            shutil.copytree(root / directory, copy / directory)
        table = Path("rust/crates/mds-math/src/estimate_table.rs")
        (copy / table).parent.mkdir(parents=True)
        shutil.copy2(root / table, copy / table)
        (copy / "src/model/key_registrars.cpp").write_text(mutated)
        environment = dict(os.environ, TMPDIR=str(artifacts))
        with (artifacts / "mutation.log").open("w") as log:
            result = subprocess.run(
                ["sh", str(copy / "tools/keypool_check/run.sh"), "1"],
                env=environment, stdout=log, stderr=subprocess.STDOUT, check=False,
            )
        (artifacts / "mutation-exit.txt").write_text(f"{result.returncode}\n")
        asan_path = artifacts / "keypool_check/asan.log"
        asan = asan_path.read_text() if asan_path.exists() else ""
        require_detection(result.returncode, (artifacts / "mutation.log").read_text(), asan)
    if (root / "src/model/key_registrars.cpp").read_text() != original:
        raise ValueError("production checkout changed during mutation check")
    print("PASS: removing the real selector guard caused a display-paste ASan violation")


if __name__ == "__main__":
    main()
