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
            'FR 0 1 REFRESH_BEGIN 1 0 0 false false',
            'FF 0 1 FIXTURE_BEGIN',
            'FT 0 1 SOLVER_CHOICE 1 0 2 1 true false false',
            'FW 0 1 PLANE_BOTH 1 0 2 1 3', 'FE 0 1 PLANE_ONE 1 0 2 1 3 3 true',
            'FS 0 1 SNAPSHOT 0 1 1', 'FL 0 1 SNAPSHOT 0 0 1 2 3 false',
            'FD 0 1 SNAPSHOT 0 0 1 U 0', 'FP 0 1 RUST_PHYSICAL 0 0 2 00000000 00000000 00000000',
        )
        for example in examples:
            with self.subTest(example=example):
                self.assertEqual(diagnostic(example.split())[2], 1)

    def test_refresh_exact_width_typed_sentinels_and_branches(self):
        valid = 'FR 0 1 REFRESH_POINT 1 0 2 true false'.split()
        self.assertEqual(diagnostic(valid)[-1], (1, 0, 2, True, False))
        for row in (valid[:-1], valid + ['false'],
                    'FR 0 1 REFRESH_POINT 1 0 0 false false'.split(),
                    'FR 0 1 REFRESH_POINT 1 0 2 true true'.split(),
                    'FR 0 1 REFRESH_POINT 1 0 2 1 false'.split(),
                    'FR 0 1 REFRESH_BEGIN 1 1 0 false false'.split(),
                    'FR 0 1 REFRESH_END 1 0 2 false false'.split(),
                    'FR 0 1 REFRESH_END 1 0 0 false true'.split()):
            with self.subTest(row=row), self.assertRaises(ValueError):
                diagnostic(row)


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


