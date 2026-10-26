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
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bullet-rust-support-check"))
from host_profiles import validate_capture, native_command, compiler_version, load, host

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def run(args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT / 'rust', **kwargs)


def check_raw_override(binary, output, environment):
    native = (output / 'raw-native.tsv').read_bytes()
    corrupted = output / 'raw-negative-native.tsv'
    corrupted.write_bytes(native.replace(b'00000000', b'80000000', 1))
    negative_environment = dict(environment, MDS_GJK_EPA_RAW_NATIVE=str(corrupted),
                                MDS_GJK_EPA_RAW_ACTUAL=str(output / 'raw-negative-rust.tsv'))
    result = subprocess.run([binary, 'directed_raw_inputs_match_native_words'],
                            env=negative_environment, capture_output=True)
    (output / 'raw-override-negative.log').write_bytes(result.stdout + result.stderr)
    if result.returncode == 0 or b'query 6801' not in result.stdout + result.stderr:
        raise SystemExit('Raw capture override negative control did not reject the altered signed zero')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    for name in list(environment):
        if name.startswith('MDS_GJK_EPA_'):
            environment.pop(name)
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
    executable = output / ('native-gjk-epa.exe' if os.name == 'nt' else 'native-gjk-epa')
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
    assert frozen_inputs.read_bytes() == prefix(inputs)
    assert raw_inputs.read_bytes() == tail(inputs)
    (output / 'raw-inputs.tsv').write_bytes(tail(inputs))
    (output / 'raw-native.tsv').write_bytes(tail(captured))
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'rlib',
         '-O', crt, '-o', output / 'libmds_crtmath.rlib'], env=environment)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--test', '-D', 'warnings', '-O',
         HERE / 'harness.rs', '--extern', f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'rust-gjk-epa'], env=environment)
    run(['rustup', 'run', '1.95.0', 'clippy-driver', '--edition=2021', '--test', '-D', 'warnings', '-O',
         HERE / 'harness.rs', '--extern', f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'clippy-gjk-epa'], env=environment)
    environment['MDS_GJK_EPA_INPUTS'] = str(output / 'inputs.tsv')
    environment['MDS_GJK_EPA_NATIVE'] = str(output / 'native.tsv')
    environment['MDS_GJK_EPA_RAW_INPUTS'] = str(output / 'raw-inputs.tsv')
    environment['MDS_GJK_EPA_RAW_NATIVE'] = str(output / 'raw-native.tsv')
    environment['MDS_GJK_EPA_ACTUAL'] = str(output / 'rust.tsv')
    environment['MDS_GJK_EPA_RAW_ACTUAL'] = str(output / 'raw-rust.tsv')
    provenance = [platform.platform(), compiler_version(), subprocess.check_output(['rustup','run','1.95.0','rustc','-Vv'],text=True)]
    (output / 'provenance.txt').write_text('\n'.join(provenance))
    run([output / 'rust-gjk-epa'], env=environment)
    if (output / 'rust.tsv').read_bytes() != captured or (output / 'raw-rust.tsv').read_bytes() != tail(captured):
        raise SystemExit('Full same-host or raw Rust output differs from native')
    check_raw_override(output / 'rust-gjk-epa', output, environment)
    fixture = validate_capture(output, 'gjk-epa')
    manifest = load('gjk-epa')[0]
    raw_native = fixture.with_name(manifest['profiles'][host()]['raw'])
    environment = {k:v for k,v in environment.items() if not k.startswith('MDS_GJK_EPA_')}
    run([output / 'rust-gjk-epa'], env=environment)
    run([sys.executable, HERE / 'mutations.py', '--out-dir', output / 'mutations', '--crt-rlib', output / 'libmds_crtmath.rlib'], env={k:v for k,v in environment.items() if not k.startswith('MDS_GJK_EPA_')})
    files = [ROOT / 'tools/bullet-rust-support-check/host_profiles.py', *HERE.glob('*.json'), *HERE.glob('*.py'), *HERE.glob('*.rs'), *crt.parent.rglob('*.rs'), *src.rglob('*.h'), *shim.rglob('*.h'), *native_sources, *observed_sources, HERE / 'oracle.cpp', HERE / 'cases.py', HERE / 'observe.py', fixture, frozen_inputs, raw_inputs, raw_native,
             ROOT / 'rust/crates/mds-bullet/src/core/gjk_epa.rs', ROOT / 'rust/crates/mds-bullet/src/core/math.rs', ROOT / 'rust/crates/mds-bullet/src/core/shape.rs', ROOT / 'rust/crates/mds-bullet/tests/pure_bullet/gjk_epa.rs', output / 'inputs.tsv', output / 'native.tsv', output / 'observed.tsv', output / 'rust.tsv', output / 'raw-inputs.tsv', output / 'raw-native.tsv', output / 'raw-rust.tsv']
    (output / 'sha256.json').write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, indent=2)+'\n')
    provenance = [platform.platform(), compiler_version(), subprocess.check_output(['rustup','run','1.95.0','rustc','-Vv'],text=True)]
    (output / 'provenance.txt').write_text('\n'.join(provenance))
    print(f'Native fixture and pure Rust agree for {len(captured.splitlines())} GJK/EPA cases.')

if __name__ == '__main__':
    main()
