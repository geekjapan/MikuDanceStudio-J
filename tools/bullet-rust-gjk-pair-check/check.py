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
from cases import COMPACT
from test_observe import test_fallback_coverage
from observe import observe

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def run(args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT / 'rust', **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--record', action='store_true', help='replace the checked-in native fixture')
    args = parser.parse_args()
    test_fallback_coverage()
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.pop('MDS_GJK_PAIR_INPUTS', None)
    environment.pop('MDS_GJK_PAIR_NATIVE', None)
    temporary = output / 'tmp'
    temporary.mkdir(exist_ok=True)
    environment['TMPDIR'] = str(temporary)
    src = ROOT / 'recipes/bullet275/bullet-src/src'
    shim = ROOT / 'rust/crates/mds-bullet-sys/shim'
    crt = ROOT / 'rust/crates/mds-crtmath/src/lib.rs'
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'staticlib',
         '-O', crt, '-o', output / 'libmds_crtmath.a'], env=environment)
    native_sources = list((src / 'BulletCollision').rglob('*.cpp')) + list((src / 'LinearMath').glob('*.cpp'))
    executable = output / 'native-gjk-pair'
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
    fixture = ROOT / 'rust/crates/mds-bullet/tests/gjk_pair_data/native.tsv'
    frozen_inputs = fixture.with_name('inputs.tsv')
    compact = COMPACT
    prefix = lambda data: b''.join(data.splitlines(keepends=True)[:compact])
    if args.record:
        frozen_inputs.write_bytes(prefix(inputs))
        fixture.write_bytes(prefix(captured))
    directed_inputs = fixture.with_name('fallback-inputs.tsv')
    directed_native = fixture.with_name('fallback-native.tsv')
    count = len((HERE / 'fallback-cases.tsv').read_text().splitlines())
    suffix = lambda data: b''.join(data.splitlines(keepends=True)[-count:])
    if args.record:
        directed_inputs.write_bytes(suffix(inputs))
        directed_native.write_bytes(suffix(captured))
    assert directed_inputs.read_bytes() == suffix(inputs)
    assert directed_native.read_bytes() == suffix(captured)
    assert subprocess.check_output([executable], input=suffix(inputs), env=environment) == suffix(captured)
    assert frozen_inputs.read_bytes() == prefix(inputs)
    assert fixture.read_bytes() == prefix(captured)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'rlib',
         '-O', crt, '-o', output / 'libmds_crtmath.rlib'], env=environment)
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--test', '-D', 'warnings', '-O',
         HERE / 'harness.rs', '--extern', f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'rust-gjk-pair'], env=environment)
    run(['rustup', 'run', '1.95.0', 'clippy-driver', '--edition=2021', '--test', '-D', 'warnings', '-O',
         HERE / 'harness.rs', '--extern', f'mds_crtmath={output / "libmds_crtmath.rlib"}', '-o', output / 'clippy-gjk-pair'], env=environment)
    run([output / 'rust-gjk-pair'], env=environment)
    environment['MDS_GJK_PAIR_INPUTS'] = str(output / 'inputs.tsv')
    environment['MDS_GJK_PAIR_NATIVE'] = str(output / 'native.tsv')
    run([output / 'rust-gjk-pair'], env=environment)
    run([sys.executable, HERE / 'mutations.py', '--out-dir', output / 'mutations', '--crt-rlib', output / 'libmds_crtmath.rlib', '--inputs', output / 'inputs.tsv', '--native', output / 'native.tsv'], env=environment)
    files = [*HERE.glob('*.py'), *HERE.glob('*.rs'), HERE / 'oracle.cpp', HERE / 'README.md', HERE / 'fallback-cases.tsv', HERE.parent / 'bullet-rust-gjk-epa-check/cases.py', *native_sources, *observed_sources,
             *src.rglob('*.h'), *shim.rglob('*.h'), *crt.parent.rglob('*.rs'),
             * (ROOT / 'rust/crates/mds-bullet/src/core').glob('*.rs'),
             ROOT / 'rust/crates/mds-bullet/tests/pure_bullet/gjk_pair.rs',
             fixture, frozen_inputs, directed_inputs, directed_native, output / 'inputs.tsv', output / 'native.tsv', output / 'observed.tsv']
    (output / 'sha256.json').write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, indent=2)+'\n')
    provenance = [platform.platform(), subprocess.check_output([os.environ.get('CXX','clang++'),'--version'],text=True), subprocess.check_output(['rustup','run','1.95.0','rustc','-Vv'],text=True)]
    (output / 'provenance.txt').write_text('\n'.join(provenance))
    print(f'Native fixture and pure Rust agree for {len(captured.splitlines())} outer queries and manifold operations.')

if __name__ == '__main__':
    main()