class RefreshTests(unittest.TestCase):
    def prepare(self, native=True, count=0):
        self.ledger = Ledger(native)
        if native:
            self.guard('STARTUP')
            self.guard('COMMAND_BEGIN')
            self.guard('MANIFOLD_ALLOC_ENTER')
            for _ in range(4):
                self.guard('CTOR_EXIT')
        self.emit('FM', 'ALLOC', 1, 0, 1)
        if native:
            self.guard('MANIFOLD_ALLOC_EXIT')
        for slot in range(count):
            if native:
                self.guard('RESULT_ENTER')
                self.guard('CTOR_EXIT')
            self.emit('FC', 'CTOR_GEOMETRIC' if native else 'RUST_CONTACT_CREATE', 2 * slot + 1)
            if native:
                self.guard('ADD_ENTER')
            self.emit('FI', 'ADD', 1, slot, 0, 2 * slot + 1, 2 * slot + 2, 0)
            if native:
                self.guard('ADD_EXIT')
                self.guard('ADDED_PRECALL')
                self.guard('RESULT_EXIT')

    def guard(self, site):
        self.ledger.guard(0, site, (True,) * 4)

    def emit(self, tag, site, *values):
        self.ledger.event(0, tag, site, values)

    def begin(self):
        if self.ledger.native:
            self.guard('REFRESH_ENTER')
        self.emit('FR', 'REFRESH_BEGIN', 1, 0, 0, False, False)

    def end(self):
        self.emit('FR', 'REFRESH_END', 1, 0, 0, False, False)
        if self.ledger.native:
            self.guard('REFRESH_EXIT')

    def visit(self, slot, gid, distance=False, lateral=False):
        self.emit('FR', 'REFRESH_POINT', 1, slot, gid, distance, lateral)
        if distance or lateral:
            if self.ledger.native:
                for site in ('REMOVE_ENTER', 'USERCACHE_ENTER', 'USERCACHE_EXIT'):
                    self.guard(site)
            self.emit('FX', 'REMOVE', 1, slot, gid)
            if self.ledger.pending_move:
                self.emit('FV', 'REMOVE_MOVE', *self.ledger.pending_move)
            if self.ledger.native:
                self.guard('REMOVE_EXIT')
        elif self.ledger.native:
            self.guard('PROCESSED_PRECALL')

    def test_actual_zero_contact_call_and_result_depth_return(self):
        self.prepare()
        self.guard('RESULT_ENTER')
        self.guard('RESULT_EXIT')
        self.begin()
        self.end()
        self.assertIsNone(self.ledger.refresh)
        self.assertEqual(self.ledger.scopes, [])

    def test_mixed_reverse_visits_move_only_already_visited_last(self):
        for native in (True, False):
            with self.subTest(native=native):
                self.prepare(native, 4)
                self.begin()
                self.visit(3, 8)
                self.visit(2, 6, distance=True)
                self.visit(1, 4)
                self.visit(0, 2, lateral=True)
                self.end()
                self.assertEqual(self.ledger.manifolds[1][1], [8, 4])
                self.assertEqual(self.ledger.points, {4: 0, 8: 0})

    def test_remove_last_and_all_kept(self):
        for native in (True, False):
            self.prepare(native, 2)
            self.begin()
            self.visit(1, 4, distance=True)
            self.visit(0, 2)
            self.end()
            self.begin()
            self.visit(0, 2)
            self.end()
            self.assertEqual(self.ledger.manifolds[1][1], [2])

    def test_orphan_duplicate_and_missing_processed(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'Processed precall binds'):
            self.guard('PROCESSED_PRECALL')
        self.prepare(count=1)
        self.begin()
        self.emit('FR', 'REFRESH_POINT', 1, 0, 2, False, False)
        for tag, site, values in (('FR', 'REFRESH_END', (1, 0, 0, False, False)),
                                  ('FX', 'REMOVE', (1, 0, 2)),
                                  ('FC', 'CTOR_GEOMETRIC', (3,))):
            with self.subTest(site=site), self.assertRaisesRegex(ValueError, 'exact refresh source order'):
                self.emit(tag, site, *values)
        self.guard('PROCESSED_PRECALL')
        with self.assertRaisesRegex(ValueError, 'exact refresh source order'):
            self.guard('PROCESSED_PRECALL')
        self.end()

    def test_missing_duplicate_reordered_refresh_and_wrong_binding(self):
        for native in (True, False):
            self.prepare(native, 2)
            self.begin()
            for values in ((1, 0, 2, False, False), (2, 1, 4, False, False),
                           (1, 1, 2, False, False), (1, 1, 4, True, True),
                           (1, 1, 4, 1, False)):
                with self.subTest(native=native, values=values), self.assertRaises(ValueError):
                    self.emit('FR', 'REFRESH_POINT', *values)
            for site in ('REFRESH_BEGIN', 'REFRESH_END'):
                with self.subTest(site=site), self.assertRaisesRegex(ValueError, 'exact refresh source order'):
                    self.emit('FR', site, 1, 0, 0, False, False)
            self.visit(1, 4)
            with self.assertRaisesRegex(ValueError, 'descending initial-count'):
                self.emit('FR', 'REFRESH_POINT', 1, 1, 4, False, False)
            self.visit(0, 2)
            self.end()
            with self.assertRaisesRegex(ValueError, 'same active refresh'):
                self.emit('FR', 'REFRESH_END', 1, 0, 0, False, False)

    def test_removal_schedule_wrong_tuple_and_branch(self):
        self.prepare(count=2)
        self.begin()
        self.emit('FR', 'REFRESH_POINT', 1, 1, 4, True, False)
        for site in ('PROCESSED_PRECALL', 'USERCACHE_ENTER', 'REMOVE_EXIT'):
            with self.subTest(site=site), self.assertRaisesRegex(ValueError, 'exact refresh source order'):
                self.guard(site)
        for site in ('REMOVE_ENTER', 'USERCACHE_ENTER', 'USERCACHE_EXIT'):
            self.guard(site)
        with self.assertRaisesRegex(ValueError, 'exact pending point'):
            self.emit('FX', 'REMOVE', 1, 0, 2)
        self.emit('FX', 'REMOVE', 1, 1, 4)
        with self.assertRaisesRegex(ValueError, 'exact refresh source order'):
            self.emit('FR', 'REFRESH_POINT', 1, 0, 2, False, False)
        self.guard('REMOVE_EXIT')
        self.visit(0, 2)
        self.end()

    def test_native_entry_exit_and_zero_sentinels_are_mandatory(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'native refresh entry'):
            self.emit('FR', 'REFRESH_BEGIN', 1, 0, 0, False, False)
        self.guard('REFRESH_ENTER')
        with self.assertRaisesRegex(ValueError, 'exact refresh source order'):
            self.guard('REFRESH_EXIT')
        self.emit('FR', 'REFRESH_BEGIN', 1, 0, 0, False, False)
        with self.assertRaisesRegex(ValueError, 'BEGIN/END sentinels'):
            self.emit('FR', 'REFRESH_END', 1, 0, 1, False, False)
        self.emit('FR', 'REFRESH_END', 1, 0, 0, False, False)
        with self.assertRaisesRegex(ValueError, 'exact refresh source order'):
            self.emit('FM', 'RELEASE', 1, 0, 1)
        self.guard('REFRESH_EXIT')

    def test_result_insertion_exit_callback_and_pending_order(self):
        self.prepare()
        self.guard('RESULT_ENTER')
        self.guard('CTOR_EXIT')
        self.emit('FC', 'CTOR_GEOMETRIC', 1)
        self.guard('ADD_ENTER')
        self.emit('FI', 'ADD', 1, 0, 0, 1, 2, 0)
        for site in ('ADDED_PRECALL', 'RESULT_EXIT'):
            with self.subTest(site=site), self.assertRaisesRegex(ValueError, 'exact insertion exit'):
                self.guard(site)
        self.guard('ADD_EXIT')
        with self.assertRaisesRegex(ValueError, 'exact insertion exit'):
            self.guard('RESULT_EXIT')
        with self.assertRaisesRegex(ValueError, 'mandatory post-insertion'):
            self.emit('FC', 'CTOR_GEOMETRIC', 3)
        self.guard('ADDED_PRECALL')
        with self.assertRaisesRegex(ValueError, 'Added precall binds'):
            self.guard('ADDED_PRECALL')
        self.guard('RESULT_EXIT')
        self.assertEqual(self.ledger.manifolds[1][1], [2])

    def test_insertion_without_result_call_is_rejected(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'actual Result call'):
            self.guard('CTOR_EXIT')


