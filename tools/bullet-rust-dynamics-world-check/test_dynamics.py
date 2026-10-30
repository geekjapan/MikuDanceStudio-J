import unittest

from cases import corpus
from hooks import MUTANTS
from trace import comparison, validate


class DynamicsControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_evidence import traces
        cls.inputs, cls.cases = corpus()
        cls.raw = traces(cls.inputs, 'ordinary', False)[0]
        cls.rows = validate(cls.raw, cls.inputs)

    def test_complete_inert_protocol_and_no_claim_of_physics_calculation(self):
        self.assertEqual(len(self.rows), len(self.inputs.splitlines()))
        for row, command in zip(self.rows, self.inputs.splitlines()):
            if command.startswith('N '):
                self.assertEqual(len(row['clock']), 4)
                self.assertEqual(sum(event[0] == 'A' for event in row['schedule']), int(row['clock'][1]))
        self.assertTrue(any(row['workspace'] for row in self.rows))

    def test_missing_extra_order_and_global_schedule_indices_refused(self):
        lines = self.raw.splitlines(keepends=True)
        clock = next(line for line in lines if line.startswith(b'K '))
        body = next(line for line in lines if line.startswith(b'W '))
        group = next(line for line in lines if line.startswith(b'Y ') and b' G ' in line)
        workspace = next(line for line in lines if line.startswith(b'V '))
        fields = group.split(); fields[5] = b'100000'
        controls = [self.raw.replace(clock, b'', 1), self.raw.replace(body, b'', 1),
                    self.raw.replace(clock, clock+clock, 1), self.raw.replace(workspace, b'', 1),
                    self.raw.replace(group, b' '.join(fields)+b'\n', 1),
                    self.raw.replace(body, body.replace(b'00000000', b'0000000g', 1), 1)]
        for raw in controls:
            with self.subTest(control=raw[:100]), self.assertRaises(ValueError):
                validate(raw, self.inputs)

    def test_numeric_and_order_witnesses_remain_visible_in_synthetic_receipts(self):
        from evidence import semantic_fields
        from test_evidence import traces
        for name in MUTANTS:
            changed = validate(traces(self.inputs, 'ordinary', False, mutation=name)[0], self.inputs)
            with self.subTest(name=name):
                self.assertNotEqual(comparison(self.rows), comparison(changed))
                self.assertTrue(any(a[field] != b[field] for a, b in zip(self.rows, changed) for field in semantic_fields(name)))

    def test_zero_time_pose_reset_has_motion_and_hash_witness_without_velocity_changes(self):
        from evidence import semantic_fields
        from test_evidence import traces
        from cases import floats
        case = next(case for case in self.cases if case['name'] == 'zero-step-motion-and-forces')
        commands = self.inputs.splitlines()
        reset = case['end'] - 3
        self.assertEqual(commands[reset], 'T 0 ' + floats([0, 10, 0, 0, 0, 0, 1]))
        self.assertEqual(commands[reset+1:case['end']], ['N 00000000 1 3f800000'] * 2)
        mutant = validate(traces(self.inputs, 'ordinary', False, mutation='zero-step-sync')[0], self.inputs)
        fields = semantic_fields('zero-step-sync')
        self.assertEqual(fields, ['bodies', 'result'])
        before, after, repeat = self.rows[reset:reset+3]
        self.assertNotEqual(before['bodies'], after['bodies'])
        self.assertNotEqual(before['result'][1], after['result'][1])
        for field in ['bodies', 'result', 'dynamics']:
            self.assertEqual(after[field], repeat[field])
        self.assertEqual(self.rows[reset-1]['dynamics'], before['dynamics'])
        self.assertEqual(before['dynamics'], after['dynamics'])
        self.assertEqual(after['dynamics'], mutant[reset+1]['dynamics'])
        for row in [before, after, repeat, mutant[reset+1]]:
            state_hash = 1469598103934665603
            for body, dynamics in zip(row['bodies'], row['dynamics']):
                words = body[30:42] + [dynamics[15], dynamics[19], '00000000']
                for word in words:
                    for byte in bytes.fromhex(word)[::-1]:
                        state_hash = ((state_hash ^ byte) * 1099511628211) & ((1 << 64)-1)
            self.assertEqual(row['result'][1], state_hash)
        self.assertTrue(all(after[field] != mutant[reset+1][field] for field in fields))
        w_only = validate(self.raw, self.inputs)
        w_only[reset+1]['dynamics'][0][22] = '3f800000'
        self.assertNotEqual(comparison(self.rows), comparison(w_only))
        self.assertFalse(any(a[field] != b[field] for a, b in zip(self.rows, w_only) for field in fields))


if __name__ == '__main__':
    unittest.main()
