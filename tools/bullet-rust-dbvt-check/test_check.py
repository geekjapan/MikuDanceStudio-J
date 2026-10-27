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
            'cases': b'operation\n' * 2326,
        }
        captures.update({f'native-{order}': b'state\n' * 2326 for order in range(4)})
        captures.update({f'ffi-default-native-{order}': b'state\n' * 2326 for order in range(4)})
        captures.update(overrides or {})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'BulletCollision/BroadphaseCollision'
            source.mkdir(parents=True)
            (source / 'btDbvt.h').write_text(header)
            argv = ['check.py', '--out-dir', str(root / 'out'), '--expected-arch', arch,
                    '--expected-profile', 'sse' if msvc else 'generic']
            with patch.object(check, 'SRC', root), patch.object(check, 'provenance'), \
                    patch.object(check, 'os', SimpleNamespace(
                        name='nt' if msvc else 'posix', environ={}, sep='/')), \
                    patch.object(check.platform, 'machine', return_value=machine), \
                    patch.object(sys, 'argv', argv), \
                    patch.object(check, 'run', side_effect=lambda command, out, name, **kw:
                                 captures.get(name, b'')) as run, \
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


if __name__ == '__main__':
    unittest.main()
