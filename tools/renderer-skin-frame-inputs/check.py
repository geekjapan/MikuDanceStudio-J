#!/usr/bin/env python3
"""Throwaway CPU diagnostic; equality is conditional on Rust's golden2 frame inputs."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

TEST = 'mesh::tests::exact_frame_skin_cpu_probe'
HEX = re.compile(r'[0-9a-f]{8}\Z')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_float_words(words):
    if not all(HEX.fullmatch(word) and int(word, 16) & 0x7f800000 != 0x7f800000
               for word in words):
        raise ValueError(f'invalid or nonfinite float words: {words}')


def validate_counts(counts):
    if not (len(counts) == 2 and all(len(c) == 6 for c in counts)
            and [c[0] for c in counts] == ['skin-0', 'skin-30']
            and all(isinstance(v, int) and v > 0 for c in counts for v in c[1:])
            and counts[0][1:] == counts[1][1:]):
        raise ValueError(f'expected matching nonempty skin-0/skin-30 counts: {counts}')


def validate_cases(cases, counts):
    validate_counts(counts)
    lines = [line.split() for line in cases.splitlines() if line.strip()]
    cursor = 0
    for label, vertices, stride, materials, bones, morphs in counts:
        expected = [('model', ['skin_tex.pmx']), ('case', [label]),
                    ('world', 16), ('camera', 4), ('edge', 1), ('shadow', ['0'])]
        # This scene's evaluated shadow flag is preserved, whichever of 0 or 1 it is.
        for op, payload in expected:
            words = lines[cursor]
            cursor += 1
            if op == 'shadow':
                if not (words in [['shadow', '0'], ['shadow', '1']]):
                    raise ValueError(words)
            elif isinstance(payload, int):
                if not (words[0] == op and len(words) == payload + 1):
                    raise ValueError(words)
                validate_float_words(words[1:])
            else:
                if not (words == [op, *payload]):
                    raise ValueError(words)
        for op, count, width in [('morph', morphs, 1), ('bone', bones, 16)]:
            for index in range(count):
                words = lines[cursor]
                cursor += 1
                if not (words[:2] == [op, str(index)] and len(words) == width + 2):
                    raise ValueError(words)
                validate_float_words(words[2:])
        if not (lines[cursor] == ['end']):
            raise ValueError('missing case end directive')
        cursor += 1
    if not (cursor == len(lines)):
        raise ValueError('extra cases or directives (including qdef)')


def read_counts(text):
    counts = []
    for line in text.splitlines():
        label, *values = line.split()
        if not (len(values) == 5):
            raise ValueError('expected five count fields')
        values = list(map(int, values))
        if not (all(v > 0 for v in values)):
            raise ValueError(values)
        counts.append((label, *values))
    validate_counts(counts)
    return counts


def dump_records(text, counts, native=False):
    validate_counts(counts)
    lines = [line.split() for line in text.splitlines()]
    cursor = 0
    records = []
    skipped_bones = 0
    for label, vertices, stride, materials, _, _ in counts:
        if not (lines[cursor] == ['model', 'skin_tex.pmx', 'pmx', 'vertices', str(vertices), 'stride', str(stride * 4)]):
            raise ValueError('unexpected dump model, vertex count or stride')
        if not (lines[cursor + 1] == ['case', label]):
            raise ValueError('unexpected dump case')
        cursor += 2
        for kind, count, width in [('v', vertices, stride + 4), ('m', materials, 16)]:
            for index in range(count):
                words = lines[cursor]
                cursor += 1
                if not (words[:2] == [kind, str(index)] and len(words) == width + 2):
                    raise ValueError(words)
                if not (all(HEX.fullmatch(w) for w in words[2:])):
                    raise ValueError(words)
                # The last vertex word is packed edge diffuse, not a float.
                validate_float_words(words[2:-1] if kind == 'v' else words[2:])
                records.append((label, kind, index, words[2:]))
        # Bone morph work records are outside Mesh::skinned's returned buffers.
        if native:
            while cursor < len(lines) and lines[cursor][0] == 'b':
                words = lines[cursor]
                if not (len(words) == 10 and int(words[1]) >= 0 and int(words[2]) >= 0):
                    raise ValueError('malformed excluded bone morph record')
                if not (all(HEX.fullmatch(w) for w in words[3:])):
                    raise ValueError('malformed excluded bone morph words')
                skipped_bones += 1
                cursor += 1
    if not (cursor == len(lines)):
        raise ValueError('extra or malformed dump records')
    return records, skipped_bones


def compare(rust, native, counts):
    actual, _ = dump_records(rust, counts)
    expected, excluded = dump_records(native, counts, native=True)
    mismatches = []
    words = 0
    for a, b in zip(actual, expected, strict=True):
        if not (a[:3] == b[:3]):
            raise ValueError('dump record identity mismatch')
        for index, (av, bv) in enumerate(zip(a[3], b[3], strict=True)):
            words += 1
            if av != bv:
                mismatches.append({'case': a[0], 'kind': a[1], 'record': a[2], 'word': index,
                                   'rust': av, 'cpp': bv})
    return {'conditional_cpu_equal': not mismatches, 'compared_words': words,
            'mismatches': mismatches, 'excluded_cpp_bone_morph_records': excluded,
            'scope': 'Main/edge buffers and 16 harness material fields, given Rust frame inputs. '
                     'No native PMM pose, GPU, or renderer parity claim.'}


def capture(out, label, command, cwd, env):
    command = list(map(str, command))
    record = {'argv': command, 'cwd': str(cwd), 'start_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'environment': {k: env[k] for k in ['RUSTUP_TOOLCHAIN', 'CXX', 'TMPDIR', 'CARGO_TARGET_DIR', 'MDS_SKIN_FRAME_OUT', 'ASAN_OPTIONS', 'CC_ENABLE_DEBUG_OUTPUT'] if k in env}}
    try:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (out / f'{label}.stdout').write_bytes(result.stdout)
        (out / f'{label}.stderr').write_bytes(result.stderr)
        record['returncode'] = result.returncode
    finally:
        record['end_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (out / f'{label}.receipt.json').write_text(json.dumps(record, indent=2) + '\n')
    result.check_returncode()
    return result.stdout


def snapshot(root, out, copy=False):
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    hashes = {}
    for name in filter(None, paths):
        path = root / name
        if path.is_file():
            hashes[name] = digest(path)
            if copy and (name.startswith(('rust/', 'tools/skin_check/', 'src/model/', 'include/', 'recipes/bullet275/', 'tests/fixtures/rust/')) or name in ['tools/renderer-skin-frame-inputs/check.py', 'tools/renderer-skin-frame-inputs/test_check.py', '.github/workflows/renderer-skin-frame-inputs.yml']):
                dest = out / 'inputs' / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
    return hashes


def run(root, out):
    if not (sys.platform == 'linux' and os.uname().machine == 'x86_64'):
        raise ValueError('Linux x64 diagnostic only')
    out.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(('MDS_RENDER_', 'MDS_BT_', 'MDS_GJK_PAIR', 'MDS_SOLVER')):
            del env[key]
    env.update(RUSTUP_TOOLCHAIN='1.95.0', CXX='clang++', TMPDIR=str(out / 'tmp'),
               CARGO_TARGET_DIR=str(out / 'target'), MDS_SKIN_FRAME_OUT=str(out / 'frames'),
               ASAN_OPTIONS='detect_leaks=0', CC_ENABLE_DEBUG_OUTPUT='1')
    Path(env['TMPDIR']).mkdir()
    start = snapshot(root, out, copy=True)
    (out / 'source-start.json').write_text(json.dumps(start, indent=2) + '\n')
    try:
        capture(out, 'identity', ['git', 'rev-parse', 'HEAD'], root, env)
        capture(out, 'rust-version', ['rustc', '+1.95.0', '-vV'], root / 'rust', env)
        capture(out, 'clang-version', ['clang++', '--version'], root, env)
        capture(out, 'host', ['uname', '-a'], root, env)
        rustc_path = Path(capture(out, 'rustc-path', ['rustup', 'which', '--toolchain', '1.95.0', 'rustc'], root / 'rust', env).decode().strip())
        compiler_paths = [rustc_path, Path(shutil.which('clang++')).resolve()]
        (out / 'compiler-hashes.json').write_text(json.dumps({str(p): digest(p) for p in compiler_paths}, indent=2) + '\n')
        capture(out, 'fetch-workspace', ['cargo', '+1.95.0', 'fetch', '--locked'], root / 'rust', env)
        capture(out, 'fetch-ffi', ['cargo', '+1.95.0', 'fetch', '--locked', '--manifest-path', '../tools/skin_check/ffi/Cargo.toml'], root / 'rust', env)
        # Build once, retaining the unchanged harness's old-case result as a baseline check.
        capture(out, 'cpp-build-old-cases', ['sh', '-x', '../tools/skin_check/run.sh', str(out / 'old.dump')], root / 'rust', env)
        baseline = root / 'tests/fixtures/rust/skin/skin.dump'
        if not ((out / 'old.dump').read_bytes() == baseline.read_bytes()):
            raise ValueError('old C++ dump baseline changed')
        binary_dir = out / 'binaries'
        binary_dir.mkdir()
        native_build = Path(env['TMPDIR']) / 'skin_check'
        for path in [*native_build.glob('*.o'), native_build / 'target/release/libskin_check_ffi.a', native_build / 'skin_check']:
            shutil.copy2(path, binary_dir / path.name)
        native = native_build / 'skin_check'
        build = capture(out, 'rust-build', ['cargo', '+1.95.0', 'test', '--locked', '-vv', '-p', 'mds-render', '--lib', '--no-run', '--message-format=json'], root / 'rust', env)
        artifacts = [json.loads(line) for line in build.decode().splitlines() if line.startswith('{')]
        executables = [a['executable'] for a in artifacts if a.get('reason') == 'compiler-artifact' and a.get('target', {}).get('name') == 'mds_render' and a.get('profile', {}).get('test') and a.get('executable')]
        if not (len(executables) == 1):
            raise ValueError(executables)
        for path in Path(env['CARGO_TARGET_DIR']).glob('debug/build/*/out/*.a'):
            dest = binary_dir / 'rust-native' / path.parent.parent.name / path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        rust = binary_dir / 'mds-render-tests'
        shutil.copy2(executables[0], rust)
        for executable in [native, rust]:
            executable.chmod(0o555)
            linked = capture(out, executable.name + '-ldd', ['ldd', str(executable)], root, env).decode()
            for lib in re.findall(r'(/[^\s()]+)', linked):
                path = Path(lib)
                if path.is_file():
                    dest = out / 'linked-libraries' / path.relative_to('/')
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, dest)
        binary_start = {str(p.relative_to(binary_dir)): digest(p) for p in binary_dir.rglob('*') if p.is_file()}
        if not (binary_start['skin_check'] == digest(native)):
            raise ValueError('native executable differs from preserved binary')
        (out / 'binary-start.json').write_text(json.dumps(binary_start, indent=2) + '\n')
        result = capture(out, 'rust-frames', [str(rust), '--exact', TEST, '--ignored', '--nocapture', '--test-threads=1'], root / 'rust', env).decode()
        if not (f'test {TEST} ... ok' in result and '1 passed; 0 failed; 0 ignored' in result):
            raise ValueError(result)
        frames = out / 'frames'
        counts = read_counts((frames / 'counts.txt').read_text())
        validate_cases((frames / 'cases.txt').read_text(), counts)
        reads = Path(frames / 'fixture-reads.txt').read_text().splitlines()
        if not (reads and all(Path(p).resolve().is_relative_to(root / 'tests/fixtures/rust') for p in reads)):
            raise ValueError('missing or out-of-scope fixture reads')
        missing = (frames / 'fixture-missing.txt').read_text().splitlines()
        if not (all(not Path(p).exists() and Path(p).resolve().is_relative_to(root / 'tests/fixtures/rust') for p in missing)):
            raise ValueError('invalid missing-fixture record')
        (out / 'fixture-read-hashes.json').write_text(json.dumps({p: digest(Path(p)) for p in reads}, indent=2) + '\n')
        native_dump = capture(out, 'cpp-frames', [str(native), str(root / 'tests/fixtures/rust/golden2'), str(frames / 'cases.txt')], root / 'rust', env).decode()
        report = compare((frames / 'rust.dump').read_text(), native_dump, counts)
        (out / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
        binary_end = {str(p.relative_to(binary_dir)): digest(p) for p in binary_dir.rglob('*') if p.is_file()}
        (out / 'binary-end.json').write_text(json.dumps(binary_end, indent=2) + '\n')
        if not (binary_start == binary_end and binary_start['skin_check'] == digest(native)):
            raise ValueError('diagnostic binaries changed')
        if not (report['conditional_cpu_equal']):
            raise ValueError('CPU words differ; see comparison.json')
    finally:
        end = snapshot(root, out)
        (out / 'source-end.json').write_text(json.dumps(end, indent=2) + '\n')
        (out / 'source-unchanged.json').write_text(json.dumps({'unchanged': start == end}) + '\n')
        seal = {str(p.relative_to(out)): digest(p) for p in sorted(out.rglob('*')) if p.is_file() and not p.is_relative_to(out / 'target') and not p.is_relative_to(out / 'tmp')}
        (out / 'SHA256SUMS.json').write_text(json.dumps(seal, indent=2) + '\n')
        if not (start == end):
            raise ValueError('source or fixtures changed during the diagnostic')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    run(Path(__file__).resolve().parents[2], args.out.resolve())
