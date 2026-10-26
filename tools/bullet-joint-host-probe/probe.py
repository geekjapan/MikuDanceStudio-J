#!/usr/bin/env python3
"""Observe complete same-host Bullet/Rust bits without changing strict gates."""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / 'tools/bullet-rust-solver-check/check.py'
JOINT = ROOT / 'rust/crates/mds-bullet/tests/pure_bullet/joint_solver.rs'
FIXTURE = JOINT.parent.parent / 'solver_data/native.tsv'


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'adapter anchor changed: {old!r}')
    return source.replace(old, new)


def save_adapter(original, adapted, destination):
    destination.write_text(adapted)
    destination.with_suffix(destination.suffix + '.diff').write_text(''.join(
        difflib.unified_diff(original.splitlines(True), adapted.splitlines(True),
                             fromfile='checked-in', tofile=str(destination))))


def joint_adapter(source, native):
    for fixture in ['native.tsv', 'native-x86_64.tsv']:
        source = replace_once(source, f'include_str!("../solver_data/{fixture}")',
                              f'include_str!({json.dumps(native.as_posix())})')
    old = '''        for (index, (a, b)) in actual.iter().zip(&expected).enumerate() {
            assert_eq!(a, b, "case {id} word {index}: Rust {a:08x}, native {b:08x}");
        }'''
    new = '''        {
            use std::io::Write;
            let path = std::env::var("MDS_JOINT_ACTUAL").expect("probe output path");
            let mut out = std::fs::OpenOptions::new().create(true).append(true)
                .open(path).expect("open actual output");
            write!(out, "{id}").unwrap();
            for word in input[..input.len() - expected.len()].iter().chain(&actual) {
                write!(out, "\\t{word:08x}").unwrap();
            }
            writeln!(out).unwrap();
        }'''
    source = replace_once(source, 'assert_eq!(row_events, 20_580);',
                          'assert_eq!(row_events, std::env::var("MDS_JOINT_EXPECTED_EVENTS")'
                          '.expect("validated native event count").parse::<usize>().unwrap());')
    return replace_once(source, old, new)


def check_adapter(source, harness):
    source = replace_once(source, 'compare_capture(captured, fixture)',
                          "print('Diagnostic frozen joint comparison:', captured == fixture.read_bytes())")
    for message in ['Native factor operations differ from checked-in fixture']:
        source = replace_once(source, f"raise SystemExit('{message}')",
                              f"print('FAIL diagnostic frozen comparison: {message}')")
    for old, new in [
        ("HERE / 'harness.rs'", repr(str(harness))),
        ("subprocess.check_output([executable, '--factors'], env=environment)",
         "capture_output([executable, '--factors'], 'factors', env=environment)"),
        ("subprocess.check_output([executable], env=environment)",
         "capture_output([executable], 'oracle', env=environment)"),
    ]:
        if old == "HERE / 'harness.rs'":
            if source.count(old) != 2:
                raise ValueError('adapter harness anchor changed')
            source = source.replace(old, new)
        else:
            source = replace_once(source, old, new)
    source = replace_once(source, "print(f'Native fixture and pure Rust agree for {len(captured.splitlines())} joint cases.')",
                          "print(f'Diagnostic capture completed for {len(captured.splitlines())} joint cases; see status.json for comparisons.')")
    source = replace_once(source, "run([output / 'rust-joints', '--nocapture'], env=environment)",
                          "environment['MDS_JOINT_EXPECTED_EVENTS'] = str(validate_native_capture(output)['simd_events'])\n"
                          "    run([output / 'rust-joints', '--nocapture'], env=environment)")
    if os.name == 'nt':
        source = replace_once(source, "output / 'native-joints'", "output / 'native-joints.exe'")
        source = source.replace("output / 'rust-joints'", "output / 'rust-joints.exe'")
    return source


def kind(word):
    value = int(word, 16)
    if value & 0x7f800000 == 0x7f800000:
        return 'nan' if value & 0x007fffff else 'infinity'
    return 'zero' if value & 0x7fffffff == 0 else 'finite'


def input_fingerprint(path):
    records = []
    for line in path.read_text().splitlines():
        fields = line.split('\t')
        if len(fields) < 302:
            raise ValueError(f'{path}: truncated input')
        records.append('\t'.join(fields[:302]) + '\n')
    return {'cases': len(records), 'words_per_case': 301,
            'sha256': hashlib.sha256(''.join(records).encode()).hexdigest()}


