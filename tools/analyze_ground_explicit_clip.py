"""Audit equal-input explicit clipping controls; this does not accept scene parity."""
import argparse
import hashlib
import json
import math
import struct
from pathlib import Path
from analyze_ground_endpoint_depth import baseline, clips, rows, value
from analyze_accessory_isolation import fnv, tags
from analyze_scene_prefix import difference


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


POLICIES = {'deferred': ('deferred', 15), 'nearest': ('nearest', 15),
            'zero': ('zero', 15), 'down': ('down', 15), 'up': ('up', 15),
            'nearest_z': ('nearest', 4), 'nearest_xyw': ('nearest', 11),
            'nearest_x': ('nearest', 1), 'nearest_y': ('nearest', 2), 'nearest_w': ('nearest', 8)}


def round_intersection(x, policy):
    if policy == 'deferred':
        return x
    nearest = f32(x)
    if nearest == x or policy == 'nearest':
        return nearest
    if policy == 'zero':
        direction = 1 if x < 0 else -1
        move = (x < 0 and nearest < x) or (x > 0 and nearest > x)
    else:
        direction = -1 if policy == 'down' else 1
        move = nearest > x if policy == 'down' else nearest < x
    if not move:
        return nearest
    bits = struct.unpack('<I', struct.pack('<f', nearest))[0]
    if nearest == 0:
        bits = 1 if direction > 0 else 0x80000001
    else:
        bits += direction if nearest > 0 else -direction
    return struct.unpack('<f', struct.pack('<I', bits))[0]


def packed(vertices):
    return b''.join(struct.pack('<4f', *v) for v in vertices)


def planes(w, h, guard):
    x, y = 1 - 2.0 * guard / w, 1 - 2.0 * guard / h
    return [(1, 0, 0, x), (-1, 0, 0, x), (0, 1, 0, y),
            (0, -1, 0, y), (0, 0, 1, 0), (0, 0, -1, 1)]


def distance(vertex, plane):
    result = 0.0
    for v, p in zip(vertex, plane):
        result += v * p
    return result


def intersection(a, b, da, db, policy=None, plane=0, trace=None):
    t = da / (da - db)
    before = tuple(x + (y - x) * t for x, y in zip(a, b))
    rule, mask = policy or ('deferred', 15)
    after = tuple(round_intersection(x, rule) if mask & (1 << k) else x for k, x in enumerate(before))
    if trace is not None:
        trace.append((plane, before, after))
    return after


def explicit_line(source, boundaries, policy=None, trace=None):
    a, b = source
    for at, plane in enumerate(boundaries):
        da, db = distance(a, plane), distance(b, plane)
        if da < 0 and db < 0:
            return []
        if (da >= 0) != (db >= 0):
            p = intersection(a, b, da, db, policy, at, trace)
            if da < 0:
                a = p
            else:
                b = p
    return [tuple(f32(x) for x in v) for v in (a, b)]


def explicit_polygon(source, boundaries, policy=None, trace=None):
    polygon = source
    for at, plane in enumerate(boundaries):
        if not polygon:
            break
        output = []
        previous = polygon[-1]
        dp = distance(previous, plane)
        for current in polygon:
            dc = distance(current, plane)
            if (dp >= 0) != (dc >= 0):
                output.append(intersection(previous, current, dp, dc, policy, at, trace))
            if dc >= 0:
                output.append(current)
            previous, dp = current, dc
        polygon = output
    return [tuple(f32(x) for x in v) for v in polygon]


def fan(polygon, anchor):
    result = []
    for n in range(1, len(polygon) - 1):
        result.extend((polygon[anchor], polygon[(anchor + n) % len(polygon)],
                       polygon[(anchor + n + 1) % len(polygon)]))
    return result


def interior(vertices, w, h):
    # Mirror float32 center arithmetic, then require a strict positive margin.
    for x, y, z, cw in vertices:
        if not all(math.isfinite(v) for v in (x, y, z, cw)) or cw <= 0:
            return False
        for cx, cy in ((x, y), (f32(x + f32(f32(1.0 / w) * cw)),
                                f32(y - f32(f32(1.0 / h) * cw)))):
            if not (-cw < cx < cw and -cw < cy < cw and 0 < z < cw):
                return False
    return bool(vertices)


def check_geometry(path, expected):
    if path.read_bytes() != packed(expected):
        raise ValueError(f'{path.name}: independent CPU clipping differs')


