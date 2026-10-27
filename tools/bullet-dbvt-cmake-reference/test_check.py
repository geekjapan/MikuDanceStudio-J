#!/usr/bin/env python3
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import venv
import contextlib
import io
import unittest
from unittest.mock import MagicMock, call, patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('cmake_reference', Path(__file__).with_name('check.py'))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class ClassificationTests(unittest.TestCase):
    def profile(self, select='return(Proximity(o,a)<Proximity(o,b)?0:1);'):
        return '''bool Intersect(const A& a,const A& b) { return(a.mi.x()<=b.mx.x()); }
int Select(const A& o,const A& a,const A& b) { %s }
void Merge(const A& a,const A& b,A& r) { if(a.mi[i]<b.mi[i]) r=a; }
struct ICollide { virtual void Process();
};
static btDbvtVolume merge(const A& a,const A& b) { char locals[sizeof(btDbvtAabbMm)]; btDbvtVolume& res=*(btDbvtVolume*)locals; return res; }
static btDbvtVolume bounds(const Array& a) { char locals[sizeof(btDbvtVolume)]; btDbvtVolume& volume=*(btDbvtVolume*)locals; return volume; }
''' % select

    def test_inline_generic_with_post_undef_aligned_cpp(self):
        profile, extracts = check.classify(self.profile(), cpp=True)
        self.assertEqual(profile, dict(Intersect='generic', Select='generic', Merge='generic', policy='virtual', merge_local='aligned', bounds_local='aligned'))
        self.assertIn('locals[', extracts['merge'])

    def test_sse_is_observed_without_os_assumptions(self):
        profile, _ = check.classify(self.profile('return _mm_cmple_ss(a,b);'))
        self.assertEqual(profile['Select'], 'sse')

    def test_unknown_and_ambiguous_fail_closed(self):
        for body in ('return 0;', 'return _mm_cmple_ss(a,b) + (Proximity(o,a)<Proximity(o,b)?0:1);'):
            with self.assertRaises(ValueError):
                check.classify(self.profile(body))

    def test_missing_policy_and_truncated_body_fail_closed(self):
        with self.assertRaises(ValueError):
            check.classify(self.profile().replace('struct ICollide', 'struct Unknown'))
        with self.assertRaises(ValueError):
            check.function('void Merge(A a) { if(a) {', 'Merge')

    def test_select_transport_must_be_a_complete_permutation(self):
        for data in (b'2,3,1,\n', b'3,2,1,\r\n'):
            check.validate_select(data)
        for data in (b'', b'2,3,1,', b'2,3,1,\nextra', b'1,1,2,\n', b'1,2,128,\n', b'bad\n'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                check.validate_select(data)


class Controls(unittest.TestCase):
    def developer_fixture(self, root, *, unicode_paths=True):
        vs = root / ('Visual Studio 日本 spaces' if unicode_paths else 'Visual Studio spaces')
        batch = vs / 'Common7/Tools/VsDevCmd.bat'
        batch.parent.mkdir(parents=True)
        compiler = vs / 'VC/Tools/MSVC/bin/Hostx64/x64/cl.exe'
        compiler.parent.mkdir(parents=True)
        compiler.write_bytes(b'fake compiler')
        out = root / 'evidence 日本 spaces'
        out.mkdir()
        (out / 'msbuild-version.stdout').write_bytes(b'fake version, not executed')
        return batch, compiler, out

    def test_developer_environment_mock_validates_fields_and_raw_transport(self):
        with tempfile.TemporaryDirectory() as folder:
            batch, compiler, out = self.developer_fixture(Path(folder))
            batch.write_text('@exit /b 0\n')
            valid = dict(INCLUDE='include path', LIB='lib path', LIBPATH='libpath', PATH='path')
            for environment in (valid, {}, None, dict(valid, INCLUDE=''), dict(valid, LIB=7),
                                dict(valid, LIBPATH='  '), dict(valid, PATH=None)):
                with self.subTest(environment=environment), patch.object(check, 'run',
                        return_value=b'setup diagnostics\n' + json.dumps(environment).encode() + b'\n') as run:
                    if environment == valid:
                        self.assertEqual(check.developer_environment(compiler, out, 'mock')['INCLUDE'], 'include path')
                        command = run.call_args.args[0]
                        self.assertIsInstance(command, str)
                        self.assertTrue(command.startswith('cmd.exe /d /v:off /s /c "call "'))
                        self.assertNotIn('\\"', command)
                        self.assertEqual(run.call_args.kwargs, dict(cwd=out, timeout=30))
                    else:
                        with self.assertRaisesRegex(ValueError, 'environment fields'):
                            check.developer_environment(compiler, out, 'mock')

    def test_developer_environment_mock_rejects_shell_path_expansion(self):
        with tempfile.TemporaryDirectory() as folder:
            batch, compiler, out = self.developer_fixture(Path(folder))
            batch.write_text('@exit /b 0\n')
            for python in ('percent%python.exe', 'caret^python.exe', 'quote"python.exe', 'line\npython.exe'):
                with self.subTest(python=python), patch.object(check.sys, 'executable', python), \
                        patch.object(check, 'run') as run, self.assertRaisesRegex(ValueError, 'metacharacter'):
                    check.developer_environment(compiler, out, 'mock')
                run.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'actual Windows cmd transport requires Windows')
    def test_windows_developer_environment_old_red_new_green(self):
        with tempfile.TemporaryDirectory(prefix='dbvt cmd spaces ') as folder:
            root = Path(folder)
            batch, compiler, out = self.developer_fixture(root)
            python_root = root / 'Python 日本 spaces'
            venv.EnvBuilder(with_pip=False).create(python_root)
            python = str(python_root / 'Scripts/python.exe')
            batch.write_text('@echo off\necho setup stdout\necho setup stderr 1>&2\n'
                             'set "INCLUDE=include path"\nset "LIB=lib path"\nset "LIBPATH=libpath"\nexit /b 0\n')
            with patch.object(check.sys, 'executable', python):
                environment = check.developer_environment(compiler, out, 'transport')
                self.assertEqual(environment['INCLUDE'], 'include path')
                script = out / 'compiler-environment.py'
                legacy = 'call "' + str(batch) + '" -no_logo -arch=x64 -host_arch=x64 >nul && "' + python + '" "' + str(script) + '"'
                with self.assertRaisesRegex(RuntimeError, 'exited'):
                    check.run(['cmd.exe', '/d', '/s', '/c', legacy], out, 'legacy', cwd=out, timeout=30)
            self.assertNotEqual(json.loads((out / 'legacy-result.json').read_text())['returncode'], 0)
            self.assertEqual(json.loads((out / 'transport-developer-environment-result.json').read_text())['returncode'], 0)
            self.assertIn(b'setup stdout', (out / 'transport-developer-environment.stdout').read_bytes())
            self.assertIn(b'setup stderr', (out / 'transport-developer-environment.stderr').read_bytes())
            self.assertEqual(json.loads((out / 'transport-replay-include-paths.json').read_text()), ['include path'])

    @unittest.skipUnless(os.name == 'nt', 'actual Windows cmd failure requires Windows')
    def test_windows_developer_environment_failure_blocks_preprocessing(self):
        with tempfile.TemporaryDirectory(prefix='dbvt cmd spaces ') as folder:
            root = Path(folder)
            batch, compiler, out = self.developer_fixture(root, unicode_paths=False)
            batch.write_text('@echo off\necho setup failed stdout\necho setup failed stderr 1>&2\nexit /b 7\n')
            source = root / 'btDbvt.cpp'
            source.write_text('source')
            (root / 'CMakeCXXCompiler.cmake').write_text('set(CMAKE_CXX_COMPILER "' + str(compiler) + '")')
            (out / 'conan-create.stdout').write_text(str(compiler))
            (out / 'conan-create.stderr').write_text('')
            record = dict(tlog=str(root / 'CL.command.1.tlog'), source=str(source), cwd=str(root),
                          argv=['/c', '/Fofoo.obj', str(source)])
            with patch.object(check, 'compile_record', return_value=record), \
                    self.assertRaisesRegex(RuntimeError, 'exited 7'):
                check.capture_tu(root, 'btDbvt', out)
            self.assertFalse((out / 'btDbvt-preprocess-command.json').exists())
            self.assertFalse((out / 'btDbvt-replay-include-paths.json').exists())
            self.assertIn(b'setup failed stdout', (out / 'btDbvt-developer-environment.stdout').read_bytes())
            self.assertIn(b'setup failed stderr', (out / 'btDbvt-developer-environment.stderr').read_bytes())
            receipt = json.loads((out / 'btDbvt-developer-environment-result.json').read_text())
            self.assertEqual(receipt, dict(returncode=7, failure=None))

    @unittest.skipUnless(os.name == 'nt', 'actual Windows cmd timeout requires Windows')
    def test_windows_developer_environment_timeout_retains_partial_outputs(self):
        with tempfile.TemporaryDirectory(prefix='dbvt cmd spaces ') as folder:
            batch, compiler, out = self.developer_fixture(Path(folder))
            batch.write_text('@echo off\necho partial stdout\necho partial stderr 1>&2\n'
                             '"' + sys.executable + '" -c "import time; time.sleep(5)"\n')
            original = check.run

            def timed(command, output, name, **kwargs):
                return original(command, output, name, cwd=kwargs['cwd'], timeout=0.5)

            with patch.object(check, 'run', side_effect=timed), self.assertRaisesRegex(ValueError, 'time bound'):
                check.developer_environment(compiler, out, 'windows-timeout')
            prefix = out / 'windows-timeout-developer-environment'
            self.assertIn(b'partial stdout', prefix.with_suffix('.stdout').read_bytes())
            self.assertIn(b'partial stderr', prefix.with_suffix('.stderr').read_bytes())
            self.assertEqual(json.loads((out / (prefix.name + '-result.json')).read_text())['failure'], 'time')
            self.assertFalse((out / 'windows-timeout-replay-include-paths.json').exists())

    def test_developer_environment_timeout_retains_partial_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            batch, compiler, out = self.developer_fixture(Path(folder))
            batch.write_text('@exit /b 0\n')
            original = check.run

            def timed(command, output, name, **kwargs):
                # Portable process control proves retention, not Windows command transport.
                return original([sys.executable, '-c',
                                 'import sys,time; print("partial stdout",flush=True); '
                                 'print("partial stderr",file=sys.stderr,flush=True); time.sleep(5)'],
                                output, name, cwd=kwargs['cwd'], timeout=0.5)

            with patch.object(check, 'run', side_effect=timed), self.assertRaisesRegex(ValueError, 'time bound'):
                check.developer_environment(compiler, out, 'timeout')
            self.assertIn(b'partial stdout', (out / 'timeout-developer-environment.stdout').read_bytes())
            self.assertIn(b'partial stderr', (out / 'timeout-developer-environment.stderr').read_bytes())
            self.assertEqual(json.loads((out / 'timeout-developer-environment-result.json').read_text())['failure'], 'time')
            self.assertFalse((out / 'timeout-replay-include-paths.json').exists())

    def test_record_build_production_argv_reaches_run_unchanged(self):
        command = ['cmake', '--build', 'out/ci/build', '--config', 'Release',
                   '--parallel', '4', '--', '/verbosity:normal', '/clp:ShowCommandLine']
        with tempfile.TemporaryDirectory() as folder, contextlib.chdir(folder):
            argv = ['check.py', 'record-build', '--out-dir', 'out/ci/dbvt-reference', '--build-command', *command]
            with patch.object(sys, 'argv', argv), patch.object(check, 'run') as run:
                self.assertEqual(check.main(), 0)
            run.assert_called_once_with(command, Path('out/ci/dbvt-reference').resolve(), 'app-build', build=True, timeout=900)

    def test_only_first_exact_build_command_is_wrapper_boundary(self):
        command = ['cmake', '--build-command', '--out-dir', '--unknown', '--']
        with tempfile.TemporaryDirectory() as folder:
            argv = ['check.py', 'record-build', '--out-dir', folder, '--build-command', *command]
            with patch.object(sys, 'argv', argv), patch.object(check, 'run') as run:
                self.assertEqual(check.main(), 0)
            run.assert_called_once_with(command, Path(folder).resolve(), 'app-build', build=True, timeout=900)

    def test_record_build_requires_command(self):
        with tempfile.TemporaryDirectory() as folder:
            for suffix in ([], ['--build-command']):
                with self.subTest(suffix=suffix), patch.object(sys, 'argv',
                        ['check.py', 'record-build', '--out-dir', folder, *suffix]), \
                        patch.object(check, 'run') as run, self.assertRaisesRegex(ValueError, 'missing build command'):
                    check.main()
                run.assert_not_called()

    def test_cli_prefix_is_strict(self):
        with tempfile.TemporaryDirectory() as folder:
            for option in ('--unknown', '--build-comman'):
                argv = ['check.py', 'record-build', '--out-dir', folder, option,
                        '--build-command', 'cmake', '--', '/verbosity:normal']
                with self.subTest(option=option), patch.object(sys, 'argv', argv), \
                        patch.object(check, 'run') as run, contextlib.redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit) as error:
                    check.main()
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()

    def test_prepare_and_measure_cli_parsing(self):
        with tempfile.TemporaryDirectory() as folder:
            for mode, result in (('prepare', 0), ('measure', 1)):
                with self.subTest(mode=mode), patch.object(sys, 'argv',
                        ['check.py', mode, '--out-dir', folder]), \
                        patch.object(check, mode, return_value=result) as action:
                    self.assertEqual(check.main(), result)
                action.assert_called_once_with(Path(folder).resolve())

    def conan_paths(self, paths):
        original = check.run
        answers = iter(paths)
        return patch.object(check, 'run', side_effect=lambda argv, *args, **kwargs:
                            next(answers) if argv[0] == 'conan' else original(argv, *args, **kwargs))

    def package_cache_fixture(self, root, text):
        package, build, source = (root / name for name in ('package', 'cache-build', 'cache-source'))
        for folder in (package, build / 'build', source, build / 'bullet-src'):
            folder.mkdir(parents=True, exist_ok=True)
        cache = build / 'build/CMakeCache.txt'
        cache.write_bytes(text.replace('SOURCE', str(build / 'bullet-src')).encode())
        graph = {'graph': {'nodes': {'1': dict(ref='bullet275/2.75#recipe', context='host',
                 package_id='package', prev='revision', package_folder=str(package))}}}
        return graph, cache, [str(path).encode() for path in (package, build, source)]

    def test_package_cache_commented_lf_and_crlf(self):
        text = ('# This is the CMakeCache file.\n\n//Name of generator.\n'
                'CMAKE_GENERATOR:INTERNAL=Visual Studio 17 2022\n\n//Platform.\n'
                'CMAKE_GENERATOR_PLATFORM:INTERNAL=x64\n\n//Source directory.\n'
                'CMAKE_HOME_DIRECTORY:INTERNAL=SOURCE\n\n//Ordinary entries.\n'
                'BUILD_SHARED_LIBS:BOOL=OFF\nCMAKE_CONFIGURATION_TYPES:STRING=Debug;Release\n'
                'CMAKE_CXX_FLAGS:STRING=\nUnrelated:STRING=first\nUnrelated:STRING=last\n'
                'CMAKE_GENERATOR_EXTRA:=ignored\n//CMAKE_GENERATOR:=Ninja\n'
                '#CMAKE_GENERATOR_PLATFORM:=Win32\n'
                ' Ordinary:STRING=value\n\t"Quoted:ordinary":STRING=value\n'
                'CMAKE_GENERATOR :STRING=unrelated\nCMAKE_GENERATOR\t:STRING=unrelated\n'
                '" CMAKE_GENERATOR":STRING=unrelated\n"CMAKE_GENERATOR ":STRING=unrelated\n')
        for newline in ('\n', '\r\n'):
            with self.subTest(newline=repr(newline)), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                graph, cache, paths = self.package_cache_fixture(root, text.replace('\n', newline))
                with self.conan_paths(paths):
                    result = check.package_paths(graph, root)
                self.assertEqual(result['source'], str(root / 'cache-build/bullet-src'))
                self.assertEqual((root / 'native-CMakeCache.txt').read_bytes(), cache.read_bytes())
                self.assertTrue((root / 'resolved-package.json').is_file())

    def test_package_cache_valid_plus_malformed_identity(self):
        valid = ('CMAKE_GENERATOR:INTERNAL=Visual Studio 17 2022\n'
                 'CMAKE_GENERATOR_PLATFORM:INTERNAL=x64\n'
                 'CMAKE_HOME_DIRECTORY:INTERNAL=SOURCE\n')
        for key, value in (('CMAKE_GENERATOR', 'Ninja'),
                           ('CMAKE_GENERATOR_PLATFORM', 'Win32'), ('CMAKE_HOME_DIRECTORY', 'SOURCE')):
            for suffix in (f':={value}\n', f':INTERNAL\n={value}\n',
                           f'={value}\n', ':INTERNAL\n', '\n'):
                for newline in ('\n', '\r\n'):
                    with self.subTest(key=key, suffix=suffix, newline=repr(newline)), \
                            tempfile.TemporaryDirectory() as folder:
                        root = Path(folder)
                        text = (valid + '# comment\n\n// comment\n' + key + suffix).replace('\n', newline)
                        graph, cache, paths = self.package_cache_fixture(root, text)
                        with self.conan_paths(paths), self.assertRaisesRegex(
                                ValueError, f'^malformed CMake cache key {key} at line 7$'):
                            check.package_paths(graph, root)
                        self.assertFalse((root / 'resolved-package.json').exists())
                        self.assertEqual((root / 'native-CMakeCache.txt').read_bytes(), cache.read_bytes())

    def test_package_cache_noncanonical_identity_spelling(self):
        valid = ('CMAKE_GENERATOR:INTERNAL=Visual Studio 17 2022\n'
                 'CMAKE_GENERATOR_PLATFORM:INTERNAL=x64\n'
                 'CMAKE_HOME_DIRECTORY:INTERNAL=SOURCE\n')
        for key, value in (('CMAKE_GENERATOR', 'Ninja'),
                           ('CMAKE_GENERATOR_PLATFORM', 'Win32'), ('CMAKE_HOME_DIRECTORY', '/outside')):
            for spelling in (' ' + key, '\t' + key, ' \t' + key,
                             f'"{key}"', f' \t"{key}"'):
                for suffix in (f':STRING={value}\n', f':={value}\n',
                               f'={value}\n', ':INTERNAL\n', '\n'):
                    for newline in ('\n', '\r\n'):
                        with self.subTest(spelling=spelling, suffix=suffix, newline=repr(newline)), \
                                tempfile.TemporaryDirectory() as folder:
                            root = Path(folder)
                            text = (valid + '# comment\n\n// comment\n' + spelling + suffix).replace('\n', newline)
                            graph, cache, paths = self.package_cache_fixture(root, text)
                            with self.conan_paths(paths), self.assertRaisesRegex(
                                    ValueError, f'^malformed CMake cache key {key} at line 7$'):
                                check.package_paths(graph, root)
                            self.assertFalse((root / 'resolved-package.json').exists())
                            self.assertEqual((root / 'native-CMakeCache.txt').read_bytes(), cache.read_bytes())

    def test_package_cache_identity_requires_physical_record(self):
        identities = ('CMAKE_GENERATOR:STRING=Visual Studio 17 2022',
                      'CMAKE_GENERATOR_PLATFORM:STRING=x64',
                      'CMAKE_HOME_DIRECTORY:STRING=SOURCE')
        for index, identity in enumerate(identities):
            for separator in ('\r', '\v', '\f', '\x1c', '\x1d', '\x1e', '\x85', '\u2028', '\u2029'):
                for prefix in ('UNRELATED:STRING=x', '//comment', '#comment'):
                    for newline in ('\n', '\r\n'):
                        with self.subTest(identity=identity, separator=repr(separator),
                                          prefix=prefix, newline=repr(newline)), \
                                tempfile.TemporaryDirectory() as folder:
                            root = Path(folder)
                            lines = list(identities)
                            lines[index] = prefix + separator + identity
                            graph, cache, paths = self.package_cache_fixture(root, newline.join(lines) + newline)
                            with self.conan_paths(paths), \
                                    self.assertRaises((ValueError, KeyError)):
                                check.package_paths(graph, root)
                            self.assertFalse((root / 'resolved-package.json').exists())
                            self.assertEqual((root / 'native-CMakeCache.txt').read_bytes(), cache.read_bytes())

    def test_package_cache_unrelated_embedded_identity_is_not_duplicate(self):
        valid = ('CMAKE_GENERATOR:STRING=Visual Studio 17 2022\n'
                 'CMAKE_GENERATOR_PLATFORM:STRING=x64\n'
                 'CMAKE_HOME_DIRECTORY:STRING=SOURCE\n')
        for separator in ('\r', '\v', '\f', '\x1c', '\x1d', '\x1e', '\x85', '\u2028', '\u2029'):
            for prefix in ('UNRELATED:STRING=x', '//comment', '#comment'):
                with self.subTest(separator=repr(separator), prefix=prefix), \
                        tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    text = valid + prefix + separator + 'CMAKE_GENERATOR:STRING=Ninja\nTAIL:STRING=valid\n'
                    graph, cache, paths = self.package_cache_fixture(root, text)
                    with self.conan_paths(paths):
                        result = check.package_paths(graph, root)
                    self.assertEqual(result['source'], str(root / 'cache-build/bullet-src'))
                    self.assertTrue((root / 'resolved-package.json').is_file())
                    self.assertEqual((root / 'native-CMakeCache.txt').read_bytes(), cache.read_bytes())

    def test_package_cache_duplicate_identity_diagnostic(self):
        for key, value in (('CMAKE_GENERATOR', 'Visual Studio 17 2022'),
                           ('CMAKE_GENERATOR_PLATFORM', 'x64'), ('CMAKE_HOME_DIRECTORY', 'SOURCE')):
            text = f'# comment\n{key}:INTERNAL={value}\n\n// comment\n{key}:INTERNAL={value}\n'
            with self.subTest(key=key), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                graph, cache, paths = self.package_cache_fixture(root, text)
                with self.conan_paths(paths), self.assertRaisesRegex(
                        ValueError, f'^duplicate CMake cache key {key} at line 5$'):
                    check.package_paths(graph, root)
                self.assertEqual((root / 'native-CMakeCache.txt').read_bytes(), cache.read_bytes())

    def test_package_cache_missing_malformed_and_duplicate_values(self):
        valid = ('CMAKE_GENERATOR:INTERNAL=Visual Studio 17 2022\n'
                 'CMAKE_GENERATOR_PLATFORM:INTERNAL=x64\n'
                 'CMAKE_HOME_DIRECTORY:INTERNAL=SOURCE\n')
        cases = [(valid.replace(line, ''), ValueError) for line in valid.splitlines(keepends=True)[:2]]
        cases += [(valid.replace('CMAKE_HOME_DIRECTORY:INTERNAL=SOURCE\n', ''), ValueError),
                  (valid.replace(':INTERNAL=', '=') , ValueError),
                  (valid.replace('Visual Studio 17 2022', 'Ninja'), ValueError),
                  (valid.replace('x64', 'Win32'), ValueError),
                  (valid + 'CMAKE_GENERATOR_PLATFORM:INTERNAL=Win32\n', ValueError),
                  ('CMAKE_GENERATOR_PLATFORM:INTERNAL=Win32\n' + valid, ValueError),
                  (valid.replace('CMAKE_GENERATOR:INTERNAL=', 'CMAKE_GENERATOR:INTERNAL\n='), ValueError)]
        for text, error in cases:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                graph, cache, paths = self.package_cache_fixture(root, text)
                with self.conan_paths(paths):
                    if error:
                        with self.assertRaises(error):
                            check.package_paths(graph, root)
                        self.assertFalse((root / 'resolved-package.json').exists())
                    else:
                        check.package_paths(graph, root)
                self.assertEqual((root / 'native-CMakeCache.txt').read_bytes(), cache.read_bytes())

    def test_package_cache_actual_nul_and_cr_aliases(self):
        valid = ('CMAKE_GENERATOR:INTERNAL=Visual Studio 17 2022\n'
                 'CMAKE_GENERATOR_PLATFORM:INTERNAL=x64\n'
                 'CMAKE_HOME_DIRECTORY:INTERNAL=SOURCE\n')
        cases = []
        for key, value in zip(check.CACHE_IDENTITIES, ('Ninja', 'Win32', '/outside')):
            cases += [valid.replace(key + ':INTERNAL=', key + ':INTER\0NAL='),
                      valid + key + ':INTER\0NAL=' + value + '\n',
                      valid + '\r \t\r' + key + ':STRING=' + value + '\n',
                      valid + '\r \t\r' + key + ':STRING=' + value + '\n' +
                      '\r' + key + ':STRING=' + value + '\n']
        cases += [valid + 'UNRELATED:INTER\0NAL=x\n']
        for text in cases:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                graph, cache, paths = self.package_cache_fixture(root, text)
                raw = cache.read_bytes()
                sentinel = cache.parent / 'PreLoad.cmake'
                sentinel.write_text('message(FATAL_ERROR "Native PreLoad executed")\n')
                sentinel_raw = sentinel.read_bytes()
                with self.conan_paths(paths), self.assertRaises(ValueError):
                    check.package_paths(graph, root)
                self.assertFalse((root / 'resolved-package.json').exists())
                self.assertEqual(cache.read_bytes(), raw)
                self.assertEqual((root / 'native-CMakeCache.txt').read_bytes(), raw)
                self.assertEqual(sentinel.read_bytes(), sentinel_raw)
                identity = json.loads((root / 'native-cache-reader-identity.json').read_text())
                self.assertEqual(Path(identity['input']).read_bytes(), raw)
                self.assertEqual(Path(identity['script']).read_text(), check.CACHE_READER)
                stderr = root / 'native-cache-reader.stderr'
                if '\0' in text and stderr.exists():
                    self.assertTrue(stderr.read_bytes())

    def test_cache_reader_rejects_zero_exit_stderr_and_bad_markers(self):
        markers = ''.join('-- DBVT_CACHE_' + key + '=78\n' for key in check.CACHE_IDENTITIES).encode()
        cases = [(markers, b'CMake Error: parse error\n'), (markers + markers, b''),
                 (markers.replace(b'=78', b'=7'), b''),
                 (markers.replace(b'=78', b'=FF'), b''),
                 (markers.replace(b'=78', b'=ff'), b''),
                 (markers.split(b'\n', 1)[1], b''),
                 (markers + b'-- DBVT_CACHE_UNKNOWN=78\n', b'')]
        for stdout, stderr in cases:
            with self.subTest(stdout=stdout, stderr=stderr), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                cache = root / 'CMakeCache.txt'
                cache.write_bytes(b'UNRELATED:STRING=x\n')
                def reader(argv, out, name, **kwargs):
                    (out / (name + '.stderr')).write_bytes(stderr)
                    return stdout
                with patch.object(check, 'run', side_effect=reader), self.assertRaises(ValueError):
                    check.read_native_cache(cache, root)

    def test_cache_reader_safe_scratch_and_byte_mutation(self):
        valid = ('CMAKE_GENERATOR:INTERNAL=Visual Studio 17 2022\n'
                 'CMAKE_GENERATOR_PLATFORM:INTERNAL=x64\n'
                 'CMAKE_HOME_DIRECTORY:INTERNAL=SOURCE\n')
        for mutate in (None, 'original', 'saved', 'input'):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                graph, cache, paths = self.package_cache_fixture(root, valid)
                original_run = check.run
                answers = iter(paths)
                def reader(argv, out, name, **kwargs):
                    if argv[0] == 'conan':
                        return next(answers)
                    scratch = Path(kwargs['cwd'])
                    self.assertNotEqual(scratch, cache.parent)
                    self.assertFalse((scratch / 'CMakeCache.txt').exists())
                    self.assertFalse((scratch / 'PreLoad.cmake').exists())
                    sentinel = scratch / 'input/PreLoad.cmake'
                    sentinel.write_text('message(FATAL_ERROR "Input PreLoad executed")\n')
                    before = sentinel.read_bytes()
                    output = original_run(argv, out, name, **kwargs)
                    self.assertEqual(sentinel.read_bytes(), before)
                    if mutate:
                        target = {'original': cache, 'saved': root / 'native-CMakeCache.txt',
                                  'input': scratch / 'input/CMakeCache.txt'}[mutate]
                        target.write_bytes(b'changed')
                    return output
                with patch.object(check, 'run', side_effect=reader):
                    if mutate:
                        with self.assertRaisesRegex(ValueError, 'bytes changed'):
                            check.package_paths(graph, root)
                        self.assertFalse((root / 'resolved-package.json').exists())
                    else:
                        check.package_paths(graph, root)
                        self.assertTrue((root / 'resolved-package.json').exists())

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
        self.assertEqual(check.preprocess_args(['/c', '/FI', 'forced.h', '/Foa.obj', 'a.cpp'], 'a.cpp'),
                         ['/FI', 'forced.h', '/E', '/showIncludes', 'a.cpp'])

    def test_replay_preserves_case_and_dash_switch_semantics(self):
        self.assertEqual(check.preprocess_args(['-TP', '-c', '-FI', 'forced.h', '-Fooutput.obj', '-Fioutput.i', 'good.cpp'], 'good.cpp'),
                         ['-TP', '-FI', 'forced.h', '/E', '/showIncludes', 'good.cpp'])
        for flag in ('/fi', '/FO', '-fo', '-fI'):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                check.preprocess_args([flag, 'good.cpp'], 'good.cpp')

    def test_replay_rejects_other_source(self):
        with self.assertRaises(ValueError):
            check.preprocess_args(['/c', 'other.cpp'], 'source.cpp')

    def test_actual_selected_tus_preserve_source_argv_and_preprocessing(self):
        import ntpath
        from pathlib import PureWindowsPath

        class WindowsPath(PureWindowsPath):
            def resolve(self):
                return WindowsPath(ntpath.normpath(str(self)))

        fixture = Path(__file__).with_name('fixtures') / 'compiler/selected-tus.json'
        records = json.loads(fixture.read_text())['records']
        self.assertEqual([r['name'] for r in records], list(check.TUS))
        for record in records:
            with self.subTest(name=record['name']):
                [source] = record['sources']
                [line] = [line for line in record['lines'] if line.strip()]
                argv = check.split_command(line)
                self.assertEqual(argv, record['argv'])
                original = argv[:]
                cwd = WindowsPath(source).parent
                with patch.object(check, 'Path', WindowsPath):
                    index = check.compile_source_index(argv, source, cwd)
                    replay = check.preprocess_args(argv, source, cwd=cwd)
                self.assertEqual(argv[index], source)
                self.assertEqual(argv, original)
                self.assertEqual(replay[-3:], ['/E', '/showIncludes', source])
                self.assertEqual(check.policy_flags(argv), ['/DWIN32', '/fp:precise', '/std:c++17'])
                if record['name'] == 'scene_create':
                    flags = ['/W3', '/openmp', '/permissive-', '/wd4267', '/wd4244',
                             '/wd4245', '/utf-8', '/Zc:alignedNew-']
                    self.assertEqual([arg for arg in replay if arg in flags], flags)
                    self.assertFalse(any(arg.startswith(('/Fo', '/Fd')) for arg in replay))

    def test_observed_cl_flags_are_exact_operand_free_tokens(self):
        flags = ('W3', 'openmp', 'permissive-', 'wd4267', 'wd4244', 'wd4245', 'utf-8', 'Zc:alignedNew-')
        for prefix in ('/', '-'):
            args = [prefix + flag for flag in flags]
            self.assertEqual(check.preprocess_args(['/c', *args, 'good.cpp'], 'good.cpp'),
                             [*args, '/E', '/showIncludes', 'good.cpp'])
            for flag in flags:
                for extra in ('other.cpp', 'input.obj', 'extensionless', ''):
                    with self.subTest(flag=flag, extra=extra), self.assertRaises(ValueError):
                        check.preprocess_args([prefix + flag, extra, 'good.cpp'], 'good.cpp')
                with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'caret full path'):
                    check.preprocess_args([prefix + flag, 'other.cpp'], 'good.cpp')
            for flag in ('W2', 'W4', 'w3', 'wd9999', 'wd4267:bad', 'wd', 'openmp:llvm',
                         'openmp:experimental', 'openmp-', 'permissive', 'permissive-:bad',
                         'utf-8:bad', 'utf8', 'Zc:alignedNew', 'Zc:alignedNew-:bad'):
                with self.subTest(flag=flag), self.assertRaises(ValueError):
                    check.preprocess_args([prefix + flag, 'good.cpp'], 'good.cpp')
        with patch.dict(os.environ, {'CL': '/Zc:alignedNew-', '_CL_': ''}):
            self.assertEqual(check.compiler_environment()['CL'], ['/Zc:alignedNew-'])
        for flag in flags[:-1]:
            with patch.dict(os.environ, {'CL': '/' + flag, '_CL_': ''}):
                with self.subTest(environment=flag), self.assertRaises(ValueError):
                    check.compiler_environment()

    def test_actual_windows_dbvt_tlogs_keep_global_cpp_mode(self):
        # Actions 40439880708, artifact 12705684917, captured caret and command records.
        records = ['^D:\\A\\_TEMP\\DBVT-CONAN-40439880708-1-X64\\P\\B\\BULLEA12CEBAAD519B\\B\\BULLET-SRC\\SRC\\BULLETCOLLISION\\BROADPHASECOLLISION\\BTDBVT.CPP\n/c /I"D:\\A\\_TEMP\\DBVT-CONAN-40439880708-1-X64\\P\\B\\BULLEA12CEBAAD519B\\B\\BULLET-SRC\\SRC" /I\\SRC /I"D:\\A\\_TEMP\\DBVT-CONAN-40439880708-1-X64\\P\\B\\BULLEA12CEBAAD519B\\B\\BULLET-SRC\\SRC\\BULLETCOLLISION\\}" /nologo /W1 /WX- /diagnostics:column /O2 /Ob2 /D _MBCS /D WIN32 /D _WINDOWS /D NDEBUG /D "CMAKE_INTDIR=\\"Release\\"" /EHsc /MD /GS /fp:precise /Zc:wchar_t /Zc:forScope /Zc:inline /GR /std:c++17 /Fo"BULLETCOLLISION.DIR\\RELEASE\\\\" /Fd"D:\\A\\_TEMP\\DBVT-CONAN-40439880708-1-X64\\P\\B\\BULLEA12CEBAAD519B\\B\\BUILD\\BULLETCOLLISION\\RELEASE\\BULLETCOLLISION.PDB" /external:W1 /Gd /TP D:\\A\\_TEMP\\DBVT-CONAN-40439880708-1-X64\\P\\B\\BULLEA12CEBAAD519B\\B\\BULLET-SRC\\SRC\\BULLETCOLLISION\\BROADPHASECOLLISION\\BTDBVT.CPP\n', '^D:\\A\\_TEMP\\DBVT-CONAN-40439880708-1-X64\\P\\B\\BULLEA12CEBAAD519B\\B\\BULLET-SRC\\SRC\\BULLETCOLLISION\\BROADPHASECOLLISION\\BTDBVTBROADPHASE.CPP\n/c /I"D:\\A\\_TEMP\\DBVT-CONAN-40439880708-1-X64\\P\\B\\BULLEA12CEBAAD519B\\B\\BULLET-SRC\\SRC" /I\\SRC /I"D:\\A\\_TEMP\\DBVT-CONAN-40439880708-1-X64\\P\\B\\BULLEA12CEBAAD519B\\B\\BULLET-SRC\\SRC\\BULLETCOLLISION\\}" /nologo /W1 /WX- /diagnostics:column /O2 /Ob2 /D _MBCS /D WIN32 /D _WINDOWS /D NDEBUG /D "CMAKE_INTDIR=\\"Release\\"" /EHsc /MD /GS /fp:precise /Zc:wchar_t /Zc:forScope /Zc:inline /GR /std:c++17 /Fo"BULLETCOLLISION.DIR\\RELEASE\\\\" /Fd"D:\\A\\_TEMP\\DBVT-CONAN-40439880708-1-X64\\P\\B\\BULLEA12CEBAAD519B\\B\\BUILD\\BULLETCOLLISION\\RELEASE\\BULLETCOLLISION.PDB" /external:W1 /Gd /TP D:\\A\\_TEMP\\DBVT-CONAN-40439880708-1-X64\\P\\B\\BULLEA12CEBAAD519B\\B\\BULLET-SRC\\SRC\\BULLETCOLLISION\\BROADPHASECOLLISION\\BTDBVTBROADPHASE.CPP\n']
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'CL.command.1.tlog'
            for record in records:
                with self.subTest(source=record.splitlines()[0]):
                    path.write_bytes(record.encode('utf-16'))
                    [(sources, args)] = check.tlog_commands(path)
                    self.assertEqual(check.compile_source_index(args, sources[0], path.parent), len(args) - 1)
                    replay = check.preprocess_args(args, sources[0], cwd=path.parent)
                    self.assertIn('/TP', replay)
                    self.assertEqual(replay[-1], sources[0])

    def test_global_cpp_mode_counts_every_positional_input(self):
        for mode in ('/TP', '-TP'):
            for source in ('good.cpp', 'good.h', 'extensionless', 'input.obj', 'input.lib', 'input.bin'):
                for args in ([mode, '/c', source], ['/c', source, mode]):
                    with self.subTest(args=args):
                        self.assertEqual(check.preprocess_args(args, source), [mode, '/E', '/showIncludes', source])
            for extra in ('other.cpp', 'other.h', 'extensionless', 'input.obj', 'input.lib', 'good.cpp'):
                for args in ([mode, 'good.cpp', extra], ['good.cpp', extra, mode]):
                    with self.subTest(args=args), self.assertRaises(ValueError):
                        check.preprocess_args(args, 'good.cpp')
            with self.assertRaisesRegex(ValueError, 'caret full path'):
                check.preprocess_args([mode, 'other.cpp'], 'good.cpp')

    def test_cl_option_values_are_not_source_operands(self):
        options = ('D', 'U', 'I', 'FI', 'external:I')
        for prefix in ('/', '-'):
            for option in options:
                values = ('other.cpp', 'other.h', 'extensionless', 'input.obj')
                if option == 'D':
                    values = tuple('NAME=' + value for value in values)
                elif option == 'U':
                    values = ('OTHER_CPP', 'OTHER_H', 'EXTENSIONLESS', 'INPUT_OBJ')
                for value in values:
                    for flags in ([prefix + option, value], [prefix + option + value]):
                        args = ['/TP', *flags, 'good.cpp']
                        with self.subTest(args=args):
                            self.assertEqual(check.compile_source_index(args, 'good.cpp', Path.cwd()), len(args) - 1)
            for option in (*options, 'sourceDependencies', 'sourceDependencies:directives', 'scanDependencies'):
                with self.subTest(option=option), self.assertRaisesRegex(ValueError, 'missing its value'):
                    check.compile_source_index(['good.cpp', prefix + option], 'good.cpp', Path.cwd())
        for option in ('/sourceDependencies', '/sourceDependencies:directives', '/scanDependencies'):
            args = ['/TP', option, 'dependency.json', 'good.cpp']
            self.assertEqual(check.compile_source_index(args, 'good.cpp', Path.cwd()), 3)
        with self.assertRaises(ValueError):
            check.preprocess_args(['/D', '/TP', 'good.h'], 'good.h')
        for option in ('/tp', '/tP', '/unknown', '/unknown:other.h', '/link', '/TPextra', '-TPextra'):
            with self.subTest(option=option), self.assertRaises(ValueError):
                check.preprocess_args(['/TP', option, 'good.cpp'], 'good.cpp')
        for extra in ('other.h', 'extensionless', 'input.obj', 'input.lib'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                check.preprocess_args(['good.cpp', extra], 'good.cpp')

    def test_output_paths_are_attached_and_never_hide_following_tokens(self):
        for prefix in ('/', '-'):
            for name in ('Fo', 'Fd', 'Fe', 'Fa', 'Fi', 'Fp'):
                for value in ('other.cpp', 'other.h', 'extensionless', 'input.obj',
                              'input.lib', prefix + 'TC', prefix + 'Tpother.h', prefix + 'unknown'):
                    args = [prefix + 'TP', prefix + name, value, 'good.cpp']
                    with self.subTest(args=args):
                        with self.assertRaises(ValueError):
                            check.compile_source_index(args, 'good.cpp', Path.cwd())
                        with self.assertRaises(ValueError):
                            check.preprocess_args(args, 'good.cpp')
                for suffix in ('', ':', ':output.obj'):
                    with self.subTest(name=name, suffix=suffix), self.assertRaises(ValueError):
                        check.preprocess_args(['/TP', prefix + name + suffix, 'good.cpp'], 'good.cpp')
                args = [prefix + 'TP', prefix + name + 'output.obj', 'good.cpp']
                expected = [prefix + 'TP']
                if name == 'Fp':
                    expected.append(prefix + name + 'output.obj')
                self.assertEqual(check.preprocess_args(args, 'good.cpp'),
                                 [*expected, '/E', '/showIncludes', 'good.cpp'])

    def test_cl_required_value_edges_and_dependency_forms(self):
        for prefix in ('/', '-'):
            for name in ('D', 'U', 'I', 'FI', 'external:I', 'sourceDependencies',
                         'sourceDependencies:directives', 'scanDependencies'):
                for value in ('', prefix + 'TC', prefix + 'Tpother.h', prefix + 'unknown', ':bad'):
                    args = ['/TP', prefix + name, value, 'good.cpp']
                    with self.subTest(args=args), self.assertRaises(ValueError):
                        check.preprocess_args(args, 'good.cpp')
                with self.subTest(name=name), self.assertRaises(ValueError):
                    check.preprocess_args(['/TP', prefix + name + ':', 'good.cpp'], 'good.cpp')
            for name in ('sourceDependencies', 'sourceDependencies:directives', 'scanDependencies'):
                for tail in ([prefix + name, 'dep.json'], [prefix + name + '-']):
                    args = ['/TP', *tail, 'good.cpp']
                    self.assertEqual(check.preprocess_args(args, 'good.cpp'),
                                     ['/TP', *tail, '/E', '/showIncludes', 'good.cpp'])
                for suffix in (':dep.json', 'dep.json'):
                    with self.assertRaises(ValueError):
                        check.preprocess_args(['/TP', prefix + name + suffix, 'good.cpp'], 'good.cpp')

    def test_modes_are_an_exact_supported_set(self):
        bogus = ('EHnotanoption', 'Zc:notACompilerOption', 'arch:madeup', 'fp:madeup',
                 'std:c++notastandard', 'favor:madeup', 'openmp:madeup')
        for prefix in ('/', '-'):
            for mode in bogus:
                with self.subTest(mode=mode, prefix=prefix), self.assertRaises(ValueError):
                    check.preprocess_args([prefix + mode, 'good.cpp'], 'good.cpp')
            for mode in ('EHsc', 'Zc:wchar_t', 'Zc:forScope', 'Zc:inline', 'std:c++17',
                         'fp:precise', 'fp:fast', 'fp:strict', 'arch:SSE2', 'arch:AVX', 'arch:AVX2'):
                self.assertEqual(check.preprocess_args([prefix + mode, 'good.cpp'], 'good.cpp'),
                                 [prefix + mode, '/E', '/showIncludes', 'good.cpp'])

    def test_pch_filename_is_optional_and_attached(self):
        for prefix in ('/', '-'):
            for pch in ('Yu', 'Yc'):
                with self.assertRaises(ValueError):
                    check.preprocess_args([prefix + pch + ':header.h', 'good.cpp'], 'good.cpp')
                for value in ('', 'other.h', 'other.cpp', 'extensionless'):
                    flag = prefix + pch + value
                    for args in ([prefix + 'TP', flag, 'good.cpp'],
                                 [prefix + 'TP', 'good.cpp', flag]):
                        with self.subTest(args=args):
                            original = args[:]
                            self.assertEqual(check.preprocess_args(args, 'good.cpp'),
                                             [prefix + 'TP', flag, '/E', '/showIncludes', 'good.cpp'])
                            self.assertEqual(args, original)

    def test_bare_pch_does_not_hide_inputs_or_switches(self):
        for prefix in ('/', '-'):
            for pch in ('Yu', 'Yc'):
                for extra in ('other.h', 'other.cpp', 'extensionless', 'input.obj', 'input.lib',
                              'good.cpp', '', prefix + 'TC', prefix + 'Tpother.h',
                              prefix + 'Tcother.cpp', prefix + 'unknown'):
                    args = [prefix + 'TP', prefix + pch, extra, 'good.cpp']
                    with self.subTest(args=args), self.assertRaises(ValueError):
                        check.preprocess_args(args, 'good.cpp')
                for required in ('D', 'U', 'I', 'FI', 'Fo', 'Fd', 'Fe', 'Fa', 'Fi', 'Fp',
                                 'external:I', 'sourceDependencies', 'sourceDependencies:directives',
                                 'scanDependencies'):
                    for tail in ([prefix + required], [prefix + required, '']):
                        args = [prefix + 'TP', 'good.cpp', prefix + pch, *tail]
                        with self.subTest(args=args), self.assertRaisesRegex(ValueError, 'missing its value'):
                            check.preprocess_args(args, 'good.cpp')
                with self.assertRaisesRegex(ValueError, 'caret full path'):
                    check.preprocess_args([prefix + 'TP', prefix + pch, 'other.cpp'], 'good.cpp')

    def test_response_pch_preserves_caret_and_rejects_hidden_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            response = root / 'inner.rsp'
            (root / 'outer.rsp').write_text('/c @inner.rsp /Fooutput.obj')
            tlog = root / 'CL.command.1.tlog'
            tlog.write_bytes('^good.cpp\n@outer.rsp\n'.encode('utf-16'))
            [(sources, command)] = check.tlog_commands(tlog)
            for prefix in ('/', '-'):
                for pch in ('Yu', 'Yc'):
                    response.write_bytes(f'{prefix}TP {prefix}{pch} good.cpp'.encode('utf-16'))
                    args = check.expand(command, root, [])
                    original = args[:]
                    with self.subTest(prefix=prefix, pch=pch):
                        self.assertEqual(check.preprocess_args(args, sources[0], cwd=root),
                                         [prefix + 'TP', prefix + pch, '/E', '/showIncludes', 'good.cpp'])
                        self.assertEqual(args, original)
                    for extra in ('other.h', 'other.cpp', 'extensionless', '""',
                                  prefix + 'TC', prefix + 'Tpother.h', prefix + 'unknown'):
                        response.write_text(f'{prefix}TP {prefix}{pch} {extra} good.cpp')
                        with self.subTest(extra=extra, pch=pch, prefix=prefix), self.assertRaises(ValueError):
                            check.preprocess_args(check.expand(command, root, []), sources[0], cwd=root)

    def test_response_expanded_global_mode_preserves_single_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'inner.rsp').write_bytes('/TP /FI forced.h /D NAME=other.cpp good.cpp'.encode('utf-16'))
            (root / 'outer.rsp').write_text('/c @inner.rsp /Fooutput.obj')
            args = check.expand(['@outer.rsp'], root, [])
            self.assertEqual(check.preprocess_args(args, 'good.cpp', cwd=root),
                             ['/TP', '/FI', 'forced.h', '/D', 'NAME=other.cpp', '/E', '/showIncludes', 'good.cpp'])
            for suffix in (' other.h', ' extensionless', ' input.obj', ' /Tpother.h', ' /Tcother', ' /TC', ' /unknown value'):
                (root / 'inner.rsp').write_text('/TP good.cpp' + suffix)
                with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                    check.preprocess_args(check.expand(['@outer.rsp'], root, []), 'good.cpp', cwd=root)

    def test_tlog_requires_source_association(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'CL.command.1.tlog'
            path.write_bytes('^source.cpp\n/c /DWIN32 /I"a b"\n'.encode('utf-16'))
            self.assertEqual(check.tlog_commands(path), [(['source.cpp'], ['/c', '/DWIN32', '/Ia b'])])
            path.write_text('/c /DWIN32')
            with self.assertRaises(ValueError):
                check.tlog_commands(path)

    def test_actual_link_tasks_preserve_lines_and_argv(self):
        fixtures = Path(__file__).with_name('fixtures') / 'link'
        for label, count in (('app', 9), ('probe', 1)):
            path = fixtures / (label + '.tlog')
            expected = json.loads(path.with_suffix('.tlog.json').read_text())
            with self.subTest(label=label):
                self.assertEqual(check.digest(path), expected['sha256'])
                [(sources, lines)] = check.tlog_tasks(path)
                raw_lines = path.read_bytes().decode('utf-16').splitlines()
                self.assertEqual(sources, raw_lines[0][1:].split('|'))
                self.assertEqual(lines, raw_lines[1:])
                self.assertEqual(len(lines), count)
                responses = []
                argv = check.linker_args((sources, lines), path.parent, responses)
                identity = json.dumps(argv, separators=(',', ':'), ensure_ascii=False).encode()
                self.assertEqual(hashlib.sha256(identity).hexdigest(), expected['argv_sha256'])
                self.assertEqual(responses, [])
                if label == 'app':
                    self.assertIn('D:/a/MikuDanceStudio-J/MikuDanceStudio-J/res/gen_resources_x64.res', argv)
                    with self.assertRaisesRegex(ValueError, 'multiple command lines'):
                        check.tlog_commands(path)

    def test_linker_continuations_are_only_object_or_resource_operands(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = '/OUT:app.exe /MAP:app.map first.obj generated.res'
            task = (['first.obj', 'a b.obj', 'icon.res'], [first, '', '  "a b.obj" icon.res  ', ''])
            self.assertEqual(check.linker_args(task, root, []),
                             ['/OUT:app.exe', '/MAP:app.map', 'first.obj', 'generated.res', 'a b.obj', 'icon.res'])
            for line in ('/OUT:other.obj', '/MAP:other.res', '-OUT:other.obj', '@other.obj',
                         'link.exe other.obj', 'cmd /c other.obj', 'other.lib', '""',
                         'a.obj && b.obj', 'a.obj | b.obj', 'a.obj > b.obj',
                         '"unterminated.obj', 'a.obj"', 'a.obj:stream.obj', 'a?.obj',
                         '/NOLOGO a.obj', '/DEFAULTLIB:other.obj'):
                with self.subTest(line=line), self.assertRaises(ValueError):
                    check.linker_args((['first.obj'], [first, line]), root, [])
            for lines in ([], [''], ['""'], ['"unterminated', 'a.obj"']):
                with self.subTest(lines=lines), self.assertRaises(ValueError):
                    check.linker_args((['a.obj'], lines), root, [])

    def test_linker_first_line_responses_keep_provenance_and_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'inner.rsp').write_bytes('/MAP:app.map first.obj'.encode('utf-16'))
            (root / 'outer.rsp').write_text('/OUT:app.exe @inner.rsp generated.res')
            responses = []
            self.assertEqual(check.linker_args((['first.obj'], ['@outer.rsp', 'last.obj']), root, responses),
                             ['/OUT:app.exe', '/MAP:app.map', 'first.obj', 'generated.res', 'last.obj'])
            self.assertEqual([r['sha256'] for r in responses],
                             [check.digest(root / name) for name in ('outer.rsp', 'inner.rsp')])
            self.assertEqual(responses[1]['encoding'], 'utf-16')
            with self.assertRaises(ValueError):
                check.linker_args((['first.obj'], ['/OUT:app.exe', '@outer.rsp']), root, [])
            with self.assertRaises(OSError):
                check.linker_args((['first.obj'], ['@missing.rsp']), root, [])
            (root / 'loop.rsp').write_text('@loop.rsp')
            with self.assertRaises(ValueError):
                check.linker_args((['first.obj'], ['@loop.rsp']), root, [])

    def test_actual_librarian_tasks_preserve_lines_and_argv(self):
        import ntpath
        from pathlib import PureWindowsPath

        class WindowsPath(PureWindowsPath):
            def resolve(self):
                return WindowsPath(ntpath.normpath(str(self)))

        fixtures = Path(__file__).with_name('fixtures') / 'librarian'
        counts = {'BulletSoftBody': 7, 'BulletDynamics': 20, 'BulletCollision': 89, 'LinearMath': 5}
        for name, count in counts.items():
            path = fixtures / (name + '.tlog')
            expected = json.loads(path.with_suffix('.tlog.json').read_text())
            with self.subTest(name=name):
                self.assertEqual(check.digest(path), expected['sha256'])
                [(sources, lines)] = check.tlog_tasks(path)
                raw_lines = path.read_bytes().decode('utf-16').splitlines()
                self.assertEqual(sources, raw_lines[0][1:].split('|'))
                self.assertEqual(lines, raw_lines[1:])
                self.assertEqual(len(lines), count)
                cwd = WindowsPath(sources[0]).parent.parent.parent
                with patch.object(check, 'Path', WindowsPath):
                    argv, output = check.librarian_args((sources, lines), cwd, [])
                self.assertEqual(output, next(arg[5:] for arg in argv if arg.upper().startswith('/OUT:')))
                identity = json.dumps(argv, separators=(',', ':'), ensure_ascii=False).encode()
                self.assertEqual(hashlib.sha256(identity).hexdigest(), expected['argv_sha256'])
                with self.assertRaisesRegex(ValueError, 'multiple command lines'):
                    check.tlog_commands(path)

    def test_tlog_tasks_reject_missing_empty_and_truncated_records(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'command.tlog'
            for text in ('', '/c source.cpp', '^', '^a||b\n/c a', '^a\n^b\n/c b', '^a\n   ', '^a\n/c a\x00'):
                with self.subTest(text=text):
                    path.write_text(text)
                    with self.assertRaises(ValueError):
                        check.tlog_tasks(path)
            path.write_text('^a\n  /c a  \n\n^b\n/c b\n')
            self.assertEqual(check.tlog_tasks(path), [(['a'], ['  /c a  ', '']), (['b'], ['/c b'])])
            self.assertEqual(check.tlog_commands(path), [(['a'], ['/c', 'a']), (['b'], ['/c', 'b'])])

    def test_librarian_rejects_ambiguous_and_truncated_operands(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sources = [str(root / 'a.obj'), str(root / 'b.obj')]
            first = '/OUT:result.lib /NOLOGO /MACHINE:X64 a.obj'
            for lines in ([first], [first, 'b.obj', 'extra.obj'], [first, 'a.obj'],
                          [first, '/OUT:other.lib b.obj'], [first, 'lib.exe b.obj'],
                          [first, '"b.obj'], [first, 'b.obj /NOLOGO'],
                          [first, 'b.obj hidden.lib'], [first, '"" b.obj'],
                          ['/OUT:result.lib /UNKNOWN a.obj', 'b.obj'],
                          ['/OUT:result.lib /MACHINE:ARM64 a.obj', 'b.obj']):
                with self.subTest(lines=lines), self.assertRaises(ValueError):
                    check.librarian_args((sources, lines), root, [])
            with self.assertRaises(ValueError):
                check.librarian_args(([sources[0], sources[0]], [first]), root, [])
            (root / 'inputs.rsp').write_text('a.obj b.obj')
            self.assertEqual(check.librarian_args((sources, ['/OUT:result.lib @inputs.rsp']), root, []),
                             (['/OUT:result.lib', 'a.obj', 'b.obj'], 'result.lib'))
            (root / 'inputs.rsp').write_text('a.obj b.obj /UNKNOWN')
            with self.assertRaises(ValueError):
                check.librarian_args((sources, ['/OUT:result.lib @inputs.rsp']), root, [])

    def test_librarian_output_requires_one_nonempty_attached_value(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            task = ['a.obj']
            for command in ('a.obj', '/OUT: a.obj', '/out: result.lib a.obj',
                            '/OUT:result.lib /OUT:result.lib a.obj',
                            '/out:other.lib /OUT:result.lib a.obj',
                            '/OUT:result.lib /out:other.lib a.obj',
                            '/OUT:result.lib a.obj /out:other.lib',
                            '/out: /OUT:result.lib a.obj',
                            '/OUT:result.lib /out: a.obj'):
                with self.subTest(command=command), self.assertRaises(ValueError):
                    check.librarian_args((task, [command]), root, [])
            (root / 'output.rsp').write_text('/oUt:"Mixed Case/Result.LIB" a.obj')
            args, output = check.librarian_args((task, ['@output.rsp']), root, [])
            self.assertEqual(output, 'Mixed Case/Result.LIB')
            self.assertEqual(args, ['/oUt:Mixed Case/Result.LIB', 'a.obj'])
            (root / 'output.rsp').write_text('/out:other.lib')
            for command in ('@output.rsp /OUT:result.lib a.obj',
                            '/OUT:result.lib a.obj @output.rsp'):
                with self.subTest(command=command), self.assertRaises(ValueError):
                    check.librarian_args((task, [command]), root, [])

    def test_librarian_output_preserves_spelling_and_archive_identity(self):
        for prefix in ('/OUT:', '/out:', '/OuT:'):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                out, libs = self.archive_fixture(root)
                for name in check.LIBS:
                    path = next((root / name).rglob('Lib.command.1.tlog'))
                    path.write_text(path.read_text().replace('/OUT:', prefix))
                    args, output = check.librarian_args(check.tlog_tasks(path)[0], root / name, [])
                    self.assertEqual(output, libs[name]['build'])
                    self.assertEqual(args[0], prefix + output)
                proof = check.archive_commands(root, out, libs)
                self.assertEqual(set(proof), set(check.LIBS))
                for name, entry in proof.items():
                    self.assertEqual(entry['argv'][0], prefix + libs[name]['build'])
                    self.assertEqual(entry['archive_sha256'], check.digest(libs[name]['build']))
                path.write_text(path.read_text().replace(libs[name]['build'], 'unverified-other.lib'))
                with self.assertRaisesRegex(ValueError, 'librarian output does not match'):
                    check.archive_commands(root, out, libs)

    def test_librarian_rejects_duplicate_outputs_in_all_archives(self):
        variants = (
            ('/OUT:', ' /out:unverified-other.lib', False),
            ('/out:', ' /OUT:unverified-other.lib', False),
            ('/OUT:', ' /OUT:unverified-other.lib', False),
            ('/OuT:', ' /oUt:unverified-other.lib', True),
            ('/OUT:', ' /out:unverified-other.lib', True),
            ('/OUT:', ' /out: unverified-other.lib', False),
            ('/OUT:', ' /out:', False),
        )
        for prefix, extra, response in variants:
            for name in check.LIBS:
                with self.subTest(prefix=prefix, extra=extra, response=response, name=name):
                    with tempfile.TemporaryDirectory() as folder:
                        root = Path(folder)
                        out, libs = self.archive_fixture(root)
                        path = next((root / name).rglob('Lib.command.1.tlog'))
                        text = path.read_text().replace('/OUT:', prefix)
                        if response:
                            (root / name / 'outputs.rsp').write_text(extra)
                        path.write_text(text + (' @outputs.rsp' if response else extra))
                        with self.assertRaises(ValueError):
                            check.archive_commands(root, out, libs)

    def test_linker_continuations_reject_options(self):
        with tempfile.TemporaryDirectory() as folder:
            build, out, libs, tlog, _ = self.link_fixture(Path(folder))
            original = tlog.read_text()
            for content, error in ((original + '\n/NOLOGO\n', 'linker continuation'),
                                   (original + '\n' + original, 'ambiguous actual app linker task')):
                tlog.write_text(content)
                with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                    check.link_proof(build, 'app', out, libs)

    def test_librarian_multiline_archive_consumer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out, libs = self.archive_fixture(root)
            for name in check.LIBS:
                path = next((root / name).rglob('Lib.command.1.tlog'))
                sources, command = path.read_text().splitlines()
                args = check.split_command(command)
                path.write_text(sources + '\n' + '\n'.join(subprocess.list2cmdline([arg]) for arg in args) + '\n')
            result = check.archive_commands(root, out, libs)
            self.assertEqual(set(result), set(check.LIBS))
            for entry in result.values():
                self.assertEqual([str(Path(source).resolve()) for source in entry['task']['sources']], list(entry['inputs']))
                self.assertGreater(len(entry['task']['lines']), 1)
            path.write_text(path.read_text() + '^extra.obj\n/OUT:extra.lib extra.obj\n')
            with self.assertRaisesRegex(ValueError, 'ambiguous actual librarian task'):
                check.archive_commands(root, out, libs)

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

    def test_link_proof_multiline_task_retains_original_evidence(self):
        for label in ('app', 'probe'):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as folder:
                build, out, libs, tlog, map_path = self.link_fixture(Path(folder), label)
                sources, lines = check.tlog_tasks(tlog)[0]
                lines += ['', '"extra resource.res" extra.obj', '']
                tlog.write_bytes(('^' + '|'.join(sources) + '\r\n' + '\r\n'.join(lines) + '\r\n').encode('utf-16'))
                proof = check.link_proof(build, label, out, libs)
                self.assertEqual(proof['task'], dict(sources=sources, lines=lines))
                self.assertEqual(proof['tlog_sha256'], check.digest(tlog))
                self.assertEqual(proof['encoding'], 'utf-16')
                self.assertEqual(proof['argv'][-2:], ['extra resource.res', 'extra.obj'])
                map_path.write_text(map_path.read_text().replace(':btDbvt.obj', ':unrelated.obj'))
                with self.assertRaisesRegex(ValueError, 'map lacks'):
                    check.link_proof(build, label, out, libs)

    def test_multiline_link_preserves_read_and_probe_identity_gates(self):
        for label in ('app', 'probe'):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as folder:
                build, out, libs, tlog, _ = self.link_fixture(Path(folder), label)
                original = tlog.read_text() + '\nextra.obj extra.res\n'
                tlog.write_text(original)
                readlog = tlog.with_name('link.read.1.tlog')
                reads = readlog.read_text()
                tlog.write_text(original.replace('^app.obj', '^changed.obj'))
                with self.assertRaisesRegex(ValueError, 'read task does not match'):
                    check.link_proof(build, label, out, libs)
                tlog.write_text(original)
                if label == 'probe':
                    obj = str(tlog.parent / 'probe.obj')
                    for replacement in ('other.obj', ''):
                        args = check.split_command(original.splitlines()[1])
                        args[args.index(obj):args.index(obj) + 1] = [replacement] if replacement else []
                        tlog.write_text('^app.obj\n' + subprocess.list2cmdline(args) + '\nextra.obj extra.res\n')
                        with self.subTest(replacement=replacement), self.assertRaisesRegex(ValueError, 'exact linker input/read object'):
                            check.link_proof(build, label, out, libs)
                    tlog.write_text(original)
                    readlog.write_text(reads.replace(obj, 'other.obj'))
                    with self.assertRaisesRegex(ValueError, 'exact linker input/read object'):
                        check.link_proof(build, label, out, libs)

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
            tlog.write_text('^' + '|'.join(map(str, objects)) + '\n' + subprocess.list2cmdline(['/OUT:' + str(library), *map(str, objects)]))
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

    def test_archive_global_cpp_mode_retains_argv_and_rejects_extra_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out, libs = self.archive_fixture(root)
            tlog = root / 'BulletCollision/BulletCollision.dir/Release/CL.command.1.tlog'
            lines = tlog.read_text().splitlines()
            args = ['/TP', *check.split_command(lines[1]), '/Yu']
            lines[1] = subprocess.list2cmdline(args)
            tlog.write_text('\n'.join(lines) + '\n')
            record = check.archive_commands(root, out, libs)['BulletCollision']['dbvt_objects']['btDbvt']['compile']
            self.assertEqual(record['argv'], args)
            self.assertIn('/TP', check.preprocess_args(record['argv'], record['source'], cwd=record['cwd']))
            for extra in ('other.h', 'extensionless', 'input.obj', 'input.lib'):
                changed = lines[:]
                changed[1] = subprocess.list2cmdline([*args, extra])
                tlog.write_text('\n'.join(changed) + '\n')
                with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, 'exactly one source'):
                    check.archive_commands(root, out, libs)

    def test_archive_boundary_rejects_hidden_output_tokens_and_bogus_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out, libs = self.archive_fixture(root)
            tlog = root / 'BulletCollision/BulletCollision.dir/Release/CL.command.1.tlog'
            original = tlog.read_text().splitlines()
            args = ['/TP', *check.split_command(original[1])]
            for prefix in ('/', '-'):
                tails = [[prefix + name, value] for name in ('Fo', 'Fd', 'Fe', 'Fa', 'Fi', 'Fp')
                         for value in ('other.cpp', 'other.h', 'extensionless', 'input.obj', 'input.lib',
                                       prefix + 'TC', prefix + 'Tpother.h', prefix + 'unknown')]
                tails += [[prefix + mode] for mode in ('EHnotanoption', 'Zc:notACompilerOption',
                           'arch:madeup', 'fp:madeup', 'std:c++notastandard', 'favor:madeup', 'openmp:madeup')]
                for tail in tails:
                    changed = original[:]
                    changed[1] = subprocess.list2cmdline([*args, *tail])
                    tlog.write_text('\n'.join(changed) + '\n')
                    with self.subTest(tail=tail), self.assertRaises(ValueError):
                        check.archive_commands(root, out, libs)
            dashed = [('-' + arg[1:]) if arg.startswith(('/Fo', '/c')) else arg for arg in args]
            changed = original[:]
            changed[1] = subprocess.list2cmdline(dashed)
            tlog.write_text('\n'.join(changed) + '\n')
            record = check.archive_commands(root, out, libs)['BulletCollision']['dbvt_objects']['btDbvt']['compile']
            self.assertEqual(record['argv'], dashed)

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
        modes += [[flag, 'other.h'] for flag in ('/TC', '-TC')]
        modes += [[flag] for flag in ('/TC', '-TC')]
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
                 patch.object(check, 'classify', return_value=('profile', {})):
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
            args.insert(0, '/TP')
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

    def test_windows_race_wait_binding_preserves_dword_failures(self):
        import ctypes
        results = iter([0xffffffff])
        wait = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)(
            lambda handle, timeout: next(results))
        self.assertEqual(wait(102, 0), -1)
        kernel = MagicMock()
        kernel.WaitForSingleObject = wait
        with patch.object(ctypes, 'WinDLL', return_value=kernel, create=True), \
             patch.object(subprocess, 'Popen', side_effect=RuntimeError('binding configured')) as popen, \
             patch.object(time, 'sleep'), self.assertRaisesRegex(RuntimeError, 'binding configured'):
            self.windows_race_control()
        popen.assert_called_once()
        self.assertEqual(ctypes.sizeof(wait.restype), 4)
        for result in (0, 258, 0xffffffff):
            results = iter([result])
            self.assertEqual(wait(102, 0), result)
        for statuses, message in (([0xffffffff], 'initial wait failed.*error=123'),
                                  ([258, 0xffffffff], 'cleanup failed.*wait error=123')):
            with self.subTest(statuses=statuses):
                results = iter(statuses)
                kernel.CloseHandle.reset_mock()
                with patch.object(ctypes, 'get_last_error', return_value=123, create=True) as error, \
                     self.assertRaisesRegex(AssertionError, message):
                    self.close_windows_descendant(kernel, 102)
                error.assert_called_once_with()
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
            kernel.WaitForSingleObject.restype = ctypes.c_uint32
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

    def test_compiler_environment_uses_the_same_strict_grammar(self):
        for flag in ('/EHnotanoption', '-fp:madeup', '/Zc:notACompilerOption', '/Fooutput.obj'):
            with patch.dict(os.environ, {'CL': flag, '_CL_': ''}):
                with self.subTest(flag=flag), self.assertRaises(ValueError):
                    check.compiler_environment()
        with patch.dict(os.environ, {'CL': '-D WIN32 -fp:precise -FI forced.h', '_CL_': ''}):
            self.assertEqual(check.compiler_environment()['CL'],
                             ['-D', 'WIN32', '-fp:precise', '-FI', 'forced.h'])

    def test_policy_normalizes_dash_options_without_losing_semantics(self):
        args = ['/D', 'WIN32', '/UWIN32', '/DDBVT_TEST=1', '/FI', 'forced.h',
                '/fp:precise', '/fp:fast', '/arch:AVX2', '/std:c++17']
        dashed = ['-' + arg[1:] if arg.startswith('/') else arg for arg in args]
        self.assertEqual(check.policy_flags(dashed), check.policy_flags(args))
        self.assertNotEqual(check.policy_flags(['-fp:precise']), check.policy_flags(['-fp:fast']))
        self.assertEqual(check.policy_flags(['-DWIN32', '-UWIN32', '-FIforced.h']),
                         ['/DWIN32', '/UWIN32', '/FIforced.h'])

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
