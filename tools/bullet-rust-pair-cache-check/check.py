#!/usr/bin/env python3
"""Compare real Bullet and pure Rust against the same strict, checked-in fixture."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def run(args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    src = ROOT / 'recipes/bullet275/bullet-src/src'
    native = out / 'native-pair-cache'
    command = [os.environ.get('CXX', 'clang++'), '-std=c++17', '-O2', '-fdeclspec',
               '-DBT_NO_PROFILE=1', '-I', src, HERE / 'oracle.cpp',
               src / 'BulletCollision/BroadphaseCollision/btOverlappingPairCache.cpp',
               src / 'BulletCollision/BroadphaseCollision/btDispatcher.cpp',
               src / 'LinearMath/btAlignedAllocator.cpp', '-o', native]
    (out / 'native-command.txt').write_text(' '.join(map(str, command)) + '\n')
    run(command)
    inputs = subprocess.check_output([sys.executable, HERE / 'cases.py'])
    (out / 'inputs.tsv').write_bytes(inputs)
    captured = subprocess.check_output([native], input=inputs)
    (out / 'native.tsv').write_bytes(captured)
    data = ROOT / 'rust/crates/mds-bullet/tests/pair_cache_data'
    if args.record:
        (data / 'inputs.tsv').write_bytes(inputs)
        (data / 'native.tsv').write_bytes(captured)
    assert (data / 'inputs.tsv').read_bytes() == inputs, 'input fixture differs'
    assert (data / 'native.tsv').read_bytes() == captured, 'native fixture differs'
    executable = out / 'rust-pair-cache'
    run(['rustup','run','1.95.0','rustc','--edition=2021','--test','-D','warnings','-O', HERE / 'test.rs','-o', executable])
    run([executable])
    print(f'Strict native/Rust equality: {len(captured.splitlines())} operations, 32 seeds x 64 mixed operations.')


if __name__ == '__main__':
    main()
