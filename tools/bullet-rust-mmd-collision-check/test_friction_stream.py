"""Pure bounded stream fixtures. These are not native or numerical receipts."""
import hashlib
import unittest

from friction_trace import Capture, compare_defined, compare_physical, parse


class StreamTests(unittest.TestCase):
    inputs = 'H synthetic fixture-injection\nX\n'

    def stream(self, variant='native-original'):
        sha = hashlib.sha256(self.inputs.encode()).hexdigest()
        body = 'O 0 H 0 0 0\nO 1 X 0 0 0\nZ 2\n'
        return (f'FH 3 {variant} ordinary {sha} 2\n' + body + 'FZ 0 2 0\n').encode(), sha

    def test_original_has_no_fabricated_ledger(self):
        raw, sha = self.stream()
        capture = parse(raw, self.inputs, variant='native-original', role='ordinary', corpus_sha=sha)
        self.assertEqual(capture.closed, 0)
        self.assertEqual(capture.history, [])

    def test_original_rejects_fabricated_guard(self):
        raw, sha = self.stream()
        raw = raw.replace(b'O 0 H', b'FG 0 1 STARTUP true true true true\nO 0 H')
        with self.assertRaisesRegex(ValueError, 'no fabricated observations'):
            parse(raw, self.inputs, variant='native-original', role='ordinary', corpus_sha=sha)

    def test_footer_identity_and_sequence_are_closed(self):
        raw, sha = self.stream()
        for changed in (raw.replace(b'FZ 0 2 0', b'FZ 1 2 0'), raw + b'O 1 X 0 0 0\n',
                        raw.replace(b'FZ 0 2 0\n', b''), raw.replace(b'ordinary', b'ascending'),
                        raw.replace(b'FZ 0 2 0', b'FZ 0 2 1'), raw.replace(b'Z 2', b'Z 1')):
            with self.subTest(changed=changed[-50:]), self.assertRaises(ValueError):
                parse(changed, self.inputs, variant='native-original', role='ordinary', corpus_sha=sha)

    def test_observed_native_requires_all_command_guards(self):
        raw, sha = self.stream('native-observed')
        with self.assertRaisesRegex(ValueError, 'complete guarded command schedule'):
            parse(raw, self.inputs, variant='native-observed', role='ordinary', corpus_sha=sha)

    def test_physical_unwritten_rust_words_are_still_compared(self):
        original = Capture('rust-original', 'ordinary', 'a' * 64)
        observed = Capture('rust-observed', 'ordinary', 'a' * 64)
        key = (0, 0, 0, 2)
        original.physical[key] = ('00000000',) * 3
        observed.physical[key] = ('80000000', '00000000', '00000000')
        original.directions[key] = ('O', ())
        observed.directions[key] = ('U', ())
        with self.assertRaisesRegex(ValueError, 'physical numerical difference'):
            compare_physical(original, observed)

    def test_defined_comparison_keeps_all_three_words_without_flag(self):
        native = Capture('native-observed', 'ordinary', 'a' * 64)
        rust = Capture('rust-observed', 'ordinary', 'a' * 64)
        key = (0, 0, 0, 2)
        native.directions[key] = ('D', ('00000000', '80000000', '7fc00001'))
        rust.physical[key] = ('00000000', '80000000', '7fc00001')
        compare_defined(native, rust)
        for index in range(3):
            words = list(native.directions[key][1])
            words[index] = '3f800000'
            rust.physical[key] = tuple(words)
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, 'DEFINED numerical difference'):
                compare_defined(native, rust)
        del rust.physical[key]
        with self.assertRaisesRegex(ValueError, 'full ordered'):
            compare_defined(native, rust)


if __name__ == '__main__':
    unittest.main()
