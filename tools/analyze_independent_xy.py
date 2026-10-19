"""Audit generated XY qualification; exact evidence is scoped to measured inputs."""
import argparse
import csv
import hashlib
import json
import math
import struct
from pathlib import Path
from analyze_accessory_isolation import tags
from analyze_model_sampling import require
from analyze_model_transform import f32, dot, multiply, pack

RULES = ('sequential', 'double', 'paired', 'fused')
CHANNELS = ('sample', 'uv', 'gradients', 'rgba8')
SHARED = {f'matrix_{m}_dot_{d}' for m in RULES for d in RULES}
GPU = {p+s for p in ('gpu_baseline', 'gpu_fused_xy') for s in ('', '_repeat1', '_repeat2', '_repeat3')}


def affine(a, t=(0, 0, 0)):
    m = [0.]*16
    m[15] = 1.
    for r in range(3):
        for c in range(3):
            m[r*4+c] = f32(a[r*3+c])
    m[12:15] = map(f32, t)
    return m


def perspective(x, y, near, far, ox=0., oy=0.):
    x, y, near, far, ox, oy = map(f32, (x, y, near, far, ox, oy))
    m = [0.]*16
    m[0], m[5], m[8], m[9], m[11] = x, y, ox, oy, 1.
    m[10] = f32(far/f32(far-near))
    m[14] = f32(-near*m[10])
    return m


def inputs():
    identity = affine((1, 0, 0, 0, 1, 0, 0, 0, 1))
    dyadic = affine((2, .25, 0, 0, 1.5, .125, .5, 0, 1), (.125, -.25, .5))
    dense = affine((1.13, .19, -.37, -.13, 1.17, .23, .41, -.29, 1.31), (-.17, .43, .11))
    view = affine((.8, .13, -.6, -.17, .93, .11, .6, -.23, .8), (.31, -.19, .37))
    rotate = affine((.8, 0, -.6, 0, 1, 0, .6, 0, .8), (-.23, .17, .41))
    cycle = affine((0, 1, 0, 0, 0, 1, 1, 0, 0), (.23, -.11, .17))
    large = affine((1.13, .19, -.37, -.13, 1.17, .23, .41, -.29, 1.31), (4096.13, -8192.27, 2048.19))
    near_unit = affine((.99999994039535522, .000013, 0, -.000017, 1, 0, 0, .000023, .99999988079071045), (-.11, .37, .29))
    p = perspective(1.173, 1.619, .173, 19.37)
    offset = perspective(1.371, 1.913, .219, 31.13, .071, -.13)
    ortho = identity[:]
    for k, value in {0: .73, 5: 1.13, 10: .17, 12: .11, 13: -.19, 14: .23}.items():
        ortho[k] = f32(value)
    return [('identity', identity, identity, identity), ('dyadic_affine', dyadic, cycle, identity),
            ('dense_orthographic', dense, view, ortho), ('rotated_perspective', rotate, view, p),
            ('permuted_perspective', dense, cycle, p), ('dense_perspective', dyadic, view, p),
            ('large_cancellation', large, identity, p), ('near_unit_view', dense, near_unit, p),
            ('off_axis_perspective', dense, view, offset), ('view_only_perspective', identity, view, offset),
            ('narrow_perspective', view, dense, perspective(2.731, 3.917, .073, 53.19, .113, .071)),
            ('dense_both_orthographic', view, dense, ortho)]


def inverse(m):
    a = [m[r*4:r*4+4]+[float(r == c) for c in range(4)] for r in range(4)]
    for c in range(4):
        pivot = max(range(c, 4), key=lambda r: abs(a[r][c]))
        require(a[pivot][c] != 0, 'singular construction matrix')
        a[c], a[pivot] = a[pivot], a[c]
        divisor = a[c][c]
        a[c] = [v/divisor for v in a[c]]
        for r in range(4):
            if r != c:
                factor = a[r][c]
                a[r] = [v-factor*u for v, u in zip(a[r], a[c])]
    return [f32(v) for row in a for v in row[4:]]


