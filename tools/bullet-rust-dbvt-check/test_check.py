import tempfile
import unittest
from unittest.mock import patch
import contextlib
import io
import json
import sys
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location('check', Path(__file__).with_name('check.py'))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)
from types import SimpleNamespace


def profile(selected, win32='0', sse='0', template='0'):
    return (f'DBVT_SELECT_IMPL={selected}\nDBVT_MERGE_IMPL={selected}\n'
            f'DBVT_INT0_IMPL={selected}\nWIN32={win32}\nBT_USE_SSE={sse}\n'
            f'DBVT_USE_TEMPLATE={template}\nBT_HAS_ALIGNED_ALLOCATOR=0\n'
            'BT_USE_DOUBLE_PRECISION=0\n').encode()


def mock_snapshot(operation):
    event = {'h': '0', 'p': '0,0,0,0,0,0,0'}.get(operation[0], '')
    return '0,0,0,0|_||' + event


class HelperTests(unittest.TestCase):
    def test_msvc_profiles_do_not_share_win32_definition(self):
        output = Path('out') / 'oracle.exe'
        for diagnostic in (False, True):
            command = check.native_command('cl', ['oracle.cpp'], output,
                                           msvc=True, ffi_default=diagnostic)
            self.assertIn('/fp:precise', command)
            self.assertIn('/MD', command)
            self.assertIn('/EHsc', command)
            self.assertIn('/O2', command)
            self.assertEqual('/DWIN32' in command, not diagnostic)
            self.assertEqual(any(str(x).startswith('/FI') for x in command), diagnostic)
            self.assertEqual(command[-1], f'/Fe{output}')
            self.assertFalse(any('BT_HAS_ALIGNED_ALLOCATOR' in str(x) for x in command))

    def test_generic_command_keeps_compiler_argument_paths(self):
        command = check.native_command('clang++', ['path with spaces/oracle.cpp'], Path('out/oracle'), msvc=False)
        self.assertIn('path with spaces/oracle.cpp', command)
        self.assertIn('-ffp-contract=off', command)
        self.assertNotIn('/DWIN32', command)

    def test_profile_mismatch_fails(self):
        check.validate_profile(profile('0'), 'generic')
        check.validate_profile(profile('1', '1', '1', '1'), 'sse')
        check.validate_profile(profile('0', sse='1'), 'generic', ffi_default=True)
        for data, expected, diagnostic in [
            (profile('0'), 'sse', False),
            (profile('1', '1', '1', '1'), 'generic', False),
            (profile('0'), 'generic', True),
            (profile('0').replace(b'BT_HAS_ALIGNED_ALLOCATOR=0', b'BT_HAS_ALIGNED_ALLOCATOR=1'), 'generic', False),
        ]:
            with self.assertRaises(AssertionError):
                check.validate_profile(data, expected, ffi_default=diagnostic)

    def test_select_profiles_are_observably_different(self):
        generic = b'x\nx\nstate|B,0(B,0(1,0;3,0);2,0)|rank|\nx\n'
        sse = b'x\nx\nstate|B,0(1,0;B,0(2,0;3,0))|rank|\nx\n'
        check.validate_select(generic, 'generic')
        check.validate_select(sse, 'sse')
        with self.assertRaises(AssertionError):
            check.validate_select(generic, 'sse')

    def test_each_profile_guard_rejects_mismatch(self):
        for expected, diagnostic, valid in [
            ('generic', False, profile('0')),
            ('sse', False, profile('1', '1', '1', '1')),
            ('generic', True, profile('0', sse='1')),
        ]:
            keys = ['DBVT_SELECT_IMPL', 'DBVT_MERGE_IMPL', 'DBVT_INT0_IMPL',
                    'BT_HAS_ALIGNED_ALLOCATOR', 'BT_USE_DOUBLE_PRECISION']
            if expected == 'sse' or diagnostic:
                keys += ['WIN32', 'BT_USE_SSE']
            if expected == 'sse':
                keys += ['DBVT_USE_TEMPLATE']
            for key in keys:
                fields = dict(line.split('=', 1) for line in valid.decode().splitlines())
                fields[key] = '0' if fields[key] == '1' else '1'
                invalid = ''.join(f'{k}={v}\n' for k, v in fields.items()).encode()
                with self.subTest(expected=expected, diagnostic=diagnostic, key=key):
                    with self.assertRaises(AssertionError):
                        check.validate_profile(invalid, expected, ffi_default=diagnostic)

    def test_malformed_profiles_reject(self):
        for invalid, error in [(b'broken', ValueError), (b'\xff', UnicodeDecodeError),
                               (b'', KeyError), (b'DBVT_SELECT_IMPL=0\n', KeyError)]:
            with self.subTest(invalid=invalid), self.assertRaises(error):
                check.validate_profile(invalid, 'generic')

    def test_incomplete_select_rejects(self):
        for rows in (0, 3, 5):
            with self.subTest(rows=rows), self.assertRaisesRegex(
                    AssertionError, 'incomplete directed Select capture'):
                check.validate_select(b'x\n' * rows, 'generic')
        with self.assertRaises(IndexError):
            check.validate_select(b'x\n' * 4, 'generic')

    def run_mock_capture(self, *, msvc=False, machine='x86_64', arch='x64',
                         header='#undef DBVT_USE_MEMMOVE', overrides=None):
        captures = {
            'original-profile': profile('1', '1', '1', '1') if msvc else profile('0'),
            'ffi-default-profile': profile('0', sse='1'),
            'original-select': (b'x\nx\nstate|B(1;B(2;3))|rank|\nx\n' if msvc else
                                b'x\nx\nstate|B(B(1;3);2)|rank|\nx\n'),
            'ffi-default-select': b'x\nx\nstate|B(B(1;3);2)|rank|\nx\n',
            'native-lifecycle': b'event\r\n' * 10,
            'rust-lifecycle': b'event\n' * 10,
            'cases': check.subprocess.check_output([sys.executable, check.HERE / 'cases.py']),
            'rust-tests': b'\ntest result: ok. 11 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s\n',
        }
        captures.update({f'native-{order}': ''.join(
            mock_snapshot(line) + '\n' for line in captures['cases'].decode().splitlines()).encode()
            for order in range(4)})
        captures.update({f'ffi-default-native-{order}': b'state\n' * 2355 for order in range(4)})
        captures.update(overrides or {})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'BulletCollision/BroadphaseCollision'
            source.mkdir(parents=True)
            (source / 'btDbvt.h').write_text(header)
            binary = root / 'test-binary'
            binary.write_bytes(b'mock compiled executable')
            captures.setdefault('rust-tests-build', json.dumps(dict(
                reason='compiler-artifact', target=dict(name='dbvt', kind=['test'],
                src_path=str(check.HERE / 'test.rs')), manifest_path=str(check.HERE / 'Cargo.toml'),
                profile=dict(test=True), executable=str(binary))).encode() +
                b'\n{"reason":"build-finished","success":true}\n')

            def capture(command, out, name, **kwargs):
                if name == 'rust-tests':
                    self.assertEqual(kwargs['cwd'], check.ROOT / 'rust')
                    self.assertEqual(command, [out / ('dbvt-tests.exe' if msvc else 'dbvt-tests')])
                    for order in range(4):
                        (out / f'rust-{order}.tsv').write_text(''.join(
                            f'{i}\t{line}\t{mock_snapshot(line)}\n' for i, line in enumerate(captures['cases'].decode().splitlines())))
                if name == 'rust-tests-build':
                    self.assertEqual(kwargs['cwd'], check.ROOT / 'rust')
                    self.assertEqual(command[-2:], ['--no-run', '--message-format=json'])
                return captures.get(name, b'')

            argv = ['check.py', '--out-dir', str(root / 'out'), '--expected-arch', arch,
                    '--expected-profile', 'sse' if msvc else 'generic',
                    '--rust-policy', 'mmd-win64-sse' if msvc else 'generic-reference']
            with patch.object(check, 'SRC', root), patch.object(check, 'provenance'), patch.object(check, 'verify_numeric_policies'), \
                    patch.object(check, 'os', SimpleNamespace(
                        name='nt' if msvc else 'posix', environ={}, sep='/')), \
                    patch.object(check.platform, 'machine', return_value=machine), \
                    patch.object(sys, 'argv', argv), \
                    patch.object(check, 'run', side_effect=capture) as run, \
                    contextlib.redirect_stdout(io.StringIO()):
                check.main()
                self.assertEqual(run.call_args.args[2], 'rust-tests')

    def test_valid_mock_captures_preserve_acceptance(self):
        for msvc, machine, arch in [(False, 'x86_64', 'x64'), (False, 'aarch64', 'arm64'),
                                    (True, 'AMD64', 'x64')]:
            with self.subTest(msvc=msvc, machine=machine):
                self.run_mock_capture(msvc=msvc, machine=machine, arch=arch)

    def test_main_guards_reject_invalid_captures(self):
        cases = [
            ({'machine': 'arm64'}, "('arm64', 'x64')"),
            ({'header': ''}, ''),
            ({'header': '#undef DBVT_USE_MEMMOVE\n#undef DBVT_USE_MEMMOVE'}, ''),
            ({'overrides': {'rust-lifecycle': b'other\n' * 10}},
             'actual allocator release order differs from native'),
            ({'overrides': {'cases': b'operation\n' * 2354}}, 'frozen operation prefix changed or extension missing'),
            ({'overrides': {'native-lifecycle': b'event\n' * 9,
                            'rust-lifecycle': b'event\n' * 9}}, 'lifecycle corpus changed'),
        ]
        for order in range(4):
            cases += [({'overrides': {f'native-{order}': b'state\n' * 2354}},
                       str((order, 'incomplete capture'))),
                      ({'msvc': True, 'overrides': {
                          f'ffi-default-native-{order}': b'state\n' * 2354}},
                       str((order, 'incomplete diagnostic capture')))]
        for kwargs, message in cases:
            with self.subTest(message=message, options=tuple(kwargs)):
                with self.assertRaises((AssertionError, ValueError)) as caught:
                    self.run_mock_capture(**kwargs)
                self.assertEqual(str(caught.exception), message)

    def replay_fixture(self, root, *, input='v 0 0 0 1 1 1',
                       native='0,0,0,0|_||', rust='0,0,0,0|_||'):
        (root / 'inputs.tsv').write_text((input + '\n') * 2355)
        for order in range(4):
            (root / f'native-{order}.tsv').write_text((native + '\n') * 2355)
            (root / f'rust-{order}.tsv').write_text(''.join(
                f'{i}\t{input}\t{rust}\n' for i in range(2355)))

    def test_complete_stream_replay_and_transport(self):
        for newline in (b'\n', b'\r\n'):
            with self.subTest(newline=newline), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.replay_fixture(root)
                for path in root.glob('*.tsv'):
                    path.write_bytes(path.read_text().encode().replace(b'\n', newline))
                    self.assertEqual(path.read_bytes().count(newline), 2355)
                    path.write_bytes(path.read_text().encode().replace(b'\n', b'\r\n'))
                    raw = path.read_bytes()
                    self.assertEqual(raw.count(b'\r\n'), 2355)
                    self.assertNotIn(b'\r\r\n', raw)
                retained = {path: path.read_bytes() for path in root.glob('*.tsv')}
                check.compare_streams(root)
                self.assertEqual({path: path.read_bytes() for path in retained}, retained)

    def test_doubled_carriage_return_transport_rejects_full_corpus(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.replay_fixture(root)
            for path in root.glob('*.tsv'):
                crlf = path.read_text().encode().replace(b'\n', b'\r\n')
                path.write_bytes(crlf.replace(b'\n', b'\r\n'))
                self.assertEqual(path.read_bytes().count(b'\r\r\n'), 2355)
            with self.assertRaisesRegex(AssertionError, '^operation corpus changed$'):
                check.compare_streams(root)

    def test_stream_length_and_identity_reject_missing_extra_duplicate_and_reorder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.replay_fixture(root)
            for order in range(4):
                for kind in ('native', 'rust'):
                    path = root / f'{kind}-{order}.tsv'
                    valid = path.read_text()
                    lines = valid.splitlines(keepends=True)
                    invalids = ['', ''.join(lines[:-1]), valid + lines[-1]]
                    if kind == 'rust':
                        invalids += [lines[0] + ''.join(lines[:-1]),
                                     lines[1] + lines[0] + ''.join(lines[2:]),
                                     valid.replace('0\tv ', '0\tq ', 1)]
                    for invalid in invalids:
                        with self.subTest(order=order, kind=kind, length=len(invalid)):
                            path.write_text(invalid)
                            with self.assertRaises(AssertionError):
                                check.compare_streams(root)
                    path.write_text(valid)
            path = root / 'rust-0.tsv'
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                check.compare_streams(root)

    def test_corrupted_complete_stream_rejects_without_changing_raw(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.replay_fixture(root, input='l 0')
            for order in range(4):
                path = root / f'rust-{order}.tsv'
                valid = path.read_text()
                for replacement in ('0,0,0,0|_||1,', '0,0,0,0|broken||',
                                    '0,0,0,0|_||bad', '0,0,0,0|_|1,|'):
                    raw = valid.replace('0,0,0,0|_||', replacement, 1)
                    path.write_text(raw)
                    with self.subTest(order=order, replacement=replacement):
                        with self.assertRaises(AssertionError):
                            check.compare_streams(root)
                        self.assertEqual(path.read_text(), raw)
                path.write_text(valid)

    def test_ordinary_semantics_keep_raw_order_but_controlled_is_exact(self):
        a = '1,0,0,0,0,0,0'
        b = '2,0,0,0,0,0,0'
        branch = 'B,0,0,0,0,0,0'
        native = f'2,0,0,0|{branch}({a};{b})|0,1,2,|2:1,1:2,'
        rust = f'2,0,0,0|{branch}({b};{a})||1:2,2:1,'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.replay_fixture(root, input='f 1', native=native,
                                rust=native.replace('|0,1,2,|', '||'))
            path = root / 'rust-3.tsv'
            path.write_text(path.read_text().replace(native.replace('|0,1,2,|', '||'), rust))
            check.compare_streams(root)
            for order in range(3):
                path = root / f'rust-{order}.tsv'
                valid = path.read_text()
                path.write_text(valid.replace(native.replace('|0,1,2,|', '||'), rust))
                with self.assertRaisesRegex(AssertionError, 'replay differs'):
                    check.compare_streams(root)
                path.write_text(valid)
            path = root / 'rust-3.tsv'
            path.write_text(path.read_text().replace('1:2,2:1,', '1:2,'))
            with self.assertRaises(AssertionError):
                check.compare_streams(root)

    def test_snapshot_parser_rejects_malformed_complete_rows(self):
        for row in ('', '0,0,0,0|_||extra|', '0,0,0,2|_||',
                    '0,0,0,0|_x||', '0,0,0,0|_(;)||',
                    '0,0,0,0|B,0,0,0,0,0,0(_;)||', '0,0,0,0|B,0,0,0,0,0,0(_;_)||', '0,0,0,0|_||1:2',
                    '0,0,0,0|_|oops|'):
            with self.subTest(row=row), self.assertRaises(AssertionError):
                check.parse_snapshot(row, 's')

    def test_empty_bounds_counterexample_is_bound_to_input_operation(self):
        row = '1,-1,0,0|_||0'
        for rust in (False, True):
            self.assertEqual(check.parse_snapshot(row, 'h', rust=rust),
                             (['1,-1,0,0', '_', '', '0'], []))
            for op in 'pvqsxfgiurelntbc?':
                with self.subTest(op=op, rust=rust), self.assertRaises(AssertionError):
                    check.parse_snapshot(row, op, rust=rust)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.replay_fixture(root, input='h', native=row, rust=row)
            check.compare_streams(root)
            (root / 'inputs.tsv').write_text('p 1 0 0 0 1 1 1 0 0 0 1\n' * 2355)
            for order in range(4):
                path = root / f'rust-{order}.tsv'
                path.write_text(path.read_text().replace('\th\t', '\tp 1 0 0 0 1 1 1 0 0 0 1\t'))
            with self.assertRaisesRegex(AssertionError, 'malformed DBVT events'):
                check.compare_streams(root)

    def test_event_variants_require_exact_operation_grammar(self):
        valid = [('h', '0'), ('h', '1,0,1,2,3,4,4294967295'),
                 ('p', '0,0,1,2,3,4,5'), ('p', '1,0,1,2,3,4,5')]
        valid += [(op, event) for op in 'vq' for event in ('', '0,12,12,')]
        valid += [(op, event) for op in 'sxfg' for event in ('', '0:12,12:0,')]
        valid += [(op, '') for op in 'iurelntbc']
        invalid = [('h', event) for event in ('', '1', '0,', '0,0,1,2,3,4,5',
                    '1,0,1,2,3,4', '1,0,1,2,3,4,5,6', '1,0,1,2,3,4,5,',
                    '2,0,1,2,3,4,5', '1,-1,1,2,3,4,5', '1,+1,1,2,3,4,5',
                    '1,1.0,1,2,3,4,5', '1,1e2,1,2,3,4,5', '1,0x1,1,2,3,4,5')]
        invalid += [('p', event) for event in ('', '0', '1', '0,0,1,2,3,4,5,', '1,0,1,2,3,4')]
        invalid += [(op, event) for op in 'vq' for event in ('1', '1:2,', '1,,', '-1,', '1.0,')]
        invalid += [(op, event) for op in 'sxfg' for event in ('1:2', '1,', '1:2:3,', '-1:2,', '1:2,,')]
        invalid += [(op, '1,') for op in 'iurelntbc']
        invalid += [(op, '') for op in ('?', '', 'hh', 'vp')]
        for op, event in valid:
            with self.subTest(op=op, event=event):
                self.assertEqual(check.parse_snapshot('0,0,0,0|_||' + event, op)[0][3], event)
        for op, event in invalid:
            with self.subTest(op=op, event=event), self.assertRaises(AssertionError):
                check.parse_snapshot('0,0,0,0|_||' + event, op)

    def test_test_summary_rejects_filtered_ignored_empty_and_duplicate(self):
        valid = b'test result: ok. 11 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s\n'
        check.validate_test_result(valid)
        for invalid in (b'', valid + valid, valid.replace(b'11 passed', b'10 passed'),
                        valid.replace(b'0 ignored', b'1 ignored'),
                        valid.replace(b'0 filtered', b'1 filtered'),
                        valid.replace(b'ok.', b'FAILED.')):
            with self.subTest(invalid=invalid), self.assertRaises(AssertionError):
                check.validate_test_result(invalid)

    def test_exact_cargo_artifact_retains_only_owned_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'original'
            binary.write_bytes(b'actual mock test bytes')
            out = root / 'out'
            out.mkdir()
            item = dict(reason='compiler-artifact', target=dict(name='dbvt', kind=['test'],
                src_path=str(check.HERE / 'test.rs')), manifest_path=str(check.HERE / 'Cargo.toml'),
                profile=dict(test=True), executable=str(binary))
            encode = lambda value: (json.dumps(value) + '\n' +
                '{"reason":"build-finished","success":true}\n').encode()
            retained = check.retain_test_binary(
                b'[quote 1.0.47] cargo:rerun-if-changed=build.rs\r\n' + encode(item) +
                b'non-JSON trailing diagnostic\n', out)
            self.assertEqual(retained.read_bytes(), binary.read_bytes())
            manifest = json.loads((out / 'rust-test-binary.json').read_text())
            self.assertEqual(manifest['bytes'], binary.stat().st_size)
            self.assertEqual(manifest['sha256'], check.hashlib.sha256(binary.read_bytes()).hexdigest())
            self.assertEqual(manifest['cwd'], str(check.ROOT / 'rust'))
            self.assertEqual(manifest['argv'], [str(retained)])
            for invalid in (b'', b'not JSON', encode(item) * 2,
                            (json.dumps(item) + '\n').encode() + encode(item),
                            b'{"reason":"build-finished","success":true}\n',
                            encode(dict(item, manifest_path=str(root / 'Cargo.toml'))),
                            encode(dict(item, target=dict(item['target'], name='foreign'))),
                            encode(dict(item, target=[])),
                            encode(dict(item, profile=[])),
                            encode(dict(item, executable=7)),
                            encode(dict(item, executable=None)),
                            encode(dict(item, executable=str(root / 'missing'))),
                            encode(dict(item, profile=dict(test=False))),
                            encode(dict(item, target=dict(item['target'], src_path=str(root / 'test.rs')))),
                            encode(dict(item, target=dict(item['target'], kind=['bin'])))):
                with self.subTest(invalid=invalid), self.assertRaises((AssertionError, ValueError)):
                    check.retain_test_binary(invalid, out)
            binary.write_bytes(b'')
            with self.assertRaisesRegex(AssertionError, 'empty'):
                check.retain_test_binary(encode(item), out)

    def test_cargo_object_stream_requires_strict_json_and_terminal_success(self):
        artifact = b'{"reason":"compiler-artifact","target":{"name":"foreign"}}\n'
        finish = b'{"reason":"build-finished","success":true}\n'
        mixed = b'[quote 1.0.47] cargo:rerun-if-changed=build.rs\r\n' + artifact + finish
        self.assertEqual(check.cargo_objects(mixed), [json.loads(artifact), json.loads(finish)])
        self.assertEqual(check.cargo_objects(mixed + b'program output\n'),
                         check.cargo_objects(mixed))
        for invalid in (b'', b'non-JSON success=true', artifact, finish + finish,
                        finish + artifact, b'{broken}\n' + finish,
                        b'{"reason":"build-finished","reason":"build-finished","success":true}\n',
                        b'{"reason":"message","nested":{"x":1,"x":2}}\n' + finish,
                        b'{"reason":"message","x":NaN}\n' + finish,
                        b'{"reason":"message","x":Infinity}\n' + finish,
                        b'{"reason":"message","x":-Infinity}\n' + finish,
                        b'{"reason":"message","x":1e999}\n' + finish,
                        b'{"reason":"build-finished"}\n',
                        b'{"reason":"build-finished","success":false}\n',
                        b'{"reason":"build-finished","success":1}\n',
                        b'{"reason":"build-finished","success":true',
                        b'{}\n' + finish, b'{"reason":null}\n' + finish):
            with self.subTest(invalid=invalid), self.assertRaises((AssertionError, ValueError)):
                check.cargo_objects(invalid)

    def test_provenance_includes_consumed_crtmath_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'rust/crates/mds-crtmath/src/lib.rs'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'consumed source')
            def git(command, **kwargs):
                self.assertEqual(kwargs['cwd'], root)
                if command[1] == 'ls-files':
                    self.assertIn('rust/crates/mds-crtmath', command)
                    return b'rust/crates/mds-crtmath/src/lib.rs\0'
                return b'fixed-head\n'
            with patch.object(check, 'ROOT', root), \
                    patch.object(check.platform, 'platform', return_value='mock host'), \
                    patch.object(check.subprocess, 'check_output', side_effect=git):
                check.provenance(root)
            data = json.loads((root / 'provenance.json').read_text())
            self.assertEqual(data['source_sha256'], {
                'rust/crates/mds-crtmath/src/lib.rs': check.hashlib.sha256(path.read_bytes()).hexdigest()})

    def test_failed_process_preserves_logs_and_command(self):
        import sys
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with self.assertRaises(subprocess.CalledProcessError):
                check.run([sys.executable, '-c', 'print("diagnostic"); raise SystemExit(7)'], out, 'failure', capture=True)
            self.assertIn(b'diagnostic', (out / 'failure-stdout.log').read_bytes())
            self.assertTrue((out / 'failure-command.json').is_file())

    def test_process_cwd_and_output_capture(self):
        command = [sys.executable, '-c',
                   'import os, sys; print(os.getcwd()); print("diagnostic", file=sys.stderr)']
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory).resolve()
            for cwd in (check.ROOT, out):
                for capture in (False, True):
                    with self.subTest(cwd=cwd, capture=capture):
                        stdout, stderr = io.StringIO(), io.StringIO()
                        kwargs = {} if cwd == check.ROOT else {'cwd': cwd}
                        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                            data = check.run(command, out, 'cwd', capture=capture, **kwargs)
                        self.assertEqual(data.decode().strip(), str(cwd))
                        self.assertEqual((out / 'cwd-stdout.log').read_bytes(), data)
                        self.assertEqual((out / 'cwd-stderr.log').read_bytes().strip(), b'diagnostic')
                        self.assertEqual(json.loads((out / 'cwd-command.json').read_text()), command)
                        self.assertEqual(stdout.getvalue(), check.subprocess.list2cmdline(command) + '\n'
                                         + ('' if capture else data.decode() + '\n'))
                        self.assertEqual(stderr.getvalue(), (out / 'cwd-stderr.log').read_bytes().decode() + '\n')


    def test_all_profile_fields_and_short_select_are_rejected(self):
        valid = profile('1', '1', '1', '1')
        for line in valid.splitlines():
            key, value = line.split(b'=')
            broken = valid.replace(line, key + b'=' + (b'0' if value == b'1' else b'1'))
            with self.subTest(key=key), self.assertRaises(AssertionError):
                check.validate_profile(broken, 'sse')
        for rows in [b'', b'x\nx\nx\n']:
            with self.subTest(rows=rows), self.assertRaisesRegex(AssertionError, 'incomplete directed Select capture'):
                check.validate_select(rows, 'generic')

    def test_corpus_preserves_prefix_and_requires_extension(self):
        generated = check.subprocess.check_output([sys.executable, check.HERE / 'cases.py'])
        lf = generated.replace(b'\r\n', b'\n')
        for generator_output in (lf, lf.replace(b'\n', b'\r\n')):
            with self.subTest(generator_crlf=b'\r\n' in generator_output):
                data = generator_output.replace(b'\r\n', b'\n')
                self.assertEqual(check.validate_corpus(data), 2355)
                self.assertEqual(check.validate_corpus(data.replace(b'\n', b'\r\n')), 2355)
                for broken in [b'bad\n' + data, b''.join(data.splitlines(keepends=True)[:2326]),
                               data.replace(b'\n', b'\r\r\n')]:
                    with self.assertRaisesRegex(ValueError, 'frozen operation prefix'):
                        check.validate_corpus(broken)

    def test_explicit_numeric_driver_and_capture_wrappers(self):
        source = check.reference_module().RUST_DRIVER
        self.assertIn('Some("mmd-win64-sse")', source)
        self.assertIn('Some("generic-reference")', source)
        self.assertIn('policy.intersects(a, b)', source)
        self.assertNotIn('cfg!', source)
        fixtures = (check.HERE / 'fixtures.rs').read_text()
        for name in ['native_controlled_address_parity', 'ordinary_native_and_production_allocator_query_sets']:
            self.assertIn(f'fn {name}(policy: DbvtPolicy)', fixtures)
            self.assertNotIn(f'#[test]\nfn {name}', fixtures)
            self.assertIn(f'#[test]\nfn {name}', (check.HERE / 'test.rs').read_text())

    def numeric_policy_run(self, out, *, select=None, numeric=None):
        fixtures = check.ROOT / 'rust/crates/mds-bullet/tests/dbvt_data'
        captured = (fixtures / 'inline-aabb.tsv').read_bytes()
        generic = captured.splitlines()
        for index in range(27, 51):
            words = generic[index].split(b',')
            words[1] = b'0' if words[1] == b'1' else b'1'
            generic[index] = b','.join(words)
        outputs = {'mmd-win64-sse-numeric': captured,
                   'generic-reference-numeric': b'\n'.join(generic) + b'\n',
                   'mmd-win64-sse-select': b'3,2,1,\n',
                   'generic-reference-select': b'2,3,1,\n'}
        outputs.update(select or {})
        outputs.update(numeric or {})

        def run(command, directory, name, **kwargs):
            if name == 'numeric-build':
                Path(command[-1]).write_bytes(b'mocked numeric binary')
            return outputs.get(name, b'')

        with patch.object(check, 'run', side_effect=run) as mocked:
            check.verify_numeric_policies(out)
        return mocked

    def test_numeric_policies_reject_invalid_select_for_both_policies(self):
        for policy in check.POLICIES.values():
            wrong = b'2,3,1,\n' if policy == 'mmd-win64-sse' else b'1,2,3,\n'
            for data in (b'', b'2,3,', b'1,1,2,\n', b'bad\n',
                         b'2,3,1,\nextra\n', wrong):
                with self.subTest(policy=policy, data=data), tempfile.TemporaryDirectory() as directory:
                    out = Path(directory)
                    with self.assertRaises(ValueError):
                        self.numeric_policy_run(out, select={policy + '-select': data})
                    self.assertFalse((out / 'numeric-policy-results.json').exists())

    def test_numeric_policies_keep_full_schema_and_exact_mismatch_cases(self):
        fixtures = check.ROOT / 'rust/crates/mds-bullet/tests/dbvt_data'
        captured = (fixtures / 'inline-aabb.tsv').read_bytes()
        rows = captured.splitlines()
        for policy in check.POLICIES.values():
            for data in (b'', b'\n'.join(rows[:-1]) + b'\n',
                         captured.replace(b',', b',bad,', 1),
                         b'\n'.join([rows[0] + b',0', *rows[1:]]) + b'\n',
                         b'\n'.join([rows[0], rows[0], *rows[2:]]) + b'\n'):
                with self.subTest(policy=policy, data=data[:40]), tempfile.TemporaryDirectory() as directory:
                    out = Path(directory)
                    with self.assertRaises(ValueError):
                        self.numeric_policy_run(out, numeric={policy + '-numeric': data})
                    self.assertFalse((out / 'numeric-policy-results.json').exists())
        for changed in (range(26, 51), range(28, 51), []):
            generic = rows.copy()
            for index in changed:
                words = generic[index].split(b',')
                words[1] = b'0' if words[1] == b'1' else b'1'
                generic[index] = b','.join(words)
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, 'expected semantic mismatches'):
                    self.numeric_policy_run(Path(directory), numeric={
                        'generic-reference-numeric': b'\n'.join(generic) + b'\n'})

    def test_numeric_policies_accept_exact_policy_results(self):
        for ending in (b'\n', b'\r\n'):
            with self.subTest(ending=ending), tempfile.TemporaryDirectory() as directory:
                out = Path(directory)
                mocked = self.numeric_policy_run(out, select={
                    'mmd-win64-sse-select': b'3,2,1,' + ending,
                    'generic-reference-select': b'2,3,1,' + ending})
                results = json.loads((out / 'numeric-policy-results.json').read_text())
                self.assertEqual(results, {
                    'mmd-win64-sse': {'numeric_mismatch_cases': [], 'select_matches': True},
                    'generic-reference': {'numeric_mismatch_cases': list(range(27, 51)), 'select_matches': False}})
                binary = json.loads((out / 'numeric-binary.json').read_text())
                self.assertEqual(binary['sha256'], check.hashlib.sha256(b'mocked numeric binary').hexdigest())
                self.assertEqual(binary['source_sha256'], check.hashlib.sha256((out / 'numeric.rs').read_bytes()).hexdigest())
                self.assertEqual(binary['build_command'], 'numeric-build-command.json')
                self.assertEqual([call.args[2] for call in mocked.call_args_list], [
                    'numeric-crt-build', 'numeric-math-build', 'numeric-build',
                    'mmd-win64-sse-numeric', 'mmd-win64-sse-select',
                    'generic-reference-numeric', 'generic-reference-select'])
                for call in mocked.call_args_list[3:]:
                    policy, kind = call.args[2].rsplit('-', 1)
                    self.assertEqual(call.args[0][1:], [policy, 'aabb' if kind == 'numeric' else 'select'])

    def test_replay_rejects_incomplete_or_foreign_captures_before_running_rust(self):
        inputs = check.subprocess.check_output([sys.executable, check.HERE / 'cases.py'])
        with tempfile.TemporaryDirectory() as directory:
            captures = Path(directory)
            (captures / 'inputs.tsv').write_bytes(inputs)
            for order in range(4):
                (captures / f'native-{order}.tsv').write_bytes(b'')
            with patch.object(check, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'incomplete Windows-sourced'):
                    check.replay(captures, captures)
                for order in range(4):
                    (captures / f'native-{order}.tsv').write_bytes(b'unit-control\n' * 2355)
                (captures / 'provenance.json').write_text(json.dumps({'commit': 'foreign-checkout'}))
                with self.assertRaisesRegex(ValueError, 'source commit differs'):
                    check.replay(captures, captures)
                run.assert_not_called()

    def test_replay_rejects_invalid_source_inventory_before_source_reads_or_outputs(self):
        inputs = check.subprocess.check_output([sys.executable, check.HERE / 'cases.py'])
        hashes = {p: check.hashlib.sha256((check.ROOT / p).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                  for p in check.source_paths()}
        self.assertEqual(len(hashes), 482)
        commit = check.subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=check.ROOT).decode().strip()
        known = 'rust/crates/mds-bullet/src/core/dbvt.rs'
        invalid = [None, [], '', {}, {known: hashes[known]},
                   {p: h for p, h in hashes.items() if p != known}]
        for extra in ['AGENTS.md', str(check.ROOT / known), 'rust/../' + known]:
            invalid.append({**hashes, extra: hashes[known]})
        with tempfile.TemporaryDirectory() as directory:
            captures = Path(directory)
            (captures / 'inputs.tsv').write_bytes(inputs)
            for order in range(4):
                (captures / f'native-{order}.tsv').write_bytes(b'unit-control\n' * 2355)
            read_bytes = Path.read_bytes

            def capture_read(path):
                if path.is_relative_to(check.ROOT):
                    self.fail('source read before inventory validation: ' + str(path))
                return read_bytes(path)

            for inventory in invalid:
                with self.subTest(inventory_type=type(inventory).__name__, size=len(inventory) if inventory is not None else None):
                    (captures / 'provenance.json').write_text(json.dumps({
                        'commit': commit, 'source_lf_sha256': inventory}))
                    with patch.object(Path, 'read_bytes', capture_read), \
                            patch.object(Path, 'write_text', side_effect=AssertionError('replay output forbidden')), \
                            patch.object(check, 'run', side_effect=AssertionError('build forbidden')):
                        with self.assertRaisesRegex(ValueError, 'source inventory differs'):
                            check.replay(captures, captures)
            (captures / 'provenance.json').write_text(json.dumps({
                'commit': commit, 'source_lf_sha256': {**hashes, known: '0' * 64}}))
            with patch.object(Path, 'write_text', side_effect=AssertionError('replay output forbidden')), \
                    patch.object(check, 'run', side_effect=AssertionError('build forbidden')):
                with self.assertRaisesRegex(ValueError, 'source bytes differ'):
                    check.replay(captures, captures)

    def test_windows_replay_retains_binary_and_streams_without_mutating_capture(self):
        inputs = check.subprocess.check_output([sys.executable, check.HERE / 'cases.py'])
        hashes = {p: check.hashlib.sha256((check.ROOT / p).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                  for p in check.source_paths()}
        self.assertEqual(len(hashes), 482)
        commit = check.subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=check.ROOT).decode().strip()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captures, out = root / 'captures', root / 'out'
            captures.mkdir()
            out.mkdir()
            (captures / 'inputs.tsv').write_bytes(inputs)
            for order in range(4):
                (captures / f'native-{order}.tsv').write_text(''.join(
                    mock_snapshot(line) + '\n' for line in inputs.decode().splitlines()))
            (captures / 'original-profile.txt').write_bytes(profile('1', '1', '1', '1'))
            selected = (b'1,-1,0,0|1,1056964608,1258291200,1056964608,1056964608,1258291200,1056964608|0,|\r\n'
                        b'2,-1,0,0|B,1056964608,1258291200,0,1065353216,1258291200,1056964608(1,1056964608,1258291200,1056964608,1056964608,1258291200,1056964608;2,1065353216,1258291200,0,1065353216,1258291200,0)|2,0,1,|\r\n'
                        b'3,-1,0,0|B,0,0,0,1065353216,1258291200,1056964608(1,1056964608,1258291200,1056964608,1056964608,1258291200,1056964608;B,0,0,0,1065353216,1258291200,0(2,1065353216,1258291200,0,1065353216,1258291200,0;3,0,0,0,0,0,0))|2,0,4,1,3,|\r\n'
                        b'3,-1,0,0|B,0,0,0,1065353216,1258291200,1056964608(1,1056964608,1258291200,1056964608,1056964608,1258291200,1056964608;B,0,0,0,1065353216,1258291200,0(2,1065353216,1258291200,0,1065353216,1258291200,0;3,0,0,0,0,0,0))|2,0,4,1,3,|3,2,1,\r\n')
            (captures / 'original-select-stdout.log').write_bytes(selected)
            (captures / 'provenance.json').write_text(json.dumps({
                'commit': commit, 'source_lf_sha256': hashes}))
            retained = {p: p.read_bytes() for p in captures.iterdir()}
            binary = root / 'built'
            binary.write_bytes(b'mocked executable')
            build = (json.dumps(dict(reason='compiler-artifact', target=dict(name='dbvt',
                kind=['test'], src_path=str(check.HERE / 'test.rs')),
                manifest_path=str(check.HERE / 'Cargo.toml'), profile=dict(test=True),
                executable=str(binary))) + '\n{"reason":"build-finished","success":true}\n').encode()

            def run(command, directory, name, **kwargs):
                self.assertEqual(kwargs['cwd'], check.ROOT / 'rust')
                if name == 'windows-sourced-rust-tests-build':
                    self.assertEqual(command[-2:], ['--no-run', '--message-format=json'])
                    return build
                self.assertEqual(command, [out / ('dbvt-tests.exe' if check.os.name == 'nt' else 'dbvt-tests')])
                self.assertEqual(kwargs['env']['DBVT_FIXTURES'], str(out))
                self.assertEqual(kwargs['env']['DBVT_POLICY'], 'mmd-win64-sse')
                self.assertEqual(name, 'windows-sourced-rust-tests')
                self.assertEqual((Path(kwargs['env']['DBVT_FIXTURES']) /
                                  'original-select-stdout.log').read_bytes(), selected)
                for order in range(4):
                    (out / f'rust-{order}.tsv').write_text(''.join(
                        f'{i}\t{line}\t{mock_snapshot(line)}\n' for i, line in enumerate(inputs.decode().splitlines())))
                return b'test result: ok. 11 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s\n'

            with patch.object(check, 'run', side_effect=run), \
                    patch.object(check, 'verify_numeric_policies') as numeric:
                check.replay(out, captures)
            numeric.assert_called_once_with(out)
            self.assertEqual({p: p.read_bytes() for p in captures.iterdir()}, retained)
            self.assertEqual((out / ('dbvt-tests.exe' if check.os.name == 'nt' else 'dbvt-tests')).read_bytes(), binary.read_bytes())

    def test_replay_rejects_missing_or_invalid_select_before_build_or_outputs(self):
        inputs = check.subprocess.check_output([sys.executable, check.HERE / 'cases.py'])
        hashes = {p: check.hashlib.sha256((check.ROOT / p).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                  for p in check.source_paths()}
        commit = check.subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=check.ROOT).decode().strip()
        with tempfile.TemporaryDirectory() as directory:
            captures, out = Path(directory) / 'captures', Path(directory) / 'out'
            captures.mkdir()
            out.mkdir()
            (captures / 'inputs.tsv').write_bytes(inputs)
            for order in range(4):
                (captures / f'native-{order}.tsv').write_bytes(b'unit-control\n' * 2355)
            (captures / 'original-profile.txt').write_bytes(profile('1', '1', '1', '1'))
            (captures / 'provenance.json').write_text(json.dumps({
                'commit': commit, 'source_lf_sha256': hashes}))
            for selected, error in [(None, FileNotFoundError), (b'x\n' * 3, AssertionError),
                                    (b'x\nx\nstate|B(B(1;3);2)|rank|\nx\n', AssertionError)]:
                with self.subTest(selected=selected):
                    if selected is not None:
                        (captures / 'original-select-stdout.log').write_bytes(selected)
                    retained = {p: p.read_bytes() for p in captures.iterdir()}
                    with patch.object(check, 'run') as run:
                        with self.assertRaises(error):
                            check.replay(out, captures)
                        run.assert_not_called()
                    self.assertEqual(list(out.iterdir()), [])
                    self.assertEqual({p: p.read_bytes() for p in captures.iterdir()}, retained)

    def test_actual_windows_fixture_bytes_match_provenance(self):
        fixtures = check.ROOT / 'rust/crates/mds-bullet/tests/dbvt_data'
        provenance = json.loads((fixtures / 'provenance.json').read_text())
        self.assertEqual(provenance['run_id'], 40465192152)
        self.assertEqual(provenance['zip_sha256'], '4d3247c287eee3e3040f06efe64a60600c3740f947220f8427c8534b5fbc5ecf')
        for name, item in provenance['members'].items():
            self.assertEqual(check.hashlib.sha256((fixtures / name).read_bytes()).hexdigest(), item['sha256'])
        reference = check.reference_module()
        self.assertEqual(len(reference.rows((fixtures / 'inline-aabb.tsv').read_bytes(), 13)), 51)
        for width, name in [(12, 'archive-merge.tsv'), (1, 'archive-intersect.tsv')]:
            self.assertEqual(len(reference.rows((fixtures / name).read_bytes(), width)), 51)



if __name__ == '__main__':
    unittest.main()