def rounding_variants():
    return {f'{base}_{policy}': (guard, policy) for base, guard in (('canonical', 0), ('guard2', 2)) for policy in POLICIES}


def stage_variants():
    return {f'{base}_{center}': (base, center, 2 if base == 'guard2' else 0)
            for base in ('raw', 'near_far', 'six_plane', 'guard2') for center in ('shader', 'viewport')}


def stage_planes(base, w, h, guard):
    p = planes(w, h, guard)
    return [(0, 0, 0, 0)] * 4 + p[4:] if base == 'near_far' else p


def audit_stages(root, region, kind, result):
    x, y, w, h = region
    descriptions = rows(root / 'stages.csv')
    triangles = range(1 if kind == 'lines' else 2)
    if [(r['variant'], int(r['triangle'])) for r in descriptions] != [(v, t) for v in stage_variants() for t in triangles]:
        raise ValueError('missing center/plane controls')
    for row in descriptions:
        name, t = row['variant'], int(row['triangle'])
        base, center, guard = stage_variants()[name]
        shifted = center == 'viewport'
        wanted = [('geometry', base), ('center', center), ('viewportX', x + (.5 if shifted else 0)),
                  ('viewportY', y + (.5 if shifted else 0)), ('width', w), ('height', h),
                  ('minDepth', 0), ('maxDepth', 1), ('shaderShift', int(not shifted))]
        for key, val in wanted:
            actual = row[key] if isinstance(val, str) else float(row[key])
            if actual != val:
                raise ValueError('observed stage description changed')
        stem = name if kind == 'lines' else f'{name}_t{t}'
        vertices = clips(root / f'{stem}.clip.bin')
        expected = vertices if shifted else [(f32(v[0] + f32(f32(1.0 / w) * v[3])),
                    f32(v[1] - f32(f32(1.0 / h) * v[3])), v[2], v[3]) for v in vertices]
        check_geometry(root / f'{stem}.shader_clip.bin', expected)
        other = f'{base}_shader' if shifted else f'{base}_viewport'
        other_stem = other if kind == 'lines' else f'{other}_t{t}'
        if packed(vertices) != (root / f'{other_stem}.clip.bin').read_bytes():
            raise ValueError('geometries differ between center stages')
        if kind == 'lines':
            if (root / f'{name}.native.bgra').read_bytes() != (root / f'{other}.native.bgra').read_bytes():
                raise ValueError('DX9 line baseline changed between center stages')
    if kind == 'depth':
        table = {(r['variant'], r['triangle'], r['point']): r for r in result['thresholds']}
        for base in ('raw', 'near_far', 'six_plane', 'guard2'):
            for t in range(2):
                for p in range(3):
                    if table[(base + '_shader', t, p)]['dx9ThresholdBits'] != table[(base + '_viewport', t, p)]['dx9ThresholdBits']:
                        raise ValueError('DX9 depth baseline changed between center stages')
        comparison = {base: {center: [table[(base + '_' + center, t, p)]['dx11ThresholdBits'] -
                             table[(base + '_' + center, t, p)]['dx9ThresholdBits'] for t in range(2) for p in range(3)]
                             for center in ('shader', 'viewport')} for base in ('raw', 'near_far', 'six_plane', 'guard2')}
    else:
        comparison = {base: {center: result['lineMetrics'][base + '_' + center]['differentPixels']
                             for center in ('shader', 'viewport')} for base in ('raw', 'near_far', 'six_plane', 'guard2')}
    return {'centerStages': True, 'GPUShaderOutputsExact': True, 'identicalUploadedGeometry': True,
            'nativeBaselinesUnchangedBetweenStages': True, 'stageComparison': comparison}


def audit_rounding(root, sources, region, kind):
    _, _, w, h = region
    wanted = [(name, t) for name in rounding_variants() for t in range(len(sources))]
    policy_rows = rows(root / 'rounding.csv')
    if [(r['variant'], int(r['triangle'])) for r in policy_rows] != wanted:
        raise ValueError('missing intersection policies')
    observed = rows(root / 'intersections.csv')
    expected_rows = []
    for row in policy_rows:
        name, t = row['variant'], int(row['triangle'])
        guard, key = rounding_variants()[name]
        policy = POLICIES[key]
        trace = []
        (explicit_line if kind == 'lines' else explicit_polygon)(sources[t], planes(w, h, guard), policy, trace)
        if any(str(row[k]) != str(v) for k, v in [('guardPixels', guard), ('policy', key), ('mask', policy[1]), ('intersections', len(trace))]):
            raise ValueError('policy description contradicts intersection trace')
        for n, (plane, before, after) in enumerate(trace):
            expected_rows.append((name, t, n, plane, *before, *after))
    actual = [(r['variant'], *(int(r[k]) for k in ('triangle', 'intersection', 'plane')),
               *(float(r[stage + c]) for stage in ('before', 'after') for c in ('X', 'Y', 'Z', 'W'))) for r in observed]
    if actual != expected_rows:
        raise ValueError('intersection rounding trace disagrees with independent reconstruction')
    return {'policies': list(POLICIES), 'recordedIntersections': len(observed), 'intersectionTraceExact': True}


