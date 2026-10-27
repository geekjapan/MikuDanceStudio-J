import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import closed_format_facts as F
from full_compiler import UNITS


def packet_fixture(root):
    """Synthetic transport fixture. It is never compiler or hosted evidence."""
    def write(name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    typ = {'canonical': {'kind': 'Int'}, 'const': False, 'volatile': False, 'restrict': False}
    symbol = lambda i: {'linker': 'function_' + str(i)}
    commands = [{'file': '/native/' + unit, 'directory': '/native',
                 'arguments': ['/clang', '-resource-dir', '/clang-resource', '-c', '/native/' + unit]} for unit in UNITS]
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
                         'va_parameters': parameters[1:], 'signature': typ})
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
                variables.extend({'id': p, 'type_id': 1} for p in parameters)
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
                {'id': raw['id'], 'kind': 'call', 'children': [raw['id'] + 1, raw['id'] + 2],
                 'location': location, 'type_id': 1, 'promotion_chain': [typ], 'arguments': args,
                 'callee_decl': target + 1, 'builtin': None},
                {'id': raw['id'] + 1, 'kind': 'literal', 'literal': {'bytes': [37, 100], 'width': 1},
                 'children': [], 'location': location, 'type_id': 1, 'promotion_chain': [typ]},
                {'id': raw['id'] + 2, 'kind': 'literal', 'literal': {'integer': 1},
                 'children': [], 'location': location, 'type_id': 1, 'promotion_chain': [typ]}])
            events.append({'expression': raw['id'], 'builtin': None, 'callee_declaration': target + 1, 'operands': args, 'relation': unresolved})
        native = {'schema': 2, 'main_input': unit, 'cwd': '/native', 'adjusted_driver_argv': command['arguments'],
                  'regenerated_cc1_argv': ['-cc1'], 'target': 'x86_64-pc-linux-gnu', 'cpu': '', 'abi': '',
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
        for row in [*statements, *expressions]:
            row['edge_count'] = len(row['children'])
        function_edges = [{'declaration': i + 1, 'parameters': [500 + i] + ([600 + i] if i >= 33 else []),
                           'fixed_count': 1 if i < 33 else 2, 'format_position': 0, 'format_parameter': 500 + i} for i in range(40)]
        facts = dict(inventory, schema=1, authorization='analysis_only', status='CompleteReport', lowering='not_authorized',
                     calls=calls, definitions=definitions, unclassified_definitions=extra, native_inputs=native,
                     expressions=expressions, statements=statements, variables=variables,
                     types=[{'type_id': 1, 'kind': 'Int'}], cursor_events=events, function_edges=function_edges,
                     unsupported_expression_count=1, unsupported_expressions=[{'expression': 9900000,
                         'native_shape': 'Atomic', 'within_slice': False, 'location': location, 'relevance': unresolved}])
        prefix = str(index) + '/' + Path(UNITS[index]).stem.replace('.', '_')
        pair = {'unit': unit, 'facts': 'on/' + prefix + '.closed-format.json', 'inventory': 'on/' + prefix + '.variadic.json',
                'cbor': 'on/' + prefix + '.cursor.cbor', 'typed_ast': 'on/' + prefix + '.typed-ast.txt',
                'rust_on': 'on/' + prefix + '.rs', 'rust_off': 'off/' + prefix + '.rs'}
        write(pair['facts'], facts); write(pair['inventory'], inventory)
        for field in ('cbor', 'typed_ast'):
            write(pair[field], b'synthetic binding, not actual AST')
        for mode in ('on', 'off'):
            write(pair['rust_' + mode], b'// synthetic fixture\n')
        pair['files'] = {name: F.sha((root / value).read_bytes()) for name, value in pair.items() if name != 'unit'}
        units.append(pair)
    write('compile_commands.json', commands); write('native-files.json', native_files); write('inventory-plan.json', plan)
    write('tool/compiler', b'synthetic compiler identity, never executable')
    write('tool/patch', b'synthetic patch')
    evidence = {'patch_sha256': F.sha(b'synthetic patch')}
    write('tool/evidence.json', evidence)
    write('tool/receipt.json', {'patch_sha256': evidence['patch_sha256'],
         'source_receipt_sha256': F.sha((root / 'tool/evidence.json').read_bytes()),
         'binary_sha256': {'c2rust-transpile': F.sha((root / 'tool/compiler').read_bytes())}})
    argv = ['/compiler', '--output-dir', '/same/emitted', '/database']
    verifier_sources = {}
    for name in ('closed_format_facts.py', 'full_compiler.py', 'probe.py'):
        write('verifier-source/' + name, Path(__file__).with_name(name).read_bytes())
        verifier_sources[name] = 'verifier-source/' + name
    packet = {'schema': 1, 'authorization': 'analysis_only', 'units': units,
              'database': 'compile_commands.json', 'native_files': 'native-files.json', 'inventory_plan': 'inventory-plan.json',
              'verifier_sources': verifier_sources,
              'tool': {'compiler': 'tool/compiler', 'patch': 'tool/patch', 'source_receipt': 'tool/receipt.json', 'source_evidence': 'tool/evidence.json'},
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
        cls.packet = packet_fixture(cls.root)

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
            ('tool/receipt.json', lambda d: d.__setitem__('patch_sha256', '0' * 64)),
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
