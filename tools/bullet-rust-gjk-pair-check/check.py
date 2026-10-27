#!/usr/bin/env python3
"""Collect complete source-bound outer GJK observations before compatibility approval."""
import argparse
import hashlib
import importlib.util
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
sys.path.insert(0, str(HERE.parent / 'bullet-rust-support-check'))
from host_profiles import rows, native_command, compiler_version, host


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def source_hashes():
    paths = subprocess.check_output(['git', '-C', ROOT, 'ls-files', '-z',
        'recipes/bullet275/bullet-src/src', 'rust/crates/mds-bullet',
        'rust/crates/mds-bullet-sys/shim', 'rust/crates/mds-crtmath',
        'tools/bullet-rust-gjk-pair-check', 'tools/bullet-rust-gjk-epa-check',
        'tools/bullet-rust-support-check', '.github/workflows/bullet-outer-gjk-host-capture.yml']).decode().split('\0')
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in paths if path and (ROOT / path).is_file()}


def run(args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT / 'rust', **kwargs)


def transport(data, count):
    ending = 'CRLF' if data.count(b'\r\n') == count else 'LF'
    if data.count(b'\n') != count or not data.endswith(b'\n'):
        raise ValueError('Incomplete stream transport')
    if ending == 'CRLF':
        if data.count(b'\r') != count:
            raise ValueError('Mixed stream transport')
        text = data.replace(b'\r\n', b'\n')
    else:
        if b'\r' in data:
            raise ValueError('Mixed stream transport')
        text = data
    return text, {'rows': count, 'line_ending': ending,
                  'raw_sha256': hashlib.sha256(data).hexdigest(),
                  'lf_sha256': hashlib.sha256(text).hexdigest()}


def stream(data, count, start=0):
    text, facts = transport(data, count)
    rows(text, 'gjk-pair', count, start)
    return text, facts


def capture_inputs(output, inputs):
    (output / 'inputs.tsv').write_bytes(inputs)
    normalized, full = transport(inputs, 5081)
    facts = {'inputs.tsv': full}
    fixture = ROOT / 'rust/crates/mds-bullet/tests/gjk_pair_data'
    for name, count, data, expected in [
            ('compact', COMPACT, b''.join(inputs.splitlines(keepends=True)[:COMPACT]), 'inputs.tsv'),
            ('fallback', 6, b''.join(inputs.splitlines(keepends=True)[-6:]), 'fallback-inputs.tsv')]:
        filename = f'{name}-inputs.tsv'
        (output / filename).write_bytes(data)
        text, facts[filename] = transport(data, count)
        assert (fixture / expected).read_bytes() == text, 'Frozen inputs changed'
    write_json(output / 'input-transport.json', facts)
    return normalized


def inventory(native, rust, count, start=0):
    differences = []
    for (a, names), (b, other) in zip(rows(native, 'gjk-pair', count, start), rows(rust, 'gjk-pair', count, start)):
        left, right = dict(zip(names, a[1:])), dict(zip(other, b[1:]))
        differences.extend([int(a[0]), name, left.get(name), right.get(name)]
                           for name in dict.fromkeys([*left, *right]) if left.get(name) != right.get(name))
    return differences


def audit(output):
    facts = {'host': host(), 'collection': 'incomplete', 'compatibility': 'FAIL',
             'profile_known': False, 'mutations': 'not-run', 'streams': {}}
    normalized = {}
    for corpus, count, start in [('full', 5081, 0), ('compact', COMPACT, 0), ('fallback', 6, 5075)]:
        for implementation in ['native', 'observed', 'rust']:
            filename = f'{implementation}.tsv' if corpus == 'full' else f'{corpus}-{implementation}.tsv'
            path = output / filename
            if path.exists():
                try:
                    normalized[corpus, implementation], facts['streams'][filename] = stream(path.read_bytes(), count, start)
                except ValueError as error:
                    facts['streams'][filename] = {'error': str(error)}
    if len(normalized) == 9:
        facts['collection'] = 'complete'
        facts['native_observed_equal'] = all(normalized[c, 'native'] == normalized[c, 'observed'] for c in ['full', 'compact', 'fallback'])
        facts['native_rust_differences'] = inventory(normalized['full', 'native'], normalized['full', 'rust'], 5081)
        fixture = ROOT / 'rust/crates/mds-bullet/tests/gjk_pair_data/native.tsv'
        facts['frozen_native_differences'] = inventory(fixture.read_bytes(), normalized['compact', 'native'], COMPACT)
    if (output / 'measured-profile.json').exists():
        facts['profile_known'] = True
        gate = json.loads((output / 'mutation-gate.json').read_text())
        facts['mutations'] = gate['status']
        integrity = output / 'integrity.json'
        unchanged = not integrity.exists() or json.loads(integrity.read_text())['source_and_fixtures_unchanged']
        facts['compatibility'] = 'PASS' if gate['status'] == 'passed' and unchanged else 'FAIL'
    write_json(output / 'host-profile.json', facts)
    return facts


