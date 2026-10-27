import copy
import importlib.util
import json
from pathlib import Path
import struct
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zlib

spec = importlib.util.spec_from_file_location('center_check', Path(__file__).with_name('check.py'))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def golden_raw(failed=3):
    tests = sorted(check.TESTS)
    return '\n'.join(f'test {name} ... {"FAILED" if i < failed else "ok"}' for i, name in enumerate(tests)) + (
        f'\ntest result: {"FAILED" if failed else "ok"}. {14-failed} passed; {failed} failed; 0 ignored; 0 measured; 0 filtered out;\n')


def calibration_raw(candidate):
    rows = []
    for helper in ('center_uv', 'center_world', 'center_value'):
        for case in sorted(check.CASES):
            reference, old = check.calibration_models(case)
            actual = reference if candidate else old[0]
            channels = 2 if helper == 'center_uv' else 3
            dist = lambda a, b: max(abs(a[c]-b[c]) for c in range(channels))
            row = {'helper': helper, 'case': case, 'actual': actual, 'reference': reference,
                   'new_error': dist(actual, reference), 'old_error': min(dist(actual, p) for p in old),
                   'separation': min(dist(reference, p) for p in old),
                   'tolerance': .00005, 'candidate': candidate}
            rows.append('CENTER_CAL ' + json.dumps(row))
    return '\n'.join(rows) + '\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n'


