#!/usr/bin/env python3
"""Isolated native consumer experiment. No product library or Cargo workspace."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

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

def run(argv, name, negative=False):
    result = subprocess.run(argv, env=env, cwd=out, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=60)
    (out / (name + '.log')).write_bytes(result.stdout)
    records.append({'argv': argv, 'exit': result.returncode, 'log': name + '.log'})
    print(name, result.returncode, result.stdout.decode(errors='replace'), flush=True)
    assert (result.returncode != 0) if negative else (result.returncode == 0), name
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
    run(['rustc', '+1.95.0', '--edition=2024', '--cfg', 'reject_unpromoted',
         str(root / 'probe.rs'), '-L', str(out), '-l', 'static=consumer',
         '-o', str(out / 'unsupported')], 'reject-unpromoted', negative=True)
    run([str(binary), 'valid'], 'valid')
    for mode in ['wrong-slot', 'wrong-offset', 'wrong-promotion', 'wrong-copy']:
        run([str(binary), mode], mode, negative=True)
finally:
    final = hashes()
    receipt = {'host': platform.platform(), 'expected': args.expect, 'commands': records,
               'source_start': start, 'source_final': final, 'source_unchanged': start == final,
               'artifacts': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(out.iterdir()) if p.is_file() and p.name != 'receipt.json'}}
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    assert start == final, 'source changed during probe'
