#!/usr/bin/env python3
"""Capture real Bullet output, compare it to the fixture, then test pure Rust."""
import argparse
from collections import Counter
import difflib
import hashlib
import json
import struct
import os
from pathlib import Path
import platform
import subprocess
import sys
from host_profiles import validate_capture, native_command, compiler_version

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def run(args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT / 'rust', **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.pop('MDS_SUPPORT_INPUTS', None)
    environment.pop('MDS_SUPPORT_NATIVE', None)
    environment.pop('MDS_SUPPORT_ACTUAL', None)
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
    native_sources += [src / 'LinearMath/btAlignedAllocator.cpp']
    executable = output / ('native-support.exe' if os.name == 'nt' else 'native-support')
    command = [os.environ.get('CXX', 'clang++'), '-std=c++17', '-O2', '-ffp-contract=off',
               '-fno-fast-math', '-fdeclspec', '-w', '-DBT_NO_PROFILE=1',
               '-I', shim / 'sse_emu', '-I', src, '-I', shim,
               '-include', shim / 'det_math.h', HERE / 'oracle.cpp', *native_sources,
               output / 'libmds_crtmath.a', '-o', executable]
    if platform.system() == 'Darwin':
        command += ['-Wl,-dead_strip']
    else:
        command += ['-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', '-ldl', '-lpthread', '-lm']
    (output / 'native-command.json').write_text(json.dumps(list(map(str, command)), indent=2) + '\n')
    command = native_command(command, output, environment)
    (output / 'effective-native-command.json').write_text(json.dumps(command, indent=2) + '\n')
    run(command, env=environment)
    source = shapes / 'btConvexShape.cpp'
    observed_source = output / 'btConvexShape-observed.cpp'
    original = source.read_text()
    observed = original.replace('#include "btConvexShape.h"', '#include "btConvexShape.h"\n#include <cstdio>\n#include <cstring>\nstatic unsigned supportWord(float v) { unsigned w; std::memcpy(&w, &v, 4); return w; }')
    start = observed.index('btVector3 btConvexShape::localGetSupportVertexWithoutMarginNonVirtual')
    end = observed.index('/* TODO: This should be bumped', start)
    prefix, body, suffix = observed[:start], observed[start:end], observed[end:]
    body = body.replace('if (lenSqr < btScalar(0.0001))', 'std::fprintf(stderr, "capsule-length %08x %d\\n", supportWord(lenSqr), lenSqr < btScalar(0.0001));\n\t\tif (lenSqr < btScalar(0.0001))')
    body = body.replace('if (newDot > maxDot)', 'std::fprintf(stderr, "capsule-cap %d %d\\n", newDot > maxDot, newDot == maxDot);\n\t\t\tif (newDot > maxDot)')
    body = body.replace('btVector3 localDirNorm = localDir;', 'btVector3 localDirNorm = localDir;\n\tstd::fprintf(stderr, "margin-length %08x\\n", supportWord((localDir.y()*localDir.y()+localDir.z()*localDir.z())+localDir.x()*localDir.x()));')
    body = body.replace('localDirNorm.setValue(btScalar(-1.),btScalar(-1.),btScalar(-1.));', 'std::fprintf(stderr, "margin-fallback\\n");\n\t\tlocalDirNorm.setValue(btScalar(-1.),btScalar(-1.),btScalar(-1.));')
    observed_source.write_text(prefix + body + suffix)
    (output / 'observed.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True), observed_source.read_text().splitlines(True), fromfile=str(source), tofile=str(observed_source))))
    observed_command = [str(x) for x in command]
    observed_command[observed_command.index(str(source))] = str(observed_source)
    observed_executable = output / ('native-support-observed.exe' if os.name == 'nt' else 'native-support-observed')
    observed_command = [arg.replace(str(executable), str(observed_executable)) for arg in observed_command]
    observed_command[1:1] = [f'/I{shapes}'] if os.name == 'nt' else ['-I', str(shapes)]
    (output / 'observed-command.json').write_text(json.dumps(observed_command, indent=2) + '\n')
    run(observed_command, env=environment)
    inputs = subprocess.check_output([sys.executable, HERE / 'cases.py'])
    (output / 'inputs.tsv').write_bytes(inputs)
    captured = subprocess.check_output([executable], input=inputs, env=environment)
    (output / 'native.tsv').write_bytes(captured)
    with (output / 'coverage.log').open('wb') as coverage:
        observed_capture = subprocess.check_output([output / ('native-support-observed.exe' if os.name == 'nt' else 'native-support-observed')], input=inputs, env=environment, stderr=coverage)
    (output / 'observed.tsv').write_bytes(observed_capture)
    if observed_capture != captured:
        raise SystemExit('Observation hooks changed native stdout')
    fixture = ROOT / 'rust/crates/mds-bullet/tests/support_data/native.tsv'
    frozen_inputs = fixture.with_name('inputs.tsv')
    compact = 1600
    if frozen_inputs.read_bytes() != b''.join(inputs.splitlines(keepends=True)[:compact]):
        raise SystemExit('Frozen support inputs differ from generator prefix')
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'rlib',
         '-O', crt, '-o', output / 'libmds_crtmath.rlib'], env=environment)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--test', '-D', 'warnings', '-O',
         ROOT / 'rust/crates/mds-bullet/tests/pure_bullet.rs', '--extern',
         f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'rust-support'], env=environment)
    environment['MDS_SUPPORT_INPUTS'] = str(output / 'inputs.tsv')
    environment['MDS_SUPPORT_NATIVE'] = str(output / 'native.tsv')
    environment['MDS_SUPPORT_ACTUAL'] = str(output / 'rust.tsv')
    provenance = [platform.platform(), compiler_version(),
                  subprocess.check_output(['rustup', 'run', '1.95.0', 'rustc', '-Vv'], text=True)]
    (output / 'provenance.txt').write_text('\n'.join(provenance))
    run([output / 'rust-support', 'support::'], env=environment)
    if (output / 'rust.tsv').read_bytes() != captured:
        raise SystemExit('Full same-host Rust output differs from native')
    fixture = validate_capture(output)
    environment.pop('MDS_SUPPORT_INPUTS')
    environment.pop('MDS_SUPPORT_ACTUAL')
    environment['MDS_SUPPORT_NATIVE'] = str(fixture)
    run([output / 'rust-support', 'support::'], env=environment)
    run([sys.executable, HERE / 'mutations.py', '--out-dir', output / 'mutations',
         '--crt-rlib', output / 'libmds_crtmath.rlib'], env={k: v for k, v in environment.items() if not k.startswith('MDS_SUPPORT_')})
    coverage = Counter((output / 'coverage.log').read_text().splitlines())
    summary = {}
    for label, threshold in [('capsule-length', 0.0001), ('margin-length', 2**-46)]:
        threshold = struct.unpack('<f', struct.pack('<f', threshold))[0]
        counts = Counter()
        words = Counter()
        for line, count in coverage.items():
            fields = line.split()
            if fields[0] != label:
                continue
            word = int(fields[1], 16)
            value = struct.unpack('<f', struct.pack('<I', word))[0]
            relation = 'nan' if value != value else 'below' if value < threshold else 'equal' if value == threshold else 'above'
            counts[relation] += count
            words[fields[1]] += count
        assert all(counts[relation] for relation in ['below', 'equal', 'above', 'nan'])
        boundary = struct.unpack('<I', struct.pack('<f', threshold))[0]
        assert all(words[f'{boundary + delta:08x}'] for delta in [-1, 0, 1])
        summary[label] = dict(counts)
        summary[label + '-threshold-words'] = {f'{boundary + delta:08x}': words[f'{boundary + delta:08x}'] for delta in [-1, 0, 1]}
    summary['cap-comparisons'] = {k: v for k, v in coverage.items() if k.startswith('capsule-cap')}
    summary['margin-fallback'] = coverage['margin-fallback']
    summary['full-rows'] = len(captured.splitlines())
    summary['compact-rows'] = compact
    summary['native-observed-stdout-identical'] = True
    (output / 'coverage.json').write_text(json.dumps(summary, indent=2) + '\n')
    files = [*native_sources, HERE / 'oracle.cpp', HERE / 'cases.py', fixture, frozen_inputs,
             ROOT / 'rust/crates/mds-bullet/src/core/shape.rs',
             output / 'inputs.tsv', output / 'native.tsv', output / 'observed.tsv', observed_source]
    (output / 'sha256.json').write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, indent=2) + '\n')
    provenance = [platform.platform(), compiler_version(),
                  subprocess.check_output(['rustup', 'run', '1.95.0', 'rustc', '-Vv'], text=True)]
    (output / 'provenance.txt').write_text('\n'.join(provenance))
    print(f'Native fixture and pure Rust agree for {len(captured.splitlines())} support cases.')


if __name__ == '__main__':
    main()
