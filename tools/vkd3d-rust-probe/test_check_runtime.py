"""Runtime setup checks do not claim Linux translation or ABI acceptance."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import check_runtime


class RuntimeTests(unittest.TestCase):
    def output(self, command):
        if command[0] == '/usr/bin/clang-18':
            return 'Ubuntu clang version 18.1.3 (1ubuntu1)\nTarget: x86_64\n'
        if command[0] == '/usr/bin/llvm-config-18':
            return '18.1.3\n'
        if command[0] == 'rustc':
            return 'rustc 1.95.0 (test)\n'
        if command[0] == 'dpkg-query':
            return 'clang-18\t1:18.1.3-1ubuntu1\n'
        if command == ['ldd', '--version']:
            return 'ldd (Ubuntu GLIBC 2.39-0ubuntu8.6) 2.39\n'
        if command[0] == 'ldd':
            return 'libclang-cpp.so.18.1 => /lib/libclang-cpp.so.18.1 (0x123)\n'
        return 'C2Rust 0.22.1\n'

    def test_matching_runtime_records_and_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            tool = Path(directory)
            with patch.object(check_runtime, 'output', side_effect=self.output):
                check_runtime.check(tool, record=True)
                check_runtime.check(tool)
            self.assertEqual(json.loads((tool / 'runtime.json').read_text())['llvm'], '18.1.3')

    def test_missing_library_stops_before_manifest(self):
        for binary in ('c2rust', 'c2rust-transpile'):
            with self.subTest(binary=binary), tempfile.TemporaryDirectory() as directory:
                tool = Path(directory)

                def output(command):
                    if command[0] == 'ldd' and Path(command[1]).name == binary:
                        return 'libLLVM.so.18.1 => not found\n'
                    return self.output(command)

                with patch.object(check_runtime, 'output', side_effect=output):
                    with self.assertRaisesRegex(RuntimeError, 'unresolved runtime dependency'):
                        check_runtime.check(tool, record=True)
                self.assertFalse((tool / 'runtime.json').exists())

    def test_command_failure_is_not_accepted(self):
        with patch('check_runtime.subprocess.run', side_effect=subprocess.CalledProcessError(1, ['ldd'])):
            with self.assertRaises(subprocess.CalledProcessError):
                check_runtime.output(['ldd', 'missing'])

    def test_missing_manifest_or_mismatched_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            tool = Path(directory)
            with patch.object(check_runtime, 'output', side_effect=self.output):
                with self.assertRaises(FileNotFoundError):
                    check_runtime.check(tool)
                check_runtime.check(tool, record=True)
                versions = json.loads((tool / 'runtime.json').read_text())
                versions['packages'] += 'different-version\n'
                (tool / 'runtime.json').write_text(json.dumps(versions))
                with self.assertRaisesRegex(RuntimeError, 'versions differ'):
                    check_runtime.check(tool)

    def test_wrong_compiler_version_is_rejected(self):
        for executable, version in (('/usr/bin/clang-18', 'clang version 19.1.3'),
                                    ('/usr/bin/llvm-config-18', '19.1.3'),
                                    ('rustc', 'rustc 1.94.0 (test)')):
            with self.subTest(executable=executable):
                def output(command):
                    return version if command[0] == executable else self.output(command)

                with patch.object(check_runtime, 'output', side_effect=output):
                    with self.assertRaisesRegex(RuntimeError, 'Clang/LLVM 18'):
                        check_runtime.check(Path('/unused'), record=True)


if __name__ == '__main__':
    unittest.main()
