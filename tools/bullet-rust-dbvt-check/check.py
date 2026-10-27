#!/usr/bin/env python3
"""Capture unmodified btDbvt with controlled real addresses, then compare Rust."""
import argparse
import hashlib
import importlib.util
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
        if not (profile[key] == selected):
            raise AssertionError((key, profile, expected))
    if not (profile['BT_HAS_ALIGNED_ALLOCATOR'] == '0'):
        raise AssertionError(profile)
    if not (profile['BT_USE_DOUBLE_PRECISION'] == '0'):
        raise AssertionError(profile)
    if expected == 'sse':
        if not (profile['WIN32'] == '1' and profile['BT_USE_SSE'] == '1'):
            raise AssertionError(profile)
        if not (profile['DBVT_USE_TEMPLATE'] == '1'):
            raise AssertionError(profile)
    if ffi_default:
        if not (profile['WIN32'] == '0' and profile['BT_USE_SSE'] == '1'):
            raise AssertionError(profile)
    return profile


def validate_select(data, expected):
    rows = data.decode().splitlines()
    if not (len(rows) == 4):
        raise AssertionError('incomplete directed Select capture')
    topology = rows[2].split('|')[1]
    shape = re.sub(r',\d+', '', topology)
    if not (shape == ('B(1;B(2;3))' if expected == 'sse' else 'B(B(1;3);2)')):
        raise AssertionError((expected, shape))