def rounding_findings(root, result, kind, prior):
    groups = {}
    for base in ('canonical', 'guard2'):
        suffix = '.clip.bin' if kind == 'lines' else '_polygon_t0.clip.bin'
        groups[base] = {'distinctLineGeometry' if kind == 'lines' else 'distinctPlaneGeometry':
                        len({(root / (f'{base}_{p}' + suffix)).read_bytes() for p in POLICIES})}
        if kind == 'depth':
            table = {(r['variant'], r['triangle'], r['point']): r for r in result['thresholds']}
            groups[base]['planeRulerInputStepsFromDeferred'] = {
                p: [table[(f'{base}_{p}', 0, pt)]['dx9ThresholdBits'] - table[(f'{base}_deferred', 0, pt)]['dx9ThresholdBits']
                    for pt in range(3)] for p in POLICIES}
            earlier = {(int(r['triangle']), int(r['point'])): r for r in rows(prior / 'thresholds.csv') if r['path'] == 'shared_clip'}
            groups[base]['policiesMatchingOriginalDX9PlaneAtAllPoints'] = [p for p in POLICIES if all(
                table[(f'{base}_{p}', 0, pt)]['dx9ThresholdBits'] == int(earlier[(0, pt)]['dx9ThresholdBits']) for pt in range(3))]
    return {'roundingFindings': groups}


