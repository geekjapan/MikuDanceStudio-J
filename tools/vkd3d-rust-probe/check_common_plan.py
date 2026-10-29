"""Hosted compiler-owned common-plan gate and pure retained-data validation."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def generated(root):
    return {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in sorted(root.rglob('*'))
            if p.is_file() and p.suffix in ('.rs', '.toml')}


def validate_plan(plan, entries):
    require(plan.get('status') == 'ClosedDiagnosticPlan' and plan.get('lowering') == 'not_authorized',
            'compiler plan must remain diagnostic')
    units = plan['units']
    require(len(units) == len(entries), 'incomplete common-plan command universe')
    expected = {}
    for row in entries:
        source = str((Path(row['directory']) / row['file']).resolve())
        effective = dict(directory=str(Path(row['directory']).resolve()), file=source,
                         arguments=row['arguments'], output=row.get('output'))
        command = sha(canonical(dict(command=effective, extra=[])))
        expected[command] = source
    require(len(expected) == len(entries), 'duplicate effective command')
    observed = set()
    for unit in units:
        identity = unit['identity']
        command = identity['command']
        require(command in expected and identity['source'] == expected[command] and command not in observed,
                'source or effective-command binding differs')
        observed.add(command)
        require(unit['native_ast_exports'] == unit['typed_imports'] == 1, 'native export/import count differs')
        require(len(identity['ast_instance']) == 64 and all(c in '0123456789abcdef' for c in identity['ast_instance']),
                'missing actual native AST instance digest')
        require(identity['target'] and len(identity['widths']) == 8 and all(identity['widths']), 'unresolved target facts')
        require(identity['source'] in unit['source_sha256'], 'missing original main buffer seal')
        for name, digest in unit['source_sha256'].items():
            require(sha(Path(name).read_bytes()) == digest, 'original native source changed')
        expected_key = sha(canonical(dict(command=command, domain=identity['domain'], target=identity['target'],
                                         widths=identity['widths'], sources=unit['source_sha256'])))
        require(identity['key'] == expected_key, 'semantic UnitKey differs')
        declarations = {d['id']: d for d in unit['declarations']}
        require(len(declarations) == len(unit['declarations']), 'duplicate authentic declaration ID')
        calls = {c['id']: c for c in unit['calls']}
        require(len(calls) == len(unit['calls']), 'duplicate authentic enclosing Call ID')
        for declaration in declarations.values():
            require(declaration['key'] == dict(unit=identity['key'], declaration=declaration['id']), 'declaration semantic scope differs')
            require(set(declaration['blockers']).isdisjoint({'Lower', 'Permitted', 'Authorized'}), 'unexpected lowering authorization')
            shape = declaration['signature']['shape']
            if isinstance(shape, dict) and 'Unknown' in shape:
                require('UnknownSignature' in declaration['blockers'], 'unknown signature lost its blocker')
        for call in calls.values():
            require(call['key'] == dict(unit=identity['key'], expression=call['id']), 'Call semantic scope differs')
            require(call['owner'] is None or call['owner']['unit'] == identity['key']
                    and call['owner']['declaration'] in declarations, 'Call owner scope differs')
            require(call['direct'] is None or call['direct'] in declarations, 'Call references an unknown declaration')
            require(call['disposition'] == 'Existing' or isinstance(call['disposition'], dict)
                    and set(call['disposition']) == {'Deferred'}, 'unsupported call disposition')
    return dict(units=len(units), declarations=sum(len(u['declarations']) for u in units),
                calls=sum(len(u['calls']) for u in units),
                unknown_definitions=[dict(unit=u['identity']['source'], id=d['id'], name=d['name'], blockers=d['blockers'])
                    for u in units for d in u['declarations'] if d['definition'] and 'UnknownSignature' in d['blockers']])


def collect(tool, database, output, timeout):
    from full_compiler import UNITS, verify_cursor_tool
    from probe import run
    verify_cursor_tool(tool)
    entries = json.loads(database.read_text())
    require(sorted(str(Path(c['file']).relative_to(c['directory'])) for c in entries) == list(UNITS),
            'common-plan gate requires untouched complete all24 input')
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(database, output / 'compile_commands.json')
    tool_root = tool.parent.parent
    shutil.copytree(tool_root / 'source-evidence', output / 'source-evidence')
    shutil.copy2(tool_root / 'source-receipt.json', output / 'source-receipt.json')
    (output / 'tool-identity.json').write_text(json.dumps(dict(compiler_sha256=sha(tool.read_bytes()),
        source_receipt_sha256=sha((output / 'source-receipt.json').read_bytes())), indent=2) + '\n')
    emitted = output / 'emitted'
    base = [str(tool), '--fail-on-error', '--disable-rustfmt', '--edition', '2024',
            '--emit-build-files', '--output-dir', str(emitted), str(database)]
    receipts = {}
    for mode in ('off', 'on'):
        argv = base if mode == 'off' else [base[0], '--diagnostic-common-plan', *base[1:]]
        receipts[mode] = run(argv, output / (mode + '.log'), timeout=timeout)
        (output / 'executions.json').write_text(json.dumps(receipts, indent=2) + '\n')
        require(receipts[mode]['exit_code'] == 0 and not receipts[mode]['timed_out'], 'common-plan compiler failed in ' + mode)
        emitted.rename(output / mode)
    manifests = {mode: generated(output / mode) for mode in ('off', 'on')}
    require(manifests['off'] and manifests['off'] == manifests['on'], 'common-plan Rust or build bytes differ')
    plan = json.loads((output / 'on/closed-variadic-plan.json').read_text())
    counts = validate_plan(plan, entries)
    log = (output / 'on.log').read_text()
    require(log.count('COMMON_PLAN_NATIVE_EXPORT ') == len(entries), 'actual native export trace count differs')
    require(log.count('COMMON_PLAN_TYPED_IMPORT ') == len(entries), 'actual typed import trace count differs')
    require(log.count('COMMON_PLAN_EMIT ') == len(entries), 'actual bound emission trace count differs')
    closed = 'COMMON_PLAN_CLOSED ' + str(len(entries))
    require(log.count(closed) == 1 and log.index(closed) < log.index('COMMON_PLAN_EMIT '), 'emission preceded complete plan')
    for p in (output / 'on').rglob('*'):
        if p.is_file() and p.suffix in ('.rs', '.toml'):
            require(b'.c2rust-plan-' not in p.read_bytes(), 'staging path leaked into generated bytes')
    inventory = database.parent / 'closed-format-facts/inventory-plan.json'
    report_root = database.parent / 'closed-format-facts/on'
    independent_unknowns = {(facts['unit'], d['name'])
        for path in report_root.rglob('*.closed-format.json')
        for facts in [json.loads(path.read_text())] for d in facts['unclassified_definitions']}
    require(independent_unknowns, 'missing independent unknown-signature evidence')
    plan_unknowns = {(d['unit'], d['name']) for d in counts['unknown_definitions']}
    require(independent_unknowns <= plan_unknowns, 'common plan lost an original unclassified definition')
    controls = boundary_controls(tool, output / 'controls', timeout, run)
    report = dict(status='PASS', authorization='diagnostic_only', lowering='not_authorized',
                  generated=manifests, counts=counts, preserved_unknowns=sorted(independent_unknowns), executions=receipts, controls=controls,
                  source_receipt_sha256=sha((output / 'source-receipt.json').read_bytes()),
                  compiler_sha256=sha(tool.read_bytes()), native_preprocessing='optional_second_Tool_run_when_emit_c_decl_map',
                  stable_build='UNRUN', native_abi='UNRUN', cmp='UNRUN')
    if inventory.is_file():
        report['independent_inventory_sha256'] = sha(inventory.read_bytes())
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def boundary_controls(tool, root, timeout, run):
    root.mkdir()
    source = root / 'legal.c'
    source.write_text('int f(int n,...){return n;} int g(void){return f(1,2);}\n')
    database = root / 'compile_commands.json'
    row = dict(directory=str(root.resolve()), file=str(source.resolve()), arguments=['clang', '-c', str(source.resolve())])
    database.write_text(json.dumps([row]))
    receipts = {}
    baseline = root / 'legal-baseline'
    receipts['legal-baseline'] = run([str(tool), '--diagnostic-common-plan', '--fail-on-error', '--disable-rustfmt',
        '--output-dir', str(baseline), str(database)], root / 'legal-baseline.log', timeout=timeout)
    require(receipts['legal-baseline']['exit_code'] == 0 and not receipts['legal-baseline']['timed_out']
            and (baseline / 'closed-variadic-plan.json').is_file(), 'legal native baseline did not publish')
    overlay = root / 'empty-overlay.json'
    overlay.write_text(json.dumps(dict(version=0, roots=[])))
    for label, text, flags, reason in [
            ('recoverable-diagnostic', '#error reject_common_plan\nint legal(void){return 1;}\n', [], 'native preparation failed'),
            ('modules', 'int legal(void){return 1;}\n', ['-fmodules'], 'unsupported native input mode'),
            ('vfs-overlay', 'int legal(void){return 1;}\n', ['-ivfsoverlay', str(overlay)], 'unsupported native input mode')]:
        rejected = root / (label + '.c')
        rejected.write_text(text)
        negative = dict(row, file=str(rejected.resolve()), arguments=['clang', *flags, '-c', str(rejected.resolve())])
        database.write_text(json.dumps([row, negative]))
        dest = root / label
        receipts[label] = run([str(tool), '--diagnostic-common-plan', '--fail-on-error', '--disable-rustfmt',
            '--output-dir', str(dest), str(database)], root / (label + '.log'), timeout=timeout)
        log = (root / (label + '.log')).read_text()
        require(receipts[label]['exit_code'] != 0 and not receipts[label]['timed_out']
                and 'COMMON_PLAN_TYPED_IMPORT ' in log and reason in log
                and 'COMMON_PLAN_CLOSED ' not in log, 'negative missed native intake: ' + label)
        require(not dest.exists(), 'native intake failure published: ' + label)
    database.write_text(json.dumps([row]))
    for label, extra, existing in [('existing-root', [], True), ('refactoring', ['--reorganize-definitions'], False),
                                   ('postprocess', ['--remote-llm-postprocess'], False)]:
        dest = root / label
        if existing:
            dest.mkdir()
            (dest / 'user.txt').write_text('user-owned\n')
        before = generated(dest) if existing else {}
        argv = [str(tool), '--diagnostic-common-plan', '--fail-on-error', '--disable-rustfmt', *extra,
                '--output-dir', str(dest), str(database)]
        receipts[label] = run(argv, root / (label + '.log'), timeout=timeout)
        require(receipts[label]['exit_code'] != 0 and not receipts[label]['timed_out'], 'boundary did not refuse ' + label)
        require(not dest.exists() if not existing else generated(dest) == before
                and (dest / 'user.txt').read_text() == 'user-owned\n', 'boundary published partial output')
    broken = root / 'broken.c'
    broken.write_text('int incomplete( {\n')
    second = dict(row, file=str(broken.resolve()), arguments=['clang', '-c', str(broken.resolve())])
    database.write_text(json.dumps([row, second]))
    dest = root / 'failed-intake'
    receipts['failed-intake'] = run([str(tool), '--diagnostic-common-plan', '--fail-on-error', '--disable-rustfmt',
                                     '--output-dir', str(dest), str(database)], root / 'failed-intake.log', timeout=timeout)
    require(receipts['failed-intake']['exit_code'] != 0 and not receipts['failed-intake']['timed_out'], 'invalid intake was accepted')
    require('COMMON_PLAN_TYPED_IMPORT ' in (root / 'failed-intake.log').read_text(), 'negative did not reach legal native baseline')
    require(not dest.exists(), 'failed intake published partial Rust/build files')
    alternate = dict(row, output='second.o', arguments=['clang', '-DSECOND=1', '-c', str(source.resolve())])
    database.write_text(json.dumps([dict(row, output='first.o'), alternate]))
    dest = root / 'same-source-commands'
    receipts['same-source-commands'] = run([str(tool), '--diagnostic-common-plan', '--fail-on-error', '--disable-rustfmt',
        '--output-dir', str(dest), str(database)], root / 'same-source-commands.log', timeout=timeout)
    log = (root / 'same-source-commands.log').read_text()
    require(receipts['same-source-commands']['exit_code'] != 0 and not receipts['same-source-commands']['timed_out']
            and 'COMMON_PLAN_CLOSED 2' in log and log.count('COMMON_PLAN_TYPED_IMPORT ') == 2,
            'same-source command negative failed before complete native intake')
    require('common plan refuses colliding output paths' in log and not dest.exists(), 'colliding outputs were published')
    broken.write_text('double _Complex bad(void){return 1.0i;}\n')
    database.write_text(json.dumps([row, second]))
    dest = root / 'failed-conversion'
    receipts['failed-conversion'] = run([str(tool), '--diagnostic-common-plan', '--fail-on-error', '--disable-rustfmt',
        '--output-dir', str(dest), str(database)], root / 'failed-conversion.log', timeout=timeout)
    log = (root / 'failed-conversion.log').read_text()
    require(receipts['failed-conversion']['exit_code'] != 0 and not receipts['failed-conversion']['timed_out']
            and 'COMMON_PLAN_CLOSED 2' in log and log.count('COMMON_PLAN_EMIT ') == 2
            and 'common plan conversion failed' in log, 'conversion negative missed the shared emitter checker')
    require(not dest.exists(), 'failed conversion published partial Rust/build files')
    (root / 'executions.json').write_text(json.dumps(receipts, indent=2) + '\n')
    return receipts


def check_test_receipts(source, listing, execution):
    import re
    paths = [source / 'c2rust-transpile/src/c_ast/closed_plan_tests.rs', source / 'c2rust-transpile/src/program.rs']
    expected = {name for path in paths for name in re.findall(r'fn (closed_variadic_plan_\w+)\(', path.read_text())}
    discovered = {line.removesuffix(': test').split('::')[-1] for line in listing.read_text().splitlines()
                  if line.endswith(': test') and 'closed_variadic_plan_' in line}
    passed = {name.split('::')[-1] for name in re.findall(r'^test (\S*closed_variadic_plan_\S*) \.\.\. ok$', execution.read_text(), re.M)}
    require(expected and expected == discovered == passed, 'focused real compiler discovery/execution coverage differs')
    return dict(status='PASS', discovered_count=len(discovered), tests=sorted(discovered))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool', type=Path)
    parser.add_argument('--database', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--compiler-source', type=Path)
    parser.add_argument('--test-list', type=Path)
    parser.add_argument('--test-log', type=Path)
    parser.add_argument('--timeout', type=int, default=1800)
    args = parser.parse_args()
    if args.compiler_source:
        report = check_test_receipts(args.compiler_source, args.test_list, args.test_log)
    else:
        require(args.tool and args.database and args.output, 'tool, database and output are required')
        report = collect(args.tool.resolve(), args.database.resolve(), args.output.resolve(), args.timeout)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
