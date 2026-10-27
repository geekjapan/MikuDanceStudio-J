#!/usr/bin/env python3
"""Native-free helper checks; all guards must survive python -O."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check

from check import CONTROLS, ROOT, classify, fixed_inputs, mutate, source_paths, witness
from trace import bind_inputs, differences, validate


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


if __name__ == '__main__':
    unittest.main()
