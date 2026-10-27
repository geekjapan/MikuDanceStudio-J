#!/usr/bin/env python3
import importlib.util
import copy
import io
import json
import tarfile
import tempfile
import struct
import zlib
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


import capture as c


class CaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet, _, _ = r.preflight(r.ROOT)
        cls.projection = cls.packet['fixture_projection']
        cls.contract = c.h.contract(r.ROOT)
        lines = ['SH_STEP']*30 + ['SH_SCENE 30 2 1 '+str(len(cls.contract['offsets'])),
            'SH_MODEL 0 0 1 1 chain8.pmx','SH_MODEL 1 1 1 1 chain8.pmd',
            'SH_ACCESSORY 0 0 1 1 0 .\\shadow_floor.x',
            'SH_UPLOAD 0 0 1065353216 1065353216','SH_UPLOAD 1 0 1065353216 0']
        for sample in cls.contract['offsets']:
            shifts = [c.h.fbits(c.struct.unpack('<f',c.struct.pack('<I',p))[0]-c.struct.unpack('<f',c.struct.pack('<I',v))[0]) for p,v in zip(cls.contract['pixel'],sample)]
            lines += ['SH_ENCODE '+' '.join(map(str,shifts))+' 1 2 1',
                'SH_CANDIDATE M 0 0 0 42 30 1065353216','SH_CANDIDATE M 1 0 0 42 30 1065353216',
                'SH_CANDIDATE A 0 0 1065353216 1065353216 1 1 0',
                'SH_DRAW M 0 0 0 42','SH_DRAW M 1 0 0 42','SH_END 2']
        cls.raw = '\n'.join(lines)+'\n'
        cls.native = ('BEGIN MDS_SHADOW_ELIGIBILITY_V1\nCANDIDATE M 0 0\nCANDIDATE A 0 0\nCANDIDATE M 1 0\n'
            'CALL 0 A 0 0 0 0 0\nCALL 1 M 0 0 0 42 1\nCALL 2 M 1 0 0 42 1\nEND 3\n')

    def parse(self, raw=None):
        return c.parse_capture(self.raw if raw is None else raw,self.contract,self.projection)

    def test_capture_all_candidates_and_real_endpoint_record_shape(self):
        result = self.parse()
        self.assertEqual(result['steps'],30)
        self.assertEqual(len(result['encodes']),len(self.contract['offsets']))
        self.assertEqual([v['kind'] for v in result['encodes'][0]['candidates']],['M','M','A'])
        self.assertEqual(len(result['encodes'][0]['draws']),2)

    def test_step_and_seek_negative_controls(self):
        for raw in [self.raw.replace('SH_STEP\n','',1),self.raw.replace('SH_STEP\n','SH_SEEK 30\n',1),self.raw+'SH_STEP\n']:
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                self.parse(raw)

    def test_missing_duplicate_or_unknown_candidate_rejected(self):
        line = 'SH_CANDIDATE A 0 0 1065353216 1065353216 1 1 0\n'
        for raw in [self.raw.replace(line,'',1),self.raw.replace(line,line+line,1),self.raw.replace('SH_CANDIDATE A 0 0','SH_CANDIDATE A 1 0',1),self.raw.replace('SH_MODEL 1 1','SH_MODEL 1 0',1)]:
            with self.assertRaises(ValueError):
                self.parse(raw)

    def test_candidate_and_pose_projection_rejected(self):
        for before,after in [('SH_UPLOAD 0 0 1065353216','SH_UPLOAD 0 0 0'),
                             ('SH_UPLOAD 0 0 1065353216 1065353216','SH_UPLOAD 0 0 1065353216 2139095040'),
                             ('SH_CANDIDATE M 0 0 0 42 30','SH_CANDIDATE M 0 0 0 42 31'),
                             ('SH_ACCESSORY 0 0 1 1 0','SH_ACCESSORY 0 0 0 1 0'),
                             ('SH_MODEL 0 0 1 1','SH_MODEL 0 0 0 1')]:
            with self.subTest(before=before), self.assertRaises(ValueError):
                self.parse(self.raw.replace(before,after,1))

    def test_draw_records_bound_to_identity_and_range(self):
        for after in ['SH_DRAW M 3 0 0 42','SH_DRAW M 0 1 0 42','SH_DRAW M 0 0 1 42',
                      'SH_DRAW M 0 0 0 0','SH_DRAW M 0 0 4294967295 42',
                      'SH_DRAW M 0 0 0 42\nSH_DRAW M 0 0 0 42']:
            with self.subTest(after=after), self.assertRaises(ValueError):
                self.parse(self.raw.replace('SH_DRAW M 0 0 0 42',after,1))

    def test_missing_draw_or_terminal_count_is_invalid(self):
        for raw in [self.raw.replace('SH_DRAW M 0 0 0 42\n','',1),
                    self.raw.replace('SH_END 2\n','',1),
                    self.raw.replace('SH_END 2','SH_END 1',1)]:
            with self.assertRaises(ValueError):
                self.parse(raw)

    def test_missing_duplicate_and_reordered_encode_rejected(self):
        line = next(v for v in self.raw.splitlines() if v.startswith('SH_ENCODE '))
        for raw in [self.raw.replace(line+'\n','',1),self.raw.replace(line,line+'\n'+line,1),self.raw.replace(line,'SH_ENCODE 0 0 1 2 1',1)]:
            with self.assertRaises(ValueError):
                self.parse(raw)

    def test_native_strict_framing_and_normal_exit(self):
        value = c.native_stdout(self.native,0,self.projection)
        self.assertEqual(value['calls'][0],['A',0,0,None,None,None])
        self.assertEqual(value['accessory_range_cull'],'NOT_APPLICABLE')
        for status in [1,2,False,True,101,-1]:
            with self.assertRaises(ValueError):
                c.native_stdout(self.native,status,self.projection)
        for raw in [self.native+'trailing\n',self.native.replace('END 3','END 2'),self.native.replace('CALL 1','CALL 2'),self.native.replace('BEGIN','BAD'),self.native.replace('CALL 0 A 0 0 0 0 0','CALL 0 A 0 0 0 1 0')]:
            with self.assertRaises(ValueError):
                c.native_stdout(raw,0,self.projection)

    def test_native_missing_duplicate_candidates_and_calls_rejected(self):
        for before,after in [('CANDIDATE A 0 0\n',''),('CANDIDATE A 0 0','CANDIDATE M 0 0'),
                             ('CALL 2 M 1 0 0 42 1','CALL 2 M 0 0 0 42 1'),
                             ('CALL 2 M 1 0 0 42 1','CALL 2 M 1 0 0 39 1'),
                             ('CALL 2 M 1 0 0 42 1','CALL 2 M 1 0 0 42 3')]:
            with self.assertRaises(ValueError):
                c.native_stdout(self.native.replace(before,after),0,self.projection)

    def test_conditional_comparison_domain_before_eligibility(self):
        capture = self.parse()
        witness = c.native_stdout(self.native,0,self.projection)
        conditions = r.CONDITIONS | {'rust_scene_origin':'actual_canonical_helper_30_steps'}
        result = c.compare(capture,witness,conditions)
        self.assertEqual(result['state'],'ConditionalEligibilityDifference')
        self.assertEqual(result['first_within_comparison_contract']['boundary'],'eligibility')
        del capture['encodes'][0]['candidates'][-1]
        with self.assertRaises(ValueError):
            c.compare(capture,witness,conditions)
        for key in conditions:
            changed = dict(conditions)
            del changed[key]
            with self.assertRaises(ValueError):
                c.compare(self.parse(),witness,changed)

    def test_source_inverse_endpoint_and_telemetry(self):
        control,observed = c.generated(r.ROOT,False),c.generated(r.ROOT,True)
        self.assertEqual(set(control),{c.h.COMMON})
        renderer = observed[c.h.RENDERER][0]
        self.assertIn(c.DRAW+'                        pass.draw_indexed',renderer)
        self.assertEqual(renderer.count('SH_DRAW M'),1)
        self.assertEqual(renderer.count('SH_CANDIDATE A'),1)
        self.assertEqual(observed[c.h.GOLDEN][0].count('SH_STEP'),1)
        self.assertIn('SAMPLE_ADAPTER',control[c.h.COMMON][0])

    def test_directed_boundaries_are_separate_and_include_index_advance(self):
        cases = c.directed(r,self.packet)
        names = [v['name'] for v in cases]
        self.assertEqual(len(names),len(set(names)))
        self.assertIn('zero-count-and-index-advance',names)
        self.assertIn('model-cull-ccw',names)
        threshold = c.h.fbits(.98)
        for kind in ('model','accessory'):
            for bits in (threshold-1,threshold,threshold+1):
                case = next(v for v in cases if v['name'] == kind+'-alpha-'+str(bits))
                self.assertEqual(bool(case['removed']), bits == threshold)

    def test_tar_rejects_unsafe_duplicate_link_and_modes(self):
        with tempfile.TemporaryDirectory(prefix='shadow-focused-') as temp:
            path = Path(temp)/'test.tar'
            for entries in [[('../bad',0o644,tarfile.REGTYPE)],[('x',0o644,tarfile.SYMTYPE)],
                            [('x',0o666,tarfile.REGTYPE)],[('x',0o644,tarfile.REGTYPE)]*2,
                            [('x',0o644,tarfile.REGTYPE),('x/y',0o644,tarfile.REGTYPE)]]:
                with tarfile.open(path,'w') as tar:
                    for name,mode,kind in entries:
                        info=tarfile.TarInfo(name);info.mode=mode;info.type=kind;info.size=1
                        tar.addfile(info,io.BytesIO(b'x'))
                with self.assertRaises(ValueError):
                    c.safe_tar(path)
            with tarfile.open(path,'w') as tar:
                info=tarfile.TarInfo('bin');info.mode=0o755;info.size=1
                tar.addfile(info,io.BytesIO(b'x'))
            self.assertEqual(c.safe_tar(path)['bin']['mode'],0o755)

    def test_retained_actual_cargo_terminal_fixture(self):
        fixtures = Path(__file__).with_name('fixtures')
        origin = r.load_json((fixtures/'origin.json').read_text())
        raw = (fixtures/'cargo-terminal.jsonl').read_bytes()
        expected = c.portable_cargo(raw,origin['cargo_source'],origin['cargo_target'])
        self.assertEqual(expected,c.h.cargo_binary(raw,origin['cargo_source'],origin['cargo_target']))
        for altered in [raw[:-1],raw+b'{"reason":"build-finished","success":true}\n',
                        raw.replace(b'"success":true',b'"success":false'),
                        raw+b'{"reason":"compiler-message"}\n']:
            with self.assertRaises(ValueError):
                c.portable_cargo(altered,origin['cargo_source'],origin['cargo_target'])

    def test_retained_actual_canonical_stdout_fixture(self):
        fixtures = Path(__file__).with_name('fixtures')
        raw = (fixtures/'canonical.stdout').read_text()+'\n'+(fixtures/'canonical.stderr').read_text()
        self.assertEqual(len(c.h.golden_log(raw,101,self.contract)),14)
        for altered in [raw.replace('11 passed','12 passed'),raw.replace('SAMPLE_ADAPTER','WRONG_ADAPTER',1),raw+'SKIP',raw.replace('selfshadow_30 ... FAILED','selfshadow_30 ... ok')]:
            with self.assertRaises(ValueError):
                c.h.golden_log(altered,101,self.contract)

    def test_missing_endpoint_and_duplicate_insertion_anchor_rejected(self):
        with tempfile.TemporaryDirectory(prefix='shadow-source-focused-') as temp:
            root = Path(temp)
            for name in (c.h.COMMON,c.h.GOLDEN,c.h.RENDERER):
                path = root/name
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes((r.ROOT/name).read_bytes())
            path = root/c.h.RENDERER
            original = path.read_text()
            for changed in [original.replace('                        pass.draw_indexed(m.start..m.start + m.count, 0, 0..1);','                        pass.draw_indexed(m.start..m.start + m.count, 1, 0..1);',1),
                            original.replace('        let mut encoder = self.device.create_command_encoder(&Default::default());\n','        let mut encoder = self.device.create_command_encoder(&Default::default());\n'*2,1)]:
                path.write_text(changed)
                with self.assertRaises(ValueError):
                    c.generated(root,True)

    def test_command_receipt_terminal_and_output_digest(self):
        with tempfile.TemporaryDirectory(prefix='shadow-receipt-focused-') as temp:
            root = Path(temp)
            (root/'native.stdout').write_bytes(b'valid')
            (root/'native.stderr').write_bytes(b'')
            row = {'argv':['fixture-only'],'cwd':'/fixture','env':{},'start_ns':1,'end_ns':2,'status':0,
                   'stdout':{'name':'native.stdout','sha256':r.digest(b'valid'),'size':5},
                   'stderr':{'name':'native.stderr','sha256':r.digest(b''),'size':0}}
            path = root/'native.json'
            path.write_text(json.dumps(row))
            self.assertEqual(c.receipt(root,'native',0)[1],b'valid')
            for changed in [row | {'status':True},row | {'status':1},row | {'end_ns':0},
                            row | {'stdout':row['stdout'] | {'size':4}},
                            row | {'stdout':row['stdout'] | {'sha256':'0'*64}}]:
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    c.receipt(root,'native',0)

    def test_real_png_metric_mask_and_pixel_controls(self):
        def png(pixel):
            def chunk(tag, raw):
                return struct.pack('>I',len(raw))+tag+raw+struct.pack('>I',zlib.crc32(tag+raw))
            return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0'+bytes(pixel)))+chunk(b'IEND',b'')
        with tempfile.TemporaryDirectory(prefix='shadow-image-focused-') as temp:
            root = Path(temp)
            gold = root/'sources/base/tests/fixtures/rust/golden2'
            gold.mkdir(parents=True)
            logs = []
            for test,name in self.contract['gates'].items():
                difference = 49 if test in c.h.FAILURES else 0
                (gold/(name+'.png')).write_bytes(png([0,0,0,255]))
                for variant in ('control','observed'):
                    images = root/variant/'images'
                    images.mkdir(parents=True,exist_ok=True)
                    (images/(name+'.png')).write_bytes(png([difference]*3+[255]))
                    (images/(name+'-diff.png')).write_bytes(png([255-min(255,4*difference)]*3+[255]))
                logs.append(name+': 1 px (0 masked), within 4 '+('0.00000' if difference else '1.00000')+', max '+str(difference)+', mean '+str(difference)+'.0000')
            contract = self.contract | {'dimensions':(1,1)}
            text = '\n'.join(logs)
            self.assertEqual(len(c.images(root,contract,[text,text])),11)
            name = next(iter(contract['gates'].values()))
            path = root/'observed/images'/(name+'.png')
            original = path.read_bytes()
            path.write_bytes(png([1,1,1,255]))
            with self.assertRaises(ValueError):
                c.images(root,contract,[text,text])
            path.write_bytes(original)
            with self.assertRaises(ValueError):
                c.images(root,contract,[text.replace('1 px','2 px',1),text])
            path = root/'observed/images'/(name+'-diff.png')
            path.write_bytes(png([255,0,255,255]))
            with self.assertRaises(ValueError):
                c.images(root,contract,[text,text])

    def test_wire_numbers_and_nonfinite_boundaries(self):
        for raw in ['-1','01','1.0','true','4294967296']:
            with self.assertRaises(ValueError):
                c.words(raw,1)
        for bits in [2139095040,2143289344,-1,4294967296,False]:
            with self.assertRaises(ValueError):
                c.finite(bits)


if __name__ == '__main__':
    unittest.main()
