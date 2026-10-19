"""Audit UV/gradient and float-color evidence without accepting renderer parity."""
import argparse
import csv
import hashlib
import json
import math
import struct
from pathlib import Path
from analyze_accessory_isolation import tags


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def floats(data):
    require(len(data) % 16 == 0, 'invalid float image')
    result = list(struct.iter_unpack('<4f', data))
    require(all(math.isfinite(v) for p in result for v in p), 'nonfinite pixel')
    return result


def metrics(a, b):
    require(len(a) == len(b), 'different image sizes')
    return {'differentPixels': sum(x != y for x, y in zip(a, b)),
            'maxAbsDelta': max((abs(u-v) for x, y in zip(a, b) for u, v in zip(x, y)), default=0)}


def quantize(pixel):
    # Diagnostic conversion model only; require agreement with saved bytes.
    return bytes(max(0, min(255, math.floor(v*255+0.5))) for v in pixel)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    root, reference, source = args.evidence, args.reference, args.archive
    meta = tags((root/'metadata.txt').read_text())
    require(meta.get('draw') == '42' and meta.get('samples') == '1' and meta.get('center') == 'viewport' and meta.get('productionActivation') == '0', 'wrong diagnostic mode')
    x, y, w, h = [int(v) for v in meta['roi'].split(',')]
    count = w*h
    state = (source/'history_replay.scene_prefix.draw42.state').read_text().splitlines()
    viewport = tags(next(s for s in state if s.startswith('VIEWPORT ')))
    vx, vy, vw, vh = [int(viewport[k]) for k in ('x', 'y', 'width', 'height')]
    target = tags(next(s for s in state if s.startswith('TARGET ')))
    require(meta['width'] == target['width'] and meta['height'] == target['height'] and target['samples'] == '0', 'wrong target')
    require(vx <= x < x+w <= vx+vw and vy <= y < y+h <= vy+vh, 'ROI outside viewport')
    run = tags((root/'summary.txt').read_text())
    for key, value in {'complete': '1', 'triangles': '3', 'dx11ByteReferenceExact': '1', 'dx9ProxyIsDiagnostic': '1',
                       'nativeVertexPsFloatExact': '1', 'repeats': '3', 'productionActivation': '0', 'imageAcceptance': '0'}.items():
        require(run.get(key) == value, 'incomplete measurement: '+key)
    with (root/'observations.csv').open(newline='') as file:
        rows = list(csv.DictReader(file))
    indexed = {(int(r['triangle']), r['mode'], int(r['format'])): r for r in rows}
    require(len(indexed) == len(rows) == int(run['measurements']), 'duplicate or missing observations')
    modes = [('auto', 0, 0, f) for f in (0, 1)]
    modes += [(f'auto_repeat{n}', 0, 0, 1) for n in (1, 2, 3)]
    modes += [('uv', 1, 0, 1), ('gradients', 2, 0, 1), ('explicit_grad', 3, 0, 1)]
    modes += [('legacy_auto', 0, 0, f) for f in (0, 1)]
    modes += [('legacy_uv', 1, 0, 1), ('legacy_gradients', 2, 0, 1)]
    modes += [(name, 0, filter_mode, f) for name, filter_mode in (('linear_auto', 1), ('point_auto', 2)) for f in (0, 1)]
    modes += [(f'lod{lod}', lod+4, 1, f) for lod in range(9) for f in (0, 1)]
    require(set(indexed) == {(t, name, f) for t in (1478, 1822, 1823) for name, _, _, f in modes}, 'wrong observation set')
    with (root/'gates.csv').open(newline='') as file:
        gates = list(csv.DictReader(file))
    require([int(r['triangle']) for r in gates] == [1478, 1822, 1823], 'wrong gate membership')
    with (root/'crossfeed.csv').open(newline='') as file:
        feed = list(csv.DictReader(file))
    require(len(feed) == int(run['crossfeed']), 'missing crossfeed data')
    feed_membership, triangle_results, control_results, expected_artifacts = set(), [], {}, set()
    rounding_controls = {}

    def raw(name, size):
        expected_artifacts.add(name)
        data = (root/name).read_bytes()
        require(len(data) == size, 'artifact size: '+name)
        return data

    def ref_image(t, side):
        b = (reference/f'compact_{t}_pure_shared_uv.{side}.bgra').read_bytes()
        require(len(b) == vw*vh*4, 'reference size')
        visible = [p for p, (v,) in enumerate(struct.iter_unpack('<I', b)) if v != 0xffffffff]
        require(all(x <= vx+p%vw < x+w and y <= vy+p//vw < y+h for p in visible), 'ROI dropped reference pixels')
        return b''.join(bytes((b[at+2], b[at+1], b[at], b[at+3])) for yy in range(y, y+h) for xx in range(x, x+w)
                        for at in [((yy-vy)*vw+xx-vx)*4])

    for t, gate in zip((1478, 1822, 1823), gates):
        label = f'compact_{t}'
        observed = (reference/(label+'.sphere.so')).read_bytes()
        vertices = raw(label+'.input', 72)
        require(vertices == b''.join(observed[n*40:n*40+24] for n in range(3)), 'shared clip/UV differs from prior SO')
        images, byte_images = {}, {}
        for name, shader, filter_mode, f in modes:
            r = indexed[t, name, f]
            require((int(r['shader']), int(r['filter'])) == (shader, filter_mode), 'wrong shader/filter description')
            if f:
                pair = tuple(floats(raw(f'{label}_{name}.{side}.float', count*16)) for side in ('dx9', 'dx11'))
                images[name] = pair
            else:
                byte_pair = tuple(raw(f'{label}_{name}.{side}.rgba', count*4) for side in ('dx9', 'dx11'))
                byte_images[name] = byte_pair
                pair = tuple([tuple(v/255 for v in b[p:p+4]) for p in range(0, len(b), 4)] for b in byte_pair)
            measured = metrics(*pair)
            require(int(r['differentPixels']) == measured['differentPixels'] and math.isclose(float(r['maxAbsDelta']), measured['maxAbsDelta'], rel_tol=1e-14, abs_tol=1e-15), 'reported metrics contradict image')
            control_results[f'{t}:{name}:{f}'] = measured
        native_ref, candidate_ref = ref_image(t, 'native'), ref_image(t, 'candidate')
        require(candidate_ref == byte_images['auto'][1], 'DX11 proxy failed reference')
        proxy_diff = sum(native_ref[p:p+4] != byte_images['auto'][0][p:p+4] for p in range(0, count*4, 4))
        require(proxy_diff == int(gate['sharedDx9ReferencePixels']) and int(gate['sharedDx11ReferencePixels']) == 0, 'proxy gate contradiction')
        covered = [p for p in range(count) if native_ref[p*4:p*4+4] != b'\xff'*4]
        require(len(covered) > 0, 'empty triangle')
        native = {}
        native['fixed'] = floats(raw(label+'.fixed.float', count*16))
        require(raw(label+'.frozen_fixed.float', count*16) == (root/(label+'.fixed.float')).read_bytes(), 'mip regeneration changed float color')
        for name in ('sample', 'uv', 'gradients', 'explicit_grad', 'lod0'):
            native[name] = floats(raw(label+'.native_vertex_'+name+'.float', count*16))
            if name in ('sample', 'explicit_grad', 'lod0'):
                b = raw(label+'.native_vertex_'+name+'.rgba', count*4)
                if name == 'sample':
                    require(b == native_ref and int(gate['nativeVertexPsReferencePixels']) == 0, 'native vertex PS changed reference')
                predicted = b''.join(quantize(p) for p in native[name])
                rounding_controls[f'{t}:native:{name}'] = {'differentPixels': sum(predicted[p:p+4] != b[p:p+4] for p in range(0, count*4, 4)),
                                                         'maxByteDelta': max(abs(u-v) for u, v in zip(predicted, b))}
        require(native['fixed'] == native['sample'] == native['explicit_grad'], 'native PS/explicit-gradient observation changed original float sample')
        for name in ('sample', 'uv', 'gradients'):
            for n in (1, 2, 3):
                require(raw(label+f'.native_vertex_{name}.repeat{n}.float', count*16) == (root/(label+f'.native_vertex_{name}.float')).read_bytes(), 'native-vertex observation unstable')
        for name in ('auto', 'legacy_auto', 'linear_auto', 'point_auto', *[f'lod{n}' for n in range(9)]):
            for side in (0, 1):
                predicted = b''.join(quantize(p) for p in images[name][side])
                b = byte_images[name][side]
                rounding_controls[f'{t}:shared{side}:{name}'] = {'differentPixels': sum(predicted[p:p+4] != b[p:p+4] for p in range(0, count*4, 4)),
                                                              'maxByteDelta': max(abs(u-v) for u, v in zip(predicted, b))}
        for n in (1, 2, 3):
            require(images[f'auto_repeat{n}'] == images['auto'], 'sampling repetition unstable')
        require(images['legacy_uv'] == images['uv'] and images['legacy_gradients'] == images['gradients'] and images['legacy_auto'] == images['auto'], 'shared shader model linkage drift')
        require(images['explicit_grad'] == images['auto'], 'shared explicit gradients changed sample')
        uv_delta = metrics(native['uv'], images['uv'][1])
        gradient_delta = metrics(native['gradients'], images['gradients'][1])
        restored, pixel_observations = {}, []
        for input_path in range(4):
            subset = [row for row in feed if int(row['triangle']) == t and int(row['inputPath']) == input_path]
            require(len(subset) == len(covered), 'incomplete crossfeed coverage')
            expected_pixels = []
            cross_native, cross_candidate, target_native, target_candidate = [], [], [], []
            actual_native, actual_candidate, wanted_native, wanted_candidate = [], [], [], []
            for row in subset:
                xx, yy = int(row['x']), int(row['y'])
                p = (yy-y)*w+xx-x
                require(x <= xx < x+w and y <= yy < y+h and p in covered, 'crossfeed outside geometry')
                key = (t, xx, yy, input_path)
                require(key not in feed_membership, 'duplicate crossfeed')
                feed_membership.add(key)
                shared_value = input_path in (1, 3)
                shared_gradient = input_path in (1, 2)
                uv = images['uv'][1][p] if shared_value else native['uv'][p]
                gradient = images['gradients'][1][p] if shared_gradient else native['gradients'][p]
                actual_input = [float(row[k]) for k in ('u', 'v', 'dxU', 'dxV', 'dyU', 'dyV')]
                require(actual_input == [*uv[:2], *gradient], 'crossfeed fitted or changed recorded input')
                a = tuple(float(row['n'+k]) for k in 'RGBA')
                b = tuple(float(row['c'+k]) for k in 'RGBA')
                aa = bytes(int(row['n'+k+'8']) for k in 'RGBA')
                bb = bytes(int(row['c'+k+'8']) for k in 'RGBA')
                require(all(math.isfinite(v) and struct.unpack('<f', struct.pack('<f', v))[0] == v for v in (*a, *b)), 'invalid float32 crossfeed')
                if input_path in (0, 1):
                    wanted = images['auto'][1][p] if input_path else native['fixed'][p]
                    require(a == b == wanted, 'crossfeed failed to recover original float colors')
                    wanted_byte = candidate_ref[p*4:p*4+4] if input_path else native_ref[p*4:p*4+4]
                    require(aa == bb == wanted_byte, 'crossfeed failed to recover actual RGBA8 colors')
                expected_pixels.append(p)
                cross_native.append(a);cross_candidate.append(b)
                target_native.append(native['fixed'][p]);target_candidate.append(images['auto'][1][p])
                actual_native.append(aa);actual_candidate.append(bb)
                wanted_native.append(native_ref[p*4:p*4+4]);wanted_candidate.append(candidate_ref[p*4:p*4+4])
                if input_path == 0:
                    pixel_observations.append({'xy': [xx, yy], 'nativeUV': list(native['uv'][p][:2]), 'candidateUV': list(images['uv'][1][p][:2]),
                                               'nativeGradients': list(native['gradients'][p]), 'candidateGradients': list(images['gradients'][1][p]),
                                               'nativeSample': list(native['fixed'][p]), 'candidateSample': list(images['auto'][1][p])})
            require(expected_pixels == covered, 'crossfeed omitted/reordered independent coordinates')
            restored[str(input_path)] = {'pixels': len(subset), 'betweenSamplers': metrics(cross_native, cross_candidate),
                                        'vsNative': metrics(cross_candidate, target_native), 'vsCandidate': metrics(cross_candidate, target_candidate),
                                        'actualBytePixelsBetweenSamplers': sum(a != b for a, b in zip(actual_native, actual_candidate)),
                                        'actualBytePixelsVsNative': sum(a != b for a, b in zip(actual_candidate, wanted_native)),
                                        'actualBytePixelsVsCandidate': sum(a != b for a, b in zip(actual_candidate, wanted_candidate)),
                                        'roundHalfUpPredictionPixelsVsNative': sum(quantize(a) != quantize(b) for a, b in zip(cross_candidate, target_native)),
                                        'roundHalfUpPredictionPixelsVsCandidate': sum(quantize(a) != quantize(b) for a, b in zip(cross_candidate, target_candidate))}
        triangle_results.append({'triangleZeroBased': t, 'coveredPixels': len(covered), 'dx9SharedProxyReferencePixels': proxy_diff,
                                 'nativeVsCandidateFloat': metrics(native['fixed'], images['auto'][1]), 'uv': uv_delta, 'gradients': gradient_delta,
                                 'nativeVsCandidateLod0': metrics(native['lod0'], images['lod0'][1]), 'crossfeed': restored,
                                 'pixels': pixel_observations})
    require(len(feed_membership) == len(feed), 'unknown crossfeed triangle/path')
    expected_artifacts |= {'metadata.txt', 'summary.txt', 'observations.csv', 'gates.csv', 'crossfeed.csv'}
    artifacts = {p.name: sha(p.read_bytes()) for p in sorted(root.iterdir()) if p.is_file() and p.suffix != '.json'}
    require(set(artifacts) == expected_artifacts, 'unexpected/missing evidence artifacts')
    if args.compare:
        other = {p.name: sha(p.read_bytes()) for p in sorted(args.compare.iterdir()) if p.is_file() and p.suffix != '.json'}
        require(other == artifacts, 'identical-input architecture evidence differs')
    result = {'measurements': len(rows), 'crossfeed': len(feed), 'roi': [x, y, w, h], 'triangles': triangle_results,
              'controlMetrics': control_results, 'roundHalfUpControls': rounding_controls, 'artifacts': artifacts, 'crossArchitectureExact': bool(args.compare),
              'ownedSourceProof': {p.name: sha(p.read_bytes()) for p in sorted(source.glob('history_replay.scene_prefix.draw42.*')) if not p.name.endswith('.bgra')},
              'productionActivation': False, 'imageAcceptance': False}
    (root/'analysis.json').write_text(json.dumps(result, indent=2)+'\n')
    compact = {k: v for k, v in result.items() if k not in ('artifacts', 'controlMetrics', 'roundHalfUpControls', 'ownedSourceProof', 'triangles')}
    compact['triangles'] = [{k: v for k, v in t.items() if k != 'pixels'} for t in triangle_results]
    print(json.dumps(compact))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