class ConstructorTests(unittest.TestCase):
    def check(self, rows):
        ledger = Ledger(True)
        for site in ('STARTUP', 'COMMAND_BEGIN'):
            ledger.guard(0, site, (True,) * 4)
        for tag, site, values in rows:
            if tag == 'FG':
                ledger.guard(0, site, (True,) * 4)
            else:
                ledger.event(0, tag, site, values)
        return ledger

    def test_allocation_requires_exact_four_backing_constructors(self):
        rows = [('FG', 'MANIFOLD_ALLOC_ENTER', ())] + [('FG', 'CTOR_EXIT', ())] * 4 + [
            ('FM', 'ALLOC', (1, 0, 1)), ('FG', 'MANIFOLD_ALLOC_EXIT', ())]
        self.assertEqual(self.check(rows).manifolds, {1: ((0, 1), [])})
        for index in range(len(rows)):
            for duplicate in (False, True):
                changed = rows[:index] + ([rows[index]] if duplicate else []) + rows[index + (not duplicate):]
                with self.subTest(index=index, duplicate=duplicate), self.assertRaises(ValueError):
                    ledger = self.check(changed)
                    # A missing final exit must also fail before serialization.
                    ledger.guard(0, 'SNAPSHOT', (True,) * 4)
        for rows in ([('FG', 'CTOR_EXIT', ())], [('FC', 'CTOR_DEFAULT', (1,))],
                     [('FM', 'ALLOC', (1, 0, 1))]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.check(rows)

    def test_geometric_constructor_requires_immediate_single_fc_in_result(self):
        prefix = [('FG', 'RESULT_ENTER', ()), ('FG', 'CTOR_EXIT', ()), ('FC', 'CTOR_GEOMETRIC', (1,))]
        self.assertEqual(self.check(prefix).temporary, {1: 0})
        for rows in (prefix[:1] + prefix[2:], prefix[:2] + prefix[1:], prefix + prefix[2:],
                     prefix[:2] + [('FG', 'RESULT_EXIT', ())],
                     prefix[:2] + [('FC', 'CTOR_DEFAULT', (1,))],
                     prefix + [('FG', 'RESULT_EXIT', ())], prefix[:1] + prefix[1:] * 2):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.check(rows)


class FixtureTests(unittest.TestCase):
    def test_native_guards_wrap_exact_visits_even_after_mask_three(self):
        helper = RefreshTests()
        helper.prepare(True, 2)
        ledger = helper.ledger
        helper.guard('SNAPSHOT')
        ledger.snapshot(1, [2, 4], (0, 1))
        ledger.complete_snapshot()
        helper.guard('COMMAND_END')
        for cp in (1, 2):
            ledger.operation = 'W'
            guard = lambda site: ledger.guard(cp, site, (True,) * 4)
            emit = lambda tag, site, values=(): ledger.event(cp, tag, site, values)
            guard('COMMAND_BEGIN')
            with self.assertRaisesRegex(ValueError, 'complete fixture'):
                guard('SNAPSHOT')
            guard('FIXTURE_BEGIN')
            emit('FF', 'FIXTURE_BEGIN')
            with self.assertRaises(ValueError):
                emit('FF', 'FIXTURE_END')
            for slot, gid in ((0, 2), (1, 4)):
                emit('FW', 'FIXTURE_W', (1, slot, gid, 0, 3))
                with self.assertRaises(ValueError):
                    emit('FW', 'FIXTURE_W', (1, slot, gid, 0, 3))
            emit('FF', 'FIXTURE_END')
            guard('FIXTURE_END')
            guard('SNAPSHOT')
            ledger.snapshot(1, [2, 4], (0, 1))
            ledger.complete_snapshot()
            guard('COMMAND_END')
        self.assertEqual(ledger.points, {2: 3, 4: 3})

    def test_snapshot_dispatcher_order_precedes_numeric_manifold_order(self):
        self.prepare(1)
        ledger = self.ledger
        ledger.operation = 'H'
        ledger.event(0, 'FM', 'ALLOC', (9, 0, 1))
        ledger.event(0, 'FC', 'RUST_CONTACT_CREATE', (3,))
        ledger.event(0, 'FI', 'ADD', (9, 0, 0, 3, 4, 0))
        ledger.snapshot(9, [4], (0, 1))
        ledger.snapshot(1, [2], (0, 1))
        ledger.complete_snapshot()
        ledger.operation = 'W'
        self.begin()
        with self.assertRaisesRegex(ValueError, 'next exact'):
            self.write(0, 2)
        self.emit('FW', 'FIXTURE_W', 9, 0, 4, 0, 3)
        self.write(0, 2)
        self.emit('FF', 'FIXTURE_END')

    def prepare(self, count=2, defined=False):
        helper = RefreshTests()
        helper.prepare(False, count)
        self.ledger = helper.ledger
        if count and defined:
            self.ledger.event(0, 'FB', 'SOLVER_BEGIN', (1, 0, 2, 1, 260, False))
            self.ledger.event(0, 'FT', 'SOLVER_CHOICE', (1, 0, 2, 1, True, False, False))
            self.ledger.event(0, 'FW', 'PLANE_BOTH', (1, 0, 2, 1, 3))
            self.ledger.event(0, 'FE', 'PLANE_ONE', (1, 0, 2, 1, 3, 3, True))
        # Actual snapshot order is independent of numeric manifold IDs.
        self.ledger.snapshot(1, list(self.ledger.manifolds[1][1]), (0, 1))
        self.ledger.complete_snapshot()
        self.ledger.operation = 'W'

    def emit(self, tag, site, *values):
        self.ledger.event(1, tag, site, values)

    def begin(self):
        self.emit('FF', 'FIXTURE_BEGIN')

    def write(self, slot, gid):
        self.emit('FW', 'FIXTURE_W', 1, slot, gid, 0, 3)

    def test_empty_and_complete_mixed_already_defined_visits(self):
        for count in (0, 2):
            self.prepare(count, defined=True)
            self.begin()
            for slot in range(count):
                self.write(slot, 2 * slot + 2)
            self.emit('FF', 'FIXTURE_END')
            self.assertIsNone(self.ledger.fixture)
            self.assertEqual(list(self.ledger.points.values()), [3] * count)

    def test_duplicate_omitted_reordered_wrong_generation_and_mutation(self):
        self.prepare()
        self.begin()
        for slot, gid in ((1, 4), (0, 4), (0, 999)):
            with self.subTest(slot=slot, gid=gid), self.assertRaises(ValueError):
                self.write(slot, gid)
        with self.assertRaisesRegex(ValueError, 'exact fixture source order'):
            self.emit('FF', 'FIXTURE_END')
        self.write(0, 2)
        with self.assertRaisesRegex(ValueError, 'next exact'):
            self.write(0, 2)
        for tag, site, values in (('FI', 'REPLACE', (1, 0, 2, 3, 4, 0)),
                                  ('FX', 'REMOVE', (1, 1, 4)), ('FF', 'FIXTURE_BEGIN', ())):
            with self.subTest(site=site), self.assertRaises(ValueError):
                self.emit(tag, site, *values)
        self.write(1, 4)
        with self.assertRaises(ValueError):
            self.write(1, 4)
        self.emit('FF', 'FIXTURE_END')
        with self.assertRaises(ValueError):
            self.emit('FF', 'FIXTURE_END')
        with self.assertRaises(ValueError):
            self.begin()

    def test_fixture_requires_actual_w_preceding_snapshot_and_ff(self):
        self.prepare()
        self.ledger.operation = 'N'
        with self.assertRaises(ValueError):
            self.begin()
        self.ledger.operation = 'W'
        with self.assertRaises(ValueError):
            self.write(0, 2)
        self.ledger.previous_snapshot = None
        with self.assertRaises(ValueError):
            self.begin()
        for raw in ('FF 0 1 FIXTURE_BEGIN extra', 'FF 0 1 FIXTURE_END 0', 'FF 0 1 UNKNOWN'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                diagnostic(raw.split())


if __name__ == '__main__':
    unittest.main()
