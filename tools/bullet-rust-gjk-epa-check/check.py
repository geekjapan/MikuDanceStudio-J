#!/usr/bin/env python3
"""Capture real Bullet output, compare it to the fixture, then test pure Rust."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from observe import observe
from cases import COMPACT

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
    environment.pop('MDS_GJK_EPA_INPUTS', None)
    environment.pop('MDS_GJK_EPA_NATIVE', None)
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
    narrow = src / 'BulletCollision/NarrowPhaseCollision'
    native_sources += [narrow / (n + '.cpp') for n in ['btGjkEpa2', 'btGjkEpaPenetrationDepthSolver', 'btVoronoiSimplexSolver']]
    executable = output / 'native-gjk-epa'
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
    run(command, env=environment)
    inputs = subprocess.check_output([sys.executable, HERE / 'cases.py'])
    (output / 'inputs.tsv').write_bytes(inputs)
    captured = subprocess.check_output([executable], input=inputs, env=environment)
    (output / 'native.tsv').write_bytes(captured)
    observed_sources = observe(src, command, executable, inputs, output, environment)
    fixture = ROOT / 'rust/crates/mds-bullet/tests/gjk_epa_data/native.tsv'
    frozen_inputs = fixture.with_name('inputs.tsv')
    compact = COMPACT
    prefix = lambda data: b''.join(data.splitlines(keepends=True)[:compact])
    raw_inputs = frozen_inputs.with_name('raw-inputs.tsv')
    raw_native = frozen_inputs.with_name('raw-native.tsv')
    tail = lambda data: b''.join(data.splitlines(keepends=True)[-9:])
    if args.record:
        raw_inputs.write_bytes(tail(inputs))
        raw_native.write_bytes(tail(captured))
        frozen_inputs.write_bytes(prefix(inputs))
        fixture.write_bytes(prefix(captured))
    assert frozen_inputs.read_bytes() == prefix(inputs)
    assert fixture.read_bytes() == prefix(captured)
    assert raw_inputs.read_bytes() == tail(inputs)
    assert raw_native.read_bytes() == tail(captured)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'rlib',
         '-O', crt, '-o', output / 'libmds_crtmath.rlib'], env=environment)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--test', '-D', 'warnings', '-O',
         HERE / 'harness.rs', '--extern', f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'rust-gjk-epa'], env=environment)
    run(['rustup', 'run', '1.95.0', 'clippy-driver', '--edition=2021', '--test', '-D', 'warnings', '-O',
         HERE / 'harness.rs', '--extern', f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'clippy-gjk-epa'], env=environment)
    run([output / 'rust-gjk-epa'], env=environment)
    environment['MDS_GJK_EPA_INPUTS'] = str(output / 'inputs.tsv')
    environment['MDS_GJK_EPA_NATIVE'] = str(output / 'native.tsv')
    run([output / 'rust-gjk-epa'], env=environment)
    run([sys.executable, HERE / 'mutations.py', '--out-dir', output / 'mutations', '--crt-rlib', output / 'libmds_crtmath.rlib'], env={k:v for k,v in environment.items() if not k.startswith('MDS_GJK_EPA_')})
    files = [*HERE.glob('*.py'), *HERE.glob('*.rs'), *crt.parent.rglob('*.rs'), *src.rglob('*.h'), *shim.rglob('*.h'), *native_sources, *observed_sources, HERE / 'oracle.cpp', HERE / 'cases.py', HERE / 'observe.py', fixture, frozen_inputs, raw_inputs, raw_native,
             ROOT / 'rust/crates/mds-bullet/src/core/gjk_epa.rs', ROOT / 'rust/crates/mds-bullet/src/core/math.rs', ROOT / 'rust/crates/mds-bullet/src/core/shape.rs', ROOT / 'rust/crates/mds-bullet/tests/pure_bullet/gjk_epa.rs', output / 'inputs.tsv', output / 'native.tsv', output / 'observed.tsv']
    (output / 'sha256.json').write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, indent=2)+'\n')
    provenance = [platform.platform(), subprocess.check_output([os.environ.get('CXX','clang++'),'--version'],text=True), subprocess.check_output(['rustup','run','1.95.0','rustc','-Vv'],text=True)]
    (output / 'provenance.txt').write_text('\n'.join(provenance))
    print(f'Native fixture and pure Rust agree for {len(captured.splitlines())} GJK/EPA cases.')

if __name__ == '__main__':
    main()
