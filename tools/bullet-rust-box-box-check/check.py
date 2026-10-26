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
        observed_capture = subprocess.check_output([observed_executable], input=inputs, env=environment, stderr=coverage)
    assert captured == observed_capture, 'Observation hook changed native output'
    (output / 'native.tsv').write_bytes(captured)
    contact = (ROOT / 'rust/crates/mds-bullet/src/core/contact.rs').read_text()
    adapter = '\n'.join(line for line in contact.splitlines() if not line.startswith('//!'))
    adapter += r"""
impl PairManifold {
    pub fn box_test_new(shapes: [Shape; 2]) -> Self {
        let a = shapes[0].angular_motion_disc()*0.02;
        let b = shapes[1].angular_motion_disc()*0.02;
        Self { shapes, kind: PairKind::SphereSphere, threshold: if a < b { a } else { b }, points: [ContactPoint::EMPTY; 4], count: 0 }
    }
    pub fn box_test_add(&mut self, p: super::box_box::BoxContact, bodies: [ContactBody; 2]) {
        self.add_contact(p.normal_on_b, p.point_on_b, p.distance, bodies);
    }
    pub fn box_test_refresh(&mut self, bodies: [ContactBody; 2]) { self.refresh(bodies[0].world,bodies[1].world); }
}
"""
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
    observed = {line.split()[0]: set(map(int, line.split()[1:])) for line in coverage.splitlines()}
    assert observed['codes'] == set(range(1, 16)), coverage
    assert set(range(3, 9)) <= observed['polygon'], coverage
    assert observed['candidates'] == set(range(1, 9)), coverage
    print(coverage, end='')
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
