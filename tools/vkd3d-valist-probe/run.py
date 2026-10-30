#!/usr/bin/env python3
"""Isolated native consumer experiment. No product library or Cargo workspace."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

RUNTIME_REJECTIONS = {
    'wrong-slot': 'first_int',
    'wrong-offset': 'first_int',
    'wrong-promotion': 'promoted_double',
    'wrong-copy': 'independent_copy',
}


def check_runtime_rejection(code, output, field):
    markers = [line for line in output.splitlines() if 'VALIST_REJECT' in line]
    if code != 86 or markers != ['VALIST_REJECT field=' + field]:
        raise AssertionError(('unexpected runtime rejection', code, field, markers))


def check_compile_rejection(code, output, source):
    diagnostics = [json.loads(line) for line in output.splitlines()]
    errors = [d for d in diagnostics if d.get('level') == 'error']
    typed = [d for d in errors if (d.get('code') or {}).get('code') == 'E0308']
    expected = {
        'let _ = Slot { double: 3.25f32 };': 'expected `f64`, found `f32`',
        'let _ = Slot { int: -7i8 };': 'expected `i32`, found `i8`',
        'let _ = Slot { wide: 1u128 };': 'expected `i64`, found `u128`',
    }
    found = {}
    for diagnostic in typed:
        spans = [s for s in diagnostic['spans'] if s['is_primary']]
        if len(spans) != 1 or Path(spans[0]['file_name']).resolve() != source.resolve():
            raise AssertionError('unexpected type error source')
        span = spans[0]
        text = '\n'.join(t['text'] for t in span['text']).strip()
        if text in found:
            raise AssertionError('duplicate type rejection')
        found[text] = span['label']
    other = [d for d in errors if d not in typed]
    if (code != 1 or len(typed) != 3 or found != expected or len(other) != 1
            or other[0].get('message') != 'aborting due to 3 previous errors'):
        raise AssertionError('expected only f32, i8, u128 E0308 rejections')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--expect', required=True, choices=['apple-arm64', 'linux-x64', 'linux-arm64', 'windows-x64'])
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for name in ['RUSTC_BOOTSTRAP', 'RUSTFLAGS', 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'CFLAGS']:
        env.pop(name, None)
    records = []

    def hashes():
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}

    def run(argv, name, negative=None):
        try:
            result = subprocess.run(argv, env=env, cwd=out, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=60)
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b'', error.stderr or b''
            (out / (name + '.log')).write_bytes(stdout + stderr)
            records.append({'argv': argv, 'exit': None, 'log': name + '.log',
                            'timed_out': True, 'timeout_seconds': error.timeout,
                            'stdout': stdout.decode(errors='replace'),
                            'stderr': stderr.decode(errors='replace')})
            raise
        (out / (name + '.log')).write_bytes(result.stdout)
        records.append({'argv': argv, 'exit': result.returncode, 'log': name + '.log'})
        print(name, result.returncode, result.stdout.decode(errors='replace'), flush=True)
        if negative == 'compile':
            check_compile_rejection(result.returncode, result.stdout.decode(errors='replace'), root / 'probe.rs')
        elif negative is not None:
            check_runtime_rejection(result.returncode, result.stdout.decode(errors='replace'), negative)
        elif result.returncode != 0:
            raise AssertionError(name)
        return result.stdout.decode(errors='replace')

    start = hashes()
    try:
        host = (platform.system(), platform.machine().lower())
        actual = {('Darwin', 'arm64'): 'apple-arm64', ('Linux', 'x86_64'): 'linux-x64',
                  ('Linux', 'aarch64'): 'linux-arm64', ('Windows', 'amd64'): 'windows-x64'}.get(host)
        assert actual == args.expect, (host, actual, args.expect)
        rust = run(['rustc', '+1.95.0', '-Vv'], 'rust-version')
        assert 'release: 1.95.0\n' in rust
        assert {'apple-arm64': 'aarch64-apple-darwin', 'linux-x64': 'x86_64-unknown-linux-gnu',
                'linux-arm64': 'aarch64-unknown-linux-gnu', 'windows-x64': 'x86_64-pc-windows-msvc'}[actual] in rust
        cc = 'clang'
        run([cc, '--version'], 'c-version')
        source = str(root / 'consumer.c')
        run([cc, '-std=c11', '-dM', '-E', source], 'compiler-macros')
        run([cc, '-std=c11', '-Xclang', '-fdump-record-layouts-complete', '-fsyntax-only', source], 'c-layout')
        run([cc, '-std=c11', '-S', '-emit-llvm', source, '-o', str(out / 'consumer.ll')], 'c-ir')
        obj = out / ('consumer.obj' if actual == 'windows-x64' else 'consumer.o')
        run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-O0', '-c', source, '-o', str(obj)], 'c-compile')
        lib = out / ('consumer.lib' if actual == 'windows-x64' else 'libconsumer.a')
        if actual == 'windows-x64':
            run(['llvm-ar', 'rcs', str(lib), str(obj)], 'archive')
        else:
            run(['ar', 'rcs', str(lib), str(obj)], 'archive')
        binary = out / ('probe.exe' if actual == 'windows-x64' else 'probe')
        run(['rustc', '+1.95.0', '--edition=2024', '-Dwarnings', str(root / 'probe.rs'),
             '-L', str(out), '-l', 'static=consumer', '-o', str(binary)], 'rust-compile')
        run(['rustc', '+1.95.0', '--edition=2024', '--cfg', 'reject_unpromoted', '--error-format=json',
             str(root / 'probe.rs'), '-L', str(out), '-l', 'static=consumer',
             '-o', str(out / 'unsupported')], 'reject-unpromoted', negative='compile')
        run([str(binary), 'valid'], 'valid')
        for mode, field in RUNTIME_REJECTIONS.items():
            run([str(binary), mode], mode, negative=field)
    finally:
        final = hashes()
        receipt = {'host': platform.platform(), 'expected': args.expect, 'commands': records,
                   'source_start': start, 'source_final': final, 'source_unchanged': start == final,
                   'artifacts': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted(out.iterdir()) if p.is_file() and p.name != 'receipt.json'}}
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        assert start == final, 'source changed during probe'


if __name__ == '__main__':
    main()
