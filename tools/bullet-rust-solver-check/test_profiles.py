"""Run with: python3 -m unittest discover -s tools/bullet-rust-solver-check."""
import unittest

from profiles import compare_capture, fixture_path, verify_profiles


class NativeProfiles(unittest.TestCase):
    def test_frozen_hashes_inputs_and_exact_48_word_difference(self):
        verify_profiles()

    def test_architecture_selection_is_explicit(self):
        for machine in ['aarch64', 'arm64']:
            self.assertEqual(fixture_path(machine).name, 'native.tsv')
        for machine in ['x86_64', 'AMD64']:
            self.assertEqual(fixture_path(machine).name, 'native-x86_64.tsv')
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            fixture_path('riscv64')

    def test_selected_profile_rejects_one_changed_word(self):
        selected = fixture_path()
        captured = selected.read_bytes()
        compare_capture(captured, selected)
        fields = captured.split(b'\t')
        fields[302] = b'000000ff'
        with self.assertRaisesRegex(ValueError, 'differs'):
            compare_capture(b'\t'.join(fields), selected)


if __name__ == '__main__':
    unittest.main()
