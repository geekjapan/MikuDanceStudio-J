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
                    path.write_text('#!/bin/sh\n' + body + '\n')
                    path.chmod(0o755)
                # The recipe needs installed license/header files only after a successful make.
                script_path = root / 'recipe.sh'
                script_path.write_text(script + '''
mkdir -p "$dl" "$here/patches"
touch "$here/patches/test.patch"
build_in "$root/work-test" "$root/prefix-test"
''')
                # Use a failing make to exercise EXIT before normal installation paths.
                env = {**os.environ, 'PATH': str(helpers) + os.pathsep + os.environ['PATH'],
                       'MDS_VKD3D_OUT': str(root / 'out'), 'MDS_VKD3D_RECORD_DIR': str(root / 'record'),
                       'COMMANDS': str(root / 'commands'), 'FAIL_MAKE': '17' if failure else '0'}
                completed = subprocess.run(['bash', str(script_path)], env=env, capture_output=True)
                record = root / 'record'
                self.assertTrue((record / 'work/make.log').is_file(), completed.stderr)
                self.assertTrue((record / 'configure-argv.nul').is_file(), completed.stderr)
                self.assertTrue((record / 'compiler-sha256.txt').is_file(), completed.stderr)
                self.assertTrue(all(line.startswith('V=1 ') for line in (root / 'commands').read_text().splitlines()))
                self.assertEqual((record / 'build-exit-code').read_text().strip(), '1' if failure else '0')
                self.assertEqual(completed.returncode, 1 if failure else 0, completed.stderr)


if __name__ == '__main__':
    unittest.main()
