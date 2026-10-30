"""Small pure protocol fixtures, never native execution or parity receipts."""
import unittest

from friction_schema import diagnostic, field, tokens, unsigned
from friction_ledger import Ledger


class GrammarTests(unittest.TestCase):
    def test_strict_integer_boolean_and_word_types(self):
        for value in ('00', '+1', '-0', '-1', '1e2', '2147483648', '1' * 100, True, 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                unsigned(value)
        self.assertEqual(unsigned('2147483647'), 2147483647)
        for value in ('0', '1', 'True', True, 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                field(value, 'b')
        self.assertIs(field('false', 'b'), False)
        for value in ('ABCDEF00', '0000000', '000000000', 'NaN'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                field(value, 'w')
        self.assertEqual(field('80000000', 'w'), '80000000')

    def test_closed_sites_fields_and_counts(self):
        valid = 'FD 0 1 SNAPSHOT 0 0 2 D 3 80000000 7fc00001 00000000'.split()
        self.assertEqual(diagnostic(valid)[-1][-3:], ('80000000', '7fc00001', '00000000'))
        for row in (valid + ['0'], valid[:-1], ['FUNKNOWN', *valid[1:]],
                    [*valid[:3], 'UNKNOWN', *valid[4:]],
                    'FD 0 1 SNAPSHOT 0 0 2 U 3 00000000 00000000 00000000'.split(),
                    'FD 0 1 SNAPSHOT 0 0 2 O 1'.split(),
                    'FL 0 1 SNAPSHOT 0 4 1 1 0 false'.split()):
            with self.subTest(row=row), self.assertRaises(ValueError):
                diagnostic(row)

    def test_ascii_and_line_guards(self):
        for raw in (b'', b'FH 3', b'FH  3\n', b' FH 3\n', b'FH 3 \n', b'FH\t3\n',
                    b'FH 3\r\n', b'FH \x00\n', b'FH \xff\n', b'FH 3\vFD 3\n', b'FG ' + b'a' * 510 + b'\n'):
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                list(tokens(raw))

    def test_every_closed_tag_has_a_typed_example(self):
        examples = (
            'FG 0 1 STARTUP true true true true', 'FM 0 1 ALLOC 1 0 1',
            'FC 0 1 CTOR_GEOMETRIC 1', 'FPY 0 1 POINT_COPY 1 2 3',
            'FI 0 1 ADD 1 0 0 1 2 0', 'FX 0 1 TEMP_END 0 0 1',
            'FV 0 1 REMOVE_MOVE 1 3 1 2', 'FB 0 1 SOLVER_BEGIN 1 0 2 1 260 false',
            'FT 0 1 SOLVER_CHOICE 1 0 2 1 true false false',
            'FW 0 1 PLANE_BOTH 1 0 2 1 3', 'FE 0 1 PLANE_ONE 1 0 2 1 3 3 true',
            'FS 0 1 SNAPSHOT 0 1 1', 'FL 0 1 SNAPSHOT 0 0 1 2 3 false',
            'FD 0 1 SNAPSHOT 0 0 1 U 0', 'FP 0 1 RUST_PHYSICAL 0 0 2 00000000 00000000 00000000',
        )
        for example in examples:
            with self.subTest(example=example):
                self.assertEqual(diagnostic(example.split())[2], 1)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(False)
        self.emit('FM', 'ALLOC', 1, 0, 1)

    def emit(self, tag, site, *values):
        self.ledger.event(0, tag, site, values)

    def add(self, temporary=1, new=2, slot=0):
        self.emit('FC', 'RUST_CONTACT_CREATE', temporary)
        self.emit('FI', 'ADD', 1, slot, 0, temporary, new, 0)

    def solve(self, *, transaction=1, velocity=False, valid=3, gid=2, slot=0, flag=False):
        self.emit('FB', 'SOLVER_BEGIN', 1, slot, gid, transaction, 260, flag)
        self.emit('FT', 'SOLVER_CHOICE', 1, slot, gid, transaction, True, velocity, False)
        self.emit('FW', 'VELOCITY_DIR1' if velocity else 'PLANE_BOTH',
                  1, slot, gid, transaction, 1 if velocity else 3)
        self.emit('FE', 'VELOCITY_ONE' if velocity else 'PLANE_ONE',
                  1, slot, gid, transaction, 1 if velocity else 3, valid, True)

    def test_velocity_one_and_plane_one_are_independent(self):
        self.add()
        self.solve(velocity=True, valid=1)
        self.assertEqual(self.ledger.points[2], 1)
        self.solve(transaction=2, flag=True)
        self.assertEqual(self.ledger.points[2], 3)

    def test_later_velocity_retains_dir2(self):
        self.add()
        self.solve()
        self.solve(transaction=2, velocity=True, valid=3, flag=True)
        self.assertEqual(self.ledger.points[2], 3)

    def test_replacement_resets_incoming_unwritten(self):
        self.add()
        self.solve()
        self.emit('FC', 'RUST_CONTACT_CREATE', 3)
        self.emit('FI', 'REPLACE', 1, 0, 2, 3, 4, 0)
        self.assertEqual(self.ledger.points, {4: 0})
        self.assertEqual(self.ledger.closed, 3)

    def test_copy_inherits_actual_validity(self):
        self.add()
        self.solve()
        self.emit('FPY', 'POINT_COPY', 2, 3, 3)
        self.emit('FI', 'REPLACE', 1, 0, 2, 3, 4, 3)
        self.assertEqual(self.ledger.points, {4: 3})
        with self.assertRaisesRegex(ValueError, 'tracked copy source'):
            self.emit('FPY', 'POINT_COPY', 2, 5, 3)

    def test_copy_cannot_promote_or_suppress_validity(self):
        self.add()
        for mask in (1, 2, 3):
            with self.subTest(mask=mask), self.assertRaisesRegex(ValueError, 'copy inherits'):
                self.emit('FPY', 'POINT_COPY', 2, 3, mask)

    def test_remove_moves_last_generation(self):
        self.add()
        self.add(3, 4, 1)
        self.solve(gid=4, slot=1)
        self.emit('FX', 'REMOVE', 1, 0, 2)
        self.emit('FV', 'REMOVE_MOVE', 1, 1, 0, 4)
        self.assertEqual(self.ledger.manifolds[1][1], [4])
        self.assertEqual(self.ledger.points, {4: 3})
        self.emit('FX', 'REMOVE', 1, 0, 4)
        self.assertIsNone(self.ledger.pending_move)

    def test_missing_and_extra_moves_fail(self):
        self.add()
        self.add(3, 4, 1)
        self.emit('FX', 'REMOVE', 1, 0, 2)
        with self.assertRaisesRegex(ValueError, 'immediate mandatory'):
            self.emit('FC', 'RUST_CONTACT_CREATE', 5)
        with self.assertRaisesRegex(ValueError, 'exact remove/move'):
            self.emit('FV', 'REMOVE_MOVE', 1, 1, 0, 2)

    def test_eviction_and_fresh_generation_reuse(self):
        for slot in range(4):
            self.add(slot * 2 + 1, slot * 2 + 2, slot)
        self.emit('FC', 'RUST_CONTACT_CREATE', 9)
        self.emit('FI', 'EVICT_ADD', 1, 2, 6, 9, 10, 0)
        self.assertNotIn(6, self.ledger.points)
        self.assertEqual(self.ledger.manifolds[1][1], [2, 4, 10, 8])
        with self.assertRaisesRegex(ValueError, 'fresh generation'):
            self.emit('FC', 'RUST_CONTACT_CREATE', 6)

    def test_clear_and_release_close_all_generations(self):
        self.add()
        self.add(3, 4, 1)
        self.emit('FM', 'CLEAR_BEGIN', 1, 0, 1)
        self.emit('FX', 'CLEAR_POINT', 1, 0, 2)
        self.emit('FX', 'CLEAR_POINT', 1, 1, 4)
        self.emit('FM', 'CLEAR_END', 1, 0, 1)
        self.emit('FM', 'RELEASE', 1, 0, 1)
        self.ledger.finish(1)
        self.assertEqual(self.ledger.closed, 4)
        with self.assertRaisesRegex(ValueError, 'fresh manifold'):
            self.emit('FM', 'ALLOC', 1, 0, 1)
        self.emit('FM', 'ALLOC', 7, 0, 1)
        self.emit('FM', 'RELEASE', 7, 0, 1)

    def test_forward_release_without_clear(self):
        self.add()
        self.add(3, 4, 1)
        self.emit('FX', 'RELEASE_POINT', 1, 0, 2)
        self.emit('FX', 'RELEASE_POINT', 1, 1, 4)
        self.emit('FM', 'RELEASE', 1, 0, 1)
        self.ledger.finish(1)

    def test_temporary_requires_closure(self):
        self.emit('FC', 'RUST_CONTACT_CREATE', 1)
        self.emit('FM', 'RELEASE', 1, 0, 1)
        with self.assertRaisesRegex(ValueError, 'closed manifold'):
            self.ledger.finish(1)
        self.emit('FX', 'TEMP_END', 0, 0, 1)
        self.ledger.finish(1)

    def test_missing_writer_cannot_be_hidden_by_union_mask(self):
        self.add()
        self.emit('FB', 'SOLVER_BEGIN', 1, 0, 2, 1, 260, False)
        self.emit('FT', 'SOLVER_CHOICE', 1, 0, 2, 1, True, False, False)
        with self.assertRaisesRegex(ValueError, 'mandatory writer schedule'):
            self.emit('FE', 'PLANE_ONE', 1, 0, 2, 1, 3, 3, True)

    def test_mask_suppression_and_false_branch_label(self):
        self.add()
        self.emit('FB', 'SOLVER_BEGIN', 1, 0, 2, 1, 260, False)
        self.emit('FT', 'SOLVER_CHOICE', 1, 0, 2, 1, True, False, False)
        self.emit('FW', 'PLANE_BOTH', 1, 0, 2, 1, 3)
        for branch, mask, valid in (('PLANE_ONE', 0, 0), ('PLANE_ONE', 3, 1), ('VELOCITY_ONE', 3, 3)):
            with self.subTest(branch=branch, mask=mask, valid=valid), self.assertRaises(ValueError):
                self.emit('FE', branch, 1, 0, 2, 1, mask, valid, True)

    def test_rust_does_not_invent_native_raw_or_dir2_writes(self):
        self.add()
        self.emit('FB', 'SOLVER_BEGIN', 1, 0, 2, 1, 260, False)
        with self.assertRaisesRegex(ValueError, 'observed branch'):
            self.emit('FW', 'DIR1_RAW', 1, 0, 2, 1, 1)
        self.emit('FT', 'SOLVER_CHOICE', 1, 0, 2, 1, True, True, False)
        with self.assertRaisesRegex(ValueError, 'Rust writer sites'):
            self.emit('FW', 'VELOCITY_DIR2', 1, 0, 2, 1, 2)

    def test_null_callback_and_cache_guards(self):
        for index in range(4):
            native = Ledger(True)
            values = [True] * 4
            values[index] = False
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, 'null Added/Processed/Destroyed/usercache'):
                native.guard(0, 'STARTUP', tuple(values))


if __name__ == '__main__':
    unittest.main()