def compare(left, right, output, joint=False):
    a, b = left.read_text().splitlines(), right.read_text().splitlines()
    mismatches = 0
    categories = {}
    with output.open('w') as report:
        report.write('case\tfield\tleft\tright\tleft_kind\tright_kind\n')
        for index in range(max(len(a), len(b))):
            aa = a[index].split('\t') if index < len(a) else []
            bb = b[index].split('\t') if index < len(b) else []
            for field in range(max(len(aa), len(bb))):
                x = aa[field] if field < len(aa) else '<missing>'
                y = bb[field] if field < len(bb) else '<missing>'
                if x == y:
                    continue
                kx = kind(x) if field and x != '<missing>' else 'structure'
                ky = kind(y) if field and y != '<missing>' else 'structure'
                category = f'{kx}/{ky}'
                categories[category] = categories.get(category, 0) + 1
                report.write(f'{index}\t{field}\t{x}\t{y}\t{kx}\t{ky}\n')
                mismatches += 1
    byte_equal = left.read_bytes() == right.read_bytes()
    result = {'status': 'PASS' if byte_equal else 'FAIL', 'byte_equal': byte_equal, 'mismatches': mismatches,
            'categories': categories, 'left': str(left), 'right': str(right),
            'left_lines': len(a), 'right_lines': len(b)}
    if joint:
        result['left_inputs'] = input_fingerprint(left)
        result['right_inputs'] = input_fingerprint(right)
        result['input_equal'] = result['left_inputs'] == result['right_inputs']
        result['attribution'] = ('same serialized inputs; exact output comparison' if result['input_equal']
                                 else 'input inequality; output attribution unavailable')
    return result


def capture_cases(path):
    lines = path.read_text().splitlines()
    if len(lines) != 518:
        raise ValueError(f'{path}: expected 518 cases, got {len(lines)}')
    cases = []
    for case_id, line in enumerate(lines):
        fields = line.split('\t')
        if fields[0] != str(case_id) or len(fields) < 303:
            raise ValueError(f'{path}: invalid case ID or truncated header at {case_id}')
        if any(re.fullmatch(r'[0-9a-fA-F]{8}', word) is None for word in fields[1:]):
            raise ValueError(f'{path}: case {case_id} requires 8hex words')
        words = [int(word, 16) for word in fields[1:]]
        if words[0] != 0x3c888889 or words[1] not in (4, 260) or words[2:4] != [3, 2]:
            raise ValueError(f'{path}: case {case_id} invalid solver header')
        for body in range(3):
            if words[4 + body * 29 + 28] not in (0, 1):
                raise ValueError(f'{path}: case {case_id} invalid body flag')
        for joint in range(2):
            offset = 91 + joint * 105
            if words[offset:offset + 2] != [joint, joint + 1]:
                raise ValueError(f'{path}: case {case_id} invalid joint connectivity')
        rows = words[301]
        if not 0 <= rows <= 12:
            raise ValueError(f'{path}: case {case_id} invalid row count {rows}')
        events = rows * 10 if words[1] == 260 else 0
        expected = 321 + 24 * rows + 13 * events
        if len(fields) != expected:
            raise ValueError(f'{path}: case {case_id} has {len(fields)} fields, expected {expected}')
        cases.append((fields, rows, events))
    return cases


def counts(path):
    cases = capture_cases(path)
    return {'cases': len(cases), 'simd_events': sum(events for _, _, events in cases)}


def resolve_record(line):
    # Native resolve records append five unnamed vectors after a doubled comma.
    named, separator, tail = line.partition(',,')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate resolve field {key}')
            result[key] = value
        return result
    try:
        record = json.loads(named + '}' if separator else named, object_pairs_hook=unique)
        extra = json.loads('[' + tail + ']') if separator else []
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError('malformed resolve record') from error
    if not isinstance(record, dict):
        raise ValueError('resolve object required')
    integers = ['n', 'iter', 'j', 'id_a', 'id_b']
    vectors = ['a_dlin', 'a_dang', 'b_dlin', 'b_dang']
    scalars = []
    if record.get('kind') == 'joint':
        vectors += ['a_vel', 'a_avel', 'b_vel', 'b_avel']
        if separator:
            raise ValueError('unexpected joint vectors')
    elif record.get('kind') in ('noncontact', 'postnc'):
        integers += ['frictionIndex', 'cidA', 'cidB']
        scalars = ['push', 'applied', 'friction', 'jac', 'rhs', 'cfm', 'lower', 'upper']
        if not separator or len(extra) != 5:
            raise ValueError('expected five unnamed resolve vectors')
    else:
        raise ValueError('unexpected resolve kind')
    if set(record) != set(integers + vectors + scalars + ['kind']):
        raise ValueError('unexpected resolve fields')
    if any(type(record[key]) is not int for key in integers):
        raise ValueError('resolve integer required')
    for vector in [record[key] for key in vectors] + extra:
        if not isinstance(vector, list) or len(vector) != 3:
            raise ValueError('resolve vector requires three words')
        if any(not isinstance(word, str) or re.fullmatch(r'[0-9a-fA-F]{8}', word) is None for word in vector):
            raise ValueError('resolve vector requires 8hex words')
    if any(not isinstance(record[key], str) or re.fullmatch(r'[0-9a-fA-F]{8}', record[key]) is None for key in scalars):
        raise ValueError('resolve scalar requires 8hex word')
    return record


