#!/usr/bin/env python3
"""Capture real Bullet output, compare it to the fixture, then test pure Rust."""
import argparse
import difflib
import hashlib
import re
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
    parser.add_argument('--record', action='store_true', help='replace the checked-in native fixture')
    args = parser.parse_args()
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
        'BulletCollision/NarrowPhaseCollision/btPersistentManifold',
        'BulletDynamics/ConstraintSolver/btGeneric6DofConstraint',
        'BulletDynamics/ConstraintSolver/btGeneric6DofSpringConstraint',
        'BulletDynamics/ConstraintSolver/btTypedConstraint',
        'BulletDynamics/ConstraintSolver/btSequentialImpulseConstraintSolver',
        'BulletDynamics/ConstraintSolver/btContactConstraint',
        'BulletDynamics/ConstraintSolver/btSolve2LinearConstraint',
        'BulletDynamics/Dynamics/btRigidBody',
        'BulletCollision/CollisionDispatch/btCollisionObject',
        'LinearMath/btAlignedAllocator']]
    original = src / 'BulletDynamics/ConstraintSolver/btSequentialImpulseConstraintSolver.cpp'
    source = original.read_text()
    hook = '\t\t\t\t\t\tresolveSingleConstraintRowGenericSIMD(m_tmpSolverBodyPool[solveManifold.m_solverBodyIdA],\tm_tmpSolverBodyPool[solveManifold.m_solverBodyIdB],solveManifold);'
    assert source.count(hook) == 1
    altered = source.replace(hook, hook + '\n\t\t\t\t\t\topenmmdLogResolve("postfr", iteration, j, m_tmpSolverBodyPool[solveManifold.m_solverBodyIdA], m_tmpSolverBodyPool[solveManifold.m_solverBodyIdB], solveManifold);')
    marker = '\n\tm_tmpSolverBodyPool.resize(0);'
    assert altered.count(marker) == 1
    finish = '\n\tif (openmmdLogOpen()) { fprintf(g_openmmdLog, "{\\"kind\\":\\"contact_end\\"}\\n"); fflush(g_openmmdLog); }'
    # Insert only into solveGroup, after writeback and before pool cleanup.
    index = altered.rindex(marker)
    altered = altered[:index] + finish + altered[index:]
    patched = output / 'btSequentialImpulseConstraintSolver.cpp'
    patched.write_text(altered)
    (output / 'observer.diff').write_text(''.join(difflib.unified_diff(source.splitlines(True), altered.splitlines(True), fromfile=str(original), tofile=str(patched))))
    (output / 'vendor-sha256.txt').write_text(hashlib.sha256(original.read_bytes()).hexdigest() + '\n')
    native_sources[native_sources.index(original)] = patched
    executable = output / 'native-contacts'
    command = [os.environ.get('CXX', 'clang++'), '-std=c++17', '-O2', '-ffp-contract=off',
               '-fno-fast-math', '-fdeclspec', '-w', '-DBT_NO_PROFILE=1',
               '-I', original.parent, '-I', shim / 'sse_emu', '-I', src, '-I', shim,
               '-include', shim / 'det_math.h', HERE / 'oracle.cpp', *native_sources,
               output / 'libmds_crtmath.a', '-o', executable]
    if platform.system() == 'Darwin':
        command += ['-Wl,-dead_strip']
    else:
        command += ['-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', '-ldl', '-lpthread', '-lm']
    (output / 'native-command.txt').write_text(' '.join(map(str, command)) + '\n')
    run(command, env=environment)
    edge_data = subprocess.check_output([executable, '--edges'], env=environment)
    (output / 'edges.tsv').write_bytes(edge_data)
    edge_fixture = ROOT / 'rust/crates/mds-bullet/tests/contact_solver_data/edges.tsv'
    if args.record:
        edge_fixture.write_bytes(edge_data)
    if edge_fixture.read_bytes() != edge_data:
        raise SystemExit('Native lower-only row edges differ from checked-in fixture')
    environment['OPENMMD_DUMP_RESOLVE'] = str(output / 'resolve.log')
    environment['OPENMMD_DUMP_SOLVES'] = '10000'
    captured = subprocess.check_output([executable], env=environment)
    (output / 'oracle.tsv').write_bytes(captured)
    groups = [[]]
    for line in (output / 'resolve.log').read_text().splitlines():
        if any(token in line for token in ['"kind":"postct"', '"kind":"postfr"']):
            words = [re.search(r'"applied":"([0-9A-F]{8})"', line)[1]]
            for name in ['a_dlin', 'a_dang', 'b_dlin', 'b_dang']:
                words += re.findall(r'[0-9A-F]{8}', re.search(r'"' + name + r'":(\[[^]]+\])', line)[1])
            assert len(words) == 13
            iteration = int(re.search(r'"iter":([0-9]+)', line)[1])
            index = int(re.search(r'"j":([0-9]+)', line)[1])
            kind = int('"kind":"postfr"' in line)
            groups[-1].append([f'{iteration:08x}', f'{kind:08x}', f'{index:08x}'] + words)
        elif '"kind":"contact_end"' in line:
            groups.append([])
    assert len(groups) == len(captured.splitlines()) + 1 and not groups[-1]
    captured = ('\n'.join(line.decode() + '\t' + format(len(events), '08x') + ''.join('\t' + str(w).lower() for event in events for w in event) for line, events in zip(captured.splitlines(), groups)) + '\n').encode()
    (output / 'native.tsv').write_bytes(captured)
    fixture = ROOT / 'rust/crates/mds-bullet/tests/contact_solver_data/native.tsv'
    if args.record:
        fixture.write_bytes(captured)
    if fixture.read_bytes() != captured:
        raise SystemExit('Native contact solver differs from checked-in fixture')
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'rlib',
         '-O', crt, '-o', output / 'libmds_crtmath.rlib'], env=environment)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'bullet_core_support', '--crate-type', 'rlib',
         '-D', 'warnings', '-O', HERE / 'support.rs', '--extern',
         f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'libbullet_core_support.rlib'], env=environment)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--test', '-D', 'warnings', '-O',
         HERE / 'harness.rs', '-L', f'dependency={output}', '--extern', f'bullet_core_support={output / "libbullet_core_support.rlib"}', '--extern',
         f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'rust-contacts'], env=environment)
    run([output / 'rust-contacts', '--nocapture'], env=environment)
    run(['rustup', 'run', '1.95.0', 'clippy-driver', '--edition=2021', '--test', '-D', 'warnings', '-O',
         HERE / 'harness.rs', '-L', f'dependency={output}', '--extern', f'bullet_core_support={output / "libbullet_core_support.rlib"}',
         '--extern', f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'clippy-contacts'], env=environment)
    assert hashlib.sha256(original.read_bytes()).hexdigest() == (output / 'vendor-sha256.txt').read_text().strip()
    print(f'Native fixture and pure Rust agree for {len(captured.splitlines())} contact solver cases.')


if __name__ == '__main__':
    main()
