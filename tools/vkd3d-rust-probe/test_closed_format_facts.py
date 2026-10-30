import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import closed_format_facts as F
from full_compiler import UNITS


def constructor_fixture_fields(graph):
    mapping = {'pointer': 'Pointer', 'function': 'Function', 'array': 'ConstantArray', 'struct': 'Struct',
               'union': 'Union', 'enum': 'Enum', 'typedef': 'Typedef', 'typeof': 'TypeOf', 'paren': 'Paren',
               'elaborated': 'Elaborated', 'decayed': 'Decayed', 'auto': 'Auto', 'attributed': 'Attributed',
               'builtin_function': 'BuiltinFn'}
    for row in graph['types']:
        row.setdefault('native_shape', mapping.get(row.get('kind'), row.get('kind')))
        shape = row['native_shape']
        if shape == 'Attributed': row.setdefault('counted_by', None)
        if shape in ('Reference', 'BlockPointer', 'Vector', 'Atomic', 'Complex', 'TypeOfExpr', 'VariableArray',
                     'Attributed', 'LongDouble', 'BFloat16'):
            row.setdefault('unproved', 'missing or unsupported required type')
        elif shape == 'BuiltinFn': row.setdefault('unproved', 'BuiltinFn requires a native endpoint relation')
        elif shape in ('ConstantArray', 'IncompleteArray') and 'element' not in row:
            row.setdefault('unproved', 'missing or inconsistent qualified array element')
    for row in graph['declarations']:
        row.setdefault('diagnostic_location', None)
        if row['kind'] == 'variable':
            for key, value in dict(initializer=None, name='', local=False, owning_function=None, static=False,
                                   thread=False, externally_visible=False, native_va_list=None).items():
                row.setdefault(key, value)
            row.setdefault('type', {'canonical': {'kind': 'Int'}, 'const': False, 'volatile': False, 'restrict': False})
        elif row['kind'] == 'field':
            row.setdefault('owners', [owner['identity'] for owner in graph['declarations']
                                     if owner['kind'] in ('struct', 'union') and row['id'] in (owner['fields'] or [])])
            row.setdefault('type', {'canonical': {'pointer': {'canonical': {'native_va_list_record': 800},
                           'const': False, 'volatile': False, 'restrict': False}}, 'const': False, 'volatile': False, 'restrict': False})
    for row in graph['expressions']:
        shape, children = row['native_shape'], row['children']
        if shape == 'Binary':
            row.setdefault('operator', 'Add')
            row.setdefault('computation_qualified_types', [None, None])
            row.setdefault('computation_types', [None, None])
        elif shape == 'UnaryType': row.setdefault('operator', 'SizeOf')
        if shape in ('Unary', 'ConstantExpr', 'ImplicitCast', 'ExplicitCast', 'Paren', 'CompoundLiteral',
                     'ImaginaryLiteral', 'Predefined', 'VAArg', 'Member'):
            operands = {'child': children[0]}
        elif shape in ('Binary', 'ArraySubscript', 'BinaryConditional'):
            operands = dict(zip(('left', 'right'), children))
        elif shape in ('Conditional', 'Choose'):
            operands = dict(zip(('condition', 'then', 'else'), children))
        elif shape == 'Call':
            operands = dict(callee=children[0], arguments=children[1:])
        elif shape == 'Statements':
            operands = dict(body=row['statement_body'])
        else:
            operands = row.get('operands', {})
        row['operands'] = operands


def coherent_graph_fixture(facts, inventory):
    import copy
    q = lambda ident: dict(type_id=ident, const=False, volatile=False, restrict=False)
    edge = F.ReportGraph.edge
    types = {1: dict(type_id=1, kind='Int'), 4: dict(type_id=4, kind='UInt')}
    variables = {v['id']: copy.deepcopy(v) for v in facts['variables']}
    expressions = {e['id']: copy.deepcopy(e) for e in facts['expressions']}
    statements = {s['id']: copy.deepcopy(s) for s in facts['statements']}
    for row in inventory['declarations']:
        ident = row['id']
        type_id = 200000 + ident
        params = variables.get(ident, {}).get('parameters', [])
        if ident >= 100:
            types[type_id] = dict(type_id=type_id, kind='attributed', original=q(1))
            body = 91000 + ident
            statements[body] = dict(id=body, kind='empty', native_shape='Empty', children=[], edge_count=0,
                                    label_target=None, location=facts['unclassified_definitions'][0]['location'],
                                    flow={'state': 'Unproved', 'reason': 'structural edges only; execution and cursor state relations not established'})
            variables[ident] = dict(id=ident, kind='function', builtin=None, parameters=[], parameter_owners=[])
        else:
            types[type_id] = dict(type_id=type_id, kind='function', return_=q(1), parameters=[q(1) for _ in params],
                                  variadic=ident <= 33, noreturn=False, prototype=True, abi='C')
            types[type_id]['return'] = types[type_id].pop('return_')
            body = next((d['body'] for d in facts['definitions'] if d['declaration'] == ident), None)
        raw = variables[ident]
        raw.update(type_id=type_id, qualified_type=q(type_id), symbol=row['symbol'], body=body,
                   aliases=[], va_parameters=row['va_parameters'], diagnostic_location=row.get('location'))
        row['location'] = raw['diagnostic_location']
        row['aliases'] = []
    for ident, row in variables.items():
        if row['kind'] == 'variable':
            row.update(qualified_type=q(row['type_id']), diagnostic_location=None, va_list=ident >= 600)
    for row in expressions.values():
        if row['kind'] == 'reference' and row['decl'] in variables and variables[row['decl']]['kind'] == 'function':
            row['type_id'] = variables[row['decl']]['type_id']
        row['qualified_type'] = q(row['type_id'])
        row['diagnostic_location'] = 'display'
        row['native_shape'] = {'literal': 'Literal', 'reference': 'DeclRef', 'call': 'Call'}[row['kind']]
        row['statement_body'] = None
        row['va_list'] = False
        row['df_children'] = [edge('expression', i) for i in row['children']]
        row['structural_children'] = copy.deepcopy(row['df_children'])
        for name in ('type', 'promotion_chain', 'arguments', 'callee_decl', 'callee_reference', 'callee_expression', 'builtin'):
            row.pop(name, None)
    for call in inventory['calls']:
        for arg in call['arguments']:
            expressions[arg['id']]['va_list'] = arg['va_list']
    unsupported = facts['unsupported_expressions'][0]
    expressions[unsupported['expression']] = dict(id=unsupported['expression'], kind='unsupported', native_shape='ConstantExpr',
        qualified_type=q(1), type_id=1, location=unsupported['location'], diagnostic_location=None,
        children=[1001], edge_count=1, df_children=[edge('expression', 1001)], structural_children=[edge('expression', 1001)], statement_body=None, va_list=False,
        effect_relation={'state': 'Unproved', 'reason': 'synthetic unsupported'})
    for row in variables.values():
        if row['kind'] == 'function':
            children = [edge('type', row['type_id'])] + [edge('declaration', p) for p in row['parameters']]
            if row['body'] is not None:
                children += [edge('statement', row['body'])]
        else:
            children = [edge('type', row['type_id'])]
        row['df_children'] = children
        row['structural_children'] = copy.deepcopy(children)
    for row in statements.values():
        row['label_target'] = None
        row['df_children'] = [{k: e[k] for k in ('kind', 'id')} for e in row['children']]
        row['structural_children'] = copy.deepcopy(row['df_children'])
    for row in types.values():
        children = ([edge('type', 1)] * (1 + len(row['parameters']))) if row['kind'] == 'function' else ([edge('type', 1)] if row['kind'] == 'attributed' else [])
        row['df_children'] = children
        row['structural_children'] = copy.deepcopy(children)
    qualified = [dict(source=q(ident), path=[ident], **({'unproved': 'attributed type facts'} if row['kind'] == 'attributed' else {'normalized': q(ident)}))
                 for ident, row in types.items()]
    facts['graph'] = dict(expressions=list(expressions.values()), statements=list(statements.values()),
                          declarations=list(variables.values()), types=list(types.values()), qualified_types=qualified,
                          declaration_order=list(variables))
    facts['schema'] = 2
    constructor_fixture_fields(facts['graph'])
    graph = F.ReportGraph(facts)
    inventory.clear()
    inventory.update(graph.inventory(facts))
    facts['declarations'] = copy.deepcopy(inventory['declarations'])
    facts['expressions'] = [graph.expression(e['id']) for e in facts['expressions']]
    facts['variables'] = [copy.deepcopy(variables[v['id']]) for v in facts['variables']]
    facts['statements'] = [copy.deepcopy(statements[s['id']]) for s in facts['statements']]
    selected_types = {v['type_id'] for v in facts['variables'] if 'type_id' in v} | {1}
    facts['types'] = [copy.deepcopy(t) for i, t in types.items() if i in selected_types]
    raw_calls = {c['id']: c for c in inventory['calls']}
    for call in facts['calls']:
        call.update(copy.deepcopy(raw_calls[call['id']]))
    for event in facts['cursor_events']:
        expr = graph.expression(event['expression'])
        event['operands'] = expr['arguments']
    for definition in facts['definitions']:
        definition['signature'] = graph.type_view(variables[definition['declaration']]['qualified_type'], True)
    for unknown in facts['unclassified_definitions']:
        unknown['signature'] = graph.type_view(variables[unknown['declaration']]['qualified_type'])
    facts['unsupported_expressions'][0]['native_shape'] = 'ConstantExpr'
    facts['unsupported_expressions'][0]['type'] = graph.type_view(q(1), True)
    facts['unsupported_expressions'][0]['relevance'] = {'state': 'Unproved', 'reason': 'outside selected slice; influence on formatting, control and effects is not established'}


