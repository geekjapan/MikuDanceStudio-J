"""Pure byte-protocol controls: no compiler or operating-system process fixture."""
import io
import json
import unittest

from diagnose_common_plan_retention import (COUNT_KEYS, MAX_BYTES, MAX_EVENTS, MAX_LINE,
                                           RetentionForwarder, parse_record)


def event(**changes):
    value = dict(schema=1, pid=42, sequence=0, monotonic_ns=10, stage='NativeExport',
                 edge='Begin', status='ok', rss_kib=100, hwm_kib=120,
                 counts=dict.fromkeys(COUNT_KEYS))
    value.update(changes)
    return json.dumps(value, separators=(',', ':')).encode() + b'\n'


class RetentionProtocolTests(unittest.TestCase):
    def test_legal_finite_event_and_nullable_unknown_counts(self):
        record = parse_record(event(), 42, 0, 0)
        self.assertEqual(record['rss_kib'], 100)
        self.assertTrue(all(v is None for v in record['counts'].values()))
        self.assertEqual(parse_record(event(status='unavailable', rss_kib=None), 42, 0, 0)['rss_kib'], None)

    def test_missing_and_extra_fields_are_refused(self):
        value = json.loads(event())
        for key in value:
            bad = dict(value)
            del bad[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_record(json.dumps(bad).encode() + b'\n', 42, 0, 0)
        with self.assertRaises(ValueError):
            parse_record(event(extra=1), 42, 0, 0)

    def test_exact_numeric_types_and_overflow(self):
        for key in ('schema', 'pid', 'sequence', 'monotonic_ns', 'rss_kib', 'hwm_kib'):
            for bad in (True, 1.0, -1, 2**64, '1'):
                with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                    parse_record(event(**{key: bad}), 42, 0, 0)
        for bad in (True, 1.0, -1, 2**64):
            counts = dict.fromkeys(COUNT_KEYS)
            counts['source_bytes'] = bad
            with self.subTest(count=bad), self.assertRaises(ValueError):
                parse_record(event(counts=counts), 42, 0, 0)

    def test_duplicate_and_nonfinite_json_are_refused(self):
        for raw in (event().replace(b'"pid":42', b'"pid":42,"pid":42'),
                    event().replace(b'"rss_kib":100', b'"rss_kib":NaN'),
                    event().replace(b'"rss_kib":100', b'"rss_kib":Infinity'),
                    event().replace(b'"rss_kib":100', b'"rss_kib":1e999')):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_record(raw, 42, 0, 0)

    def test_wrong_pid_sequence_time_stage_and_counts_are_refused(self):
        for changes in (dict(pid=43), dict(sequence=1), dict(monotonic_ns=9),
                        dict(stage='Unknown'), dict(stage=True), dict(edge='Observation'),
                        dict(counts={}), dict(status='truncated')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_record(event(**changes), 42, 0, 10)
        for key, value in (('unit_index', 24), ('retained_units', 25)):
            counts = dict.fromkeys(COUNT_KEYS)
            counts[key] = value
            with self.assertRaises(ValueError):
                parse_record(event(counts=counts), 42, 0, 0)

    def test_line_and_sequence_caps(self):
        for raw in (event().rstrip(b'\n'), b' ' * MAX_LINE + b'\n'):
            with self.assertRaises(ValueError):
                parse_record(raw, 42, 0, 0)
        with self.assertRaises(ValueError):
            parse_record(event(sequence=MAX_EVENTS), 42, MAX_EVENTS, 0)

    def test_forwarder_only_emits_valid_complete_records(self):
        stream = io.BytesIO(event() + event(sequence=1, monotonic_ns=11))
        seen = []
        forwarder = RetentionForwarder(stream, 42, lambda line, **_: seen.append(line))
        forwarder.drain(final=True)
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(line.startswith('RETENTION_EVENT ') for line in seen))
        self.assertEqual(forwarder.sequence, 2)

    def test_partial_line_waits_then_reports_unavailable_once(self):
        stream = io.BytesIO(event()[:-1])
        seen = []
        forwarder = RetentionForwarder(stream, 42, lambda line, **_: seen.append(line))
        forwarder.drain()
        self.assertEqual(seen, [])
        forwarder.drain(final=True)
        forwarder.drain(final=True)
        self.assertEqual(seen, ['RETENTION_DIAGNOSTIC_UNAVAILABLE sidecar'])

    def test_malformed_record_never_forwards_child_content(self):
        seen = []
        forwarder = RetentionForwarder(io.BytesIO(b'child secret text\n'), 42,
                                      lambda line, **_: seen.append(line))
        forwarder.drain()
        self.assertEqual(seen, ['RETENTION_DIAGNOSTIC_UNAVAILABLE sidecar'])

    def test_partial_and_total_byte_caps(self):
        for initial, raw in ((0, b'x' * MAX_LINE), (MAX_BYTES, b'x')):
            seen = []
            forwarder = RetentionForwarder(io.BytesIO(raw), 42, lambda line, **_: seen.append(line))
            forwarder.bytes = initial
            forwarder.drain()
            self.assertTrue(forwarder.disabled)
            self.assertEqual(seen, ['RETENTION_DIAGNOSTIC_UNAVAILABLE sidecar'])

    def test_explicit_truncation_is_forwarded_once(self):
        raw = event(stage='Telemetry', edge='Observation', status='truncated')
        seen = []
        forwarder = RetentionForwarder(io.BytesIO(raw), 42, lambda line, **_: seen.append(line))
        forwarder.drain()
        forwarder.drain()
        self.assertTrue(forwarder.disabled)
        self.assertEqual(len(seen), 1)
        self.assertIn('"status":"truncated"', seen[0])


if __name__ == '__main__':
    unittest.main()
