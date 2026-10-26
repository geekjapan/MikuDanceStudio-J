#!/usr/bin/env python3
"""Measure the final mds-bullet-sys consumer and gate native/Rust compatibility."""
import argparse
import hashlib
import json
import os
import platform
import shutil
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OLD = ROOT / 'tools/bullet-rust-dbvt-check'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function(text, name):
    match = re.search(r'\b' + name + r'\s*\([^{};]*\)\s*\{', text)
    if not match:
        raise ValueError(f'missing {name} definition')
    depth, end = 1, match.end()
    while depth and end < len(text):
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    if depth:
        raise ValueError(f'unterminated {name}')
    return text[match.start():end]


def classify(text, cpp=False):
    extracts = {name: function(text, name) for name in ('Intersect', 'Select', 'Merge')}
    compact = {key: re.sub(r'\s+', '', value) for key, value in extracts.items()}
    result = {}
    for name, generic, sse in [('Intersect', 'a.mi.x()<=b.mx.x()', '_mm_cmplt_ps'),
                               ('Select', 'Proximity(o,a)<Proximity(o,b)?0:1', '_mm_cmple_ss'),
                               ('Merge', 'if(a.mi[i]<b.mi[i])', '_mm_min_ps')]:
        found = [profile for profile, needle in [('generic', generic), ('sse', sse)] if needle in compact[name]]
        if len(found) != 1:
            raise ValueError(f'unknown or ambiguous {name} branch')
        result[name] = found[0]
    policy = re.search(r'struct\s+ICollide\s*\{(.*?)\n\s*\};', text, re.S)
    if not policy or 'Process' not in policy[1]:
        raise ValueError('missing ICollide policy')
    result['policy'] = 'virtual' if re.search(r'\bvirtual\b', policy[1]) else 'template'
    extracts['ICollide'] = policy[0]
    if cpp:
        for name in ('merge', 'bounds'):
            extracts[name] = function(text, name)
            body = re.sub(r'\s+', '', extracts[name])
            if 'locals[' in body and '*(btDbvtVolume*)locals' in body:
                result[name + '_local'] = 'aligned'
            elif 'locals[' not in body and 'btDbvtVolume' in body:
                result[name + '_local'] = 'ordinary'
            else:
                raise ValueError(f'unknown {name} local branch')
    return result, extracts



def validate_aabb(data):
    rows = data.decode('ascii').splitlines()
    if len(rows) != 51:
        raise ValueError('incomplete direct AABB capture')
    inputs = []
    for expected_id, row in enumerate(rows):
        fields = row.split('|')
        if len(fields) != 3 or fields[0] != str(expected_id):
            raise ValueError('malformed AABB case ID')
        words = [[int(value) for value in field.split(',')] for field in fields[1:]]
        if list(map(len, words)) != [12, 13] or words[1][0] not in (0, 1):
            raise ValueError('malformed AABB shape')
        if any(value < 0 or value > 0xffffffff for group in words for value in group):
            raise ValueError('AABB word outside u32')
        inputs.append(words[0])
    return inputs



def validate_select(data):
    text = data.decode('ascii')
    if not re.fullmatch(r'(?:[0-9]+,){3}\r?\n', text) or sorted(map(int, text.strip().split(',')[:-1])) != [1, 2, 3]:
        raise ValueError('malformed Rust directed Select capture')