def synthetic_packet_fixture(root):
    def write(name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    typ = {'canonical': {'kind': 'Int'}, 'const': False, 'volatile': False, 'restrict': False}
    symbol = lambda i: {'linker': 'function_' + str(i)}
    native_root = root.parent / 'native'
    commands = [{'file': str(native_root / unit), 'directory': str(native_root),
                 'arguments': ['/usr/lib/llvm-18/bin/clang', '-DHAVE_CONFIG_H', '-I' + str(native_root / 'include'),
                               '-c', str(native_root / unit)]} for unit in UNITS]
    buffers = b'"%d"'
    checksum = F.sha(buffers)
    position = dict(path='', buffer_sha256=checksum, begin=0, end=4, bytes_hex=buffers.hex())
    location = {'spelling': position, 'expansion': position, 'presumed': {'path': 'display.c', 'line': 9000}}
    unresolved = {'state': 'Unproved', 'reason': 'synthetic transport fixture'}
    plan = {'units': sorted(c['file'] for c in commands), 'symbols': [{'symbol': ['linker', 'function_' + str(i)], 'signature': {'variadic': i < 33}, 'calls': []} for i in range(40)],
            'unclassified_definitions': []}
    units = []
    calls_per_unit = [[] for _ in UNITS]
    next_ids = [1000 for _ in UNITS]
    n = 0
    for target in range(40):
        count = (4798 if target == 0 else 1) if target < 33 else (29 if target == 33 else 1)
        for _ in range(count):
            index = n % 24
            call_id = next_ids[index]
            next_ids[index] += 10
            args = [{'id': call_id + 1, 'type': typ, 'promotion_chain': [typ], 'va_list': False},
                    {'id': call_id + 2, 'type': typ, 'promotion_chain': [typ], 'va_list': target >= 33}]
            row = {'id': call_id, 'owner': None, 'location': 'display', 'callee': symbol(target), 'arguments': args}
            calls_per_unit[index].append((row, target))
            plan['symbols'][target]['calls'].append({'unit': commands[index]['file'], 'expression': call_id})
            n += 1
    native_files = {}
    header = native_root / 'include/fixture.h'
    header.parent.mkdir(parents=True)
    header.write_bytes(buffers)
    native_files[str(header)] = checksum
    for index, command in enumerate(commands):
        unit = command['file']
        Path(unit).parent.mkdir(parents=True, exist_ok=True)
        Path(unit).write_bytes(buffers)
        position['path'] = unit
        native_files[unit] = checksum
        rows, definitions, variables, statements, expressions, events = [], [], [], [], [], []
        for i in range(40):
            parameters = [500 + i] + ([600 + i] if i >= 33 else [])
            rows.append({'id': i + 1, 'symbol': symbol(i), 'definition': i % 24 == index,
                         'va_parameters': parameters[1:], 'signature': dict(typ, canonical={'variadic': i < 33})})
            if i % 24 == index:
                definitions.append({'declaration': i + 1, 'symbol': symbol(i), 'variadic': i < 33,
                                    'parameters': parameters, 'va_parameters': parameters[1:], 'body': 90000 + i,
                                    'location': location, 'generated_origin': unresolved, 'control_effect_lifetime': unresolved})
                branch, condition, value = 800000 + i * 10, 700000 + i * 10, 700001 + i * 10
                statements.extend([
                    {'id': 90000 + i, 'kind': 'compound', 'children': [{'kind': 'statement', 'id': branch}], 'location': location, 'flow': unresolved},
                    {'id': branch, 'kind': 'branch', 'children': [{'kind': 'expression', 'id': condition}, {'kind': 'statement', 'id': branch + 1}], 'location': location, 'flow': unresolved},
                    {'id': branch + 1, 'kind': 'loop', 'children': [{'kind': 'expression', 'id': condition}, {'kind': 'statement', 'id': branch + 2}], 'location': location, 'flow': unresolved},
                    {'id': branch + 2, 'kind': 'return', 'children': [{'kind': 'expression', 'id': value}], 'location': location, 'flow': unresolved}])
                expressions.extend({'id': e, 'kind': 'literal', 'literal': {'integer': 1}, 'children': [],
                                    'location': location, 'type_id': 1, 'promotion_chain': [typ]} for e in (condition, value))

        for i in range(40):
            variables.extend({'id': p, 'kind': 'variable', 'type_id': 1, 'parameter_owners': [i + 1]}
                             for p in [500 + i] + ([600 + i] if i >= 33 else []))
        variables.extend({'id': i + 1, 'kind': 'function', 'builtin': None, 'type_id': 1, 'parameter_owners': [],
                          'parameters': [500 + i] + ([600 + i] if i >= 33 else [])} for i in range(40))
        extra = []
        if index == 0:
            for i in range(5):
                rows.append({'id': 100 + i, 'symbol': {'linker': 'blob_' + str(i)}, 'definition': True,
                             'va_parameters': [], 'signature': {'unproved': 'attributed'}})
                extra.append({'declaration': 100 + i, 'symbol': {'linker': 'blob_' + str(i)}, 'location': location,
                              'signature': {'unproved': 'attributed'}, 'state': 'Unproved', 'reason': 'attributed type facts'})
                plan['unclassified_definitions'].append({'unit': unit, 'id': 100 + i})
        calls = []
        raw_calls = []
        for raw, target in calls_per_unit[index]:
            raw_calls.append(raw)
            row = dict(raw, callee_declaration=target + 1, fixed_count=1 if target < 33 else 2,
                       format_position=0, format={'kind': 'Literal', 'expression': raw['id'] + 1, 'bytes': [37, 100],
                           'consumption': {'state': 'Parsed', 'arguments': 1, 'conversions': [{'begin': 0, 'end': 2, 'length': [], 'conversion': 100, 'arguments': [{'slot': 0, 'role': 'value'}]}], 'type_compatibility': unresolved}},
                       generated_origin=unresolved, evaluation=unresolved, format_position_relation=unresolved)
            row['native_location'] = location
            calls.append(row)
            args = raw['arguments']
            expressions.extend([
                {'id': raw['id'], 'kind': 'call', 'children': [raw['id'] + 3, raw['id'] + 1, raw['id'] + 2],
                 'location': location, 'type_id': 1, 'promotion_chain': [typ], 'arguments': args,
                 'callee_decl': target + 1, 'builtin': None, 'callee_expression': raw['id'] + 3, 'callee_reference': raw['id'] + 3},
                {'id': raw['id'] + 1, 'kind': 'literal', 'literal': {'bytes': [37, 100], 'width': 1},
                 'children': [], 'location': location, 'type_id': 1, 'promotion_chain': [typ]},
                {'id': raw['id'] + 2, 'kind': 'literal', 'literal': {'integer': 1},
                 'children': [], 'location': location, 'type_id': 1, 'promotion_chain': [typ]}])
            expressions.append({'id': raw['id'] + 3, 'kind': 'reference', 'decl': target + 1,
                                'children': [], 'location': location, 'type_id': 1, 'promotion_chain': [typ]})
            events.append({'expression': raw['id'], 'builtin': None, 'callee_declaration': target + 1, 'operands': args, 'relation': unresolved})
        native = {'schema': 2, 'main_input': unit, 'cwd': str(native_root), 'adjusted_driver_argv': command['arguments'] + ['-fno-builtin-strlen', '-fparse-all-comments', '-Wwrite-strings',
                      '-D_FORTIFY_SOURCE=0', '-DC2RUST=1', '-resource-dir=/usr/lib/llvm-18/bin/../lib/clang/18', '-fsyntax-only'],
                  'regenerated_cc1_argv': ['-x', 'c', unit, '-triple', 'x86_64-pc-linux-gnu', '-resource-dir',
                      '/usr/lib/llvm-18/bin/../lib/clang/18', '-fdebug-compilation-dir=' + str(native_root)], 'target': 'x86_64-pc-linux-gnu', 'cpu': '', 'abi': '',
                  'features': [], 'features_as_written': [], 'vfs': 'clangtool_empty_overlay_on_real_filesystem',
                  'unsupported': [], 'lexer_events': [{'file_id': str(i), 'reason': 'enter', 'characteristic': 0} for i in (1, 2, 3)],
                  'buffers': [{'role': 'main', 'identifier': unit, 'physical_path': unit, 'aliases': [unit],
                               'native_device': '1', 'native_file': '1', 'length': len(buffers), 'bytes_hex': buffers.hex(),
                               'sha256': checksum, 'lexed': True, 'lexer_file_ids': ['1']},
                              {'role': 'predefines', 'identifier': '<built-in>', 'physical_path': '', 'aliases': [],
                               'native_device': '0', 'native_file': '0', 'length': 0, 'bytes_hex': '', 'sha256': F.sha(b''),
                               'lexed': True, 'lexer_file_ids': ['2']},
                              {'role': 'file', 'identifier': str(header), 'physical_path': str(header), 'aliases': [str(header)],
                               'native_device': '1', 'native_file': '3', 'length': len(buffers), 'bytes_hex': buffers.hex(),
                               'sha256': checksum, 'lexed': True, 'lexer_file_ids': ['3']}]}
        widths = dict(char=8, short=16, int=32, long=64, long_long=64, pointer=64, float=32, double=64)
        inventory = {'unit': unit, 'target': native['target'], 'target_c_widths_bits': widths,
                     'declarations': rows, 'calls': raw_calls}
        for row in expressions:
            row['effect_relation'] = unresolved
            row['type'] = typ
        for row in statements:
            row['native_shape'] = {'compound': 'Compound', 'branch': 'If', 'loop': 'While', 'return': 'ReturnValue'}[row['kind']]
            roles = {'compound': ['item'], 'branch': ['condition', 'then'], 'loop': ['condition', 'body'], 'return': ['value']}[row['kind']]
            for edge, role in zip(row['children'], roles):
                edge['role'] = role
        for row in [*statements, *expressions]:
            row['edge_count'] = len(row['children'])
        function_edges = [{'declaration': i + 1, 'parameters': [500 + i] + ([600 + i] if i >= 33 else []),
                           'fixed_count': 1 if i < 33 else 2, 'format_position': 0, 'format_parameter': 500 + i} for i in range(40)]
        facts = dict(inventory, schema=1, authorization='analysis_only', status='CompleteReport', lowering='not_authorized',
                     calls=calls, definitions=definitions, unclassified_definitions=extra, native_inputs=native,
                     expressions=expressions, statements=statements, variables=variables,
                     types=[{'type_id': 1, 'kind': 'Int'}], native_record_identities=[], cursor_events=events, function_edges=function_edges,
                     unsupported_expression_count=1, unsupported_expressions=[{'expression': 9900000,
                         'native_shape': 'Atomic', 'within_slice': False, 'location': location, 'relevance': unresolved}])
        coherent_graph_fixture(facts, inventory)
        prefix = str(index) + '/' + Path(UNITS[index]).stem.replace('.', '_')
        pair = {'unit': unit, 'facts': 'on/' + prefix + '.closed-format.json', 'inventory': 'on/' + prefix + '.variadic.json',
                'authority': 'on/' + prefix + '.unknown-authority.json',
                'cbor': 'on/' + prefix + '.cursor.cbor', 'typed_ast': 'on/' + prefix + '.typed-ast.txt',
                'rust_on': 'on/' + prefix + '.rs', 'rust_off': 'off/' + prefix + '.rs'}
        facts['compiler_session'] = {'raw_cbor_sha256': F.sha(b'synthetic binding, not actual AST'),
                                     'typed_ast_sha256': F.sha(b'synthetic binding, not actual AST')}
        write(pair['facts'], facts); write(pair['inventory'], inventory)
        write(pair['authority'], F.authority_projection(facts))
        for field in ('cbor', 'typed_ast'):
            write(pair[field], b'synthetic binding, not actual AST')
        for mode in ('on', 'off'):
            write(pair['rust_' + mode], b'// synthetic fixture\n')
        pair['files'] = {name: F.sha((root / value).read_bytes()) for name, value in pair.items() if name != 'unit'}
        units.append(pair)
    write('compile_commands.json', commands); write('native-files.json', native_files); write('inventory-plan.json', plan)
    write('fixture-kind.txt', b'Synthetic transport only. Never compiler or hosted evidence.\n')
    write('tool/bin/c2rust-transpile', b'synthetic compiler identity, never executable')
    write('tool/bin/c2rust', b'synthetic driver identity, never executable')
    patch = Path(__file__).with_name('patches') / 'c2rust-win64-abi.patch'
    write('tool/source-evidence/c2rust-source.patch', patch.read_bytes())
    from apply_c2rust_patch import REVISION, patch_destinations
    applied = {}
    for name in patch_destinations(patch):
        write('tool/source-evidence/c2rust-applied-source/' + name, ('synthetic source ' + name).encode())
        applied[name] = F.sha(('synthetic source ' + name).encode())
    evidence = {'official_repository': 'https://github.com/immunant/c2rust.git',
                'original_revision': REVISION, 'patch_sha256': F.sha(patch.read_bytes()),
                'applied_diff_sha256': F.sha(patch.read_bytes()), 'modified_source_sha256': applied}
    write('tool/source-evidence/c2rust-patch.json', evidence)
    write('tool/source-receipt.json', {'patch_sha256': evidence['patch_sha256'],
         'source_receipt_sha256': F.sha((root / 'tool/source-evidence/c2rust-patch.json').read_bytes()),
         'binary_sha256': {name: F.sha((root / 'tool/bin' / name).read_bytes()) for name in ('c2rust', 'c2rust-transpile')}})
    argv = ['/compiler', '--output-dir', '/same/emitted', '/database']
    verifier_sources = {}
    for name in ('closed_format_facts.py', 'full_compiler.py', 'probe.py', 'apply_c2rust_patch.py'):
        write('verifier-source/' + name, Path(__file__).with_name(name).read_bytes())
        verifier_sources[name] = 'verifier-source/' + name
    packet = {'schema': 2, 'unknown_authority_representation': F.AUTHORITY_REPRESENTATION,
              'authorization': 'analysis_only', 'units': units,
              'database': 'compile_commands.json', 'native_files': 'native-files.json', 'inventory_plan': 'inventory-plan.json',
              'verifier_sources': verifier_sources,
              'tool': {'compiler': 'tool/bin/c2rust-transpile', 'patch': 'tool/source-evidence/c2rust-source.patch', 'source_receipt': 'tool/source-receipt.json', 'source_evidence': 'tool/source-evidence/c2rust-patch.json'},
              'commands': {'off': argv, 'on': [argv[0], '--emit-closed-format-facts', *argv[1:]]},
              'paired_rust': {mode: {str(i) + '/' + Path(UNITS[i]).stem.replace('.', '_') + '.rs': F.sha(b'// synthetic fixture\n') for i in range(24)} for mode in ('off', 'on')}}
    packet['native_syntax'] = 'native-syntax.json'
    write('native-syntax.json', [{'command': c['arguments'][:-2] + ['-fsyntax-only', c['file']], 'exit_code': 0, 'timed_out': False} for c in commands])
    packet['executions'] = 'executions.json'
    write('executions.json', {mode: {'command': command, 'exit_code': 0, 'process_exit_code': 0, 'timed_out': False} for mode, command in packet['commands'].items()})
    write('packet.json', packet)
    write('seal.json', F.manifest(root))
    return packet


class ClosedFormatFactsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name) / 'closed-format-facts'
        cls.root.mkdir()
        cls.packet = synthetic_packet_fixture(cls.root)
        cls.trusted = F.replay(cls.root, trusted_handoff=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_complete_transport_is_distinct_from_lowerability(self):
        result = F.replay(self.root)
        self.assertEqual(result['incoming_calls'], 4865)
        self.assertEqual(result['lowerability'], 'blocked')
        self.assertEqual(result['public_callback'], 'unproved')

    def test_authority_projection_is_type_strict_and_keeps_empty_units(self):
        for pair in self.packet['units']:
            facts = F.loads((self.root / pair['facts']).read_bytes())
            self.assertTrue(F.same(F.read_authority(self.root, pair), F.authority_projection(facts)))
        self.assertTrue(any(not F.read_authority(self.root, p)['unclassified_definitions'] for p in self.packet['units']))
        for left, right in [(True, 1), (1, 1.0), ([False], [0]), ({'nested': [True]}, {'nested': [1]})]:
            self.assertFalse(F.same(left, right))

    def test_authority_resealed_metadata_and_projection_controls(self):
        pair = self.packet['units'][0]
        path = self.root / pair['authority']
        original = path.read_bytes()
        packet_path = self.root / 'packet.json'
        original_packet = packet_path.read_bytes()
        changes = [lambda a: a.update(schema=True), lambda a: a.update(schema=1.0),
                   lambda a: a.update(unit='/foreign.c'), lambda a: a.update(target='foreign'),
                   lambda a: a['target_c_widths_bits'].update(char=8.0),
                   lambda a: a['compiler_session'].update(raw_cbor_sha256='0' * 64),
                   lambda a: a.update(extra=True), lambda a: a.pop('unclassified_definitions'),
                   lambda a: a['unclassified_definitions'].pop(),
                   lambda a: a['unclassified_definitions'][0].update(declaration=100.0),
                   lambda a: a['unclassified_definitions'][0].update(declaration=True),
                   lambda a: a['unclassified_definitions'][0].update(declaration=2**64),
                   lambda a: a['unclassified_definitions'][0]['symbol'].update(static='late_name'),
                   lambda a: a['unclassified_definitions'][0]['location']['spelling'].update(bytes_hex='00'),
                   lambda a: a['unclassified_definitions'][0].update(signature={'unproved': 'late reason'}),
                   lambda a: a['unclassified_definitions'][0].update(location={'unproved': 'late origin'})]
        try:
            for mutate in changes:
                value = F.loads(original)
                mutate(value)
                path.write_text(json.dumps(value))
                packet = F.loads(original_packet)
                packet['units'][0]['files']['authority'] = F.sha(path.read_bytes())
                packet_path.write_text(json.dumps(packet))
                (self.root / 'seal.json').write_text(json.dumps(F.manifest(self.root)))
                with self.assertRaises((F.FactsError, ValueError)):
                    F.replay(self.root)
        finally:
            path.write_bytes(original)
            packet_path.write_bytes(original_packet)
            (self.root / 'seal.json').write_text(json.dumps(F.manifest(self.root)))

    def test_authority_bound_duplicate_nonfinite_and_overflow_controls(self):
        pair = copy.deepcopy(self.packet['units'][0])
        path = self.root / pair['authority']
        original = path.read_bytes()
        try:
            exact = original + b' ' * (F.MAX_AUTHORITY - len(original))
            path.write_bytes(exact)
            pair['files']['authority'] = F.sha(exact)
            F.read_authority(self.root, pair)
            path.write_bytes(exact + b' ')
            pair['files']['authority'] = F.sha(exact + b' ')
            with self.assertRaisesRegex(F.FactsError, 'byte bound'):
                F.read_authority(self.root, pair)
            for raw in (b'{"schema":1,"schema":1}', b'{"schema":NaN}', b'{"schema":Infinity}', b'{"schema":1e999}'):
                path.write_bytes(raw)
                pair['files']['authority'] = F.sha(raw)
                with self.assertRaises((F.FactsError, ValueError)):
                    F.read_authority(self.root, pair)
        finally:
            path.write_bytes(original)

    def test_authority_packet_roles_are_exact_all24(self):
        commands = F.loads((self.root / 'compile_commands.json').read_bytes())
        changes = [lambda p: p.update(schema=1), lambda p: p.pop('unknown_authority_representation'),
                   lambda p: p.update(unknown_authority_representation='foreign'),
                   lambda p: p['units'].pop(), lambda p: p['units'].append(p['units'][0]),
                   lambda p: p['units'][0].pop('authority'),
                   lambda p: p['units'][0]['files'].pop('authority'),
                   lambda p: p['units'][0].update(authority=p['units'][1]['authority']),
                   lambda p: p['units'][0].update(authority=p['units'][0]['facts']),
                   lambda p: p['units'][0].update(authority='on/foreign.unknown-authority.json')]
        for mutate in changes:
            packet = copy.deepcopy(self.packet)
            mutate(packet)
            with self.assertRaises((F.FactsError, ValueError)):
                F.packet_pairs(packet, commands)

    def test_common_authority_admission_uses_current_sources_and_opaque_full_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            handoff = Path(directory) / 'trusted.json'
            raw = F.handoff_bytes(self.trusted)
            handoff.write_bytes(raw)
            commands = F.loads((self.root / 'compile_commands.json').read_bytes())
            tool = self.root / 'tool/bin/c2rust-transpile'
            decoder = F.loads
            def metadata_only(data):
                self.assertNotIn(b'"CompleteReport"', data)
                return decoder(data)
            with patch.object(F, 'loads', side_effect=metadata_only):
                admitted, before = F.authority_packet(self.root, commands, tool, handoff, len(raw), F.sha(raw))
            self.assertEqual(len(admitted['units']), len(UNITS))
            self.assertTrue(F.same(before, self.trusted['manifest']))
            path = Path(commands[0]['file'])
            original = path.read_bytes()
            try:
                path.write_bytes(b'int late_source;\n')
                with self.assertRaisesRegex(F.FactsError, 'current native source'):
                    F.authority_packet(self.root, commands, tool, handoff, len(raw), F.sha(raw))
            finally:
                path.write_bytes(original)

    def test_trusted_handoff_rejects_independently_resealed_packet_drift(self):
        pair = self.packet['units'][0]
        names = ['packet.json', 'compile_commands.json', 'native-files.json', pair['facts'],
                 pair['authority'], pair['cbor'], pair['typed_ast'], 'tool/bin/c2rust-transpile']
        saved = {name: (self.root / name).read_bytes() for name in names}
        with tempfile.TemporaryDirectory() as directory:
            handoff = Path(directory) / 'trusted.json'
            raw = F.handoff_bytes(self.trusted)
            handoff.write_bytes(raw)
            commands = F.loads(saved['compile_commands.json'])
            tool = self.root / 'tool/bin/c2rust-transpile'
            def argv_only(data):
                data['compile_commands.json'][0]['arguments'].insert(1, '-DRESEALED_ARGV_ONLY=1')
            def remap(data):
                old = data['packet.json']['units'][0]['unit']
                new = old.replace('/native/', '/remapped/')
                data['packet.json']['units'][0]['unit'] = new
                data['compile_commands.json'][0]['file'] = new
                data[pair['authority']]['unit'] = new
                data[pair['authority']]['compiler_session']['raw_cbor_sha256'] = '0' * 64
            def omit_header(data):
                del data['native-files.json'][str(self.root.parent / 'native/include/fixture.h')]
            changes = [argv_only, remap, omit_header,
                       lambda d: d.update({'tool/bin/c2rust-transpile': b'changed compiler'}),
                       lambda d: d[pair['facts']]['native_inputs']['buffers'][0].update(bytes_hex='00'),
                       lambda d: d.update({pair['cbor']: b'changed CBOR'}),
                       lambda d: d.update({pair['typed_ast']: b'changed typed AST'})]
            for mutate in changes:
                with self.subTest(change=mutate):
                    try:
                        data = {name: F.loads(value) if name.endswith('.json') else value for name, value in saved.items()}
                        mutate(data)
                        for name, value in data.items():
                            (self.root / name).write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
                        packet = data['packet.json']
                        for unit in packet['units']:
                            unit['files'] = {role: F.sha((self.root / unit[role]).read_bytes()) for role in unit['files']}
                        (self.root / 'packet.json').write_text(json.dumps(packet))
                        (self.root / 'seal.json').write_text(json.dumps(F.manifest(self.root)))
                        current = F.loads((self.root / 'compile_commands.json').read_bytes())
                        with self.assertRaisesRegex(F.FactsError, 'trusted replay manifest differs'):
                            F.authority_packet(self.root, current, tool, handoff, len(raw), F.sha(raw))
                    finally:
                        for name, value in saved.items():
                            (self.root / name).write_bytes(value)
                        (self.root / 'seal.json').write_text(json.dumps(F.manifest(self.root)))
            self.assertEqual(F.authority_packet(self.root, commands, tool, handoff, len(raw), F.sha(raw))[0], self.packet)

    def test_trusted_handoff_external_authentication_and_closed_types(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trusted.json'
            raw = F.handoff_bytes(self.trusted)
            path.write_bytes(raw)
            F.read_handoff(self.root, path, len(raw), F.sha(raw))
            for size, digest in [(None, None), (True, F.sha(raw)), (len(raw) + 1, F.sha(raw)),
                                 (len(raw), '0' * 64), (len(raw), F.sha(raw).upper())]:
                with self.subTest(size=size, digest=digest), self.assertRaises(F.FactsError):
                    F.read_handoff(self.root, path, size, digest)
            for candidate in (None, self.root / 'seal.json', Path(directory) / 'missing.json'):
                with self.assertRaises(F.FactsError):
                    F.read_handoff(self.root, candidate, len(raw), F.sha(raw))
            path.write_bytes(raw + b'corruption')
            with self.assertRaises(F.FactsError):
                F.read_handoff(self.root, path, len(raw), F.sha(raw))
            tampered = raw.replace(b'complete_coverage', b'changed_coverage!')
            self.assertNotEqual(tampered, raw)
            self.assertEqual(len(tampered), len(raw))
            path.write_bytes(tampered)
            with self.assertRaisesRegex(F.FactsError, 'external digest'):
                F.read_handoff(self.root, path, len(raw), F.sha(raw))
            changes = [lambda h: h.update(schema=True), lambda h: h.update(schema=1.0),
                       lambda h: h.update(schema=2), lambda h: h.update(kind='foreign'),
                       lambda h: h.update(status='unchecked'), lambda h: h.update(authorization='lowering'),
                       lambda h: h.update(extra=True), lambda h: h.pop('bindings'),
                       lambda h: h.update(bindings={}), lambda h: h.update(native_files=[]),
                       lambda h: h.update(manifest=[])]
            for mutate in changes:
                value = copy.deepcopy(self.trusted)
                mutate(value)
                invalid = json.dumps(value).encode()
                path.write_bytes(invalid)
                with self.assertRaises(F.FactsError):
                    F.read_handoff(self.root, path, len(invalid), F.sha(invalid))
            for invalid in (b'{"schema":1,"schema":1}', b'{"schema":NaN}', b'{"schema":Infinity}', b'{"schema":1e999}'):
                path.write_bytes(invalid)
                with self.assertRaises(F.FactsError):
                    F.read_handoff(self.root, path, len(invalid), F.sha(invalid))

    def test_trusted_handoff_requires_exact_typed_all24_bindings(self):
        commands = F.loads((self.root / 'compile_commands.json').read_bytes())
        changes = [lambda h: h['bindings'].pop(), lambda h: h['bindings'].append(h['bindings'][0]),
                   lambda h: h['bindings'][0].update(unit='/remapped/blob.c'),
                   lambda h: h['bindings'][0]['command']['arguments'].append('-DDRIFT'),
                   lambda h: h['bindings'][0]['compiler_session'].update(raw_cbor_sha256='0' * 64),
                   lambda h: h['bindings'][0].update(facts=h['bindings'][1]['facts']),
                   lambda h: h['bindings'][0].update(extra=True),
                   lambda h: h.update(native_files='foreign.json'),
                   lambda h: h['manifest']['packet.json'].update(bytes=float(h['manifest']['packet.json']['bytes']))]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trusted.json'
            for mutate in changes:
                value = copy.deepcopy(self.trusted)
                mutate(value)
                raw = F.handoff_bytes(value)
                path.write_bytes(raw)
                with self.assertRaisesRegex(F.FactsError, 'trusted replay (manifest differs|unit command or session bindings differ)'):
                    F.authority_packet(self.root, commands, self.root / 'tool/bin/c2rust-transpile',
                                       path, len(raw), F.sha(raw))

    def test_common_collection_rechecks_manifest_after_unknown_join(self):
        import check_common_plan as common
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            handoff = Path(directory) / 'trusted.json'
            raw = F.handoff_bytes(self.trusted)
            handoff.write_bytes(raw)
            database = self.root.parent / 'compile_commands.json'
            database.write_bytes((self.root / 'compile_commands.json').read_bytes())
            output = Path(directory) / 'common'
            path = self.root / self.packet['units'][0]['authority']
            original = path.read_bytes()
            def run(command, log, **kwargs):
                emitted = Path(command[command.index('--output-dir') + 1])
                emitted.mkdir()
                (emitted / 'fixture.rs').write_bytes(b'// synthetic fixture\n')
                log.write_text('COMMON_PLAN_CLOSED 24\n' + 'COMMON_PLAN_NATIVE_EXPORT \n' * 24
                               + 'COMMON_PLAN_TYPED_IMPORT \n' * 24 + 'COMMON_PLAN_EMIT \n' * 24)
                return dict(exit_code=0, timed_out=False)
            def late(reports, validation, sources):
                self.assertEqual(len(list(reports)), 24)
                path.write_bytes(original + b' ')
                return {}
            try:
                with patch('probe.run', side_effect=run), patch.object(common, 'seal_live_report', return_value={}), \
                     patch.object(common, 'ReportValidation') as validation, \
                     patch.object(common, 'preserved_unknowns', side_effect=late):
                    validation.return_value.__enter__.return_value = SimpleNamespace(sources=set())
                    with self.assertRaisesRegex(ValueError, 'independent packet changed during unknown join'):
                        common.collect(self.root / 'tool/bin/c2rust-transpile', database, output, 1,
                                       handoff, len(raw), F.sha(raw))
                self.assertFalse((output / 'report.json').exists())
            finally:
                path.write_bytes(original)

    def test_trusted_handoff_exact_bound_and_one_over_refuse(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trusted.json'
            raw = F.handoff_bytes(self.trusted)
            exact = raw + b' ' * (F.MAX_AUTHORITY - len(raw))
            path.write_bytes(exact)
            F.read_handoff(self.root, path, len(exact), F.sha(exact))
            path.write_bytes(exact + b' ')
            with self.assertRaisesRegex(F.FactsError, 'anchor required'):
                F.read_handoff(self.root, path, len(exact) + 1, F.sha(exact + b' '))
            value = dict(self.trusted, native_files='')
            value['native_files'] = 'x' * (F.MAX_AUTHORITY - len(F.handoff_bytes(value)))
            self.assertEqual(len(F.handoff_bytes(value)), F.MAX_AUTHORITY)
            value['native_files'] += 'x'
            with self.assertRaisesRegex(F.FactsError, 'byte bound'):
                F.handoff_bytes(value)

    def test_resealed_identity_and_coverage_controls(self):
        cases = [
            ('packet.json', lambda d: d['units'].pop()),
            ('packet.json', lambda d: d['units'].append(d['units'][0])),
            ('packet.json', lambda d: d['commands']['on'].append('--different-flag')),
            ('native-files.json', lambda d: d.__setitem__(next(iter(d)), '0' * 64)),
            ('inventory-plan.json', lambda d: d['symbols'].pop()),
            ('inventory-plan.json', lambda d: d['symbols'].append(d['symbols'][0])),
            ('inventory-plan.json', lambda d: d['unclassified_definitions'].pop()),
            ('inventory-plan.json', lambda d: d['symbols'][0]['calls'][1].update(d['symbols'][0]['calls'][0])),
            ('tool/source-receipt.json', lambda d: d.__setitem__('patch_sha256', '0' * 64)),
            ('native-syntax.json', lambda d: d.pop()),
            ('executions.json', lambda d: d['on'].__setitem__('timed_out', True)),
            ('on/0/blob.closed-format.json', lambda d: d['definitions'].pop()),
            ('on/0/blob.closed-format.json', lambda d: d['unsupported_expressions'].pop()),
            ('on/0/blob.closed-format.json', lambda d: d['unsupported_expressions'][0].__setitem__('within_slice', True)),
            ('on/0/blob.closed-format.json', lambda d: d['unsupported_expressions'][0].__setitem__('relevance', {'state': 'Proved'})),
            ('on/9/dxil.closed-format.json', lambda d: d['definitions'].pop()),
            ('on/0/blob.closed-format.json', lambda d: d['calls'].pop()),
            ('on/0/blob.closed-format.json', lambda d: d['calls'].append(d['calls'][0])),
            ('on/0/blob.closed-format.json', lambda d: d['calls'][0].__setitem__('format_position', 1)),
            ('on/0/blob.closed-format.json', lambda d: d['calls'][0]['format'].__setitem__('bytes', [37, 115])),
            ('on/0/blob.closed-format.json', lambda d: d['calls'][0]['format']['consumption']['conversions'][0].__setitem__('conversion', 115)),
            ('on/0/blob.closed-format.json', lambda d: d['calls'][0].__setitem__('callee_declaration', 40)),
            ('on/0/blob.closed-format.json', lambda d: d['expressions'][1].__setitem__('type_id', 999)),
            ('on/0/blob.closed-format.json', lambda d: next(e for e in d['expressions'] if e['id'] == d['calls'][0]['arguments'][0]['id']).__setitem__('promotion_chain', [])),
            ('on/0/blob.closed-format.json', lambda d: d['cursor_events'].pop()),
            ('on/0/blob.closed-format.json', lambda d: d['cursor_events'][0].__setitem__('builtin', [1, 'va_end'])),
            ('on/0/blob.closed-format.json', lambda d: d['statements'].pop()),
            ('on/0/blob.closed-format.json', lambda d: d['statements'][1]['children'].pop()),
            ('on/0/blob.closed-format.json', lambda d: d['statements'][2]['children'].pop()),
            ('on/0/blob.closed-format.json', lambda d: d['statements'][3]['children'].pop()),
            ('on/0/blob.closed-format.json', lambda d: d['definitions'][0].__setitem__('generated_origin', {'state': 'Proved'})),
            ('on/0/blob.closed-format.json', lambda d: d.__setitem__('target', 'aarch64-linux-gnu')),
            ('on/0/blob.closed-format.json', lambda d: d['native_inputs']['buffers'][0].__setitem__('sha256', '0' * 64)),
        ]
        for name, mutate in cases:
            with self.subTest(control=name, mutation=cases.index((name, mutate))):
                path = self.root / name
                original = path.read_bytes()
                packet_path = self.root / 'packet.json'
                original_packet = packet_path.read_bytes()
                data = F.loads(original)
                mutate(data)
                path.write_text(json.dumps(data))
                if name.endswith('.closed-format.json'):
                    packet = F.loads(original_packet)
                    for pair in packet['units']:
                        if pair['facts'] == name:
                            pair['files']['facts'] = F.sha(path.read_bytes())
                    packet_path.write_text(json.dumps(packet))
                (self.root / 'seal.json').write_text(json.dumps(F.manifest(self.root)))
                try:
                    with self.assertRaises((F.FactsError, KeyError, TypeError, ValueError)):
                        F.replay(self.root)
                finally:
                    path.write_bytes(original)
                    packet_path.write_bytes(original_packet)
                    (self.root / 'seal.json').write_text(json.dumps(F.manifest(self.root)))
                self.assertEqual(F.replay(self.root)['status'], 'complete_coverage')

    def reject_coordinated(self, mutate, reason):
        names = ['packet.json', 'compile_commands.json', 'native-syntax.json', 'on/0/blob.closed-format.json',
                 'on/0/blob.variadic.json', 'on/0/blob.cursor.cbor', 'on/0/blob.typed-ast.txt',
                 'tool/source-evidence/c2rust-source.patch', 'tool/source-evidence/c2rust-patch.json',
                 'tool/source-receipt.json', 'tool/bin/c2rust-transpile']
        saved = {name: (self.root / name).read_bytes() for name in names}
        data = {name: F.loads(raw) if name.endswith('.json') else raw for name, raw in saved.items()}
        try:
            mutate(data)
            for name, value in data.items():
                (self.root / name).write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
            packet = data['packet.json']
            for pair in packet['units']:
                pair['files'] = {k: F.sha((self.root / pair[k]).read_bytes()) for k in pair['files']}
            (self.root / 'packet.json').write_text(json.dumps(packet))
            (self.root / 'seal.json').write_text(json.dumps(F.manifest(self.root)))
            if reason is None:
                self.assertEqual(F.replay(self.root)['status'], 'complete_coverage')
            else:
                with self.assertRaisesRegex((F.FactsError, ValueError), reason + '|graph projection|graph closure|classification projection'):
                    F.replay(self.root)
        finally:
            for name, raw in saved.items():
                (self.root / name).write_bytes(raw)
            (self.root / 'seal.json').write_text(json.dumps(F.manifest(self.root)))

    def test_recursive_type_reference_closure_is_structural(self):
        self.reject_coordinated(self.native_record_positive, None)

    def test_coordinated_tool_identity_controls(self):
        evidence = 'tool/source-evidence/c2rust-patch.json'
        receipt = 'tool/source-receipt.json'
        def refresh(d):
            d[receipt]['source_receipt_sha256'] = F.sha(json.dumps(d[evidence]).encode())
        def patch_and_receipts(d):
            d['tool/source-evidence/c2rust-source.patch'] += b'\n'
            checksum = F.sha(d['tool/source-evidence/c2rust-source.patch'])
            d[evidence]['patch_sha256'] = d[evidence]['applied_diff_sha256'] = checksum
            d[receipt]['patch_sha256'] = checksum
            refresh(d)
        self.reject_coordinated(patch_and_receipts, 'differs from reviewed patch')
        for field, value, reason in [('original_revision', '0' * 40, 'source evidence'),
                                     ('official_repository', 'https://invalid.example/source', 'source repository')]:
            def mutate(d, field=field, value=value):
                d[evidence][field] = value
                refresh(d)
            self.reject_coordinated(mutate, reason)
        self.reject_coordinated(lambda d: d.__setitem__('tool/bin/c2rust-transpile', b'changed compiler'), 'binary')
        self.reject_coordinated(lambda d: d[evidence]['modified_source_sha256'].__setitem__(
            next(iter(d[evidence]['modified_source_sha256'])), '0' * 64), 'source evidence|receipt')

    def test_database_changes_with_refreshed_syntax_do_not_change_actual_invocation(self):
        for flag in ('-DCOORDINATED=1', '-I/different/include', '--target=aarch64-linux-gnu',
                     '-resource-dir=/different/resource'):
            def mutate(d, flag=flag):
                command = d['compile_commands.json'][0]
                command['arguments'].insert(1, flag)
                d['native-syntax.json'][0]['command'] = command['arguments'][:-2] + ['-fsyntax-only', command['file']]
            self.reject_coordinated(mutate, 'actual adjusted invocation')
        def source(d):
            command = d['compile_commands.json'][0]
            command['arguments'][-1] = '/different/source.c'
            d['native-syntax.json'][0]['command'] = command['arguments'][:-2] + ['-fsyntax-only', command['file']]
        self.reject_coordinated(source, 'actual adjusted invocation')
        def cwd(d):
            d['compile_commands.json'][0]['directory'] = '/'
        self.reject_coordinated(cwd, 'all24 units|invocation identity')

    def test_coordinated_missing_references_and_ownership_reject(self):
        name = 'on/0/blob.closed-format.json'
        cases = [
            lambda f: f['function_edges'][0]['parameters'].__setitem__(0, 999999),
            lambda f: f['definitions'][0]['parameters'].__setitem__(0, 501),
            lambda f: f['variables'][0].__setitem__('initializer', 999999),
            lambda f: f['variables'][0].__setitem__('parameter_owners', [2]),
            lambda f: f['types'][0].__setitem__('inner', 999999),
            lambda f: f['types'][0].__setitem__('kind', 'pointer'),
            lambda f: f['types'][0].__setitem__('pointee', {'type_id': 999999}),
            lambda f: f['types'][0].__setitem__('element', {'type_id': 999999}),
            lambda f: f['types'][0].__setitem__('declaration', 999999),
            lambda f: f['variables'][0].__setitem__('native_va_list', {'builtin_type_id': 999999}),
            lambda f: f['variables'][0].__setitem__('fields', [999999]),
            lambda f: f['expressions'][0].__setitem__('statement_body', 999999),
        ]
        for i, mutate in enumerate(cases):
            with self.subTest(reference=i):
                self.reject_coordinated(lambda d: mutate(d[name]), 'missing|ownership|owned|ordered|reference')

    def test_coordinated_control_and_call_structure_reject(self):
        name = 'on/0/blob.closed-format.json'
        def drop_role(f, index, role):
            stmt = f['statements'][index]
            stmt['children'] = [e for e in stmt['children'] if e['role'] != role]
            stmt['edge_count'] = len(stmt['children'])
        for index, role in ((1, 'condition'), (2, 'condition'), (3, 'value')):
            self.reject_coordinated(lambda d: drop_role(d[name], index, role), 'mandatory statement role')
        def for_condition(d):
            d[name]['statements'][2]['native_shape'] = 'ForLoop010'
            drop_role(d[name], 2, 'condition')
        self.reject_coordinated(for_condition, 'mandatory statement role')
        for kind, shape in (('return', 'ReturnValue'), ('empty', 'Empty')):
            def relabel(d, kind=kind, shape=shape):
                d[name]['statements'][1].update(kind=kind, native_shape=shape)
            self.reject_coordinated(relabel, 'mandatory statement role|incompatible statement roles')
        def call_operands(d):
            f = d[name]
            expr = next(e for e in f['expressions'] if e['id'] == f['calls'][0]['id'])
            expr['arguments'] = list(reversed(expr['arguments']))
            expr['children'][1:] = [a['id'] for a in expr['arguments']]
            f['cursor_events'][0]['operands'] = expr['arguments']
        self.reject_coordinated(call_operands, 'ordered operands')
        def callee(d):
            f = d[name]
            expr = next(e for e in f['expressions'] if e['id'] == f['calls'][0]['id'])
            expr['callee_decl'] = 2
            f['cursor_events'][0]['callee_declaration'] = 2
        self.reject_coordinated(callee, 'callee or ordered operands')
        def builtin(d):
            f = d[name]
            expr = next(e for e in f['expressions'] if e['id'] == f['calls'][0]['id'])
            expr['builtin'] = [123, 'va_copy']
            f['cursor_events'][0]['builtin'] = expr['builtin']
        self.reject_coordinated(builtin, 'builtin contradicts declaration')

    def test_coordinated_graph_relations_reject(self):
        name, inventory = 'on/0/blob.closed-format.json', 'on/0/blob.variadic.json'
        def terminal(d):
            expr = {e['id']: e for e in d[name]['expressions']}
            expr[1003]['decl'] = 2
            expr[1000]['callee_reference'] = 1013
        self.reject_coordinated(terminal, 'callee terminal')
        for children in ([1003], [1013], [1013, 1023]):
            def wrapper(d, children=children):
                expr = {e['id']: e for e in d[name]['expressions']}
                expr[1003].update(kind='paren', children=children, edge_count=len(children))
            self.reject_coordinated(wrapper, 'cyclic|ambiguous|callee terminal|promotion chain coverage')
        for parameters in ([], [999999999], [638], [639, 639], [639, 539]):
            def va(d, parameters=parameters):
                for key in (name, inventory):
                    d[key]['declarations'][39]['va_parameters'] = parameters
                raw = next(row for row in d[name]['graph']['declarations'] if row['id'] == 40)
                raw['va_parameters'] = parameters
            self.reject_coordinated(va, 'va parameter')
        def edge(d):
            d[name]['function_edges'] = [e for e in d[name]['function_edges'] if e['declaration'] != 40]
        self.reject_coordinated(edge, 'edge coverage')
        def argument_type(d):
            for key in (name, inventory):
                d[key]['calls'][0]['arguments'][0]['type']['canonical']['kind'] = 'UInt'
        self.reject_coordinated(argument_type, 'argument type contradicts promotion head')
        def promotion_type(d):
            argument_type(d)
            for key in (name, inventory):
                d[key]['calls'][0]['arguments'][0]['promotion_chain'][0]['canonical']['kind'] = 'UInt'
            f = d[name]
            next(e for e in f['expressions'] if e['id'] == 1001)['promotion_chain'][0]['canonical']['kind'] = 'UInt'
        self.reject_coordinated(promotion_type, 'expression type contradicts promotion chain')
        def nested_promotion(d):
            expr = {e['id']: e for e in d[name]['expressions']}
            expr[1003].update(kind='implicit_cast', children=[1013], edge_count=1,
                             promotion_chain=[expr[1003]['type'], {'canonical': {'kind': 'UInt'}}])
            expr[1000]['callee_reference'] = 1013
        self.reject_coordinated(nested_promotion, 'expression type contradicts promotion chain')

    @staticmethod
    def refresh_graph_views(data, *, prepare=True, validate=True, projection_graph=None):
        import copy
        facts = data['on/0/blob.closed-format.json']
        if prepare:
            constructor_fixture_fields(facts['graph'])
        if projection_graph is not None:
            graph = projection_graph
        elif validate:
            graph = F.ReportGraph(facts)
        else:
            from unittest.mock import patch
            def fixture_relations(owner):
                for kind, rows in owner.tables.items():
                    for row in rows.values():
                        extra, references = [], []
                        normalization = None
                        if kind == 'type':
                            shape = row['native_shape']
                            if shape in ('Struct','Union','Enum','Typedef'): references = [owner.edge('declaration',row['declaration'])]
                            if shape in ('TypeOf', 'Paren', 'Elaborated', 'Decayed', 'Auto'):
                                normalization = owner.edge('type', row['inner']); extra.append(normalization)
                            elif shape == 'Typedef' and 'original' in row:
                                normalization = owner.edge('type', row['original']['type_id']); extra.append(normalization)
                        elif kind == 'expression':
                            if row['qualified_type'] is not None: extra.append(owner.edge('type', row['type_id']))
                            if row['kind'] == 'reference':
                                references = [owner.edge('declaration', row['decl'])]; extra += references
                        owner.relation(kind, row, normalization, references, extra)
            with patch.object(F.ReportGraph, 'check_raw_constructors', fixture_relations):
                graph = F.ReportGraph(facts)
        inventory = graph.inventory(facts)
        data['on/0/blob.variadic.json'] = inventory
        facts['declarations'] = copy.deepcopy(inventory['declarations'])
        for field, table in (('variables', graph.declarations), ('statements', graph.statements), ('types', graph.types)):
            key = 'type_id' if field == 'types' else 'id'
            facts[field] = [copy.deepcopy(table[row[key]]) for row in facts[field]]
        facts['expressions'] = [graph.expression(row['id']) for row in facts['expressions']]
        calls = {c['id']: c for c in inventory['calls']}
        for call in facts['calls']:
            call.update(copy.deepcopy(calls[call['id']]))
        expr = {e['id']: e for e in facts['expressions']}
        for event in facts['cursor_events']:
            event['operands'] = copy.deepcopy(expr[event['expression']]['arguments'])
            event['builtin'] = copy.deepcopy(expr[event['expression']]['builtin'])
            event['callee_declaration'] = expr[event['expression']]['callee_decl']
        facts['native_record_identities'] = [{'declaration': row['id'], 'identity': row['identity']}
                                            for row in facts['variables'] if row.get('native_va_list_record')]
        selected = set(expr)
        facts['unsupported_expressions'] = [{'expression': ident, 'native_shape': row['native_shape'],
            'type': graph.expression(ident)['type'], 'within_slice': ident in selected, 'location': row['location'],
            'relevance': {'state': 'Unproved', 'reason': 'selected unsupported expression retains its complete structural children'
                          if ident in selected else 'outside selected slice; influence on formatting, control and effects is not established'}}
            for ident, row in sorted(graph.expressions.items()) if row['kind'] == 'unsupported']
        facts['unsupported_expression_count'] = len(facts['unsupported_expressions'])

    def native_record_positive(self, data):
        import copy
        facts = data['on/0/blob.closed-format.json']
        graph = facts['graph']
        q = lambda ident: dict(type_id=ident, const=False, volatile=False, restrict=False)
        edge = F.ReportGraph.edge
        raw = {e['id']: e for e in graph['expressions']}
        terminal = copy.deepcopy(raw[1003])
        terminal['id'] = 999999
        graph['expressions'].append(terminal)
        facts['expressions'].append({'id': 999999})
        raw[1003].update(kind='paren', native_shape='Paren', children=[999999], edge_count=1,
                         df_children=[edge('expression', 999999)],
                         structural_children=[edge('type', raw[1003]['type_id']), edge('expression', 999999)])
        raw[1003].pop('decl')
        for ident, fields in ((800, [802]), (801, [])):
            row = dict(id=ident, kind='struct', fields=fields, parameter_owners=[], native_va_list_record=True,
                       identity={'unproved': 'missing physical record evidence'}, state='unproved', layout=None,
                       diagnostic_location=None, df_children=[edge('declaration', p) for p in fields],
                       structural_children=[edge('declaration', p) for p in fields])
            graph['declarations'].append(row)
            graph['declaration_order'].append(ident)
            if ident == 800:
                facts['variables'].append({'id': ident})
        field = dict(id=802, kind='field', name='next', type_id=2, qualified_type=q(2), parameter_owners=[],
                     bit_width=None, bit_offset=0, type_bit_width=64, alignment=None, diagnostic_location=None,
                     df_children=[edge('type', 2)], structural_children=[edge('type', 2)])
        graph['declarations'].append(field)
        graph['declaration_order'].append(802)
        facts['variables'].append({'id': 802})
        for row in (dict(type_id=2, kind='pointer', pointee=q(3), df_children=[edge('type', 3)], structural_children=[edge('type', 3)]),
                    dict(type_id=3, kind='struct', declaration=800, df_children=[edge('declaration', 800)], structural_children=[edge('declaration', 800)])):
            graph['types'].append(row)
            facts['types'].append({'type_id': row['type_id']})
            graph['qualified_types'].append(dict(source=q(row['type_id']), path=[row['type_id']], normalized=q(row['type_id'])))
        raw[1002].update(type_id=2, qualified_type=q(2))
        self.refresh_graph_views(data)

    def test_producer_wrapper_and_inventory_cursor_type_relations_accept(self):
        self.reject_coordinated(self.native_record_positive, None)
        for change in ('missing', 'wrong_identity', 'wrong_existing_struct', 'same_unknown_other_marker'):
            def contradict(data, change=change):
                self.native_record_positive(data)
                facts = data['on/0/blob.closed-format.json']
                if change == 'missing':
                    facts['native_record_identities'] = []
                elif change == 'wrong_identity':
                    facts['native_record_identities'][0]['identity'] = {'unproved': 'different record origin'}
                elif change == 'wrong_existing_struct':
                    facts['native_record_identities'][0]['declaration'] = 801
                else:
                    expressions = {e['id']: e for e in facts['expressions']}
                    cursor = expressions[1002]['type']
                    cursor['canonical']['pointer']['canonical']['native_va_list_record'] = 801
                    expressions[1000]['arguments'][1]['type'] = cursor
                    facts['cursor_events'][0]['operands'][1]['type'] = cursor
                    facts['native_record_identities'][0]['declaration'] = 801
            self.reject_coordinated(contradict, 'projection')

    def test_operand_projection_rejects_false_direct_and_outside_reference(self):
        for field, value in (('direct_decl', 2), ('references', [{'id': 1013, 'decl': 1}])):
            def mutate(data, field=field, value=value):
                facts = data['on/0/blob.closed-format.json']
                call = next(e for e in facts['expressions'] if e['id'] == 1000)
                call['arguments'][0][field] = value
                facts['cursor_events'][0]['operands'][0][field] = value
            self.reject_coordinated(mutate, 'selected expressions graph projection')
        def uint_source_with_int_view(data):
            facts = data['on/0/blob.closed-format.json']
            for rows in (facts['expressions'], facts['graph']['expressions']):
                row = next(e for e in rows if e['id'] == 1001)
                row['type_id'] = row['qualified_type']['type_id'] = 4
            facts['types'].append(next(t for t in facts['graph']['types'] if t['type_id'] == 4))
        self.reject_coordinated(uint_source_with_int_view, 'selected expressions graph projection')

    def shared_subtree_positive(self, data):
        facts = data['on/0/blob.closed-format.json']
        raw = {e['id']: e for e in facts['graph']['expressions']}
        row = raw[1002]
        edge = F.ReportGraph.edge
        nested = dict(row, id=999990, kind='binary', native_shape='Binary', children=[1013, 1003], edge_count=2,
                      df_children=[edge('expression', i) for i in (1013, 1003)],
                      structural_children=[edge('expression', i) for i in (1013, 1003)])
        nested.pop('literal')
        facts['graph']['expressions'].append(nested)
        facts['expressions'].append({'id': 999990})
        row.update(kind='binary', native_shape='Binary', children=[1003, 999990], edge_count=2,
                   df_children=[edge('expression', i) for i in (1003, 999990)],
                   structural_children=[edge('expression', i) for i in (1003, 999990)])
        row.pop('literal')
        self.refresh_graph_views(data)

    def test_shared_subtree_reference_order_and_duplicates(self):
        self.reject_coordinated(self.shared_subtree_positive, None)
        for mode in ('missing', 'duplicate', 'reversed'):
            def mutate(data, mode=mode):
                self.shared_subtree_positive(data)
                facts = data['on/0/blob.closed-format.json']
                row = next(e for e in facts['expressions'] if e['id'] == 1000)
                refs = row['arguments'][1]['references']
                changed = refs[:-1] if mode == 'missing' else refs + refs[:1] if mode == 'duplicate' else [refs[1], refs[0], refs[2]]
                row['arguments'][1]['references'] = changed
                facts['cursor_events'][0]['operands'][1]['references'] = changed
            self.reject_coordinated(mutate, 'selected expressions graph projection')

    def statement_subtree_positive(self, data):
        self.native_record_positive(data)
        facts = data['on/0/blob.closed-format.json']
        edge = F.ReportGraph.edge
        graph = facts['graph']
        raw = next(e for e in graph['expressions'] if e['id'] == 1002)
        raw.update(kind='unsupported', native_shape='Statements', children=[], edge_count=0, statement_body=998000,
                   df_children=[edge('statement', 998000)], structural_children=[edge('statement', 998000)])
        raw.pop('literal')
        statement = dict(id=998000, kind='declarations', native_shape='Decls', label_target=None,
                         children=[dict(role='declaration', kind='declaration', id=804)], edge_count=1,
                         df_children=[edge('declaration', 804)], structural_children=[edge('declaration', 804)],
                         location=raw['location'], flow={'state': 'Unproved', 'reason': 'synthetic structural statement'})
        graph['statements'].append(statement)
        facts['statements'].append({'id': 998000})
        declaration = dict(id=804, kind='variable', type_id=2, type=next(r['type'] for r in graph['declarations'] if r['id'] == 802),
                           qualified_type=dict(type_id=2, const=False, volatile=False, restrict=False),
                           initializer=1013, local=False, owning_function=None, parameter_owners=[], va_list=False,
                           df_children=[edge('type', 2), edge('expression', 1013)],
                           structural_children=[edge('type', 2), edge('expression', 1013)])
        graph['declarations'].append(declaration)
        graph['declaration_order'].append(804)
        facts['variables'].append({'id': 804})
        self.refresh_graph_views(data)

    def test_statement_declaration_initializer_and_cycle_df_projection(self):
        self.reject_coordinated(self.statement_subtree_positive, None)
        def remove_reference(data):
            self.statement_subtree_positive(data)
            facts = data['on/0/blob.closed-format.json']
            call = next(e for e in facts['expressions'] if e['id'] == 1000)
            operand = call['arguments'][1]
            self.assertEqual(operand['references'], [{'id': 1013, 'decl': 1}])
            self.assertEqual(operand['references_unproved'], 'cyclic DF traversal retains raw edges')
            operand['references'] = []
            facts['cursor_events'][0]['operands'][1]['references'] = []
        self.reject_coordinated(remove_reference, 'selected expressions graph projection')

    def qualified_path_positive(self, data):
        facts = data['on/0/blob.closed-format.json']
        graph = facts['graph']
        edge = F.ReportGraph.edge
        q = lambda ident, **flags: dict(type_id=ident, const=flags.get('const', False),
                                        volatile=flags.get('volatile', False), restrict=False)
        original = q(1, const=True)
        for row in (dict(type_id=5, kind='typedef', declaration=805, original=original,
                         df_children=[edge('declaration', 805)], structural_children=[edge('declaration', 805)]),
                    dict(type_id=6, kind='elaborated', inner=5, df_children=[], structural_children=[])):
            graph['types'].append(row)
            facts['types'].append({'type_id': row['type_id']})
        declaration = dict(id=805, kind='typedef', type_id=1, qualified_type=original, parameter_owners=[],
                           df_children=[edge('type', 1)], structural_children=[edge('type', 1)])
        graph['declarations'].append(declaration)
        graph['declaration_order'].append(805)
        facts['variables'].append({'id': 805})
        graph['qualified_types'].append(dict(source=original, path=[1], normalized=original))
        graph['qualified_types'].append(dict(source=q(6, volatile=True), path=[6, 5, 1], normalized=q(1, const=True, volatile=True)))
        row = next(e for e in graph['expressions'] if e['id'] == 1002)
        row.update(type_id=6, qualified_type=q(6, volatile=True))
        self.refresh_graph_views(data)

    def test_compiler_owned_qualified_paths_and_terminal_projection(self):
        self.reject_coordinated(self.qualified_path_positive, None)
        for mode in ('hop', 'terminal', 'copy'):
            def mutate(data, mode=mode):
                self.qualified_path_positive(data)
                facts = data['on/0/blob.closed-format.json']
                row = next(q for q in facts['graph']['qualified_types'] if q['source']['type_id'] == 6)
                if mode == 'hop':
                    row['path'] = [6, 1]
                elif mode == 'terminal':
                    row['normalized']['type_id'] = 4
                else:
                    row['normalized']['const'] = False
            self.reject_coordinated(mutate, 'normalization path|normalized terminal|graph projection')

    def test_raw_cycles_do_not_relax_selected_lexical_ownership(self):
        import copy
        def positive(data):
            facts = data['on/0/blob.closed-format.json']
            row = copy.deepcopy(facts['graph']['statements'][0])
            row.update(id=999995, children=[dict(role='item', kind='statement', id=999995)], edge_count=1,
                       df_children=[F.ReportGraph.edge('statement', 999995)],
                       structural_children=[F.ReportGraph.edge('statement', 999995)])
            facts['graph']['statements'].append(row)
        self.reject_coordinated(positive, None)
        for mode in ('shared', 'cyclic'):
            def mutate(data, mode=mode):
                positive(data)
                facts = data['on/0/blob.closed-format.json']
                body = facts['definitions'][0]['body']
                for rows in (facts['statements'], facts['graph']['statements']):
                    row = next(s for s in rows if s['id'] == body)
                    ident = body if mode == 'cyclic' else row['children'][0]['id']
                    row['children'].append(dict(role='item', kind='statement', id=ident))
                    row['edge_count'] += 1
                    row['df_children'].append(F.ReportGraph.edge('statement', ident))
                    row['structural_children'].append(F.ReportGraph.edge('statement', ident))
            self.reject_coordinated(mutate, 'cyclic or shared statement ownership')

    def test_full_inventory_census_missing_and_extra_rows(self):
        for field in ('declarations', 'calls', 'record_definitions', 'non_call_references', 'va_arg'):
            for mode in ('missing', 'extra'):
                def mutate(data, field=field, mode=mode):
                    self.native_record_positive(data)
                    facts = data['on/0/blob.closed-format.json']
                    raw = facts['graph']['expressions']
                    reference = dict(next(e for e in raw if e['id'] == 999999), id=999998)
                    raw.append(reference)
                    arg = dict(next(e for e in raw if e['id'] == 1001), id=999997, native_shape='VAArg', kind='unsupported',
                               children=[1001], edge_count=1, df_children=[F.ReportGraph.edge('expression', 1001)],
                               structural_children=[F.ReportGraph.edge('type', 1), F.ReportGraph.edge('expression', 1001)])
                    arg.pop('literal')
                    raw.append(arg)
                    self.refresh_graph_views(data)
                    rows = data['on/0/blob.variadic.json'][field]
                    self.assertTrue(rows, field)
                    if mode == 'missing':
                        rows.pop()
                    else:
                        rows.append(json.loads(json.dumps(rows[-1])))
                self.reject_coordinated(mutate, 'full inventory graph projection')

    def test_complete_raw_constructor_counterexamples_reject_after_refresh(self):
        for case, reason in enumerate(('raw type mandatory edges', 'raw type mandatory edges',
                                       'raw type mandatory edges', 'raw expression mandatory edges',
                                       'mandatory statement role')):
            def mutate(data, case=case):
                if case in (0, 1):
                    self.native_record_positive(data) if case == 0 else self.statement_subtree_positive(data)
                facts = data['on/0/blob.closed-format.json']
                graph = facts['graph']
                if case in (0, 1):
                    row = next(r for r in graph['types'] if r['type_id'] == 3)
                    if case == 0:
                        row['df_children'] = []
                        row['structural_children'] = []
                    else:
                        row['df_children'].append(F.ReportGraph.edge('expression', 1023))
                        row['structural_children'].append(F.ReportGraph.edge('expression', 1023))
                elif case == 2:
                    next(r for r in graph['types'] if r['type_id'] == 200001)['df_children'] = []
                elif case == 3:
                    row = next(r for r in graph['expressions'] if r['id'] == 9900000)
                    row.update(df_children=[F.ReportGraph.edge('type', 1)],
                               structural_children=[F.ReportGraph.edge('type', 1)], children=[], edge_count=0)
                else:
                    next(r for r in graph['statements'] if r['id'] == 91100).update(kind='return', native_shape='ReturnValue')
                self.refresh_graph_views(data, prepare=False, validate=False)
            self.reject_coordinated(mutate, reason)

    def test_neighboring_raw_type_and_declaration_constructors(self):
        import copy
        facts = F.loads((self.root / 'on/0/blob.closed-format.json').read_bytes())
        edge = F.ReportGraph.edge
        q = lambda i: dict(type_id=i, const=False, volatile=False, restrict=False)
        graph = facts['graph']
        types = [
            dict(native_shape='Reference', original=q(1)), dict(native_shape='BlockPointer', original=q(1)),
            dict(native_shape='Vector', original=q(1)), dict(native_shape='Atomic', original=q(1)),
            dict(native_shape='Complex', element_type=1), dict(native_shape='TypeOfExpr', expression=1001),
            dict(native_shape='VariableArray', element_type=1, count_expression=1001),
            dict(native_shape='VariableArray', element_type=1, count_expression=None),
            dict(native_shape='ConstantArray', kind='array', element_type=1, element=q(1), length=2),
            dict(native_shape='IncompleteArray', kind='array', element_type=1, length=None),
            dict(native_shape='Attributed', kind='attributed', original=q(1), counted_by=1001),
            dict(native_shape='Elaborated', kind='elaborated', inner=1),
            dict(native_shape='TypeOf', kind='typeof', inner=1),
            dict(native_shape='BFloat16'), dict(native_shape='BuiltinFn', kind='builtin_function')]
        for i, row in enumerate(types, 880000):
            row['type_id'] = i
            shape = row['native_shape']
            children = ([] if shape in ('Elaborated', 'BFloat16', 'BuiltinFn') else
                        [edge('expression', 1001)] if shape == 'TypeOfExpr' else [edge('type', 1)])
            if shape in ('VariableArray', 'Attributed') and row.get('count_expression', row.get('counted_by')) is not None:
                children += [edge('expression', 1001)]
            row.update(df_children=copy.deepcopy(children), structural_children=copy.deepcopy(children))
            graph['types'].append(row)
        for i, (shape, field, target) in enumerate((('NonCanonicalDecl', 'canonical_decl', 1),
                                                   ('StaticAssert', 'assert_expr', 1001),
                                                   ('MacroObject', None, None), ('MacroFunction', None, None)), 890000):
            children = [] if field is None else [edge('declaration' if field == 'canonical_decl' else 'expression', target)]
            row = dict(id=i, kind='unsupported', native_shape=shape, parameter_owners=[],
                       df_children=copy.deepcopy(children), structural_children=copy.deepcopy(children))
            if field:
                row[field] = target
            graph['declarations'].append(row)
            graph['declaration_order'].append(i)
        constructor_fixture_fields(graph)
        F.ReportGraph(facts)
        for field, rows in (('types', types), ('declarations', graph['declarations'][-4:])):
            for row in rows:
                for projection in ('df_children', 'structural_children'):
                    original = copy.deepcopy(row[projection])
                    mutations = [[], [edge('expression', 1002)], original + [edge('type', 1)]]
                    if len(original) > 1:
                        mutations.append(list(reversed(original)))
                    for changed in mutations:
                        if changed == original:
                            continue
                        with self.subTest(field=field, shape=row['native_shape'], projection=projection, changed=changed):
                            row[projection] = changed
                            with self.assertRaisesRegex(F.FactsError, 'raw type mandatory edges|raw declaration mandatory edges'):
                                F.ReportGraph(facts)
                    row[projection] = original

    def test_neighboring_expression_constructors_and_raw_statement_order(self):
        import copy
        facts = F.loads((self.root / 'on/0/blob.closed-format.json').read_bytes())
        edge = F.ReportGraph.edge
        raw = facts['graph']['expressions']
        base = next(e for e in raw if e['id'] == 9900000)
        rows = []
        cases = [('ConstantExpr', dict(child=1001), [edge('expression', 1001)]),
                 ('Predefined', dict(child=1001), [edge('expression', 1001)]),
                 ('UnaryType', dict(expression=None), []),
                 ('OffsetOf', dict(type=1, index=1001), []),
                 ('OffsetOf', dict(type=None, index=None), []),
                 ('ShuffleVector', dict(elements=[1001, 1002]), []),
                 ('ConvertVector', dict(elements=[1002, 1001]), []),
                 ('InitList', dict(initializers=[1002, 1001]), [edge('expression', 1002), edge('expression', 1001)]),
                 ('Atomic', dict(ptr=1001, order=1002, val1=1001, order_fail=None, val2=None, weak=1002),
                  [edge('expression', i) for i in (1001, 1002, 1001, 1002)]),
                 ('Conditional', dict(condition=1001, then=1002, **{'else': 1001}),
                  [edge('expression', i) for i in (1001, 1002, 1001)])]
        for i, (shape, operands, df) in enumerate(cases, 885000):
            row = copy.deepcopy(base)
            row.update(id=i, native_shape=shape, operands=operands, df_children=copy.deepcopy(df))
            structural = copy.deepcopy(df)
            if shape == 'UnaryType':
                row.update(kind='unary_type', operator='SizeOf', argument_qualified_type=base['qualified_type'],
                           argument_type=F.ReportGraph(facts).type_view(base['qualified_type'], True))
                structural = [edge('type', 1)]
            elif shape == 'OffsetOf' and operands['type'] is not None:
                structural = [edge('type', 1), edge('expression', 1001)]
            elif shape in ('ShuffleVector', 'ConvertVector'):
                structural = [edge('expression', i) for i in operands['elements']]
            row.update(structural_children=structural, children=[e['id'] for e in structural if e['kind'] == 'expression'])
            row['edge_count'] = len(row['children'])
            raw.append(row)
            rows.append(row)
        F.ReportGraph(facts)
        for row in rows:
            for projection in ('df_children', 'structural_children'):
                original = copy.deepcopy(row[projection])
                for changed in ([], [edge('type', 1)], original + [edge('expression', 1001)], list(reversed(original))):
                    if changed == original:
                        continue
                    with self.subTest(shape=row['native_shape'], projection=projection, changed=changed):
                        row[projection] = changed
                        with self.assertRaisesRegex(F.FactsError, 'raw expression mandatory edges'):
                            F.ReportGraph(facts)
                row[projection] = original
        statement = next(r for r in facts['graph']['statements'] if r['id'] == 91100)
        statement.update(kind='loop', native_shape='DoWhile', edge_count=2,
                         children=[dict(role='body', kind='statement', id=91100), dict(role='condition', kind='expression', id=1001)],
                         df_children=[edge('statement', 91100), edge('expression', 1001)],
                         structural_children=[edge('statement', 91100), edge('expression', 1001)])
        F.ReportGraph(facts)
        statement['children'].reverse()
        statement['df_children'].reverse()
        statement['structural_children'].reverse()
        with self.assertRaisesRegex(F.FactsError, 'statement role order'):
            F.ReportGraph(facts)

    def test_producer_finalization_returns_views_with_qualified_snapshot(self):
        patch = (Path(__file__).parent / 'patches/c2rust-win64-abi.patch').read_text()
        source = patch.split('+++ b/c2rust-transpile/src/c_ast/closed_variadic.rs\n', 1)[1].split('diff --git ', 1)[0]
        source = '\n'.join(line[1:] for line in source.splitlines() if line.startswith('+'))
        finalizer = source.split('    fn finalize_expression_views(', 1)[1].split('    fn facts(', 1)[0]
        self.assertLess(finalizer.index('self.expression(*id)'), finalizer.index('self.qualified.borrow()'))
        self.assertIn('(expressions, qualified_types)', finalizer)
        facts = source.split('    fn facts(', 1)[1].split('\nimpl TypedAstContext', 1)[0]
        self.assertIn('let (expression_views, qualified_types) = self.finalize_expression_views();', facts)
        self.assertNotIn('self.expression(', facts)
        self.assertNotIn('self.qualified.borrow()', facts)
        self.assertIn('fn closed_format_native_record_identity_is_compiler_owned', source)
        self.assertIn('assert_eq!(qualified.len(), graph.qualified.borrow().len())', source)

    def test_closed_raw_records_and_reference_neighbors(self):
        import copy
        q = dict(type_id=1, const=False, volatile=False, restrict=False)
        edge = lambda kind, ident: dict(kind=kind, id=ident)
        unknown = {'unproved': 'independent native origin'}
        effect = {'state': 'Unproved', 'reason': 'independent effect relation'}
        base = dict(id=1001, kind='literal', native_shape='Literal', operands={}, literal={'integer': 1},
                    qualified_type=q, type_id=1, va_list=False, statement_body=None, diagnostic_location=None,
                    location=unknown, children=[], edge_count=0, df_children=[], structural_children=[], effect_relation=effect)
        decl = dict(id=800, kind='struct', identity=unknown, native_va_list_record=False, fields=[802], layout=[False, None, None, 4, 4],
                    state='complete', parameter_owners=[], diagnostic_location=None,
                    df_children=[edge('declaration', 802)], structural_children=[edge('declaration', 802)])
        view = {'canonical': {'kind': 'Int'}, 'const': False, 'volatile': False, 'restrict': False}
        field = dict(id=802, kind='field', name='field', type_id=1, qualified_type=q, type=view, owners=[unknown],
                     bit_width=None, bit_offset=0, type_bit_width=32, alignment=None, parameter_owners=[], diagnostic_location=None,
                     df_children=[edge('type', 1)], structural_children=[edge('type', 1)])
        typedef = dict(id=803, kind='typedef', type_id=1, qualified_type=q, parameter_owners=[], diagnostic_location=None,
                       df_children=[edge('type', 1)], structural_children=[edge('type', 1)])
        enum = dict(id=804, kind='enum', identity=unknown, native_va_list_record=False, variants=[805], underlying=q,
                    state='complete', parameter_owners=[], diagnostic_location=None,
                    df_children=[edge('declaration', 805), edge('type', 1)], structural_children=[edge('declaration', 805), edge('type', 1)])
        variant = dict(id=805, kind='enum_constant', name='value', signed=True, value=-1,
                       owning_enum={'declaration': 804, 'identity': unknown}, parameter_owners=[], diagnostic_location=None,
                       df_children=[], structural_children=[])
        variable = dict(id=806, kind='variable', name='v', type_id=1, qualified_type=q, type=view, local=False, owning_function=None,
                        va_list=False, initializer=None, static=False, thread=False, externally_visible=False, native_va_list=None,
                        parameter_owners=[], diagnostic_location=None, df_children=[edge('type', 1)], structural_children=[edge('type', 1)])
        statement = dict(id=900, kind='empty', native_shape='Empty', label_target=None, location=unknown,
                         edge_count=0, children=[], flow=effect, df_children=[], structural_children=[])
        typ = dict(type_id=1, kind='Int', native_shape='Int', df_children=[], structural_children=[])
        facts = {'unit':'/native/fixture.c', 'graph': dict(types=[typ], expressions=[base], declarations=[decl, field, typedef, enum, variant, variable],
                              statements=[statement], declaration_order=[800, 802, 803, 804, 805, 806],
                              qualified_types=[dict(source=q, path=[1], normalized=q)])}
        expressions = [
            ('BadExpr', 'unsupported', {}, [], [], dict(qualified_type=None, type_id=None, va_list=None,
                type_unproved='importer expression has no qualified type')),
            ('Member', 'member', {'child': 1001}, [edge('expression', 1001)], [edge('expression', 1001)], dict(member={'id':803}, access='Dot')),
            ('ImplicitCast', 'implicit_cast', {'child':1001}, [edge('expression', 1001)], [edge('type', 1), edge('expression', 1001)], dict(cast='NoOp', field=802)),
            ('ExplicitCast', 'explicit_cast', {'child':1001}, [edge('expression', 1001)], [edge('type', 1), edge('expression', 1001)], dict(cast='NoOp', field=None)),
            ('DeclRef', 'reference', {}, [], [], dict(decl=803)),
            ('ConstantExpr', 'unsupported', {'child':1001}, [edge('expression', 1001)], [edge('expression', 1001)], {}),
            ('Unary', 'unary', {'child':1001}, [edge('expression', 1001)], [edge('expression', 1001)], dict(operator='Plus')),
            ('Binary', 'binary', dict(left=1001, right=1001), [edge('expression', 1001)] * 2, [edge('expression', 1001)] * 2,
             dict(operator='Add', computation_qualified_types=[q, None], computation_types=[view, None])),
            ('UnaryType', 'unary_type', dict(expression=None), [], [edge('type', 1)], dict(operator='SizeOf', argument_qualified_type=q, argument_type=view)),
        ]
        for ident, (shape, kind, operands, df, structural, extra) in enumerate(expressions, 1100):
            row = dict(copy.deepcopy(base), id=ident, kind=kind, native_shape=shape, operands=operands,
                       df_children=df, structural_children=structural,
                       children=[e['id'] for e in structural if e['kind'] == 'expression'])
            row.pop('literal')
            row.update(extra, edge_count=len(row['children']))
            facts['graph']['expressions'].append(row)
        types = [
            dict(type_id=2, native_shape='Char', kind='Char', signed=False),
            dict(type_id=3, native_shape='Char', kind='Char', unproved='missing plain char signedness'),
            dict(type_id=4, native_shape='Typedef', kind='typedef', declaration=803, original=q),
            dict(type_id=5, native_shape='Typedef', kind='typedef', declaration=803, unproved='missing original typedef declaration or type'),
            dict(type_id=6, native_shape='ConstantArray', kind='array', element_type=1, element=q, length=2),
            dict(type_id=7, native_shape='IncompleteArray', kind='array', element_type=1, length=None, unproved='missing or inconsistent qualified array element'),
            dict(type_id=8, native_shape='Struct', kind='struct', declaration=800),
            dict(type_id=9, native_shape='Enum', kind='enum', declaration=804),
        ]
        for row in types:
            shape = row['native_shape']
            edges = ([edge('declaration', row['declaration'])] if shape in ('Typedef', 'Struct', 'Enum') else
                     [edge('type', 1)] if shape in ('ConstantArray', 'IncompleteArray') else [])
            row.update(df_children=edges, structural_children=copy.deepcopy(edges))
            facts['graph']['types'].append(row)
        union = dict(copy.deepcopy(decl), id=807, kind='union', fields=None, layout=None, state='incomplete', df_children=[], structural_children=[])
        facts['graph']['declarations'].append(union)
        facts['graph']['declaration_order'].append(807)
        scalars = ('Void Bool Short Long LongLong UShort UInt ULong ULongLong SChar UChar Double Float Int128 UInt128 Half').split()
        for ident, shape in enumerate(scalars, 20):
            facts['graph']['types'].append(dict(type_id=ident, native_shape=shape, kind=shape, df_children=[], structural_children=[]))
        unsupported = ('BFloat16 UnhandledSveType Float128 Int8 Int16 Int32 Int64 IntPtr UInt8 UInt16 UInt32 UInt64 UIntPtr IntMax UIntMax Size SSize PtrDiff WChar').split()
        for ident, shape in enumerate(unsupported, 50):
            facts['graph']['types'].append(dict(type_id=ident, native_shape=shape, unproved='missing or unsupported required type', df_children=[], structural_children=[]))
        extra_types = [
            ('Pointer', 'pointer', dict(pointee=q), [edge('type',1)]),
            ('Function', 'function', dict(return_=q, parameters=[q,q], variadic=False, noreturn=False, prototype=True, abi='C'), [edge('type',1)] * 3),
            ('Union', 'union', dict(declaration=807), [edge('declaration',807)]),
            ('BuiltinFn', 'builtin_function', dict(unproved='BuiltinFn requires a native endpoint relation'), []),
            ('LongDouble', 'LongDouble', dict(unproved='missing or unsupported required type'), []),
            ('TypeOfExpr', None, dict(expression=1001), [edge('expression',1001)]),
            ('Complex', None, dict(element_type=1), [edge('type',1)]),
            ('VariableArray', None, dict(element_type=1, count_expression=1001), [edge('type',1),edge('expression',1001)]),
            ('VariableArray', None, dict(element_type=1, count_expression=None), [edge('type',1)]),
            ('Attributed', 'attributed', dict(original=q,counted_by=1001), [edge('type',1),edge('expression',1001)]),
            ('Attributed', 'attributed', dict(original=q,counted_by=None), [edge('type',1)]),
        ]
        for shape in ('Reference', 'BlockPointer', 'Vector', 'Atomic'):
            extra_types.append((shape, None, dict(original=q), [edge('type',1)]))
        for shape, kind in (('TypeOf','typeof'), ('Paren','paren'), ('Elaborated','elaborated'), ('Decayed','decayed'), ('Auto','auto')):
            extra_types.append((shape, kind, dict(inner=1), [] if shape == 'Elaborated' else [edge('type',1)]))
        for ident, (shape, kind, fields, edges) in enumerate(extra_types, 80):
            row = dict(type_id=ident, native_shape=shape, df_children=edges, structural_children=copy.deepcopy(edges), **fields)
            if 'return_' in row: row['return'] = row.pop('return_')
            if kind is not None: row['kind'] = kind
            if shape in ('Reference','BlockPointer','Vector','Atomic','Attributed','TypeOfExpr','Complex','VariableArray'):
                row['unproved'] = 'missing or unsupported required type'
            facts['graph']['types'].append(row)
        extra_expressions = [
            ('Literal','literal',{},[],dict(literal={'character':65})),
            ('Literal','literal',{},[],dict(literal={'unsupported':True})),
            ('Literal','literal',{},[],dict(literal={'bytes':[65,0], 'width':2})),
            ('ArraySubscript','subscript',dict(left=1001,right=1001),[edge('expression',1001)]*2,{}),
            ('Conditional','unsupported',dict(condition=1001,then=1001,**{'else':1001}),[edge('expression',1001)]*3,{}),
            ('Choose','unsupported',dict(condition=1001,then=1001,**{'else':1001}),[edge('expression',1001)]*3,{}),
            ('BinaryConditional','unsupported',dict(left=1001,right=1001),[edge('expression',1001)]*2,{}),
            ('Call','call',dict(callee=1104,arguments=[1001]),[edge('expression',1104),edge('expression',1001)],{}),
            ('InitList','unsupported',dict(initializers=[1001,1001]),[edge('expression',1001)]*2,{}),
            ('ImplicitValueInit','unsupported',{},[],{}), ('DesignatedInitExpr','unsupported',{},[],{}),
            ('Atomic','unsupported',dict(ptr=1001,order=1001,val1=None,order_fail=None,val2=None,weak=None),[edge('expression',1001)]*2,{}),
            ('Statements','unsupported',dict(body=900),[edge('statement',900)],dict(statement_body=900)),
        ]
        for shape, kind in (('Paren','paren'), ('CompoundLiteral','unsupported'), ('ImaginaryLiteral','unsupported'), ('Predefined','unsupported'), ('VAArg','unsupported')):
            extra_expressions.append((shape,kind,dict(child=1001),[edge('expression',1001)],{}))
        for shape in ('ShuffleVector','ConvertVector'):
            extra_expressions.append((shape,'unsupported',dict(elements=[1001,1001]),[],{}))
        extra_expressions += [('OffsetOf','unsupported',dict(type=1,index=1001),[],{}), ('OffsetOf','unsupported',dict(type=None,index=None),[],{})]
        for ident, (shape, kind, operands, df, fields) in enumerate(extra_expressions, 1200):
            structural = copy.deepcopy(df)
            if shape in ('Paren','CompoundLiteral','ImaginaryLiteral','VAArg'): structural.insert(0,edge('type',1))
            elif shape in ('ShuffleVector','ConvertVector'): structural = [edge('expression',1001)]*2
            elif shape == 'OffsetOf' and operands['type'] is not None: structural = [edge('type',1),edge('expression',1001)]
            row = dict(copy.deepcopy(base), id=ident, native_shape=shape, kind=kind, operands=operands,
                       df_children=df, structural_children=structural, children=[e['id'] for e in structural if e['kind']=='expression'])
            row.pop('literal'); row.update(fields, edge_count=len(row['children']))
            facts['graph']['expressions'].append(row)
        statement_shapes = [
            ('Compound','compound',[('item','statement',900),('item','statement',900)]),
            ('Expr','expression',[('expression','expression',1001)]), ('Decls','declarations',[('declaration','declaration',806)]),
            ('ReturnValue','return',[('value','expression',1001)]), ('ReturnVoid','return',[]),
            ('If','branch',[('condition','expression',1001),('then','statement',900)]),
            ('IfElse','branch',[('condition','expression',1001),('then','statement',900),('else','statement',900)]),
            ('Switch','branch',[('condition','expression',1001),('body','statement',900)]),
            ('While','loop',[('condition','expression',1001),('body','statement',900)]),
            ('DoWhile','loop',[('body','statement',900),('condition','expression',1001)]),
            ('Label','label',[('body','statement',900)]), ('Default','label',[('body','statement',900)]),
            ('Case','label',[('value','expression',1001),('body','statement',900)]),
            ('Attributed','attributed',[('body','statement',900)]), ('Goto','goto',[]), ('Break','break',[]),
            ('Continue','continue',[]), ('Asm','unsupported',[('operand','expression',1001)]), ('BadStmt','unsupported',[])]
        for mask in range(8):
            roles = ([('init','statement',900)] if mask & 4 else [])
            roles += [('condition','expression',1001)] if mask & 2 else []
            roles += [('increment','expression',1001)] if mask & 1 else []
            statement_shapes.append(('ForLoop'+format(mask,'03b'),'loop',roles+[('body','statement',900)]))
        for ident, (shape, kind, roles) in enumerate(statement_shapes, 910):
            children = [dict(role=role,kind=target,id=ident) for role,target,ident in roles]
            edges = [dict(kind=e['kind'],id=e['id']) for e in children]
            facts['graph']['statements'].append(dict(copy.deepcopy(statement),id=ident,native_shape=shape,kind=kind,
                children=children,edge_count=len(children),df_children=edges,structural_children=copy.deepcopy(edges),label_target=920 if shape=='Goto' else None))
        for ident, shape, fields, edges in ((810,'NonCanonicalDecl',dict(canonical_decl=803),[edge('declaration',803)]),
                                            (811,'StaticAssert',dict(assert_expr=1001),[edge('expression',1001)]),
                                            (812,'MacroObject',{},[]),(813,'MacroFunction',{},[])):
            facts['graph']['declarations'].append(dict(id=ident,kind='unsupported',native_shape=shape,parameter_owners=[],diagnostic_location=None,
                df_children=edges,structural_children=copy.deepcopy(edges),**fields))
            facts['graph']['declaration_order'].append(ident)
        function_type = dict(type_id=150,kind='function',native_shape='Function',parameters=[],variadic=False,noreturn=False,prototype=True,abi='C',
                             df_children=[edge('type',1)],structural_children=[edge('type',1)],**{'return':q})
        facts['graph']['types'].append(function_type)
        function_key = dict(q,type_id=150)
        facts['graph']['qualified_types'].append(dict(source=function_key,path=[150],normalized=function_key))
        function = dict(id=808,kind='function',type_id=150,qualified_type=function_key,parameters=[],va_parameters=[],builtin=None,
                        symbol={'unit':facts['unit'],'static':'local_function'},aliases=[],body=None,parameter_owners=[],diagnostic_location=None,
                        df_children=[edge('type',150)],structural_children=[edge('type',150)])
        facts['graph']['declarations'].append(function)
        facts['graph']['declaration_order'].append(808)
        graph = F.ReportGraph(copy.deepcopy(facts))
        self.assertEqual(graph.expression(1101)['member'], typedef)
        self.assertEqual(graph.expression(1100)['type'], None)
        self.assertEqual(graph.relations['statement', 924].required, ())
        self.assertEqual(graph.relations['statement', 924].references, ({'kind':'statement','id':920},))
        rows = [(table, index) for table in ('types', 'expressions', 'statements', 'declarations')
                for index in range(len(facts['graph'][table]))]
        for table, index in rows:
            row = facts['graph'][table][index]
            for field in row:
                for change in ('missing', 'null', 'bool'):
                    nullable = table == 'expressions' and field == 'field' or table == 'declarations' and field == 'layout'
                    if change == 'null' and (row[field] is None or nullable) or change == 'bool' and type(row[field]) is bool: continue
                    changed = copy.deepcopy(facts)
                    target = changed['graph'][table][index]
                    if change == 'missing': target.pop(field)
                    else: target[field] = None if change == 'null' else True
                    with self.subTest(table=table, shape=row.get('native_shape', row.get('kind')), field=field, change=change):
                        with self.assertRaises((F.FactsError, KeyError, TypeError, ValueError)):
                            F.ReportGraph(changed)
            candidates = {field:value for peer in facts['graph'][table] for field,value in peer.items() if field not in row}
            for field,value in candidates.items():
                changed = copy.deepcopy(facts)
                changed['graph'][table][index][field] = copy.deepcopy(value)
                with self.subTest(table=table, transplant=field, shape=row.get('native_shape',row.get('kind'))):
                    with self.assertRaises((F.FactsError,KeyError,TypeError,ValueError)): F.ReportGraph(changed)
            changed = copy.deepcopy(facts)
            changed['graph'][table][index]['future_operand'] = q
            with self.assertRaises(F.FactsError): F.ReportGraph(changed)
        for table, ident, field_name, value in (
            ('expressions',1101,'member',{'id':999999}), ('expressions',1101,'member',{'id':True}),
            ('expressions',1101,'member',{'id':803,'extra':1}), ('expressions',1102,'field',803),
            ('expressions',1102,'field',1001), ('expressions',1102,'field',999999),
            ('expressions',1104,'decl',1001), ('types',8,'declaration',803),
            ('declarations',805,'owning_enum',{'declaration':800,'identity':unknown}),
            ('declarations',802,'owners',[{'unproved':'different'}]),
            ('declarations',806,'type',{'unproved':'different'}),
            ('declarations',806,'type',dict(view, const=0)),
            ('types',1,'inner',1), ('expressions',1105,'qualified_type',None),
        ):
            changed = copy.deepcopy(facts)
            key = 'type_id' if table == 'types' else 'id'
            next(r for r in changed['graph'][table] if r[key] == ident)[field_name] = value
            with self.subTest(table=table, ident=ident, field=field_name, value=value):
                with self.assertRaises((F.FactsError, KeyError, TypeError, ValueError)): F.ReportGraph(changed)
        repeated = copy.deepcopy(facts)
        record = next(d for d in repeated['graph']['declarations'] if d['id']==800)
        record['fields'] *= 2; record['df_children'] *= 2; record['structural_children'] *= 2
        next(d for d in repeated['graph']['declarations'] if d['id']==802)['owners'] *= 2
        F.ReportGraph(repeated)
        for builtin_id in (0, 2 ** 64 - 1):
            valid = copy.deepcopy(facts)
            next(d for d in valid['graph']['declarations'] if d['id']==808)['builtin'] = [builtin_id,'unknown']
            F.ReportGraph(valid)
        for builtin_id in (True, False, -1, 2 ** 64):
            invalid = copy.deepcopy(facts)
            next(d for d in invalid['graph']['declarations'] if d['id']==808)['builtin'] = [builtin_id,'unknown']
            with self.assertRaisesRegex(F.FactsError,'invalid builtin identity'): F.ReportGraph(invalid)
        physical = dict(kind='struct',tag=None,physical=dict(path='/native/fixture.c',line=1,column=1),scope={'file':True})
        physical_facts = copy.deepcopy(facts)
        next(d for d in physical_facts['graph']['declarations'] if d['id']==800)['identity'] = physical
        next(d for d in physical_facts['graph']['declarations'] if d['id']==802)['owners'] = [physical]
        F.ReportGraph(physical_facts)
        for field,value in (('path','relative.c'),('line',True),('line',0),('column',None)):
            changed = copy.deepcopy(physical_facts)
            next(d for d in changed['graph']['declarations'] if d['id']==800)['identity']['physical'][field] = value
            with self.assertRaises((F.FactsError,KeyError,TypeError,ValueError)): F.ReportGraph(changed)
        changed = copy.deepcopy(facts)
        next(d for d in changed['graph']['declarations'] if d['id']==808)['symbol']['unit'] = '/native/other.c'
        with self.assertRaisesRegex(F.FactsError,'raw static symbol unit'): F.ReportGraph(changed)
        changed = copy.deepcopy(facts)
        changed['graph']['types'][0]['inner'] = 1
        with self.assertRaisesRegex(F.FactsError, 'raw constructor fields'): F.ReportGraph(changed)

    def test_record_physical_position_unsigned_range(self):
        import copy
        identity = dict(kind='struct', tag=None,
                        physical=dict(path='/native/fixture.c', line=1, column=1), scope={'file': True})
        record = dict(id=800, kind='struct', identity=identity, native_va_list_record=False,
                      fields=[], layout=None, state='complete', diagnostic_location=None,
                      parameter_owners=[], df_children=[], structural_children=[])
        facts = dict(unit='/native/fixture.c', graph=dict(types=[], qualified_types=[], expressions=[],
                     statements=[], declarations=[record], declaration_order=[800]))
        for nested in (False, True):
            legal = copy.deepcopy(facts)
            target = legal['graph']['declarations'][0]['identity']
            if nested:
                target['scope'] = {'record': copy.deepcopy(identity)}
                target = target['scope']['record']
            F.ReportGraph(legal)
            for field in ('line', 'column'):
                for value in (1, 2 ** 64 - 1, 0, -1, True, False, 2 ** 64, '1', 1.0, None):
                    changed = copy.deepcopy(legal)
                    position = changed['graph']['declarations'][0]['identity']
                    if nested: position = position['scope']['record']
                    position['physical'][field] = value
                    with self.subTest(nested=nested, field=field, value=value):
                        if type(value) is int and 0 < value < 2 ** 64:
                            F.ReportGraph(changed)
                        else:
                            reason = 'invalid record physical position' if type(value) is int and value == 0 else 'invalid raw integer'
                            with self.assertRaisesRegex(F.FactsError, reason): F.ReportGraph(changed)

    def test_qualified_normalization_flags_and_coordinated_peers(self):
        import copy
        flags = ('const', 'volatile', 'restrict')
        def q(ident, values):
            return dict(type_id=ident, **dict(zip(flags, values)))
        def fixture(types, qualified, declarations=()):
            return dict(unit='/native/qualifiers.c', graph=dict(types=types, qualified_types=qualified,
                        declarations=list(declarations), declaration_order=[d['id'] for d in declarations],
                        expressions=[], statements=[]))
        scalar = dict(type_id=1, native_shape='Int', kind='Int', df_children=[], structural_children=[])
        for mask in range(8):
            source = q(1, tuple(bool(mask & bit) for bit in (4, 2, 1)))
            facts = fixture([scalar], [dict(source=source, path=[1], normalized=copy.deepcopy(source))])
            F.ReportGraph(facts)
            for flag in flags:
                changed = copy.deepcopy(facts)
                changed['graph']['qualified_types'][0]['normalized'][flag] = not source[flag]
                with self.subTest(shape='scalar', mask=mask, flag=flag):
                    with self.assertRaisesRegex(F.FactsError, 'normalized terminal'):
                        F.ReportGraph(changed)
        for shape, kind in (('TypeOf', 'typeof'), ('Paren', 'paren'), ('Elaborated', 'elaborated'),
                            ('Decayed', 'decayed'), ('Auto', 'auto')):
            children = [] if shape == 'Elaborated' else [dict(kind='type', id=1)]
            wrapper = dict(type_id=2, native_shape=shape, kind=kind, inner=1,
                           df_children=children, structural_children=children)
            source, terminal = q(2, (True, False, True)), q(1, (True, False, True))
            facts = fixture([scalar, wrapper], [dict(source=source, path=[2, 1], normalized=terminal)])
            F.ReportGraph(facts)
            for flag in flags:
                changed = copy.deepcopy(facts)
                changed['graph']['qualified_types'][0]['normalized'][flag] = not terminal[flag]
                with self.subTest(shape=shape, flag=flag):
                    with self.assertRaisesRegex(F.FactsError, 'normalized terminal'):
                        F.ReportGraph(changed)
        original = q(1, (True, False, True))
        typedef = dict(type_id=2, native_shape='Typedef', kind='typedef', declaration=803, original=original,
                       df_children=[dict(kind='declaration', id=803)], structural_children=[dict(kind='declaration', id=803)])
        declaration = dict(id=803, kind='typedef', type_id=1, qualified_type=original, parameter_owners=[],
                           diagnostic_location=None, df_children=[dict(kind='type', id=1)], structural_children=[dict(kind='type', id=1)])
        source, terminal = q(2, (False, True, False)), q(1, (True, True, True))
        facts = fixture([scalar, typedef], [dict(source=original, path=[1], normalized=copy.deepcopy(original)),
                        dict(source=source, path=[2, 1], normalized=terminal)], [declaration])
        F.ReportGraph(facts)
        for flag in flags:
            changed = copy.deepcopy(facts)
            changed['graph']['qualified_types'][1]['normalized'][flag] = False
            with self.subTest(shape='typedef', flag=flag):
                with self.assertRaisesRegex(F.FactsError, 'normalized terminal'):
                    F.ReportGraph(changed)

        def legal(data, shape):
            facts = data['on/0/blob.closed-format.json']
            if shape == 'typedef':
                self.qualified_path_positive(data)
                graph = facts['graph']
                next(t for t in graph['types'] if t['type_id'] == 5)['original']['restrict'] = True
                next(row for row in graph['qualified_types'] if row['source']['type_id'] == 6)['normalized']['restrict'] = True
                self.refresh_graph_views(data, prepare=False)
                return 6
            graph = facts['graph']
            source = q(150, (True, False, True))
            row = dict(type_id=150, native_shape='Int' if shape == 'scalar' else 'Elaborated',
                       kind='Int' if shape == 'scalar' else 'elaborated', df_children=[], structural_children=[])
            if shape == 'wrapper': row['inner'] = 1
            graph['types'].append(row)
            graph['qualified_types'].append(dict(source=source, path=[150] if shape == 'scalar' else [150, 1],
                                                 normalized=q(150 if shape == 'scalar' else 1, (True, False, True))))
            next(e for e in graph['expressions'] if e['id'] == 9900000).update(type_id=150, qualified_type=source)
            self.refresh_graph_views(data, prepare=False)
            return 150
        for shape in ('scalar', 'wrapper', 'typedef'):
            self.reject_coordinated(lambda data, shape=shape: legal(data, shape), None)
            for flag in flags:
                def contradict(data, shape=shape, flag=flag):
                    ident = legal(data, shape)
                    facts = data['on/0/blob.closed-format.json']
                    projection = F.ReportGraph(facts)
                    row = next(row for row in facts['graph']['qualified_types'] if row['source']['type_id'] == ident)
                    row['normalized'][flag] = not row['normalized'][flag]
                    self.refresh_graph_views(data, prepare=False, projection_graph=projection)
                with self.subTest(shape=shape, flag=flag):
                    self.reject_coordinated(contradict, 'normalized terminal disconnected from source qualified type')

    def test_closed_boundary_four_complete_coordinated_contradictions(self):
        for case, reason in enumerate(('raw constructor fields', 'invalid source qualified key',
                                       'raw declaration reference missing', 'raw declaration reference missing')):
            def mutate(data, case=case):
                import copy
                facts = data['on/0/blob.closed-format.json']
                if case == 0:
                    for rows in (facts['graph']['types'], facts['types']):
                        next(r for r in rows if r['type_id'] == 1)['inner'] = 4
                    facts['types'].append(copy.deepcopy(next(r for r in facts['graph']['types'] if r['type_id'] == 4)))
                else:
                    row = next(e for e in facts['graph']['expressions'] if e['id'] == 9900000)
                    if case == 1:
                        row.update(qualified_type=None, type_id=None)
                        facts['unsupported_expressions'][0]['type'] = None
                    else:
                        row.update(kind='member' if case == 2 else 'implicit_cast', native_shape='Member' if case == 2 else 'ImplicitCast', operands={'child':1001})
                        if case == 2: row.update(member={'id':999999999}, access='Dot')
                        else: row.update(cast='NoOp', field=999999999, structural_children=[F.ReportGraph.edge('type',1), F.ReportGraph.edge('expression',1001)])
                        facts['unsupported_expressions'] = []
                        facts['unsupported_expression_count'] = 0
            self.reject_coordinated(mutate, reason)

    def test_closed_boundary_coordinated_metadata_and_legal_neighbors(self):
        import copy
        name = 'on/0/blob.closed-format.json'
        def legal(data, shape):
            facts = data[name]
            row = next(e for e in facts['graph']['expressions'] if e['id'] == 9900000)
            if shape == 'BadExpr':
                row.update(native_shape='BadExpr', operands={}, qualified_type=None, type_id=None, va_list=None,
                           children=[], edge_count=0, df_children=[], structural_children=[],
                           type_unproved='importer expression has no qualified type')
            elif shape == 'Member':
                row.update(kind='member', native_shape='Member', operands={'child':1001}, member={'id':1}, access='Dot')
            else:
                row.update(kind='implicit_cast', native_shape='ImplicitCast', operands={'child':1001}, field=None, cast='NoOp',
                           structural_children=[F.ReportGraph.edge('type', 1), F.ReportGraph.edge('expression', 1001)])
            if shape == 'ImplicitCast':
                next(d for d in facts['graph']['declarations'] if d['id']==1)['builtin'] = [0,'unknown']
            self.refresh_graph_views(data, prepare=False)
        for shape in ('BadExpr', 'Member', 'ImplicitCast'):
            self.reject_coordinated(lambda data, shape=shape: legal(data, shape), None)
        def native(data):
            facts = data[name]
            row = next(d for d in facts['graph']['declarations'] if d['id'] == 500)
            canonical = copy.deepcopy(row['type'])
            row['native_va_list'] = dict(same_canonical_type=True, target_kind=5)
            for prefix in ('declared', 'builtin'):
                row['native_va_list'].update({prefix + '_type_id':1, prefix + '_canonical_type':canonical,
                                              prefix + '_const':False, prefix + '_volatile':False, prefix + '_restrict':False})
            self.refresh_graph_views(data, prepare=False)
        self.reject_coordinated(native, None)
        cases = [
            ('expression primitive', lambda f: next(e for e in f['graph']['expressions'] if e['id'] == 9900000).__setitem__('va_list', 0), 'expression source qualified'),
            ('expression missing key', lambda f: next(e for e in f['graph']['expressions'] if e['id'] == 9900000).pop('diagnostic_location'), 'raw constructor fields'),
            ('unsupported forbidden field', lambda f: next(e for e in f['graph']['expressions'] if e['id'] == 9900000).__setitem__('decl', 1), 'raw constructor fields'),
            ('function aliases', lambda f: next(d for d in f['graph']['declarations'] if d['kind'] == 'function').__setitem__('aliases', [None]), 'invalid function aliases'),
            ('function builtin', lambda f: next(d for d in f['graph']['declarations'] if d['kind'] == 'function').__setitem__('builtin', [True, 'va_copy']), 'invalid builtin identity'),
            ('statement nested extra', lambda f: f['graph']['statements'][0]['flow'].__setitem__('extra', 1), 'Unproved record'),
            ('statement missing key', lambda f: f['graph']['statements'][0].pop('label_target'), 'raw constructor fields'),
            ('qualified extra', lambda f: f['graph']['qualified_types'][0]['source'].__setitem__('extra', False), 'invalid source qualified key'),
            ('normalization bool', lambda f: f['graph']['qualified_types'][0]['path'].__setitem__(0, True), 'invalid normalization path'),
            ('raw source bytes', lambda f: next(e for e in f['graph']['expressions'] if e['id'] == 9900000)['location']['spelling'].__setitem__('bytes_hex', '00'), 'quoted physical source bytes differ'),
        ]
        for label, change, reason in cases:
            def mutate(data, change=change):
                facts = data[name]
                change(facts)
                declarations = {r['id']:r for r in facts['graph']['declarations']}
                statements = {r['id']:r for r in facts['graph']['statements']}
                facts['variables'] = [copy.deepcopy(declarations[r['id']]) for r in facts['variables']]
                facts['statements'] = [copy.deepcopy(statements[r['id']]) for r in facts['statements']]
                for rows in (facts['declarations'],data['on/0/blob.variadic.json']['declarations']):
                    for row in rows: row['aliases'] = copy.deepcopy(declarations[row['id']]['aliases'])
                for row in facts['expressions']:
                    if row['kind']=='call' and row['callee_decl'] is not None: row['builtin'] = copy.deepcopy(declarations[row['callee_decl']]['builtin'])
                expressions = {r['id']:r for r in facts['expressions']}
                for event in facts['cursor_events']: event['builtin'] = copy.deepcopy(expressions[event['expression']]['builtin'])
                raw = {r['id']:r for r in facts['graph']['expressions']}
                for row in facts['unsupported_expressions']: row['location'] = copy.deepcopy(raw[row['expression']]['location'])
            with self.subTest(category=label): self.reject_coordinated(mutate, reason)
        for mode, reason in (('copy', 'native cursor qualified projection'), ('bool', 'invalid source qualified key'),
                             ('missing', 'raw constructor fields'), ('type', 'invalid source qualified key')):
            def contradict(data, mode=mode):
                native(data)
                for rows in (data[name]['graph']['declarations'], data[name]['variables']):
                    row = next(r for r in rows if r['id'] == 500)['native_va_list']
                    if mode == 'copy': row['declared_canonical_type']['const'] = 0
                    elif mode == 'bool': row['declared_type_id'] = True
                    elif mode == 'missing': row.pop('builtin_restrict')
                    else: row['declared_type_id'] = 1001
            self.reject_coordinated(contradict, reason)
        def member_wrong_table(data):
            legal(data, 'Member')
            next(e for e in data[name]['graph']['expressions'] if e['id'] == 9900000)['member']['id'] = 1001
        self.reject_coordinated(member_wrong_table, 'raw declaration reference missing')
        def field_wrong_kind(data):
            legal(data, 'ImplicitCast')
            next(e for e in data[name]['graph']['expressions'] if e['id'] == 9900000)['field'] = 1
        self.reject_coordinated(field_wrong_kind, 'raw declaration reference kind')

    def test_old_facts_schema_is_rejected(self):
        self.reject_coordinated(lambda data: data['on/0/blob.closed-format.json'].__setitem__('schema', 1),
                                'not a complete report-only compiler record')

    def test_raw_ast_replacement_with_refreshed_pairs_and_seal_rejects(self):
        for name in ('on/0/blob.cursor.cbor', 'on/0/blob.typed-ast.txt'):
            self.reject_coordinated(lambda d: d.__setitem__(name, b'replacement with fresh pair digests'), 'compiler session')

    def test_missing_extra_corrupt_and_changed_rust_members_reject(self):
        for name, data in [('extra', b'extra'), ('on/0/blob.rs', b'changed generated Rust'),
                           ('on/0/blob.cursor.cbor', b'corrupt CBOR')]:
            path = self.root / name
            original = path.read_bytes() if path.exists() else None
            path.write_bytes(data)
            try:
                with self.assertRaises(F.FactsError):
                    F.replay(self.root)
            finally:
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)
        path = self.root / 'on/0/blob.rs'
        original = path.read_bytes()
        path.write_bytes(b'changed generated Rust')
        (self.root / 'seal.json').write_text(json.dumps(F.manifest(self.root)))
        try:
            with self.assertRaises(F.FactsError):
                F.replay(self.root)
        finally:
            path.write_bytes(original)
            (self.root / 'seal.json').write_text(json.dumps(F.manifest(self.root)))

    def test_normal_and_optimized_default_replay_and_real_effect_guards(self):
        code = '''import json,os,socket,subprocess,sys
from pathlib import Path
import closed_format_facts as f
sys.addaudithook(f.guard)
print(json.dumps(f.replay(Path(sys.argv[1])),sort_keys=True))
for effect in (lambda: Path(sys.argv[1]+'/forbidden').write_bytes(b'x'),
               lambda: os.mkdir(sys.argv[1]+'/forbidden-dir'),
               lambda: subprocess.Popen([sys.executable,'-c','pass']),
               lambda: socket.socket()):
    try: effect()
    except f.FactsError: continue
    raise RuntimeError('real effect guard failed')
print('four real effects denied')
'''
        outputs = []
        for optimized in (False, True):
            command = [sys.executable, '-B', *(['-O'] if optimized else []), '-c', code, str(self.root)]
            run = subprocess.run(command, cwd=Path(__file__).parent, capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            outputs.append(run.stdout)
        self.assertEqual(outputs[0], outputs[1])
        self.assertIn('four real effects denied', outputs[0])
        self.assertFalse((self.root / 'forbidden').exists())
        self.assertFalse((self.root / 'forbidden-dir').exists())

    def test_duplicate_json_keys_and_unsafe_paths_reject(self):
        with self.assertRaises(F.FactsError):
            F.loads('{"id":1,"id":2}')
        for name in ('../escape', '/absolute', 'on/../off/0/blob.rs', 'on\\0.rs'):
            with self.assertRaises(F.FactsError):
                F.safe_file(self.root, name)


if __name__ == '__main__':
    unittest.main()
