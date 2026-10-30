"""Pure bounded stream fixtures. These are not native or numerical receipts."""
import hashlib
import unittest

from friction_trace import Capture, compare_defined, compare_physical, parse


class StreamTests(unittest.TestCase):
    inputs = 'H synthetic fixture-injection\nX\n'

    def rust_original_stream(self):
        inputs = 'H initialized fixture-injection\nN 0 1 0\nX\n'
        sha = hashlib.sha256(inputs.encode()).hexdigest()
        lines = [f'FH 3 rust-original ordinary {sha} 3']
        for cp, op in ((0, 'H'), (1, 'N')):
            if cp:
                lines += ['K 1 1 1 00000000 00000000', 'Y 1 P 1 0',
                          'Y 1 G 0 1 0 0 0', 'V 1 0 1', 'Y 1 A', 'R 1 1', 'STATUS 1 0']
            lines += [f'O {cp} {op} 1 0 0',
                      ' '.join(['B', str(cp), '0'] + ['0'] * 6 + ['00000000'] * 51 + ['0'] * 6),
                      ' '.join(['W', str(cp), '0', '0', '0'] + ['00000000'] * 36)]
            lines += [f'S {cp} {axis} 0' for axis in range(3)]
            lines += [' '.join(['J', str(cp), '0', '-1', '0', '0'] + ['0', '00000000', '00000000'] * 6)]
        lines += ['O 2 X 0 0 0', 'Z 3', 'FZ 0 3 0']
        return ('\n'.join(lines) + '\n').encode(), inputs, sha

    def test_rust_original_retains_actual_sap_joint_and_step_rows(self):
        raw, inputs, sha = self.rust_original_stream()
        capture = parse(raw, inputs, variant='rust-original', role='ordinary', corpus_sha=sha)
        self.assertEqual({row[0] for row in capture.base}, {'O', 'B', 'W', 'S', 'J', 'R', 'K', 'Y', 'V', 'STATUS'})

    def test_empty_w_requires_complete_fixture_boundaries_in_both_languages(self):
        inputs = 'H initialized fixture-injection\nW\nX\n'
        sha = hashlib.sha256(inputs.encode()).hexdigest()
        for native in (False, True):
            variant = 'native-observed' if native else 'rust-observed'
            events = [('FG', 0, 'STARTUP')] if native else []
            for cp, op in enumerate(('H', 'W', 'X')):
                if native:
                    events.append(('FG', cp, 'COMMAND_BEGIN'))
                if op == 'W':
                    if native:
                        events.append(('FG', cp, 'FIXTURE_BEGIN'))
                    events += [('FF', cp, 'FIXTURE_BEGIN'), ('FF', cp, 'FIXTURE_END')]
                    if native:
                        events.append(('FG', cp, 'FIXTURE_END'))
                if native:
                    events.append(('FG', cp, 'SNAPSHOT'))
                events.append(('BASE', f'O {cp} {op} 0 0 0'))
                if native:
                    events.append(('FG', cp, 'COMMAND_END'))
            events.append(('BASE', 'Z 3'))
            def raw(selected):
                lines, seq = [f'FH 3 {variant} ordinary {sha} 3'], 0
                for event in selected:
                    if event[0] == 'BASE':
                        lines.append(event[1])
                    else:
                        tag, cp, site = event
                        seq += 1
                        tail = ' true true true true' if tag == 'FG' else ''
                        lines.append(f'{tag} {cp} {seq} {site}{tail}')
                return ('\n'.join(lines) + f'\nFZ {seq} 3 0\n').encode()
            parse(raw(events), inputs, variant=variant, role='ordinary', corpus_sha=sha)
            for index, event in enumerate(events):
                if event[0] == 'FF' or event[0] == 'FG' and event[2].startswith('FIXTURE_'):
                    for duplicate in (False, True):
                        changed = events[:index] + ([event] if duplicate else []) + events[index + (not duplicate):]
                        with self.subTest(native=native, event=event, duplicate=duplicate), self.assertRaises(ValueError):
                            parse(raw(changed), inputs, variant=variant, role='ordinary', corpus_sha=sha)
            with self.assertRaises(ValueError):
                parse(raw([event for event in events if event[0] != 'FF']), inputs,
                      variant=variant, role='ordinary', corpus_sha=sha)

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

    def guarded(self, extra=()):
        raw, sha = self.stream('native-observed')
        events = [('FG', 0, 'STARTUP'), ('FG', 0, 'COMMAND_BEGIN'), *extra,
                  ('FG', 0, 'SNAPSHOT'), ('BASE', 'O 0 H 0 0 0'), ('FG', 0, 'COMMAND_END'),
                  ('FG', 1, 'COMMAND_BEGIN'), ('FG', 1, 'SNAPSHOT'), ('BASE', 'O 1 X 0 0 0'),
                  ('BASE', 'Z 2'), ('FG', 1, 'COMMAND_END')]
        lines, seq = [raw.decode().splitlines()[0]], 0
        for event in events:
            if event[0] == 'BASE':
                lines.append(event[1])
            else:
                tag, cp, site, *values = event
                seq += 1
                tail = ' '.join(str(value) for value in values) if values else 'true true true true'
                lines.append(f'{tag} {cp} {seq} {site} {tail}')
        lines.append(f'FZ {seq} 2 0')
        return ('\n'.join(lines) + '\n').encode(), sha

    def test_complete_native_empty_stream_and_orphan_processed(self):
        raw, sha = self.guarded()
        capture = parse(raw, self.inputs, variant='native-observed', role='ordinary', corpus_sha=sha)
        self.assertEqual(capture.closed, 0)
        for count in (1, 2):
            raw, sha = self.guarded([('FG', 0, 'PROCESSED_PRECALL')] * count)
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, 'Processed precall binds'):
                parse(raw, self.inputs, variant='native-observed', role='ordinary', corpus_sha=sha)

    def test_base_rows_cannot_interrupt_refresh_entry(self):
        raw, sha = self.guarded([('FG', 0, 'REFRESH_ENTER'), ('BASE', 'O 0 H 0 0 0')])
        with self.assertRaisesRegex(ValueError, 'exact refresh source order'):
            parse(raw, self.inputs, variant='native-observed', role='ordinary', corpus_sha=sha)

    def test_originals_reject_refresh_records(self):
        for variant in ('native-original', 'rust-original'):
            raw, sha = self.stream(variant)
            raw = raw.replace(b'O 0 H', b'FR 0 1 REFRESH_BEGIN 1 0 0 false false\nO 0 H')
            with self.subTest(variant=variant), self.assertRaisesRegex(ValueError, 'no fabricated observations'):
                parse(raw, self.inputs, variant=variant, role='ordinary', corpus_sha=sha)

    def test_originals_reject_fixture_records(self):
        for variant in ('native-original', 'rust-original'):
            raw, sha = self.stream(variant)
            raw = raw.replace(b'O 0 H', b'FF 0 1 FIXTURE_BEGIN\nO 0 H')
            with self.subTest(variant=variant), self.assertRaisesRegex(ValueError, 'no fabricated observations'):
                parse(raw, self.inputs, variant=variant, role='ordinary', corpus_sha=sha)

    def contact_stream(self, native):
        variant = 'native-observed' if native else 'rust-observed'
        sha = hashlib.sha256(self.inputs.encode()).hexdigest()
        lines, seq = [f'FH 3 {variant} ordinary {sha} 2'], 0

        def event(cp, tag, site, *values):
            nonlocal seq
            seq += 1
            tail = ' '.join(str(value).lower() if type(value) is bool else str(value) for value in values)
            lines.append(f'{tag} {cp} {seq} {site} {tail}')

        def guard(cp, site):
            if native:
                event(cp, 'FG', site, True, True, True, True)

        guard(0, 'STARTUP')
        guard(0, 'COMMAND_BEGIN')
        lines += ['E 0 A+ 9']
        guard(0, 'MANIFOLD_ALLOC_ENTER')
        for _ in range(4):
            guard(0, 'CTOR_EXIT')
        lines += ['E 0 M+ 1 0 1']
        event(0, 'FM', 'ALLOC', 1, 0, 1)
        guard(0, 'MANIFOLD_ALLOC_EXIT')
        guard(0, 'RESULT_ENTER')
        guard(0, 'CTOR_EXIT')
        event(0, 'FC', 'CTOR_GEOMETRIC' if native else 'RUST_CONTACT_CREATE', 1)
        guard(0, 'ADD_ENTER')
        event(0, 'FI', 'ADD', 1, 0, 0, 1, 2, 0)
        guard(0, 'ADD_EXIT')
        guard(0, 'ADDED_PRECALL')
        guard(0, 'RESULT_EXIT')
        guard(0, 'REFRESH_ENTER')
        event(0, 'FR', 'REFRESH_BEGIN', 1, 0, 0, False, False)
        event(0, 'FR', 'REFRESH_POINT', 1, 0, 2, False, False)
        guard(0, 'PROCESSED_PRECALL')
        event(0, 'FR', 'REFRESH_END', 1, 0, 0, False, False)
        guard(0, 'REFRESH_EXIT')
        guard(0, 'SNAPSHOT')
        lines.append('O 0 H 2 1 1')
        for index in range(2):
            lines.append(' '.join(['B', '0', str(index)] + ['0'] * 6 + ['00000000'] * 51 + ['0'] * 6))
            lines.append(' '.join(['W', '0', str(index), '0', '0'] + ['00000000'] * 36))
        lines += [f'S 0 {axis} 0' for axis in range(3)]
        lines += ['P 0 0 0 1 9 0 9', 'M 0 0 1 9 0 1 00000000 00000000 1']
        event(0, 'FS', 'SNAPSHOT', 0, 1, 1)
        event(0, 'FL', 'SNAPSHOT', 0, 0, 1, 2, 0, False)
        lines.append(' '.join(['Q', '0', '0', '0'] + ['00000000'] * 21 + ['0', 'false']))
        for direction in (1, 2):
            event(0, 'FD', 'SNAPSHOT', 0, 0, direction, 'U', 0)
        if not native:
            for direction in (1, 2):
                event(0, 'FP', 'RUST_PHYSICAL', 0, 0, direction, *(['00000000'] * 3))
        guard(0, 'COMMAND_END')
        guard(1, 'COMMAND_BEGIN')
        guard(1, 'RELEASE_ENTER')
        guard(1, 'CLEAR_ENTER')
        event(1, 'FM', 'CLEAR_BEGIN', 1, 0, 1)
        guard(1, 'USERCACHE_ENTER')
        guard(1, 'USERCACHE_EXIT')
        event(1, 'FX', 'CLEAR_POINT', 1, 0, 2)
        event(1, 'FM', 'CLEAR_END', 1, 0, 1)
        guard(1, 'CLEAR_EXIT')
        event(1, 'FM', 'RELEASE', 1, 0, 1)
        guard(1, 'RELEASE_EXIT')
        lines += ['E 1 M- 1', 'E 1 A- 9']
        guard(1, 'SNAPSHOT')
        lines += ['O 1 X 0 0 0', 'Z 2']
        guard(1, 'COMMAND_END')
        lines.append(f'FZ {seq} 2 2')
        return ('\n'.join(lines) + '\n').encode(), sha, variant

    def check_contact(self, native):
        raw, sha, variant = self.contact_stream(native)
        capture = parse(raw, self.inputs, variant=variant, role='ordinary', corpus_sha=sha)
        self.assertEqual(capture.bindings, {(0, 0, 0): (1, 2)})
        self.assertEqual(capture.closed, 2)
        self.assertEqual(len(capture.directions), 2)
        self.assertEqual(len(capture.physical), 0 if native else 2)

    def test_complete_native_contact_snapshot(self):
        self.check_contact(True)

    def test_complete_rust_contact_snapshot_and_physical_rows(self):
        self.check_contact(False)

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