def validate_native_capture(directory):
    cases = capture_cases(directory / 'native.tsv')
    oracle = (directory / 'oracle.tsv').read_text().splitlines()
    if len(oracle) != len(cases):
        raise ValueError('oracle case count differs')
    sequence = 0
    with (directory / 'resolve.log').open() as log:
        for case_id, (fields, rows, events) in enumerate(cases):
            prefix = 321 + 24 * rows
            if oracle[case_id] != '\t'.join(fields[:prefix]):
                raise ValueError(f'case {case_id} oracle prefix differs')
            cursor = prefix
            if int(fields[2], 16) != 260:
                continue
            for iteration in range(10):
                expected = [(kind, row) for row in range(rows) for kind in ['noncontact', 'postnc']]
                expected += [('joint', joint) for joint in range(2)]
                for kind, index in expected:
                    sequence += 1
                    line = next(log, None)
                    if line is None:
                        raise ValueError('missing resolve event')
                    record = resolve_record(line)
                    if (record['n'], record['kind'], record['iter'], record['j']) != (sequence, kind, iteration, index):
                        raise ValueError(f'resolve event order differs at {sequence}')
                    if kind == 'joint' and (record['id_a'], record['id_b']) != (index, index + 1):
                        raise ValueError('resolve joint connectivity differs')
                    if kind == 'postnc':
                        payload = [record['applied']] + [word for key in ['a_dlin', 'a_dang', 'b_dlin', 'b_dang'] for word in record[key]]
                        if [word.lower() for word in payload] != fields[cursor:cursor + 13]:
                            raise ValueError(f'case {case_id} resolve payload differs at {sequence}')
                        cursor += 13
            if cursor != prefix + events * 13:
                raise ValueError('resolve trace dimension differs')
        if next(log, None) is not None:
            raise ValueError('extra resolve event')
    return {'cases': len(cases), 'rows': sum(rows for _, rows, _ in cases),
            'simd_events': sum(events for _, _, events in cases), 'resolve_records': sequence}


def validate_capture(directory):
    structure = validate_native_capture(directory)
    counts(directory / 'rust.tsv')
    if input_fingerprint(directory / 'native.tsv') != input_fingerprint(directory / 'rust.tsv'):
        raise ValueError('same-host input invariant failed')
    if (directory / 'native.tsv').read_bytes() != (directory / 'rust.tsv').read_bytes():
        raise ValueError('same-host raw bytes differ')
    return structure


def msvc_command(command, profile, out, native_libs):
    src = ROOT / 'recipes/bullet275/bullet-src/src'
    shim = ROOT / 'rust/crates/mds-bullet-sys/shim'
    sources = [x for x in command if x.endswith('.cpp')]
    # MSVC retains btContactConstraint's default constructor and its manifold dependency.
    sources.append(str(src / 'BulletCollision/NarrowPhaseCollision/btPersistentManifold.cpp'))
    command = ['cl', '/nologo', '/std:c++17', '/O2', '/fp:precise', '/EHsc', '/W0', '/MD',
               '/DBT_NO_PROFILE=1', f'/I{src}', f'/I{shim}', f'/FI{shim / "det_math.h"}',
               *(['/DWIN32'] if profile == 'msvc-cmake-win32' else []),
               *sources, str(out / 'libmds_crtmath.a'), f'/Fe:{out / "native-joints.exe"}',
               f'/Fo:{out}\\', '/link', '/OPT:REF', *native_libs]
    return command