def capture(output, environment):
    test_fallback_coverage()
    src = ROOT / 'recipes/bullet275/bullet-src/src'
    shim = ROOT / 'rust/crates/mds-bullet-sys/shim'
    crt = ROOT / 'rust/crates/mds-crtmath/src/lib.rs'
    provenance = [platform.platform(), compiler_version(), subprocess.check_output(['rustup', 'run', '1.95.0', 'rustc', '-Vv'], text=True)]
    (output / 'provenance.txt').write_text('\n'.join(provenance))
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'staticlib', '-O', crt, '-o', output / 'libmds_crtmath.a'], env=environment)
    native_sources = sorted((src / 'BulletCollision').rglob('*.cpp')) + sorted((src / 'LinearMath').glob('*.cpp'))
    executable = output / ('native-gjk-pair.exe' if os.name == 'nt' else 'native-gjk-pair')
    command = [os.environ.get('CXX', 'clang++'), '-std=c++17', '-O2', '-ffp-contract=off',
               '-fno-fast-math', '-fdeclspec', '-w', '-DBT_NO_PROFILE=1',
               '-I', shim / 'sse_emu', '-I', src, '-I', shim,
               '-include', shim / 'det_math.h', HERE / 'oracle.cpp', *native_sources,
               output / 'libmds_crtmath.a', '-o', executable]
    command += ['-Wl,-dead_strip'] if platform.system() == 'Darwin' else ['-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', '-ldl', '-lpthread', '-lm']
    write_json(output / 'native-command.json', list(map(str, command)))
    command = native_command(command, output, environment)
    write_json(output / 'effective-native-command.json', command)
    run(command, env=environment)
    inputs = subprocess.check_output([sys.executable, HERE / 'cases.py'])
    capture_inputs(output, inputs)
    (output / 'native.tsv').write_bytes(subprocess.check_output([executable], input=inputs, env=environment))
    observation_error = None
    try:
        observe(src, command, executable, inputs, output, environment)
    except (AssertionError, subprocess.CalledProcessError) as error:
        observation_error = str(error)
        write_json(output / 'observer-failure.json', {'error': observation_error})
    run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'rlib', '-O', crt, '-o', output / 'libmds_crtmath.rlib'], env=environment)
    env = dict(environment, MDS_GJK_PAIR_INPUTS=str(output / 'inputs.tsv'),
               MDS_GJK_PAIR_NATIVE=str(output / 'native.tsv'), MDS_GJK_PAIR_ACTUAL=str(output / 'rust.tsv'))
    spec = importlib.util.spec_from_file_location('outer_mutations', HERE / 'mutations.py')
    mutation_runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mutation_runner)
    result = mutation_runner.run_harness(None, None, output / 'full-rust', output / 'libmds_crtmath.rlib', env)
    write_json(output / 'full-rust-result.json', result)
    for implementation in ['native', 'observed', 'rust']:
        path = output / f'{implementation}.tsv'
        if path.exists():
            lines = path.read_bytes().splitlines(keepends=True)
            (output / f'compact-{implementation}.tsv').write_bytes(b''.join(lines[:COMPACT]))
            (output / f'fallback-{implementation}.tsv').write_bytes(b''.join(lines[-6:]))
    fallback = subprocess.check_output([executable], input=(output / 'fallback-inputs.tsv').read_bytes(), env=environment)
    (output / 'fallback-independent-native.tsv').write_bytes(fallback)
    assert fallback == (output / 'fallback-native.tsv').read_bytes(), 'Fallback requires prior history'
    facts = audit(output)
    if observation_error or facts['collection'] != 'complete':
        raise ValueError('Collection incomplete or observer coverage failed')
    from measured_profiles import validate
    receipt = validate(output)
    write_json(output / 'measured-profile.json', receipt)
    run([sys.executable, HERE / 'mutations.py', '--out-dir', output / 'mutations',
         '--crt-rlib', output / 'libmds_crtmath.rlib', '--inputs', output / 'inputs.tsv',
         '--native', output / 'native.tsv'], env=environment)
    write_json(output / 'mutation-gate.json', {'status': 'passed', 'required': 13})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('Capture directory must be empty to exclude stale observations')
    environment = {k: v for k, v in os.environ.items() if not k.startswith('MDS_GJK_PAIR_')}
    temporary = output / 'tmp'
    temporary.mkdir()
    environment['TMPDIR'] = str(temporary)
    before = source_hashes()
    write_json(output / 'source-before.json', before)
    (output / 'source-head.txt').write_bytes(subprocess.check_output(['git', '-C', ROOT, 'rev-parse', 'HEAD']))
    write_json(output / 'mutation-gate.json', {'status': 'not-run', 'reason': 'No approved outer GJK host profiles'})
    try:
        capture(output, environment)
    except Exception as error:
        write_json(output / 'failure.json', {'type': type(error).__name__, 'error': str(error)})
        raise
    finally:
        after = source_hashes()
        write_json(output / 'source-after.json', after)
        write_json(output / 'integrity.json', {'source_and_fixtures_unchanged': before == after,
                   'changed': [p for p in before.keys() | after.keys() if before.get(p) != after.get(p)]})
        audit(output)
        write_json(output / 'sha256.json', {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in output.rglob('*') if p.is_file() and p != output / 'sha256.json'})
        if before != after:
            raise ValueError('Source or frozen fixture integrity changed')


if __name__ == '__main__':
    main()
