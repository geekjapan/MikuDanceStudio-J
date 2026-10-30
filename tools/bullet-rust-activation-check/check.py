#!/usr/bin/env python3
"""Recapture actual native activation APIs and replay every operation in pure Rust."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from cases import corpus

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = {k: v for k, v in os.environ.items() if not k.startswith('MDS_ACTIVATION_')}
    temporary = output / 'tmp'
    temporary.mkdir(exist_ok=True)
    environment['TMPDIR'] = str(temporary)

    def run(command, **kwargs):
        subprocess.run(list(map(str, command)), check=True, cwd=ROOT / 'rust', env=environment, **kwargs)

    src = ROOT / 'recipes/bullet275/bullet-src/src'
    shim = ROOT / 'rust/crates/mds-bullet-sys/shim'
    crt = ROOT / 'rust/crates/mds-crtmath/src/lib.rs'
    rustc = ['rustup', 'run', '1.95.0', 'rustc']
    run([*rustc, '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'rlib,staticlib', '-O', crt, '--out-dir', output])
    native_sources = sorted(p for folder in ['LinearMath', 'BulletCollision', 'BulletDynamics'] for p in (src / folder).rglob('*.cpp'))
    executable = output / 'native-activation'
    command = [os.environ.get('CXX', 'clang++'), '-std=c++17', '-O2', '-ffp-contract=off', '-fno-fast-math',
               '-fdeclspec', '-w', '-DBT_NO_PROFILE=1', '-I', shim / 'sse_emu', '-I', src, '-I', shim,
               '-include', shim / 'det_math.h', HERE / 'oracle.cpp', *native_sources,
               output / 'libmds_crtmath.a', '-o', executable]
    command += ['-Wl,-dead_strip'] if platform.system() == 'Darwin' else ['-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', '-ldl', '-lpthread', '-lm']
    (output / 'native-command.json').write_text(json.dumps(list(map(str, command)), indent=2) + '\n')
    run(command)
    inputs, compact_rows, scenarios = corpus()
    captured = subprocess.check_output([executable], input=inputs, env=environment)
    assert len(inputs.splitlines()) == len(captured.splitlines())
    (output / 'inputs.tsv').write_bytes(inputs)
    (output / 'native.tsv').write_bytes(captured)
    fixture = ROOT / 'rust/crates/mds-bullet/tests/activation_data'
    for name, data in [('inputs.tsv', inputs), ('native.tsv', captured)]:
        prefix = b''.join(data.splitlines(keepends=True)[:compact_rows])
        if args.record:
            (fixture / name).write_bytes(prefix)
        assert (fixture / name).read_bytes() == prefix, name + ' differs from complete frozen prefix'
    binary = output / 'rust-activation'
    common = ['--edition=2021', '--test', '-D', 'warnings', '-O', HERE / 'harness.rs', '--extern', f'mds_crtmath={output / "libmds_crtmath.rlib"}']
    run([*rustc, *common, '-o', binary])
    run(['rustup', 'run', '1.95.0', 'clippy-driver', *common, '-o', output / 'clippy-activation'])
    run([binary])
    environment['MDS_ACTIVATION_INPUTS'] = str(output / 'inputs.tsv')
    environment['MDS_ACTIVATION_NATIVE'] = str(output / 'native.tsv')
    run([binary])
    environment.pop('MDS_ACTIVATION_INPUTS')
    environment.pop('MDS_ACTIVATION_NATIVE')
    run([sys.executable, HERE / 'mutations.py', '--out-dir', output / 'mutations', '--crt-rlib', output / 'libmds_crtmath.rlib'])
    files = [*HERE.glob('*.*'), *fixture.glob('*.tsv'), *src.rglob('*.h'), *native_sources,
             *shim.rglob('*.h'), *crt.parent.rglob('*.rs'),
             ROOT / 'rust/crates/mds-bullet/src/core/activation.rs', ROOT / 'rust/crates/mds-bullet/src/core/math.rs',
             ROOT / 'rust/crates/mds-bullet/tests/pure_bullet/activation.rs',
             ROOT / 'rust/crates/mds-bullet/tests/pure_bullet.rs', ROOT / 'rust/crates/mds-bullet/src/core/mod.rs',
             ROOT / '.github/workflows/bullet-primitives.yml', output / 'inputs.tsv', output / 'native.tsv']
    (output / 'sha256.json').write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, indent=2) + '\n')
    provenance = [platform.platform(), subprocess.check_output([os.environ.get('CXX', 'clang++'), '--version'], text=True),
                  subprocess.check_output(['rustup', 'run', '1.95.0', 'rustc', '-Vv'], text=True)]
    (output / 'provenance.txt').write_text('\n'.join(provenance))
    compact_scenarios = sum(line.split()[1] == b'reset' for line in inputs.splitlines()[:compact_rows])
    summary = {'scenarios': scenarios, 'snapshots': len(captured.splitlines()), 'compact_scenarios': compact_scenarios, 'compact_snapshots': compact_rows,
               'native_sources_modified': False, 'masked_words': 0}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