def audit_lines(root, prior, region, rounding_reference=None, stage_reference=None):
    x, y, w, h = region
    source = clips(root / 'source.clip.bin')
    if packed(source) != (prior / 'candidate.raw_clip.bin').read_bytes():
        raise ValueError('line source clip input changed')
    expected = {'raw': (source, 0)}
    for guard in (() if rounding_reference or stage_reference else (0, 2, 8)):
        name = f'guard{guard}' if guard else 'canonical'
        vertices = explicit_line(source, planes(w, h, guard))
        expected[name] = (vertices, guard)
        expected[name + '_reverse'] = (vertices[::-1], guard)
    if rounding_reference:
        for name, (guard, policy) in rounding_variants().items():
            expected[name] = (explicit_line(source, planes(w, h, guard), POLICIES[policy]), guard)
    if stage_reference:
        expected = {name: (source if base == 'raw' else explicit_line(source, stage_planes(base, w, h, guard)), guard)
                    for name, (base, _, guard) in stage_variants().items()}
    controls = rows(root / 'line_controls.csv')
    if [r['variant'] for r in controls] != list(expected):
        raise ValueError('missing or reordered line variants')
    raw_name = 'raw_shader' if stage_reference else 'raw'
    base = [(root / f'{raw_name}.{side}.bgra').read_bytes() for side in ('native', 'candidate')]
    if any(b != (prior / f'common_clip.{side}.bgra').read_bytes()
           for b, side in zip(base, ('native', 'candidate'))):
        raise ValueError('raw line images no longer match prior evidence')
    pixel_log, metrics = [], {}
    for row in controls:
        name = row['variant']
        vertices, guard = expected[name]
        check_geometry(root / f'{name}.clip.bin', vertices)
        if int(row['guardPixels']) != guard or int(row['vertices']) != len(vertices):
            raise ValueError('line geometry description changed')
        if guard and not interior(vertices, w, h):
            raise ValueError('guarded line can still require native clipping')
        if rounding_reference and name.endswith('_deferred'):
            base_name = 'guard2' if guard else 'canonical'
            check_geometry(rounding_reference / f'{base_name}.clip.bin', vertices)
        if stage_reference and stage_variants()[name][0] in ('six_plane', 'guard2'):
            base_name = 'canonical' if stage_variants()[name][0] == 'six_plane' else 'guard2'
            check_geometry(stage_reference / f'{base_name}.clip.bin', vertices)
        a, b = [(root / f'{name}.{side}.bgra').read_bytes() for side in ('native', 'candidate')]
        if len(a) != w * h * 4 or len(b) != len(a):
            raise ValueError('line readback extent differs')
        if rounding_reference and name.endswith('_deferred'):
            if any(now != (rounding_reference / f'{base_name}.{side}.bgra').read_bytes() for now, side in zip((a, b), ('native', 'candidate'))):
                raise ValueError('previous deferred line baseline changed')
        if stage_reference and stage_variants()[name][0] in ('six_plane', 'guard2') and stage_variants()[name][1] == 'shader':
            if any(now != (stage_reference / f'{base_name}.{side}.bgra').read_bytes() for now, side in zip((a, b), ('native', 'candidate'))):
                raise ValueError('previous shader-stage line baseline changed')
        changed, maximum, first = difference(a, b)
        changes = [difference(original, now)[0] for original, now in zip(base, (a, b))]
        for key, val in [('differentPixels', changed), ('maxDelta', maximum),
                         ('nativeChangedFromRaw', changes[0]), ('candidateChangedFromRaw', changes[1]),
                         ('nativeHash', fnv(a)), ('candidateHash', fnv(b))]:
            if int(row[key]) != val:
                raise ValueError(f'{name}: image contradicts {key}')
        first_xy = None if first is None else [x + first % w, y + first // w]
        if first_xy and first_xy != [int(row['firstX']), int(row['firstY'])]:
            raise ValueError('line first pixel differs')
        for at in range(0, len(a), 4):
            if a[at:at + 4] != b[at:at + 4]:
                p = at // 4
                pixel_log.append((name, x + p % w, y + p // w, *a[at:at + 4], *b[at:at + 4]))
        metrics[name] = {'differentPixels': changed, 'first': first_xy,
                         'nativeChangedFromRaw': changes[0], 'candidateChangedFromRaw': changes[1]}
    keys = ['x', 'y'] + [side + k for side in ('native', 'candidate') for k in ('B', 'G', 'R', 'A')]
    actual = [(r['variant'], *(int(r[k]) for k in keys)) for r in rows(root / 'line_pixels.csv')]
    if actual != pixel_log:
        raise ValueError('line pixel table contradicts readbacks')
    summary = tags((root / 'clip_summary.txt').read_text())
    if int(summary['variants']) != len(expected) or summary['priorRawExact'] != '1':
        raise ValueError('incomplete line control summary')
    return {'variants': len(expected), 'lineMetrics': metrics,
            'clippedLinesAgree': all(metrics[n]['differentPixels'] == 0 for n in expected if n not in ('raw', 'raw_shader', 'raw_viewport'))}


def audit_depth(root, prior, region, rounding_reference=None, stage_reference=None):
    _, _, w, h = region
    variants = {'raw': (0, 0), 'canonical': (0, 0), 'guard2': (2, 0),
                'guard2_anchor1': (2, 1), 'guard8': (8, 0)}
    if rounding_reference:
        variants = {'raw': (0, 0), **{name: (guard, 0) for name, (guard, _) in rounding_variants().items()}}
    if stage_reference:
        variants = {name: (guard, 0) for name, (_, _, guard) in stage_variants().items()}
    sources = [clips(root / f'source_t{t}.clip.bin') for t in range(2)]
    for t, source in enumerate(sources):
        if packed(source) != (prior / f'triangle{t}.raw_clip.bin').read_bytes():
            raise ValueError('triangle source clip input changed')
    geometry = rows(root / 'geometry.csv')
    if [(r['variant'], int(r['triangle'])) for r in geometry] != [(v, t) for v in variants for t in range(2)]:
        raise ValueError('missing depth geometry')
    for row in geometry:
        name, t = row['variant'], int(row['triangle'])
        guard, anchor = variants[name]
        base = stage_variants()[name][0] if stage_reference else name
        if base == 'raw':
            expected = sources[t]
        else:
            policy = POLICIES[rounding_variants()[name][1]] if rounding_reference else None
            boundaries = stage_planes(base, w, h, guard) if stage_reference else planes(w, h, guard)
            polygon = explicit_polygon(sources[t], boundaries, policy)
            poly_name = 'guard2' if name == 'guard2_anchor1' else name
            check_geometry(root / f'{poly_name}_polygon_t{t}.clip.bin', polygon)
            expected = fan(polygon, anchor)
            if rounding_reference:
                if len(polygon) != len(explicit_polygon(sources[t], planes(w, h, guard))):
                    raise ValueError('polygon topology changed with rounding')
                if name.endswith('_deferred'):
                    base_name = 'guard2' if guard else 'canonical'
                    check_geometry(rounding_reference / f'{base_name}_t{t}.clip.bin', expected)
            if stage_reference and base in ('six_plane', 'guard2'):
                base_name = 'canonical' if base == 'six_plane' else 'guard2'
                check_geometry(stage_reference / f'{base_name}_t{t}.clip.bin', expected)
        check_geometry(root / f'{name}_t{t}.clip.bin', expected)
        inside = interior(expected, w, h)
        if any(int(row[k]) != v for k, v in [('guardPixels', guard), ('anchor', anchor),
                                               ('vertices', len(expected)), ('strictInterior', int(inside))]):
            raise ValueError('triangle description contradicts geometry')
        if guard and not inside:
            raise ValueError('guarded triangle can still require native clipping')
    old = {(int(r['triangle']), int(r['point'])): r for r in rows(prior / 'thresholds.csv') if r['path'] == 'shared_clip'}
    reference = rounding_reference or stage_reference
    earlier = {(r['variant'], int(r['triangle']), int(r['point'])): r for r in rows(reference / 'thresholds.csv')} if reference else {}
    threshold = rows(root / 'thresholds.csv')
    queries = rows(root / 'queries.csv')
    expected_keys = {(v, t, p) for v in variants for t in range(2) for p in range(3)}
    actual_keys = [(r['variant'], int(r['triangle']), int(r['point'])) for r in threshold]
    if len(actual_keys) != len(expected_keys) or set(actual_keys) != expected_keys:
        raise ValueError('missing threshold measurement')
    result = []
    for row in threshold:
        key = (row['variant'], int(row['triangle']), int(row['point']))
        old_row = old[key[1:]]
        if row['repeatExact'] != '1' or any(row[k] != old_row[k] for k in ('x', 'y')):
            raise ValueError('held-out coordinate or repetition changed')
        if key[0] in ('raw', 'raw_shader') and any(row[k] != old_row[k] for k in ('dx9ThresholdBits', 'dx11ThresholdBits')):
            raise ValueError('unmodified raw threshold no longer reproduces')
        if rounding_reference and key[0].endswith('_deferred'):
            base_name = key[0].removesuffix('_deferred')
            if any(row[k] != earlier[(base_name, *key[1:])][k] for k in ('dx9ThresholdBits', 'dx11ThresholdBits')):
                raise ValueError('previous deferred depth baseline changed')
        if stage_reference:
            base, center, _ = stage_variants()[key[0]]
            if base in ('six_plane', 'guard2') and center == 'shader':
                base_name = 'canonical' if base == 'six_plane' else 'guard2'
                if any(row[k] != earlier[(base_name, *key[1:])][k] for k in ('dx9ThresholdBits', 'dx11ThresholdBits')):
                    raise ValueError('previous shader-stage depth baseline changed')
        cache, fresh = {}, {}
        for q in queries:
            if (q['variant'], int(q['triangle']), int(q['point'])) != key:
                continue
            bits, cmp = int(q['bits']), q['comparison']
            answer = (q['dx9'], q['dx11'])
            if any(q[k] != row[k] for k in ('x', 'y')) or cmp not in ('Less', 'Equal') or any(a not in ('G', 'R') for a in answer):
                raise ValueError('invalid ruler observation')
            query = (bits, cmp)
            if query in cache and cache[query] != answer:
                raise ValueError('ruler repetition changed')
            cache[query] = answer
            if q['fresh'] == '1':
                fresh[query] = fresh.get(query, 0) + 1
                stem = f'{key[0]}_t{key[1]}_p{key[2]}_b{bits}_{cmp.lower()}'
                for side, color in zip(('native', 'candidate'), answer):
                    image = (root / f'{stem}.{side}.bgra').read_bytes()
                    expected = bytes((0, 255, 0, 255)) if color == 'G' else bytes((0, 0, 255, 255))
                    if len(image) != 100 or image[48:52] != expected:
                        raise ValueError('ruler ROI contradicts observation')
            elif q['fresh'] != '0':
                raise ValueError('invalid fresh flag')
        expected_fresh = {}
        for b in {int(row['dx9ThresholdBits']), int(row['dx11ThresholdBits'])}:
            for query in ((b, 'Less'), (b - 1, 'Less'), (b, 'Equal')):
                expected_fresh[query] = expected_fresh.get(query, 0) + 3
        if fresh != expected_fresh:
            raise ValueError('missing fresh edge repetitions')
        for backend, k in enumerate(('dx9ThresholdBits', 'dx11ThresholdBits')):
            b = int(row[k])
            if any(cache.get(q, ('', ''))[backend] != answer for q, answer in
                   [((b, 'Less'), 'R'), ((b - 1, 'Less'), 'G'), ((b, 'Equal'), 'G')]):
                raise ValueError('threshold edge unproven')
            for (bits, cmp), answer in cache.items():
                if cmp == 'Less' and answer[backend] != ('G' if bits < b else 'R'):
                    raise ValueError('nonmonotonic ruler search')
        result.append({**{k: int(row[k]) for k in ('triangle', 'point', 'x', 'y', 'dx9ThresholdBits', 'dx11ThresholdBits')},
                       'variant': key[0], 'dx9Reference': value(int(row['dx9ThresholdBits'])),
                       'dx11Reference': value(int(row['dx11ThresholdBits']))})
    if any((q['variant'], int(q['triangle']), int(q['point'])) not in expected_keys for q in queries):
        raise ValueError('unexpected ruler queries')
    summary = tags((root / 'clip_summary.txt').read_text())
    if int(summary['variants']) != len(variants) or int(summary['measurements']) != len(threshold) or int(summary['queries']) != len(queries) or summary['priorClipExact'] != '1' or summary['rawD24Readback'] != '0':
        raise ValueError('incomplete depth summary')
    return {'variants': len(variants), 'measurements': len(threshold), 'queries': len(queries),
            'thresholds': result, 'clippedThresholdsAgree': all(r['dx9ThresholdBits'] == r['dx11ThresholdBits'] for r in result if r['variant'] not in ('raw', 'raw_shader', 'raw_viewport'))}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('kind', choices=('lines', 'depth'))
    p.add_argument('archive', type=Path)
    p.add_argument('previous', type=Path)
    p.add_argument('evidence', type=Path)
    p.add_argument('--rounding-reference', type=Path)
    p.add_argument('--stage-reference', type=Path)
    args = p.parse_args()
    root = args.evidence
    state = (args.archive / 'history_replay.scene_prefix.draw1.state').read_text().splitlines()
    desc = tags(next(s for s in state if s.startswith('VIEWPORT ')))
    region = [int(desc[k]) for k in ('x', 'y', 'width', 'height')]
    controls = baseline(args.archive, root, 1 if args.kind == 'lines' else 6)
    run = tags((root / 'summary.txt').read_text())
    summary = tags((root / 'clip_summary.txt').read_text())
    if [r['mode'] for r in controls] != ['original', 'repeat1', 'repeat2', 'repeat3'] or run['comparisons'] != '4' or run['baselineNativeExact'] != '1' or run['repeatedBaselineExact'] != '1' or summary['repeats'] != '3' or summary['productionActivation'] != '0' or summary['CPUIntersection'] != 'double':
        raise ValueError('invalid diagnostic completion')
    for side in ('native', 'candidate'):
        original = (root / f'original.{side}.bgra').read_bytes()
        if any((root / f'repeat{n}.{side}.bgra').read_bytes() != original for n in range(1, 4)):
            raise ValueError('original baseline repetition changed')
    if args.rounding_reference and args.stage_reference:
        raise ValueError('choose one diagnostic mode')
    result = (audit_lines if args.kind == 'lines' else audit_depth)(root, args.previous, region, args.rounding_reference, args.stage_reference)
    if args.rounding_reference:
        if summary['intersectionRounding'] != '1':
            raise ValueError('intersection rounding diagnostic is not recorded')
        sources = [clips(root / 'source.clip.bin')] if args.kind == 'lines' else [clips(root / f'source_t{t}.clip.bin') for t in range(2)]
        result.update(audit_rounding(root, sources, region, args.kind))
        result.update(rounding_findings(root, result, args.kind, args.previous))
    if args.stage_reference:
        if summary['centerStages'] != '1':
            raise ValueError('center-stage diagnostic is not recorded')
        result.update(audit_stages(root, region, args.kind, result))
    result.update(kind=args.kind, region=region, nativeApplicationBaselineExact=True, baselineRepeats=3,
                  independentClippingBytesExact=True, edgeRepeats=3, productionActivation=False,
                  imageAcceptance=False, rawD24Readback=False, actualDX9VertexCapture=False)
    result['evidenceHashes'] = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(root.iterdir()) if f.is_file() and f.name != 'analysis.json'}
    (root / 'analysis.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('evidenceHashes', 'thresholds')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
