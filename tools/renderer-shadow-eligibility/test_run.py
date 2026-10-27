#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('shadow_eligibility', Path(__file__).with_name('run.py'))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blobs = r.fixed(r.ROOT)
        cls.packet, cls.generated, _ = r.preflight(r.ROOT)
        cls.template = Path(__file__).with_name('native.cpp.in').read_text()

    def test_actual_fixture_native_projection(self):
        projection = self.packet['fixture_projection']
        self.assertEqual([(m['slot'], m['material'], m['doubleSided']) for m in projection['models']],
                         [(0, 0, 1), (1, 0, 1)])
        self.assertEqual([m['fields']['toonFlag']['offset'] for m in projection['models']], [1248, 2441])
        self.assertEqual([m['fields']['loadComplete']['value'] for m in projection['models']], [1, 1])
        self.assertEqual([(a['slot'], a['material']) for a in projection['accessories']], [(0, 0)])
        fields = projection['accessories'][0]['fields']
        self.assertEqual([fields[n]['value'] for n in ('visible', 'shadowEnabled', 'additiveBlend')], [1, 1, 0])
        self.assertEqual(fields['diffuse_alpha_text']['projected_f32_bits'], 1065353216)

    def test_every_fixed_blob_mutation_is_rejected(self):
        for path, raw in self.blobs.items():
            with self.subTest(path=path):
                changed = self.blobs | {path: raw[:-1] + bytes([raw[-1] ^ 1])}
                with self.assertRaisesRegex(ValueError, 'drift'):
                    r.validate_blobs(changed)

    def test_missing_blob_rejected(self):
        changed = dict(self.blobs)
        del changed[r.FLOOR]
        with self.assertRaisesRegex(ValueError, 'inventory'):
            r.validate_blobs(changed)

    def test_stored_pmm_fields_cannot_use_initializer(self):
        for offset in [1248, 2441] + [m['fields']['loadComplete']['offset']
                                      for m in self.packet['fixture_projection']['models']]:
            with self.subTest(offset=offset):
                raw = bytearray(self.blobs[r.PMM])
                raw[offset] = 0
                with self.assertRaisesRegex(ValueError, 'raw field'):
                    r.fixture_projection(self.blobs | {r.PMM: bytes(raw)})

    def test_floor_domain_mutations_rejected(self):
        for offset in (2632, 2733, 3146, 3183, 3184):
            with self.subTest(offset=offset):
                raw = bytearray(self.blobs[r.PMM])
                raw[offset] ^= 1
                with self.assertRaises(ValueError):
                    r.fixture_projection(self.blobs | {r.PMM: bytes(raw)})

    def test_fixture_field_offset_is_bound(self):
        fields = self.packet['fixture_projection']['models'][0]['fields']
        row = fields['doubleSided_raw']
        with self.assertRaisesRegex(ValueError, 'raw field'):
            r.binding(self.blobs, row['fixture'], row['offset']+1, row['size'], row['value'], row['assignment'])

    def test_assignment_anchor_is_bound(self):
        path = 'src/model/pmx_load.cpp'
        raw = self.blobs[path].replace(b'mat.doubleSided = (mat.flags & 0x10) != 0;',
                                       b'mat.doubleSided = (mat.flags & 0x01) != 0;')
        with self.assertRaisesRegex(ValueError, 'anchor'):
            r.fixture_projection(self.blobs | {path: raw})

    def test_native_source_inverse_and_spans(self):
        generated, rows, mapping = r.generate(self.blobs, self.template)
        self.assertEqual(generated, self.generated)
        for name, row in mapping.items():
            start, size = row['generated_start'], row['generated_bytes']
            self.assertEqual(r.digest(generated.encode()[start:start+size]), row['sha256'], name)
        self.assertIn('if (indexCount == 0)\n            continue;', rows['model_materials']['text'])
        self.assertIn('firstIndex += indexCount;', rows['model_advance']['text'])
        self.assertLess(generated.index('evaluate_accessories(&inputs);'), generated.index('evaluate_models(&inputs);'))
        self.assertNotIn('device->', generated)
        self.assertNotIn('fx::', generated)
        self.assertNotIn('mme::', generated)

    def test_endpoint_anchor_mutations_rejected(self):
        for path, before in [(r.MODEL, b'firstIndex, indexCount / 3);'),
                             (r.ACCESSORY, b'mme::DrawAccessorySubset(app, accessory, i);')]:
            with self.subTest(path=path):
                raw = self.blobs[path].replace(before, before.replace(b';', b' /* drift */;'))
                with self.assertRaisesRegex(ValueError, 'anchor'):
                    r.extract(self.blobs | {path: raw})

    def test_duplicate_source_anchor_rejected(self):
        rows = r.extract(self.blobs)
        row = rows['model_materials']
        raw = self.blobs[r.MODEL]
        altered = raw[:row['start']] + row['begin'].encode() + raw[row['start']:]
        with self.assertRaisesRegex(ValueError, 'anchor'):
            r.extract(self.blobs | {r.MODEL: altered})

    def test_duplicate_template_anchor_rejected(self):
        with self.assertRaisesRegex(ValueError, 'template anchor'):
            r.generate(self.blobs, self.template + '@MODEL_CULL@')

    def test_omitted_spans_bind_original_bytes(self):
        rows = r.extract(self.blobs)
        spans = r.omitted_spans(self.blobs, rows)
        self.assertTrue(spans)
        for row in spans:
            self.assertGreater(row['end'], row['start'])
            self.assertEqual(r.digest(self.blobs[row['path']][row['start']:row['end']]), row['sha256'])

    def test_wire_preserves_both_domains_and_native_values(self):
        wire = r.native_wire(self.packet)
        self.assertEqual(wire, 'MDS_SHADOW_ELIGIBILITY_V1\n2 1\nM 0 1 1 2 1\n'
                         '42 1065353216 1065353216 30 1\nM 1 1 1 0 1\n'
                         '42 1065353216 0 0 1\nA 0 1 1 0 1\n1065353216\n')

    def test_partial_cannot_claim_capture_or_comparison(self):
        self.assertEqual(self.packet['state'], 'PARTIAL_NOT_A_COMPARISON')
        self.assertEqual(self.packet['conditions']['rust_scene_origin'], 'not_captured')
        self.assertEqual(self.packet['conditions']['native_gpu_draw'], 'not_executed')
        self.assertTrue(self.packet['missing'])
        self.assertNotIn('rust_calls', self.packet)

    def test_strict_json(self):
        for raw in ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":1e999}']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                r.load_json(raw)


if __name__ == '__main__':
    unittest.main()
