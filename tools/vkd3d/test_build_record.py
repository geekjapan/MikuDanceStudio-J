"""Exercise build recording with tiny recipe stand-ins, without Docker or vkd3d."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class BuildRecordTest(unittest.TestCase):
    def test_record_directory_must_be_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'existing').write_text('preserve')
            completed = subprocess.run(['bash', str(Path(__file__).with_name('build.sh')), 'windows'],
                env={**os.environ, 'MDS_VKD3D_RECORD_DIR': str(root)}, capture_output=True)
            self.assertEqual(completed.returncode, 2)
            self.assertEqual((root / 'existing').read_text(), 'preserve')

    def test_success_and_failure_retain_actual_work(self):
        script = Path(__file__).with_name('build.sh').read_text().split('if [ "${1:-}" = "--inside" ]; then')[0]
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                helpers = root / 'bin'
                helpers.mkdir()
                for name, body in {
                    'tar': 'while [ "$1" != -C ]; do shift; done; mkdir -p "$2/vkd3d-2.1/include"; touch "$2/vkd3d-2.1/include/test.h" "$2/vkd3d-2.1/include/vkd3d_shader.h" "$2/vkd3d-2.1/include/vkd3d_types.h" "$2/vkd3d-2.1/LICENSE" "$2/vkd3d-2.1/COPYING" "$2/vkd3d-2.1/AUTHORS"; printf "#!/bin/sh\\nprintf \'CC = cc\\\\n\' > Makefile\\n" > "$2/vkd3d-2.1/configure"; chmod +x "$2/vkd3d-2.1/configure"',
                    'cc': 'if [ "$1" = -print-prog-name=cc1 ]; then echo /usr/bin/true; else echo stand-in; fi',
                    'make': '[ "$1" != --version ] || { echo stand-in; exit 0; }; printf "%s\\n" "$*" >> "$COMMANDS"; exit "$FAIL_MAKE"',
                    'patch': 'exit 0', 'bison': 'echo stand-in', 'flex': 'echo stand-in',
                }.items():
                    path = helpers / name
                    body = body.replace('$COMMANDS', str(root / 'commands')).replace('$FAIL_MAKE', '17' if failure else '0')
                    path.write_text('#!/bin/sh\n' + body + '\n')
                    path.chmod(0o755)
                # The recipe needs installed license/header files only after a successful make.
                script_path = root / 'build.sh'
                script_path.write_text(script + '''
mkdir -p "$dl" "$here/patches"
touch "$here/patches/test.patch" "$dl/vkd3d-2.1.tar.xz" "$dl/vulkan-headers.tar.gz" "$dl/spirv-headers.tar.gz"
build_in "$root/work-test" "$root/prefix-test"
''')
                # Use a failing make to exercise EXIT before normal installation paths.
                env = {**os.environ, 'PATH': str(helpers) + os.pathsep + os.environ['PATH'],
                       'MDS_VKD3D_OUT': str(root / 'out'), 'MDS_VKD3D_RECORD_DIR': str(root / 'record'),
                       'COMMANDS': str(root / 'commands'), 'FAIL_MAKE': '17' if failure else '0'}
                completed = subprocess.run(['bash', str(script_path), 'linux-native'], env=env, capture_output=True)
                record = root / 'record'
                self.assertTrue((record / 'work/make.log').is_file(), completed.stderr)
                self.assertTrue((record / 'configure-argv.nul').is_file(), completed.stderr)
                self.assertTrue((record / 'compiler-sha256.txt').is_file(), completed.stderr)
                self.assertTrue(all(line.startswith('-f ') and ' V=1 ' in line for line in (root / 'commands').read_text().splitlines()))
                self.assertEqual((record / 'build-exit-code').read_text().strip(), '1' if failure else '0', completed.stderr)
                self.assertEqual(completed.returncode, 1 if failure else 0, completed.stderr)
                receipt = __import__('json').loads((record / 'producer-receipt.json').read_text())
                self.assertEqual(receipt['status'], 'failure' if failure else 'success')
                self.assertEqual([item['stage'] for item in receipt['stages']],
                                 ['prepared', 'configured'] if failure else
                                 ['prepared', 'configured', 'frozen', 'compiled', 'installed'])

    def test_producer_rejects_changes_after_freeze(self):
        script = Path(__file__).with_name('build.sh')
        python = script.read_text().split("<<'PRODUCER_PY'\n", 1)[1].split('\nPRODUCER_PY', 1)[0]
        for name in ('include/config.h', 'libtool', 'libs/vkd3d-shader/hlsl.tab.c'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                work, record, dl, here = (root / name for name in ('work', 'record', 'dl', 'here'))
                for path in (record, dl, here / 'patches', work / 'hdr/include', work / 'spv/include'):
                    path.mkdir(parents=True)
                (here / 'build.sh').write_bytes(script.read_bytes())
                for archive in ('vkd3d-2.1.tar.xz', 'vulkan-headers.tar.gz', 'spirv-headers.tar.gz'):
                    (dl / archive).write_text('synthetic snapshot fixture')
                target = work / 'vkd3d-2.1' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('before')
                def stage(value):
                    return subprocess.run([__import__('sys').executable, '-', str(record), str(work),
                                           str(here), str(dl), value, ''], input=python.encode(), capture_output=True)
                for value in ('prepared', 'configured', 'frozen'):
                    completed = stage(value)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                target.write_text('after')
                completed = stage('compiled')
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(b'frozen producer input changed', completed.stderr)
                receipt = __import__('json').loads((record / 'producer-receipt.json').read_text())
                self.assertEqual(receipt['status'], 'failure')
                self.assertEqual(len(receipt['stages']), 3)

    def test_ambient_injection_rejected_before_tools(self):
        for name in ('MAKEFILES', 'MAKEFLAGS', 'GNUMAKEFLAGS', 'MFLAGS', 'CPPFLAGS', 'CFLAGS',
                     'CPATH', 'C_INCLUDE_PATH', 'COMPILER_PATH', 'GCC_EXEC_PREFIX', 'AR', 'FLEX', 'CONFIG_SITE', 'CONFIG_SHELL', 'PKG_CONFIG_PATH'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                record = Path(directory) / 'record'
                completed = subprocess.run(['bash', str(Path(__file__).with_name('build.sh')), 'windows'],
                    env={**os.environ, 'MDS_VKD3D_RECORD_DIR': str(record), name: 'injected'}, capture_output=True)
                self.assertEqual(completed.returncode, 2)
                self.assertIn(name.encode(), completed.stderr)
                self.assertEqual((record / 'build-exit-code').read_text().strip(), '2')

    def test_explicit_makefile_and_disabled_dependency_include(self):
        # A real make sentinel, with no compiler or project build.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('GNUmakefile', 'makefile', 'extra.mk'):
                (root / name).write_text('$(error injected ' + name + ')\n')
            (root / '.deps').mkdir()
            (root / '.deps/input.Plo').write_text('$(error injected dependency)\n')
            (root / 'Makefile').write_text('#include .deps/input.Plo\nall:\n\t@echo frozen\n')
            environment = {key: value for key, value in os.environ.items()
                           if key not in ('MAKEFILES', 'MAKEFLAGS', 'GNUMAKEFLAGS', 'MFLAGS')}
            completed = subprocess.run(['make', '-f', str(root / 'Makefile')], cwd=root,
                                       env=environment, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), 'frozen')
            injected = subprocess.run(['make', '-f', str(root / 'Makefile')], cwd=root,
                env={**environment, 'MAKEFILES': str(root / 'extra.mk')}, capture_output=True)
            self.assertNotEqual(injected.returncode, 0)


if __name__ == '__main__':
    unittest.main()
