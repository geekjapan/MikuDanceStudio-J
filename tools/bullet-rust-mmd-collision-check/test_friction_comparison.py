"""Pure comparison fixtures, not provider or numerical receipts."""
import unittest

from friction_compare import common_fields, observed_bijection
from friction_trace import Capture


class ComparisonTests(unittest.TestCase):
    def test_rust_original_compares_every_actual_extra_row_and_field(self):
        original = Capture('rust-original', 'ordinary', 'a' * 64)
        observed = Capture('rust-observed', 'ordinary', 'a' * 64)
        rows = [('S', '0', '0', '1', '1', '0'), ('J', '0', '0', '0'),
                ('R', '0', '1'), ('K', '0', '1', '1', '00000000', '00000000'),
                ('Y', '0', 'P', '2', '1'), ('V', '0', '0', '2')]
        original.base = list(rows)
        observed.base = [('E', '0', 'A+', '1'), *rows]
        common_fields(original, observed)
        for index, row in enumerate(rows):
            for field_index in range(2, len(row)):
                changed = list(row)
                changed[field_index] += '1'
                observed.base = [*rows[:index], tuple(changed), *rows[index + 1:]]
                with self.subTest(tag=row[0], field=field_index), self.assertRaises(ValueError):
                    common_fields(original, observed)
            for changed in (rows[:index] + rows[index + 1:], rows[:index] + [row] + rows[index:]):
                observed.base = changed
                with self.subTest(tag=row[0], length=len(changed)), self.assertRaisesRegex(ValueError, 'row lengths'):
                    common_fields(original, observed)

    def test_fixture_boundaries_and_every_write_are_compared(self):
        n = Capture('native-observed', 'ordinary', 'a' * 64)
        r = Capture('rust-observed', 'ordinary', 'a' * 64)
        n.history = r.history = [(0, 'FF', 'FIXTURE_BEGIN', ()), (0, 'FF', 'FIXTURE_END', ())]
        observed_bijection(n, r)
        for changed in (r.history[:1], r.history * 2, r.history[::-1]):
            r.history = changed
            with self.assertRaises(ValueError):
                observed_bijection(n, r)

    def test_all_generation_events_bind_independent_local_ids(self):
        n = Capture('native-observed', 'ordinary', 'a' * 64)
        r = Capture('rust-observed', 'ordinary', 'a' * 64)
        n.history = [(0, 'FM', 'ALLOC', (1, 0, 1)), (0, 'FC', 'CTOR_GEOMETRIC', (1,)),
                     (0, 'FI', 'ADD', (1, 0, 0, 1, 2, 0)), (1, 'FX', 'REMOVE', (1, 0, 2)),
                     (1, 'FM', 'RELEASE', (1, 0, 1))]
        r.history = [(0, 'FM', 'ALLOC', (91, 0, 1)), (0, 'FC', 'RUST_CONTACT_CREATE', (72,)),
                     (0, 'FI', 'ADD', (91, 0, 0, 72, 88, 0)), (1, 'FX', 'REMOVE', (91, 0, 88)),
                     (1, 'FM', 'RELEASE', (91, 0, 1))]
        n.bindings = {(0, 0, 0): (1, 2)}
        r.bindings = {(0, 0, 0): (91, 88)}
        maps = observed_bijection(n, r)
        self.assertEqual(maps['mid'], {1: 91})
        self.assertEqual(maps['gid'], {1: 72, 2: 88})
        r.bindings[(0, 0, 0)] = (91, 72)
        with self.assertRaisesRegex(ValueError, 'logical generations commute'):
            observed_bijection(n, r)

    def test_observed_nonidentity_rows_are_not_projected_away(self):
        n = Capture('native-observed', 'ordinary', 'a' * 64)
        r = Capture('rust-observed', 'ordinary', 'a' * 64)
        n.base = [('S', '0', '0', '2', '0', '0', '1', '1')]
        r.base = list(n.base)
        maps = dict(mid={}, gid={}, tx={}, alg={})
        common_fields(n, r, observed_maps=maps)
        r.base = [('S', '0', '0', '2', '0', '0', '2', '1')]
        with self.assertRaisesRegex(ValueError, 'complete common field'):
            common_fields(n, r, observed_maps=maps)

    def test_refresh_maps_every_identity_sentinel_branch_and_visit(self):
        n = Capture('native-observed', 'ordinary', 'a' * 64)
        r = Capture('rust-observed', 'ordinary', 'a' * 64)
        n.history = [(0, 'FM', 'ALLOC', (1, 0, 1)), (0, 'FC', 'CTOR_GEOMETRIC', (1,)),
                     (0, 'FI', 'ADD', (1, 0, 0, 1, 2, 0)),
                     (0, 'FR', 'REFRESH_BEGIN', (1, 0, 0, False, False)),
                     (0, 'FR', 'REFRESH_POINT', (1, 0, 2, False, True)),
                     (0, 'FX', 'REMOVE', (1, 0, 2)),
                     (0, 'FR', 'REFRESH_END', (1, 0, 0, False, False))]
        r.history = [(0, 'FM', 'ALLOC', (91, 0, 1)), (0, 'FC', 'RUST_CONTACT_CREATE', (72,)),
                     (0, 'FI', 'ADD', (91, 0, 0, 72, 88, 0)),
                     (0, 'FR', 'REFRESH_BEGIN', (91, 0, 0, False, False)),
                     (0, 'FR', 'REFRESH_POINT', (91, 0, 88, False, True)),
                     (0, 'FX', 'REMOVE', (91, 0, 88)),
                     (0, 'FR', 'REFRESH_END', (91, 0, 0, False, False))]
        observed_bijection(n, r)
        original = list(r.history)
        for index, values in ((3, (91, 0, 88, False, False)),
                              (4, (1, 0, 88, False, True)), (4, (91, 1, 88, False, True)),
                              (4, (91, 0, 72, False, True)), (4, (91, 0, 88, True, False)),
                              (4, (91, 0, 88, False, False)), (6, (91, 0, 0, False, True))):
            r.history = list(original)
            r.history[index] = (*r.history[index][:3], values)
            with self.subTest(index=index, values=values), self.assertRaisesRegex(ValueError, 'logical obligation correspondence'):
                observed_bijection(n, r)


if __name__ == '__main__':
    unittest.main()