def vertices(world, view, projection, geometry):
    ndc = (((-.731, -.617), (-.413, .713), (.791, -.337)),
           ((-.813, -.139), (.793, .017), (.717, .151)),
           ((-.173, .817), (.617, -.713), (-.717, -.317)))
    depths = ((2.313, 4.719, 3.137), (5.173, 2.719, 6.131), (3.731, 6.317, 2.113))
    uv = ((.173, .297), (1.113, -.231), (-.407, 1.371))
    inv = inverse(multiply(world, view, 'double'))
    out = []
    for n in range(3):
        persp = projection[11] != 0
        depth = f32(depths[geometry][n]) if persp else (.5 if projection[10] == 1 else 2.)
        w = depth if persp else 1.
        camera = [(f32(ndc[geometry][n][0])*w-depth*projection[8]-projection[12])/projection[0],
                  (f32(ndc[geometry][n][1])*w-depth*projection[9]-projection[13])/projection[5], depth, 1.]
        out.append([f32(sum(camera[k]*inv[k*4+c] for k in range(4))) for c in range(3)]+[0., 0., 1.]+list(map(f32, uv[n])))
    return out


def pixel_metrics(a, b, byte_image=False):
    require(len(a) == len(b), 'different image sizes')
    if a == b:
        return 0, 0.
    step = 4 if byte_image else 16
    count = sum(a[i:i+step] != b[i:i+step] for i in range(0, len(a), step))
    if byte_image:
        # Match the transport's separate float32 byte-to-unit conversions.
        maximum = max(abs(f32(x/255)-f32(y/255)) for x, y in zip(a, b))
    else:
        av = struct.unpack(f'<{len(a)//4}f', a)
        bv = struct.unpack(f'<{len(b)//4}f', b)
        require(all(math.isfinite(x) for x in (*av, *bv)), 'nonfinite image')
        maximum = max(abs(x-y) for x, y in zip(av, bv))
    return count, maximum


