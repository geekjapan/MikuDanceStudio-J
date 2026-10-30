"""Small inert helper tests. Hosted suites do not substitute for actual capture."""
import unittest
import struct

from cases import corpus, word
from hooks import MUTANTS, OWNER, inverse, mutate, replace
from trace import frames


class Memory:
    def __init__(self, files, name=''):
        self.files, self.name = files, name
    def __truediv__(self, name):
        return Memory(self.files, self.name + ('/' if self.name else '') + str(name))
    def read_bytes(self):
        return self.files[self.name]
    def write_bytes(self, raw):
        self.files[self.name] = raw


class CorpusTests(unittest.TestCase):
    def test_source_derived_case_families_and_unique_names(self):
        inputs, cases = corpus()
        self.assertLessEqual(len(inputs.encode()), 64 * 1024)
        families = {'constructor': 1, 'ordered-shapes': 9, 'floor': 6, 'signed-filter': 8,
                    'mode': 9, 'motion': 3, 'joint': 6, 'huge-aabb': 12, 'multiway': 1}
        self.assertEqual({family: sum(c['family'] == family for c in cases) for family in families}, families)
        self.assertEqual(len(cases), sum(families.values()))
        self.assertEqual(len({c['name'] for c in cases}), len(cases))
        commands = inputs.splitlines()
        for case in cases:
            self.assertEqual(commands[case['start']].split()[1], case['name'])
            self.assertEqual(commands[case['end']], 'X')
        self.assertEqual(cases[0]['start'], 0)
        self.assertEqual(cases[-1]['end'], len(commands) - 1)
        self.assertTrue(all(b['start'] == a['end'] + 1 for a, b in zip(cases, cases[1:])))

    def test_huge_boxes_keep_one_edge_unsaturated_and_use_reachable_flags(self):
        inputs, cases = corpus()
        lines = inputs.splitlines()
        for case in cases:
            if case['family'] != 'huge-aabb':
                continue
            body = lines[case['start'] + 1].split()
            self.assertEqual(body[6], body[10])
            flags = int(case['name'].split('-')[-1])
            self.assertEqual(body[3], '0' if flags & 1 else '1')
            self.assertEqual(lines[case['start'] + 2], f'K 1 {int(bool(flags & 2))}')

    def test_words_preserve_negative_zero(self):
        self.assertEqual(word(-0.0), '80000000')
        self.assertNotEqual(word(-0.0), word(0.0))

    def test_stop_at_has_its_own_nonzero_interpolation_marker(self):
        inputs, cases = corpus()
        lines = inputs.splitlines()
        for case in cases:
            if case['family'] != 'motion':
                continue
            operations = lines[case['start']:case['end']]
            stop = next(i for i, command in enumerate(operations) if command.startswith('O '))
            self.assertTrue(operations[stop - 1].startswith('V 1 '))
            self.assertNotIn('00000000', operations[stop - 1].split()[2:])

    def test_translated_huge_boundary_uses_float32_operations(self):
        f32 = lambda value: struct.unpack('<f', struct.pack('<f', value))[0]
        inputs, cases = corpus()
        lines = inputs.splitlines()
        for case in cases:
            if case['family'] != 'huge-aabb':
                continue
            words = lines[case['start'] + 1].split()
            extent = struct.unpack('<f', bytes.fromhex(words[6])[::-1])[0]
            half = f32(f32(extent - f32(.04)) + f32(.04))
            lo = f32(f32(extent - half) - f32(.02))
            hi = f32(f32(extent + half) + f32(.02))
            width = f32(hi - lo)
            side = f32(f32(1.0 + f32(.02)) - f32(-1.0 - f32(.02)))
            diagonal = f32(f32(f32(width * width) + f32(side * side)) + f32(side * side))
            expected = case['name'].split('-')[1]
            self.assertEqual('below' if diagonal < f32(1e12) else 'above' if diagonal > f32(1e12) else 'equal', expected)
            self.assertGreaterEqual(lo, -10000.0)

    def test_exact_hook_inverse_for_both_transports(self):
        for ending in (b'\n', b'\r\n'):
            original = b'one' + ending + b'two' + ending
            memory = Memory({'source': original})
            edits = []
            replace(memory, 'source', 'one\ntwo', 'one\nobserved\ntwo', edits)
            inverse(memory, edits, {'source': original})
            self.assertNotEqual(memory.files['source'], original)
            memory.files['source'] += b'changed'
            with self.assertRaises(ValueError):
                inverse(memory, edits, {'source': original})

    def test_each_mutant_is_an_exact_single_reversible_edit(self):
        for name, (path, old, new, field) in MUTANTS.items():
            self.assertTrue(field)
            self.assertNotEqual(old, new)
            memory = Memory({path: old.encode()})
            edits = mutate(memory, name)
            self.assertEqual(len(edits), 1)
            self.assertEqual(memory.files[path], new.encode())
            inverse(memory, edits, {path: old.encode()})

    def test_empty_trace_is_framed_without_claiming_actual_capture(self):
        commands = 'H empty genuine\nX\n'
        raw = b'O 0 H 0 0 0\nO 1 X 0 0 0\nZ 2\n'
        self.assertEqual(len(frames(raw, commands)), 2)
        for changed in (raw[:-4], raw + b'Z 2\n', raw.replace(b'O 1', b'O 2'), raw.replace(b'Z 2', b'Z 1')):
            with self.assertRaises(ValueError):
                frames(changed, commands)


if __name__ == '__main__':
    unittest.main()