def png(pixels, width=2, height=2):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind+data))
    raw = b''.join(b'\0' + bytes(sum(pixels[y*width:(y+1)*width], ())) for y in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


class Boundaries(unittest.TestCase):
    def test_png_crc_truncation_and_format(self):
        pixels = [(1, 2, 3, 255)]*4
        raw = png(pixels)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'tiny.png'
            path.write_bytes(raw)
            self.assertEqual(check.read_png(path, (2, 2)), pixels)
            for bad in (raw[:-1], raw + b'X', raw[:40] + bytes([raw[40] ^ 1]) + raw[41:], raw[:8]):
                path.write_bytes(bad)
                with self.assertRaises(ValueError):
                    check.read_png(path, (2, 2))
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                check.read_png(path)

    def test_expected_failed_gates_are_valid_execution(self):
        self.assertEqual(check.golden_log(golden_raw(), 101)['failed'], 3)
        self.assertEqual(check.golden_log(golden_raw(0), 0)['passed'], 14)
        for raw, code in [(golden_raw(), 0), (golden_raw()+'SKIP', 101), (golden_raw().replace('0 ignored', '1 ignored'), 101),
                          (golden_raw().replace('0 filtered out', '1 filtered out'), 101),
                          (golden_raw()+golden_raw(), 101), (golden_raw().replace('test accessory_0', 'test skin_0'), 101),
                          (golden_raw()+'Validation Error', 101)]:
            with self.assertRaises(ValueError):
                check.golden_log(raw, code)

    def test_calibration_requires_all_finite_distinct_rows(self):
        for candidate in (False, True):
            raw = calibration_raw(candidate)
            self.assertEqual(len(check.calibration(raw, candidate)), 24)
            for bad in (raw.replace('CENTER_CAL ', '', 1), raw+raw.splitlines()[0]+'\n',
                        raw.replace('\"tolerance\": 5e-05', '\"tolerance\": NaN', 1), raw.replace('\"tolerance\": 5e-05', '\"tolerance\": Infinity', 1),
                        raw.replace('5e-05', '0.5', 1), raw.replace('"separation": 0.0', '"separation": -1.0', 1),
                        raw.replace('"new_error": 0.0', '"new_error": 1.0') if candidate else raw.replace('"old_error": 0.0', '"old_error": 1.0')):
                with self.assertRaises(ValueError):
                    check.calibration(bad, candidate)
            with self.assertRaises(ValueError):
                check.calibration(raw, not candidate)

    def test_adapter_and_json_boundaries(self):
        raw = 'CENTER_ADAPTER llvmpipe (LLVM)|Vulkan\n'*14
        self.assertIn('llvmpipe', check.adapters(raw, 14))
        for bad in (raw[:-1].rsplit('\n', 1)[0], raw.replace('llvmpipe', 'hardware', 1), raw.replace('|Vulkan', '|Metal')):
            with self.assertRaises(ValueError):
                check.adapters(bad, 14)
        for bad in ('{"x":1,"x":2}', '{"x": NaN}', '{"x": Infinity}', '{'):
            with self.assertRaises(ValueError):
                check.load_json(bad)

    def test_image_analysis_recomputes_changes_and_checks_diff(self):
        size = 640*360
        gold = [(0, 0, 0, 255)]*size
        before = gold.copy()
        before[0] = (5, 0, 0, 255)
        after = gold.copy()
        after[1] = (2, 0, 0, 255)
        mask_at = 2
        def image(path):
            path = Path(path)
            is_a = path.parent.name == 'A'
            if path.name.endswith('-diff.png'):
                pixels = before if is_a else after
                result = [(255-min(255,4*max(p[:3])),)*3+(255,) for p in pixels]
                result[mask_at] = (255, 0, 255, 255)
                return result
            return gold if path.parent.name == 'gold' else before if is_a else after
        name = 'skin-0'
        logs = []
        for pixels in (before, after):
            ds = [max(p[:3]) for i, p in enumerate(pixels) if i != mask_at]
            score = check.metrics(ds)
            logs.append(f"test skin_0 ... ok\n{name}: {len(ds)} px (1 masked), within 4 {score['close']:.5f}, max {score['max']}, mean {score['mean']:.4f}\n")
        with patch.object(check, 'NAMES', [name]), patch.object(check, 'read_png', side_effect=image):
            row = check.analyze_images(Path('A'), Path('B'), Path('gold'), logs)[0]
            self.assertEqual((row['changed'], row['improved'], row['worsened']), (2, 1, 1))
            self.assertEqual((row['whole_frame_A']['over4'], row['change_max']), (1, 5))
            self.assertEqual(len(row['fixed_points']), 2)
            with self.assertRaisesRegex(ValueError, 'score mismatch'):
                check.analyze_images(Path('A'), Path('B'), Path('gold'), [logs[0].replace('max 5', 'max 9'), logs[1]])

    def test_whole_frame_metrics_keep_original_gate(self):
        self.assertEqual(check.metrics([0]*9999+[4])['gate'], 'PASS')
        self.assertEqual(check.metrics([0]*9999+[49])['gate'], 'FAIL')
        self.assertEqual(check.metrics([0]*9998+[5, 5])['gate'], 'FAIL')


def fixture(directory):
    root = Path(directory)
    adapter = 'llvmpipe (inert fixture)|Vulkan'
    env = {'VK_ICD_FILENAMES': str(root/'icd.json'), 'WGPU_BACKEND': 'vulkan'}
    def record(label, stdout='', stderr='', argv=None, cwd=None, environment=None, status=0):
        out, err = root/(label+'.stdout'), root/(label+'.stderr')
        out.write_text(stdout)
        err.write_text(stderr)
        return {'argv': argv or [label], 'cwd': str(cwd or root), 'env': environment or env,
                'start_ns': 1, 'end_ns': 2, 'status': status, 'stdout': check.file_id(out), 'stderr': check.file_id(err)}
    def identity(name, text):
        p = root/name
        p.write_text(text)
        return check.file_id(p)
    host = {'icd': identity('icd.json', '{}'), 'libraries': [identity('lib.so', 'inert')],
            'commands': [record('version', 'rustc 1.95.0'), record('vulkan', adapter)]}
    variants = []
    revision = '1'*40
    for variant in ('A', 'B'):
        source = root/variant
        (source/Path(check.SHADER).parent).mkdir(parents=True)
        (source/check.SHADER).write_text('control' if variant == 'A' else 'candidate')
        (source/'immutable.txt').write_text('inert')
        sources = check.snapshot(source)
        archive = root/(variant+'.tar')
        with tarfile.open(archive, 'w', format=tarfile.PAX_FORMAT, pax_headers={'comment': revision}) as tar:
            for name in sources:
                tar.add(source/name, arcname=name)
        image_dir = root/(variant+'-images')
        image_dir.mkdir()
        for name in check.NAMES:
            for suffix in ('.png', '-diff.png'):
                (image_dir/(name+suffix)).write_bytes(b'inert fixture')
        venv = env | {'CARGO_TARGET_DIR': str(root/('target-'+variant))}
        cargo_rows, executables = [], {}
        for target, key in [('golden2', 'golden2'), ('center_reconstruction', 'calibration')]:
            retained = identity(variant+'-'+target, variant+' inert executable '+target)
            cargo_path = str(root/('target-'+variant)/target)
            cargo_rows.append(json.dumps({'reason': 'compiler-artifact', 'target': {'name': target}, 'executable': cargo_path}))
            executables[key] = {'cargo_path': cargo_path, 'retained': retained}
        build_argv = ['cargo', '+1.95.0', 'test', '-p', 'mds-render', '--test', 'golden2', '--test',
                      'center_reconstruction', '--no-run', '--locked', '--message-format=json', '-vv']
        v = {'variant': variant, 'source_root': str(source), 'sources': sources, 'source_archive': check.file_id(archive),
             'inputs': {}, 'build_target': venv['CARGO_TARGET_DIR'], 'executables': executables, 'adapter': adapter,
             'image_dir': str(image_dir), 'images': check.snapshot(image_dir),
             'build': record(variant+'-build', '\n'.join(cargo_rows), argv=build_argv, cwd=source/'rust', environment=venv)}
        for key, raw, code, count in [('golden2', golden_raw(), 101, 14), ('calibration', calibration_raw(variant=='B'), 0, 1)]:
            v[key] = record(variant+'-'+key, raw, '\n'.join(['CENTER_ADAPTER '+adapter]*count)+'\n',
                            argv=[executables[key]['retained']['path'], '--include-ignored', '--nocapture', '--test-threads=1'],
                            cwd=source/'rust', environment=venv | ({'MDS_RENDER_PNG_DIR': str(image_dir)} if key=='golden2' else {}), status=code)
        variants.append(v)
    return {'schema': 1, 'base': check.BASE, 'candidate_commit': revision, 'candidate_shader_sha256': check.digest(b'candidate'),
            'baseline_description': 'candidate sources with exact fixed BASE shader', 'host': host, 'variants': variants,
            'candidate_archive': variants[1]['source_archive'],
            'git_delta': record('git-delta', check.SHADER+'\n', argv=['git', 'diff', '--name-only', check.BASE, revision])}


class ManifestControls(unittest.TestCase):
    def test_retained_evidence_can_be_replayed_after_relocation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(check, 'BASE_SHADER_SHA256', check.digest(b'control')), \
             patch.object(check, 'analyze_images', return_value=[]):
            original = Path(directory)/'original'
            original.mkdir()
            manifest = fixture(original)
            relocated = Path(directory)/'downloaded'
            shutil.move(original, relocated)
            with patch.object(check, 'RELOCATION', (original, relocated)):
                self.assertEqual(check.verify(manifest)['status'], 'VALID_EXPERIMENT')

    def test_inert_complete_pair_and_malformed_controls(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(check, 'BASE_SHADER_SHA256', check.digest(b'control')), \
             patch.object(check, 'analyze_images', return_value=[]) as images:
            manifest = fixture(directory)
            self.assertEqual(check.verify(manifest)['status'], 'VALID_EXPERIMENT')
            images.assert_called_once()
            mutations = [
                lambda m: m.update(base='0'*40),
                lambda m: m.update(candidate_commit='2'*40),
                lambda m: m['variants'].append(m['variants'][0]),
                lambda m: m['variants'][1].update(adapter='other'),
                lambda m: m['variants'][1].update(build_target=m['variants'][0]['build_target']),
                lambda m: m['variants'][1]['sources'].update({'extra': '0'*64}),
                lambda m: m['variants'][0]['sources'].update({check.SHADER: '0'*64}),
                lambda m: m['variants'][0]['inputs'].update({'unpaired': '0'*64}),
                lambda m: m['variants'][0]['images'].clear(),
                lambda m: m['variants'][0]['golden2'].update(status=0),
                lambda m: m['variants'][0]['calibration'].update(status=101),
                lambda m: m['variants'][0]['golden2']['argv'].append('skin_0'),
                lambda m: m['variants'][1]['golden2']['env'].update(RUSTFLAGS='changed'),
                lambda m: m['variants'][0]['build']['env'].update(MDS_RENDER_RECORD='1'),
                lambda m: m['variants'][0]['build'].update(status=1),
                lambda m: m['variants'][0]['build'].update(start_ns=3),
                lambda m: m['variants'][0]['build']['stdout'].update(sha256='0'*64),
                lambda m: m['host']['libraries'].clear(),
            ]
            for mutate in mutations:
                m = copy.deepcopy(manifest)
                mutate(m)
                with self.assertRaises(ValueError):
                    check.verify(m)


if __name__ == '__main__':
    unittest.main()
