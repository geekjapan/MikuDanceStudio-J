"""Read-only replay of compiler-owned, report-only closed format fact packets."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys

from full_compiler import UNITS, verify_native_cursor_inputs

MAX_FILE = 512 * 1024 * 1024
MAX_PACKET = 4 * 1024 * 1024 * 1024


class FactsError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise FactsError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def loads(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'duplicate JSON key ' + key)
            result[key] = value
        return result
    def invalid_constant(value):
        raise FactsError('nonfinite JSON number ' + value)
    return json.loads(data, object_pairs_hook=unique, parse_constant=invalid_constant)


def key(symbol):
    need(isinstance(symbol, dict), 'missing compiler symbol identity')
    if set(symbol) == {'linker'}:
        need(isinstance(symbol['linker'], str) and symbol['linker'], 'invalid linker identity')
        return ('linker', symbol['linker'])
    need(set(symbol) == {'unit', 'static'} and all(isinstance(v, str) and v for v in symbol.values()),
         'invalid static identity')
    return ('static', symbol['unit'], symbol['static'])


def table(rows, field, label):
    need(isinstance(rows, list), 'missing ' + label)
    result = {}
    for row in rows:
        need(isinstance(row, dict) and type(row.get(field)) is int and row[field] > 0,
             'invalid ' + label + ' ID')
        need(row[field] not in result, 'duplicate ' + label + ' ID')
        result[row[field]] = row
    return result


def safe_file(root, name):
    need(isinstance(name, str) and name == '/'.join(PurePosixPath(name).parts)
         and not name.startswith('/') and '\\' not in name
         and all(p not in ('.', '..', '.git') for p in PurePosixPath(name).parts), 'unsafe packet path')
    path = root
    for part in PurePosixPath(name).parts:
        path /= part
        need(not path.is_symlink(), 'symlink packet member')
    need(path.is_file() and path.stat().st_size <= MAX_FILE, 'missing or excessive packet member ' + name)
    return path


def manifest(root):
    need(root.is_dir() and not root.is_symlink(), 'missing packet directory')
    files = {}
    size = 0
    for path in sorted(root.rglob('*')):
        need(not path.is_symlink(), 'symlink in packet')
        if path.is_dir():
            continue
        name = path.relative_to(root).as_posix()
        if name == 'seal.json':
            continue
        data = safe_file(root, name).read_bytes()
        size += len(data)
        need(size <= MAX_PACKET and len(files) < 4096, 'packet size or file count limit')
        files[name] = {'sha256': sha(data), 'bytes': len(data)}
    return files


def location(row, buffers, buffer_paths):
    need(isinstance(row, dict), 'missing native location')
    if set(row) == {'unproved'}:
        need(isinstance(row['unproved'], str) and row['unproved'], 'empty native origin reason')
        return
    need(set(row) == {'spelling', 'expansion', 'presumed'}, 'invalid native location schema')
    need(isinstance(row['presumed'], dict) and set(row['presumed']) == {'path', 'line'}, 'invalid presumed display')
    for name in ('spelling', 'expansion'):
        span = row[name]
        need(isinstance(span, dict), 'missing physical interval')
        if set(span) == {'unproved'}:
            need(isinstance(span['unproved'], str) and span['unproved'], 'empty physical interval reason')
            continue
        need(set(span) == {'path', 'buffer_sha256', 'begin', 'end', 'bytes_hex'}, 'invalid physical interval schema')
        need(span['path'] in buffer_paths.get(span['buffer_sha256'], set()), 'physical source path differs from native buffer')
        data = buffers.get(span['buffer_sha256'])
        need(data is not None and type(span['begin']) is int and type(span['end']) is int
             and 0 <= span['begin'] <= span['end'] <= len(data), 'native physical interval outside buffer')
        need(data[span['begin']:span['end']].hex() == span['bytes_hex'], 'quoted physical source bytes differ')


def unproved(row):
    need(isinstance(row, dict) and row.get('state') == 'Unproved'
         and isinstance(row.get('reason'), str) and row['reason'],
         'relation requires a concrete Unproved record; no proof is admitted')


def check_unit(facts, inventory, command):
    need(facts.get('schema') == 1 and facts.get('authorization') == 'analysis_only'
         and facts.get('status') == 'CompleteReport' and facts.get('lowering') == 'not_authorized',
         'not a complete report-only compiler record')
    unit = facts['unit']
    need(unit == inventory['unit'] == command['file'] and facts['target'] == inventory['target']
         and facts['target_c_widths_bits'] == inventory['target_c_widths_bits'], 'unit target or width identity differs')
    need(facts['target'] == 'x86_64-pc-linux-gnu'
         and facts['target_c_widths_bits'] == dict(char=8, short=16, int=32, long=64,
              long_long=64, pointer=64, float=32, double=64), 'unretained target ABI')
    verify_native_cursor_inputs(facts, unit, facts['target'], command, read_current=False)
    native = facts['native_inputs']
    need(native.get('schema') == 2 and native.get('main_input') == unit and native.get('target') == facts['target']
         and native.get('unsupported') == [] and native.get('cwd') == command['directory'], 'native invocation mismatch')
    buffers = {}
    paths = {}
    buffer_paths = {}
    for row in native['buffers']:
        data = bytes.fromhex(row['bytes_hex'])
        need(len(data) == row['length'] and sha(data) == row['sha256'], 'cached native buffer identity differs')
        buffer_paths.setdefault(row['sha256'], set()).add(row['physical_path'])
        previous = buffers.setdefault(row['sha256'], data)
        need(previous == data, 'native buffer digest collision')
        if row['physical_path']:
            paths[row['physical_path']] = row['sha256']
    need(unit in paths, 'native main input missing')
    declarations = table(facts['declarations'], 'id', 'declaration')
    need(facts['declarations'] == inventory['declarations'], 'compiler declaration census differs from inventory')
    function_edges = table(facts['function_edges'], 'declaration', 'function parameter edges')
    for i, edge in function_edges.items():
        need(i in declarations and edge['fixed_count'] == len(edge['parameters'])
             and len(set(edge['parameters'])) == len(edge['parameters']), 'function parameter reference coverage differs')
        position = edge['format_position']
        need(position is None and edge['format_parameter'] is None or type(position) is int
             and 0 <= position < len(edge['parameters']) and edge['format_parameter'] == edge['parameters'][position], 'function format parameter edge differs')
    raw_calls = table(inventory['calls'], 'id', 'inventory call')
    calls = table(facts['calls'], 'id', 'format call')
    definitions = table(facts['definitions'], 'declaration', 'definition')
    unclassified = table(facts['unclassified_definitions'], 'declaration', 'unclassified definition')
    expressions = table(facts['expressions'], 'id', 'expression')
    statements = table(facts['statements'], 'id', 'statement')
    variables = table(facts['variables'], 'id', 'variable')
    types = table(facts['types'], 'type_id', 'type')
    def type_references(value):
        if isinstance(value, dict):
            if 'type_id' in value and not (value['type_id'] is None and value.get('type_unproved')):
                need(value['type_id'] in types, 'qualified type reference missing')
            for child in value.values():
                type_references(child)
        elif isinstance(value, list):
            for child in value:
                type_references(child)
    for row in [*expressions.values(), *variables.values(), *types.values()]:
        type_references(row)
    unsupported = table(facts['unsupported_expressions'], 'expression', 'unsupported expression')
    need(type(facts['unsupported_expression_count']) is int and facts['unsupported_expression_count'] == len(unsupported),
         'unsupported expression census coverage differs')
    for i, row in unsupported.items():
        need(type(row['within_slice']) is bool and row['within_slice'] == (i in expressions)
             and isinstance(row['native_shape'], str) and row['native_shape'], 'unsupported relevance or shape reference differs')
        unproved(row['relevance'])
        location(row['location'], buffers, buffer_paths)
        if row['within_slice']:
            need(expressions[i]['kind'] == 'unsupported' and expressions[i]['native_shape'] == row['native_shape'], 'selected unsupported shape differs')
    need({i for i, e in expressions.items() if e['kind'] == 'unsupported'} <= unsupported.keys(), 'selected unsupported expression omitted')
    events = table(facts['cursor_events'], 'expression', 'cursor event')
    expected_events = {i: e for i, e in expressions.items() if e['kind'] == 'call'}
    need(events.keys() == expected_events.keys(), 'cursor start copy forward format end coverage differs')
    for i, event in events.items():
        unproved(event['relation'])
        expr = expected_events[i]
        need(event['builtin'] == expr['builtin'] and event['callee_declaration'] == expr['callee_decl']
             and event['operands'] == expr['arguments'], 'cursor event operands or builtin edge differs')
    for row in [*definitions.values(), *unclassified.values()]:
        decl = declarations.get(row['declaration'])
        need(decl is not None and decl['definition'] and decl['symbol'] == row['symbol'], 'definition declaration edge differs')
        location(row['location'], buffers, buffer_paths)
    for row in unclassified.values():
        need(row['signature'] == declarations[row['declaration']]['signature'] and row['state'] == 'Unproved'
             and row['reason'], 'unclassified native signature facts lost')
    for row in definitions.values():
        unproved(row['generated_origin'])
        unproved(row['control_effect_lifetime'])
        need(row['body'] in statements and set(row['parameters']) <= variables.keys(), 'definition body or parameter missing')
        need(row['va_parameters'] == declarations[row['declaration']]['va_parameters'], 'consumer parameter edge differs')
    for row in calls.values():
        location(row['native_location'], buffers, buffer_paths)
    for row in [*expressions.values(), *statements.values()]:
        location(row['location'], buffers, buffer_paths)
    for row in calls.values():
        raw = raw_calls.get(row['id'])
        need(raw is not None and all(row.get(k) == v for k, v in raw.items()), 'call inventory facts changed')
        need(row['callee_declaration'] in declarations
             and declarations[row['callee_declaration']]['symbol'] == row['callee'], 'callee declaration edge differs')
        need(row['id'] in expressions, 'call expression missing')
        need(type(row['fixed_count']) is int and 0 <= row['fixed_count'] <= len(row['arguments']), 'fixed argument coverage differs')
        need(row['callee_declaration'] in function_edges, 'call function parameter edges absent')
        edge = function_edges[row['callee_declaration']]
        need(row['fixed_count'] == edge['fixed_count'] and row['format_position'] == edge['format_position'], 'call format or fixed parameter position differs')
        position = row['format_position']
        need(position is None or type(position) is int and 0 <= position < row['fixed_count'], 'format position outside fixed arguments')
        if position is not None:
            need(row['format'].get('expression') == row['arguments'][position]['id'], 'format position expression edge differs')
        unproved(row['generated_origin'])
        unproved(row['evaluation'])
        unproved(row['format_position_relation'])
        for argument in row['arguments']:
            expr = expressions.get(argument['id'])
            need(expr is not None and expr['promotion_chain'] == argument['promotion_chain'], 'promotion chain reference differs')
    for row in expressions.values():
        unproved(row['effect_relation'])
        need(type(row['edge_count']) is int and row['edge_count'] == len(row['children']), 'expression edge coverage differs')
        need(set(row['children']) <= expressions.keys(), 'expression child missing')
        if row.get('kind') == 'reference':
            need(row['decl'] in variables or row['decl'] in declarations, 'expression declaration missing')
        if row.get('kind') == 'call':
            need(all(a['id'] in expressions for a in row['arguments']), 'body call argument missing')
    for row in statements.values():
        need(type(row['edge_count']) is int and row['edge_count'] == len(row['children']), 'control statement edge coverage differs')
        need(row['kind'] in ('compound', 'expression', 'declarations', 'return', 'branch', 'loop',
             'break', 'continue', 'goto', 'empty', 'unsupported'), 'invalid statement classification')
        for edge in row['children']:
            target = {'statement': statements, 'expression': expressions, 'declaration': variables}.get(edge['kind'])
            need(target is not None and edge['id'] in target, 'structural control edge missing')
        need(row['flow']['state'] == 'Unproved' and row['flow']['reason'], 'structural order relabeled execution proof')
    reachable = set()
    pending = [row['body'] for row in definitions.values()]
    pending.extend(row['statement_body'] for row in expressions.values() if row.get('statement_body') is not None)
    need(set(pending) <= statements.keys(), 'statement expression body missing')
    while pending:
        node = pending.pop()
        need(node not in reachable, 'cyclic or shared statement ownership')
        reachable.add(node)
        pending.extend(e['id'] for e in statements[node]['children'] if e['kind'] == 'statement')
    need(reachable == statements.keys(), 'missing branch loop return or complete body edge')
    def consumption(row, literal):
        need(isinstance(row, dict) and row.get('state') in ('Parsed', 'Unproved'), 'missing compiler format consumption')
        conversions = row.get('conversions', []) if row['state'] == 'Parsed' else row.get('prefix', [])
        if row['state'] == 'Unproved':
            need(isinstance(row.get('reason'), str) and row['reason'], 'unsupported syntax lost its reason')
        else:
            unproved(row['type_compatibility'])
        slots, previous = [], 0
        for conversion in conversions:
            begin, end = conversion['begin'], conversion['end']
            need(type(begin) is int and type(end) is int and previous <= begin < end <= len(literal)
                 and literal[begin] == 37 and literal[end - 1] == conversion['conversion'], 'conversion source interval differs')
            length = conversion['length']
            need(literal[end - 1 - len(length):end - 1] == length, 'conversion length bytes differ')
            for argument in conversion['arguments']:
                need(argument['role'] in ('width', 'precision', 'value'), 'invalid consumption role')
                slots.append(argument['slot'])
            previous = end
        need(slots == list(range(len(slots))), 'format argument consumption has missing or duplicate slots')
        if row['state'] == 'Parsed':
            need(type(row['arguments']) is int and row['arguments'] == len(slots), 'format consumption arity differs')
    def format_refs(row):
        need(isinstance(row, dict) and row.get('kind') in ('Wrapper', 'Literal', 'Conditional', 'Declaration', 'Unproved'), 'invalid format origin')
        if 'expression' in row:
            need(row['expression'] in expressions, 'format expression missing')
        if row['kind'] == 'Wrapper':
            need(expressions[row['expression']]['children'] == [row['inner']['expression']], 'format wrapper edge differs')
            format_refs(row['inner'])
        elif row['kind'] == 'Literal':
            need(expressions[row['expression']].get('literal', {}).get('bytes') == row['bytes'], 'format literal bytes differ')
            consumption(row['consumption'], row['bytes'])
        elif row['kind'] == 'Conditional':
            need(expressions[row['expression']]['children'] == [row['condition'], row['true']['expression'], row['false']['expression']], 'conditional format edges differ')
            format_refs(row['true']); format_refs(row['false'])
        elif row['kind'] == 'Declaration':
            need(expressions[row['expression']].get('decl') == row['declaration'], 'format declaration edge differs')
            unproved(row['relation'])
        else:
            need(row.get('reason'), 'missing runtime format reason')
    for row in calls.values():
        format_refs(row['format'])
    return definitions, calls, unclassified


def replay(root):
    need(not root.is_symlink(), 'symlink packet directory')
    root = root.absolute()
    before = manifest(root)
    need(loads(safe_file(root, 'seal.json').read_bytes()) == before, 'packet seal differs')
    packet = loads(safe_file(root, 'packet.json').read_bytes())
    need(packet.get('schema') == 1 and packet.get('authorization') == 'analysis_only', 'invalid packet schema')
    def read(name):
        return loads(safe_file(root, name).read_bytes())
    need(set(packet['verifier_sources']) == {'closed_format_facts.py', 'full_compiler.py', 'probe.py'}, 'incomplete verifier source identity')
    for name, snapshot in packet['verifier_sources'].items():
        need(safe_file(root, snapshot).read_bytes() == Path(__file__).with_name(name).read_bytes(), 'verifier source identity differs')
    commands = read(packet['database'])
    need(len(commands) == len(UNITS) and len({c['file'] for c in commands}) == len(UNITS), 'missing extra or duplicate TU commands')
    need(sorted(str(Path(c['file']).relative_to(c['directory'])) for c in commands) == list(UNITS), 'exact all24 units differ')
    command_map = {c['file']: c for c in commands}
    syntax = read(packet['native_syntax'])
    need(len(syntax) == len(commands), 'native syntax receipt coverage differs')
    for command, record in zip(commands, syntax):
        need(record.get('exit_code') == 0 and not record.get('timed_out') and record.get('command') ==
             command['arguments'][:-2] + ['-fsyntax-only', command['file']], 'native syntax receipt failed or differs')
    need(len(packet['units']) == len(command_map) and {u['unit'] for u in packet['units']} == command_map.keys(), 'fact TU coverage differs')
    expected_tools = {'compiler', 'source_receipt', 'patch', 'source_evidence'}
    need(set(packet['tool']) == expected_tools, 'incomplete compiler tool binding')
    for name in packet['tool'].values():
        safe_file(root, name)
    receipt = read(packet['tool']['source_receipt'])
    evidence = read(packet['tool']['source_evidence'])
    need(sha(safe_file(root, packet['tool']['patch']).read_bytes()) == receipt['patch_sha256'] == evidence['patch_sha256']
         and receipt['source_receipt_sha256'] == sha(safe_file(root, packet['tool']['source_evidence']).read_bytes())
         and receipt['binary_sha256']['c2rust-transpile'] == sha(safe_file(root, packet['tool']['compiler']).read_bytes()), 'compiler source patch or executable identity differs')
    native_files = read(packet['native_files'])
    observed_native_files = set()
    symbols, incoming, extras = {}, {}, {}
    need(len({u['rust_on'] for u in packet['units']}) == len(commands), 'generated TU module identity merged')
    for pair in packet['units']:
        required = {'facts', 'inventory', 'cbor', 'typed_ast', 'rust_off', 'rust_on'}
        need(set(pair) == required | {'unit', 'files'} and set(pair['files']) == required, 'incomplete paired AST binding')
        stem = Path(pair['unit']).stem.replace('.', '_')
        suffixes = {'facts': '.closed-format.json', 'inventory': '.variadic.json', 'cbor': '.cursor.cbor',
                    'typed_ast': '.typed-ast.txt', 'rust_on': '.rs', 'rust_off': '.rs'}
        for field, suffix in suffixes.items():
            need(Path(pair[field]).name == stem + suffix, 'generated module or paired AST unit origin differs')
        for field in required:
            need(sha(safe_file(root, pair[field]).read_bytes()) == pair['files'][field], 'paired raw AST or emission digest differs')
        facts, inventory = read(pair['facts']), read(pair['inventory'])
        need(pair['unit'] == facts['unit'], 'fact pair unit differs')
        for field in ('cbor', 'typed_ast', 'rust_off', 'rust_on'):
            safe_file(root, pair[field])
        need(safe_file(root, pair['rust_off']).read_bytes() == safe_file(root, pair['rust_on']).read_bytes(), 'flag-only generated Rust bytes differ')
        for buffer in facts['native_inputs']['buffers']:
            if buffer['physical_path']:
                observed_native_files.add(buffer['physical_path'])
                need(native_files.get(buffer['physical_path']) == buffer['sha256'], 'native source or header manifest differs')
        definitions, calls, unclassified = check_unit(facts, inventory, command_map[pair['unit']])
        for row in definitions.values():
            symbol = key(row['symbol'])
            need(symbol not in symbols, 'duplicate compiler definition symbol')
            symbols[symbol] = (pair['unit'], row)
        for row in calls.values():
            call_key = (pair['unit'], row['id'])
            need(call_key not in incoming, 'cross-TU call identity merged or duplicated')
            incoming[call_key] = row
        for row in unclassified.values():
            extras[(pair['unit'], row['declaration'])] = row
    need(observed_native_files == native_files.keys(), 'native source or header manifest coverage differs')
    plan = read(packet['inventory_plan'])
    expected = {tuple(s['symbol']): s for s in plan['symbols']}
    need(len(expected) == len(plan['symbols']) == 40 and symbols.keys() == expected.keys(), 'missing extra or duplicate closed symbol or consumer')
    need(plan['units'] == sorted(command_map), 'independent inventory TU identity differs')
    for symbol, (_, row) in symbols.items():
        need(type(row['variadic']) is bool and row['variadic'] == expected[symbol]['signature']['variadic'], 'symbol variadic or cursor classification differs')
    expected_calls = {(c['unit'], c['expression']): symbol for symbol, row in expected.items() for c in row['calls']}
    need(len(expected_calls) == sum(len(row['calls']) for row in expected.values()), 'duplicate independent inventory call identity')
    selected = {k: key(v['callee']) for k, v in incoming.items() if key(v['callee']) in expected}
    need(selected == expected_calls and len(selected) == 4865, 'incoming call coverage differs from independent inventory')
    expected_extras = {(r['unit'], r['id']) for r in plan['unclassified_definitions']}
    need(extras.keys() == expected_extras and len(extras) == 5, 'five attributed blob signatures missing or extra')
    need(sum(bool(row[1]['variadic']) for row in symbols.values()) == 33, 'variadic definition census differs')
    need(sum(not row[1]['variadic'] for row in symbols.values()) == 7, 'cursor consumer census differs')
    need(sum(symbols[v][1]['variadic'] for v in selected.values()) == 4830, 'variadic call census differs')
    actual_manifests = {mode: {p.relative_to(root / mode).as_posix(): sha(p.read_bytes())
                              for p in (root / mode).rglob('*.rs')} for mode in ('off', 'on')}
    need(actual_manifests == packet['paired_rust'] and actual_manifests['off'] == actual_manifests['on']
         and len(actual_manifests['off']) >= len(UNITS), 'complete paired Rust module manifests differ')
    executions = read(packet['executions'])
    need(set(executions) == {'off', 'on'}, 'paired execution receipt missing')
    for mode, record in executions.items():
        need(record.get('command') == packet['commands'][mode] and record.get('exit_code') == 0
             and record.get('process_exit_code') == 0 and not record.get('timed_out'), 'paired compiler execution failed or differs')
    off, on = packet['commands']['off'], packet['commands']['on']
    need('--emit-closed-format-facts' not in off and on.count('--emit-closed-format-facts') == 1
         and [a for a in on if a != '--emit-closed-format-facts'] == off, 'paired command changes more than facts flag')
    need(manifest(root) == before, 'replay changed packet')
    return {'schema': 1, 'status': 'complete_coverage', 'authorization': 'analysis_only',
            'units': 24, 'symbols': 40, 'incoming_calls': 4865, 'unclassified': 5,
            'lowerability': 'blocked', 'whole_library_stable': 'unaccepted', 'four_host_ABI': 'unrun',
            'public_callback': 'unproved', 'corpus_48_positive_2_negative': 'unaccepted',
            'CMP': 'unresolved', 'scan': 'unaccepted', 'reflection': 'unaccepted',
            'product_integration': 'unaccepted', 'native_source_removal': 'not_authorized',
            'authentic_job_proof': False}


def guard(event, args):
    if event == 'open':
        mode, flags = args[1] or '', args[2] or 0
        need(not any(c in mode for c in 'wax+') and not flags &
             (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND), 'read-only replay write denied')
    need(event not in ('os.mkdir', 'os.remove', 'os.rename', 'os.rmdir', 'os.chmod', 'os.link',
         'os.symlink', 'os.truncate', 'os.utime', 'os.system', 'os.posix_spawn', 'os.fork', 'os.forkpty', 'os.exec')
         and not event.startswith(('subprocess.', 'socket.')), 'read-only replay effect denied ' + event)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, required=True)
    args = parser.parse_args()
    sys.addaudithook(guard)
    print(json.dumps(replay(args.replay), sort_keys=True))


if __name__ == '__main__':
    main()
