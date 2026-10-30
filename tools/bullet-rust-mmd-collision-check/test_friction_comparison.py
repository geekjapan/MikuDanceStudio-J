"""Pure comparison fixtures, not provider or numerical receipts."""
import unittest

from friction_compare import common_fields, observed_bijection
from friction_trace import Capture


class ComparisonTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
