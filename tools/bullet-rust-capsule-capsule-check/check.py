#!/usr/bin/env python3
"""Compare real Bullet capsule-capsule processCollision manifolds to pure Rust."""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
COMMAND_LOG = None


def record(args):
    if COMMAND_LOG is not None:
        with COMMAND_LOG.open('a') as log:
            log.write(json.dumps(list(map(str, args))) + '\n')


def run(args, **kwargs):
    record(args)
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT / 'rust', **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--freeze', action='store_true', help='Write native-derived fixture bytes')
    args = parser.parse_args()
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    global COMMAND_LOG
    COMMAND_LOG = output / 'commands.jsonl'
    COMMAND_LOG.write_text('')
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
        'btConvexConvexAlgorithm', 'btManifoldResult',
        'btCollisionObject', 'btActivatingCollisionAlgorithm']]
    native_sources += sorted((src / 'BulletCollision/NarrowPhaseCollision').glob('*.cpp'))
    detector = src / 'BulletCollision/CollisionDispatch/btConvexConvexAlgorithm.cpp'
    original = detector.read_text()
    instrumented = original.replace('#include "btConvexConvexAlgorithm.h"', '#include "btConvexConvexAlgorithm.h"\n#include <cstdio>\nextern int capsuleOperation;\n#define COVER(label) std::fprintf(stderr,"%d %s\\n",capsuleOperation,label)')
    instrumented = instrumented.replace('if ( distance > distanceThreshold )\n\t\treturn distance;',
                                        'if ( distance > distanceThreshold ) { COVER("early-return"); return distance; }')
    instrumented = instrumented.replace('resultOut->refreshContactPoints();\n\t\treturn;',
                                        'resultOut->refreshContactPoints();\n COVER("fastpath-return");\n\t\treturn;')
    for text, label in [
        ('tA = 0.0f;', 'parallel'),
        ('tA = ( dirA_dot_trans - dirB_dot_trans * dirA_dot_dirB ) / denom;', 'skew'),
        ('tA = -hlenA;', 'a-low'), ('tA = hlenA;', 'a-high'),
        ('tB = -hlenB;', 'b-low'), ('tB = hlenB;', 'b-high'),
        ('return distance;', 'distance-return'),
        ('mmdCapsulePlaneSpace(normalOnB, directionA.z()', 'tangent-z'),
        ('mmdCapsulePlaneSpace(normalOnB, directionA.x()', 'tangent-xy')]:
        if text.endswith(';'):
            instrumented = instrumented.replace(text, '{ COVER("'+label+'"); '+text+' }')
        else:
            instrumented = instrumented.replace(text, 'COVER("'+label+'"); '+text)
    instrumented = instrumented.replace('if (dist<threshold)\n\t\t{', 'if (dist<threshold)\n\t\t{\n COVER("emitted");')
    instrumented = instrumented.replace('if (dist<threshold)', 'if (dist==threshold) { COVER("equal"); }\n if (dist<threshold)')
    hooked = output / 'btConvexConvexAlgorithm-observed.cpp'
    hooked.write_text(instrumented)
    (output / 'observation.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True),instrumented.splitlines(True),fromfile=str(detector),tofile=str(hooked))))
    (output / 'native-sources.sha256').write_text(''.join(
        hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + str(path.relative_to(ROOT)) + '\n'
        for path in [*native_sources, HERE / 'oracle.cpp', crt, shim / 'det_math.h']))
    executable = output / 'native-capsule-capsule'
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
    observed_executable = output / 'native-capsule-capsule-observed'
    observed_command = [observed_executable if v == executable else hooked if v == detector else v for v in command]
    run(observed_command, env=environment)
    record([sys.executable, HERE / 'cases.py'])
    inputs = subprocess.check_output([sys.executable, HERE / 'cases.py'])
    (output / 'inputs.tsv').write_bytes(inputs)
    record([executable])
    with (output / 'native-stderr.txt').open('wb') as native_stderr:
        captured = subprocess.check_output([executable], input=inputs, env=environment, stderr=native_stderr)
    record([observed_executable])
    with (output / 'coverage.txt').open('wb') as coverage:
        observed_capture = subprocess.check_output([observed_executable], input=inputs, env=dict(environment, CAPSULE_COVERAGE_TRACE="1"), stderr=coverage)
    (output / 'native-observed.tsv').write_bytes(observed_capture)
    assert captured == observed_capture, 'Observation hook changed native output'
    (output / 'native.tsv').write_bytes(captured)
    contact = (ROOT / 'rust/crates/mds-bullet/src/core/contact.rs').read_text()
    adapter = '\n'.join(line for line in contact.splitlines() if not line.startswith('//!'))
    trace_tests = ROOT / 'rust/crates/mds-bullet/tests/pure_bullet/capsule_capsule.rs'
    adapter += '\n#[path = "' + str(trace_tests) + '"] pub mod capsule_capsule_tests;\n'
    adapter_path = output / 'contact-adapter.rs'
    adapter_path.write_text(adapter)
    environment['CAPSULE_CONTACT_ADAPTER'] = str(adapter_path)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'rlib',
         '-O', crt, '-o', output / 'libmds_crtmath.rlib'], env=environment)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '-D', 'warnings', '-O',
         HERE / 'test.rs', '--extern',
         f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'rust-contacts'], env=environment)
    run([output / 'rust-contacts', output / 'inputs.tsv', output / 'native.tsv'], env=environment)
    coverage_lines = (output / 'coverage.txt').read_text().splitlines()
    coverage = {line.split()[1] for line in coverage_lines}
    required = {'early-return','fastpath-return','parallel','skew','a-low','a-high','b-low','b-high','tangent-z','tangent-xy','equal','emitted'}
    assert required <= coverage, required - coverage
    assert sum(line.endswith(' fastpath-return') for line in coverage_lines) == sum(line.startswith(b'T ') for line in inputs.splitlines())
    print('Native observed branches: ' + ', '.join(sorted(coverage)))
    (output / 'coverage-summary.txt').write_text(''.join(label + ' ' + str(sum(line.endswith(' ' + label) for line in coverage_lines)) + '\n' for label in sorted(coverage)))
    groups = []
    group_for_operation = {}
    results = iter(captured.splitlines(keepends=True))
    for operation, line in enumerate(inputs.splitlines(keepends=True), 1):
        if line.startswith(b'N '):
            groups.append({'input': b'', 'native': b'', 'coverage': set()})
        group = groups[-1]
        group_for_operation[operation] = len(groups)-1
        group['input'] += line
        if not line.startswith(b'N '):
            group['native'] += next(results)
    assert next(results, None) is None
    for line in coverage_lines:
        operation, label = line.split()
        groups[group_for_operation[int(operation)]]['coverage'].add(label)
    selected = set(range(32)) | set(range(len(groups)-4, len(groups)))
    covered = set().union(*(groups[i]['coverage'] for i in selected))
    while required - covered:
        best = max(range(len(groups)), key=lambda i: len(groups[i]['coverage'] & (required-covered)))
        assert groups[best]['coverage'] & (required-covered)
        selected.add(best)
        covered.update(groups[best]['coverage'])
    frozen_input = b''.join(groups[i]['input'] for i in sorted(selected))
    frozen_native = b''.join(groups[i]['native'] for i in sorted(selected))
    summary = 'groups ' + ' '.join(map(str, sorted(selected))) + '\nbranches ' + ' '.join(sorted(covered)) + '\n'
    (output / 'selected-inputs.tsv').write_bytes(frozen_input)
    (output / 'selected-native.tsv').write_bytes(frozen_native)
    (output / 'selected-coverage.txt').write_text(summary)
    fixture = ROOT / 'rust/crates/mds-bullet/tests/capsule_capsule_data'
    if args.freeze:
        (fixture / 'inputs.tsv').write_bytes(frozen_input)
        (fixture / 'native.tsv').write_bytes(frozen_native)
        (fixture / 'coverage.txt').write_text(summary)
    else:
        assert (fixture / 'inputs.tsv').read_bytes() == frozen_input
        assert (fixture / 'native.tsv').read_bytes() == frozen_native
        assert (fixture / 'coverage.txt').read_text() == summary
    run([output / 'rust-contacts', output / 'selected-inputs.tsv', output / 'selected-native.tsv'], env=environment)
    mutations = {
        'inclusive-threshold': ('if distance < self.threshold {', 'if distance <= self.threshold {'),
        'extra-margin': ('let distance = (len2.sqrt() - ra) - rb;', 'let distance = (len2.sqrt() - (ra + 0.04)) - (rb + 0.04);'),
        'omit-recompute': ('ta = clamp_a(tb * dot + at);', 'let _ = (tb, dot, at);'),
        'fixed-tangent': ('let normal = if len2 <=', 'let normal = if true { Vec3([1.0, 0.0, 0.0]) } else if len2 <='),
    }
    for name, (before, after) in mutations.items():
        assert before in adapter
        mutation = output / (name + '.rs')
        mutation.write_text(adapter.replace(before, after))
        mutated_env = dict(environment, CAPSULE_CONTACT_ADAPTER=str(mutation))
        executable = output / name
        run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '-O', HERE / 'test.rs',
             '--extern', f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', executable], env=mutated_env)
        record([executable, output / 'selected-inputs.tsv', output / 'selected-native.tsv'])
        with (output / (name + '-red.txt')).open('wb') as evidence:
            result = subprocess.run([executable, output / 'selected-inputs.tsv', output / 'selected-native.tsv'],
                                    cwd=ROOT / 'rust', env=mutated_env, stdout=evidence, stderr=evidence)
        assert result.returncode != 0, name + ' escaped'
        print('Mutation detected: ' + name)


if __name__ == '__main__':
    main()
