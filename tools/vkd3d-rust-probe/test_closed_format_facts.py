import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import closed_format_facts as F
from full_compiler import UNITS


def constructor_fixture_fields(graph):
    mapping = {'pointer': 'Pointer', 'function': 'Function', 'array': 'ConstantArray', 'struct': 'Struct',
               'union': 'Union', 'enum': 'Enum', 'typedef': 'Typedef', 'typeof': 'TypeOf', 'paren': 'Paren',
               'elaborated': 'Elaborated', 'decayed': 'Decayed', 'auto': 'Auto', 'attributed': 'Attributed',
               'builtin_function': 'BuiltinFn'}
    for row in graph['types']:
        row.setdefault('native_shape', mapping.get(row.get('kind'), row.get('kind')))
        if row['native_shape'] == 'Attributed':
            row.setdefault('counted_by', None)
    for row in graph['declarations']:
        if row['kind'] == 'variable':
            row.setdefault('initializer', None)
    for row in graph['expressions']:
        shape, children = row['native_shape'], row['children']
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
    commands = [{'file': '/native/' + unit, 'directory': '/native',
                 'arguments': ['/usr/lib/llvm-18/bin/clang', '-DHAVE_CONFIG_H', '-I/native/include', '-c', '/native/' + unit]} for unit in UNITS]
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
    for index, command in enumerate(commands):
        unit = command['file']
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
        native = {'schema': 2, 'main_input': unit, 'cwd': '/native', 'adjusted_driver_argv': command['arguments'] + ['-fno-builtin-strlen', '-fparse-all-comments', '-Wwrite-strings',
                      '-D_FORTIFY_SOURCE=0', '-DC2RUST=1', '-resource-dir=/usr/lib/llvm-18/bin/../lib/clang/18', '-fsyntax-only'],
                  'regenerated_cc1_argv': ['-x', 'c', unit, '-triple', 'x86_64-pc-linux-gnu', '-resource-dir',
                      '/usr/lib/llvm-18/bin/../lib/clang/18', '-fdebug-compilation-dir=/native'], 'target': 'x86_64-pc-linux-gnu', 'cpu': '', 'abi': '',
                  'features': [], 'features_as_written': [], 'vfs': 'clangtool_empty_overlay_on_real_filesystem',
                  'unsupported': [], 'lexer_events': [{'file_id': str(i), 'reason': 'enter', 'characteristic': 0} for i in (1, 2)],
                  'buffers': [{'role': 'main', 'identifier': unit, 'physical_path': unit, 'aliases': [unit],
                               'native_device': '1', 'native_file': '1', 'length': len(buffers), 'bytes_hex': buffers.hex(),
                               'sha256': checksum, 'lexed': True, 'lexer_file_ids': ['1']},
                              {'role': 'predefines', 'identifier': '<built-in>', 'physical_path': '', 'aliases': [],
                               'native_device': '0', 'native_file': '0', 'length': 0, 'bytes_hex': '', 'sha256': F.sha(b''),
                               'lexed': True, 'lexer_file_ids': ['2']}]}
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
                'cbor': 'on/' + prefix + '.cursor.cbor', 'typed_ast': 'on/' + prefix + '.typed-ast.txt',
                'rust_on': 'on/' + prefix + '.rs', 'rust_off': 'off/' + prefix + '.rs'}
        facts['compiler_session'] = {'raw_cbor_sha256': F.sha(b'synthetic binding, not actual AST'),
                                     'typed_ast_sha256': F.sha(b'synthetic binding, not actual AST')}
        write(pair['facts'], facts); write(pair['inventory'], inventory)
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
    packet = {'schema': 1, 'authorization': 'analysis_only', 'units': units,
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
        cls.root = Path(cls.directory.name)
        cls.packet = synthetic_packet_fixture(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_complete_transport_is_distinct_from_lowerability(self):
        result = F.replay(self.root)
        self.assertEqual(result['incoming_calls'], 4865)
        self.assertEqual(result['lowerability'], 'blocked')
        self.assertEqual(result['public_callback'], 'unproved')

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
    def refresh_graph_views(data, *, prepare=True, validate=True):
        import copy
        facts = data['on/0/blob.closed-format.json']
        if prepare:
            constructor_fixture_fields(facts['graph'])
        if validate:
            graph = F.ReportGraph(facts)
        else:
            from unittest.mock import patch
            with patch.object(F.ReportGraph, 'check_raw_constructors'):
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
        declaration = dict(id=804, kind='variable', type_id=2,
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
                row.update(kind='unary_type', argument_qualified_type=base['qualified_type'],
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