def capture_command(out, label, command, **kwargs):
    command = list(map(str, command))
    (out / f'{label}.command.json').write_text(json.dumps(command) + '\n')
    record = {'command': command, 'returncode': None, 'status': 'FAIL'}
    stdout = stderr = b''
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        stdout, stderr = result.stdout, result.stderr
        record.update(returncode=result.returncode, status='PASS' if result.returncode == 0 else 'FAIL')
    except BaseException as error:
        record['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        (out / f'{label}.stdout').write_bytes(stdout)
        (out / f'{label}.stderr').write_bytes(stderr)
        if label in ['factors', 'oracle']:
            (out / f'{label}.tsv').write_bytes(stdout)
        (out / f'{label}.status.json').write_text(json.dumps(record, indent=2) + '\n')
        with (out / 'build-and-test.log').open('ab') as log:
            log.write(stdout + stderr)
    result.check_returncode()
    return stdout, stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--profile', choices=['clang-helper', 'msvc-ffi-default', 'msvc-cmake-win32'], required=True)
    args = parser.parse_args()
    if (os.name == 'nt') != args.profile.startswith('msvc-'):
        parser.error('profile must match the actual host compiler')
    out = args.out_dir.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error('out-dir must be empty to prevent stale evidence')
    out.mkdir(parents=True, exist_ok=True)
    status = {'execution': 'FAIL', 'phase': 'setup'}
    env = os.environ.copy()
    argv = sys.argv[:]
    import_path = sys.path[:]
    try:
        joint = out / 'joint_solver.rs'
        save_adapter(JOINT.read_text(), joint_adapter(JOINT.read_text(), out / 'native.tsv'), joint)
        harness_source = (CHECK.parent / 'harness.rs').read_text()
        harness = out / 'harness.rs'
        for relative in re.findall(r'#\[path = "([^"]+)"\]', harness_source):
            path = joint if relative.endswith('/joint_solver.rs') else (CHECK.parent / relative).resolve()
            harness_source = replace_once(harness_source, json.dumps(relative), json.dumps(path.as_posix()))
        save_adapter((CHECK.parent / 'harness.rs').read_text(), harness_source, harness)
        adapted = check_adapter(CHECK.read_text(), harness)
        save_adapter(CHECK.read_text(), adapted, out / 'check.py')
        provenance = {'profile': args.profile, 'platform': platform.platform(),
                      'python': sys.version, 'math': 'unchanged det_math.h + real mds-crtmath staticlib',
                      'scope': 'helper diagnostic; CMake WIN32 macro profile is not a full app oracle'}
        (out / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
        commands = out / 'commands.jsonl'
        native_libs = []

        def invoke(command, label=None, **kwargs):
            status['phase'] = label or 'build-and-test'
            with commands.open('a') as log:
                log.write(json.dumps(command) + '\n')
            label = label or f'command-{sum(1 for _ in commands.open()):03d}'
            stdout, stderr = capture_command(out, label, command,
                cwd=out if command[0] == 'cl' else ROOT / 'rust', **kwargs)
            return stdout + stderr

        def capture_output(command, label, **kwargs):
            status['phase'] = label
            stdout, _ = capture_command(out, label, command, **kwargs)
            return stdout

        def run(command, **kwargs):
            command = list(map(str, command))
            if args.profile.startswith('msvc-') and command[0] == os.environ.get('CXX', 'clang++'):
                command = msvc_command(command, args.profile, out, native_libs)
                (out / 'native-command.txt').write_text(subprocess.list2cmdline(command) + '\n')
            if '--crate-type' in command and command[command.index('--crate-type') + 1] == 'staticlib':
                command += ['--print', 'native-static-libs']
            if any(x.endswith('/oracle.cpp') or x.endswith('\\oracle.cpp') for x in command):
                macro_source = out / 'profile.cpp'
                macros = ['WIN32', '_WIN32', '_WIN64', '_MSC_VER', '__clang_major__',
                          '__x86_64__', '__aarch64__', 'BT_USE_SSE', 'BT_USE_DOUBLE_PRECISION',
                          'BT_NO_PROFILE', 'MDS_BT_SYSTEM_MATH']
                code = '#include "LinearMath/btScalar.h"\n#include <cstdio>\n'
                code += '#define S_(x) #x\n#define S(x) S_(x)\nint main() {\n'
                for macro in macros:
                    code += (f'#ifdef {macro}\nstd::puts("{macro}=" S({macro}));\n'
                             f'#else\nstd::puts("{macro}=<undefined>");\n#endif\n')
                code += 'std::printf("pointer_bits=%zu\\n", sizeof(void*) * 8);\n}\n'
                macro_source.write_text(code)
                macro_command = []
                inserted = False
                for arg in command:
                    if arg.endswith('.cpp'):
                        if not inserted:
                            macro_command.append(str(macro_source))
                            inserted = True
                    else:
                        macro_command.append(arg.replace('native-joints', 'native-profile'))
                invoke(macro_command, **kwargs)
                profile_exe = out / ('native-profile.exe' if os.name == 'nt' else 'native-profile')
                profile_data = invoke([str(profile_exe)], **kwargs)
                (out / 'effective-profile.txt').write_bytes(profile_data)
                profile = dict(line.split('=', 1) for line in profile_data.decode().splitlines())
                assert profile['BT_USE_SSE'] != '<undefined>', profile
                if os.name == 'nt':
                    assert profile['_WIN64'] == '1' and profile['pointer_bits'] == '64', profile
                    assert (profile['WIN32'] != '<undefined>') == (args.profile == 'msvc-cmake-win32'), profile
            result = invoke(command, **kwargs)
            if b'native-static-libs:' in result:
                native_libs[:] = result.decode(errors='replace').split('native-static-libs:')[-1].splitlines()[0].split()

        compiler = os.environ.get('CXX', 'cl' if os.name == 'nt' else 'clang++')
        for name, command in [('compiler', [compiler, '/?'] if os.name == 'nt' else [compiler, '--version']),
                              ('rustc', ['rustup', 'run', '1.95.0', 'rustc', '-Vv']),
                              ('git-head', ['git', 'rev-parse', 'HEAD'])]:
            (out / f'{name}.txt').write_bytes(invoke(command, label=name))

        os.environ['MDS_JOINT_ACTUAL'] = str(out / 'rust.tsv')
        namespace = {'__name__': 'probe_adapter', '__file__': str(CHECK),
                     'validate_native_capture': validate_native_capture}
        sys.path.insert(0, str(CHECK.parent))
        exec(compile(adapted, str(out / 'check.py'), 'exec'), namespace)
        namespace['run'] = run
        namespace['capture_output'] = capture_output
        status['phase'] = 'check'
        sys.argv = [str(CHECK), '--out-dir', str(out)]
        namespace['main']()
        status['phase'] = 'comparison'
        for name in ['native', 'rust']:
            counts(out / f'{name}.tsv')
        comparison = compare(out / 'rust.tsv', out / 'native.tsv', out / 'rust-vs-native.diff.tsv', joint=True)
        if not comparison['input_equal']:
            raise ValueError('same-host input invariant failed')
        status['structure'] = validate_capture(out)
        if comparison['status'] != 'PASS':
            raise SystemExit('same-host exact bit comparison failed; see diagnostic artifacts')
        status['execution'] = 'PASS'
    except BaseException as error:
        status['error'] = f'{type(error).__name__}: {error}'
        status['returncode'] = getattr(error, 'returncode', error.code if isinstance(error, SystemExit) else None)
        raise
    finally:
        sys.argv = argv
        sys.path[:] = import_path
        os.environ.clear()
        os.environ.update(env)
        for name in ['native', 'rust']:
            path = out / f'{name}.tsv'
            if path.exists():
                try:
                    status[name] = counts(path)
                except (ValueError, UnicodeError) as error:
                    status[name] = {'error': str(error)}
        for label, left, right in [('native-vs-frozen', out / 'native.tsv', FIXTURE),
                                   ('rust-vs-native', out / 'rust.tsv', out / 'native.tsv'),
                                   ('rust-vs-frozen', out / 'rust.tsv', FIXTURE),
                                   ('factors-vs-frozen', out / 'factors.tsv', FIXTURE.with_name('factors.tsv'))]:
            if left.exists() and right.exists():
                try:
                    status[label] = compare(left, right, out / f'{label}.diff.tsv', joint=label != 'factors-vs-frozen')
                except (ValueError, UnicodeError) as error:
                    status[label] = {'status': 'FAIL', 'error': str(error)}
        (out / 'status.json').write_text(json.dumps(status, indent=2) + '\n')
        hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for folder in ['recipes/bullet275/bullet-src/src', 'rust/crates/mds-bullet/src',
                                 'rust/crates/mds-bullet-sys/shim', 'rust/crates/mds-crtmath/src',
                                 'rust/crates/mds-bullet/tests', 'tools/bullet-rust-solver-check']
                  for path in sorted((ROOT / folder).rglob('*')) if path.is_file()}
        for path in [Path(__file__).resolve(), Path(__file__).with_name('test_probe.py'),
                     ROOT / '.github/workflows/bullet-joint-host-probe.yml']:
            hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes.update({path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in out.iterdir() if path.is_file()})
        (out / 'sha256.json').write_text(json.dumps(hashes, indent=2) + '\n')
        print(json.dumps(status, indent=2))


if __name__ == '__main__':
    main()
