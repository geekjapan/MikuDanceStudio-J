#!/usr/bin/env python3
"""Capture real Bullet output, compare it to the fixture, then test pure Rust."""
import argparse
import os
from pathlib import Path
import platform
import subprocess

from profiles import compare_capture, fixture_path, verify_profiles

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def run(args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT / 'rust', **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--record', action='store_true', help='replace the checked-in native fixture')
    args = parser.parse_args()
    fixture = fixture_path()
    verify_profiles()
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
        'BulletDynamics/ConstraintSolver/btGeneric6DofSpringConstraint',
        'BulletDynamics/ConstraintSolver/btTypedConstraint',
        'BulletDynamics/ConstraintSolver/btSequentialImpulseConstraintSolver',
        'BulletDynamics/ConstraintSolver/btContactConstraint',
        'BulletDynamics/ConstraintSolver/btSolve2LinearConstraint',
        'BulletDynamics/Dynamics/btRigidBody',
        'BulletCollision/CollisionDispatch/btCollisionObject',
        'LinearMath/btAlignedAllocator']]
    executable = output / 'native-joints'
    command = [os.environ.get('CXX', 'clang++'), '-std=c++17', '-O2', '-ffp-contract=off',
               '-fno-fast-math', '-fdeclspec', '-w', '-DBT_NO_PROFILE=1',
               '-I', shim / 'sse_emu', '-I', src, '-I', shim,
               '-include', shim / 'det_math.h', HERE / 'oracle.cpp', *native_sources,
               output / 'libmds_crtmath.a', '-o', executable]
    if platform.system() == 'Darwin':
        command += ['-Wl,-dead_strip']
    else:
        command += ['-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', '-ldl', '-lpthread', '-lm']
    (output / 'native-command.txt').write_text(' '.join(map(str, command)) + '\n')
    run(command, env=environment)
    environment['OPENMMD_DUMP_RESOLVE'] = str(output / 'resolve.log')
    environment['OPENMMD_DUMP_SOLVES'] = '10000'
    factor_data = subprocess.check_output([executable, '--factors'], env=environment)
    (output / 'factors.tsv').write_bytes(factor_data)
    factor_fixture = ROOT / 'rust/crates/mds-bullet/tests/solver_data/factors.tsv'
    if args.record:
        factor_fixture.write_bytes(factor_data)
    if factor_fixture.read_bytes() != factor_data:
        raise SystemExit('Native factor operations differ from checked-in fixture')
    captured = subprocess.check_output([executable], env=environment)
    (output / 'oracle.tsv').write_bytes(captured)
    import re
    events = []
    for line in (output / 'resolve.log').read_text().splitlines():
        if '"kind":"postnc"' in line:
            vectors = []
            for name in ['a_dlin', 'a_dang', 'b_dlin', 'b_dang']:
                vectors += re.findall(r'[0-9A-F]{8}', re.search(r'"' + name + r'":(\[[^]]+\])', line)[1])
            applied = re.search(r'"applied":"([0-9A-F]{8})"', line)[1]
            events.append([applied] + vectors)
    cursor = 0
    lines = []
    # Inputs have 3 bodies * 29 words and 2 joints * 105 words, plus the four-word header.
    for line in captured.decode().splitlines():
        fields = line.split('\t')
        count = int(fields[1 + 4 + 3 * 29 + 2 * 105], 16)
        event_count = count * 10 if int(fields[2], 16) == 260 else 0
        trace = events[cursor:cursor + event_count]
        assert len(trace) == event_count
        cursor += event_count
        lines.append(line + ''.join('\t' + w.lower() for event in trace for w in event))
    assert cursor == len(events)
    captured = ('\n'.join(lines) + '\n').encode()
    (output / 'native.tsv').write_bytes(captured)
    if args.record:
        fixture.write_bytes(captured)
    compare_capture(captured, fixture)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'rlib',
         '-O', crt, '-o', output / 'libmds_crtmath.rlib'], env=environment)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'bullet_core_support', '--crate-type', 'rlib',
         '-D', 'warnings', '-O', HERE / 'support.rs', '--extern',
         f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'libbullet_core_support.rlib'], env=environment)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--test', '-D', 'warnings', '-O',
         HERE / 'harness.rs', '-L', f'dependency={output}', '--extern', f'bullet_core_support={output / "libbullet_core_support.rlib"}', '--extern',
         f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'rust-joints'], env=environment)
    run([output / 'rust-joints', '--nocapture'], env=environment)
    run(['rustup', 'run', '1.95.0', 'clippy-driver', '--edition=2021', '--test', '-D', 'warnings', '-O',
         HERE / 'harness.rs', '-L', f'dependency={output}', '--extern', f'bullet_core_support={output / "libbullet_core_support.rlib"}',
         '--extern', f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'clippy-solver'], env=environment)
    print(f'Native fixture and pure Rust agree for {len(captured.splitlines())} joint cases.')


if __name__ == '__main__':
    main()
