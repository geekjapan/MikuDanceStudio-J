"""Bounded all-unit experiment; generated compiler sources stay outside Git."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil

UNITS = tuple(sorted(
    ['libs/vkd3d-shader/' + name + '.c' for name in (
        'checksum', 'd3d_asm', 'd3dbc', 'dxbc', 'dxil', 'fx', 'glsl', 'hlsl',
        'hlsl.tab', 'hlsl.yy', 'hlsl_codegen', 'hlsl_constant_ops', 'ir', 'msl',
        'preproc.tab', 'preproc.yy', 'spirv', 'tpf', 'vkd3d_shader_main')]
    + ['libs/vkd3d-common/' + name + '.c' for name in ('blob', 'debug', 'error', 'memory', 'utf8')]))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generated_parser(working):
    matches = list((working / 'src').rglob('hlsl_tab.rs'))
    if (len(matches) != 1 or not matches[0].is_file()
            or not matches[0].resolve().is_relative_to(working.resolve())):
        raise ValueError('missing, ambiguous, or outside-owned generated parser: hlsl_tab.rs')
    return matches[0]


def stable_env(target):
    env = dict(os.environ, CARGO_TARGET_DIR=str(target))
    for key in ('RUSTC_BOOTSTRAP', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS',
                'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTDOCFLAGS', 'CARGO_BUILD_RUSTFLAGS'):
        env.pop(key, None)
    for key in list(env):
        if key.startswith("CARGO_TARGET_") and key.endswith("_RUSTFLAGS"):
            env.pop(key)
    return env


def source_manifest(root):
    return {str(path.relative_to(root)): digest(path)
            for path in sorted(root.rglob('*')) if path.is_file()}


def collect(result, args, source, output, entries, artifacts, run, checkpoint):
    result['all_unit_prototype'] = True
    result['runtime_comparison'] = {'status': 'not_run'}
    result['link'] = {'status': 'not_run', 'reason': 'no compiled all-unit static library yet'}
    env = stable_env(artifacts / 'raw-target')
    command = ['cargo', '+' + args.rust_toolchain, 'build', '--manifest-path', str(artifacts / 'rust-raw/Cargo.toml')]
    result['stable_build'] = run(command, artifacts / 'cargo-stable.log', env=env, timeout=args.build_timeout)
    checkpoint()
    working = artifacts / 'rust-working'
    try:
        generated_parser(output)
        original = source_manifest(output)
        shutil.copytree(output, working)
        generated_parser(working)
        copied = source_manifest(working)
        result['working_source_identity'] = {
            'original_sha256': original, 'working_sha256': copied,
            'equal': original == copied,
        }
        if original != copied:
            raise ValueError('working source manifest differs from emitted source')
    except (ValueError, OSError) as error:
        result['working_copy_failure'] = str(error)
        return
    command = ['cargo', '+' + args.rust_toolchain, 'build', '--manifest-path', str(working / 'Cargo.toml')]
    target = artifacts / 'working-target'
    env = stable_env(target)
    result['working_stable_build'] = run(command, artifacts / 'cargo-working-stable.log', env=env, timeout=args.build_timeout)
    checkpoint()
    for mode, flags in [('bootstrap', None), ('prototype', '-Zcrate-attr=feature(stmt_expr_attributes) -Astatic_mut_refs')]:
        if result.get('working_stable_build', {}).get('exit_code') == 0 or result.get('bootstrap_build', {}).get('exit_code') == 0:
            break
        env['RUSTC_BOOTSTRAP'] = '1'
        if flags:
            env['RUSTFLAGS'] = flags
            result['prototype_flags'] = flags
        result[mode + '_build'] = run(command, artifacts / ('cargo-' + mode + '.log'), env=env, timeout=args.build_timeout)
        checkpoint()
    archives = list((target / 'debug').glob('*.a'))
    if len(archives) != 1:
        result['link']['reason'] = 'all-unit static library unavailable; see compiler failures'
        return
    archive = archives[0]
    result['undefined_symbols'] = run(['nm', '-u', str(archive)], artifacts / 'undefined-symbols.log', timeout=60)
    result['defined_symbols'] = run(['nm', '--defined-only', str(archive)], artifacts / 'defined-symbols.log', timeout=60)
    binary = artifacts / 'shader-driver'
    driver = Path(__file__).with_name('shader_driver.rs')
    link_env = stable_env(artifacts / 'driver-target')
    result['link'] = run(['rustc', '+' + args.rust_toolchain, '--edition', '2024', str(driver),
                          '-o', str(binary), '-L', 'native=' + str(archive.parent),
                          '-l', 'static=' + archive.stem.removeprefix('lib'), '-l', 'm', '-l', 'pthread', '-l', 'dl'],
                         artifacts / 'link.log', env=link_env, timeout=args.build_timeout)
    result['link']['status'] = 'success' if result['link']['exit_code'] == 0 else 'link_failure'
    checkpoint()
    if result['link']['exit_code'] == 0:
        result['linked_dependencies'] = run(['ldd', str(binary)], artifacts / 'linked-dependencies.log', timeout=30)
        from shader_matrix import compare
        result['runtime_comparison'] = compare(binary, args.native_library, artifacts, run)


def verify_cursor_tool(tool):
    from apply_c2rust_patch import verify_tool
    tool = tool.resolve()
    if tool.name != 'c2rust-transpile' or tool.parent.name != 'bin':
        raise ValueError('cursor witness unexpected tool path')
    root = tool.parent.parent
    verify_tool(root)
    reviewed_patch = Path(__file__).parent / 'patches/c2rust-win64-abi.patch'
    if digest(root / 'source-evidence/c2rust-source.patch') != digest(reviewed_patch):
        raise ValueError('cursor witness tool differs from reviewed patch')


def cursor_command_units(entries):
    units = {}
    for entry in entries:
        directory = Path(entry['directory'])
        if not directory.is_absolute():
            raise ValueError('cursor witness command directory must be absolute')
        unit = str((directory / entry['file']).resolve())
        if unit in units:
            raise ValueError('cursor witness duplicate compile database unit')
        units[unit] = entry
    if not units:
        raise ValueError('cursor witness empty compile database')
    return units


def verify_native_cursor_inputs(raw, unit, target, command, *, read_current=True):
    """Revalidate cached native facts, optionally including the current source files."""
    def canonical_path(value):
        return str(Path(value).resolve()) if read_current else str(PurePosixPath(value))
    facts = raw.get('native_inputs')
    required = {'schema', 'main_input', 'cwd', 'adjusted_driver_argv', 'regenerated_cc1_argv',
                'target', 'cpu', 'abi', 'features', 'features_as_written', 'vfs', 'unsupported', 'buffers', 'lexer_events'}
    if not isinstance(facts, dict) or set(facts) != required or facts['schema'] != 2:
        raise ValueError('cursor witness missing native cached input facts')
    if facts['unsupported'] != [] or facts['vfs'] != 'clangtool_empty_overlay_on_real_filesystem':
        raise ValueError('cursor witness unsupported native input mode')
    if (facts['main_input'] != unit or canonical_path(unit) != unit
            or facts['target'] != target or not Path(facts['cwd']).is_absolute()
            or canonical_path(facts['cwd']) != canonical_path(command['directory'])):
        raise ValueError('cursor witness native invocation identity differs')
    for key in ('adjusted_driver_argv', 'regenerated_cc1_argv', 'features', 'features_as_written'):
        if not isinstance(facts[key], list) or any(not isinstance(a, str) for a in facts[key]):
            raise ValueError('cursor witness invalid native invocation arguments')
    if not facts['adjusted_driver_argv'] or not facts['regenerated_cc1_argv'] or not any(
            a == '-resource-dir' or a.startswith('-resource-dir=') for a in facts['adjusted_driver_argv']):
        raise ValueError('cursor witness missing adjusted invocation or resource directory')
    if any(not isinstance(facts[k], str) for k in ('cpu', 'abi')):
        raise ValueError('cursor witness invalid native target options')
    buffers = facts['buffers']
    if not isinstance(buffers, list) or not buffers:
        raise ValueError('cursor witness empty native buffer manifest')
    events = facts['lexer_events']
    if not isinstance(events, list) or not events:
        raise ValueError('cursor witness missing native lexer event ledger')
    entered = set()
    for event in events:
        if (not isinstance(event, dict) or set(event) != {'file_id', 'reason', 'characteristic'}
                or not isinstance(event['file_id'], str) or not event['file_id'].isascii()
                or not event['file_id'].isdigit() or event['reason'] not in ('enter', 'exit')
                or type(event['characteristic']) is not int or event['characteristic'] not in range(5)):
            raise ValueError('cursor witness invalid native lexer event')
        if event['reason'] == 'enter': entered.add(event['file_id'])
    seen, roles, covered = set(), [], set()
    for record in buffers:
        if not isinstance(record, dict) or set(record) != {
                'role', 'identifier', 'physical_path', 'aliases', 'native_device', 'native_file',
                'length', 'bytes_hex', 'sha256', 'lexed', 'lexer_file_ids'}:
            raise ValueError('cursor witness invalid native buffer record')
        role = record['role']
        if role not in ('main', 'file', 'predefines', 'scratch') or type(record['lexed']) is not bool or (
                role != 'scratch' and not record['lexed']):
            raise ValueError('cursor witness native buffer missing lexer coverage')
        if type(record['length']) is not int or record['length'] < 0 or not isinstance(record['bytes_hex'], str):
            raise ValueError('cursor witness invalid native buffer length')
        data = bytes.fromhex(record['bytes_hex'])
        if (data.hex() != record['bytes_hex'] or len(data) != record['length']
                or hashlib.sha256(data).hexdigest() != record['sha256']):
            raise ValueError('cursor witness native cached bytes differ')
        if not isinstance(record['identifier'], str) or any(
                not isinstance(record[k], str) or not record[k].isascii() or not record[k].isdigit()
                for k in ('native_device', 'native_file')):
            raise ValueError('cursor witness invalid native buffer identity')
        ids = record['lexer_file_ids']
        if (not isinstance(ids, list) or any(not isinstance(i, str) for i in ids)
                or len(ids) != len(set(ids)) or set(ids) & covered
                or not set(ids) <= entered or bool(ids) != record['lexed']):
            raise ValueError('cursor witness native lexer/cache coverage differs')
        covered.update(ids)
        aliases = record['aliases']
        if not isinstance(aliases, list) or any(not isinstance(a, str) or not a for a in aliases) or len(aliases) != len(set(aliases)):
            raise ValueError('cursor witness invalid native path aliases')
        physical = record['physical_path']
        if role in ('main', 'file'):
            path = Path(physical)
            if not physical or not path.is_absolute() or canonical_path(physical) != physical:
                raise ValueError('cursor witness invalid physical buffer path')
            paths = [path, *[Path(facts['cwd']) / a for a in aliases]]
            for alias in paths if read_current else ():
                if alias.resolve() != path or alias.read_bytes() != data:
                    raise ValueError('cursor witness current input differs: ' + str(alias))
            identity = ('file', physical)
            if role == 'main' and physical != unit:
                raise ValueError('cursor witness native main buffer differs')
        else:
            if physical or aliases or record['native_device'] != '0' or record['native_file'] != '0':
                raise ValueError('cursor witness nonfile buffer has physical identity')
            if role == 'scratch' and record['identifier'] != '<scratch space>':
                raise ValueError('cursor witness unknown scratch buffer')
            identity = (role, record['identifier'], record['sha256'])
        if identity in seen:
            raise ValueError('cursor witness duplicate native input buffer')
        seen.add(identity)
        roles.append(role)
    if entered != covered:
        raise ValueError('cursor witness unaccounted native lexer event')
    if roles.count('main') != 1 or roles.count('predefines') != 1:
        raise ValueError('cursor witness missing native main or predefines buffer')


def cursor_witness_receipt(tool, database, output):
    """Retain raw paired exports and revalidate native cached input bytes."""
    verify_cursor_tool(tool)
    entries = json.loads(database.read_text())
    inventories = sorted(output.rglob('*.variadic.json'))
    units = cursor_command_units(entries)
    if len(inventories) != len(entries):
        raise ValueError('cursor witness paired unit manifest differs')
    pairs = []
    for inventory in inventories:
        item = json.loads(inventory.read_text())
        unit = item['unit']
        if unit not in units:
            raise ValueError('cursor witness unit outside compile database or duplicate export')
        witness = inventory.with_name(inventory.name.removesuffix('.variadic.json') + '.cursor-witness.json')
        raw = json.loads(witness.read_text())
        if raw['unit'] != unit or raw['target'] != item['target']:
            raise ValueError('cursor witness paired identity differs')
        cbor = inventory.with_name(inventory.name.removesuffix('.variadic.json') + '.cursor.cbor')
        typed = inventory.with_name(inventory.name.removesuffix('.variadic.json') + '.typed-ast.txt')
        entry = units.pop(unit)
        verify_native_cursor_inputs(raw, unit, item['target'], entry)
        pairs.append({'unit': unit, 'target': item['target'], 'compile_command': entry,
                      'files': {str(p.resolve()): digest(p) for p in (inventory, witness, cbor, typed, Path(unit))},
                      'inventory': str(inventory.resolve()), 'witness': str(witness.resolve()),
                      'cbor': str(cbor.resolve()), 'typed_ast': str(typed.resolve())})
    if units:
        raise ValueError('cursor witness missing compile database units')
    return {'schema': 1, 'authorization': 'witness_only', 'pairs': pairs,
            'files': {str(p.resolve()): digest(p) for p in
                      (tool, tool.parent.parent / 'source-receipt.json', database)},
            'database': str(database.resolve()), 'tool': str(tool.resolve()),
            'source_receipt': str((tool.parent.parent / 'source-receipt.json').resolve()),
            'source_input_consistency': 'cached_inputs_revalidated', 'authentic_job_proof': False}


def prove_bound_cursor_witness(receipt, symbol):
    from closed_variadic_plan import PlanError, prove_cursor_witness
    try:
        if receipt.get('schema') != 1 or receipt.get('authorization') != 'witness_only':
            raise ValueError('unsupported cursor binding receipt')
        tool = Path(receipt['tool'])
        verify_cursor_tool(tool)
        if receipt['source_receipt'] != str(tool.parent.parent / 'source-receipt.json'):
            raise ValueError('cursor witness source receipt path differs')
        if set(receipt['files']) != {receipt[k] for k in ('database', 'tool', 'source_receipt')}:
            raise ValueError('cursor witness incomplete tool binding')
        for record in [receipt, *receipt['pairs']]:
            for name, expected in record['files'].items():
                if digest(Path(name)) != expected:
                    raise ValueError('cursor witness binding differs: ' + name)
        entries = json.loads(Path(receipt['database']).read_text())
        units = cursor_command_units(entries)
        if len(receipt['pairs']) != len(units):
            raise ValueError('cursor witness paired unit manifest differs')
        inventories, witnesses = [], []
        for pair in receipt['pairs']:
            unit = pair['unit']
            if unit not in units or units.pop(unit) != pair['compile_command']:
                raise ValueError('cursor witness command binding differs')
            if set(pair['files']) != {pair[k] for k in ('inventory', 'witness', 'cbor', 'typed_ast', 'unit')}:
                raise ValueError('cursor witness incomplete AST binding')
            inventory = json.loads(Path(pair['inventory']).read_text())
            witness = json.loads(Path(pair['witness']).read_text())
            if (inventory['unit'] != unit or witness['unit'] != unit
                    or inventory['target'] != pair['target'] or witness['target'] != pair['target']):
                raise ValueError('cursor witness binding identity differs')
            verify_native_cursor_inputs(witness, unit, pair['target'], pair['compile_command'])
            inventories.append(inventory)
            witnesses.append(witness)
        if units:
            raise ValueError('cursor witness missing compile database units')
        return prove_cursor_witness(inventories, witnesses, symbol)
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise PlanError(str(error)) from error


def collect_cursor_witness(tool, database, output, run, symbol):
    output.mkdir(parents=True, exist_ok=False)
    command = [str(tool), '--fail-on-error', '--disable-rustfmt', '--edition', '2024',
               '--emit-cursor-witness', '--output-dir', str(output / 'raw'), str(database)]
    from closed_variadic_plan import PlanError
    try:
        exported = run(command, output / 'export.log', timeout=1800)
        if exported['exit_code']:
            raise ValueError('paired cursor witness export failed')
        receipt = cursor_witness_receipt(tool, database, output / 'raw')
        receipt['export_command'] = command
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        proof = prove_bound_cursor_witness(receipt, symbol)
    except (OSError, PlanError, KeyError, TypeError, ValueError) as error:
        proof = {'schema': 1, 'authorization': 'witness_only', 'status': 'rejected', 'reason': str(error)}
    (output / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    return proof


def collect_closed_format_facts(tool, database, output, run, syntax):
    """Hosted-only paired emission. Default replay lives in closed_format_facts."""
    from closed_format_facts import FactsError, manifest, replay
    from closed_variadic_plan import build_plan
    output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 1, 'authorization': 'analysis_only', 'status': 'AnalysisFailure',
              'category': 'missing_data', 'lowering': 'not_authorized'}
    try:
        verify_cursor_tool(tool)
        entries = json.loads(database.read_text())
        units = cursor_command_units(entries)
        if sorted(str(Path(c['file']).relative_to(c['directory'])) for c in entries) != list(UNITS):
            raise ValueError('format facts require exact all24 command inventory')
        if len(syntax) != len(entries) or any(record.get('exit_code') != 0 or record.get('timed_out')
                or record.get('command') != entry['arguments'][:-2] + ['-fsyntax-only', entry['file']]
                for entry, record in zip(entries, syntax)):
            raise ValueError('format facts require actual successful all24 native syntax receipts')
        (output / 'native-syntax.json').write_text(json.dumps(syntax, indent=2) + '\n')
        emitted = output / 'emitted'
        command = [str(tool), '--fail-on-error', '--disable-rustfmt', '--edition', '2024',
                   '--emit-build-files', '--emit-variadic-inventory', '--output-dir', str(emitted), str(database)]
        commands = {'off': command, 'on': [*command[:1], '--emit-closed-format-facts', *command[1:]]}
        executions = {}
        for mode in ('off', 'on'):
            executions[mode] = run(commands[mode], output / (mode + '.log'), timeout=1800)
            (output / 'executions.json').write_text(json.dumps(executions, indent=2) + '\n')
            if executions[mode]['exit_code']:
                report['category'] = ('timeout' if executions[mode].get('timed_out') else
                                      'crash' if executions[mode]['exit_code'] < 0 else 'compiler_or_parse_failure')
                raise ValueError('paired compiler extraction failed in ' + mode)
            emitted.rename(output / mode)
        off, on = output / 'off', output / 'on'
        rust_off = {p.relative_to(off).as_posix(): digest(p) for p in off.rglob('*.rs')}
        rust_on = {p.relative_to(on).as_posix(): digest(p) for p in on.rglob('*.rs')}
        if not rust_off or rust_off != rust_on:
            raise ValueError('facts flag changed generated Rust manifest or bytes')
        pairs, inventories, native_files = [], [], {}
        for path in sorted(on.rglob('*.closed-format.json')):
            facts = json.loads(path.read_text())
            unit = facts['unit']
            if unit not in units:
                raise ValueError('duplicate or unexpected format facts unit')
            entry = units.pop(unit)
            verify_native_cursor_inputs(facts, unit, facts['target'], entry)
            for buffer in facts['native_inputs']['buffers']:
                if buffer['physical_path']:
                    native_files[buffer['physical_path']] = digest(Path(buffer['physical_path']))
            prefix = path.name.removesuffix('.closed-format.json')
            inventory = path.with_name(prefix + '.variadic.json')
            inventories.append(json.loads(inventory.read_text()))
            def relative(p):
                return p.relative_to(output).as_posix()
            pairs.append({'unit': unit, 'facts': relative(path), 'inventory': relative(inventory),
                          'cbor': relative(path.with_name(prefix + '.cursor.cbor')),
                          'typed_ast': relative(path.with_name(prefix + '.typed-ast.txt')),
                          'rust_on': relative(path.with_name(prefix + '.rs')),
                          'rust_off': relative(off / path.with_name(prefix + '.rs').relative_to(on))})
            pairs[-1]['files'] = {name: digest(output / value) for name, value in pairs[-1].items() if name != 'unit'}
        if units:
            raise ValueError('missing all24 compiler facts')
        (output / 'compile_commands.json').write_text(json.dumps(entries, indent=2) + '\n')
        (output / 'native-files.json').write_text(json.dumps(native_files, indent=2) + '\n')
        (output / 'inventory-plan.json').write_text(json.dumps(build_plan(inventories, [e['file'] for e in entries], []), indent=2) + '\n')
        tool_root = tool.parent.parent
        retained = output / 'tool'
        retained.mkdir()
        tool_files = {'compiler': tool, 'source_receipt': tool_root / 'source-receipt.json',
                      'patch': tool_root / 'source-evidence/c2rust-source.patch',
                      'source_evidence': tool_root / 'source-evidence/c2rust-patch.json'}
        names = {}
        for label, path in tool_files.items():
            target = retained / path.name
            shutil.copy2(path, target)
            names[label] = target.relative_to(output).as_posix()
        snapshots = output / 'verifier-source'
        snapshots.mkdir()
        verifier_sources = {}
        for name in ('closed_format_facts.py', 'full_compiler.py', 'probe.py'):
            shutil.copy2(Path(__file__).with_name(name), snapshots / name)
            verifier_sources[name] = 'verifier-source/' + name
        packet = {'schema': 1, 'authorization': 'analysis_only', 'units': pairs, 'tool': names,
                  'database': 'compile_commands.json', 'native_files': 'native-files.json', 'verifier_sources': verifier_sources,
                  'inventory_plan': 'inventory-plan.json', 'commands': commands, 'executions': 'executions.json',
                  'native_syntax': 'native-syntax.json', 'authentic_job_proof': False,
                  'paired_rust': {'off': rust_off, 'on': rust_on},
                  'abi_scope': 'Linux_x64', 'stable_output_acceptance': 'unrun'}
        (output / 'packet.json').write_text(json.dumps(packet, indent=2) + '\n')
        (output / 'seal.json').write_text(json.dumps(manifest(output), indent=2) + '\n')
        report = replay(output)
    except (FactsError, OSError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, FactsError):
            report['category'] = 'schema_reference_or_identity_failure'
        elif isinstance(error, json.JSONDecodeError):
            report['category'] = 'parse_failure'
        report['reason'] = str(error)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (output / 'seal.json').write_text(json.dumps(manifest(output), indent=2) + '\n')
    return report


def collect_closed_format_fixture(tool, clang, output, run):
    """Hosted source fixture tests native extraction, including presumed locations."""
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'facts.c'
    source.write_text('''#include <stdarg.h>
#include <stdio.h>
#line 9000 "presumed-format-facts.c"
volatile unsigned counter;
int once(void) { return ++counter; }
int consume(const char *format, va_list args) {
    va_list copy;
    va_copy(copy, args);
    int result = vsnprintf(NULL, 0, format, copy);
    va_end(copy);
    return result;
}
int produce(int choose, const char *format, ...) {
    va_list args;
    va_start(args, format);
    for (unsigned i = 0; i < 2; ++i) {
        if (choose) consume(format, args);
    }
    va_end(args);
    return 0;
}
void caller(int choose) {
    produce(1, choose ? "%*.*g" : "%*.*g", 2, 3, (float)1);
    produce(1, "%d", once());
    produce(1, "%u", counter);
}
''')
    database = output / 'compile_commands.json'
    database.write_text(json.dumps([{'directory': str(output), 'file': str(source),
                                     'arguments': [str(clang), '-std=c11', '-c', str(source)]}]))
    command = [str(tool), '--fail-on-error', '--disable-rustfmt', '--edition', '2024',
               '--emit-variadic-inventory', '--output-dir', str(output / 'emitted'), str(database)]
    for mode in ('off', 'on'):
        argv = command if mode == 'off' else [*command[:1], '--emit-closed-format-facts', *command[1:]]
        result = run(argv, output / (mode + '.log'), timeout=120)
        if result['exit_code']:
            raise ValueError('format fixture extraction failure ' + mode)
        (output / 'emitted').rename(output / mode)
    off = {p.relative_to(output / 'off'): p.read_bytes() for p in (output / 'off').rglob('*.rs')}
    on = {p.relative_to(output / 'on'): p.read_bytes() for p in (output / 'on').rglob('*.rs')}
    if not off or off != on:
        raise ValueError('format fixture flag-only Rust byte equality failed')
    paths = list((output / 'on').rglob('*.closed-format.json'))
    if len(paths) != 1:
        raise ValueError('format fixture raw fact coverage differs')
    facts = json.loads(paths[0].read_text())
    definitions = {key: row for row in facts['definitions'] for key in [row['symbol'].get('linker')]}
    if not {'consume', 'produce'} <= definitions.keys():
        raise ValueError('format fixture cursor consumer omitted')
    kinds = {s['kind'] for s in facts['statements']}
    if not {'branch', 'loop', 'return'} <= kinds:
        raise ValueError('format fixture complete control slice omitted')
    semantics = {e['builtin'][1] for e in facts['cursor_events'] if e['builtin']}
    if not {'va_start', 'va_copy', 'va_end'} <= semantics:
        raise ValueError('format fixture cursor events omitted')
    if not any(e['type'] and e['type'].get('volatile') for e in facts['expressions']):
        raise ValueError('format fixture volatile qualification omitted')
    def conditional(origin):
        return origin['kind'] == 'Conditional' or origin['kind'] == 'Wrapper' and conditional(origin['inner'])
    if not any(conditional(c['format']) for c in facts['calls']):
        raise ValueError('format fixture conditional origin omitted')
    if not any(any(t.get('canonical', {}).get('kind') == 'Double' for t in a['promotion_chain'])
               for c in facts['calls'] for a in c['arguments']):
        raise ValueError('format fixture actual float promotion omitted')
    once_ids = {d['id'] for d in facts['declarations'] if d['symbol'].get('linker') == 'once'}
    if sum(e.get('callee_decl') in once_ids for e in facts['expressions']) != 1:
        raise ValueError('format fixture evaluate-once expression count differs')
    physical = [e['location'] for e in facts['expressions'] if 'spelling' in e['location']]
    if not any(p['presumed']['path'] == 'presumed-format-facts.c'
               and p['spelling'].get('path') == str(source) and p['presumed']['line'] >= 9000 for p in physical):
        raise ValueError('format fixture physical and presumed locations conflated')
    result = {'status': 'compiler_fixture_pass', 'paired_bytes': True,
              'checks': ['literal', 'conditional', 'promotion', 'volatile', 'evaluate_once',
                         'branch', 'loop', 'return', 'start', 'copy', 'end', 'physical_vs_presumed'],
              'lowerability': 'unproved'}
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
