#!/usr/bin/env python3
"""Strict real native SAP and pure Rust comparison, without a native World."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def run(command, **kwargs):
    subprocess.run(list(map(str, command)), check=True, cwd=ROOT, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    src = ROOT / 'recipes/bullet275/bullet-src/src'
    broadphase = src / 'BulletCollision/BroadphaseCollision'
    native = out / 'native-axis-sweep'
    sources = [broadphase / f'{name}.cpp' for name in [
        'btAxisSweep3', 'btOverlappingPairCache', 'btDispatcher', 'btDbvtBroadphase', 'btDbvt', 'btBroadphaseProxy']]
    sources += [src / 'LinearMath/btAlignedAllocator.cpp']
    command = [os.environ.get('CXX', 'clang++'), '-std=c++17', '-O2', '-ffp-contract=off',
               '-fno-fast-math', '-fdeclspec', '-DBT_NO_PROFILE=1', '-I', src,
               HERE / 'oracle.cpp', *sources, '-o', native]
    (out / 'native-command.txt').write_text(' '.join(map(str, command))+'\n')
    run(command)
    inputs = subprocess.check_output([sys.executable, HERE / 'cases.py'])
    (out / 'inputs.tsv').write_bytes(inputs)
    captured = subprocess.check_output([native], input=inputs)
    (out / 'native.tsv').write_bytes(captured)
    data = ROOT / 'rust/crates/mds-bullet/tests/axis_sweep_data'
    if args.record:
        (data / 'inputs.tsv').write_bytes(inputs)
        (data / 'native.tsv').write_bytes(captured)
    assert (data / 'inputs.tsv').read_bytes() == inputs, 'input fixture differs'
    assert (data / 'native.tsv').read_bytes() == captured, 'native fixture differs'
    crt = ROOT / 'rust/crates/mds-crtmath/src/lib.rs'
    run(['rustup','run','1.95.0','rustc','--edition=2021','--crate-name','mds_crtmath','--crate-type','rlib','-O',crt,'-o',out / 'libmds_crtmath.rlib'])
    executable = out / 'rust-axis-sweep'
    run(['rustup','run','1.95.0','rustc','--edition=2021','--test','-D','warnings','-O',HERE / 'test.rs','--extern',f'mds_crtmath={out / "libmds_crtmath.rlib"}','-o',executable])
    run([executable])
    print(f'Strict native/Rust equality: {len(captured.splitlines())} operations, 32 seeds x 128 mixed operations.')


if __name__ == '__main__':
    main()
