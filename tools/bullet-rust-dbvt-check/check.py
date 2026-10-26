#!/usr/bin/env python3
"""Capture unmodified btDbvt with controlled real addresses, then compare Rust."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SRC = ROOT / 'recipes/bullet275/bullet-src/src'


def native_command(compiler, source, output, *, msvc, ffi_default=False):
    if msvc:
        flags = ['/nologo', '/std:c++17', '/O2', '/MD', '/EHsc', '/fp:precise',
                 '/DBT_NO_PROFILE=1', f'/I{SRC}', f'/Fo{output.parent}{os.sep}']
        if ffi_default:
            flags += [f'/FI{ROOT / "rust/crates/mds-bullet-sys/shim/det_math.h"}']
        else:
            flags += ['/DWIN32']
        return [compiler, *flags, *source, f'/Fe{output}']
    return [compiler, '-std=c++17', '-O2', '-fdeclspec', '-ffp-contract=off',
            '-fno-fast-math', '-DBT_NO_PROFILE=1', '-I', SRC, *source, '-o', output]


def run(command, out, name, *, capture=False, cwd=ROOT, **kwargs):
    command = list(map(str, command))
    (out / f'{name}-command.json').write_text(json.dumps(command, indent=2) + '\n')
    print(subprocess.list2cmdline(command), flush=True)
    with (out / f'{name}-stdout.log').open('wb') as stdout, \
            (out / f'{name}-stderr.log').open('wb') as stderr:
        result = subprocess.run(command, cwd=cwd, stdout=stdout, stderr=stderr, timeout=300, **kwargs)
    errors = (out / f'{name}-stderr.log').read_bytes()
    if errors:
        print(errors.decode(errors='replace'), file=sys.stderr, flush=True)
    data = (out / f'{name}-stdout.log').read_bytes()
    if not capture:
        print(data.decode(errors='replace'), flush=True)
    result.check_returncode()
    return data


def validate_profile(data, expected, *, ffi_default=False):
    profile = dict(line.split('=', 1) for line in data.decode().splitlines())
    selected = '1' if expected == 'sse' else '0'
    for key in ('DBVT_SELECT_IMPL', 'DBVT_MERGE_IMPL', 'DBVT_INT0_IMPL'):
        assert profile[key] == selected, (key, profile, expected)
    assert profile['BT_HAS_ALIGNED_ALLOCATOR'] == '0', profile
    assert profile['BT_USE_DOUBLE_PRECISION'] == '0', profile
    if expected == 'sse':
        assert profile['WIN32'] == '1' and profile['BT_USE_SSE'] == '1', profile
        assert profile['DBVT_USE_TEMPLATE'] == '1', profile
    if ffi_default:
        assert profile['WIN32'] == '0' and profile['BT_USE_SSE'] == '1', profile
    return profile


def validate_select(data, expected):
    rows = data.decode().splitlines()
    assert len(rows) == 4, 'incomplete directed Select capture'
    topology = rows[2].split('|')[1]
    shape = re.sub(r',\d+', '', topology)
    assert shape == ('B(1;B(2;3))' if expected == 'sse' else 'B(B(1;3);2)'), (expected, shape)


def provenance(out):
    tracked = subprocess.check_output(['git', 'ls-files', '-z', 'recipes/bullet275/bullet-src/src',
                                      'rust/crates/mds-bullet', 'rust/crates/mds-bullet-sys',
                                      'tools/bullet-rust-dbvt-check', 'rust/Cargo.lock',
                                      '.github/workflows/bullet-dbvt-hosted.yml'], cwd=ROOT)
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
              for p in tracked.decode().split('\0') if p and (ROOT / p).is_file()}
    data = dict(commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
                platform=platform.platform(), machine=platform.machine(), python=sys.version,
                runner={k: os.environ.get(k) for k in ('RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion')},
                compiler_environment={k: os.environ.get(k) for k in ('CXX', 'CL', '_CL_', 'CXXFLAGS')},
                source_sha256=hashes)
    (out / 'provenance.json').write_text(json.dumps(data, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--expected-profile', choices=('generic', 'sse'),
                        default='sse' if os.name == 'nt' else 'generic')
    parser.add_argument('--expected-arch', choices=('x64', 'arm64'))
    args = parser.parse_args()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    provenance(out)
    arch = {'amd64': 'x64', 'x86_64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine().lower())
    if args.expected_arch:
        assert arch == args.expected_arch, (platform.machine(), args.expected_arch)
    msvc = os.name == 'nt'
    compiler = os.environ.get('CXX', 'cl' if msvc else 'clang++')
    suffix = '.exe' if msvc else ''
    run([compiler, '/?'] if msvc else [compiler, '--version'], out, 'compiler-version')
    run(['rustup', 'run', '1.95.0', 'rustc', '-Vv'], out, 'rust-version')
    run(['rustup', 'run', '1.95.0', 'cargo', '-V'], out, 'cargo-version', cwd=ROOT / 'rust')
    header = (SRC / 'BulletCollision/BroadphaseCollision/btDbvt.h').read_text()
    marker = '#undef DBVT_USE_MEMMOVE'
    keys = ('DBVT_SELECT_IMPL', 'DBVT_MERGE_IMPL', 'DBVT_INT0_IMPL',
            'DBVT_USE_TEMPLATE', 'DBVT_USE_INTRINSIC_SSE')
    assert header.count(marker) == 1
    observation = '// Altered profile-only copy: preserve configuration before PP cleanup.\n'
    observation += ''.join(f'constexpr int observed_{key} = {key};\n' for key in keys)
    observed_header = out / 'observed-btDbvt.h'
    observed_header.write_text(header.replace(marker, observation + marker))
    (out / 'observed-header.sha256').write_text(hashlib.sha256(observed_header.read_bytes()).hexdigest() + '\n')
    for profile in (['original', 'ffi-default'] if msvc else ['original']):
        exe = out / (profile + '-profile' + suffix)
        command = native_command(compiler, [HERE / 'profile.cpp'], exe, msvc=msvc,
                                 ffi_default=profile == 'ffi-default')
        command.insert(1, f'/I{out}' if msvc else f'-I{out}')
        run(command, out, profile + '-profile-build')
        captured = run([exe], out, profile + '-profile', capture=True)
        (out / (profile + '-profile.txt')).write_bytes(captured)
        validate_profile(captured, 'generic' if profile == 'ffi-default' else args.expected_profile,
                         ffi_default=profile == 'ffi-default')
    for name in ('oracle', 'lifecycle'):
        command = native_command(compiler, [HERE / f'{name}.cpp',
                                 SRC / 'BulletCollision/BroadphaseCollision/btDbvt.cpp',
                                 SRC / 'LinearMath/btAlignedAllocator.cpp'],
                                 out / (name + suffix), msvc=msvc)
        run(command, out, name + '-build')
    directed = b'i 1 0.5 8388608 0.5 0.5 8388608 0.5\ni 2 1 8388608 0 1 8388608 0\ni 3 0 0 0 0 0 0\nv -1 -1 -1 2 8388609 2\n'
    (out / 'select-inputs.tsv').write_bytes(directed)
    selected = run([out / ('oracle' + suffix), '0'], out, 'original-select', capture=True, input=directed)
    validate_select(selected, args.expected_profile)
    if msvc:
        diagnostic = out / ('ffi-default-oracle' + suffix)
        command = native_command(compiler, [HERE / 'oracle.cpp',
                                 SRC / 'BulletCollision/BroadphaseCollision/btDbvt.cpp',
                                 SRC / 'LinearMath/btAlignedAllocator.cpp'], diagnostic,
                                 msvc=True, ffi_default=True)
        run(command, out, 'ffi-default-oracle-build')
        selected = run([diagnostic, '0'], out, 'ffi-default-select', capture=True, input=directed)
        validate_select(selected, 'generic')
    native_lifecycle = run([out / ('lifecycle' + suffix)], out, 'native-lifecycle', capture=True)
    (out / 'native-lifecycle.tsv').write_bytes(native_lifecycle)
    rust_lifecycle = run(['rustup', 'run', '1.95.0', 'cargo', 'run', '--locked', '--manifest-path',
                          HERE / 'Cargo.toml', '--release', '--bin', 'dbvt-lifecycle'],
                         out, 'rust-lifecycle', capture=True, cwd=ROOT / 'rust')
    (out / 'rust-lifecycle.tsv').write_bytes(rust_lifecycle)
    # Windows iostream emits CRLF while Rust writes LF. Compare the same event records.
    assert rust_lifecycle.splitlines() == native_lifecycle.splitlines(), 'actual allocator release order differs from native'
    inputs = run([sys.executable, HERE / 'cases.py'], out, 'cases', capture=True)
    assert len(inputs.splitlines()) == 2326, 'operation corpus changed'
    assert len(native_lifecycle.splitlines()) == 10, 'lifecycle corpus changed'
    (out / 'inputs.tsv').write_bytes(inputs)
    for order in range(4):
        captured = run([out / ('oracle' + suffix), str(order)], out, f'native-{order}', capture=True, input=inputs)
        assert len(captured.splitlines()) == 2326, (order, 'incomplete capture')
        (out / f'native-{order}.tsv').write_bytes(captured)
    if msvc:
        for order in range(4):
            captured = run([diagnostic, str(order)], out, f'ffi-default-native-{order}', capture=True, input=inputs)
            assert len(captured.splitlines()) == 2326, (order, 'incomplete diagnostic capture')
    env = dict(os.environ, DBVT_FIXTURES=str(out))
    run(['rustup', 'run', '1.95.0', 'cargo', 'test', '--locked', '--manifest-path',
         HERE / 'Cargo.toml', '--release'], out, 'rust-tests', env=env, cwd=ROOT / 'rust')
    print('6,978 strict snapshots, 2,326 ordinary allocator comparisons and 10 lifecycle cases compared.')


if __name__ == '__main__':
    main()
