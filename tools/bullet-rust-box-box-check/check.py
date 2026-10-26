#!/usr/bin/env python3
"""Compare real Bullet box candidates and collision manifold traces to pure Rust."""
import argparse
import difflib
import hashlib
import re
import os
from pathlib import Path
import platform
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def run(args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT / 'rust', **kwargs)


def select_fixture(inputs, captured, coverage):
    """Keep complete owned scenarios, including lifecycle traces and observed SAT cases."""
    lines = inputs.splitlines(keepends=True)
    results = iter(captured.splitlines(keepends=True))
    groups = []
    operation_group = {}
    for operation, line in enumerate(lines):
        if line.startswith(b'N '):
            groups.append({'input': b'', 'native': b'', 'coverage': set(),
                           'owned': line.split()[1] == b'0'})
        group = groups[-1]
        group['input'] += line
        if line.startswith(b'T '):
            group['native'] += next(results)
        group['native'] += next(results)
        operation_group[operation] = len(groups) - 1
    assert next(results, None) is None
    for line in coverage.splitlines():
        if line.startswith('trace '):
            _, operation, code, polygon, candidates = line.split()
            groups[operation_group[int(operation)]]['coverage'].update(
                [('codes', int(code)), ('polygon', int(polygon)), ('candidates', int(candidates))])
    required = ({('codes', n) for n in range(1, 16)}
                | {('polygon', n) for n in range(3, 9)}
                | {('candidates', n) for n in range(1, 9)})
    selected = set(range(6))
    covered = set().union(*(groups[i]['coverage'] for i in selected))
    while required - covered:
        best = max((i for i, group in enumerate(groups) if group['owned'] and i not in selected),
                   key=lambda i: (len(groups[i]['coverage'] & (required - covered)), -i))
        assert groups[best]['coverage'] & (required - covered), 'Missing native owned coverage'
        selected.add(best)
        covered.update(groups[best]['coverage'])
    selected = sorted(selected)
    assert all(groups[i]['owned'] for i in selected)
    summary = 'groups ' + ' '.join(map(str, selected)) + '\n'
    for name in ['codes', 'polygon', 'candidates']:
        summary += name + ' ' + ' '.join(str(n) for kind, n in sorted(covered) if kind == name) + '\n'
    return (b''.join(groups[i]['input'] for i in selected),
            b''.join(groups[i]['native'] for i in selected), summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    temporary = output / 'tmp'
    temporary.mkdir(exist_ok=True)
    environment['TMPDIR'] = str(temporary)
    src = ROOT / 'recipes/bullet275/bullet-src/src'
    shim = ROOT / 'rust/crates/mds-bullet-sys/shim'
    crt = ROOT / 'rust/crates/mds-crtmath/src/lib.rs'
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'staticlib',
         '-O', crt, '-o', output / 'libmds_crtmath.a'], env=environment)
    shapes = src / 'BulletCollision/CollisionShapes'
    native_sources = [shapes / f'{name}.cpp' for name in [
        'btSphereShape', 'btBoxShape', 'btCapsuleShape', 'btStaticPlaneShape',
        'btCollisionShape', 'btConvexShape', 'btConvexInternalShape',
        'btPolyhedralConvexShape', 'btConcaveShape']]
    native_sources += [src / path for path in [
        'LinearMath/btAlignedAllocator.cpp',
        'BulletCollision/BroadphaseCollision/btDispatcher.cpp',
        'BulletCollision/BroadphaseCollision/btCollisionAlgorithm.cpp']]
    native_sources += [src / 'BulletCollision/CollisionDispatch' / f'{name}.cpp' for name in [
        'btBoxBoxCollisionAlgorithm', 'btManifoldResult',
        'btCollisionObject', 'btActivatingCollisionAlgorithm']]
    native_sources += [src / 'BulletCollision/NarrowPhaseCollision/btPersistentManifold.cpp']
    detector = src / 'BulletCollision/CollisionDispatch/btBoxBoxDetector.cpp'
    original = detector.read_text()
    instrumented = original.replace('#include "btBoxBoxDetector.h"', '#include "btBoxBoxDetector.h"\nextern void boxCoverage(int,int,int);')
    instrumented = instrumented.replace('    return 1;\n  }', '    boxCoverage(code,0,1);\n    return 1;\n  }')
    instrumented = instrumented.replace('  if (cnum <= maxc)', '  boxCoverage(code,n,cnum);\n  if (cnum <= maxc)')
    hooked = output / 'btBoxBoxDetector-observed.cpp'
    hooked.write_text(instrumented)
    (output / 'detector.sha256').write_text(hashlib.sha256(detector.read_bytes()).hexdigest()+'  '+str(detector)+'\n')
    (output / 'observation.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True),instrumented.splitlines(True),fromfile=str(detector),tofile=str(hooked))))
    native_sources += [detector]
    (output / 'native-sources.sha256').write_text(''.join(
        hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + str(path.relative_to(ROOT)) + '\n'
        for path in [*native_sources, HERE / 'oracle.cpp', crt, shim / 'det_math.h']))
    executable = output / 'native-box-box'
    command = [os.environ.get('CXX', 'clang++'), '-std=c++17', '-O2', '-ffp-contract=off',
               '-fno-fast-math', '-fdeclspec', '-w', '-DBT_NO_PROFILE=1',
               '-I', shim / 'sse_emu', '-I', src, '-I', shim, '-I', detector.parent,
               '-include', shim / 'det_math.h', HERE / 'oracle.cpp', *native_sources,
               output / 'libmds_crtmath.a', '-o', executable]
    if platform.system() == 'Darwin':
        command += ['-Wl,-dead_strip']
    else:
        command += ['-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', '-ldl', '-lpthread', '-lm']
    run(command, env=environment)
    observed_executable = output / 'native-box-box-observed'
    observed_command = [observed_executable if v == executable else hooked if v == detector else v for v in command]
    run(observed_command, env=environment)
    inputs = subprocess.check_output([sys.executable, HERE / 'cases.py'])
    (output / 'inputs.tsv').write_bytes(inputs)
    with (output / 'native-stderr.txt').open('wb') as native_stderr:
        captured = subprocess.check_output([executable], input=inputs, env=environment, stderr=native_stderr)
    with (output / 'coverage.txt').open('wb') as coverage:
        observed_capture = subprocess.check_output([observed_executable], input=inputs, env=dict(environment, BOX_COVERAGE_TRACE="1"), stderr=coverage)
    assert captured == observed_capture, 'Observation hook changed native output'
    (output / 'native.tsv').write_bytes(captured)
    contact = (ROOT / 'rust/crates/mds-bullet/src/core/contact.rs').read_text()
    adapter = '\n'.join(line for line in contact.splitlines() if not line.startswith('//!'))
    trace_tests = ROOT / 'rust/crates/mds-bullet/tests/pure_bullet/box_box.rs'
    adapter += '\n#[path = "' + str(trace_tests) + '"] pub mod box_box_tests;\n'
    adapter_path = output / 'contact-adapter.rs'
    adapter_path.write_text(adapter)
    environment['BOX_CONTACT_ADAPTER'] = str(adapter_path)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'rlib',
         '-O', crt, '-o', output / 'libmds_crtmath.rlib'], env=environment)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '-D', 'warnings', '-O',
         HERE / 'test.rs', '--extern',
         f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'rust-contacts'], env=environment)
    run([output / 'rust-contacts', output / 'inputs.tsv', output / 'native.tsv'], env=environment)
    coverage = (output / 'coverage.txt').read_text()
    observed = {line.split()[0]: set(map(int, line.split()[1:])) for line in coverage.splitlines() if not line.startswith('trace ')}
    assert observed['codes'] == set(range(1, 16)), coverage
    assert set(range(3, 9)) <= observed['polygon'], coverage
    assert observed['candidates'] == set(range(1, 9)), coverage
    print('\n'.join(line for line in coverage.splitlines() if not line.startswith('trace ')))
    frozen_input, frozen_native, summary = select_fixture(inputs, captured, coverage)
    fixture = ROOT / 'rust/crates/mds-bullet/tests/box_box_data'
    assert (fixture / 'inputs.tsv').read_bytes() == frozen_input, 'Selected native input differs'
    assert (fixture / 'native.tsv').read_bytes() == frozen_native, 'Frozen native box trace differs'
    assert (fixture / 'coverage.txt').read_text() == summary, 'Selected native coverage differs'
    (output / 'selected-coverage.txt').write_text(summary)
    print('Frozen complete owned scenarios match the native recapture.\n' + summary, end='')
    source = ROOT / 'rust/crates/mds-bullet/src/core/box_box.rs'
    mutation = source.read_text().replace('cull(&positions, first)', '{ let _ = (&positions, first); [0, 1, 2, 3] }')
    assert mutation != source.read_text()
    mutated_source = output / 'box-box-first-four.rs'
    mutated_source.write_text(mutation)
    harness = (HERE / 'test.rs').read_text()
    harness = re.sub(r'#\[path = "([^"]+)"\]', lambda m: '#[path = "'+str((HERE / m[1]).resolve())+'"]', harness)
    harness = harness.replace(str(source), str(mutated_source))
    mutated_harness = output / 'first-four-test.rs'
    mutated_harness.write_text(harness)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '-O', mutated_harness,
         '--extern', f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'first-four-test'], env=environment)
    with (output / 'first-four-regression.txt').open('wb') as evidence:
        regression = subprocess.run([output / 'first-four-test', output / 'inputs.tsv', output / 'native.tsv'],
                                    cwd=ROOT / 'rust', env=environment, stdout=evidence, stderr=evidence)
    assert regression.returncode != 0, 'Candidate-order regression was not detected'
    print('Author regression detected: keeping the first four candidates fails native order parity.')


if __name__ == '__main__':
    main()
