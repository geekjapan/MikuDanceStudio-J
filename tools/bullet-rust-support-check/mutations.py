#!/usr/bin/env python3
"""Compile isolated source mutations and require the compact fixture to reject each."""
import argparse
import json
import os
import re
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--crt-rlib', type=Path, required=True)
    args = parser.parse_args()
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = (ROOT / 'rust/crates/mds-bullet/src/core/shape.rs').read_text()
    start = source.index('    /// Nonvirtual convex support')
    end = source.index('    pub fn margin(self)', start)
    prefix, body, suffix = source[:start], source[start:end], source[end:]
    with_margin = body.index('    pub fn supporting_vertex_nonvirtual')
    mutations = {
        'virtual-substitute': body[:with_margin] + '    pub fn supporting_vertex_nonvirtual(self, direction: Vec3) -> Option<Vec3> { self.supporting_vertex(direction) }\n',
        'sphere-radius-without-margin': body.replace('Self::Sphere { .. } => Vec3::ZERO', 'Self::Sphere { radius } => direction.normalize().scale(radius)'),
        'capsule-margin-removal': body.replace('.sub(v.scale(CONVEX_MARGIN))', ''),
        'cap-greater-equal': body.replace('dot > maximum', 'dot >= maximum'),
        'capsule-threshold-equal': body.replace('length2 < 0.0001', 'length2 <= 0.0001'),
        'capsule-length-association': body.replace('(z * z + y * y) + x * x', '(x * x + y * y) + z * z'),
        'capsule-radius-association': body.replace('.scale(radius))\n                        .sub(v.scale(CONVEX_MARGIN))', '.scale(radius - CONVEX_MARGIN))'),
        'margin-length-association': body.replace('(y * y + z * z) + x * x', '(x * x + y * y) + z * z'),
    }
    environment = {k: v for k, v in os.environ.items() if not k.startswith('MDS_SUPPORT_')}
    outcomes = {}
    (output / 'results.json').write_text('{}\n')
    baseline = run_harness(source, output / 'baseline', args.crt_rlib, environment)
    outcomes['baseline'] = baseline
    (output / 'evidence.json').write_text(json.dumps(outcomes, indent=2) + '\n')
    if baseline['status'] != 'passed':
        raise SystemExit(f"Unmodified support baseline did not pass: {baseline['status']}")
    for name, mutated in mutations.items():
        assert mutated != body, name
        outcomes[name] = run_harness(prefix + mutated + suffix, output / name, args.crt_rlib, environment)
        print(name, outcomes[name]['status'], flush=True)
    (output / 'evidence.json').write_text(json.dumps(outcomes, indent=2) + '\n')
    statuses = {name: result['status'] for name, result in outcomes.items() if name != 'baseline'}
    (output / 'results.json').write_text(json.dumps(statuses, indent=2) + '\n')
    if any(status != 'rejected' for status in statuses.values()):
        raise SystemExit('A support mutation survived or failed without a native comparison assertion')


TEST = 'support::nonvirtual_support_matches_native_words'
FIELDS = [f'{entry}.{axis}' for entry in ['without-margin', 'with-margin', 'virtual'] for axis in 'xyz']


def classify(result):
    log = result.stdout + result.stderr
    if result.returncode == 0:
        status = 'passed' if re.search(r'test result: ok\. 1 passed; 0 failed;', log) else 'invalid-test-result'
        return {'status': status, 'returncode': result.returncode}
    failure = {'status': 'non-comparison-failure', 'returncode': result.returncode}
    if result.returncode != 101 or log.count('panicked at ') != 1:
        return failure
    if not re.search(r"thread '" + TEST + r"'(?: \(\d+\))? panicked at [^\n]*support\.rs:\d+:\d+:\n", log):
        return failure
    if not re.search(r'test result: FAILED\. 0 passed; 1 failed; 0 ignored;', log):
        return failure
    matches = re.findall(r'MDS_SUPPORT_NATIVE_MISMATCH_BEGIN\n(.*?)\nMDS_SUPPORT_NATIVE_MISMATCH_END', log, re.S)
    if len(matches) != 1:
        return failure
    differences = []
    cases = set()
    for line in matches[0].splitlines():
        match = re.fullmatch(r'support case (\d+) actual \[(.*?)\] expected \[(.*?)\]', line)
        if match is None:
            return failure
        case = int(match[1])
        actual, expected = match[2].split(', '), match[3].split(', ')
        if case >= 1600 or case in cases or len(actual) != 9 or len(expected) != 9 or actual == expected:
            return failure
        if any(re.fullmatch('[0-9a-f]{8}', word) is None for word in actual + expected):
            return failure
        cases.add(case)
        differences.extend([case, field, a, e] for field, a, e in zip(FIELDS, actual, expected) if a != e)
    if not differences:
        return failure
    return {'status': 'rejected', 'returncode': result.returncode, 'differences': differences}


def run_harness(source, directory, crt_rlib, environment):
    directory.mkdir(parents=True, exist_ok=True)
    shape = directory / 'shape.rs'
    shape.write_text(source)
    harness = directory / 'test.rs'
    math = ROOT / 'rust/crates/mds-bullet/src/core/math.rs'
    test = ROOT / 'rust/crates/mds-bullet/tests/pure_bullet/support.rs'
    harness.write_text(f'#![allow(dead_code)]\nmod core {{ #[path = "{math}"] pub mod math; #[path = "{shape}"] pub mod shape; }}\n#[path = "{test}"] mod support;\n')
    executable = directory / ('test.exe' if os.name == 'nt' else 'test')
    command = ['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--test', '-O', str(harness), '--extern', f'mds_crtmath={crt_rlib.resolve()}', '-o', str(executable)]
    try:
        compiled = subprocess.run(command, cwd=ROOT / 'rust', env=environment, capture_output=True, text=True, timeout=120)
        (directory / 'compile.log').write_text(compiled.stdout + compiled.stderr)
        if compiled.returncode:
            return {'status': 'compile-failure', 'returncode': compiled.returncode}
        result = subprocess.run([executable, '--exact', TEST], cwd=ROOT / 'rust', env=environment,
                                capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {'status': 'timeout'}
    except OSError as error:
        return {'status': 'execution-error', 'error': str(error)}
    (directory / 'test.log').write_text(result.stdout + result.stderr)
    return classify(result)

if __name__ == '__main__':
    main()
