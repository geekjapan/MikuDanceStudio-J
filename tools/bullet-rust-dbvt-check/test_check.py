"""Cheap checks for command construction and profile acceptance boundaries."""
import tempfile
import unittest
import contextlib
import io
import json
import sys
from pathlib import Path
import check


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