def validate_native(data, inputs):
    rows = data.decode('ascii').splitlines()
    operations = inputs.decode('ascii').splitlines()
    if len(rows) != len(operations):
        raise ValueError('incomplete native operation capture')
    # oracle.cpp emits state|recursive topology|preorder address ranks|events.
    node = re.compile(r'(B|[0-9]+)((?:,[0-9]+){6})')
    for row, operation in zip(rows, operations):
        fields = row.split('|')
        if len(fields) != 4:
            raise ValueError('malformed native field count')
        state, topology, ranks, events = fields
        if not re.fullmatch(r'[0-9]+,-?[0-9]+,[0-9]+,[01]', state):
            raise ValueError('malformed native state')
        leaves, lookahead, opath, free = map(int, state.split(','))
        if not (leaves <= 128 and -(2**31) <= lookahead < 2**31 and opath < 2**32):
            raise ValueError('native state outside schema')
        keys, nodes = [], []

        def tree(pos):
            match = node.match(topology, pos)
            if not match:
                raise ValueError('malformed native topology')
            kind, words = match.groups()
            if any(int(word) > 0xffffffff for word in words[1:].split(',')):
                raise ValueError('native volume outside u32')
            nodes.append(kind)
            if len(nodes) > 255:
                raise ValueError('native topology exceeds oracle capacity')
            pos = match.end()
            if kind != 'B':
                key = int(kind)
                if key >= 128 or key in keys:
                    raise ValueError('malformed native leaf ID')
                keys.append(key)
                return pos
            for separator in ('(', ';'):
                if topology[pos:pos + 1] != separator:
                    raise ValueError('malformed native branch')
                pos = tree(pos + 1)
            if topology[pos:pos + 1] != ')':
                raise ValueError('malformed native branch end')
            return pos + 1

        if topology != '_' and tree(0) != len(topology):
            raise ValueError('trailing native topology')
        if not re.fullmatch(r'(?:[0-9]+,)*', ranks) or len(ranks.split(',')[:-1]) != len(nodes) + free:
            raise ValueError('malformed native address ranks')
        if any(int(rank) > 0xffffffffffffffff for rank in ranks.split(',')[:-1]):
            raise ValueError('native address rank outside u64')
        op = operation.split()[0]
        if op == 'p':
            if not re.fullmatch(r'[01](?:,[0-9]+){6}', events) or any(int(word) > 0xffffffff for word in events.split(',')[1:]):
                raise ValueError('malformed native predicted-update event')
        elif op in ('v', 'q', 's', 'x'):
            pattern = r'(?:[0-9]+,)*' if op in ('v', 'q') else r'(?:[0-9]+:[0-9]+,)*'
            if not re.fullmatch(pattern, events) or any(int(key) >= 128 for key in re.findall(r'[0-9]+', events)):
                raise ValueError('malformed native query event')
        elif events:
            raise ValueError('unexpected native event')


COMPARISON_TESTS = {
    'dbvt::tests::native_controlled_address_parity': ('controlled_corpus', 'order '),
    'dbvt::tests::ordinary_native_and_production_allocator_query_sets': ('ordinary_corpus', 'operation '),
    'select::directed_select_association_matches_native': ('directed_select', 'directed Select native'),
}
REQUIRED_TESTS = set(COMPARISON_TESTS) | {
    'dbvt::tests::' + name for name in (
        'merge_preserves_right_operand_zero_and_nan_bits',
        'one_free_box_is_reused_and_dead_slots_stay_bounded',
        'native_empty_partition_regression_terminates',
        'large_finite_optimization_subprocess',
        'production_address_order_and_query_sets',
        'production_sort_rotates_by_actual_box_address',
        'zero_center_split_falls_back_without_changing_leaves',
        'optimization_unwind_subprocess',
    )
}


def comparison_result(tests):
    text = tests.stdout.decode('utf-8', errors='strict')
    summaries = re.findall(r'^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', text, re.M)
    outcomes = re.findall(r'^test ([\w:]+) \.\.\. (ok|FAILED)$', text, re.M)
    if (len(summaries) != 1 or len(outcomes) != len(REQUIRED_TESTS)
            or {name for name, _ in outcomes} != REQUIRED_TESTS):
        raise ValueError('Rust comparison did not complete all eleven required tests')
    status, passed, failed, ignored, measured, filtered = summaries[0]
    failed_names = {name for name, outcome in outcomes if outcome == 'FAILED'}
    if (int(ignored) or int(measured) or int(filtered)
            or int(passed) + int(failed) != len(outcomes) or int(failed) != len(failed_names)):
        raise ValueError('incomplete Rust comparison results')
    panics = re.findall(r"^thread '([^']+)'(?: \([0-9]+\))? panicked at [^\n]+:\n([^\n]+)", text, re.M)
    if text.count(' panicked at ') != len(panics):
        raise ValueError('unrecognized Rust panic transport')
    result = {key: name not in failed_names for name, (key, _) in COMPARISON_TESTS.items()}
    if tests.returncode == 0 and status == 'ok' and not failed_names and not panics:
        return result
    marker = 'assertion `left == right` failed: DBVT_COMPATIBILITY_MISMATCH '
    if (tests.returncode == 101 and status == 'FAILED' and failed_names
            and failed_names <= COMPARISON_TESTS.keys() and len(panics) == len(failed_names)
            and {name for name, _ in panics} == failed_names
            and all(line.startswith(marker + COMPARISON_TESTS[name][1]) for name, line in panics)):
        return result
    raise ValueError('Rust failure is not an identified compatibility comparison')


