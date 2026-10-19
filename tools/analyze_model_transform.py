"""Audit fixed XY/W and triangle-order controls; never infer native registers."""
import argparse
import csv
import hashlib
import json
import math
import struct
from pathlib import Path
from analyze_accessory_isolation import tags, fnv
from analyze_model_sampling import floats, metrics, require


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def dot(a, b, rule):
    if rule == 'double':
        total = 0.
        for u, v in zip(a, b):
            total += u*v
        return f32(total)
    if rule == 'fused':
        total = 0.
        for u, v in zip(a, b):
            total = f32(math.fma(u, v, total))
        return total
    p = [f32(u*v) for u, v in zip(a, b)]
    if rule == 'paired':
        return f32(f32(p[0]+p[1])+f32(p[2]+p[3]))
    total = 0.
    for value in p:
        total = f32(total+value)
    return total


def multiply(a, b, rule):
    return [dot(a[row*4:row*4+4], b[col::4], rule) for row in range(4) for col in range(4)]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pack(vertices):
    return b''.join(struct.pack('<6f', *v) for v in vertices)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('sampling_reference', type=Path)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--material-reference', type=Path, required=True)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    source, reference, root = args.archive, args.sampling_reference, args.evidence
    meta = tags((root/'metadata.txt').read_text())
    run = tags((root/'summary.txt').read_text())
    require(all(run.get(k) == v for k, v in {'complete': '1', 'triangles': '3', 'repeats': '3', 'gpuSoRepeats': '3',
                'materialRepeats': '3', 'nativeVertexCapture': '0', 'productionActivation': '0', 'imageAcceptance': '0'}.items()), 'invalid completion summary')
    require(meta.get('roi') == '847,333,42,27' and meta.get('samples') == '1' and meta.get('nativeVertexCapture') == '0' and meta.get('productionActivation') == '0', 'wrong diagnostic geometry')
    x, y, w, h = [int(v) for v in meta['roi'].split(',')]
    state = (source/'history_replay.scene_prefix.draw42.state').read_text().splitlines()
    desc = tags(state[0]);viewport = tags(next(s for s in state if s.startswith('VIEWPORT ')))
    v = {k: float(value) for k, value in viewport.items()}
    matrices = [[f32(float(tags(next(s for s in state if s.startswith(kind+' ')))[f'f{k}'])) for k in range(16)] for kind in ('WORLD', 'VIEW', 'PROJECTION')]
    world, view, projection = matrices
    rules = ('sequential', 'double', 'paired', 'fused')
    combined = {rule: multiply(multiply(world, view, rule), projection, rule) for rule in rules}
    with (root/'matrices.csv').open(newline='') as file:
        matrix_rows = list(csv.DictReader(file))
    require(len(matrix_rows) == 64, 'missing matrix coefficients')
    for n, row in enumerate(matrix_rows):
        rule, k = rules[n//16], n%16
        wanted = combined[rule][k]
        require(row['mode'] == rule and int(row['k']) == k and struct.pack('<f', float(row['value'])) == struct.pack('<f', wanted)
                and int(row['bits']) == struct.unpack('<I', struct.pack('<f', wanted))[0], 'matrix arithmetic differs')
    with (root/'observations.csv').open(newline='') as file:
        rows = list(csv.DictReader(file))
    indexed = {(int(r['triangle']), r['mode'], r['channel']): r for r in rows}
    require(len(rows) == len(indexed) == int(run['observations']), 'duplicate/missing observations')
    native_modes = {'original', *[f'original_repeat{n}' for n in range(1, 4)],
                    *[f'native_{prefix}_{r}' for prefix in ('precombined', 'worldview') for r in rules],
                    *[f'{prefix}_rhw_{r}' for prefix in ('baseline', 'fused_xy') for r in ('float', 'double')],
                    *[f'native_order{n}' for n in range(1, 6)]}
    shared_modes = {'baseline', *[f'baseline_repeat{n}' for n in range(1, 4)],
                    *[f'matrix_{m}_dot_{d}' for m in rules for d in rules], 'fused_xy_hold_zw', 'fused_x_only', 'fused_y_only',
                    *[f'{prefix}_order{n}' for prefix in ('baseline', 'fused_xy') for n in range(1, 6)]}
    channels = ('sample', 'uv', 'gradients')
    require(set(indexed) == {(t, mode, c) for t in (1478, 1822, 1823) for mode in native_modes|shared_modes for c in channels}, 'missing control branch')
    artifacts, result_metrics, geometry = {}, {}, []

    def raw(name, size):
        b = (root/name).read_bytes()
        require(len(b) == size, 'wrong binary extent: '+name)
        artifacts[name] = sha(b)
        return b

    source_vertices = (source/'history_replay.scene_prefix.draw42.vertices').read_bytes()
    source_indices = (source/'history_replay.scene_prefix.draw42.indices').read_bytes()
    native_log = (source/'history_replay.dx9').read_text().splitlines()
    index_desc = tags(next(s for s in native_log if s.startswith('BUFFER sequence=42 kind=index ')))
    step = 2 if index_desc['format'] == '101' else 4
    permutations = ((0, 1, 2), (1, 2, 0), (2, 0, 1), (0, 2, 1), (2, 1, 0), (1, 0, 2))
    for t in (1478, 1822, 1823):
        label = f'compact_{t}'
        baseline_b = raw(label+'.baseline.input', 72)
        require(baseline_b == (reference/(label+'.input')).read_bytes(), 'prior GPU geometry changed')
        baseline = [list(v) for v in struct.iter_unpack('<6f', baseline_b)]
        model_b = raw(label+'.model.vertices', 96)
        model = [list(v) for v in struct.iter_unpack('<8f', model_b)]
        at = int(desc['start'])+t*3
        indices = [int.from_bytes(source_indices[(at+n)*step:(at+n+1)*step], 'little') for n in range(3)]
        for n, i in enumerate(indices):
            require(model_b[n*32:n*32+24] == source_vertices[i*32:i*32+24] and model[n][6:] == baseline[n][4:], 'model bytes changed beyond UV crossfeed')
        inputs = {'baseline': baseline, **{f'baseline_repeat{n}': baseline for n in range(1, 4)}}
        for m in rules:
            for d in rules:
                values = []
                for n in range(3):
                    object_value = model[n][:3]+[1.]
                    clip = [dot(object_value, combined[m][col::4], d) for col in range(4)]
                    values.append(clip+baseline[n][4:])
                inputs[f'matrix_{m}_dot_{d}'] = values
        fused = [p[:2]+baseline[n][2:] for n, p in enumerate(inputs['matrix_sequential_dot_fused'])]
        inputs['fused_xy_hold_zw'] = fused
        inputs['fused_x_only'] = [[fused[n][0], *b[1:]] for n, b in enumerate(baseline)]
        inputs['fused_y_only'] = [[b[0], fused[n][1], *b[2:]] for n, b in enumerate(baseline)]
        for perm in range(1, 6):
            inputs[f'baseline_order{perm}'] = [baseline[n] for n in permutations[perm]]
            inputs[f'fused_xy_order{perm}'] = [fused[n] for n in permutations[perm]]
        for mode, values in inputs.items():
            require(raw(label+'_'+mode+'.input', 72) == pack(values), 'submitted clip arithmetic/order: '+mode)
        for repeat in range(4):
            name = label+'.gpu_fused_xy'+(f'.repeat{repeat}' if repeat else '')+'.input'
            require(raw(name, 72) == pack(fused), 'GPU fused XY output differs from CPU')
        for prefix, vertices in (('baseline', baseline), ('fused_xy', fused)):
            for rule in ('float', 'double'):
                values = []
                for p in vertices:
                    px, py, pz, pw = p[:4]
                    if rule == 'double':
                        screen = [f32(v['x']+(px/pw+1)*v['width']*.5), f32(v['y']+(1-py/pw)*v['height']*.5), f32(pz/pw), f32(1/pw)]
                    else:
                        screen = [f32(v['x']+f32(f32(f32(f32(px/pw)+1)*v['width'])/2)),
                                  f32(v['y']+f32(f32(f32(1-f32(py/pw))*v['height'])/2)),
                                  f32(v['minZ']+f32(f32(pz/pw)*f32(v['maxZ']-v['minZ']))), f32(1/pw)]
                    values.append(screen+p[4:])
                require(raw(label+f'_{prefix}_rhw_{rule}.vertices', 72) == pack(values), 'pretransformed screen arithmetic')
        expected = {c: (reference/(label+'.native_vertex_'+c+'.float')).read_bytes() for c in channels}
        for mode in native_modes|shared_modes:
            if mode in native_modes:
                submitted_model = model_b
                submitted_matrices = matrices
                identity = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]
                if mode.startswith('native_precombined_'):
                    submitted_matrices = [identity, identity, combined[mode.removeprefix('native_precombined_')]]
                elif mode.startswith('native_worldview_'):
                    rule = mode.removeprefix('native_worldview_')
                    submitted_matrices = [multiply(world, view, rule), identity, projection]
                elif mode.startswith('native_order'):
                    perm = permutations[int(mode.removeprefix('native_order'))]
                    submitted_model = b''.join(model_b[n*32:(n+1)*32] for n in perm)
                elif '_rhw_' in mode:
                    submitted_model = (root/(label+'_'+mode+'.vertices')).read_bytes()
                require(raw(label+'_'+mode+'.submitted.vertices', len(submitted_model)) == submitted_model, 'native input changed')
                require(raw(label+'_'+mode+'.submitted.transforms', 192) == b''.join(struct.pack('<16f', *m) for m in submitted_matrices), 'native matrices changed')
            control = {}
            for c in channels:
                row = indexed[t, mode, c]
                a = raw(label+'_'+mode+'_'+c+'.native.float', w*h*16)
                measured = sum(a[p:p+16] != expected[c][p:p+16] for p in range(0, len(a), 16))
                require(measured == int(row['nativeVsReference']), 'native pixels contradict table')
                if mode in native_modes:
                    require(row['candidateVsReference'] == row['betweenApis'] == '-1', 'unexpected second API')
                    control[c] = {'nativeVsReference': measured}
                else:
                    b = raw(label+'_'+mode+'_'+c+'.candidate.float', w*h*16)
                    cm = sum(b[p:p+16] != expected[c][p:p+16] for p in range(0, len(b), 16))
                    between = sum(a[p:p+16] != b[p:p+16] for p in range(0, len(a), 16))
                    require(cm == int(row['candidateVsReference']) and between == int(row['betweenApis']), 'candidate pixels contradict table')
                    require(between == 0, 'common-input APIs disagree')
                    control[c] = {'nativeVsReference': measured, 'candidateVsReference': cm, 'betweenApis': between}
                require(all(math.isfinite(value) for pixel in floats(a) for value in pixel), 'nonfinite control')
                if mode == 'original' or mode.startswith('original_repeat'):
                    require(a == expected[c], 'native reference/repetition drift')
                if mode.startswith('baseline_repeat'):
                    require(a == (root/(label+'_baseline_'+c+'.native.float')).read_bytes(), 'shared baseline repetition drift')
                if mode.startswith('native_order') or mode.startswith('native_precombined') or mode.startswith('native_worldview') or mode.startswith('fused_xy_order') or mode == 'fused_xy_hold_zw' or mode == 'fused_y_only':
                    require(a == expected[c], 'previously exact isolation control changed')
            result_metrics[f'{t}:{mode}'] = control
        deltas = []
        for n in range(3):
            b, f = baseline[n], fused[n]
            changes = [k for k in range(4) if struct.pack('<f', b[k]) != struct.pack('<f', f[k])]
            deltas.append({'vertexIndex': indices[n], 'baselineClip': b[:4], 'fusedClip': f[:4], 'changedComponents': changes,
                           'delta': [f[k]-b[k] for k in range(4)],
                           'bitDelta': [struct.unpack('<I', struct.pack('<f', f[k]))[0]-struct.unpack('<I', struct.pack('<f', b[k]))[0] for k in range(4)]})
        geometry.append({'triangleZeroBased': t, 'sourceIndices': indices, 'clipChanges': deltas,
                         'fusedMatchesAllNativeChannels': all(result_metrics[f'{t}:fused_xy_hold_zw'][c]['candidateVsReference'] == 0 for c in channels),
                         'yOnlyMatchesAllNativeChannels': all(result_metrics[f'{t}:fused_y_only'][c]['candidateVsReference'] == 0 for c in channels)})
    batch = root/'material42'
    with (batch/'controls.csv').open(newline='') as file:
        batch_rows = list(csv.DictReader(file))
    require([r['mode'] for r in batch_rows] == ['original', 'repeat1', 'repeat2', 'repeat3'], 'material repetition missing')
    original_native = (args.material_reference/'isolated42.native.bgra').read_bytes()
    material_metrics = []
    for row in batch_rows:
        name = row['mode']
        a = (batch/(name+'.native.bgra')).read_bytes();b = (batch/(name+'.candidate.bgra')).read_bytes()
        require(a == original_native and len(a) == int(v['width']*v['height']*4) and len(a) == len(b), 'full material native reference drift')
        pixels = sum(a[p:p+4] != b[p:p+4] for p in range(0, len(a), 4));maximum = max(abs(u-z) for u, z in zip(a, b))
        require(pixels == int(row['differentPixels']) and maximum == int(row['maxDelta']) and fnv(a) == int(row['nativeHash']) and fnv(b) == int(row['candidateHash']), 'material pixel metrics drift')
        require(int(row['triangles']) == int(desc['count']) and int(row['firstTriangle']) == 0, 'material draw range changed')
        for side, image in (('native', a), ('candidate', b)):
            require(image == (batch/('original.'+side+'.bgra')).read_bytes(), 'material repetition drift')
            artifacts['material42/'+name+'.'+side+'.bgra'] = sha(image)
        material_metrics.append({'mode': name, 'differentPixels': pixels, 'maxDelta': maximum})
    with (batch/'pixels.csv').open(newline='') as file:
        require(list(csv.DictReader(file)) == [], 'unexpected full-material focus observations')
    policy = tags((batch/'xy_policy.txt').read_text())
    require(policy.get('fusedXY') == '1' and policy.get('GPUStreamOutputMatchesCPU') == '1' and policy.get('productionActivation') == '0', 'wrong material policy')
    for name in ('metadata.txt', 'summary.txt', 'observations.csv', 'matrices.csv', 'material42/controls.csv',
                 'material42/pixels.csv', 'material42/xy_policy.txt', 'material42/mode.txt'):
        artifacts[name] = sha((root/name).read_bytes())
    actual_artifacts = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.suffix != '.json'}
    require(set(artifacts) == actual_artifacts, 'unexpected or missing artifacts')
    if args.compare:
        other = {p.relative_to(args.compare).as_posix(): sha(p.read_bytes()) for p in args.compare.rglob('*') if p.is_file() and p.suffix != '.json'}
        require(artifacts == other, 'identical-input architecture artifacts differ')
    result = {'observations': len(rows), 'geometry': geometry, 'controlMetrics': result_metrics, 'material42': material_metrics,
              'artifacts': artifacts, 'crossArchitectureExact': bool(args.compare), 'nativeVertexCapture': False,
              'productionActivation': False, 'fullSceneAcceptance': False}
    (root/'analysis.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('artifacts', 'controlMetrics')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
