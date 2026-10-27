#!/usr/bin/env python3
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import contextlib
import io
import unittest
from unittest.mock import MagicMock, call, patch
from types import SimpleNamespace

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
        self.assertEqual(check.preprocess_args(['/c', '/FI', 'forced.h', '/Fo', 'a.obj', 'a.cpp'], 'a.cpp'),
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
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(check.subprocess, 'check_output', side_effect=[b'd' * 40, b'e' * 40]) as git:
                result = check.identity()
            self.assertEqual(git.call_args_list, [
                call(['git', 'rev-parse', 'HEAD'], cwd=check.ROOT),
                call(['git', 'show', '-s', '--format=%P', 'HEAD'], cwd=check.ROOT)])
            self.assertEqual(result['pr_head'], 'a' * 40)
            self.assertEqual(result['pr_base'], 'b' * 40)
            self.assertEqual(result['checkout'], 'd' * 40)
            self.assertEqual(result['parents'], ['e' * 40])
            self.assertEqual(result['GITHUB_RUN_ATTEMPT'], '2')

    def test_missing_identity_fails(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(check.subprocess, 'check_output', return_value=b'd' * 40) as git:
            with self.assertRaisesRegex(ValueError, '^missing Actions run identity$'):
                check.identity()
        git.assert_called_once_with(['git', 'rev-parse', 'HEAD'], cwd=check.ROOT)

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

    def link_fixture(self, root, label='app'):
        build, out = root / 'build with spaces', root / 'evidence'
        out.mkdir(exist_ok=True)
        target = 'dbvt_cmake_reference' if label == 'probe' else 'MikuDanceStudio'
        tlog = build / (target + '.dir/Release/link.command.1.tlog')
        tlog.parent.mkdir(parents=True)
        exe = build / ('Release/' + target + '.exe')
        exe.parent.mkdir(exist_ok=True)
        exe.write_bytes(b'actual target')
        libs = {}
        for name in check.LIBS:
            path = root / (name + '.lib')
            path.write_bytes(name.encode())
            libs[name] = dict(package=str(path), sha256=check.digest(path))
        map_path = build / (target + '.map')
        map_path.write_text(target + '\n 0001:00000000 symbol 140001000 f BulletCollision:btDbvt.obj\n'
                            ' 0001:00000001 symbol 140001001 f BulletCollision:btDbvtBroadphase.obj\n')
        args = ['/OUT:' + str(exe), '/MAP:' + str(map_path), *[entry['package'] for entry in libs.values()]]
        objects = []
        if label == 'probe':
            source = build / 'probe.cpp'
            source.write_text('probe source')
            obj = tlog.parent / 'probe.obj'
            obj.write_bytes(b'probe object')
            objects.append(str(obj))
            args.append(str(obj))
            (build / (target + '.vcxproj')).write_text('project')
            tlog.with_name('CL.command.1.tlog').write_text('^' + str(source) + '\n' + subprocess.list2cmdline(['/c', '/Fo' + str(obj), str(source)]))
        tlog.write_text('^app.obj\n' + subprocess.list2cmdline(args))
        tlog.with_name('link.read.1.tlog').write_text('^app.obj\n' + '\n'.join([*[entry['package'] for entry in libs.values()], *objects]))
        (out / (label + '-build.stdout')).write_text('Loaded C:/other-package/BulletCollision.lib(btDbvt.obj)\nLoaded C:/other-package/BulletCollision.lib(btDbvtBroadphase.obj)\n')
        (out / (label + '-build.stderr')).write_text('')
        return build, out, libs, tlog, map_path

    def test_link_proof_requires_exact_target_map_and_each_library(self):
        for label in ('app', 'probe'):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as folder:
                build, out, libs, tlog, map_path = self.link_fixture(Path(folder), label)
                self.assertEqual(len(check.link_proof(build, label, out, libs)['libraries']), 4)
                map_path.write_text(map_path.read_text().replace(':btDbvt.obj', ':unrelated.obj'))
                with self.assertRaisesRegex(ValueError, 'map lacks'):
                    check.link_proof(build, label, out, libs)

    def test_unrelated_test_or_other_archive_log_cannot_supply_member_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            build, out, libs, tlog, map_path = self.link_fixture(Path(folder))
            for bad in ('other_test\n', 'MikuDanceStudio\n C:/other-package/BulletCollision.lib(btDbvt.obj)\n'):
                map_path.write_text(bad)
                with self.assertRaises(ValueError):
                    check.link_proof(build, 'app', out, libs)

    def test_other_or_ambiguous_archive_reads_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            build, out, libs, tlog, map_path = self.link_fixture(Path(folder))
            readlog = tlog.with_name('link.read.1.tlog')
            original = readlog.read_text()
            for bad in (original.replace(libs['BulletCollision']['package'], 'C:/other-package/BulletCollision.lib'),
                        original + '\nC:/other-package/BulletCollision.lib', original.replace('^app.obj', '^test.obj')):
                readlog.write_text(bad)
                with self.assertRaises(ValueError):
                    check.link_proof(build, 'app', out, libs)

    def coff_archive(self, path, members):
        names, bodies = b'', []
        for name, body in members:
            index = len(names)
            names += name.encode() + b'\x00'
            bodies.append(('/' + str(index), body))
        data = b'!<arch>\n'
        for name, body in [('//', names), *bodies]:
            data += f'{name:<16}{0:<12}{0:<6}{0:<6}{0:<8}{len(body):<10}`\n'.encode() + body
            if len(body) % 2:
                data += b'\n'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def archive_fixture(self, root):
        out = root / 'evidence'
        out.mkdir()
        libs = {}
        for name in check.LIBS:
            project = root / name
            project.mkdir()
            (project / (name + '.vcxproj')).write_text('project')
            tlog = project / (name + '.dir/Release/Lib.command.1.tlog')
            tlog.parent.mkdir(parents=True)
            library = project / ('Release/' + name + '.lib')
            libs[name] = dict(build=str(library))
            objects = []
            for stem in ('btDbvt', 'btDbvtBroadphase') if name == 'BulletCollision' else ('other',):
                source = project / (stem + '.cpp')
                source.write_text('actual source')
                obj = tlog.parent / (stem + '.obj')
                obj.write_bytes(('object ' + stem).encode())
                objects.append(obj)
                with tlog.with_name('CL.command.1.tlog').open('a') as stream:
                    stream.write('^' + str(source) + '\n' + subprocess.list2cmdline(['/c', '/Fo' + str(obj), str(source)]) + '\n')
            self.coff_archive(library, [(str(obj.relative_to(project)), obj.read_bytes()) for obj in objects])
            tlog.write_text('^inputs\n' + subprocess.list2cmdline(['/OUT:' + str(library), *map(str, objects)]))
        return out, libs

    def test_librarian_binds_real_compiler_output_and_archive_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out, libs = self.archive_fixture(root)
            proof = check.archive_commands(root, out, libs)
            record = proof['BulletCollision']['dbvt_objects']['btDbvt']
            self.assertEqual(record['compile']['object_sha256'], record['member']['sha256'])
            self.assertEqual(check.digest(out / 'archives/btDbvt.obj'), record['member']['sha256'])
            Path(record['compile']['object']).unlink()
            with self.assertRaisesRegex(ValueError, 'compiler output is missing'):
                check.archive_commands(root, out, libs)

    def test_compile_source_operand_must_match_caret_full_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out, libs = self.archive_fixture(root)
            tlog = root / 'BulletCollision/BulletCollision.dir/Release/CL.command.1.tlog'
            original = tlog.read_text()
            source = root / 'BulletCollision/btDbvt.cpp'
            other = root / 'other/btDbvt.cpp'
            other.parent.mkdir()
            other.write_text('different actual source')
            lines = original.splitlines()
            for operands in ([str(other)], [str(source), str(other)], [str(source), str(source)], []):
                args = check.split_command(lines[1])
                args[-1:] = operands
                changed = lines[:]
                changed[1] = subprocess.list2cmdline(args)
                tlog.write_text('\n'.join(changed) + '\n')
                with self.subTest(operands=operands), self.assertRaises(ValueError):
                    check.archive_commands(root, out, libs)

    def test_explicit_cl_source_modes_fail_before_archive_or_replay(self):
        modes = [[flag + name] for flag in ('/Tc', '/Tp', '-Tc', '-Tp') for name in ('other.h', 'other')]
        modes += [[flag, name] for flag in ('/Tc', '/Tp', '-Tc', '-Tp') for name in ('other.h', 'other')]
        modes += [[flag, 'other.h'] for flag in ('/TC', '/TP', '-TC', '-TP')]
        modes += [[flag] for flag in ('/TC', '/TP', '-TC', '-TP')]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out, libs = self.archive_fixture(root)
            project = root / 'BulletCollision'
            tlog = project / 'BulletCollision.dir/Release/CL.command.1.tlog'
            original = tlog.read_text().splitlines()
            source = project / 'btDbvt.cpp'
            for mode in modes:
                with self.subTest(mode=mode):
                    args = check.split_command(original[1]) + mode
                    changed = original[:]
                    changed[1] = subprocess.list2cmdline(args)
                    tlog.write_text('\n'.join(changed) + '\n')
                    with self.assertRaisesRegex(ValueError, 'source mode'):
                        check.archive_commands(root, out, libs)
                    with self.assertRaisesRegex(ValueError, 'source mode'):
                        check.preprocess_args(args, source, cwd=project)
            # The explicit input has no extension and /Fo names a directory.
            changed = original[:]
            changed[1] = subprocess.list2cmdline(['/c', '/Fo' + str(tlog.parent) + '/', str(source), '/Tcother'])
            tlog.write_text('\n'.join(changed) + '\n')
            with self.assertRaisesRegex(ValueError, 'source mode'):
                check.archive_commands(root, out, libs)

    def test_capture_tu_requires_one_distinct_matching_cl_read_task(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            out, _ = self.archive_fixture(root)
            project = root / 'BulletCollision'
            source = project / 'btDbvt.cpp'
            header, other = project / 'btDbvt.h', project / 'other.h'
            header.write_text('header')
            other.write_text('other header')
            compiler = root / 'cl.exe'
            compiler.write_bytes(b'compiler')
            (project / 'CMakeCXXCompiler.cmake').write_text('set(CMAKE_CXX_COMPILER "' + str(compiler) + '")')
            (out / 'conan-create.stdout').write_text(str(compiler))
            (out / 'conan-create.stderr').write_text('')
            readlog = project / 'BulletCollision.dir/Release/CL.read.1.tlog'
            preprocess = '\n'.join('# 1 "' + str(path) + '"' for path in (header, other))

            def replay(*args, **kwargs):
                (out / 'btDbvt-preprocess.stdout').write_text(preprocess)
                (out / 'btDbvt-preprocess.stderr').write_text('')

            good = '^' + str(source) + '\n' + str(header) + '\n'
            with patch.object(check, 'run', side_effect=replay), \
                 patch.object(check, 'developer_environment', return_value={}), \
                 patch.object(check.consumer, 'classify', return_value=('profile', {})):
                readlog.write_text(good)
                self.assertEqual(check.capture_tu(root, 'btDbvt', out), 'profile')
                for bad in (good + '^' + str(source) + '\n' + str(other) + '\n',
                            good + good, '^' + str(other) + '\n' + str(header),
                            good.replace(str(source), str(source) + '|' + str(other))):
                    with self.subTest(readlog=bad):
                        readlog.write_text(bad)
                        with self.assertRaisesRegex(ValueError, 'read task'):
                            check.capture_tu(root, 'btDbvt', out)

    def test_expanded_relative_source_is_preserved_and_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out, libs = self.archive_fixture(root)
            project = root / 'BulletCollision'
            tlog = project / 'BulletCollision.dir/Release/CL.command.1.tlog'
            lines = tlog.read_text().splitlines()
            args = check.split_command(lines[1])
            args[-1] = 'btDbvt.cpp'
            response = project / 'compile.rsp'
            response.write_text(subprocess.list2cmdline(args))
            lines[1] = '@compile.rsp'
            tlog.write_text('\n'.join(lines) + '\n')
            record = check.archive_commands(root, out, libs)['BulletCollision']['dbvt_objects']['btDbvt']['compile']
            self.assertEqual(record['argv'][-1], 'btDbvt.cpp')
            self.assertEqual(check.preprocess_args(record['argv'], record['source'], cwd=record['cwd'])[-1], 'btDbvt.cpp')
            other = root / 'other/btDbvt.cpp'
            other.parent.mkdir()
            other.write_text('other source')
            args[-1] = str(other)
            response.write_text(subprocess.list2cmdline(args))
            with self.assertRaisesRegex(ValueError, 'caret full path'):
                check.archive_commands(root, out, libs)
            args[-1] = 'btDbvt.cpp'
            response.write_text(subprocess.list2cmdline(args))
            lines[0] += '|' + str(other)
            tlog.write_text('\n'.join(lines) + '\n')
            with self.assertRaisesRegex(ValueError, 'caret must identify exactly one source'):
                check.archive_commands(root, out, libs)

    def test_repeated_caret_read_tasks_cannot_pool_library_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            build, out, libs, tlog, _ = self.link_fixture(Path(folder))
            readlog = tlog.with_name('link.read.1.tlog')
            lines = readlog.read_text().splitlines()
            readlog.write_text('\n'.join([*lines[:3], lines[0], *lines[3:]]) + '\n')
            with self.assertRaises(ValueError):
                check.link_proof(build, 'app', out, libs)

    def test_unrelated_same_basename_or_missing_lib_input_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out, libs = self.archive_fixture(root)
            tlog = root / 'BulletCollision/BulletCollision.dir/Release/Lib.command.1.tlog'
            original = tlog.read_text()
            bad = root / 'unrelated/btDbvt.obj'
            for exists in (False, True):
                if exists:
                    bad.parent.mkdir()
                    bad.write_bytes(b'object btDbvt')
                tlog.write_text(original.replace(str(root / 'BulletCollision/BulletCollision.dir/Release/btDbvt.obj'), str(bad)))
                with self.assertRaises(ValueError):
                    check.archive_commands(root, out, libs)

    def test_archive_member_wrong_bytes_path_or_ambiguity_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out, libs = self.archive_fixture(root)
            path = Path(libs['BulletCollision']['build'])
            a, b = 'BulletCollision.dir/Release/btDbvt.obj', 'BulletCollision.dir/Release/btDbvtBroadphase.obj'
            for members in ([(a, b'wrong'), (b, b'object btDbvtBroadphase')],
                            [('other/btDbvt.obj', b'object btDbvt'), (b, b'object btDbvtBroadphase')],
                            [(a, b'object btDbvt'), (a, b'object btDbvt'), (b, b'object btDbvtBroadphase')]):
                self.coff_archive(path, members)
                with self.assertRaises(ValueError):
                    check.archive_commands(root, out, libs)

    def test_nonreading_child_with_large_stdin_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            start = time.monotonic()
            with self.assertRaisesRegex(ValueError, 'time bound'):
                check.run([sys.executable, '-c', 'import time; time.sleep(10)'], Path(folder), 'nonreader',
                          data=b'x' * 1048576, timeout=0.1)
            self.assertLess(time.monotonic() - start, 2)

    def test_owned_descendant_cannot_outlive_successful_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            marker = out / 'leftover'
            child = 'import pathlib,time;time.sleep(.4);pathlib.Path(' + repr(str(marker)) + ').write_text("leftover")'
            parent = 'import subprocess,sys;subprocess.Popen([sys.executable,"-c",' + repr(child) + '])'
            check.run([sys.executable, '-c', parent], out, 'descendant', timeout=2)
            time.sleep(.5)
            self.assertFalse(marker.exists())

    def test_windows_launch_is_suspended_until_job_assignment_and_cleans_failures(self):
        for failure in (None, 'job', 'resume', 'close'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                events = []
                process = MagicMock(returncode=0)
                process.poll.return_value = 0

                def event(name):
                    events.append(name)
                    if failure == name:
                        raise OSError(name)

                def launch(*args, **kwargs):
                    self.assertEqual(kwargs['creationflags'], 0x4)
                    self.assertFalse(kwargs['start_new_session'])
                    self.assertEqual(kwargs['stdin'].read(), b'bounded input')
                    event('create')
                    return process

                def job(child):
                    self.assertIs(child, process)
                    event('job')
                    return lambda: event('close')

                with patch.object(check, 'os', SimpleNamespace(name='nt', fstat=os.fstat)), \
                     patch.object(check.subprocess, 'Popen', side_effect=launch), \
                     patch.object(check, 'windows_job', side_effect=job), \
                     patch.object(check, 'windows_resume', side_effect=lambda child: event('resume')), \
                     patch.object(check, 'stop', side_effect=lambda child: event('stop')):
                    if failure:
                        with self.assertRaisesRegex(OSError, failure):
                            check.run(['child'], Path(folder), 'order', data=b'bounded input')
                    else:
                        check.run(['child'], Path(folder), 'order', data=b'bounded input')
                expected = ['create', 'job']
                if failure != 'job':
                    expected += ['resume', 'close']
                self.assertEqual(events, [*expected, 'stop'])
                process._handle.Close.assert_called_once_with()

    def test_windows_job_api_owns_process_and_closes_failed_job(self):
        import ctypes
        for failure in (None, 'create', 'limits', 'assign'):
            with self.subTest(failure=failure):
                kernel = MagicMock()
                kernel.CreateJobObjectW.return_value = 0 if failure == 'create' else 201

                def limits(job, kind, pointer, size):
                    self.assertEqual(pointer._obj.basic.flags, 0x2000)
                    self.assertEqual(kind, 9)
                    return failure != 'limits'

                kernel.SetInformationJobObject.side_effect = limits
                kernel.AssignProcessToJobObject.return_value = failure != 'assign'
                with patch.object(ctypes, 'WinDLL', return_value=kernel, create=True), \
                     patch.object(ctypes, 'get_last_error', return_value=5, create=True), \
                     patch.object(ctypes, 'WinError', side_effect=lambda code: OSError(code, 'Windows API failure'), create=True):
                    if failure:
                        with self.assertRaises(OSError):
                            check.windows_job(SimpleNamespace(_handle=301))
                    else:
                        close = check.windows_job(SimpleNamespace(_handle=301))
                        kernel.CloseHandle.assert_not_called()
                        kernel.AssignProcessToJobObject.assert_called_once_with(201, 301)
                        close()
                self.assertEqual(kernel.CloseHandle.call_count, 0 if failure == 'create' else 1)

    def test_windows_stop_kills_unassigned_suspended_child_directly(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch.object(check, 'os', SimpleNamespace(name='nt')):
            check.stop(process)
        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=5)

    def test_windows_resume_api_and_handle_cleanup(self):
        import ctypes
        for failure in (None, 'snapshot', 'first', 'next', 'open', 'resume', 'count'):
            with self.subTest(failure=failure):
                kernel = MagicMock()
                kernel.CreateToolhelp32Snapshot.return_value = ctypes.c_void_p(-1).value if failure == 'snapshot' else 101

                def first(snapshot, pointer):
                    pointer._obj.owner = 42
                    pointer._obj.thread = 43
                    return failure != 'first'

                kernel.Thread32First.side_effect = first
                kernel.Thread32Next.return_value = 0
                kernel.OpenThread.return_value = 0 if failure == 'open' else 102
                kernel.ResumeThread.return_value = 0xffffffff if failure == 'resume' else 2 if failure == 'count' else 1
                with patch.object(ctypes, 'WinDLL', return_value=kernel, create=True), \
                     patch.object(ctypes, 'get_last_error', return_value=5 if failure == 'next' else 18, create=True), \
                     patch.object(ctypes, 'WinError', side_effect=lambda code: OSError(code, 'Windows API failure'), create=True):
                    if failure:
                        with self.assertRaises((OSError, ValueError)):
                            check.windows_resume(SimpleNamespace(pid=42))
                    else:
                        check.windows_resume(SimpleNamespace(pid=42))
                handles = [call.args[0] for call in kernel.CloseHandle.call_args_list]
                self.assertEqual(handles, [] if failure == 'snapshot' else [101] if failure in ('first', 'next', 'open') else [101, 102])
                if failure not in ('snapshot', 'first', 'next', 'open'):
                    kernel.OpenThread.assert_called_once_with(0x2, False, 43)
                    kernel.ResumeThread.assert_called_once_with(102)

    def close_windows_descendant(self, kernel, handle):
        import ctypes
        try:
            status = kernel.WaitForSingleObject(handle, 0)
            error = ctypes.get_last_error() if status == 0xffffffff else None
            self.assertIn(status, (0, 258), f'control descendant initial wait failed: result={status}, error={error}')
            terminate_error = None
            if status == 258:
                if not kernel.TerminateProcess(handle, 1):
                    terminate_error = ctypes.get_last_error()
            status = kernel.WaitForSingleObject(handle, 5000)
            wait_error = ctypes.get_last_error() if status == 0xffffffff else None
            self.assertEqual(status, 0, f'control descendant cleanup failed: result={status}, '
                                       f'TerminateProcess error={terminate_error}, wait error={wait_error}')
        finally:
            kernel.CloseHandle(handle)

    def test_windows_control_cleanup_terminates_surviving_handles(self):
        kernel = MagicMock()
        kernel.WaitForSingleObject.side_effect = [258, 0]
        self.close_windows_descendant(kernel, 102)
        kernel.TerminateProcess.assert_called_once_with(102, 1)
        self.assertEqual(kernel.WaitForSingleObject.call_args_list[-1].args, (102, 5000))
        kernel.CloseHandle.assert_called_once_with(102)

    def test_windows_control_cleanup_accepts_concurrent_job_termination(self):
        import ctypes
        kernel = MagicMock()
        kernel.WaitForSingleObject.side_effect = [258, 0]
        kernel.TerminateProcess.return_value = 0
        with patch.object(ctypes, 'get_last_error', return_value=123, create=True) as error:
            self.close_windows_descendant(kernel, 102)
        error.assert_called_once_with()
        self.assertEqual(kernel.WaitForSingleObject.call_args_list, [call(102, 0), call(102, 5000)])
        kernel.CloseHandle.assert_called_once_with(102)

    def test_windows_control_cleanup_waits_and_closes_on_failure(self):
        import ctypes
        for terminated, result in ((True, 258), (False, 258), (True, 0xffffffff), (False, 0xffffffff)):
            with self.subTest(terminated=terminated, result=result):
                kernel = MagicMock()
                kernel.TerminateProcess.return_value = terminated
                kernel.WaitForSingleObject.side_effect = [258, result]
                with patch.object(ctypes, 'get_last_error', side_effect=[123, 456], create=True), \
                     self.assertRaisesRegex(AssertionError, 'control descendant cleanup failed') as failure:
                    self.close_windows_descendant(kernel, 102)
                if not terminated:
                    self.assertIn('TerminateProcess error=123', str(failure.exception))
                if result == 0xffffffff:
                    self.assertIn('wait error=' + str(456 if not terminated else 123), str(failure.exception))
                kernel.TerminateProcess.assert_called_once_with(102, 1)
                kernel.CloseHandle.assert_called_once_with(102)
                self.assertEqual(kernel.WaitForSingleObject.call_args_list[-1].args, (102, 5000))

    def test_windows_control_cleanup_rejects_initial_wait_failure(self):
        import ctypes
        kernel = MagicMock()
        kernel.WaitForSingleObject.return_value = 0xffffffff
        with patch.object(ctypes, 'get_last_error', return_value=123, create=True), \
             self.assertRaisesRegex(AssertionError, 'control descendant initial wait failed.*error=123'):
            self.close_windows_descendant(kernel, 102)
        kernel.TerminateProcess.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(102)

    def windows_race_control(self, failure=None):
        import ctypes
        from ctypes import wintypes
        with tempfile.TemporaryDirectory() as folder, contextlib.ExitStack() as containment:
            out = Path(folder)
            started, ready, release, pidfile, leftover = [out / name for name in ('started', 'ready', 'release', 'pid', 'leftover')]
            child = ('import pathlib,time\npathlib.Path(' + repr(str(ready)) + ').touch()\ntime.sleep(.7)\n'
                     'while True:\n pathlib.Path(' + repr(str(leftover)) + ').touch()\n time.sleep(.05)\n')
            parent = ('import pathlib,subprocess,sys,time\n'
                      'pathlib.Path(' + repr(str(started)) + ').touch()\n'
                      'child=subprocess.Popen([sys.executable,"-c",' + repr(child) + '])\n'
                      'pathlib.Path(' + repr(str(pidfile)) + ').write_text(str(child.pid))\n'
                      'while not pathlib.Path(' + repr(str(ready)) + ').exists(): time.sleep(.01)\n'
                      'while not pathlib.Path(' + repr(str(release)) + ').exists(): time.sleep(.01)\n')
            original_job, original_resume = check.windows_job, check.windows_resume
            handles = []
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]

            def outer_job(process):
                containment.callback(original_job(process))

            def wait_ready(label):
                deadline = time.monotonic() + 5
                while not (ready.exists() and pidfile.exists()) and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(ready.exists() and pidfile.exists() and failure != label + '-ready',
                                label + ' readiness timeout')

            def retain_descendant():
                handle = kernel.OpenProcess(0x100001, False, int(pidfile.read_text()))
                self.assertTrue(handle, 'could not retain terminate-capable descendant handle')
                handles.append(handle)
                return handle

            try:
                baseline = subprocess.Popen([sys.executable, '-c', parent], stdin=subprocess.DEVNULL,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x4)
                close_baseline_job = None
                try:
                    outer_job(baseline)
                    original_resume(baseline)
                    wait_ready('baseline')
                    baseline_handle = retain_descendant()
                    close_baseline_job = original_job(baseline)
                    release.touch()
                    self.assertEqual(baseline.wait(timeout=5), 0)
                    close_baseline_job()
                    close_baseline_job = None
                    self.assertEqual(kernel.WaitForSingleObject(baseline_handle, 0), 258,
                                     'old schedule did not reproduce the escaped descendant')
                finally:
                    try:
                        if close_baseline_job:
                            close_baseline_job()
                    finally:
                        try:
                            check.stop(baseline)
                        finally:
                            baseline._handle.Close()
                self.close_windows_descendant(kernel, handles.pop())
                for marker in (started, ready, release, pidfile, leftover):
                    marker.unlink(missing_ok=True)

                def delayed_job(process):
                    outer_job(process)
                    time.sleep(.3)
                    self.assertFalse(started.exists(), 'child executed before job assignment')
                    self.assertFalse(pidfile.exists(), 'child spawned a descendant before job assignment')
                    close_inner = original_job(process)
                    if failure == 'survivor':
                        containment.callback(close_inner)
                        return lambda: None
                    return close_inner

                def resume(process):
                    original_resume(process)
                    wait_ready('corrected')
                    handle = retain_descendant()
                    self.assertEqual(kernel.WaitForSingleObject(handle, 0), 258, 'descendant was not running')
                    release.touch()
                    self.assertEqual(process.wait(timeout=5), 0, 'parent did not exit before job close')

                with patch.object(check, 'windows_job', side_effect=delayed_job), patch.object(check, 'windows_resume', side_effect=resume):
                    check.run([sys.executable, '-c', parent], out, 'windows-race', timeout=15)
                self.assertEqual(len(handles), 1)
                self.assertEqual(kernel.WaitForSingleObject(handles[0], 0 if failure == 'survivor' else 5000), 0,
                                 'orphan survived job close')
            finally:
                try:
                    # Outer jobs own descendants even before their PID or handle is available.
                    containment.close()
                finally:
                    try:
                        for handle in handles:
                            self.close_windows_descendant(kernel, handle)
                    finally:
                        leftover.unlink(missing_ok=True)
                        time.sleep(.8)
                        self.assertFalse(leftover.exists(), 'control descendant ran after failure cleanup')

    @unittest.skipUnless(os.name == 'nt', 'requires actual Windows Job Object and suspended thread APIs')
    def test_windows_delayed_assignment_prevents_escape_and_kills_orphan(self):
        self.windows_race_control()

    @unittest.skipUnless(os.name == 'nt', 'requires actual Windows Job Object and suspended thread APIs')
    def test_windows_race_control_contains_injected_failures(self):
        for failure, message in (('baseline-ready', 'baseline readiness timeout'),
                                 ('corrected-ready', 'corrected readiness timeout'),
                                 ('survivor', 'orphan survived job close')):
            with self.subTest(failure=failure), self.assertRaisesRegex(AssertionError, message):
                self.windows_race_control(failure)

    def test_probe_object_cannot_be_supplied_by_another_link_input(self):
        with tempfile.TemporaryDirectory() as folder:
            build, out, libs, tlog, map_path = self.link_fixture(Path(folder), 'probe')
            obj = tlog.parent / 'probe.obj'
            other = build / 'other/probe.obj'
            other.parent.mkdir()
            other.write_bytes(obj.read_bytes())
            tlog.write_text(tlog.read_text().replace(str(obj), str(other)))
            with self.assertRaisesRegex(ValueError, 'exact linker input'):
                check.link_proof(build, 'probe', out, libs)

    def test_build_diagnostics_are_retained_and_forwarded(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            text = 'source.cpp(1): error C2143: syntax error\nLINK : fatal error LNK1104: cannot open file\nCMake Error at CMakeLists.txt:7 (find_package):\n  Could not locate requested package Bullet275\n  TOKEN=secret\nERROR: Conan build failed\nUNRELATED=secret'
            console = io.StringIO()
            with contextlib.redirect_stdout(console), self.assertRaises(RuntimeError) as error:
                check.run([sys.executable, '-c', 'print(' + repr(text) + ');raise SystemExit(1)'], out, 'diagnostics', build=True)
            for marker in ('C2143', 'LNK1104', 'CMake Error', 'Could not locate', 'ERROR: Conan'):
                self.assertIn(marker, (out / 'diagnostics.stdout').read_text())
                self.assertIn(marker, console.getvalue())
            self.assertNotIn('UNRELATED', console.getvalue())
            self.assertNotIn('TOKEN', console.getvalue())
            self.assertIn(str(out / 'diagnostics.stdout'), str(error.exception))
            self.assertTrue((out / 'diagnostics.stderr').is_file())

    def test_archive_merge_compares_insertion_order_without_masking_bits(self):
        rust = [[1, 0x80000000, 0, 0, 0x7fc00001, 0, 0, 0, 0, 0, 0x7fc00002, 0, 0] for _ in range(51)]
        merged = [row[7:13] + row[1:7] for row in rust]
        result = check.comparison_report(b'3,2,1,\n', rust, merged, [[1]] * 51, b'3,2,1,\n', rust)
        self.assertTrue(result['comparisons']['archive_merge'])
        merged[15][0] ^= 0x80000000
        merged[27][3] ^= 1
        result = check.comparison_report(b'3,2,1,\n', rust, merged, [[1]] * 51, b'3,2,1,\n', rust)
        self.assertEqual(result['different_cases']['archive_merge'], [15, 27])

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
