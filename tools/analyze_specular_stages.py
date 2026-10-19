"""Verify specular stage evidence and report causal limits without image acceptance."""
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def read(root, name):
    with (root / name).open(newline='') as stream:
        return list(csv.DictReader(stream))


def repeated(rows):
    groups = defaultdict(set)
    for row in rows:
        key = tuple((k, v) for k, v in row.items() if k != 'repeat')
        assert row['repeat'] not in groups[key], 'duplicate observation'
        groups[key].add(row['repeat'])
    return bool(groups) and all(values == {'0', '1', '2'} for values in groups.values())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--compare', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    expected = {'inputs.csv': 648, 'arithmetic.csv': 2916, 'fixed.csv': 243, 'pow_scan.csv': 729,
                'references.csv': 81, 'rebased.csv': 81, 'half_axes.csv': 243,
                'half_scan.csv': 2187, 'half_causal.csv': 27, 'candidates.csv': 243}
    tables = {name: read(args.input, name) for name in expected}
    for name, rows in tables.items():
        assert len(rows) == expected[name], (name, len(rows), expected[name])
        assert repeated(rows), (name, 'non-repeatable or incomplete')
        assert {r['geometry'] for r in rows} == {'saved', 'independent', 'holdout'}
        assert {r['vertex'] for r in rows} == {'0', '1', '2'}
    files = {p.name: p for p in args.input.iterdir() if p.suffix in ('.csv', '.hlsl', '.asm')}
    other = {p.name: p for p in args.compare.iterdir() if p.suffix in ('.csv', '.hlsl', '.asm')}
    cross_exact = files.keys() == other.keys() and all(sha(p) == sha(other[n]) for n, p in files.items())
    assert cross_exact, 'architecture evidence differs'
    arithmetic = [r for r in tables['arithmetic.csv'] if r['repeat'] == '0']
    stage_differences = Counter((r['geometry'], r['cut'], r['stage']) for r in arithmetic if r['dx9Bits'] != r['dx11Bits'])
    fixed = [r for r in tables['fixed.csv'] if r['repeat'] == '0']
    normal_differences = [r for r in fixed if r['stage'].startswith('normalizer_') and r['nativeBits'] != r['explicitBits']]
    light_differences = [r for r in fixed if r['stage'] == 'light_direction' and r['nativeBits'] != r['explicitBits']]
    scans = [r for r in tables['pow_scan.csv'] if r['repeat'] == '0']
    references = {(r['geometry'], r['vertex'], r['power']): r for r in tables['references.csv'] if r['repeat'] == '0'}
    scan_lookup = {(r['geometry'], r['vertex'], r['offset'], r['power']): r for r in scans}
    original_offsets = []
    for geometry in ('saved', 'independent', 'holdout'):
        for vertex in ('0', '1', '2'):
            matches = [offset for offset in range(-4, 5) if all(
                scan_lookup[(geometry, vertex, str(offset), power)]['nativeBits'] == references[(geometry, vertex, power)]['nativeBits']
                for power in ('1', '2', '5'))]
            original_offsets.append(dict(geometry=geometry, vertex=int(vertex), offsets=matches))
    rebased = []
    explicit_reconstruction = True
    for r in tables['rebased.csv']:
        if r['repeat'] != '0':
            continue
        original = references[(r['geometry'], r['vertex'], r['power'])]
        explicit_reconstruction &= r['dx11Bits'] == original['dx11Bits']
        rebased.append(dict(geometry=r['geometry'], vertex=int(r['vertex']), power=float(r['power']),
                            nativeVsOriginalUlps=int(r['nativeBits'])-int(original['nativeBits']),
                            nativeVsExplicitUlps=int(r['nativeBits'])-int(r['dx11Bits'])))
    inputs = {(r['geometry'], r['vertex'], r['slot'], r['channel']): r for r in tables['inputs.csv'] if r['repeat'] == '0'}
    passthrough = [r for r in arithmetic if r['stage'] == 'shared_value']
    shared_gate = len(passthrough) == 36 and all(
        r['dx9Bits'] == r['dx11Bits'] == inputs[(r['geometry'], r['vertex'], '3', r['channel'])]['bits'] for r in passthrough)
    axes = [r for r in tables['half_scan.csv'] if r['repeat'] == '0']
    half_offsets = []
    for geometry in ('saved', 'independent', 'holdout'):
        for vertex in ('0', '1', '2'):
            for channel in ('0', '1', '2'):
                matches = [offset for offset in range(-4, 5) if all(
                    r['matchesAxis'] == '1' for r in axes if r['geometry'] == geometry and r['vertex'] == vertex
                    and r['channel'] == channel and r['offset'] == str(offset))]
                half_offsets.append(dict(geometry=geometry, vertex=int(vertex), channel=int(channel), magnitudeOffsets=matches))
    causal = [r for r in tables['half_causal.csv'] if r['repeat'] == '0']
    arithmetic_lookup = {(r['geometry'], r['vertex'], r['stage'], r['channel']): r
                         for r in arithmetic if r['cut'] == 'baseline'}
    inferred_components = []
    for half in half_offsets:
        if len(half['magnitudeOffsets']) != 1:
            continue
        key = half['geometry'], str(half['vertex']), '4', str(half['channel'])
        original_bits = int(inputs[key]['bits'])
        expected_bits = ((original_bits & 0x7fffffff) + half['magnitudeOffsets'][0]) | (original_bits & 0x80000000)
        actual = arithmetic_lookup[(half['geometry'], str(half['vertex']), 'fused_halfway', str(half['channel']))]
        inferred_components.append(expected_bits == int(actual['dx11Bits']))
    causal_dot = []
    for row in causal:
        if row['uniqueComponents'] == '3':
            dot = arithmetic_lookup[(row['geometry'], row['vertex'], 'fused_dot', '0')]
            causal_dot.append(row['dotBits'] == dot['dx11Bits'] and row['strengthBits'] == row['rebasedBits'] == row['nativePowBits'])
    candidate_differences = Counter((r['geometry'], r['cameraPolicy']) for r in tables['candidates.csv']
                                    if r['repeat'] == '0' and r['nativeBits'] != r['candidateBits'])
    result = dict(evidenceComplete=True, productionActivation=False, imageAcceptance=False, repeats=3,
                  crossArchitectureExact=cross_exact, comparedArtifacts=len(files),
                  explicitSharedValueExact=shared_gate, explicitOriginalStrengthReproduced=explicit_reconstruction,
                  arithmeticDifferences=[dict(geometry=k[0], cut=k[1], stage=k[2], channels=v) for k, v in sorted(stage_differences.items())],
                  fixedNormalNormalizationDifferences=normal_differences, fixedLightDirectionDifferences=light_differences,
                  sameInputPowComparisons=len(scans), sameInputPowExact=all(r['nativeBits'] == r['dx9Bits'] == r['dx11Bits'] for r in scans),
                  originalEffectiveDotOffsets=original_offsets, rebased=rebased, effectiveHalfOffsets=half_offsets,
                  inferredHalfCausal=causal,
                  candidateDifferences=[dict(geometry=g, cameraPolicy=int(p), mismatches=candidate_differences[(g, p)])
                                        for g in ('saved', 'independent', 'holdout') for p in ('0', '1', '2')],
                  fusedHalfInferredComponentChecks=len(inferred_components), fusedHalfMatchesInferred=all(inferred_components),
                  inferredHalfCausalChecks=len(causal_dot), inferredHalfDotAndPowerReproduced=all(causal_dot),
                  fusedCombinedCameraCandidateExact=all(r['nativeBits'] == r['candidateBits'] for r in tables['candidates.csv'] if r['cameraPolicy'] == '2'),
                  limitations=['FF normal-axis responses test the normalizer, not hidden local-viewer registers.',
                               'Effective dot/half values are inferred from a finite scan and three powers, not direct register captures.',
                               'Identity rebasing is equivalent to the original batch only when its native output reproduction gate passes.',
                               'A rule must explain independent inputs before any backend compatibility change.'])
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('rebased', 'effectiveHalfOffsets', 'inferredHalfCausal',
          'originalEffectiveDotOffsets', 'fixedNormalNormalizationDifferences', 'fixedLightDirectionDifferences')}, indent=2))
    assert shared_gate and explicit_reconstruction, 'measurement route does not reproduce its reference'


if __name__ == '__main__':
    main()
