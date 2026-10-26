#!/usr/bin/env python3
"""Regenerate/check the native primitive oracle without building mds-bullet-sys."""
import argparse
import os
from pathlib import Path
import platform
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true", help="replace the committed native bit fixture")
    parser.add_argument("--work-dir", type=Path, help="parent for isolated compiler outputs")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.work_dir:
        args.work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mds-bullet-math-", dir=args.work_dir) as directory:
        work = Path(directory)
        env = dict(os.environ, TMPDIR=str(work), TMP=str(work), TEMP=str(work))
        rust = root / "rust"
        rustc = ["rustup", "run", "1.95.0", "rustc"]

        def run(command):
            subprocess.run([str(x) for x in command], cwd=rust, env=env, check=True)

        run([*rustc, "--edition=2021", "--crate-name", "mds_crtmath", "--crate-type", "rlib,staticlib",
             "-C", "opt-level=2", "--out-dir", work, "crates/mds-crtmath/src/lib.rs"])
        shim = root / "rust/crates/mds-bullet-sys/shim"
        executable = work / "oracle"
        native_libraries = ["-ldl", "-lpthread", "-lm"] if platform.system() == "Linux" else []
        run([os.environ.get("CXX", "clang++"), "-std=c++11", "-O2", "-ffp-contract=off",
             "-fno-fast-math", "-fdeclspec", "-w", "-I", shim / "sse_emu",
             "-I", root / "recipes/bullet275/bullet-src/src", "-include", shim / "det_math.h",
             root / "tools/bullet-rust-math-check/oracle.cpp", work / "libmds_crtmath.a",
             "-o", executable, *native_libraries])
        actual = subprocess.check_output([str(executable)], env=env)
        fixture = root / "rust/crates/mds-bullet/tests/data/math-native-bits.tsv"
        if args.record:
            fixture.write_bytes(actual)
        if actual != fixture.read_bytes():
            raise SystemExit("native oracle differs from committed bit fixture")
        print(f"Native fixture matched: {len(actual.splitlines())} rows on {platform.platform()}", flush=True)
        test = work / "pure_bullet"
        run([*rustc, "--edition=2021", "--test", "-D", "warnings", "-C", "opt-level=2", "--extern",
             f"mds_crtmath={work / 'libmds_crtmath.rlib'}", "crates/mds-bullet/tests/pure_bullet.rs",
             "-o", test])
        run([test])


if __name__ == "__main__":
    main()
