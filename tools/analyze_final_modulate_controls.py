"""Validate independent native FF versus measured cascade controls."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def require(value, reason):
    if not value:
        raise ValueError(reason)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controls', required=True, type=Path)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    expected = {
        (stages, pattern, material, highlight, repeat)
        for stages in range(4) for pattern in range(3)
        for material in range(4) for highlight in range(4) for repeat in range(3)
        if not (stages == 0 and pattern)
        and not (stages == 1 and pattern == 2)
        and not (highlight >= 2 and material)
    }
    with (args.controls/'controls.csv').open(newline='') as file:
        rows = list(csv.DictReader(file))
    keys = [tuple(int(row[name]) for name in ('stages', 'pattern', 'material', 'highlight', 'repeat')) for row in rows]
    require(len(keys) == len(set(keys)) and set(keys) == expected, 'missing or duplicate control/repeat')
    for key, row in zip(keys, rows):
        require(int(row['byteDifferent']) == int(row['floatDifferent']) == 0, f'nonzero whole-image difference: {key}')
        require(float(row['nativeG']) == float(row['candidateG']), f'focus differs: {key}')
    summary = dict(token.split('=', 1) for token in (args.controls/'summary.txt').read_text().split())
    require(summary['complete'] == '1' and int(summary['comparisons']) == len(expected), 'incomplete run')
    require(summary['byteDifferences'] == summary['floatDifferences'] == '0', 'aggregate mismatch')
    baseline = sum(int(row['genericByteDifferent']) for row in rows if row['repeat'] == '0')
    require(baseline == int(summary['genericByteDifferences']) and baseline > 0, 'generic negative control did not discriminate')
    for key in {key[:4] for key in keys}:
        repeats = [row for entry, row in zip(keys, rows) if entry[:4] == key]
        require(len({tuple(row[name] for name in ('nativeG', 'candidateG', 'genericByteDifferent')) for row in repeats}) == 1, f'repeat drift: {key}')
    result = dict(status='PASS', controls=len(expected)//3, comparisons=len(expected),
                  byteDifferences=0, floatDifferences=0, genericByteDifferences=baseline,
                  evidenceSha256=hashlib.sha256((args.controls/'controls.csv').read_bytes()).hexdigest())
    if args.compare:
        for name in ('controls.csv', 'summary.txt'):
            require((args.controls/name).read_bytes() == (args.compare/name).read_bytes(), 'cross-architecture evidence differs: '+name)
        result['crossArchitectureExact'] = True
    (args.controls/'analysis.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
