#!/usr/bin/env python3
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('cmake_reference', Path(__file__).with_name('check.py'))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class Controls(unittest.TestCase):
    def test_windows_quotes_round_trip(self):
        for args in ([r'C:\Program Files\cl.exe', '/Iinc path', '/DNAME="value"', 'C:\\output\\', ''],
                     ['/FIforced.h', '/DWIN32', r'quote\"x', 'a b\\']):
            self.assertEqual(check.split_command(subprocess.list2cmdline(args)), args)

    def test_unterminated_quote(self):
        with self.assertRaises(ValueError):
            check.split_command('/I"never closed')

    def test_response_encoding_and_nested_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'inner.rsp').write_bytes('/UWIN32 /DWIN32 /fp:precise'.encode('utf-16'))
            (root / 'outer.rsp').write_text('/I"a b" @inner.rsp /std:c++17')
            records = []
            self.assertEqual(check.expand(['@outer.rsp', '/O2'], root, records),
                             ['/Ia b', '/UWIN32', '/DWIN32', '/fp:precise', '/std:c++17', '/O2'])
            self.assertEqual(records[1]['encoding'], 'utf-16')
            self.assertEqual(records[1]['sha256'], check.digest(root / 'inner.rsp'))

    def test_response_missing_and_cycle_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(OSError):
                check.expand(['@missing.rsp'], root, [])
            (root / 'loop.rsp').write_text('@loop.rsp')
            with self.assertRaises(ValueError):
                check.expand(['@loop.rsp'], root, [])

    def test_replay_keeps_ordered_semantic_flags(self):
        args = ['/c', '/DWIN32', '/UWIN32', '/DWIN32', '/FIforced.h', '/Iinclude',
                '/std:c++17', '/fp:precise', '/O2', '/Foobj/', '/Fdfile.pdb', 'source.cpp']
        self.assertEqual(check.preprocess_args(args, 'source.cpp'),
                         ['/DWIN32', '/UWIN32', '/DWIN32', '/FIforced.h', '/Iinclude',
                          '/std:c++17', '/fp:precise', '/O2', '/E', '/showIncludes', 'source.cpp'])

    def test_replay_preserves_separate_forced_include(self):
        self.assertEqual(check.preprocess_args(['/c', '/FI', 'forced.h', '/Fo', 'a.obj'], 'a.cpp'),
                         ['/FI', 'forced.h', '/E', '/showIncludes', 'a.cpp'])

    def test_replay_rejects_other_source(self):
        with self.assertRaises(ValueError):
            check.preprocess_args(['/c', 'other.cpp'], 'source.cpp')

    def test_tlog_requires_source_association(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'CL.command.1.tlog'
            path.write_bytes('^source.cpp\n/c /DWIN32 /I"a b"\n'.encode('utf-16'))
            self.assertEqual(check.tlog_commands(path), [(['source.cpp'], ['/c', '/DWIN32', '/Ia b'])])
            path.write_text('/c /DWIN32')
            with self.assertRaises(ValueError):
                check.tlog_commands(path)

    def test_allowlisted_environment_only(self):
        with patch.dict(os.environ, {'CL': '/DWIN32 /fp:precise', '_CL_': '/UWIN32'}, clear=True):
            self.assertEqual(check.compiler_environment()['CL'], ['/DWIN32', '/fp:precise'])
        with patch.dict(os.environ, {'CL': '@unrelated-sensitive-path'}, clear=True):
            with self.assertRaisesRegex(ValueError, '^CL contains an unrecognized compiler option$'):
                check.compiler_environment()

    def test_identity_captures_checkout_and_pr_not_only_event_sha(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'event.json'
            path.write_text(json.dumps({'pull_request': {'head': {'sha': 'a' * 40}, 'base': {'sha': 'b' * 40}}}))
            env = {'GITHUB_EVENT_PATH': str(path), 'GITHUB_RUN_ID': '7', 'GITHUB_RUN_ATTEMPT': '2',
                   'GITHUB_JOB': 'build', 'GITHUB_SHA': 'c' * 40}
            with patch.dict(os.environ, env, clear=True):
                result = check.identity()
            self.assertEqual(result['pr_head'], 'a' * 40)
            self.assertEqual(result['pr_base'], 'b' * 40)
            self.assertEqual(len(result['checkout']), 40)
            self.assertEqual(result['GITHUB_RUN_ATTEMPT'], '2')

    def test_missing_identity_fails(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            check.identity()

    def test_original_51_word_cases(self):
        cases = check.input_words()
        self.assertEqual(len(cases), 51)
        self.assertTrue(all(len(case) == 12 for case in cases))
        self.assertEqual(cases[27][0], 0x7fc00001)
        self.assertEqual(cases[50][11], 0x7fc00002)
        self.assertEqual(cases[15][0], 0x80000000)

    def test_strict_runtime_parser(self):
        valid = ('\n'.join(f'{i},0' for i in range(51)) + '\n').encode()
        self.assertEqual(check.rows(valid, 1), [[0]] * 51)
        for broken in (valid[:-5], valid.replace(b'0,0\n', b'1,0\n', 1),
                       valid.replace(b'0,0\n', b'0,4294967296\n', 1),
                       valid.replace(b'0,0\n', b'0,-1\n', 1), valid + b'extra\n'):
            with self.assertRaises(ValueError):
                check.rows(broken, 1)

    def test_runtime_timeout_and_failure_are_gaps(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            with self.assertRaises(ValueError):
                check.run([sys.executable, '-c', 'import time; time.sleep(3)'], out, 'timeout', timeout=0.1)
            with self.assertRaises(RuntimeError):
                check.run([sys.executable, '-c', 'raise SystemExit(9)'], out, 'failure')

    def test_bounded_output(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(check, 'LIMIT', 1024):
            with self.assertRaises(ValueError):
                check.run([sys.executable, '-c', 'print("x"*2048)'], Path(folder), 'oversized')

    def test_build_log_excludes_unrelated_values(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            check.run([sys.executable, '-c', 'print("UNRELATED=value"); print("cl.exe /c source.cpp")'], out, 'build', build=True)
            self.assertNotIn('UNRELATED', (out / 'build.stdout').read_text())
            self.assertIn('cl.exe /c source.cpp', (out / 'build.stdout').read_text())

    def test_link_proof_requires_each_exact_library_and_member(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            build, out = root / 'MikuDanceStudio-J', root / 'evidence'
            out.mkdir()
            tlog = build / 'MikuDanceStudio.dir/Release/link.command.1.tlog'
            tlog.parent.mkdir(parents=True)
            libs = {name: dict(package=str(root / (name + '.lib'))) for name in check.LIBS}
            command = ' '.join(entry['package'] for entry in libs.values())
            tlog.write_text('^app.obj\n' + command)
            (out / 'app-build.stdout').write_text('Loaded BulletCollision.lib(btDbvt.obj)\nLoaded BulletCollision.lib(btDbvtBroadphase.obj)\n')
            (out / 'app-build.stderr').write_text('')
            self.assertEqual(len(check.link_proof(build, 'app', out, libs)['libraries']), 4)
            (out / 'app-build.stdout').write_text('Loaded BulletCollision.lib(btDbvt.obj)\n')
            with self.assertRaises(ValueError):
                check.link_proof(build, 'app', out, libs)
            tlog.write_text('^app.obj\n' + command.replace(libs['LinearMath']['package'], 'other/LinearMath.lib'))
            with self.assertRaises(ValueError):
                check.link_proof(build, 'app', out, libs)

    def test_librarian_output_and_dbvt_members_are_required(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out = root / 'evidence'
            out.mkdir()
            libs = {}
            for name in check.LIBS:
                project = root / name
                tlog = project / (name + '.dir') / 'Lib.command.1.tlog'
                tlog.parent.mkdir(parents=True)
                library = project / 'Release' / (name + '.lib')
                libs[name] = dict(build=str(library))
                tlog.write_text('^inputs\n/OUT:' + str(library) + ' btDbvt.obj btDbvtBroadphase.obj')
            self.assertEqual(set(check.archive_commands(root, out, libs)), set(check.LIBS))
            tlog = root / 'BulletCollision/BulletCollision.dir/Lib.command.1.tlog'
            tlog.write_text(tlog.read_text().replace(' btDbvtBroadphase.obj', ''))
            with self.assertRaises(ValueError):
                check.archive_commands(root, out, libs)

    def test_policy_flags_preserve_override_order(self):
        self.assertEqual(check.policy_flags(['/D', 'WIN32', '/DUNRELATED', '/UWIN32', '/DWIN32', '/fp:precise', '/FI', 'forced.h']),
                         ['/DWIN32', '/UWIN32', '/DWIN32', '/fp:precise', '/FIforced.h'])
        self.assertNotEqual(check.policy_flags(['/DWIN32', '/UWIN32']), check.policy_flags(['/UWIN32', '/DWIN32']))

    def test_complete_numeric_mismatch_is_not_validation_gap(self):
        rust = [[1] + [0] * 12 for _ in range(51)]
        merged = [row[1:] for row in rust]
        intersected = [[row[0]] for row in rust]
        result = check.comparison_report(b'3,2,1,\n', rust, merged, intersected, b'3,2,1,\n', rust)
        self.assertEqual(result['compatibility'], 'PASS')
        changed = [row[:] for row in rust]
        changed[27][0] = 0
        result = check.comparison_report(b'2,3,1,\n', changed, merged, intersected, b'3,2,1,\n', rust)
        self.assertEqual(result['observation'], 'complete')
        self.assertEqual(result['compatibility'], 'FAIL')
        self.assertEqual(result['classification'], 'compatibility-mismatch')
        self.assertEqual(result['different_cases']['inline_aabb'], [27])
        self.assertFalse(result['comparisons']['select'])
        self.assertTrue(result['comparisons']['archive_merge'])

    def test_genuine_mismatch_remains_distinct_from_gap(self):
        # The receipt must stay incomplete if no actual archive observation exists.
        with tempfile.TemporaryDirectory() as folder, patch.object(check, 'source_manifest', return_value={}):
            out = Path(folder)
            check.save(out / 'source-start.json', {})
            self.assertEqual(check.measure(out), 1)
            report = json.loads((out / 'report.json').read_text())
            self.assertEqual(report['observation'], 'incomplete')
            self.assertEqual(report['compatibility'], 'not-evaluated')


if __name__ == '__main__':
    unittest.main()
