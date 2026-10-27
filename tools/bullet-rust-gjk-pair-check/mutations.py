#!/usr/bin/env python3
"""Require each compiled semantic mutation to fail the real native comparison."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/bullet-rust-support-check'))
from host_profiles import fields, rows

TEST = 'gjk_pair_tests::outer_and_persistent_mixed_pairs_match_native_words'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--crt-rlib',type=Path,required=True)
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--native',type=Path,required=True)
    args=parser.parse_args();output=args.out_dir.resolve();output.mkdir(parents=True,exist_ok=True)
    core=ROOT/'rust/crates/mds-bullet/src/core'
    pair=(core/'gjk_pair.rs').read_text();contact=(core/'contact.rs').read_text();kernel=(core/'gjk_epa.rs').read_text()
    mutations={
        'delete-penetration':('gjk_epa',kernel.replace('if let QueryResult::Success(solution) = penetration(shapes, transforms, guess, true)','if let QueryResult::Success(solution) = QueryResult::Failure(Status::Separated)')),
        'delete-distance-fallback':('gjk_epa',kernel.replace('} else if let QueryResult::Success(solution) = distance(shapes, transforms, guess)', '} else if let QueryResult::Success(solution) = QueryResult::Failure(Status::GjkFailed)')),
        'nonvalid-is-failure':('gjk_epa',kernel.replace('== EpaStatus::Failed {','!= EpaStatus::Valid {')),
        'face-tie':('gjk_epa',kernel.replace('sqd < mind','sqd <= mind')),
        'stock-final-distance-gate':('gjk_pair',pair.replace('if let Some(mut point) = contact {','if let Some(mut point) = contact.filter(|p| p.distance < 0.0 || p.distance * p.distance < maximum_distance_squared) {')),
        'rotate-fallback-normal':('gjk_pair',pair.replace('PenDepth::Separated(solution) => {\n                query.cached_axis = solution.normal;', 'PenDepth::Separated(solution) => {\n                query.cached_axis = transforms[0].basis.apply(solution.normal);')),
        'normalize-fallback-normal':('gjk_pair',pair.replace('PenDepth::Separated(solution) => {\n                query.cached_axis = solution.normal;', 'PenDepth::Separated(solution) => {\n                query.cached_axis = solution.normal.scale(1.0 / solution.normal.length());')),
        'remove-midpoint':('gjk_pair',pair.replace('let offset = transforms[0].origin.add(transforms[1].origin).scale(0.5);','let offset = Vec3::ZERO;')),
        'fresh-simplex':('gjk_pair',pair.replace('    simplex.reset();','    let mut fresh = VoronoiSimplexSolver::default();\n    let simplex = &mut fresh;\n    simplex.reset();')),
        'erase-cache':('gjk_pair',pair.replace('    simplex.reset();','    simplex.reset();\n    simplex.cached_p1 = Vec3::ZERO;\n    simplex.cached_p2 = Vec3::ZERO;\n    simplex.cached_v = Vec3::ZERO;')),
        'clear-manifold':('contact',contact.replace('            PairKind::ConvexConvex => {','            PairKind::ConvexConvex => {\n                self.count = 0;')),
        'strict-manifold-threshold':('contact',contact.replace('if distance > self.threshold {','if distance >= self.threshold {')),
        'float-threshold-sum':('contact',contact.replace('let sum = self.shapes[1].margin() as f64','let sum = self.shapes[1].margin()').replace('(self.threshold as f64 + self.shapes[0].margin() as f64)','(self.threshold + self.shapes[0].margin())')),
    }
    results = {}
    clean = {k: v for k, v in os.environ.items() if not k.startswith('MDS_GJK_PAIR_')}
    env = dict(clean, MDS_GJK_PAIR_INPUTS=str(args.inputs.resolve()), MDS_GJK_PAIR_NATIVE=str(args.native.resolve()))
    (output / 'results.json').write_text('{}\n')
    for name, environment in [('baseline-default', clean), ('baseline-full-same-host', env)]:
        results[name] = run_harness(None, None, output / name, args.crt_rlib, environment)
        (output / 'evidence.json').write_text(json.dumps(results, indent=2)+'\n')
        if results[name]['status'] != 'passed':
            raise SystemExit(f'Mandatory {name} failed; mutations not run')
    for name,(module,changed) in mutations.items():
        assert changed!=(core/(module+'.rs')).read_text(),name
        results[name] = run_harness(module, changed, output / name, args.crt_rlib, env)
        print(name, results[name]['status'], flush=True)
        (output / 'evidence.json').write_text(json.dumps(results, indent=2)+'\n')
    for name, environment in [('clean-default', clean), ('clean-full-same-host', env)]:
        results[name] = run_harness(None, None, output / name, args.crt_rlib, environment)
        (output / 'evidence.json').write_text(json.dumps(results, indent=2)+'\n')
        if results[name]['status'] != 'passed':
            raise SystemExit(f'Mandatory {name} failed')
    statuses = {name: result['status'] for name, result in results.items() if name in mutations}
    (output / 'results.json').write_text(json.dumps(statuses, indent=2)+'\n')
    if len(statuses) != 13 or any(status != 'rejected' for status in statuses.values()):
        raise SystemExit('A semantic mutation survived or has a validation gap')


def classify(result):
    log = result.stdout + result.stderr
    gap = {'status': 'validation-gap', 'returncode': result.returncode}
    if result.returncode == 0:
        return {'status': 'passed' if re.search(r'test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;', log) and f'test {TEST} ... ok' in log else 'validation-gap', 'returncode': 0}
    if result.returncode != 101 or log.count('panicked at ') != 1:
        return gap
    if not re.search(r"thread '" + TEST + r"'(?: \(\d+\))? panicked at [^\n]*gjk_pair\.rs:\d+:\d+:\n", log):
        return gap
    if not re.search(r'test result: FAILED\. 0 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out;', log):
        return gap
    blocks = re.findall(r'MDS_GJK_PAIR_NATIVE_MISMATCH_BEGIN\n(.*?)\nMDS_GJK_PAIR_NATIVE_MISMATCH_END', log, re.S)
    if len(blocks) != 1:
        return gap
    differences, cases = [], set()
    for line in blocks[0].splitlines():
        match = re.fullmatch(r'input (.*?) actual (.*?) expected (.*)', line)
        if match is None:
            return gap
        inputs, actual, expected = [part.split() for part in match.groups()]
        if len(inputs) != 39 or not inputs[0].isdigit() or not 0 <= int(inputs[0]) < 5081:
            return gap
        case = int(inputs[0])
        if case in cases or inputs[1] not in ['0', '1', '2'] or inputs[2] not in ['0', '1', '2'] or inputs[3] not in ['0', '1']:
            return gap
        if any(re.fullmatch('[0-9a-f]{8}', value) is None for value in inputs[4:]):
            return gap
        if not actual or not expected or actual[0] != str(case) or expected[0] != str(case) or actual == expected:
            return gap
        try:
            a = dict(zip(fields('gjk-pair', actual), actual[1:]))
            e = dict(zip(fields('gjk-pair', expected), expected[1:]))
        except ValueError:
            return gap
        cases.add(case)
        differences.extend([case, field, a.get(field), e.get(field)] for field in dict.fromkeys([*a, *e]) if a.get(field) != e.get(field))
    return {'status': 'rejected', 'returncode': result.returncode, 'differences': differences} if differences else gap


def rust_path_literal(path):
    return json.dumps(path.as_posix(), ensure_ascii=False)


def full_baseline(directory, environment):
    facts = {'status': 'validation-gap'}
    try:
        inputs = Path(environment['MDS_GJK_PAIR_INPUTS']).read_bytes()
        native = Path(environment['MDS_GJK_PAIR_NATIVE']).read_bytes()
        (directory / 'baseline-inputs.tsv').write_bytes(inputs)
        (directory / 'baseline-native.tsv').write_bytes(native)
        facts['raw_sha256'] = {name: hashlib.sha256(data).hexdigest()
                               for name, data in [('inputs', inputs), ('native', native)]}
        generated = subprocess.check_output([sys.executable, ROOT / 'tools/bullet-rust-gjk-pair-check/cases.py'])
        generated = generated.replace(b'\r\n', b'\n')
        if len(generated.splitlines()) != 5081:
            raise ValueError('Generator must produce exactly 5081 rows')
        if inputs not in (generated, generated.replace(b'\n', b'\r\n')):
            raise ValueError('Full baseline inputs must exactly match all 5081 generated rows in order with LF or CRLF transport')
        facts['inputs'] = {'rows': 5081, 'line_ending': 'CRLF' if b'\r' in inputs else 'LF',
                           'lf_sha256': hashlib.sha256(generated).hexdigest()}
        normalized = native.replace(b'\r\n', b'\n')
        if (b'\r' in normalized or normalized.count(b'\n') != 5081 or not normalized.endswith(b'\n')
                or native not in (normalized, normalized.replace(b'\n', b'\r\n'))):
            raise ValueError('Full native baseline requires complete LF or CRLF transport')
        rows(normalized, 'gjk-pair', 5081)
        facts['native'] = {'rows': 5081, 'line_ending': 'CRLF' if b'\r' in native else 'LF',
                           'lf_sha256': hashlib.sha256(normalized).hexdigest()}
        facts['status'] = 'validated'
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
        facts['error'] = str(error)
    (directory / 'baseline-validation.json').write_text(json.dumps(facts, indent=2) + '\n', encoding='utf-8')
    return facts


def run_harness(module, changed, directory, crt_rlib, environment):
    directory.mkdir(parents=True, exist_ok=True)
    if any(key in environment for key in ['MDS_GJK_PAIR_INPUTS', 'MDS_GJK_PAIR_NATIVE']):
        validation = full_baseline(directory, environment)
        if validation['status'] != 'validated':
            return {'status': 'validation-gap', 'reason': 'invalid-full-baseline', 'error': validation['error']}
        environment = dict(environment, MDS_GJK_PAIR_INPUTS=str(directory / 'baseline-inputs.tsv'),
                           MDS_GJK_PAIR_NATIVE=str(directory / 'baseline-native.tsv'))
    core = ROOT / 'rust/crates/mds-bullet/src/core'
    original_module_sha256 = hashlib.sha256((core / (module + '.rs')).read_bytes()).hexdigest() if module else None
    requested_mutation_sha256 = hashlib.sha256(changed.encode()).hexdigest() if changed is not None else None
    harness = (ROOT / 'tools/bullet-rust-gjk-pair-check/harness.rs').read_text()
    harness = re.sub(r'#\[path = "([^\"]+)"\]', lambda m: '#[path = ' + rust_path_literal((ROOT / 'tools/bullet-rust-gjk-pair-check' / m[1]).resolve()) + ']', harness)
    original_test = ROOT / 'rust/crates/mds-bullet/tests/pure_bullet/gjk_pair.rs'
    test_source = original_test.read_text()
    test_source = re.sub(r'#\[test\]\n(fn (?!outer_and_persistent_mixed_pairs_match_native_words)[a-z_]+)', r'\1', test_source)
    test_source = re.sub(r'include_str!\("([^\"]+)"\)', lambda m: 'include_str!(' + rust_path_literal((original_test.parent / m[1]).resolve()) + ')', test_source)
    isolated = directory / 'comparison/gjk_pair.rs'
    isolated.parent.mkdir(exist_ok=True)
    isolated.write_text(test_source, encoding='utf-8')
    harness = harness.replace(rust_path_literal(original_test), rust_path_literal(isolated))
    if module != 'contact':
        contact = (core / 'contact.rs').read_text()
        contact = re.sub(r'#\[cfg\(test\)\]\n#\[path = "[^"]+"\]\nmod [a-z_]+;', '', contact)
        contact_source = directory / 'contact.rs'
        contact_source.write_text(contact, encoding='utf-8')
        harness = harness.replace(rust_path_literal(core / 'contact.rs'), rust_path_literal(contact_source))
    if module is not None:
        changed = re.sub(r'#\[cfg\(test\)\]\n#\[path = "[^"]+"\]\nmod [a-z_]+;', '', changed)
        changed = re.sub(r'#\[path = "(../../tests/[^\"]+)"\]', lambda m: '#[path = ' + rust_path_literal((core / m[1]).resolve()) + ']', changed)
        source = directory / (module + '.rs')
        source.write_text(changed, encoding='utf-8')
        harness = harness.replace(rust_path_literal(core / (module + '.rs')), rust_path_literal(source))
    harness = harness.replace('#![allow(dead_code)]', '#![allow(dead_code,unused_variables)]')
    test = directory / 'harness.rs'
    test.write_text(harness, encoding='utf-8')
    binary = directory / ('test.exe' if os.name == 'nt' else 'test')
    command = ['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--test', '-O', str(test), '--extern', f'mds_crtmath={crt_rlib.resolve()}', '-o', str(binary)]
    sources = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in [test, isolated, *([contact_source] if module != 'contact' else []), *([source] if module is not None else [])]}
    (directory / 'source-proof.json').write_text(json.dumps({'module': module, 'original_module_sha256': original_module_sha256,
        'requested_mutation_sha256': requested_mutation_sha256, 'source_sha256': sources,
        'compile_command': command, 'test_command': [str(binary), '--exact', TEST]}, indent=2) + '\n')
    try:
        compiled = subprocess.run(command, capture_output=True, text=True, cwd=ROOT / 'rust', env=environment, timeout=120)
        (directory / 'compile.log').write_text(compiled.stdout + compiled.stderr)
        (directory / 'compile-result.json').write_text(json.dumps({'returncode': compiled.returncode,
            'executable_sha256': hashlib.sha256(binary.read_bytes()).hexdigest() if compiled.returncode == 0 else None}, indent=2) + '\n')
        if compiled.returncode:
            return {'status': 'validation-gap', 'reason': 'compile-failure', 'returncode': compiled.returncode}
        result = subprocess.run([binary, '--exact', TEST], capture_output=True, text=True, cwd=ROOT / 'rust', env=environment, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'status': 'validation-gap', 'reason': str(error)}
    (directory / 'test.log').write_text(result.stdout + result.stderr)
    facts = classify(result)
    if facts['status'] == 'rejected':
        inputs = {line.split('\t', 1)[0]: line for line in (directory / 'baseline-inputs.tsv').read_text().splitlines()}
        native = {line.split('\t', 1)[0]: line for line in (directory / 'baseline-native.tsv').read_text().splitlines()}
        for supplied, actual, expected in re.findall(r'^input (.*?) actual (.*?) expected (.*?)$', result.stdout + result.stderr, re.M):
            case = supplied.split('\t', 1)[0]
            if supplied != inputs.get(case) or expected != native.get(case):
                facts = {'status': 'validation-gap', 'reason': 'mismatch-not-bound-to-same-host-baseline'}
                break
    (directory / 'result.json').write_text(json.dumps(facts, indent=2) + '\n')
    return facts


if __name__=='__main__':main()
