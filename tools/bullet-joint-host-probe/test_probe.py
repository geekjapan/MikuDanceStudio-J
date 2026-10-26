import importlib.util
from pathlib import Path
import tempfile
import json
import os
import subprocess
import sys
from unittest import mock
import unittest

spec = importlib.util.spec_from_file_location('probe', Path(__file__).with_name('probe.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_adapter_keeps_properties_and_only_removes_bit_comparison(self):
        original = probe.JOINT.read_text()
        adapted = probe.joint_adapter(original, Path('/tmp/native.tsv'))
        self.assertNotIn('assert_eq!(a, b, "case {id} word', adapted)
        self.assertIn('assert_eq!(actual.len(), expected.len()', adapted)
        self.assertEqual(original.count('assert'), adapted.count('assert') + 1)
        self.assertIn('input[..input.len() - expected.len()].iter().chain(&actual)', adapted)
        loop = '''        for (index, (a, b)) in actual.iter().zip(&expected).enumerate() {
            assert_eq!(a, b, "case {id} word {index}: Rust {a:08x}, native {b:08x}");
        }'''
        for anchor in ['include_str!("../solver_data/native.tsv")', loop]:
            for changed in [original.replace(anchor, ''), original + '\n' + anchor]:
                with self.assertRaises(ValueError):
                    probe.joint_adapter(changed, Path('/tmp/native.tsv'))
        with self.assertRaises(ValueError):
            probe.joint_adapter(original.replace('native {b:08x}', 'changed'), Path('/tmp/native.tsv'))

    def test_frozen_failures_are_observed_and_no_record_is_added(self):
        source = probe.check_adapter(probe.CHECK.read_text(), Path('/tmp/harness.rs'))
        self.assertNotIn("raise SystemExit('Native", source)
        self.assertEqual(source.count('FAIL diagnostic frozen comparison:'), 2)
        self.assertNotIn('Native fixture and pure Rust agree', source)
        self.assertEqual(source.count('capture_output('), 2)
        anchor = 'subprocess.check_output([executable], env=environment)'
        for changed in [probe.CHECK.read_text().replace(anchor, ''), probe.CHECK.read_text() + anchor]:
            with self.assertRaises(ValueError):
                probe.check_adapter(changed, Path('/tmp/harness.rs'))

    def test_exact_differences_include_nan_sign_zero_finite_and_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            left, right, report = [Path(directory) / name for name in ['a', 'b', 'diff']]
            left.write_text('0\t7fc00000\t00000000\t3f800000\n')
            right.write_text('0\tffc00000\t80000000\t40000000\t00000000\n')
            result = probe.compare(left, right, report)
            self.assertEqual(result['mismatches'], 4)
            self.assertEqual(result['categories'], {'nan/nan': 1, 'zero/zero': 1,
                                                    'finite/finite': 1, 'structure/zero': 1})
            self.assertIn('7fc00000\tffc00000', report.read_text())
            self.assertEqual(probe.compare(left, left, report)['status'], 'PASS')

    def test_msvc_profiles_keep_real_intrinsics_and_native_link_libraries(self):
        original = ['clang++', '-I', '/shim/sse_emu', '/src/oracle.cpp', '/src/body.cpp']
        for profile in ['msvc-ffi-default', 'msvc-cmake-win32']:
            command = probe.msvc_command(original, profile, Path('/out'), ['kernel32.lib'])
            self.assertEqual(command[0], 'cl')
            self.assertEqual('/DWIN32' in command, profile == 'msvc-cmake-win32')
            for flag in ['/O2', '/MD', '/fp:precise', '/EHsc', '/W0', '/DBT_NO_PROFILE=1']:
                self.assertIn(flag, command)
            self.assertIn('/src/oracle.cpp', command)
            self.assertIn('/out/libmds_crtmath.a', command)
            self.assertIn('kernel32.lib', command)
            self.assertNotIn('/shim/sse_emu', command)
            self.assertTrue(any(arg.startswith('/FI') and arg.endswith('det_math.h') for arg in command))

    def test_compiler_failure_finalizes_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'capture'
            command = [sys.executable, str(Path(probe.__file__)), '--profile',
                       'msvc-ffi-default' if os.name == 'nt' else 'clang-helper',
                       '--out-dir', str(out)]
            env = dict(os.environ)
            original = probe.capture_command
            def capture(path, label, args, **kwargs):
                if label == 'compiler':
                    args = [sys.executable, '-c', 'import sys; sys.stdout.buffer.write(b"compiler partial"); sys.stderr.write("compiler failed"); sys.exit(1)']
                return original(path, label, args, **kwargs)
            with mock.patch.object(sys, 'argv', command[1:]), mock.patch.object(probe, 'capture_command', capture):
                with self.assertRaises(subprocess.CalledProcessError) as error:
                    probe.main()
            self.assertEqual(error.exception.returncode, 1)
            self.assertEqual((out / 'compiler.stdout').read_bytes(), b'compiler partial')
            self.assertEqual((out / 'compiler.stderr').read_bytes(), b'compiler failed')
            status = json.loads((out / 'status.json').read_text())
            self.assertEqual(status['execution'], 'FAIL')
            self.assertEqual(status['phase'], 'compiler')
            self.assertEqual(status['returncode'], 1)
            self.assertIn('CalledProcessError', status['error'])
            hashes = json.loads((out / 'sha256.json').read_text())
            self.assertIn('status.json', hashes)
            self.assertIn('compiler.stderr', hashes)
            sentinel = out / 'keep'
            sentinel.write_bytes(b'untouched')
            before = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}
            subprocess.run(command, env=env, capture_output=True)
            self.assertEqual(before, {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()})

    def test_native_failure_keeps_partial_bytes_and_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'capture'
            command = [sys.executable, '-c',
                       'import sys; sys.stdout.buffer.write(b"partial\\x00\\xff"); '
                       'sys.stderr.buffer.write(b"native error\\xfe"); sys.exit(99)']
            def failed_check(source, harness):
                return 'def main():\n    capture_output(' + repr(command) + ', "oracle")\n'
            with mock.patch.object(sys, 'argv', ['probe', '--profile',
                    'msvc-ffi-default' if os.name == 'nt' else 'clang-helper', '--out-dir', str(out)]), \
                    mock.patch.object(probe, 'check_adapter', failed_check):
                # Metadata still uses real subprocesses; bypass it with a successful compiler.
                with mock.patch.dict(os.environ, {'CXX': sys.executable}):
                    original = probe.capture_command
                    def capture(path, label, args, **kwargs):
                        if label == 'compiler':
                            args = [sys.executable, '--version']
                        return original(path, label, args, **kwargs)
                    with mock.patch.object(probe, 'capture_command', capture):
                        with self.assertRaises(subprocess.CalledProcessError) as error:
                            probe.main()
            self.assertEqual(error.exception.returncode, 99)
            self.assertEqual(error.exception.output, b'partial\x00\xff')
            self.assertEqual((out / 'oracle.tsv').read_bytes(), b'partial\x00\xff')
            self.assertEqual((out / 'oracle.stderr').read_bytes(), b'native error\xfe')
            self.assertEqual(json.loads((out / 'oracle.status.json').read_text())['returncode'], 99)
            status = json.loads((out / 'status.json').read_text())
            self.assertEqual(status['returncode'], 99)
            self.assertEqual(status['phase'], 'oracle')
            self.assertIn('oracle.tsv', json.loads((out / 'sha256.json').read_text()))

    def test_rust_adapter_compiles_actual_capture_instead_of_frozen_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            native = out / 'native.tsv'
            fields = probe.FIXTURE.read_text().splitlines()[0].split('\t')
            fields[1] = '3d000001'
            native.write_text('\t'.join(fields) + '\n')
            adapter = probe.joint_adapter(probe.JOINT.read_text(), native)
            include = next(line.strip() for line in adapter.splitlines() if 'for line in include_str!' in line)
            source = out / 'input.rs'
            source.write_text('fn main() {\n' + include + '\n'
                              'let fields: Vec<_> = line.split(\'\\t\').collect();\n'
                              'assert_eq!(fields[1], "3d000001");\n'
                              'print!("{}", fields[1]); break; } }\n')
            executable = out / ('input.exe' if os.name == 'nt' else 'input')
            subprocess.run(['rustup', 'run', '1.95.0', 'rustc', str(source), '-o', str(executable)],
                           cwd=probe.ROOT / 'rust', check=True, capture_output=True)
            self.assertEqual(subprocess.check_output([executable]), b'3d000001')
            self.assertNotIn(str(probe.FIXTURE), adapter)

    def test_setup_failure_finalizes_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'capture'
            with mock.patch.object(sys, 'argv', ['probe', '--profile',
                    'msvc-ffi-default' if os.name == 'nt' else 'clang-helper', '--out-dir', str(out)]), \
                    mock.patch.object(probe, 'joint_adapter', side_effect=ValueError('changed anchor')):
                with self.assertRaisesRegex(ValueError, 'changed anchor'):
                    probe.main()
            self.assertEqual(json.loads((out / 'status.json').read_text())['phase'], 'setup')
            self.assertIn('status.json', json.loads((out / 'sha256.json').read_text()))

    def test_input_invariant_failure_is_not_successful_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'capture'
            def changed_check(source, harness):
                return ('from pathlib import Path\ndef main():\n'
                        '    source = Path(' + repr(str(probe.FIXTURE)) + ').read_text()\n'
                        '    Path(' + repr(str(out / 'native.tsv')) + ').write_text(source)\n'
                        '    lines = source.splitlines()\n'
                        '    fields = lines[0].split("\\t")\n'
                        '    fields[1] = "3d000001"\n'
                        '    lines[0] = "\\t".join(fields)\n'
                        '    Path(' + repr(str(out / 'rust.tsv')) + ').write_text("\\n".join(lines) + "\\n")\n')
            original = probe.capture_command
            def capture(path, label, args, **kwargs):
                if label == 'compiler':
                    args = [sys.executable, '--version']
                return original(path, label, args, **kwargs)
            with mock.patch.object(sys, 'argv', ['probe', '--profile',
                    'msvc-ffi-default' if os.name == 'nt' else 'clang-helper', '--out-dir', str(out)]), \
                    mock.patch.object(probe, 'capture_command', capture), \
                    mock.patch.object(probe, 'check_adapter', changed_check):
                with self.assertRaisesRegex(ValueError, 'same-host input invariant failed'):
                    probe.main()
            status = json.loads((out / 'status.json').read_text())
            self.assertEqual(status['execution'], 'FAIL')
            self.assertFalse(status['rust-vs-native']['input_equal'])
            self.assertEqual(status['native'], {'cases': 518, 'simd_events': 20580})
            self.assertIn('status.json', json.loads((out / 'sha256.json').read_text()))

    def test_input_fingerprints_classify_unequal_corpus(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = [Path(directory) / name for name in ['native', 'rust']]
            line = probe.FIXTURE.read_text().splitlines()[0]
            a.write_text(line + '\n')
            fields = line.split('\t')
            fields[1] = '3d000001' if fields[1] != '3d000001' else '3d000002'
            b.write_text('\t'.join(fields) + '\n')
            result = probe.compare(a, b, Path(directory) / 'diff', joint=True)
            self.assertFalse(result['input_equal'])
            self.assertNotEqual(result['left_inputs']['sha256'], result['right_inputs']['sha256'])
            self.assertEqual(result['attribution'], 'input inequality; output attribution unavailable')

    def test_capture_completeness(self):
        self.assertEqual(probe.counts(probe.FIXTURE), {'cases': 518, 'simd_events': 20580})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'short.tsv'
            path.write_text(probe.FIXTURE.read_text().splitlines()[0] + '\n')
            with self.assertRaises(ValueError):
                probe.counts(path)


if __name__ == '__main__':
    unittest.main()
