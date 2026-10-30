#!/usr/bin/env python3
"""Capture real Bullet output, compare it to the fixture, then test pure Rust."""
import argparse
import os
from pathlib import Path
import platform
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def run(args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT / 'rust', **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--cases', type=int, default=2120)
    parser.add_argument('--record', action='store_true', help='replace the checked-in native fixture')
    args = parser.parse_args()
    if args.cases < 2120:
        parser.error('--cases must be at least 2120')
    if args.record and args.cases != 2120:
        parser.error('--record requires the default case count')
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.pop('OPENMMD_DUMP_ROWS', None)
    environment.pop('OPENMMD_DUMP_SPRING', None)
    temporary = output / 'tmp'
    temporary.mkdir(exist_ok=True)
    environment['TMPDIR'] = str(temporary)
    src = ROOT / 'recipes/bullet275/bullet-src/src'
    shim = ROOT / 'rust/crates/mds-bullet-sys/shim'
    crt = ROOT / 'rust/crates/mds-crtmath/src/lib.rs'
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'staticlib',
         '-O', crt, '-o', output / 'libmds_crtmath.a'], env=environment)
    native_sources = [src / f'{name}.cpp' for name in [
        'BulletDynamics/ConstraintSolver/btGeneric6DofConstraint',
        'BulletDynamics/ConstraintSolver/btTypedConstraint',
        'BulletDynamics/Dynamics/btRigidBody',
        'BulletCollision/CollisionDispatch/btCollisionObject',
        'LinearMath/btAlignedAllocator']]
    executable = output / 'native-coordinates'
    command = [os.environ.get('CXX', 'clang++'), '-std=c++17', '-O2', '-ffp-contract=off',
               '-fno-fast-math', '-fdeclspec', '-w', '-DBT_NO_PROFILE=1',
               '-I', shim / 'sse_emu', '-I', src, '-I', shim,
               '-include', shim / 'det_math.h', HERE / 'oracle.cpp', *native_sources,
               output / 'libmds_crtmath.a', '-o', executable]
    if platform.system() == 'Darwin':
        command += ['-Wl,-dead_strip']
    else:
        command += ['-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', '-ldl', '-lpthread', '-lm']
    run(command, env=environment)
    captured = subprocess.check_output([executable, str(args.cases)], env=environment)
    (output / 'native.tsv').write_bytes(captured)
    fixture = ROOT / 'rust/crates/mds-bullet/tests/coordinate_data/native.tsv'
    if args.record:
        fixture.write_bytes(captured)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'rlib',
         '-O', crt, '-o', output / 'libmds_crtmath.rlib'], env=environment)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--test', '-D', 'warnings', '-O',
         HERE / 'harness.rs', '--extern',
         f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'rust-coordinates'], env=environment)
    environment['MDS_COORDINATE_FIXTURE'] = str(output / 'native.tsv')
    run([output / 'rust-coordinates'], env=environment)
    if args.cases == 2120 and fixture.read_bytes() != captured:
        raise SystemExit('Native coordinate output differs from checked-in fixture')
    print(f'Native fixture and pure Rust agree for {len(captured.splitlines())} coordinate cases.')


if __name__ == '__main__':
    main()
