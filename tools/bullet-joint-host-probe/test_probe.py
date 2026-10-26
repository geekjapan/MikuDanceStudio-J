import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('probe', Path(__file__).with_name('probe.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_adapter_keeps_properties_and_only_removes_bit_comparison(self):
        original = probe.JOINT.read_text()
        adapted = probe.joint_adapter(original)
        self.assertNotIn('assert_eq!(a, b, "case {id} word', adapted)
        self.assertIn('assert_eq!(actual.len(), expected.len()', adapted)
        self.assertEqual(original.count('assert'), adapted.count('assert') + 1)
        self.assertIn('input[..input.len() - expected.len()].iter().chain(&actual)', adapted)
        with self.assertRaises(ValueError):
            probe.joint_adapter(original.replace('native {b:08x}', 'changed'))

    def test_frozen_failures_are_observed_and_no_record_is_added(self):
        source = probe.check_adapter(probe.CHECK.read_text(), Path('/tmp/harness.rs'))
        self.assertNotIn("raise SystemExit('Native", source)
        self.assertEqual(source.count('FAIL diagnostic frozen comparison:'), 2)
        self.assertNotIn('Native fixture and pure Rust agree', source)

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

    def test_capture_completeness(self):
        self.assertEqual(probe.counts(probe.FIXTURE), {'cases': 518, 'simd_events': 20580})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'short.tsv'
            path.write_text(probe.FIXTURE.read_text().splitlines()[0] + '\n')
            with self.assertRaises(ValueError):
                probe.counts(path)


if __name__ == '__main__':
    unittest.main()
