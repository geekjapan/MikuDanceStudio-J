"""Cheap checks for command construction and profile acceptance boundaries."""
import tempfile
import unittest
import contextlib
import io
import json
import sys
from pathlib import Path
import check
from types import SimpleNamespace
from unittest.mock import patch


def profile(selected, win32='0', sse='0', template='0'):
    return (f'DBVT_SELECT_IMPL={selected}\nDBVT_MERGE_IMPL={selected}\n'
            f'DBVT_INT0_IMPL={selected}\nWIN32={win32}\nBT_USE_SSE={sse}\n'
            f'DBVT_USE_TEMPLATE={template}\nBT_HAS_ALIGNED_ALLOCATOR=0\n'
            'BT_USE_DOUBLE_PRECISION=0\n').encode()


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
            'cases': b'l 0\n' * 2326,
            'rust-tests': b'\ntest result: ok. 11 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s\n',
        }
        captures.update({f'native-{order}': b'0,0,0,0|_||\n' * 2326 for order in range(4)})
        captures.update({f'ffi-default-native-{order}': b'state\n' * 2326 for order in range(4)})
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
                            f'{i}\tl 0\t0,0,0,0|_||\n' for i in range(2326)))
                if name == 'rust-tests-build':
                    self.assertEqual(kwargs['cwd'], check.ROOT / 'rust')
                    self.assertEqual(command[-2:], ['--no-run', '--message-format=json'])
                return captures.get(name, b'')

            argv = ['check.py', '--out-dir', str(root / 'out'), '--expected-arch', arch,
                    '--expected-profile', 'sse' if msvc else 'generic']
            with patch.object(check, 'SRC', root), patch.object(check, 'provenance'), \
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
            ({'overrides': {'cases': b'operation\n' * 2325}}, 'operation corpus changed'),
            ({'overrides': {'native-lifecycle': b'event\n' * 9,
                            'rust-lifecycle': b'event\n' * 9}}, 'lifecycle corpus changed'),
        ]
        for order in range(4):
            cases += [({'overrides': {f'native-{order}': b'state\n' * 2325}},
                       str((order, 'incomplete capture'))),
                      ({'msvc': True, 'overrides': {
                          f'ffi-default-native-{order}': b'state\n' * 2325}},
                       str((order, 'incomplete diagnostic capture')))]
        for kwargs, message in cases:
            with self.subTest(message=message, options=tuple(kwargs)):
                with self.assertRaises(AssertionError) as caught:
                    self.run_mock_capture(**kwargs)
                self.assertEqual(str(caught.exception), message)

    def replay_fixture(self, root, *, input='v 0 0 0 1 1 1',
                       native='0,0,0,0|_||', rust='0,0,0,0|_||'):
        (root / 'inputs.tsv').write_text((input + '\n') * 2326)
        for order in range(4):
            (root / f'native-{order}.tsv').write_text((native + '\n') * 2326)
            (root / f'rust-{order}.tsv').write_text(''.join(
                f'{i}\t{input}\t{rust}\n' for i in range(2326)))

    def test_complete_stream_replay_and_transport(self):
        for newline in (b'\n', b'\r\n'):
            with self.subTest(newline=newline), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.replay_fixture(root)
                for path in root.glob('*.tsv'):
                    path.write_bytes(path.read_text().encode().replace(b'\n', newline))
                    self.assertEqual(path.read_bytes().count(newline), 2326)
                    path.write_bytes(path.read_text().encode().replace(b'\n', b'\r\n'))
                    raw = path.read_bytes()
                    self.assertEqual(raw.count(b'\r\n'), 2326)
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
                self.assertEqual(path.read_bytes().count(b'\r\r\n'), 2326)
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
            self.replay_fixture(root, input='s', native=native,
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
                check.parse_snapshot(row)

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


if __name__ == '__main__':
    unittest.main()
