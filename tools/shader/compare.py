#!/usr/bin/env python3
"""Validate or compare v1 per-entry shader contracts without aggregate thresholds."""
import csv
import json
import sys
from pathlib import Path
from urllib.parse import unquote

COLUMNS = 'file profile entry args source_hash spirv wgsl msl hlsl scan reflection coverage probe reparse reflection_origin error'.split()
IDENTITY = COLUMNS[:5]
CONTRACTS = COLUMNS[5:-2]


def read(path):
    with Path(path).open(encoding='utf-8', newline='') as stream:
        if stream.readline().rstrip('\r\n') != 'mds-shader-contracts-v1':
            raise ValueError(f'{path}: unsupported manifest schema')
        compiler = stream.readline().rstrip('\r\n').split('\t')
        if len(compiler) != 2 or compiler[0] != 'compiler' or not compiler[1]:
            raise ValueError(f'{path}: missing compiler provenance')
        reader = csv.DictReader(stream, delimiter='\t', quoting=csv.QUOTE_NONE)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f'{path}: invalid columns')
        rows = {}
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f'{path}: malformed row')
            row = {key: unquote(value) for key, value in row.items()}
            key = tuple(row[name] for name in IDENTITY)
            if not all(row[name] for name in ('file', 'profile', 'entry', 'source_hash')):
                raise ValueError(f'{path}: incomplete identity')
            if key in rows:
                raise ValueError(f'{path}: duplicate identity {key}')
            for name in CONTRACTS:
                if not (row[name].startswith(('OK ', 'ERR ')) or row[name] == 'UNAVAILABLE'):
                    raise ValueError(f'{path}: invalid {name} result')
            if row['spirv'] != 'OK ' and not row['error']:
                raise ValueError(f'{path}: rejected entry lacks an error')
            rows[key] = row
        if not rows:
            raise ValueError(f'{path}: empty capture')
        return rows


def compare(baseline, candidate):
    failures = []
    for key, before in baseline.items():
        after = candidate.get(key)
        if after is None:
            failures.append({'identity': key, 'contract': 'missing entry or changed source'})
            continue
        for name in CONTRACTS:
            changed = after[name] != before[name]
            improved = before[name].startswith('ERR ') and after[name].startswith('OK ')
            if changed and before[name] != 'UNAVAILABLE' and not improved:
                failures.append({'identity': key, 'contract': name,
                                 'expected': before[name], 'actual': after[name]})
        error_cleared = bool(before['error']) and not after['error'] and all(
            after[name] == 'OK ' for name in ('spirv', 'wgsl', 'msl', 'hlsl'))
        backend_errors_match = all(
            row['spirv'] == 'OK ' and
            all(row[name].startswith(('OK ', 'ERR ')) for name in ('wgsl', 'msl', 'hlsl')) and
            row['error'] == next((row[name][4:] for name in ('wgsl', 'msl', 'hlsl')
                                  if row[name].startswith('ERR ')), '')
            for row in (before, after))
        if before['error'] != after['error'] and not (error_cleared or backend_errors_match):
            failures.append({'identity': key, 'contract': 'error',
                             'expected': before['error'], 'actual': after['error']})
    return failures


def summary(rows):
    return {
        'entries': len(rows),
        'rejected': [key for key, row in rows.items()
                     if any(row[name] != 'OK ' for name in ('spirv', 'wgsl', 'msl', 'hlsl'))],
        'reflection_gaps': [{'identity': key, 'reflection': row['reflection'],
                             'coverage': row['coverage'], 'origin': row['reflection_origin']}
                            for key, row in rows.items()
                            if row['spirv'] == 'OK ' and
                            (not row['reflection'].startswith('OK ') or row['coverage'] != 'OK ')],
    }


def main(args):
    if len(args) == 2 and args[0] == '--validate':
        print(json.dumps(summary(read(args[1])), indent=2))
        return 0
    if len(args) != 2:
        raise ValueError('usage: compare.py --validate <manifest> | <baseline> <candidate>')
    baseline, candidate = map(read, args)
    failures = compare(baseline, candidate)
    print(json.dumps({'baseline': summary(baseline), 'candidate': summary(candidate),
                      'regressions': failures}, indent=2))
    return int(bool(failures))


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (ValueError, OSError) as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(2)
