"""Validate explicit Z shader observations without selecting a policy by residual."""
import argparse
import csv
import json
from pathlib import Path
import struct
from analyze_w_gpu_batch import vertices
from analyze_accessory_isolation import f32, tags, fnv
from generate_sensitive_depth_matrices import multiply, dot


PATHS = ('p2', 'p3', 'p4', 'p5', 'shared3', 'native_dot_z')
RULES = {3: 'fused', 4: 'double', 5: 'sequential'}


def csv_rows(path):
    with path.open(newline='') as file:
        rows = list(csv.DictReader(file))
    if any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ValueError('malformed CSV')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--peer', type=Path, help='compare the same synthetic fixtures from the other architecture')
    args = parser.parse_args()
    if bool(args.fixtures) == bool(args.reference) or bool(args.reference) != bool(args.archive):
        raise ValueError('specify either synthetic fixtures or PMM reference+archive')
    dr = args.directory
    real = bool(args.reference)
    if real:
        trace = (args.reference/'history_replay.dx9').read_text().splitlines()
        region = tags(next(l for l in trace if l.startswith('PORTABLE_REGION ')))
        viewport = [int(region[k]) for k in ('x', 'y', 'width', 'height')]
        if viewport == [565, 25, 1032, 774]:
            points = [(t, x, y, hold) for t in (135, 227) for x, y, hold in ((1220, 505, 0), (1218, 505, 1), (1222, 505, 1))]
        elif viewport == [274, 25, 670, 503]:
            points = [(t, x, y, hold) for t in (197, 231) for x, y, hold in ((427, 338, 0), (425, 338, 1), (429, 338, 1))]
            points += [(t, x, y, hold) for t in (185, 231) for x, y, hold in ((381, 340, 0), (383, 339, 1), (381, 339, 1))]
            points += [(197, x, 234, hold) for x, hold in ((430, 0), (428, 1), (429, 1))]
        else:
            raise ValueError('unexpected captured viewport')
        count = 1
        manifest = None
    else:
        fixture_bytes = args.fixtures.read_bytes()
        manifest = json.loads(args.fixtures.with_suffix('.json').read_text())
        if len(fixture_bytes) != 12+12*112 or fixture_bytes[:12] != b'ZGEOM001'+struct.pack('<I', 12) or len(manifest['cases']) != 12 or manifest['seed'] != 20261005:
            raise ValueError('invalid fixed Z fixture')
        points = [(0, 36, 46, 0), (0, 20, 42, 1), (0, 28, 44, 1)]
        count = 12
    measured = csv_rows(dr/'thresholds.csv')
    indexed = {}
    for row in measured:
        key = int(row['case']), int(row['triangle']), int(row['x']), int(row['y']), row['path']
        if key in indexed or row['repeatExact'] != '1':
            raise ValueError('duplicate or unstable threshold')
        if any(not 0 <= int(row[last])-int(row[first]) < 8 for first, last in (('dx9Bits','dx9EqualLast'),('dx11Bits','dx11EqualLast'))):
            raise ValueError('invalid equality-reference interval')
        indexed[key] = row
    expected = {(n, t, x, y, path) for n in range(count) for t, x, y, hold in points for path in PATHS}
    if indexed.keys() != expected:
        raise ValueError('incomplete fixed measurement matrix')
    verification = csv_rows(dr/'verification.csv')
    if len(verification) != count*3 or {(int(r['case']), int(r['policy'])) for r in verification} != {(n, p) for n in range(count) for p in RULES}:
        raise ValueError('incomplete GPU vertex verification')
    bit_summary = {p: {'vertices': 0, 'cpuExact': 0, 'cpuDifferent': 0, 'heldXYWExact': 0, 'changedZ': 0} for p in RULES}
    for number in range(count):
        matrices_bytes = (dr/f'c{number}.matrices').read_bytes()
        if len(matrices_bytes) != 192:
            raise ValueError('incomplete source matrices')
        values = struct.unpack('<48f', matrices_bytes)
        combined = multiply(multiply(values[:16], values[16:32], 'sequential'), values[32:], 'sequential')
        if (dr/f'c{number}.combined').read_bytes() != struct.pack('<16f', *combined):
            raise ValueError('CPU combined coefficients disagree')
        vb = (dr/f'c{number}.vertices').read_bytes()
        ib = (dr/f'c{number}.indices').read_bytes()
        if not vb or len(vb) % 32:
            raise ValueError('incomplete object vertices')
        objects = [(*struct.unpack_from('<3f', vb, n*32), 1.) for n in range(len(vb)//32)]
        if manifest:
            case = manifest['cases'][number]
            if case['id'] != number or case['split'] != ('calibration' if number < 6 else 'holdout'):
                raise ValueError('preassigned split changed')
            saved_fixture = struct.pack('<28f', *(combined+[v for p in objects for v in p]))
            if saved_fixture != fixture_bytes[12+112*number:12+112*(number+1)] or saved_fixture != struct.pack('<28f', *(case['matrix']+[v for p in case['objects'] for v in p])):
                raise ValueError('measured independent input differs from fixture')
            if any(v == 0 for v in combined[2::4]) or any(any(v == 0 for v in obj) for obj in objects):
                raise ValueError('four nonzero Z terms not exercised')
        else:
            archived = args.archive/'history_replay.reduction.draw2'
            native_draw = tags(next(l for l in trace if l.startswith('DRAW sequence=2 ')))
            if vb != Path(str(archived)+'.vertices').read_bytes() or ib != Path(str(archived)+'.indices').read_bytes() or fnv(vb) != int(native_draw['vbVersion']) or fnv(ib) != int(native_draw['ibVersion']):
                raise ValueError('source geometry differs from archive/application capture')
            offset = 0
            for name, transform in (('WORLD', 256), ('VIEW', 2), ('PROJECTION', 3)):
                fields = tags(next(l for l in trace if l.startswith(f'MATRIX sequence=2 transform={transform} ')))
                if matrices_bytes[offset:offset+64] != b''.join(f32(fields[f'm{k}']) for k in range(16)):
                    raise ValueError('original native matrices changed')
                offset += 64
        base = vertices(dr/f'c{number}_p2.raw')
        if len(base) != len(objects):
            raise ValueError('incomplete clip capture')
        if manifest and any(v[3] != 6 for v in base):
            raise ValueError('constant W control changed')
        if real and (args.reference/'accessory-w-gpu-2/draw2.candidate_raw.clip').read_bytes() != (dr/f'c{number}_p2.raw').read_bytes():
            raise ValueError('original policy 2 clip changed')
        for policy, rule in RULES.items():
            capture = vertices(dr/f'c{number}_p{policy}.raw')
            if len(capture) != len(objects):
                raise ValueError('incomplete explicit Z capture')
            exact = changed = 0
            for n, obj in enumerate(objects):
                expected_z = dot(obj, combined[2::4], rule)
                exact += f32(capture[n][2]) == f32(expected_z)
                changed += f32(capture[n][2]) != f32(base[n][2])
                if any(f32(capture[n][k]) != f32(base[n][k]) for k in (0, 1, 3)):
                    raise ValueError('Z policy changed XY/W')
                if manifest and f32(expected_z) != f32(manifest['cases'][number]['cpuZ'][rule][n]):
                    raise ValueError('generator CPU candidate differs')
            row = next(r for r in verification if int(r['case']) == number and int(r['policy']) == policy)
            if [int(row[k]) for k in ('vertices', 'zCpuExact', 'zCpuDifferent', 'heldXYWExact', 'zChanged')] != [len(objects), exact, len(objects)-exact, len(objects), changed]:
                raise ValueError('reported GPU Z-bit counts differ')
            summary = bit_summary[policy]
            for k, value in zip(summary, (len(objects), exact, len(objects)-exact, len(objects), changed)):
                summary[k] += value
    summaries = {}
    for path in PATHS:
        data = [r for r in measured if r['path'] == path]
        summary = {'total': len(data), 'backendMatches': sum(r['dx9Bits'] == r['dx11Bits'] and r['dx9EqualLast'] == r['dx11EqualLast'] for r in data)}
        if path.startswith('p'):
            for split, case_range in (('calibration', range(min(6, count))), ('holdout', range(6, count))) if not real else (('primary', (0,)), ('additional', (1,))):
                selected = [r for r in data if int(r['holdout'] if real else r['case']) in case_range]
                summary[split] = {'total': len(selected), 'nativeMatches': sum(r['dx9Bits'] == r['dx11Bits'] and r['dx9EqualLast'] == r['dx11EqualLast'] for r in selected)}
        if path == 'native_dot_z':
            summary['matchesOriginalNative'] = sum(all(r[field] == indexed[int(r['case']), int(r['triangle']), int(r['x']), int(r['y']), 'p2'][field] for field in ('dx9Bits','dx9EqualLast')) for r in data)
        if path == 'shared3':
            summary['matchesActualGpuFusedZ'] = sum(all(r[field] == indexed[int(r['case']), int(r['triangle']), int(r['x']), int(r['y']), 'p3'][field] for field in ('dx11Bits','dx11EqualLast')) for r in data)
        summaries[path] = summary
    for n in range(count):
        for t, x, y, holdout in points:
            original_native = indexed[n, t, x, y, 'p2']['dx9Bits']
            for path in ('p3', 'p4', 'p5'):
                row = indexed[n, t, x, y, path]
                if row['dx9Bits'] != original_native or int(row['holdout']) != holdout:
                    raise ValueError('native reference or coordinates changed')
    result = {'realPMM': real, 'thresholdPairs': len(measured), 'gpuBits': bit_summary, 'thresholds': summaries,
        'multipleFloatReferencesEqual': sum(r['dx9EqualLast'] != r['dx9Bits'] or r['dx11EqualLast'] != r['dx11Bits'] for r in measured),
        'nativeInputsUnchanged': True, 'repeatExact': True, 'nativeClipCapture': False, 'rawD24Readback': False,
        'fullSceneAcceptance': False,
        'limit': 'Fixed arithmetic policies on measured driver. Reference bits are float32 ruler inputs, not raw D24. CPU bit mismatch is retained rather than relabeled as a matching candidate.'}
    if args.peer:
        if real:
            raise ValueError('different real viewports cannot isolate architecture')
        peer_rows = csv_rows(args.peer/'thresholds.csv')
        peer = {(int(r['case']), int(r['triangle']), int(r['x']), int(r['y']), r['path']): r for r in peer_rows}
        if len(peer_rows) != len(peer) or peer.keys() != indexed.keys():
            raise ValueError('architecture measurement sets differ')
        fields = ('dx9Bits', 'dx11Bits', 'dx9EqualLast', 'dx11EqualLast')
        differences = sum(indexed[key][field] != peer[key][field] for key in indexed for field in fields)
        clip_differences = sum((dr/f'c{n}_p{p}.{kind}').read_bytes() != (args.peer/f'c{n}_p{p}.{kind}').read_bytes() for n in range(count) for p in range(2,6) for kind in ('raw','final'))
        result['architectureComparison'] = {'thresholdValueDifferences': differences, 'thresholdValues': len(indexed)*4,
            'clipBufferDifferences': clip_differences, 'clipBuffers': count*4*2}
        print('architectureComparison', result['architectureComparison'])
    (dr/'analysis.json').write_text(json.dumps(result, indent=2)+'\n')
    print('gpuBits', bit_summary)
    for path, summary in summaries.items():
        print(path, summary)
    if real:
        for n, t, x, y, path in indexed:
            if path == 'p3' and indexed[n, t, x, y, path]['holdout'] == '0':
                print(f'primary triangle={t} pixel={x},{y} '+str({p:(indexed[n,t,x,y,p]['dx9Bits'], indexed[n,t,x,y,p]['dx11Bits']) for p in PATHS}))


if __name__ == '__main__':
    main()
