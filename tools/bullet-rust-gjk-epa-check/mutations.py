#!/usr/bin/env python3
"""Every mutation must compile and fail the frozen complete-scenario prefix."""
import argparse
import json
import os
import re
import sys
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/bullet-rust-support-check'))
from host_profiles import fields

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--crt-rlib',type=Path,required=True)
    args=parser.parse_args()
    output=args.out_dir.resolve();output.mkdir(parents=True,exist_ok=True)
    source=(ROOT/'rust/crates/mds-bullet/src/core/gjk_epa.rs').read_text()
    adapter=source.index('pub fn calc_pen_depth(')
    mutations={
        'delete-penetration': source[:adapter]+source[adapter:].replace('if let QueryResult::Success(solution) = penetration(shapes, transforms, guess, true)', 'if let QueryResult::Success(solution) = QueryResult::Failure(Status::Separated)'),
        'delete-distance-fallback': source[:adapter]+source[adapter:].replace('distance(shapes, transforms, guess)', 'QueryResult::Failure(Status::GjkFailed)'),
        'nonvalid-is-failure':source.replace('== EpaStatus::Failed {','!= EpaStatus::Valid {'),
        'face-tie-selection':source.replace('sqd < mind','sqd <= mind'),
        'margin-removal':source.replace('Minkowski::new(shapes, transforms, use_margins)', 'Minkowski::new(shapes, transforms, false)'),
        'epa-accuracy':source.replace('if wdist > 0.0001','if wdist > 0.001'),
        'nonnative-double-length':source.replace('let d = d.scale(1.0 / d.length());','let d = d.scale(1.0 / (d.0.into_iter().map(|v| f64::from(v)*f64::from(v)).sum::<f64>().sqrt() as f32));'),
        'world-normal':source.replace('normal: epa.normal.negate(),','normal: transforms[0].basis.apply(epa.normal.negate()),'),
        'gjk-reduction':source.replace('if mask & (1 << i) != 0','if weight > 0.0'),
    }
    outcomes = {}
    environment = {k: v for k, v in os.environ.items() if not k.startswith('MDS_GJK_EPA_')}
    (output / 'results.json').write_text('{}\n')
    baseline = run_harness(source, output / 'baseline', args.crt_rlib, environment)
    outcomes['baseline'] = baseline
    (output / 'evidence.json').write_text(json.dumps(outcomes, indent=2) + '\n')
    if baseline['status'] != 'passed':
        raise SystemExit(f"Unmodified GJK/EPA baseline did not pass: {baseline['status']}")
    for name, changed in mutations.items():
        assert changed != source, name
        outcomes[name] = run_harness(changed, output / name, args.crt_rlib, environment)
        print(name, outcomes[name]['status'], flush=True)
        (output / 'evidence.json').write_text(json.dumps(outcomes, indent=2) + '\n')
    statuses = {name: result['status'] for name, result in outcomes.items() if name != 'baseline'}
    (output / 'results.json').write_text(json.dumps(statuses, indent=2) + '\n')
    if any(status != 'rejected' for status in statuses.values()):
        raise SystemExit('A GJK/EPA mutation survived or failed without a native comparison assertion')


TEST = 'gjk_epa::internal_queries_match_native_words'


def classify(result):
    log = result.stdout + result.stderr
    if result.returncode == 0:
        status = 'passed' if re.search(r'test result: ok\. 1 passed; 0 failed;', log) else 'invalid-test-result'
        return {'status': status, 'returncode': result.returncode}
    failure = {'status': 'non-comparison-failure', 'returncode': result.returncode}
    if result.returncode != 101 or log.count('panicked at ') != 1:
        return failure
    if not re.search(r"thread '" + TEST + r"'(?: \(\d+\))? panicked at [^\n]*gjk_epa\.rs:\d+:\d+:\n", log):
        return failure
    if not re.search(r'test result: FAILED\. 0 passed; 1 failed; 0 ignored;', log):
        return failure
    matches = re.findall(r'MDS_GJK_EPA_NATIVE_MISMATCH_BEGIN\n(.*?)\nMDS_GJK_EPA_NATIVE_MISMATCH_END', log, re.S)
    if len(matches) != 1:
        return failure
    differences, cases = [], set()
    for line in matches[0].splitlines():
        match = re.fullmatch(r'query (\d+) input (.*?) actual (.*?) expected (.*)', line)
        if match is None:
            return failure
        case = int(match[1])
        inputs = match[2].split()
        actual, expected = match[3].split('\t'), match[4].split('\t')
        if case >= 1801 or case in cases or len(inputs) != 36 or inputs[0] != str(case):
            return failure
        if inputs[1] not in ['0', '1', '2'] or inputs[2] not in ['0', '1', '2'] or any(re.fullmatch('[0-9a-f]{8}', word) is None for word in inputs[3:]):
            return failure
        if actual[0] != str(case) or expected[0] != str(case) or actual == expected:
            return failure
        try:
            a = dict(zip(fields('gjk-epa', actual), actual[1:]))
            e = dict(zip(fields('gjk-epa', expected), expected[1:]))
        except ValueError:
            return failure
        cases.add(case)
        differences.extend([case, field, a.get(field), e.get(field)] for field in dict.fromkeys([*a, *e]) if a.get(field) != e.get(field))
    if not differences:
        return failure
    return {'status': 'rejected', 'returncode': result.returncode, 'differences': differences}


def harness_source(kernel):
    math = ROOT / 'rust/crates/mds-bullet/src/core/math.rs'
    shape = math.with_name('shape.rs')
    test = ROOT / 'rust/crates/mds-bullet/tests/pure_bullet/gjk_epa.rs'
    paths = [json.dumps(str(p), ensure_ascii=False) for p in [math, shape, kernel, test]]
    return (f'#![allow(dead_code,unused_variables)]\nmod core {{ #[path={paths[0]}] pub mod math; '
            f'#[path={paths[1]}] pub mod shape; #[path={paths[2]}] pub mod gjk_epa; }}\n'
            f'#[path={paths[3]}] mod gjk_epa;\n')


def run_harness(source, directory, crt_rlib, environment):
    directory.mkdir(parents=True, exist_ok=True)
    kernel = directory / 'gjk_epa.rs'
    kernel.write_text(source)
    harness = directory / 'harness.rs'
    harness.write_text(harness_source(kernel))
    binary = directory / ('test.exe' if os.name == 'nt' else 'test')
    command = ['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--test', '-O', str(harness), '--extern', f'mds_crtmath={crt_rlib.resolve()}', '-o', str(binary)]
    try:
        compiled = subprocess.run(command, cwd=ROOT / 'rust', env=environment, capture_output=True, text=True, timeout=120)
        (directory / 'compile.log').write_text(compiled.stdout + compiled.stderr)
        if compiled.returncode:
            return {'status': 'compile-failure', 'returncode': compiled.returncode}
        result = subprocess.run([binary, '--exact', TEST], cwd=ROOT / 'rust', env=environment, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {'status': 'timeout'}
    except OSError as error:
        return {'status': 'execution-error', 'error': str(error)}
    (directory / 'test.log').write_text(result.stdout + result.stderr)
    return classify(result)


if __name__=='__main__':main()
