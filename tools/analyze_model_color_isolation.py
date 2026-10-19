"""Audit draw-42 reduction and sampling controls; never relax the image gate."""
import argparse
import csv
import hashlib
import json
import math
import re
import struct
from pathlib import Path
from analyze_accessory_isolation import fnv, tags
from analyze_scene_prefix import difference


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--compare', type=Path, help='Another architecture using identical inputs')
    args = parser.parse_args()
    source, root = args.archive, args.evidence
    stem = source / 'history_replay.scene_prefix.draw42'
    state = Path(str(stem) + '.state').read_text().splitlines()
    desc = tags(state[0])
    region = tags(next(s for s in state if s.startswith('VIEWPORT ')))
    x, y, w, h = [int(region[k]) for k in ('x', 'y', 'width', 'height')]
    require(desc['sequence'] == '42' and desc['type'] == '4' and desc['indexed'] == '1' and desc['stride'] == '32', 'unexpected material input')
    count = int(desc['count'])
    with (root / 'controls.csv').open(newline='') as file:
        rows = list(csv.DictReader(file))
    data = {row['mode']: row for row in rows}
    require(len(data) == len(rows), 'duplicate controls')
    complete = tags((root / 'summary.txt').read_text())
    for key, value in {'complete': '1', 'draw': '42', 'repeats': '3', 'sphereSoRepeats': '3', 'frozenMipsExact': '1',
                       'sourceReferenceExact': '1', 'productionActivation': '0', 'imageAcceptance': '0'}.items():
        require(complete.get(key) == value, 'invalid completion: ' + key)
    require(int(complete['comparisons']) == len(rows), 'comparison count mismatch')
    mode = tags((root / 'mode.txt').read_text())
    require(all(mode.get(k) == v for k, v in {'center': 'viewport', 'shaderShift': '0', 'viewportShiftX': '0.5',
            'viewportShiftY': '0.5', 'samples': '1', 'productionActivation': '0'}.items()), 'wrong diagnostic stage')
    suffixes = ('.native.bgra', '.candidate.bgra')
    baseline = tuple((root / ('original' + s)).read_bytes() for s in suffixes)
    require(all(len(b) == w*h*4 for b in baseline), 'wrong original image size')
    require(baseline == tuple((args.reference / ('isolated42' + s)).read_bytes() for s in suffixes), 'original reference drift')
    focus = [p for p, (a, b) in enumerate(zip(memoryview(baseline[0]).cast('I'), memoryview(baseline[1]).cast('I'))) if a != b]
    require(0 < len(focus) <= 31, 'invalid focus pixels')
    with (root / 'pixels.csv').open(newline='') as file:
        pixel_rows = list(csv.DictReader(file))
    require(len(pixel_rows) == len(rows)*len(focus), 'missing focus observations')
    metrics, image_hashes, expected_pixels, hash_cache = {}, {}, [], {}
    for row in rows:
        name = row['mode']
        images = tuple((root / (name + s)).read_bytes() for s in suffixes)
        require(all(len(b) == w*h*4 for b in images), 'image extent: ' + name)
        hashes = tuple(sha(b) for b in images)
        for k, b in enumerate(images):
            if hashes[k] not in hash_cache:
                hash_cache[hashes[k]] = fnv(b)
            require(hash_cache[hashes[k]] == int(row['candidateHash' if k else 'nativeHash']), 'image hash: ' + name)
        changed, maximum, first = difference(*images)
        mask = sum((images[0][p*4:p*4+4] != images[1][p*4:p*4+4]) << n for n, p in enumerate(focus))
        require((changed, maximum, mask) == tuple(int(row[k]) for k in ('differentPixels', 'maxDelta', 'focusMask')), 'image metrics: ' + name)
        metrics[name] = {'differentPixels': changed, 'maxDelta': maximum, 'focusMask': mask,
                         'first': None if first is None else [x+first%w, y+first//w]}
        if re.fullmatch(r'compact_\d+_pure_constant_uv\d+', name):
            drawn = sum(v != 0xffffffff for v in memoryview(images[0]).cast('I'))
            require(drawn > 0, 'constant UV control drew no visible triangle')
            metrics[name]['nonWhitePixels'] = drawn
        image_hashes[name] = hashes
        for p in focus:
            expected_pixels.append((name, x+p%w, y+p//w, tuple(images[0][p*4:p*4+4]), tuple(images[1][p*4:p*4+4])))
        if len(metrics) % 20 == 0:
            print(f'audited {len(metrics)}/{len(rows)} controls', flush=True)
    actual_pixels = [(r['mode'], int(r['x']), int(r['y']), tuple(int(r['n'+k]) for k in 'BGRA'),
                      tuple(int(r['c'+k]) for k in 'BGRA')) for r in pixel_rows]
    require(actual_pixels == expected_pixels, 'focus observations contradict images')
    for name in ('repeat1', 'repeat2', 'repeat3', 'frozen_sphere_mips'):
        require(image_hashes[name] == image_hashes['original'], 'baseline/mip stability: ' + name)
    names = ['no_blend', 'no_alpha_test', 'no_depth_stencil', 'no_specular', 'no_lighting', 'no_normalize',
             'toon_only', 'sphere_only', 'no_textures', 'white_toon', 'white_sphere', 'white_both', 'point',
             'linear_mip_point', 'linear_mip_linear']
    expected = {'original', 'repeat1', 'repeat2', 'repeat3', 'frozen_sphere_mips', *names}
    pending, leaves = [(0, count)], []
    for first, size in pending:
        name = f'range_{first}_{size}'
        expected.add(name)
        require(name in data and int(data[name]['firstTriangle']) == first and int(data[name]['triangles']) == size, 'incomplete range tree')
        if not metrics[name]['focusMask']:
            continue
        if size == 1:
            leaves.append(first)
        else:
            half = size//2
            pending.extend(((first, half), (first+half, size-half)))
    require(int(complete['leaves']) == len(leaves), 'leaf count mismatch')
    with (root / 'triangles.csv').open(newline='') as file:
        triangles = list(csv.DictReader(file))
    require([int(r['triangle']) for r in triangles] == leaves, 'leaf selection mismatch')
    vertices = Path(str(stem) + '.vertices').read_bytes()
    indices = Path(str(stem) + '.indices').read_bytes()
    native_log = (source / 'history_replay.dx9').read_text().splitlines()
    ib = tags(next(s for s in native_log if s.startswith('BUFFER sequence=42 kind=index ')))
    step = 2 if int(ib['format']) == 101 else 4
    geometry, covered = [], 0
    for row in triangles:
        triangle = int(row['triangle'])
        start = int(desc['start'])+triangle*3
        original_indices = [int.from_bytes(indices[(start+n)*step:(start+n+1)*step], 'little') for n in range(3)]
        require(original_indices == [int(row[k]) for k in ('index0', 'index1', 'index2')], 'source index mismatch')
        compact = b''.join(vertices[i*32:(i+1)*32] for i in original_indices)
        label = f'compact_{triangle}'
        require(len(compact) == 96 and (root / (label + '.vertices')).read_bytes() == compact, 'source vertex mismatch')
        expected.update((f'leaf_{triangle}', label))
        expected.update(label+'_'+n for n in names)
        require(image_hashes[f'leaf_{triangle}'] == image_hashes[label], 'compaction changed image')
        covered |= metrics[label]['focusMask']
        so = (root / (label + '.sphere.so')).read_bytes()
        require(len(so) == 120, 'SO layout mismatch')
        for n in range(1, 4):
            require((root / (label + f'.sphere.repeat{n}.so')).read_bytes() == so, 'unstable SO observation')
        observed = [struct.unpack_from('<10f', so, n*40) for n in range(3)]
        require(all(all(math.isfinite(v) for v in vertex) and vertex[3] > 0 for vertex in observed), 'nonfinite SO data')
        baked = bytearray(compact)
        for n in range(3):
            baked[n*32+24:n*32+32] = so[n*40+16:n*40+24]
        require((root / (label + '.baked.vertices')).read_bytes() == baked, 'shared UV not identical to observation')
        for variant in ('shared_uv', 'pure_shared_uv'):
            expected.update(label+'_'+variant+s for s in ('', '_frozen', '_point', '_linear_mip_point', '_linear_mip_linear'))
            require(image_hashes[label+'_'+variant] == image_hashes[label+'_'+variant+'_frozen'], 'explicit mips changed image')
        expected.update(label+f'_pure_constant_uv{n}' for n in range(7))
        # This is a measured result, not a required assumption for future inputs.
        geometry.append({'triangleZeroBased': triangle, 'sourceIndices': original_indices,
                         'compactSha256': sha(compact), 'sphereUV': [list(v[4:6]) for v in observed],
                         'sharedUvImagesExactToOriginal': image_hashes[label] == image_hashes[label+'_shared_uv']})
    require(covered == (1 << len(focus))-1, 'reduced geometry failed to account for every focus pixel')
    require(set(data) == expected, 'missing/unexpected controls: '+str(set(data)^expected))
    artifacts = {p.name: sha(p.read_bytes()) for p in sorted(root.iterdir()) if p.is_file() and p.suffix not in ('.json',)}
    if args.compare:
        other = {p.name: sha(p.read_bytes()) for p in sorted(args.compare.iterdir()) if p.is_file() and p.suffix not in ('.json',)}
        require(artifacts == other, 'architecture evidence differs for identical inputs')
    result = {'draw': 42, 'controls': len(rows), 'region': [x, y, w, h], 'baseline': metrics['original'],
              'focusPixels': expected_pixels[:len(focus)], 'geometry': geometry, 'controlMetrics': metrics,
              'ownedSourceProof': {p.name: sha(p.read_bytes()) for p in sorted(source.glob(stem.name+'.*')) if not p.name.endswith('.bgra')},
              'artifacts': artifacts, 'crossArchitectureExact': bool(args.compare),
              'productionActivation': False, 'imageAcceptance': False}
    (root / 'analysis.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('controlMetrics', 'artifacts', 'ownedSourceProof')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
