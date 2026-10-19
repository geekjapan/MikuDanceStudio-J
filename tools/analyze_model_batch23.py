"""Verify owned draw-23 reduction and the measured final multiply/add rounding."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import struct


def require(value, reason):
    if not value:
        raise ValueError(reason)


def tags(line):
    return dict(token.split('=', 1) for token in line.split() if '=' in token)


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'isolation', 'stages'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--compare-isolation', type=Path)
    parser.add_argument('--compare-stages', type=Path)
    args = parser.parse_args()
    source, isolation, stages = args.archive, args.isolation, args.stages
    state = source/'history_replay.scene_prefix.draw23.state'
    lines = state.read_text().splitlines()
    draw, viewport = tags(lines[0]), tags(lines[1])
    require((int(draw['sequence']), int(draw['start']), int(draw['count']), int(draw['stride'])) == (23, 7275, 7667, 32), 'wrong native batch')
    require('status=READY nativeExact=1' in (source/'history_replay.scene_prefix.manifest').read_text().splitlines()[0], 'unverified native archive')
    w, h = int(viewport['width']), int(viewport['height'])
    x, y = int(viewport['x']), int(viewport['y'])
    focus = (486-y)*w + 867-x
    require(0 <= focus < w*h, 'focus outside known region')
    with (isolation/'controls.csv').open(newline='') as file:
        controls = list(csv.DictReader(file))
    modes = {r['mode']: r for r in controls}
    require(len(modes) == len(controls), 'duplicate controls')
    metrics = {}
    for row in controls:
        name = row['mode']
        a = (isolation/(name+'.native.bgra')).read_bytes()
        b = (isolation/(name+'.candidate.bgra')).read_bytes()
        require(len(a) == len(b) == w*h*4, 'wrong image size: '+name)
        count = sum(a[n:n+4] != b[n:n+4] for n in range(0, len(a), 4))
        maximum = max(abs(left-right) for left, right in zip(a, b))
        differs = a[focus*4:focus*4+4] != b[focus*4:focus*4+4]
        require((count, maximum, int(differs)) == tuple(int(row[k]) for k in ('differentPixels', 'maxDelta', 'focusDifferent')), 'image metrics: '+name)
        metrics[name] = dict(differentPixels=count, maxDelta=maximum, focusDifferent=differs)
    require(metrics['history23']['differentPixels'] == metrics['original']['differentPixels'] == 1, 'original failure not reproduced')
    require((isolation/'history23.native.bgra').read_bytes() == (source/'history_replay.scene_prefix.draw24.before.bgra').read_bytes(), 'native replay differs from application')
    for prefix in ('history_', ''):
        baseline = 'history23' if prefix else 'original'
        for n in range(1, 4):
            name = prefix+'repeat'+str(n)
            for suffix in ('.native.bgra', '.candidate.bgra'):
                require((isolation/(baseline+suffix)).read_bytes() == (isolation/(name+suffix)).read_bytes(), 'repeat drift: '+name)
    with (isolation/'triangles.csv').open(newline='') as file:
        triangles = list(csv.DictReader(file))
    require(triangles == [dict(triangle='1383', index0='8065', index1='8067', index2='7923')], 'unexpected leaf geometry')
    vertices = (source/'history_replay.scene_prefix.draw23.vertices').read_bytes()
    compact = b''.join(vertices[n*32:(n+1)*32] for n in (8065, 8067, 7923))
    require((isolation/'compact_1383.vertices').read_bytes() == compact, 'vertex compaction changes bytes')
    for suffix in ('.native.bgra', '.candidate.bgra'):
        require((isolation/('compact_1383'+suffix)).read_bytes() == (isolation/('leaf_1383'+suffix)).read_bytes(), 'compaction changes image')
    with (stages/'stages.csv').open(newline='') as file:
        rows = list(csv.DictReader(file))
    stage_names = ['diffuse', 'specular', 'coordinate0', 'coordinate1', 'sample0', 'sample1', 'pre_specular', 'final', 'final_fused']
    require([(r['mode'], int(r['repeat'])) for r in rows] == [('fixed_function_float', 0)]+[(name, n) for name in stage_names for n in range(3)], 'incomplete stage observations')
    observations = {}
    for name in stage_names:
        group = [r for r in rows if r['mode'] == name]
        a = [float(group[0]['native'+k]) for k in 'RGBA']
        b = [float(group[0]['candidate'+k]) for k in 'RGBA']
        require(all([float(r['native'+k]) for k in 'RGBA'] == a and [float(r['candidate'+k]) for k in 'RGBA'] == b for r in group), 'float repeat drift: '+name)
        observations[name] = dict(native=a, candidate=b)
    for name in ('diffuse', 'specular', 'sample0', 'sample1', 'pre_specular'):
        require(observations[name]['native'] == observations[name]['candidate'], 'earlier stage differs: '+name)
    a, b, c = (observations[name]['native'][1] for name in ('diffuse', 'sample1', 'specular'))
    # Products of two float32 operands and this addition fit exactly in binary64.
    # Thus one final float32 cast tests single rounding without an epsilon fit.
    fused, separate = f32(a*b+c), f32(f32(a*b)+c)
    require(fused == observations['final']['native'][1] and separate == observations['final']['candidate'][1] and fused != separate, 'rounding hypotheses do not predict native and candidate')
    fixed = rows[0]
    require([float(fixed['native'+k]) for k in 'RGBA'] == observations['final']['native'], 'native PS observation changes fixed-function output at focus')
    require(observations['final_fused']['native'] == observations['final_fused']['candidate'], 'explicit fused diagnostic differs')
    gate = tags((stages/'byte_gate.txt').read_text())
    require(gate['nativeExplicitPsExact'] == gate['candidateExplicitPsExact'] == '1', 'explicit PS changes byte baseline')
    native = (stages/'native.bgra').read_bytes()
    baseline = (stages/'baseline.candidate.bgra').read_bytes()
    require(native == (stages/'fused.candidate.bgra').read_bytes(), 'fused diagnostic byte images differ')
    require(native[focus*4:focus*4+4] == bytes((150, 95, 17, 255)) and baseline[focus*4:focus*4+4] == bytes((150, 96, 17, 255)), 'byte failure drift')
    cross = {}
    for name, left, right in [('isolation', isolation, args.compare_isolation), ('stages', stages, args.compare_stages)]:
        artifacts = lambda root: {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file() and p.suffix != '.json'}
        if right:
            require(artifacts(left) == artifacts(right), 'architecture changes '+name+' inputs/results')
            cross[name] = len(artifacts(left))
    result = dict(draw=23, triangle=1383, sourceIndices=[8065,8067,7923], pixel=[867,486], controls=len(controls),
                  stageObservations=len(rows)-1, controlMetrics=metrics, observations=observations,
                  greenRounding=dict(singleRound=fused, multiplyThenAdd=separate), fusedWholeTriangleByteExact=True,
                  crossArchitectureArtifacts=cross, productionActivation=False, imageAcceptance=False,
                  sourceSha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob('history_replay.scene_prefix.draw23.*')})
    (stages/'analysis.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('controlMetrics','observations','sourceSha256')}))


if __name__ == '__main__':
    main()
