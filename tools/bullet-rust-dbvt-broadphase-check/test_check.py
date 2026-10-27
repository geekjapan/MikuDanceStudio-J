#!/usr/bin/env python3
"""Native-free helper checks; all guards must survive python -O."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import check

from check import CONTROLS, ROOT, classify, fixed_inputs, mutate, source_paths, witness
from trace import bind_inputs, differences, validate, validate_allocator, validate_profile, LAYOUT_FIELDS


class Helpers(unittest.TestCase):
    def setUp(self):
        self.inputs = 'H 0\n'
        self.row = [0, 0, 'H', [0, 0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 10, 1, 0],
                    [None, None], [[], [], []], [], [], 0, [], [], [[0, -1, 0], [0, -1, 0]], [[[], None], [[], None]]]
    def raw(self, row=None):
        return (json.dumps(self.row if row is None else row) + '\n').encode()
    def test_fixed_corpus_count_and_all_optimization_boundaries(self):
        inputs, manifest = fixed_inputs()
        self.assertEqual(len(inputs.splitlines()), 1193)
        self.assertEqual(len(manifest['histories']), 16)
        names = {h['history'] for h in manifest['histories']}
        for count in [99, 100, 101, 200]:
            self.assertIn('fixed-optimization-' + str(count), names)
    def test_capture_preserves_exact_corpus_bytes_with_host_newlines(self):
        inputs, manifest = fixed_inputs()
        original_open, original_save = Path.open, check.save
        for newline in ['\n', '\r\n']:
            with self.subTest(newline=newline), tempfile.TemporaryDirectory() as folder:
                out = Path(folder)
                def host_open(path, mode='r', *args, **kwargs):
                    if 'b' not in mode and kwargs.get('newline') is None:
                        kwargs['newline'] = newline
                    return original_open(path, mode, *args, **kwargs)
                def stop_after_manifest(path, value):
                    original_save(path, value)
                    if path.name == 'manifest.json':
                        raise RuntimeError('capture boundary reached')
                with patch.object(Path, 'open', host_open):
                    probe = out / 'newline-probe.txt'
                    probe.write_text('H 0\n')
                    self.assertEqual(probe.read_bytes(), ('H 0' + newline).encode())
                    with patch.object(check.sys, 'argv', ['check.py', '--out-dir', str(out),
                                                         '--policy', 'mmd-win64-sse']), \
                            patch.object(check, 'snapshot', return_value={}), \
                            patch.object(check, 'save', side_effect=stop_after_manifest), \
                            patch.object(check.subprocess, 'run') as run:
                        with self.assertRaisesRegex(RuntimeError, 'capture boundary reached'):
                            check.main()
                        run.assert_not_called()
                archived = (out / 'inputs.txt').read_bytes()
                self.assertEqual(archived, inputs.encode())
                self.assertNotIn(b'\r', archived)
                self.assertEqual(check.digest(archived), manifest['sha256'])
    def test_empty_native_rank_binding_and_strict_equality(self):
        rows = validate(self.raw(), self.inputs, True)
        self.assertEqual(bind_inputs(self.inputs, rows), 'H 0\nB 0 - 0 -\n')
        rust = copy.deepcopy(self.row)
        rust[12] = None
        self.assertEqual(differences(rows, validate(self.raw(rust), self.inputs, False)), [])
    def test_malformed_capture_never_counts_as_semantic_control(self):
        for raw in [b'', b'{}\n', b'[]\n', self.raw() * 2, b'[NaN]\n', self.raw()[:-2]]:
            with self.subTest(raw=raw), self.assertRaises((ValueError, TypeError)):
                validate(raw, self.inputs, True)
    def test_wrong_checkpoint_and_unknown_fields_reject(self):
        for index, value in [(0, 1), (1, 1), (2, 'c'), (3, [0]), (4, []), (5, []), (6, {}), (7, {}), (9, {}), (10, {})]:
            row = copy.deepcopy(self.row)
            row[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate(self.raw(row), self.inputs, True)
    def test_integer_bool_overflow_and_rank_coverage_reject(self):
        for value in [True, -1, 1 << 32, '0']:
            row = copy.deepcopy(self.row)
            row[3][0] = value
            with self.assertRaises(ValueError):
                validate(self.raw(row), self.inputs, True)
        for nodes, free in [([[0, 0, *([0] * 6)]], None), ([[0, 1, *([0] * 6)]], 1)]:
            row = copy.deepcopy(self.row)
            row[12][0] = [nodes, free]
            with self.assertRaises(ValueError):
                validate(self.raw(row), self.inputs, True)
    def test_actual_preprocessed_policy_classification(self):
        def text(sse):
            a = '_mm_cmplt_ps(a,b);' if sse else 'return a.mi.x() <= b.mx.x();'
            b = '_mm_cmple_ss(a,b);' if sse else 'return Proximity(o,a)<Proximity(o,b);'
            c = '_mm_min_ps(a,b);' if sse else 'r=a;'
            return f'bool Intersect(const btDbvtAabbMm& a,const btDbvtAabbMm& b){{{a}}}\nint Select(const btDbvtAabbMm& o,const btDbvtAabbMm& a,const btDbvtAabbMm& b){{{b}}}\nvoid Merge(const btDbvtAabbMm& a,const btDbvtAabbMm& b,btDbvtAabbMm& r){{{c}}}'
        self.assertEqual(classify(text(False))['policy'], 'generic-reference')
        self.assertEqual(classify(text(True))['policy'], 'mmd-win64-sse')
        for broken in [text(True).replace('_mm_cmple_ss', 'unknown'), text(False) + text(False), text(False)[:-1]]:
            with self.assertRaises(ValueError):
                classify(broken)
    def test_every_compiled_semantic_control_has_one_exact_source_anchor(self):
        for name in CONTROLS:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                for path in ['rust/crates/mds-bullet/src/core/dbvt.rs', 'rust/crates/mds-bullet/src/core/dbvt_broadphase.rs']:
                    target = root / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((ROOT / path).read_bytes())
                change = mutate(root, name)
                self.assertNotEqual(change['before'], change['after'])
    def test_direct_crt_lib_and_transitive_modules_are_in_source_closure(self):
        paths = {p.relative_to(ROOT).as_posix() for p in source_paths()}
        for name in ['lib', 'digest', 'explog', 'inv', 'tables', 'trig']:
            self.assertIn('rust/crates/mds-crtmath/src/' + name + '.rs', paths)
    def test_order_control_requires_a_create_checkpoint_witness(self):
        with self.assertRaises(ValueError):
            witness('order', [self.row], [self.row])
        changed = copy.deepcopy(self.row)
        changed[7] = [[1, 2, 0]]
        with self.assertRaises(ValueError):
            witness('order', [self.row], [changed])


class AllocatorReceipts(unittest.TestCase):
    def fixture(self, mode='ascending', node_bytes=64):
        base = 1 << 24
        slots = {'ascending': [0, 1], 'descending': [65535, 65534], 'alternating': [0, 65535], 'ordinary': [0, 1]}[mode]
        pointers = [base + slot * 128 for slot in slots]
        controlled = mode != 'ordinary'
        header = dict(schema=1, mode=mode, hooks=controlled, arena_base=base, slots=65536,
                      stride=128, arena_alignment=64, pointer_bytes=8, node_bytes=node_bytes, node_alignment=16,
                      node_type_alignment=8 if node_bytes == 56 else 16, node_volume_offset=0,
                      node_parent_offset=32, node_childs_offset=40, raw_node_bytes=node_bytes+23,
                      bt_has_aligned_allocator=False, bt_debug_memory_allocations=False, cellos_lv2=False)
        def event(op, ordinal, pointer):
            value = dict(op=op, route='raw', ordinal=ordinal, pointer=pointer)
            if op == 'alloc':
                value.update(size=node_bytes+23, alignment=0)
            return value
        def record(index, events, counters):
            return dict(kind='checkpoint', identity=[0, index, 'H' if index == 0 else 'p'],
                        events=events if controlled else [], counters=counters if controlled else [0]*4)
        records = [header,
                   record(0, [event('alloc', 2, pointers[0]), event('alloc', 3, pointers[1])], [3, 0, 0, 0]),
                   record(1, [], [3, 0, 0, 0]),
                   record(2, [], [3, 0, 0, 0]),
                   dict(kind='trailer', events=[event('free', 1, pointers[0]), event('free', 2, pointers[1])]
                        if controlled else [], counters=[3, 3, 0, 0] if controlled else [0]*4)]
        node = lambda p: [0, p + 16 if controlled else p + (1 << 28), *([0]*6)]
        rows = [[0, i, 'H' if i == 0 else 'p', *([None]*9), [[[node(pointers[1])], pointers[0]+16 if controlled else pointers[0]+(1 << 28)], [[], None]]]
                for i in range(3)]
        rows[1][12][0] = [[node(pointers[0]), node(pointers[1])], None]
        rows[2][12] = [[[], None], [[], None]]
        return records, rows
    def profile(self, node_bytes=64, policy='generic-reference'):
        header = self.fixture(node_bytes=node_bytes)[0][0]
        return dict(pointer_bits=64, prevent_false_update=0, accurate_sleeping=0, margin_bits=1028443341,
                    bt_use_sse=policy == 'mmd-win64-sse', win32=policy == 'mmd-win64-sse',
                    **{key: header[key] for key in LAYOUT_FIELDS})
    def check(self, records, rows, mode='ascending', profile=None):
        if profile is None:
            profile = self.profile(56 if records[0].get('node_bytes') == 56 else 64)
        return validate_allocator(('\n'.join(json.dumps(r) for r in records)+'\n').encode(), rows, mode, profile)
    def test_actual_raw_callbacks_cached_reuse_and_final_frees(self):
        for node_bytes in [56, 64]:
            for mode in ['ascending', 'descending', 'alternating', 'ordinary']:
                with self.subTest(mode=mode, node_bytes=node_bytes):
                    records, rows = self.fixture(mode, node_bytes)
                    result = self.check(records, rows, mode)
                    self.assertEqual(result['allocations'], 0 if mode == 'ordinary' else 2)
                    self.assertEqual(result['cache_reuse'], True)
    def test_profile_and_header_layout_must_match_exactly(self):
        for node_bytes in [56, 64]:
            profile = self.profile(node_bytes)
            self.assertEqual(validate_profile(json.dumps(profile), 'generic-reference'), profile)
            records, rows = self.fixture(node_bytes=node_bytes)
            for key in LAYOUT_FIELDS:
                broken = copy.deepcopy(profile)
                broken[key] = not profile[key] if type(profile[key]) is bool else profile[key] + 1
                with self.subTest(node_bytes=node_bytes, key=key), self.assertRaises(ValueError):
                    self.check(records, rows, profile=broken)
            other = self.profile(64 if node_bytes == 56 else 56)
            with self.assertRaisesRegex(ValueError, 'header matches native profile'):
                self.check(records, rows, profile=other)
    def test_strict_profile_and_bounded_layout_reject(self):
        for node_bytes in [56, 64]:
            profile = self.profile(node_bytes)
            for key in profile:
                changes = [lambda p, k=key: p.pop(k), lambda p, k=key: p.update({k: True if type(p[k]) is int else 1})]
                if key in LAYOUT_FIELDS - {'bt_has_aligned_allocator', 'bt_debug_memory_allocations', 'cellos_lv2'}:
                    changes += [lambda p, k=key: p.update({k: p[k]+1})]
                for change in changes:
                    broken = copy.deepcopy(profile)
                    change(broken)
                    with self.subTest(node_bytes=node_bytes, key=key), self.assertRaises(ValueError):
                        validate_profile(json.dumps(broken), 'generic-reference')
            for raw in [b'{}', b'[]', b'NaN', json.dumps(dict(profile, extra=1)).encode(),
                        json.dumps(profile).replace('"pointer_bits": 64', '"pointer_bits": 64, "pointer_bits": 64').encode()]:
                with self.assertRaises(ValueError):
                    validate_profile(raw, 'generic-reference')
            records, rows = self.fixture(node_bytes=node_bytes)
            for key in LAYOUT_FIELDS:
                for value in [True, None, 1 << 64]:
                    broken = copy.deepcopy(records)
                    broken[0][key] = value
                    with self.subTest(node_bytes=node_bytes, key=key, value=value), self.assertRaises(ValueError):
                        self.check(broken, rows)
                broken = copy.deepcopy(records)
                broken[0].pop(key)
                with self.assertRaises(ValueError):
                    self.check(broken, rows)
            for request in [79 if node_bytes == 64 else 87, True, 128, 1 << 64]:
                broken = copy.deepcopy(records)
                broken[1]['events'][0]['size'] = request
                with self.assertRaises(ValueError):
                    self.check(broken, rows)
    def test_both_layouts_retain_counter_history_and_live_bounds(self):
        for node_bytes in [56, 64]:
            for mode in ['ascending', 'descending', 'alternating']:
                records, rows = self.fixture(mode, node_bytes)
                broken = copy.deepcopy(records)
                for record in broken[1:-1]:
                    record['counters'] = [3, 3, 0, 0]
                with self.subTest(node_bytes=node_bytes, mode=mode), self.assertRaisesRegex(ValueError, 'counter history'):
                    self.check(broken, rows, mode)
                for pointer in [records[0]['arena_base']+65536*128+16, rows[0][12][0][1]+128,
                                rows[0][12][0][1]-1]:
                    broken_rows = copy.deepcopy(rows)
                    broken_rows[0][12][0][1] = pointer
                    with self.subTest(node_bytes=node_bytes, mode=mode, pointer=pointer), self.assertRaises(ValueError):
                        self.check(records, broken_rows, mode)
                broken = copy.deepcopy(records)
                broken[0]['node_bytes'] = 128
                broken[0]['raw_node_bytes'] = 151
                with self.assertRaises(ValueError):
                    self.check(broken, rows, mode)
    def test_receipt_and_checkpoint_schema_reject(self):
        records, rows = self.fixture()
        for raw in [b'', b'{}', b'NaN', b'{}\n'*5]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate_allocator(raw, rows, 'ascending', self.profile())
        changes = [lambda r: r.pop(), lambda r: r.append(r[-1]),
                   lambda r: r.__setitem__(2, copy.deepcopy(r[1])),
                   lambda r: r[1]['identity'].__setitem__(1, True),
                   lambda r: r[1].update(extra=1), lambda r: r[0].update(extra=1),
                   lambda r: r[0].update(mode='unknown'), lambda r: r[0].update(schema=True),
                   lambda r: r[0].update(hooks=1), lambda r: r[0].update(bt_has_aligned_allocator=True),
                   lambda r: r[0].update(bt_debug_memory_allocations=True), lambda r: r[0].update(cellos_lv2=True),
                   lambda r: r[0].update(node_bytes=56), lambda r: r[0].update(pointer_bytes=4),
                   lambda r: r[0].update(arena_base=(1 << 64)-64), lambda r: r[0].update(arena_base=(1 << 24)+16),
                   lambda r: r[0].update(stride=64), lambda r: r[0].update(slots=65535),
                   lambda r: r[1]['counters'].__setitem__(0, True),
                   lambda r: r[1]['counters'].__setitem__(0, 1 << 64),
                   lambda r: r[2]['counters'].__setitem__(0, 2),
                   lambda r: r[2]['counters'].__setitem__(2, 1),
                   lambda r: r[1]['events'][0].update(route='aligned'),
                   lambda r: r[1]['events'][0].update(size=64),
                   lambda r: r[1]['events'][0].update(alignment=16),
                   lambda r: r[1]['events'][0].update(ordinal=0),
                   lambda r: r[1]['events'][0].update(ordinal=4),
                   lambda r: r[1]['events'][1].update(ordinal=2),
                   lambda r: r[1]['events'][1].update(pointer=1 << 24),
                   lambda r: r[1]['events'][0].update(pointer=(1 << 24)+128),
                   lambda r: r[1]['events'][0].update(pointer=True),
                   lambda r: r[-1]['events'][0].update(pointer=(1 << 24)+256),
                   lambda r: r[-1]['events'][1].update(pointer=1 << 24),
                   lambda r: r[-1]['events'].pop(),
                   lambda r: r[-1]['counters'].__setitem__(1, 2)]
        for index, change in enumerate(changes):
            broken = copy.deepcopy(records)
            change(broken)
            with self.subTest(mutation=index), self.assertRaises(ValueError):
                self.check(broken, rows)
        encoded = ('\n'.join(json.dumps(r) for r in records)+'\n').replace('"schema": 1', '"schema": 1, "schema": 1')
        with self.assertRaisesRegex(ValueError, 'duplicate receipt field'):
            validate_allocator(encoded.encode(), rows, 'ascending', self.profile())
        with self.assertRaises(ValueError):
            self.check(records, rows, 'unknown')
    def test_checkpoint_counters_must_cover_live_arena_allocations(self):
        records, rows = self.fixture()
        for record in records[1:-1]:
            record['counters'] = [3, 3, 0, 0]
        records[-1]['counters'] = [5, 5, 0, 0]
        for ordinal, event in enumerate(records[-1]['events'], 4):
            event['ordinal'] = ordinal
        with self.assertRaisesRegex(ValueError, 'allocator counter history'):
            self.check(records, rows)
    def test_ordered_callbacks_must_have_a_feasible_prefix(self):
        for next_allocation, valid in [(2, False), (101, True)]:
            records, rows = self.fixture()
            first, second = records[1]['events']
            third = copy.deepcopy(first)
            third.update(ordinal=next_allocation+1, pointer=first['pointer']+256)
            first['ordinal'] = 1
            second['ordinal'] = next_allocation
            free = copy.deepcopy(records[-1]['events'][0])
            free['ordinal'] = 100
            records[1]['events'] = [first, free, second, third]
            for record in records[1:-1]:
                record['counters'] = [102, 100, 0, 0]
            for row in rows:
                for nodes, _ in row[12]:
                    for node in nodes:
                        if node[1] == first['pointer']+16:
                            node[1] = third['pointer']+16
                if row[12][0][1] is not None:
                    row[12][0][1] = third['pointer']+16
            records[-1]['counters'] = [102, 102, 0, 0]
            records[-1]['events'][0].update(pointer=third['pointer'], ordinal=101)
            records[-1]['events'][1]['ordinal'] = 102
            with self.subTest(valid=valid):
                if valid:
                    self.assertEqual(self.check(records, rows)['allocations'], 3)
                else:
                    with self.assertRaisesRegex(ValueError, 'allocator callback ordinal/delta'):
                        self.check(records, rows)
    def test_trailer_prefix_allows_only_feasible_hidden_fallbacks(self):
        for ordinal, valid in [(4, False), (102, True)]:
            records, rows = self.fixture()
            first, second = records[-1]['events']
            first['ordinal'] = 100
            second['ordinal'] = 101
            allocation = copy.deepcopy(records[1]['events'][0])
            allocation.update(ordinal=ordinal, pointer=allocation['pointer']+256)
            final_free = copy.deepcopy(first)
            final_free.update(ordinal=102, pointer=allocation['pointer'])
            records[-1].update(counters=[102, 102, 0, 0], events=[first, allocation, second, final_free])
            with self.subTest(valid=valid):
                if valid:
                    self.assertEqual(self.check(records, rows)['allocations'], 3)
                else:
                    with self.assertRaisesRegex(ValueError, 'allocator callback ordinal/delta'):
                        self.check(records, rows)
    def test_checkpoint_boundary_preserves_hidden_fallback_balance(self):
        for outstanding, valid in [(1, False), (2, True), (3, True)]:
            records, rows = self.fixture()
            records[2]['counters'] = [103, 103-outstanding, 0, 0]
            records[3]['counters'] = records[2]['counters'].copy()
            records[-1]['counters'] = [105, 105, 0, 0]
            records[-1]['events'][0]['ordinal'] = 104
            records[-1]['events'][1]['ordinal'] = 105
            with self.subTest(outstanding=outstanding):
                if valid:
                    self.assertEqual(self.check(records, rows)['allocations'], 2)
                else:
                    with self.assertRaisesRegex(ValueError, 'allocator counter history'):
                        self.check(records, rows)
    def test_initial_hidden_fallback_free_can_precede_arena_allocations(self):
        for mode in ['ascending', 'descending', 'alternating']:
            records, rows = self.fixture(mode)
            for record in records[1:-1]:
                record['counters'][1] = 1
            for event in records[-1]['events']:
                event['ordinal'] += 1
            with self.subTest(mode=mode):
                self.assertEqual(self.check(records, rows, mode)['allocations'], 2)
    def test_live_and_cached_nodes_require_live_unique_exact_arena_allocations(self):
        records, rows = self.fixture()
        for field in ['live', 'cached']:
            for pointer in [0, True, (1 << 64), (1 << 24)+17, (1 << 24)+256+16, (1 << 28)]:
                broken = copy.deepcopy(rows)
                if field == 'live':
                    broken[0][12][0][0][0][1] = pointer
                else:
                    broken[0][12][0][1] = pointer
                with self.subTest(field=field, pointer=pointer), self.assertRaises(ValueError):
                    self.check(records, broken)
        broken = copy.deepcopy(rows)
        broken[0][12][1][1] = broken[0][12][0][1]
        with self.assertRaisesRegex(ValueError, 'unique live and cached'):
            self.check(records, broken)
        broken = copy.deepcopy(rows)
        broken[0][12][0][1] = broken[0][12][0][0][0][1]
        with self.assertRaises(ValueError):
            self.check(records, broken)
        broken = copy.deepcopy(records)
        broken[1]['events'] = []
        with self.assertRaises(ValueError):
            self.check(broken, rows)
        broken = copy.deepcopy(records)
        freed = broken[-1]['events'].pop(0)
        broken[2]['events'] = [freed]
        broken[2]['counters'][1] = 1
        broken[3]['counters'][1] = 1
        with self.assertRaises(ValueError):
            self.check(broken, rows)
        broken = copy.deepcopy(rows)
        broken[1][12][0] = copy.deepcopy(broken[0][12][0])
        with self.assertRaisesRegex(ValueError, 'genuine cached-free'):
            self.check(records, broken)
    def test_replay_requires_each_receipt_before_binding_or_ordinary_comparison(self):
        inputs = 'H 0\np\np\n'
        helper = Helpers()
        helper.setUp()
        plain = []
        for i, op in enumerate(['H', 'p', 'p']):
            row = copy.deepcopy(helper.row)
            row[:3] = [0, i, op]
            row[12] = None
            plain.append(row)
        rust_raw = ('\n'.join(json.dumps(r) for r in plain)+'\n').encode()
        for missing in [*check.MODES, 'profile-layout', 'profile-schema', 'profile-missing']:
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as folder:
                capture, out = Path(folder)/'capture', Path(folder)/'out'
                capture.mkdir()
                check.save(capture/'report.json', dict(status='CONTROLLED_PASS', policy='mmd-win64-sse', host=dict(system='Windows')))
                check.save(capture/'artifact-manifest.json', {})
                if missing != 'profile-missing':
                    profile = self.profile(56 if missing == 'profile-layout' else 64, policy='mmd-win64-sse')
                    if missing == 'profile-schema':
                        profile.pop('node_type_alignment')
                    check.save(capture/'actual-macros.json', profile)
                check.save(capture/'source-canonical.json', {})
                (capture/'inputs.txt').write_bytes(inputs.encode())
                for mode in check.MODES:
                    records, nodes = self.fixture(mode)
                    native = copy.deepcopy(plain)
                    for row, node_row in zip(native, nodes):
                        row[12] = node_row[12]
                    (capture/('native-'+mode+'.stdout')).write_text('\n'.join(json.dumps(r) for r in native)+'\n')
                    if mode != missing:
                        (capture/('allocator-'+mode+'.jsonl')).write_text('\n'.join(json.dumps(r) for r in records)+'\n')
                def run(argv, **kwargs):
                    return SimpleNamespace(returncode=0, stdout=rust_raw if 'rust-broadphase' in str(argv[0]) else b'', stderr=b'')
                with patch.object(check.sys, 'argv', ['check.py', '--out-dir', str(out), '--policy', 'mmd-win64-sse', '--replay-dir', str(capture)]), \
                        patch.object(check, 'snapshot', return_value={}), \
                        patch.object(check, 'fixed_inputs', return_value=(inputs, {'checkpoints': 3})), \
                        patch.object(check.subprocess, 'run', side_effect=run), \
                        patch.object(check, 'bind_inputs', wraps=bind_inputs) as bind, \
                        patch.object(check, 'differences', wraps=differences) as compare:
                    error = 'required allocator receipt: '+missing
                    if missing.startswith('profile-'):
                        error = {'profile-layout': 'header matches native profile',
                                 'profile-schema': 'native profile schema',
                                 'profile-missing': 'actual-macros.json'}[missing]
                    with self.assertRaisesRegex(FileNotFoundError if missing == 'profile-missing' else ValueError, error):
                        check.main()
                    count = check.MODES.index(missing) if missing in check.MODES else 0
                    self.assertEqual(bind.call_count, count)
                    self.assertEqual(compare.call_count, count)
    def test_zero_callbacks_and_ordinary_hook_claims_reject(self):
        records, rows = self.fixture()
        for r in records[1:]:
            r['events'] = []
            r['counters'] = [0]*4
        for row in rows:
            row[12] = [[[], None], [[], None]]
        with self.assertRaisesRegex(ValueError, 'nonzero raw'):
            self.check(records, rows)
        for change in [lambda r: r[0].update(hooks=True),
                       lambda r: r[1]['counters'].__setitem__(0, 1),
                       lambda r: r[1]['events'].append(dict(op='free', route='raw', ordinal=1, pointer=1))]:
            records, rows = self.fixture('ordinary')
            change(records)
            with self.assertRaises(ValueError):
                self.check(records, rows, 'ordinary')
        records, rows = self.fixture('ordinary')
        rows[0][12][0][1] = records[0]['arena_base']+16
        with self.assertRaises(ValueError):
            self.check(records, rows, 'ordinary')


if __name__ == '__main__':
    unittest.main()