def rows(path):
    with path.open(newline='') as file:
        return list(csv.DictReader(file))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    root = args.evidence
    summary = tags((root/'summary.txt').read_text())
    expected = {'complete': '1', 'transforms': '12', 'holdoutTransforms': '6', 'geometries': '3', 'cases': '36',
                'observations': '2592', 'samples': '1', 'nativeRepeats': '3', 'gpuRepeats': '3',
                'productionActivation': '0', 'nativeVertexCapture': '0'}
    require(all(summary.get(k) == v for k, v in expected.items()), 'invalid completion summary')
    meta = tags((root/'metadata.txt').read_text())
    require(all(meta.get(k) == v for k, v in {'width': '80', 'height': '72', 'viewport': '5,7,64,56',
                'center': 'viewport', 'mipLevels': '1', 'filter': 'linear'}.items()), 'wrong raster controls')
    case_rows, table, material_rows = rows(root/'cases.csv'), rows(root/'observations.csv'), rows(root/'materials.csv')
    require(len(case_rows) == 36 and len(table) == 2592 and len(material_rows) == 72, 'missing observations')
    indexed = {(int(r['case']), r['mode'], r['channel']): r for r in table}
    expected_keys = {(i, mode, c) for i in range(36) for mode in SHARED|GPU for c in (CHANNELS if mode in GPU else ('uv', 'gradients'))}
    expected_keys |= {(i, 'precombined_'+r, c) for i in range(36) for r in RULES for c in ('uv', 'gradients')}
    require(len(indexed) == len(table) and set(indexed) == expected_keys, 'missing/duplicate branches')
    material_index = {(int(r['case']), r['mode']): int(r['differentPixels']) for r in material_rows}
    require(set(material_index) == {(i, m) for i in range(36) for m in ('baseline', 'fused_xy')}, 'invalid full-material branches')
    artifacts = {}

    def raw(name, size):
        data = (root/name).read_bytes()
        require(len(data) == size, 'wrong extent: '+name)
        artifacts[name] = hashlib.sha256(data).hexdigest()
        return data

    texture = bytes(v for y in range(32) for x in range(32) for v in ((17*x+29*y+13)%239, (31*x+7*y+47)%241, (11*x+23*y+71)%251, 255))
    require(raw('texture.rgba', 4096) == texture, 'generated texture changed')
    results, shared_failures, qualified, material_qualified = [], 0, 0, 0
    for i, case in enumerate(case_rows):
        name, world, view, projection = inputs()[i//3]
        require(int(case['case']) == i and int(case['transform']) == i//3 and int(case['geometry']) == i%3
                and case['name'] == name and int(case['holdout']) == (i//3 >= 6), 'case construction changed')
        label = f'case{i}'
        matrices = world+view+projection
        require(raw(label+'.matrices', 192) == struct.pack('<48f', *matrices), 'independent matrix generation differs')
        model = vertices(world, view, projection, i%3)
        require(raw(label+'.vertices', 96) == b''.join(struct.pack('<8f', *v) for v in model), 'independent geometry generation differs')
        reference = {}
        for c in CHANNELS:
            extension, size = ('.rgba', 80*72*4) if c == 'rgba8' else ('.float', 80*72*16)
            reference[c] = raw(label+'_native_'+c+extension, size)
            if c != 'rgba8':
                pixels = list(struct.iter_unpack('<4f', reference[c]))
                require(all(math.isfinite(v) for p in pixels for v in p), 'nonfinite native image')
            for n in range(1, 4):
                require(raw(f'{label}_native_repeat{n}_{c}{extension}', size) == reference[c], 'native observation repeat changed')
        coverage = sum(p[2] == 0 for p in struct.iter_unpack('<4f', reference['uv']))
        require(coverage == int(case['coverage']) and coverage > 8, 'empty or changed coverage')
        combined, values, precombined_metrics = {}, {}, {}
        for m in RULES:
            combined[m] = multiply(multiply(world, view, m), projection, m)
            require(raw(label+'.combined_'+m, 64) == struct.pack('<16f', *combined[m]), 'combined matrix arithmetic differs')
            for d in RULES:
                mode = f'matrix_{m}_dot_{d}'
                values[mode] = [[dot(v[:3]+[1.], combined[m][c::4], d) for c in range(4)]+v[6:8] for v in model]
                require(raw(label+'_'+mode+'.input', 72) == pack(values[mode]), 'clip-coordinate arithmetic differs: '+mode)
            for c in ('uv', 'gradients'):
                data = raw(f'{label}_precombined_{m}_{c}.float', 80*72*16)
                row = indexed[i, 'precombined_'+m, c]
                different = pixel_metrics(data, reference[c])[0]
                precombined_metrics.setdefault(m, {})[c] = different
                require(int(row['nativeDifferent']) == different
                        and row['candidateDifferent'] == row['betweenApis'] == '-1', 'precombined observation metric differs')
        for mode in GPU:
            data = raw(label+'_'+mode+'.input', 72)
            base = mode.split('_repeat')[0]
            if '_repeat' in mode:
                require(data == raw(label+'_'+base+'.input', 72), 'GPU SO repeat differs')
            parsed = list(struct.iter_unpack('<6f', data))
            for n, v in enumerate(parsed):
                wanted = values['matrix_sequential_dot_fused'][n]
                require(v[4:] == tuple(model[n][6:8]) and v[2:4] == tuple(wanted[2:4]), 'GPU W/Z or source UV changed')
            if base == 'gpu_fused_xy':
                require(data == pack(values['matrix_sequential_dot_fused']), 'GPU SO does not match independent fused arithmetic')
            values[mode] = parsed
        mode_metrics = {}
        for mode in SHARED|GPU:
            mode_metrics[mode] = {}
            for c in (CHANNELS if mode in GPU else ('uv', 'gradients')):
                byte_image = c == 'rgba8'
                size = 80*72*(4 if byte_image else 16)
                extension = '.rgba' if byte_image else '.float'
                a = raw(f'{label}_{mode}_{c}.dx9'+extension, size)
                b = raw(f'{label}_{mode}_{c}.dx11'+extension, size)
                native_diff, _ = pixel_metrics(a, reference[c], byte_image)
                candidate_diff, maximum = pixel_metrics(b, reference[c], byte_image)
                between, _ = pixel_metrics(a, b, byte_image)
                row = indexed[i, mode, c]
                require((native_diff, candidate_diff, between) == tuple(int(row[k]) for k in ('nativeDifferent', 'candidateDifferent', 'betweenApis')),
                        'saved image does not support table metrics')
                require(maximum == float(row['maxAbsDelta']), f'wrong maximum delta: {i} {mode} {c}')
                shared_failures += between != 0
                if '_repeat' in mode:
                    base = mode.split('_repeat')[0]
                    for api, data in (('dx9', a), ('dx11', b)):
                        require(data == raw(f'{label}_{base}_{c}.{api}'+extension, size), 'shared raster repeat changed')
                mode_metrics[mode][c] = candidate_diff
        is_qualified = all(v == 0 for v in mode_metrics['gpu_fused_xy'].values())
        qualified += is_qualified
        fixed = raw(label+'_material.native.rgba', 80*72*4)
        material_metrics = {}
        for mode in ('baseline', 'fused_xy'):
            image = raw(f'{label}_material.{mode}.rgba', 80*72*4)
            count, maximum = pixel_metrics(fixed, image, True)
            require(count == material_index[i, mode], 'full material metric differs')
            material_metrics[mode] = {'differentPixels': count, 'maxByteDelta': round(maximum*255)}
            for repeat in range(1, 4):
                require(raw(f'{label}_material.{mode}.repeat{repeat}.rgba', 80*72*4) == image, 'full material repeat differs')
        material_qualified += material_metrics['fused_xy']['differentPixels'] == 0
        exact_hypotheses = [m for m in sorted(SHARED) if all(v == 0 for v in mode_metrics[m].values())]
        coefficient_distinction = len({struct.pack('<16f', *m) for m in combined.values()}) > 1
        dot_distinction = len({pack(v) for m, v in values.items() if m.startswith('matrix_')}) > 1
        results.append({'case': i, 'name': name, 'holdout': i//3 >= 6, 'geometry': i%3, 'coverage': coverage,
                        'qualified': is_qualified, 'gpuBaseline': mode_metrics['gpu_baseline'],
                        'gpuFusedXY': mode_metrics['gpu_fused_xy'], 'material': material_metrics,
                        'exactUVGradientHypotheses': exact_hypotheses,
                        'nativePrecombined': precombined_metrics,
                        'distinctCombinedCoefficients': coefficient_distinction, 'distinctClipHypotheses': dot_distinction})
    require(qualified == int(summary['qualifiedCases']) and shared_failures == int(summary['sharedFailures'])
            and material_qualified == int(summary['materialQualified']), 'qualification summary differs from evidence')
    for name in ('cases.csv', 'observations.csv', 'materials.csv', 'summary.txt', 'metadata.txt'):
        raw(name, (root/name).stat().st_size)
    require(set(artifacts) == {p.name for p in root.iterdir() if p.is_file() and p.name != 'analysis.json'}, 'unreviewed/missing artifact')
    result = {'cases': 36, 'holdoutCases': 18, 'qualifiedCases': qualified, 'materialQualifiedCases': material_qualified,
              'sharedClipFailures': shared_failures,
              'baselineUVGradientFailures': sum(any(r['gpuBaseline'][c] for c in ('uv', 'gradients')) for r in results),
              'baselineMaterialFailures': sum(r['material']['baseline']['differentPixels'] != 0 for r in results),
              'distinctCoefficientCases': sum(r['distinctCombinedCoefficients'] for r in results),
              'distinctClipCases': sum(r['distinctClipHypotheses'] for r in results),
              'exactHypothesisCases': {m: sum(m in r['exactUVGradientHypotheses'] for r in results) for m in sorted(SHARED)},
              'exactNativePrecombinedCases': {m: sum(all(v == 0 for v in r['nativePrecombined'][m].values()) for r in results) for m in RULES},
              'nativeVertexCapture': False, 'productionActivation': False, 'msaaAcceptance': False,
              'artifactCount': len(artifacts), 'results': results, 'artifactSHA256': artifacts}
    if args.compare:
        other = args.compare
        names = {p.name for p in other.iterdir() if p.is_file() and p.name != 'analysis.json'}
        require(names == set(artifacts), 'different cross-architecture artifact membership')
        for name, digest in artifacts.items():
            require(hashlib.sha256((other/name).read_bytes()).hexdigest() == digest, 'cross-architecture bytes differ: '+name)
        result['crossArchitectureExact'] = True
    (root/'analysis.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('results', 'artifactSHA256')}, indent=2))


if __name__ == '__main__':
    main()
