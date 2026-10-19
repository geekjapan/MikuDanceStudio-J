"""Qualify generated specular inputs independently of full-scene image acceptance."""
import argparse
import csv
import hashlib
import itertools
import json
import math
from collections import defaultdict
from pathlib import Path


def read(root, name):
    with (root / name).open(newline='') as stream:
        return list(csv.DictReader(stream))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--compare', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert args.input.resolve() != args.compare.resolve(), 'comparison needs an independent evidence directory'
    scope = read(args.input, 'scope.csv')
    vertices = read(args.input, 'vertices.csv')
    inputs = read(args.input, 'inputs.csv')
    assert len(scope) == 480 and len(vertices) == 4320 and len(inputs) == 400
    keys = ('transform', 'normalSet', 'normalize', 'localViewer', 'powerIndex')
    expected = set(itertools.product(range(5), range(2), range(2), range(2), range(4)))
    observed = defaultdict(dict)
    for row in scope:
        key = tuple(int(row[k]) for k in keys)
        repeat = int(row['repeat'])
        assert repeat not in observed[key], 'duplicate observation'
        assert int(row['coveredPixels']) > 128 and int(row['activeVertexChannels']) > 0
        assert int(row['holdout']) == int(key[0] >= 3 or key[1] == 1)
        observed[key][repeat] = {k: v for k, v in row.items() if k != 'repeat'}
    assert set(observed) == expected
    assert all(set(r) == {0, 1, 2} and r[0] == r[1] == r[2] for r in observed.values()), 'repeat differs'
    value_lookup = {}
    for row in vertices:
        key = tuple(int(row[k]) for k in keys) + (int(row['repeat']), int(row['vertex']), int(row['channel']))
        assert key not in value_lookup
        assert float(row['power']) == (0.5, 1.7000000476837158, 5.0, 7.300000190734863)[key[4]]
        assert all(math.isfinite(float(row[k])) for k in ('native', 'baseline', 'candidate'))
        value_lookup[key] = row
    assert set(value_lookup) == {k + (r, v, c) for k in expected for r in range(3) for v in range(3) for c in range(3)}
    for key in expected:
        for vertex in range(3):
            for channel in range(3):
                values = [value_lookup[key + (r, vertex, channel)] for r in range(3)]
                assert all({k: v for k, v in row.items() if k != 'repeat'} ==
                           {k: v for k, v in values[0].items() if k != 'repeat'} for row in values)
        for repeat in range(3):
            channels = [value_lookup[key + (repeat, vertex, channel)] for vertex in range(3) for channel in range(3)]
            summary = observed[key][repeat]
            assert int(summary['baselineChannels']) == sum(r['nativeBits'] != r['baselineBits'] for r in channels)
            assert int(summary['candidateChannels']) == sum(r['nativeBits'] != r['candidateBits'] for r in channels)
            assert int(summary['regressedChannels']) == sum(r['nativeBits'] == r['baselineBits'] and r['nativeBits'] != r['candidateBits'] for r in channels)
            assert int(summary['activeVertexChannels']) == sum(0 < float(r['native']) < 1 for r in channels)
    files = {p.name: p for p in args.input.iterdir() if p.suffix in ('.csv', '.hlsl', '.asm')}
    other = {p.name: p for p in args.compare.iterdir() if p.suffix in ('.csv', '.hlsl', '.asm')}
    cross = files.keys() == other.keys() and all(digest(p) == digest(other[n]) for n, p in files.items())
    first = [rows[0] for rows in observed.values()]
    failures = lambda field: sum(int(r[field]) > 0 for r in first)
    gates = failures('nativeReproductionPixels') + failures('candidateReproductionPixels')
    regressions = failures('regressedChannels') + failures('regressedPixels')
    candidate_exact = not failures('candidateChannels') and not failures('candidatePixels')
    unchanged = all(r['baselineHash'] == r['candidateHash'] for r in first if r['localViewer'] == '0') and all(
        r['baselineBits'] == r['candidateBits'] for r in vertices if r['localViewer'] == '0')
    groups = []
    for transform in range(5):
        for viewer in range(2):
            rows = [r for r in first if int(r['transform']) == transform and int(r['localViewer']) == viewer]
            groups.append(dict(transform=transform, localViewer=viewer, controls=len(rows),
                               baselineVertexFailures=sum(int(r['baselineChannels']) > 0 for r in rows),
                               candidateVertexFailures=sum(int(r['candidateChannels']) > 0 for r in rows),
                               candidateImageFailures=sum(int(r['candidatePixels']) > 0 for r in rows),
                               gateFailures=sum(int(r['nativeReproductionPixels']) > 0 or int(r['candidateReproductionPixels']) > 0 for r in rows)))
    mismatches = [{**row, 'signedUlps': int(row['candidateBits']) - int(row['nativeBits'])}
                  for row in vertices if row['repeat'] == '0' and row['candidateBits'] != row['nativeBits']]
    result = dict(evidenceComplete=True, candidateQualified=cross and candidate_exact and not gates and not regressions and unchanged,
                  imageAcceptance=False, productionActivation=False, archiveRequired=False,
                  controls=160, observations=len(scope), repeats=3, crossArchitectureExact=cross, comparedArtifacts=len(files),
                  baselineVertexFailures=failures('baselineChannels'), baselineImageFailures=failures('baselinePixels'),
                  candidateVertexFailures=failures('candidateChannels'), candidateImageFailures=failures('candidatePixels'),
                  nativeReproductionFailures=failures('nativeReproductionPixels'), candidateReproductionFailures=failures('candidateReproductionPixels'),
                  regressedVertexControls=failures('regressedChannels'), regressedImageControls=failures('regressedPixels'),
                  localViewerOffUnchanged=unchanged, groups=groups, vertexMismatches=mismatches,
                  limitations=['Native flat observations require the original Gouraud image reproduction gate.',
                               'These synthetic controls qualify only the tested adapter, inputs and arithmetic.',
                               'Independent material colors and the saved full scene remain separate acceptance gates.'])
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'vertexMismatches'}, indent=2))
    if not result['candidateQualified']:
        raise SystemExit(33)


if __name__ == '__main__':
    main()
