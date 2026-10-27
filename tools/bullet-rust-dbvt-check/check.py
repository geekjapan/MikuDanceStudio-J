#!/usr/bin/env python3
"""Capture unmodified btDbvt with controlled real addresses, then compare Rust."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
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
        if profile[key] != selected:
            raise AssertionError((key, profile, expected))
    if profile['BT_HAS_ALIGNED_ALLOCATOR'] != '0':
        raise AssertionError(profile)
    if profile['BT_USE_DOUBLE_PRECISION'] != '0':
        raise AssertionError(profile)
    if expected == 'sse':
        if profile['WIN32'] != '1' or profile['BT_USE_SSE'] != '1':
            raise AssertionError(profile)
        if profile['DBVT_USE_TEMPLATE'] != '1':
            raise AssertionError(profile)
    if ffi_default:
        if profile['WIN32'] != '0' or profile['BT_USE_SSE'] != '1':
            raise AssertionError(profile)
    return profile


def validate_select(data, expected):
    rows = data.decode().splitlines()
    if len(rows) != 4:
        raise AssertionError('incomplete directed Select capture')
    topology = rows[2].split('|')[1]
    shape = re.sub(r',\d+', '', topology)
    if shape != ('B(1;B(2;3))' if expected == 'sse' else 'B(B(1;3);2)'):
        raise AssertionError((expected, shape))


def provenance(out):
    tracked = subprocess.check_output(['git', 'ls-files', '-z', 'recipes/bullet275/bullet-src/src',
                                      'rust/crates/mds-bullet', 'rust/crates/mds-bullet-sys',
                                      'rust/crates/mds-crtmath',
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
        select_capture = run([exe, policy, 'select'], out, policy + '-select', capture=True)
        reference.validate_select(select_capture)
        actual_select = select_capture.splitlines()
        expected_select = selected if policy == 'mmd-win64-sse' else [b'2,3,1,']
        if actual_select != expected_select:
            raise ValueError('Rust policy differs from expected directed Select capture')
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
    for name in ['inputs.tsv', *(f'native-{order}.tsv' for order in range(4))]:
        shutil.copy2(captures / name, out / name)
    env = dict(os.environ, DBVT_FIXTURES=str(out), DBVT_POLICY='mmd-win64-sse')
    build = run(['rustup', 'run', '1.95.0', 'cargo', 'test', '--locked', '--manifest-path',
                 HERE / 'Cargo.toml', '--release', '--no-run', '--message-format=json'],
                out, 'windows-sourced-rust-tests-build', capture=True, cwd=ROOT / 'rust')
    executable = retain_test_binary(build, out)
    result = run([executable], out, 'windows-sourced-rust-tests', env=env, cwd=ROOT / 'rust', capture=True)
    validate_test_result(result)
    compare_streams(out)
    verify_numeric_policies(out)


def cargo_objects(data):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate Cargo JSON key')
            result[key] = value
        return result

    def finite_number(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('non-finite Cargo JSON number')
        return number

    objects = []
    finished = False
    for line in data.decode().splitlines():
        # Cargo cannot control stdout from other tools; raw logs retain those lines.
        if not line.startswith('{'):
            continue
        item = json.loads(line, object_pairs_hook=object_pairs,
                          parse_constant=finite_number, parse_float=finite_number)
        if not isinstance(item, dict) or not isinstance(item.get('reason'), str):
            raise ValueError('expected Cargo JSON object with a reason')
        if finished:
            raise AssertionError('Cargo JSON object after build-finished')
        if item['reason'] == 'build-finished':
            if item.get('success') is not True:
                raise AssertionError('Cargo build did not succeed')
            finished = True
        objects.append(item)
    if not finished:
        raise AssertionError('missing successful Cargo build-finished')
    return objects


def retain_test_binary(data, out):
    candidates = []
    for item in cargo_objects(data):
        if item.get('reason') != 'compiler-artifact':
            continue
        target = item.get('target')
        if not isinstance(target, dict) or not isinstance(item.get('profile'), dict):
            raise ValueError('malformed Cargo compiler-artifact')
        if target.get('name') != 'dbvt':
            continue
        if (target.get('kind') != ['test'] or
                not all(isinstance(value, str) and value for value in (
                    target.get('src_path'), item.get('manifest_path'), item.get('executable'))) or
                Path(target.get('src_path', '')).resolve() != (HERE / 'test.rs').resolve() or
                Path(item.get('manifest_path', '')).resolve() != (HERE / 'Cargo.toml').resolve() or
                item.get('profile', {}).get('test') is not True or not item.get('executable')):
            raise AssertionError('unexpected DBVT test artifact')
        candidates.append(Path(item['executable']))
    if len(candidates) != 1 or not candidates[0].is_file():
        raise AssertionError('expected exactly one existing DBVT test executable')
    source = candidates[0].resolve()
    executable = out / ('dbvt-tests.exe' if os.name == 'nt' else 'dbvt-tests')
    shutil.copy2(source, executable)
    raw = executable.read_bytes()
    if not raw or raw != source.read_bytes():
        raise AssertionError('DBVT test executable copy differs or is empty')
    (out / 'rust-test-binary.json').write_text(json.dumps(dict(
        source_path=str(source), retained_path=str(executable), bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(), cwd=str(ROOT / 'rust'),
        toolchain='1.95.0', argv=[str(executable)]), indent=2) + '\n')
    return executable


def validate_test_result(data):
    summaries = re.findall(rb'test result: (.+)', data)
    if len(summaries) != 1 or not re.fullmatch(
            rb'ok\. 11 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in .+',
            summaries[0]):
        raise AssertionError('expected all 11 DBVT tests with none ignored or filtered')


def parse_snapshot(line, *, rust=False):
    fields = line.split('|')
    if len(fields) != 4 or not re.fullmatch(r'\d+,-?\d+,\d+,[01]', fields[0]):
        raise AssertionError('malformed DBVT snapshot')
    if (rust and fields[2]) or (not rust and not re.fullmatch(r'(?:\d+,)*', fields[2])):
        raise AssertionError('malformed DBVT rank column')
    topology = fields[1]
    tokens = re.findall(r'_|(?:B|\d+)(?:,\d+){6}|[();]', topology)
    if ''.join(tokens) != topology:
        raise AssertionError('malformed DBVT topology')
    position = 0
    leaves = []

    def node(*, root=False):
        nonlocal position
        if position == len(tokens):
            raise AssertionError('truncated DBVT topology')
        token = tokens[position]
        position += 1
        if token in ('(', ')', ';') or (token == '_' and not root):
            raise AssertionError('malformed DBVT topology node')
        if token.startswith('B'):
            for delimiter in ('(', ';', ')'):
                if position == len(tokens) or tokens[position] != delimiter:
                    raise AssertionError('malformed DBVT topology branch')
                position += 1
                if delimiter != ')':
                    node()
        elif token != '_':
            leaves.append(token)

    node(root=True)
    if position != len(tokens):
        raise AssertionError('extra DBVT topology tokens')
    events = fields[3]
    if not re.fullmatch(r'(?:\d+(?::\d+)?,)*|[01](?:,\d+){6}', events):
        raise AssertionError('malformed DBVT events')
    return fields, sorted(leaves)


def query_set(events):
    result = []
    for event in events.split(','):
        if event:
            if ':' in event:
                a, b = map(int, event.split(':'))
                event = f'{min(a, b)}:{max(a, b)}'
            result.append(event)
    return sorted(result)


def compare_streams(out):
    inputs = (out / 'inputs.tsv').read_text().splitlines()
    if len(inputs) != 2355 or any(not line for line in inputs):
        raise AssertionError('operation corpus changed')
    for order in range(4):
        native = (out / f'native-{order}.tsv').read_text().splitlines()
        rust = (out / f'rust-{order}.tsv').read_text().splitlines()
        if len(native) != len(inputs) or len(rust) != len(inputs):
            raise AssertionError((order, 'incomplete or extra replay rows'))
        for i in range(len(inputs)):
            identity = rust[i].split('\t')
            if len(identity) != 3 or identity[:2] != [str(i), inputs[i]]:
                raise AssertionError((order, i, 'Rust operation identity differs'))
            actual, actual_leaves = parse_snapshot(identity[2], rust=True)
            expected, expected_leaves = parse_snapshot(native[i])
            if order < 3:
                equal = [actual[j] for j in (0, 1, 3)] == [expected[j] for j in (0, 1, 3)]
            else:
                equal = actual_leaves == expected_leaves
                equal = equal and (query_set(actual[3]) == query_set(expected[3])
                                   if inputs[i][0] in 'vsqxfg' else actual[3] == expected[3])
            if not equal:
                raise AssertionError((order, i, 'native/Rust replay differs'))


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
        if arch != args.expected_arch:
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
    if header.count(marker) != 1:
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
    if rust_lifecycle.splitlines() != native_lifecycle.splitlines():
        raise AssertionError('actual allocator release order differs from native')
    inputs = run([sys.executable, HERE / 'cases.py'], out, 'cases', capture=True)
    count = validate_corpus(inputs)
    if len(native_lifecycle.splitlines()) != 10:
        raise AssertionError('lifecycle corpus changed')
    (out / 'inputs.tsv').write_bytes(inputs)
    for order in range(4):
        captured = run([out / ('oracle' + suffix), str(order)], out, f'native-{order}', capture=True, input=inputs)
        if len(captured.splitlines()) != count:
            raise AssertionError((order, 'incomplete capture'))
        (out / f'native-{order}.tsv').write_bytes(captured)
    if msvc:
        for order in range(4):
            captured = run([diagnostic, str(order)], out, f'ffi-default-native-{order}', capture=True, input=inputs)
            if len(captured.splitlines()) != count:
                raise AssertionError((order, 'incomplete diagnostic capture'))
    env = dict(os.environ, DBVT_FIXTURES=str(out), DBVT_POLICY=args.rust_policy)
    build = run(['rustup', 'run', '1.95.0', 'cargo', 'test', '--locked', '--manifest-path',
                 HERE / 'Cargo.toml', '--release', '--no-run', '--message-format=json'],
                out, 'rust-tests-build', capture=True, cwd=ROOT / 'rust')
    executable = retain_test_binary(build, out)
    result = run([executable], out, 'rust-tests', env=env, cwd=ROOT / 'rust', capture=True)
    validate_test_result(result)
    compare_streams(out)
    verify_numeric_policies(out)
    print(f'{count * 3} strict snapshots, {count} ordinary allocator comparisons and 10 lifecycle cases compared.')


if __name__ == '__main__':
    main()
