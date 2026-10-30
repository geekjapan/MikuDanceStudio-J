"""Hosted compiler-owned common-plan gate and pure retained-data validation."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from common_plan_report import ReportValidation, seal_live_report, parent_resources


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


def unproved_reason(value):
    return (type(value) is dict and set(value) == {'unproved'}
            and type(value['unproved']) is str and bool(value['unproved'].strip()))


def unknown_signature(value):
    if unproved_reason(value):
        return True
    return (type(value) is dict and set(value) == {'canonical', 'const', 'volatile', 'restrict'}
            and all(type(value[key]) is bool for key in ('const', 'volatile', 'restrict'))
            and unproved_reason(value['canonical']))


def native_location(value):
    if unproved_reason(value):
        return True
    if type(value) is not dict or set(value) != {'spelling', 'expansion', 'presumed'}:
        return False
    for key in ('spelling', 'expansion'):
        position = value[key]
        if unproved_reason(position):
            continue
        if type(position) is not dict or set(position) != {'path', 'buffer_sha256', 'begin', 'end', 'bytes_hex'}:
            return False
        if not (type(position['path']) is str and bool(position['path'])
                and type(position['begin']) is int and type(position['end']) is int
                and 0 <= position['begin'] <= position['end'] < 2**63):
            return False
        digest, text = position['buffer_sha256'], position['bytes_hex']
        if not (type(digest) is str and len(digest) == 64
                and all(c in '0123456789abcdef' for c in digest)
                and type(text) is str and len(text) == 2 * (position['end'] - position['begin'])
                and all(c in '0123456789abcdef' for c in text)):
            return False
    presumed = value['presumed']
    return (type(presumed) is dict and set(presumed) == {'path', 'line'}
            and type(presumed['path']) is str and type(presumed['line']) is int
            and 0 <= presumed['line'] < 2**63)


def preserved_unknowns(reports, validation, sources):
    units = set()
    for facts in reports:
        require(type(facts) is dict, 'independent unknown report must be an object')
        unit = facts.get('unit')
        require(type(unit) is str and unit in sources, 'independent unknown unit differs')
        require(unit not in units, 'duplicate independent unknown unit')
        units.add(unit)
        definitions = facts.get('unclassified_definitions')
        require(type(definitions) is list, 'unclassified definitions must be a list')
        declarations = set()
        for definition in definitions:
            require(type(definition) is dict and set(definition) == {
                'declaration', 'location', 'reason', 'signature', 'state', 'symbol'},
                'unclassified definition schema differs')
            require(type(definition['declaration']) is int and 0 < definition['declaration'] < 2**64
                    and type(definition['location']) is dict and type(definition['signature']) is dict,
                    'unclassified definition field types differ')
            require(definition['declaration'] not in declarations, 'duplicate unclassified declaration')
            declarations.add(definition['declaration'])
            require(definition['state'] == 'Unproved'
                    and definition['reason'] == 'native attributed function signature unclassified',
                    'unclassified definition evidence differs')
            require(native_location(definition['location']),
                    'unclassified definition location evidence differs or is unsupported')
            require(unknown_signature(definition['signature']),
                    'unclassified definition signature must remain unproved; unsupported evidence shape')
            symbol = definition['symbol']
            require(type(symbol) is dict and set(symbol) == {'unit', 'static'},
                    'unclassified definition requires static C source identity')
            require(type(symbol['unit']) is str and symbol['unit'] == unit
                    and type(symbol['static']) is str and bool(symbol['static']),
                    'unclassified definition static source identity differs')
            validation.independent(unit, symbol['static'])
    count = validation.independent_count()
    require(count > 0, 'missing independent unknown-signature evidence')
    return dict(status='PASS', count=count, join='full_source_and_name_bytes')


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
    def diagnostic_run(command, log, **kwargs):
        return run(command, log, diagnostics=dict(phase=log.stem, path=log.with_suffix('.diagnostics.jsonl')), **kwargs)
    for mode in ('off', 'on'):
        argv = base if mode == 'off' else [base[0], '--diagnostic-common-plan', *base[1:]]
        receipts[mode] = diagnostic_run(argv, output / (mode + '.log'), timeout=timeout)
        (output / 'executions.json').write_text(json.dumps(receipts, indent=2) + '\n')
        require(receipts[mode]['exit_code'] == 0 and not receipts[mode]['timed_out'], 'common-plan compiler failed in ' + mode)
        emitted.rename(output / mode)
    manifests = {mode: generated(output / mode) for mode in ('off', 'on')}
    require(manifests['off'] and manifests['off'] == manifests['on'], 'common-plan Rust or build bytes differ')
    authority = seal_live_report(output / 'on', receipts['on'])
    (output / 'common-plan-authority.json').write_text(json.dumps(authority, indent=2) + '\n')
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
    from closed_format_facts import authority_packet, read_authority, manifest
    report_root = database.parent / 'closed-format-facts'
    packet, independent_authority = authority_packet(report_root, entries, tool)
    (output / 'independent-report-authority.json').write_text(json.dumps(independent_authority, indent=2) + '\n')
    with ReportValidation(output / 'on', entries, authority) as validation:
        independent_unknowns = preserved_unknowns(
            (read_authority(report_root, pair) for pair in packet['units']), validation, validation.sources)
        require(manifest(report_root) == independent_authority, 'independent packet changed during unknown join')
        counts = validation.counts
        resources = parent_resources()
    controls = boundary_controls(tool, output / 'controls', timeout, diagnostic_run)
    report = dict(schema=2, status='PASS', authorization='diagnostic_only', lowering='not_authorized',
                  generated=manifests, counts=counts, preserved_unknowns=independent_unknowns,
                  parent_validation_resources=resources, executions=receipts, controls=controls,
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
    paths = [source / 'c2rust-transpile/src/c_ast/closed_plan_tests.rs', source / 'c2rust-transpile/src/program.rs',
             source / 'c2rust-transpile/src/c_ast/closed_variadic.rs']
    expected = {name for path in paths for name in re.findall(r'fn (closed_variadic_plan_\w+)\(', path.read_text())}
    report_controls = {'closed_variadic_plan_command_reorder_preserves_owned_plan',
                       'closed_variadic_plan_unknown_authority_preserves_complete_projection',
                       'closed_variadic_plan_unknown_authority_exact_cap_and_one_over_refuse',
                       'closed_variadic_plan_paged_report_matches_legacy_logical',
                       'closed_variadic_plan_test_only_oracle_propagates_write_failure',
                       'closed_variadic_plan_report_flush_failure_publishes_no_partial_output',
                       'closed_variadic_plan_paged_file_failures_publish_no_partial_output',
                       'closed_variadic_plan_paged_report_giant_native_fact_is_lossless',
                       'closed_variadic_plan_paged_report_giant_text_vectors_and_owner_are_lossless',
                       'closed_variadic_plan_paged_report_caps_abort_before_index'}
    require(report_controls <= expected, 'focused report writer controls missing from compiler source')
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