def source_manifest():
    paths = [
        'recipes/bullet275/bullet-src/src', 'rust/crates/mds-bullet-sys',
        'rust/crates/mds-crtmath', 'rust/crates/mds-bullet/src/core/dbvt.rs',
        'rust/crates/mds-bullet/src/core/math.rs', 'rust/crates/mds-bullet/src/core/pair_cache.rs',
        'rust/Cargo.toml', 'rust/Cargo.lock', 'rust/rust-toolchain.toml',
        'tools/bullet-rust-dbvt-check', 'tools/bullet-dbvt-consumer-profile',
    ]
    files = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z', *paths],
        cwd=ROOT).decode().split('\0')
    return {p: digest(ROOT / p) for p in sorted(files) if p and (ROOT / p).is_file()}


def artifact_manifest(out):
    # check.log belongs to the caller and can still be open when this report is written.
    excluded = ('report.json', 'check.log')
    return {p.name: digest(p) for p in sorted(out.iterdir()) if p.is_file() and p.name not in excluded}


def run(argv, out, name, *, check=True, **kwargs):
    argv = list(map(str, argv))
    (out / (name + '-command.json')).write_text(json.dumps(argv, indent=2) + '\n')
    result = subprocess.run(argv, cwd=ROOT / 'rust', stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=600, **kwargs)
    (out / (name + '.stdout')).write_bytes(result.stdout)
    (out / (name + '.stderr')).write_bytes(result.stderr)
    if check and result.returncode:
        print(result.stderr.decode(errors='replace'), file=sys.stderr)
        raise RuntimeError(f'{name} exited {result.returncode}')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = dict(observation='incomplete', compatibility='not-evaluated', target=args.target)
    target_dir = out / 'target'
    env = dict(os.environ, MDS_BT_CONSUMER_PROBE_OUT=str(out))
    try:
        report['source_start_sha256'] = source_manifest()
        for key in ('MDS_BT_SYSTEM_MATH', 'MDS_BT_ASAN'):
            if env.get(key) not in (None, '', '0'):
                raise ValueError(f'{key} must be disabled')
        run(['rustup', 'run', '1.95.0', 'rustc', '-Vv'], out, 'rust-version')
        run(['rustup', 'run', '1.95.0', 'cargo', 'build', '--locked', '--release',
             '--manifest-path', HERE / 'Cargo.toml', '--target', args.target,
             '--target-dir', target_dir], out, 'consumer-build', env=env)
        environment = json.loads((out / 'build-environment.json').read_text())
        if environment['cargo']['TARGET'] != args.target or environment['cargo']['HOST'] != args.target:
            raise ValueError('probe requires execution on its native target host')
        argv = json.loads((out / 'configured-tool-command.json').read_text())
        report['compiler'] = dict(argv=argv, resolved=shutil.which(argv[0], path=environment['tool'].get('PATH')))
        report['host'] = dict(machine=platform.machine(), platform=platform.platform())
        archive = Path((out / 'archive-path.txt').read_text())
        report['archive'] = dict(path=str(archive), sha256=digest(archive))
        profiles = {}
        for name in ('btDbvt', 'btDbvtBroadphase', 'mds_bt', 'mds_mmd'):
            text = (out / (name + '.stdout')).read_text(errors='strict')
            profiles[name], extracts = classify(text, cpp=name == 'btDbvt')
            (out / (name + '-extracts.json')).write_text(json.dumps(extracts, indent=2) + '\n')
        report['profiles'] = profiles
        inline = [{k: v for k, v in profile.items() if not k.endswith('_local')} for profile in profiles.values()]
        if any(profile != inline[0] for profile in inline):
            raise ValueError('translation units disagree on inline configuration')
        exe = target_dir / args.target / 'release' / ('consumer-profile.exe' if os.name == 'nt' else 'consumer-profile')
        directed = b'i 1 0.5 8388608 0.5 0.5 8388608 0.5\ni 2 1 8388608 0 1 8388608 0\ni 3 0 0 0 0 0 0\nv -1 -1 -1 2 8388609 2\n'
        (out / 'select-inputs.tsv').write_bytes(directed)
        native_select = run([exe, 'oracle'], out, 'native-select', input=directed).stdout
        (out / 'original-select-stdout.log').write_bytes(native_select)
        validate_native(native_select, directed)
        rust_select = run([exe, 'select'], out, 'rust-select').stdout
        validate_select(rust_select)
        expected = b'2,3,1,' if inline[0]['Select'] == 'generic' else b'3,2,1,'
        if native_select.splitlines()[-1].split(b'|')[-1] != expected:
            raise ValueError('Select branch disagrees with native behavior')
        native_aabb = run([exe, 'native-aabb'], out, 'native-aabb').stdout
        rust_aabb = run([exe, 'rust-aabb'], out, 'rust-aabb').stdout
        aabb_inputs = validate_aabb(native_aabb)
        if aabb_inputs != validate_aabb(rust_aabb):
            raise ValueError('native/Rust AABB inputs disagree')
        (out / 'aabb-inputs.tsv').write_text(''.join(','.join(map(str, words)) + '\n' for words in aabb_inputs))
        inputs = run([sys.executable, OLD / 'cases.py'], out, 'cases').stdout
        if len(inputs.splitlines()) != 2326:
            raise ValueError('operation corpus changed')
        (out / 'inputs.tsv').write_bytes(inputs)
        for order in range(4):
            native = run([exe, 'oracle', str(order)], out, f'native-{order}', input=inputs).stdout
            validate_native(native, inputs)
            (out / f'native-{order}.tsv').write_bytes(native)
        report['comparisons'] = dict(select=rust_select.strip() == expected,
                                     aabb=native_aabb.splitlines() == rust_aabb.splitlines())
        tests = run(['rustup', 'run', '1.95.0', 'cargo', 'test', '--locked', '--release', '--manifest-path', OLD / 'Cargo.toml'], out, 'rust-tests', check=False, env=dict(os.environ, DBVT_FIXTURES=str(out)))
        test_matches = comparison_result(tests)
        report['observation'] = 'complete'
        report['comparisons'].update(test_matches)
        report['comparisons']['corpus'] = test_matches['controlled_corpus'] and test_matches['ordinary_corpus']
        report['compatibility'] = 'PASS' if all(report['comparisons'].values()) else 'FAIL'
        report['classification'] = 'compatible' if report['compatibility'] == 'PASS' else 'compatibility-mismatch'
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired,
            KeyError, TypeError, IndexError, AttributeError) as error:
        report['failure'] = str(error)
        report['classification'] = 'environment-failure' if isinstance(error, (OSError, subprocess.TimeoutExpired)) else 'validation-gap'
    finally:
        report['source_sha256'] = source_manifest()
        report['source_unchanged'] = report.get('source_start_sha256') == report['source_sha256']
        if not report['source_unchanged']:
            report.update(observation='incomplete', compatibility='not-evaluated',
                          classification='validation-gap', failure='source changed during observation')
        report['input_sha256'] = {p.name: digest(p) for p in out.glob('*inputs.tsv')}
        report['artifact_sha256'] = artifact_manifest(out)
        report['artifact_hash_exclusions'] = {'report.json': 'receipt written after manifest',
                                              'check.log': 'caller-owned orchestration log may still be open'}
        report['capture_sha256'] = {p.name: digest(p) for p in out.glob('*.stdout')}
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({k: report[k] for k in ('observation', 'compatibility', 'target')}, indent=2))
    return 0 if report['observation'] == 'complete' and report['compatibility'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
