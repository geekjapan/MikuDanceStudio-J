"""Summarize accepted CPU ground/projected-shadow history runs without rerunning GPUs."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = []
    required = {'ground_lines', 'ground_plane', 'projected_model_shadow'}
    for directory in args.runs:
        report = json.loads((directory / 'run.json').read_text(encoding='utf-8'))
        assert report['status'] == 'PASS', str(directory)
        assert report['cpuPrefixFamilies'] == 'ground-shadow'
        assert report['projectedShadowsTemporaryFixture'] and report['groundTemporaryFixture']
        assert report['cpuPrefixExact'] and report['sceneHistoryExact']
        assert report['previewExact'] and report['lifecycleExact']
        assert report['materialOrderExact'] and report['prefixOrderExact']
        assert report['playbackSamples'] > 0 and report['previewCoveredPixels'] > 0
        assert report['applicationBackend'] == 'dx9' and not report['productionActivation']
        assert report['inputMode'] in ('audit', 'direct')
        if report['inputMode'] == 'audit':
            assert report['inputsExact']
        counts = Counter()
        for filename in directory.glob('cpu_prefix.*.csv'):
            with filename.open(encoding='utf-8', newline='') as stream:
                rows = list(csv.DictReader(stream))
            boundaries = [int(row['boundary']) for row in rows]
            assert boundaries == sorted(set(boundaries)), str(filename)
            for row in rows:
                assert row['status'] == 'PASS' and row['reason'] == 'exact_fields_and_bytes'
                assert row['geometrySource'] == row['stateSource'] == 'cpu'
                counts[row['family']] += 1
            shadows = [int(row['material']) for row in rows if row['family'] == 'projected_model_shadow']
            if shadows:
                assert shadows == list(range(17)), str(filename)
        assert set(counts) == required and sum(counts.values()) == report['cpuPrefixChecks']
        assert counts['ground_lines'] == counts['ground_plane'] == 2
        assert counts['projected_model_shadow'] == 17
        results.append(dict(directory=str(directory), inputMode=report['inputMode'],
                            translucent=report['translucent'], switchToon=report['switchToon'],
                            applicationSha256=report['applicationSha256'],
                            cpuDrawChecks=report['cpuPrefixChecks'],
                            historyChecks=report['sceneHistoryChecks'],
                            lifecycleChecks=report['lifecycleChecks'],
                            nonemptyPreviewChecks=report['previewSamples']-report['previewEmptySamples'],
                            families=dict(counts)))
    summary = dict(status='PASS', runs=results,
                   cpuDrawChecks=sum(r['cpuDrawChecks'] for r in results),
                   historyChecks=sum(r['historyChecks'] for r in results),
                   lifecycleChecks=sum(r['lifecycleChecks'] for r in results),
                   nonemptyPreviewChecks=sum(r['nonemptyPreviewChecks'] for r in results))
    args.output.write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k != 'runs'}))


if __name__ == '__main__':
    main()