def provenance(out):
    tracked = subprocess.check_output(['git', 'ls-files', '-z', 'recipes/bullet275/bullet-src/src',
                                      'rust/crates/mds-bullet', 'rust/crates/mds-bullet-sys',
                                      'tools/bullet-rust-dbvt-check', 'tools/bullet-dbvt-cmake-reference', 'rust/Cargo.lock',
                                      '.github/workflows/bullet-dbvt-hosted.yml'], cwd=ROOT)
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
              for p in tracked.decode().split('\0') if p and (ROOT / p).is_file()}
    data = dict(commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
                platform=platform.platform(), machine=platform.machine(), python=sys.version,
                runner={k: os.environ.get(k) for k in ('RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion')},
                compiler_environment={k: os.environ.get(k) for k in ('CXX', 'CL', '_CL_', 'CXXFLAGS')},
                source_sha256=hashes,
                source_lf_sha256={p: hashlib.sha256((ROOT / p).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for p in hashes})
    (out / 'provenance.json').write_text(json.dumps(data, indent=2) + '\n')


POLICIES = {'sse': 'mmd-win64-sse', 'generic': 'generic-reference'}


def reference_module():
    spec = importlib.util.spec_from_file_location('cmake_dbvt_reference', ROOT / 'tools/bullet-dbvt-cmake-reference/check.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_corpus(data):
    # Keep original row bytes after CRLF/LF normalization; extensions append only.
    lines = data.splitlines()
    if hashlib.sha256(b'\n'.join(lines[:2326]) + b'\n').hexdigest() != '860efaddcfae02b859f18d6d5d0dbf6480effe8836b058f02b360a24e331cf93' or len(lines) <= 2326:
        raise ValueError('frozen operation prefix changed or extension missing')
    return len(lines)


def verify_numeric_policies(out):
    """Run both real Rust policies against raw actual-Windows numeric captures."""
    reference = reference_module()
    core = ROOT / 'rust/crates/mds-bullet/src/core'
    source = reference.RUST_DRIVER.replace('DBVT', (core / 'dbvt.rs').as_posix()).replace('PAIR_CACHE', (core / 'pair_cache.rs').as_posix())
    driver = out / 'numeric.rs'
    driver.write_text(source)
    rustc = ['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '-C', 'opt-level=2']
    run([*rustc, '--crate-name', 'mds_crtmath', '--crate-type', 'rlib', '--out-dir', out,
         ROOT / 'rust/crates/mds-crtmath/src/lib.rs'], out, 'numeric-crt-build', cwd=ROOT / 'rust')
    run([*rustc, '--crate-name', 'dbvt_math', '--crate-type', 'rlib', '--out-dir', out,
         '--extern', f'mds_crtmath={out / "libmds_crtmath.rlib"}', core / 'math.rs'], out, 'numeric-math-build', cwd=ROOT / 'rust')
    exe = out / ('numeric.exe' if os.name == 'nt' else 'numeric')
    run([*rustc, '--extern', f'dbvt_math={out / "libdbvt_math.rlib"}', '-L', f'dependency={out}', driver,
         '-o', exe], out, 'numeric-build', cwd=ROOT / 'rust')
    (out / 'numeric-binary.json').write_text(json.dumps(dict(binary=exe.name, sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
        source=driver.name, source_sha256=hashlib.sha256(driver.read_bytes()).hexdigest(), build_command='numeric-build-command.json'), indent=2) + '\n')
    fixtures = ROOT / 'rust/crates/mds-bullet/tests/dbvt_data'
    data = (fixtures / 'inputs.tsv').read_bytes()
    expected = reference.rows((fixtures / 'inline-aabb.tsv').read_bytes(), 13)
    selected = (fixtures / 'select.tsv').read_bytes().splitlines()
    results = {}
    for policy in POLICIES.values():
        actual = reference.rows(run([exe, policy, 'aabb'], out, policy + '-numeric', capture=True, input=data), 13)
        actual_select = run([exe, policy, 'select'], out, policy + '-select', capture=True).splitlines()
        mismatches = [i for i, (a, b) in enumerate(zip(actual, expected)) if a != b]
        if policy == 'mmd-win64-sse':
            if mismatches or actual_select != selected:
                raise ValueError('production Rust policy differs from actual Windows numeric capture')
        elif mismatches != list(range(27, 51)) or actual_select == selected:
            raise ValueError('wrong-policy Rust binary did not produce expected semantic mismatches')
        results[policy] = dict(numeric_mismatch_cases=mismatches, select_matches=actual_select == selected)
    (out / 'numeric-policy-results.json').write_text(json.dumps(results, indent=2) + '\n')


def replay(out, captures):
    inputs = (captures / 'inputs.tsv').read_bytes()
    count = validate_corpus(inputs)
    for order in range(4):
        if len((captures / f'native-{order}.tsv').read_bytes().splitlines()) != count:
            raise ValueError('incomplete Windows-sourced replay capture')
    captured_provenance = json.loads((captures / 'provenance.json').read_text())
    current = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    if captured_provenance['commit'] != current:
        raise ValueError('Windows replay source commit differs from current checkout')
    for path, expected in captured_provenance['source_lf_sha256'].items():
        if hashlib.sha256((ROOT / path).read_bytes().replace(b'\r\n', b'\n')).hexdigest() != expected:
            raise ValueError(f'Windows replay source bytes differ: {path}')
    observed = validate_profile((captures / 'original-profile.txt').read_bytes(), 'sse')
    (out / 'replay-provenance.json').write_text(json.dumps(dict(
        classification='Windows-sourced controlled capture replay; not local native execution',
        capture_provenance=captured_provenance, profile=observed,
        capture_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in captures.iterdir() if p.is_file()},
        rust_policy='mmd-win64-sse'), indent=2) + '\n')
    env = dict(os.environ, DBVT_FIXTURES=str(captures), DBVT_POLICY='mmd-win64-sse')
    run(['rustup', 'run', '1.95.0', 'cargo', 'test', '--locked', '--manifest-path',
         HERE / 'Cargo.toml', '--release'], out, 'windows-sourced-rust-tests', env=env, cwd=ROOT / 'rust')
    verify_numeric_policies(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--rust-policy', choices=tuple(POLICIES.values()), required=True)
    parser.add_argument('--replay-dir', type=Path)
    parser.add_argument('--expected-profile', choices=('generic', 'sse'),
                        default='sse' if os.name == 'nt' else 'generic')
    parser.add_argument('--expected-arch', choices=('x64', 'arm64'))
    args = parser.parse_args()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    provenance(out)
    if args.replay_dir:
        if args.rust_policy != 'mmd-win64-sse':
            raise ValueError('Windows replay requires production SSE policy')
        replay(out, args.replay_dir.resolve())
        return
    if args.rust_policy != POLICIES[args.expected_profile]:
        raise ValueError('native comparison requires explicit matching Rust policy')
    arch = {'amd64': 'x64', 'x86_64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine().lower())
    if args.expected_arch:
        if not (arch == args.expected_arch):
            raise AssertionError((platform.machine(), args.expected_arch))
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
    if not (header.count(marker) == 1):
        raise AssertionError()
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
                          HERE / 'Cargo.toml', '--release', '--bin', 'dbvt-lifecycle', '--', args.rust_policy],
                         out, 'rust-lifecycle', capture=True, cwd=ROOT / 'rust')
    (out / 'rust-lifecycle.tsv').write_bytes(rust_lifecycle)
    # Windows iostream emits CRLF while Rust writes LF. Compare the same event records.
    if not (rust_lifecycle.splitlines() == native_lifecycle.splitlines()):
        raise AssertionError('actual allocator release order differs from native')
    inputs = run([sys.executable, HERE / 'cases.py'], out, 'cases', capture=True)
    count = validate_corpus(inputs)
    if not (len(native_lifecycle.splitlines()) == 10):
        raise AssertionError('lifecycle corpus changed')
    (out / 'inputs.tsv').write_bytes(inputs)
    for order in range(4):
        captured = run([out / ('oracle' + suffix), str(order)], out, f'native-{order}', capture=True, input=inputs)
        if not (len(captured.splitlines()) == count):
            raise AssertionError((order, 'incomplete capture'))
        (out / f'native-{order}.tsv').write_bytes(captured)
    if msvc:
        for order in range(4):
            captured = run([diagnostic, str(order)], out, f'ffi-default-native-{order}', capture=True, input=inputs)
            if not (len(captured.splitlines()) == count):
                raise AssertionError((order, 'incomplete diagnostic capture'))
    env = dict(os.environ, DBVT_FIXTURES=str(out), DBVT_POLICY=args.rust_policy)
    run(['rustup', 'run', '1.95.0', 'cargo', 'test', '--locked', '--manifest-path',
         HERE / 'Cargo.toml', '--release'], out, 'rust-tests', env=env, cwd=ROOT / 'rust')
    verify_numeric_policies(out)
    print(f'{count * 3} strict snapshots, {count} ordinary allocator comparisons and 10 lifecycle cases compared.')


if __name__ == '__main__':
    main()
