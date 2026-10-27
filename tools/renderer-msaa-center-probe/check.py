#!/usr/bin/env python3
"""Bounded same-job GPU experiment. Gate failures are data, malformed evidence is an error."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import time
import zlib

ROOT = Path(__file__).resolve().parents[2]
RELOCATION = None
BASE = '3cf0711d38f94e6be5c5d06129257d1c963f973a'
SHADER = 'rust/crates/mds-render/src/shader.wgsl'
NAMES = ['accessory-0', 'accessory-30', 'background-0', 'groundshadow-0', 'groundshadow-30',
         'perspective-0', 'perspective-30', 'selfshadow-0', 'selfshadow-30', 'skin-0', 'skin-30']
TESTS = {n.replace('-', '_') for n in NAMES} | {'grid_lines', 'selfshadow_0_map_4096', 'shadow_map_display_draws_the_map_in_gray'}
CASES = {'constant_zero', 'constant_positive', 'constant_negative', 'varying_zero',
         'varying_positive', 'varying_negative', 'varying_mixed', 'valid_extrapolation'}
POINTS = {'skin-0': [(334, 229), (332, 232)], 'skin-30': [(361, 149), (342, 187)],
          'selfshadow-30': [(193, 192), (455, 199), (456, 199), (288, 296)]}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_id(path):
    return {'path': str(path), 'sha256': digest(path.read_bytes()), 'size': path.stat().st_size}


def snapshot(root):
    return {str(p.relative_to(root)): digest(p.read_bytes()) for p in sorted(root.rglob('*')) if p.is_file()}


def load_json(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'duplicate JSON key: ' + k)
            result[k] = v
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError('nonfinite JSON: ' + v)))


def read_png(path, dimensions=(640, 360)):
    data = Path(path).read_bytes()
    require(data[:8] == b'\x89PNG\r\n\x1a\n', 'PNG signature')
    pos, chunks, idat, ended = 8, [], bytearray(), False
    while pos < len(data):
        require(pos + 12 <= len(data), 'truncated PNG chunk')
        n, kind = struct.unpack('>I4s', data[pos:pos+8])
        require(n <= len(data) - pos - 12, 'truncated PNG body')
        body = data[pos+8:pos+8+n]
        crc = struct.unpack('>I', data[pos+8+n:pos+12+n])[0]
        require(zlib.crc32(kind + body) == crc, 'PNG CRC')
        require(not ended, 'PNG trailing data')
        if kind == b'IHDR':
            require(not chunks and n == 13, 'PNG IHDR order/length')
            header = struct.unpack('>IIBBBBB', body)
            require(header == (*dimensions, 8, 6, 0, 0, 0), 'PNG format/dimensions')
        elif kind == b'IDAT':
            require(chunks and chunks[0] == b'IHDR', 'PNG IDAT before IHDR')
            require(not idat or chunks[-1] == b'IDAT', 'PNG split IDAT')
            idat.extend(body)
        elif kind == b'IEND':
            require(n == 0 and idat, 'PNG IEND')
            ended = True
        else:
            require(kind[0] & 32, 'unsupported critical PNG chunk')
        chunks.append(kind)
        pos += n + 12
    require(ended, 'missing PNG IEND')
    width, height = dimensions
    stride = width * 4
    decoder = zlib.decompressobj()
    raw = decoder.decompress(idat, height * (stride + 1) + 1)
    require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail, 'PNG zlib stream')
    require(len(raw) == height * (stride + 1), 'PNG decoded length')
    result, previous = bytearray(), bytearray(stride)
    for y in range(height):
        kind = raw[y*(stride+1)]
        require(kind <= 4, 'PNG filter')
        line = bytearray(raw[y*(stride+1)+1:(y+1)*(stride+1)])
        for i in range(stride):
            a = line[i-4] if i >= 4 else 0
            b, c = previous[i], previous[i-4] if i >= 4 else 0
            p = a + b - c
            pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
            prediction = (0, a, b, (a+b)//2, a if pa <= pb and pa <= pc else b if pb <= pc else c)[kind]
            line[i] = (line[i] + prediction) & 255
        result.extend(line)
        previous = line
    return [tuple(result[i:i+4]) for i in range(0, len(result), 4)]


def differences(a, b):
    require(len(a) == len(b) and len(a) > 0, 'pixel count')
    return [max(abs(x[c]-y[c]) for c in range(3)) for x, y in zip(a, b)]


def metrics(ds):
    require(ds, 'empty score')
    close = sum(d <= 4 for d in ds) / len(ds)
    return {'pixels': len(ds), 'over4': sum(d > 4 for d in ds), 'close': close,
            'max': max(ds), 'mean': sum(ds)/len(ds), 'gate': 'PASS' if close >= .9999 and max(ds) <= 48 else 'FAIL'}


def golden_log(raw, code):
    require(not re.search(r'SKIP|Validation Error|validation error|wgpu error', raw, re.I), 'GPU skip/validation error')
    summaries = re.findall(r'test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw)
    require(len(summaries) == 1, 'missing/duplicate test summary')
    status, *counts = summaries[0]
    passed, failed, ignored, measured, filtered = map(int, counts)
    require(passed + failed == 14 and ignored == measured == filtered == 0, 'golden2 must execute 14 tests')
    require((code == 0 and status == 'ok' and failed == 0) or (code == 101 and status == 'FAILED' and failed > 0), 'test status mismatch')
    rows = re.findall(r'^test (\w+) \.\.\. (ok|FAILED)$', raw, re.M)
    require(len(rows) == 14 and {r[0] for r in rows} == TESTS, 'missing/duplicate golden2 test')
    require(sum(r[1] == 'FAILED' for r in rows) == failed, 'test row count mismatch')
    return {'passed': passed, 'failed': failed, 'ignored': ignored, 'filtered': filtered}


def adapters(raw, expected):
    rows = re.findall(r'^CENTER_ADAPTER (.+)$', raw, re.M)
    require(len(rows) == expected and len(set(rows)) == 1, 'adapter missing/duplicate/mismatch')
    require('llvmpipe' in rows[0].lower() and rows[0].endswith('|Vulkan'), 'requires Vulkan llvmpipe')
    return rows[0]


def calibration_models(case):
    w = [1., 1., 1.] if case.startswith('constant') else [1., 2., 4.]
    offset = ((0., 0.) if case.endswith('zero') else (.375, .25) if case.endswith('positive') else
              (-.375, -.25) if case.endswith('negative') else (.375, -.25) if case == 'varying_mixed' else (8., 0.))
    attributes = [(0.2, 0.4, 0.6), (1.8, -0.6, 2.5), (-0.8, 1.5, -1.2)]
    def ref(x, y):
        bary = [1-(x+2)/16-(y+2)/16, (x+2)/16, (y+2)/16]
        denominator = sum(b/q for b, q in zip(bary, w))
        require(denominator > 0 and math.isfinite(denominator), 'calibration denominator')
        return [sum(b*a[c]/q for b, a, q in zip(bary, attributes, w))/denominator for c in range(3)]
    at = ref(3.5, 3.5)
    old = []
    for y in (2.5, 3.5):
        for x in (2.5, 3.5):
            left, right, top, bottom = ref(2.5, y), ref(3.5, y), ref(x, 2.5), ref(x, 3.5)
            old.append([at[c]-(right[c]-left[c])*offset[0]-(bottom[c]-top[c])*offset[1] for c in range(3)])
    return ref(3.5-offset[0], 3.5-offset[1]), old


def calibration(raw, candidate):
    require(not re.search(r'SKIP|Validation Error|validation error|wgpu error', raw, re.I), 'calibration GPU error')
    require(len(re.findall(r'^test result:', raw, re.M)) == 1 and
            re.search(r'test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;', raw), 'calibration not executed exactly once')
    rows = [load_json(s) for s in re.findall(r'^CENTER_CAL (.+)$', raw, re.M)]
    expected = {(h, c) for h in ('center_uv', 'center_world', 'center_value') for c in CASES}
    require(len(rows) == 24 and {(r['helper'], r['case']) for r in rows} == expected, 'calibration coverage/duplicates')
    for r in rows:
        require(r['candidate'] is candidate and r['tolerance'] == .00005, 'calibration variant/tolerance')
        require(all(type(x) in (float, int) and math.isfinite(x) for x in
                    r['actual'] + r['reference'] + [r['new_error'], r['old_error'], r['separation']]), 'nonfinite calibration')
        require(len(r['actual']) == len(r['reference']) == 3, 'calibration vector shape')
        require(min(r['new_error'], r['old_error'], r['separation']) >= 0, 'negative error')
        reference, old = calibration_models(r['case'])
        channels = 2 if r['helper'] == 'center_uv' else 3
        dist = lambda a, b: max(abs(a[c]-b[c]) for c in range(channels))
        require(max(abs(a-b) for a, b in zip(r['reference'], reference)) < 1e-12, 'calibration reference mismatch')
        expected = {'new_error': dist(r['actual'], reference),
                    'old_error': min(dist(r['actual'], p) for p in old),
                    'separation': min(dist(reference, p) for p in old)}
        require(all(abs(r[k]-v) < 1e-12 for k, v in expected.items()), 'calibration reported error mismatch')
        error = r['new_error'] if candidate else r['old_error']
        require(error <= r['tolerance'], 'calibration mathematical model mismatch')
        if r['case'] == 'valid_extrapolation':
            require(r['separation'] > 100 * r['tolerance'], 'calibration discriminator')
    return rows


def command(out, label, argv, cwd, env):
    start = time.time_ns()
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True)
    end = time.time_ns()
    stdout, stderr = out / (label + '.stdout'), out / (label + '.stderr')
    stdout.write_bytes(result.stdout)
    stderr.write_bytes(result.stderr)
    record = {'argv': list(map(str, argv)), 'cwd': str(cwd), 'env': env,
              'start_ns': start, 'end_ns': end, 'status': result.returncode,
              'stdout': file_id(stdout), 'stderr': file_id(stderr)}
    (out / (label + '.json')).write_text(json.dumps(record, indent=2) + '\n')
    return record


def output(record):
    return artifact_path(record['stdout']['path']).read_text() + '\n' + artifact_path(record['stderr']['path']).read_text()


def artifact_path(path):
    path = Path(path)
    if RELOCATION is not None:
        original, current = RELOCATION
        try:
            return current / path.relative_to(original)
        except ValueError:
            pass
    return path


def checked_file(record):
    require(isinstance(record['path'], str) and type(record['size']) is int and record['size'] >= 0 and
            isinstance(record['sha256'], str) and re.fullmatch('[0-9a-f]{64}', record['sha256']), 'file identity shape')
    path = artifact_path(record['path'])
    require(path.is_file() and path.stat().st_size == record['size'] and digest(path.read_bytes()) == record['sha256'], 'file identity mismatch: ' + str(path))
    return path


def validate_command(record):
    require(all(type(record[k]) is int for k in ('status', 'start_ns', 'end_ns')) and
            0 <= record['start_ns'] <= record['end_ns'], 'command status/time')
    require(isinstance(record['argv'], list) and record['argv'] and isinstance(record['env'], dict), 'command shape')
    require(all(isinstance(v, str) for v in record['argv']) and isinstance(record['cwd'], str) and
            all(isinstance(k, str) and isinstance(v, str) for k, v in record['env'].items()), 'command argument/environment types')
    require('MDS_RENDER_RECORD' not in record['env'], 'recording prohibited')
    for key in ('stdout', 'stderr'):
        checked_file(record[key])


def analyze_images(a, b, golden, logs):
    rows = []
    for name in NAMES:
        pa, pb, gold = (read_png(p / (name + '.png')) for p in (a, b, golden))
        da, db = (read_png(p / (name + '-diff.png')) for p in (a, b))
        masks = [[p == (255, 0, 255, 255) for p in d] for d in (da, db)]
        require(masks[0] == masks[1], name + ' mask changed')
        mask = masks[0]
        scores = []
        errors = [differences(p, gold) for p in (pa, pb)]
        for variant, (pixels, diff, ds, raw) in enumerate(zip((pa, pb), (da, db), errors, logs)):
            for i, d in enumerate(ds):
                if not mask[i]:
                    value = 255 - min(255, 4*d)
                    require(diff[i] == (value, value, value, 255), name + ' diff PNG mismatch')
            score = metrics([d for d, m in zip(ds, mask) if not m])
            matches = re.findall(re.escape(name) + r': (\d+) px \((\d+) masked\), within 4 ([0-9.]+), max (\d+), mean ([0-9.]+)', raw)
            require(len(matches) == 1, name + ' missing/duplicate score')
            n, masked, close, maximum, mean = matches[0]
            require((int(n), int(masked), close, int(maximum), mean) ==
                    (score['pixels'], sum(mask), f"{score['close']:.5f}", score['max'], f"{score['mean']:.4f}"), name + ' score mismatch')
            expected_status = 'ok' if score['gate'] == 'PASS' else 'FAILED'
            require(re.search(r'^test ' + re.escape(name.replace('-', '_')) + r' \.\.\. ' + expected_status + r'$', raw, re.M), name + ' gate/test status mismatch')
            scores.append(score)
        change = differences(pa, pb)
        points = []
        for x, y in POINTS.get(name, []):
            i = y*640+x
            points.append({'x': x, 'y': y, 'masked': mask[i], 'A': pa[i], 'B': pb[i], 'golden': gold[i],
                           'error_A': errors[0][i], 'error_B': errors[1][i]})
        rows.append({'name': name, 'A': scores[0], 'B': scores[1], 'whole_frame_A': metrics(errors[0]),
                     'whole_frame_B': metrics(errors[1]), 'changed': sum(d > 0 for d in change),
                     'improved': sum(y < x for x, y in zip(*errors)), 'worsened': sum(y > x for x, y in zip(*errors)),
                     'change_max': max(change), 'change_mean': sum(change)/len(change), 'change_over4': sum(d > 4 for d in change),
                     'mask_sha256': digest(bytes(mask)), 'fixed_points': points})
    return rows

BASE_SHADER_SHA256 = '40e5df9cb46cd896430e0afccc1ec2a911cdfde791b8732f3f6c38e751bf972d'
ALLOWLIST = {SHADER, '.github/workflows/renderer-msaa-center-probe.yml',
             'tools/renderer-msaa-center-probe/check.py', 'tools/renderer-msaa-center-probe/test_check.py',
             'rust/crates/mds-render/tests/common/mod.rs', 'rust/crates/mds-render/tests/center_reconstruction.rs'}


def verify(manifest):
    require(manifest['schema'] == 1 and manifest['base'] == BASE, 'experiment base/schema')
    require(re.fullmatch('[0-9a-f]{40}', manifest['candidate_commit']), 'candidate commit identity')
    checked_file(manifest['candidate_archive'])
    with tarfile.open(artifact_path(manifest['candidate_archive']['path'])) as tar:
        require(tar.pax_headers.get('comment') == manifest['candidate_commit'], 'candidate archive commit identity')
        candidate_map = {m.name: digest(tar.extractfile(m).read()) for m in tar.getmembers() if m.isfile()}
    validate_command(manifest['git_delta'])
    require(manifest['git_delta']['status'] == 0 and manifest['git_delta']['argv'] == ['git', 'diff', '--name-only', BASE, manifest['candidate_commit']], 'git delta identity')
    delta = artifact_path(manifest['git_delta']['stdout']['path']).read_text().splitlines()
    require(set(delta) <= ALLOWLIST and SHADER in delta, 'candidate delta allowlist')
    require(manifest['baseline_description'] == 'candidate sources with exact fixed BASE shader', 'baseline transparency')
    host = manifest['host']
    require(len(host['commands']) >= 2, 'host identity commands missing')
    for cmd in host['commands']:
        validate_command(cmd)
        require(cmd['status'] == 0, 'host identity command failed')
    require('rustc 1.95.0' in output(host['commands'][0]), 'wrong toolchain')
    require('llvmpipe' in output(host['commands'][1]).lower(), 'host Vulkan identity')
    checked_file(host['icd'])
    require(host['libraries'], 'missing Mesa/loader library identity')
    for record in host['libraries']:
        checked_file(record)
    variants = manifest['variants']
    require(len(variants) == 2 and [v['variant'] for v in variants] == ['A', 'B'], 'paired variants required')
    source_maps, logs, adapters_seen, image_dirs, counts = [], [], [], [], []
    for v in variants:
        require(v['build_target'] != '', 'build target identity')
        require(snapshot(artifact_path(v['source_root'])) == v['sources'], 'source closure changed')
        archive = checked_file(v['source_archive'])
        with tarfile.open(archive) as tar:
            archive_map = {m.name: digest(tar.extractfile(m).read()) for m in tar.getmembers() if m.isfile()}
        require(archive_map == v['sources'], 'source archive mismatch')
        require(v['inputs'] == {p: h for p, h in v['sources'].items() if p.startswith('tests/fixtures/')}, 'input identities')
        source_maps.append(v['sources'])
        for key in ('build', 'golden2', 'calibration'):
            validate_command(v[key])
        require(v['build']['status'] == 0, 'build failed')
        expected_build = ['cargo', '+1.95.0', 'test', '-p', 'mds-render', '--test', 'golden2', '--test',
                          'center_reconstruction', '--no-run', '--locked', '--message-format=json', '-vv']
        require(v['build']['argv'] == expected_build and v['build']['cwd'] == str(Path(v['source_root'])/'rust'), 'build command identity')
        require(v['build']['env']['CARGO_TARGET_DIR'] == v['build_target'], 'build directory identity')
        cargo = [load_json(line) for line in artifact_path(v['build']['stdout']['path']).read_text().splitlines()]
        for target, key in [('golden2', 'golden2'), ('center_reconstruction', 'calibration')]:
            matches = [r['executable'] for r in cargo if r.get('reason') == 'compiler-artifact' and r['target']['name'] == target and r.get('executable')]
            require(len(matches) == 1 and matches[0] == v['executables'][key]['cargo_path'], 'Cargo executable identity')
            checked_file(v['executables'][key]['retained'])
            argv = [v['executables'][key]['retained']['path'], '--include-ignored', '--nocapture', '--test-threads=1']
            require(v[key]['argv'] == argv and v[key]['cwd'] == v['build']['cwd'], 'execution command identity')
            require(v[key]['env']['VK_ICD_FILENAMES'] == host.get('icd_original_path', host['icd']['path']), 'execution ICD identity')
            require(v[key]['env']['WGPU_BACKEND'] == 'vulkan', 'execution backend identity')
        raw, cal = output(v['golden2']), output(v['calibration'])
        counts.append(golden_log(raw, v['golden2']['status']))
        require(v['calibration']['status'] == 0, 'calibration failed')
        calibration(cal, v['variant'] == 'B')
        adapter = adapters(raw, 14)
        require(adapters(cal, 1) == adapter, 'calibration adapter mismatch')
        require(v['adapter'] == adapter, 'manifest adapter mismatch')
        adapters_seen.append(adapter)
        logs.append(raw)
        images = artifact_path(v['image_dir'])
        require(v['golden2']['env']['MDS_RENDER_PNG_DIR'] == v['image_dir'], 'image directory identity')
        expected = {n + suffix for n in NAMES for suffix in ('.png', '-diff.png')}
        require({p.name for p in images.iterdir()} == expected, '11 render and 11 diff PNGs required')
        require(snapshot(images) == v['images'], 'image identities')
        image_dirs.append(images)
    require(adapters_seen[0] == adapters_seen[1], 'A/B adapter identity mismatch')
    require(variants[0]['build_target'] != variants[1]['build_target'], 'A/B shared build directory')
    for key in ('golden2', 'calibration'):
        require(variants[0]['executables'][key]['cargo_path'] != variants[1]['executables'][key]['cargo_path'], 'A/B shared executable')
    a, b = source_maps
    require(a.keys() == b.keys() and [p for p in a if a[p] != b[p]] == [SHADER], 'source delta must be exactly shader')
    require(a[SHADER] == BASE_SHADER_SHA256 and b[SHADER] == manifest['candidate_shader_sha256'], 'shader identity')
    require(variants[0]['inputs'] == variants[1]['inputs'], 'A/B input identity mismatch')
    require(candidate_map == b, 'candidate archive/source mismatch')
    common_env = {k: v for k, v in variants[0]['build']['env'].items() if k != 'CARGO_TARGET_DIR'}
    for v in variants:
        expected_env = common_env | {'CARGO_TARGET_DIR': v['build_target']}
        require(v['build']['env'] == expected_env and v['calibration']['env'] == expected_env, 'paired build/calibration environment mismatch')
        require(v['golden2']['env'] == expected_env | {'MDS_RENDER_PNG_DIR': v['image_dir']}, 'paired golden2 environment mismatch')
    golden = artifact_path(variants[1]['source_root']) / 'tests/fixtures/rust/golden2'
    rows = analyze_images(*image_dirs, golden, logs)
    return {'status': 'VALID_EXPERIMENT', 'renderer_fix_adopted': False, 'adapter': adapters_seen[0],
            'test_counts': dict(zip(('A', 'B'), counts)), 'rows': rows,
            'interpretation': 'Gate failures remain separate from experiment validity. No improvement threshold or adoption decision is applied.'}


def run(out, build_root):
    require(sys.platform == 'linux', 'GPU experiment runs only on CI Linux')
    require(not out.exists() and not build_root.exists(), 'experiment requires fresh output and build directories')
    out.mkdir(parents=True)
    build_root.mkdir(parents=True)
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'CARGO_HOME', 'RUSTUP_HOME', 'TMPDIR', 'LD_LIBRARY_PATH') if k in os.environ}
    icds = list(Path('/usr/share/vulkan/icd.d').glob('lvp_icd*.json'))
    require(len(icds) == 1, 'one llvmpipe ICD required')
    runtime = out / '.xdg-runtime'
    runtime.mkdir(mode=0o700)
    env.update({'WGPU_BACKEND': 'vulkan', 'VK_ICD_FILENAMES': str(icds[0]), 'XDG_RUNTIME_DIR': str(runtime),
                'CARGO_TERM_COLOR': 'never', 'CARGO_INCREMENTAL': '0', 'CXX': 'clang++'})
    host_commands = [command(out, label, argv, ROOT/'rust', env) for label, argv in (
        ('rust-version', ['rustc', '+1.95.0', '-vV']), ('vulkan-summary', ['vulkaninfo', '--summary']),
        ('mesa-packages', ['dpkg-query', '-W', 'mesa-vulkan-drivers', 'libvulkan1']),
        ('loader-libraries', ['ldconfig', '-p']))]
    require(all(c['status'] == 0 for c in host_commands), 'host identity command failed')
    icd_data = load_json(icds[0].read_text())
    icd_library = Path(icd_data['ICD']['library_path'])
    if not icd_library.is_absolute():
        matches = list(Path('/usr/lib/x86_64-linux-gnu').glob(icd_library.name))
        require(len(matches) == 1, 'ICD library resolution')
        icd_library = matches[0]
    libraries = sorted({icd_library} | {Path(p) for p in re.findall(r'=> (/\S+)', output(host_commands[-1])) if 'libvulkan' in p})
    require(any('lvp' in str(p) for p in libraries), 'llvmpipe shared library missing')
    for index, library in enumerate(libraries.copy()):
        deps = command(out, 'library-deps-' + str(index), ['ldd', str(library)], ROOT/'rust', env)
        host_commands.append(deps)
        libraries.extend(Path(p) for p in re.findall(r'=> (/\S+)', output(deps)))
    libraries = sorted(set(libraries))
    host_files = out/'host-files'
    host_files.mkdir()
    retained_libraries = []
    for i, library in enumerate(libraries):
        retained = host_files/(str(i)+'-'+library.name)
        shutil.copy2(library, retained)
        retained_libraries.append(file_id(retained) | {'original_path': str(library)})
    retained_icd = host_files/icds[0].name
    shutil.copy2(icds[0], retained_icd)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    git_delta = command(out, 'git-delta', ['git', 'diff', '--name-only', BASE, revision], ROOT, env)
    require(git_delta['status'] == 0, 'git delta command failed')
    changed = Path(git_delta['stdout']['path']).read_text().splitlines()
    require(set(changed) <= ALLOWLIST and SHADER in changed, 'candidate source changes outside experiment')
    clean = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT)
    require(not clean, 'CI checkout must be clean')
    archive = out / 'candidate-source.tar'
    with archive.open('wb') as stream:
        subprocess.run(['git', 'archive', revision], cwd=ROOT, stdout=stream, check=True)
    sources = out / 'sources'
    sources.mkdir()
    candidate = sources / 'B'
    candidate.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(candidate, filter='data')
    control = sources / 'A'
    shutil.copytree(candidate, control)
    base_shader = subprocess.check_output(['git', 'show', BASE + ':' + SHADER], cwd=ROOT)
    require(digest(base_shader) == BASE_SHADER_SHA256, 'fixed base shader mismatch')
    (control / SHADER).write_bytes(base_shader)
    (out/'base-shader.wgsl').write_bytes(base_shader)
    manifest = {'schema': 1, 'base': BASE, 'candidate_commit': revision, 'candidate_archive': file_id(archive), 'git_delta': git_delta,
                'candidate_shader_sha256': digest((candidate/SHADER).read_bytes()),
                'baseline_description': 'candidate sources with exact fixed BASE shader',
                'artifact_root': str(out),
                'host': {'commands': host_commands, 'icd': file_id(retained_icd), 'icd_original_path': str(icds[0]), 'libraries': retained_libraries},
                'variants': []}
    for variant, source in [('A', control), ('B', candidate)]:
        directory = out / variant
        directory.mkdir()
        source_map = snapshot(source)
        source_archive = directory/'source.tar'
        with tarfile.open(source_archive, 'w') as tar:
            for p in source_map:
                tar.add(source/p, arcname=p, recursive=False)
        images = directory/'images'
        images.mkdir()
        variant_env = env | {'CARGO_TARGET_DIR': str(build_root/variant)}
        build = command(directory, 'build', ['cargo', '+1.95.0', 'test', '-p', 'mds-render', '--test', 'golden2',
                        '--test', 'center_reconstruction', '--no-run', '--locked', '--message-format=json', '-vv'], source/'rust', variant_env)
        v = {'variant': variant, 'source_root': str(source), 'sources': source_map, 'source_archive': file_id(source_archive),
             'inputs': {p: h for p, h in source_map.items() if p.startswith('tests/fixtures/')},
             'build_target': str(build_root/variant), 'build': build, 'executables': {}, 'image_dir': str(images)}
        manifest['variants'].append(v)
        if build['status'] != 0:
            continue
        cargo = [load_json(line) for line in Path(build['stdout']['path']).read_text().splitlines()]
        for target, key in [('golden2', 'golden2'), ('center_reconstruction', 'calibration')]:
            executables = [r['executable'] for r in cargo if r.get('reason') == 'compiler-artifact' and r['target']['name'] == target and r.get('executable')]
            require(len(executables) == 1, 'one executable required: ' + target)
            binary = directory/target
            shutil.copy2(executables[0], binary)
            v['executables'][key] = {'cargo_path': executables[0], 'retained': file_id(binary)}
            test_env = variant_env | ({'MDS_RENDER_PNG_DIR': str(images)} if key == 'golden2' else {})
            v[key] = command(directory, key, [str(binary), '--include-ignored', '--nocapture', '--test-threads=1'], source/'rust', test_env)
        raw = output(v['golden2'])
        found = re.findall(r'^CENTER_ADAPTER (.+)$', raw, re.M)
        v['adapter'] = found[0] if found else None
        v['images'] = snapshot(images)
        require(snapshot(source) == source_map, 'source/input changed during build or run')
    path = out/'experiment.json'
    with path.open('x') as stream:
        json.dump(manifest, stream, indent=2)
        stream.write('\n')
    (out/'experiment.sha256').write_text(digest(path.read_bytes()) + '\n')
    return manifest


def main():
    global RELOCATION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--build-root', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    try:
        if args.run:
            require(args.build_root is not None, '--build-root required')
            manifest = run(out, args.build_root.resolve())
        else:
            path = out/'experiment.json'
            require((out/'experiment.sha256').read_text().strip() == digest(path.read_bytes()), 'manifest seal mismatch')
            manifest = load_json(path.read_text())
            RELOCATION = (Path(manifest['artifact_root']), out)
        result = verify(manifest)
        (out/'analysis.json').write_text(json.dumps(result, indent=2) + '\n')
        print('VALID_EXPERIMENT. Actual golden2 gates are recorded separately in analysis.json.')
        return 0
    except (ValueError, KeyError, IndexError, TypeError, OSError, subprocess.SubprocessError, tarfile.TarError, zlib.error, struct.error) as error:
        out.mkdir(parents=True, exist_ok=True)
        (out/'analysis.json').write_text(json.dumps({'status': 'MALFORMED_OR_INCOMPLETE_EXPERIMENT', 'error': str(error)}, indent=2) + '\n')
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
