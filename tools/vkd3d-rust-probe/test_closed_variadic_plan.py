import unittest
import json
from pathlib import Path
import tempfile

from closed_variadic_plan import PlanError, build_plan, collect_probe, promoted_slot


def scalar(kind):
    return {'canonical': {'kind': kind}, 'const': False, 'volatile': False, 'restrict': False}


def inventory(unit, definition=False):
    signature = {'canonical': {'return': scalar('Int'), 'parameters': [scalar('Int')],
                              'variadic': True, 'noreturn': False, 'prototype': True, 'abi': 'C'},
                 'const': False, 'volatile': False, 'restrict': False}
    return {'schema': 2, 'record_evidence_schema': 2, 'record_definitions': [], 'authorization': 'inventory_only', 'unit': unit, 'target': 'x86_64-unknown-linux-gnu',
            'target_c_widths_bits': {'char': 8, 'short': 16, 'int': 32, 'long': 64, 'long_long': 64, 'pointer': 64, 'float': 32, 'double': 64},
            'declarations': [{'id': 1, 'symbol': {'linker': 'format'}, 'location': unit + ':1',
                              'signature': signature, 'definition': definition, 'va_parameters': []}],
            'calls': [], 'non_call_references': [], 'va_arg': []}


class ClosedPlanTests(unittest.TestCase):
    def plan(self, a=None, b=None, exports=()):
        return build_plan([a or inventory('definition.c', True), b or inventory('caller.c')],
                          ['definition.c', 'caller.c'], exports)

    def test_actual_blob_unproved_definitions_are_retained(self):
        # Run 40465179935 blob.variadic.json SHA256 4e21d31be92241e67ef940729e140b8e1465d9121aba135a15e1e3eb1258b8ab.
        unit = '/home/runner/work/_temp/vkd3d-probe/evidence/result/source/libs/vkd3d-common/blob.c'
        item = inventory(unit, True)
        item['declarations'] = [
            {'aliases': [], 'definition': True, 'id': ident,
             'location': '(fileid 39) ' + unit + ':' + str(line) + ':1',
             'signature': {'unproved': 'attributed type facts'},
             'symbol': {'static': name, 'unit': unit}, 'va_parameters': []}
            for ident, line, name in [
                (86884, 101, 'vkd3d_blob_GetBufferSize'),
                (86952, 92, 'vkd3d_blob_GetBufferPointer'),
                (87002, 75, 'vkd3d_blob_Release'),
                (87129, 65, 'vkd3d_blob_AddRef'),
                (87199, 47, 'vkd3d_blob_QueryInterface')]]
        plan = build_plan([item], [unit], [])
        self.assertEqual(plan['symbols'], [])
        unknown = plan['unclassified_definitions']
        self.assertEqual([d['id'] for d in unknown], [86884, 86952, 87002, 87129, 87199])
        for original, retained in zip(item['declarations'], unknown):
            self.assertEqual(retained['signature'], original['signature'])
            self.assertEqual(retained['unit'], unit)
            self.assertEqual(retained['name'], original['symbol']['static'])
            self.assertEqual(retained['location'], original['location'])
            self.assertEqual(retained['reason'], 'attributed type facts')
        self.assertEqual([d['code'] for d in plan['diagnostics']],
                         ['candidate_signature_unproved'] * 5)

    def test_unknown_definition_eligibility_and_calls_fail_closed(self):
        for va_parameters in ([], [0]):
            with self.subTest(va_parameters=va_parameters):
                a, b = inventory('definition.c', True), inventory('caller.c')
                for item in (a, b):
                    item['declarations'][0]['signature'] = {'unproved': 'attributed type facts'}
                a['declarations'][0]['va_parameters'] = va_parameters
                b['calls'] = [{'id': 9, 'owner': None, 'callee': {'linker': 'format'},
                               'location': 'caller.c:9', 'arguments': []}]
                plan = self.plan(a, b)
                self.assertEqual(plan['symbols'], [])
                self.assertEqual(len(plan['unclassified_definitions']), 1)
                self.assertIn('call_signature_unproved', [d['code'] for d in plan['diagnostics']])
                self.assertNotIn('signature_mismatch', [d['code'] for d in plan['diagnostics']])

    def test_alias_call_to_unknown_definition_has_no_slots(self):
        a, b = inventory('definition.c', True), inventory('caller.c')
        a['declarations'][0]['signature'] = {'unproved': 'attributed type facts'}
        b['declarations'][0].update(symbol={'linker': 'alias'}, aliases=['format'])
        b['calls'] = [{'id': 9, 'owner': None, 'callee': {'linker': 'alias'},
                       'location': 'caller.c:9', 'arguments': [{'type': scalar('Double')}]}]
        plan = self.plan(a, b)
        self.assertEqual(plan['symbols'], [])
        self.assertIn('call_signature_unproved', [d['code'] for d in plan['diagnostics']])

    def test_unknown_competing_definition_blocks_call_slots(self):
        a, b = inventory('definition.c', True), inventory('caller.c', True)
        b['declarations'][0]['signature'] = {'unproved': 'attributed type facts'}
        b['calls'] = [{'id': 9, 'owner': None, 'callee': {'linker': 'format'},
                       'location': 'caller.c:9', 'arguments': [{'type': scalar('Int')}]}]
        plan = self.plan(a, b)
        self.assertEqual(len(plan['symbols']), 1)
        self.assertEqual(len(plan['unclassified_definitions']), 1)
        self.assertEqual(plan['symbols'][0]['calls'], [])
        self.assertTrue({'multiple_definitions', 'candidate_signature_unproved',
                         'call_signature_unproved'} <= {d['code'] for d in plan['diagnostics']})

    def test_unproved_declaration_cannot_match_known_candidate(self):
        b = inventory('caller.c')
        b['declarations'][0]['signature'] = {'unproved': 'attributed type facts'}
        plan = self.plan(b=b)
        self.assertEqual(len(plan['symbols']), 1)
        self.assertIn('candidate_signature_unproved', [d['code'] for d in plan['diagnostics']])

    def test_malformed_signature_is_not_valid_unproved_evidence(self):
        for signature in (None, {}, {'unproved': ''}, {'unproved': 1},
                          {'unproved': 'reason', 'canonical': {}},
                          {'canonical': {}}, {'canonical': None}):
            with self.subTest(signature=signature):
                a = inventory('definition.c', True)
                a['declarations'][0]['signature'] = signature
                with self.assertRaisesRegex(PlanError, 'function signature'):
                    self.plan(a=a)
        a = inventory('definition.c', True)
        del a['declarations'][0]['signature']
        with self.assertRaisesRegex(PlanError, 'function signature'):
            self.plan(a=a)

    def test_global_cross_unit_declaration_is_not_external(self):
        caller = inventory('caller.c')
        caller['calls'] = [{'id': 9, 'owner': None, 'callee': {'linker': 'format'},
                            'location': 'caller.c:9', 'arguments': [{'type': scalar('Int')},
                                                                    {'type': scalar('ULong')}]}]
        result = self.plan(b=caller)
        self.assertEqual(result['symbols'][0]['calls'][0]['slots'], ['c_ulong'])
        self.assertEqual(result['authorization'], 'inventory_only')
        self.assertIn('cursor_dataflow_unproved', [d['code'] for d in result['diagnostics']])

    def test_external_variadic_stays_outside_plan(self):
        caller = inventory('caller.c')
        caller['declarations'][0]['symbol'] = {'linker': 'printf'}
        caller['calls'] = [{'id': 9, 'owner': None, 'callee': {'linker': 'printf'},
                            'location': 'caller.c:9', 'arguments': []}]
        self.assertEqual(self.plan(b=caller)['symbols'][0]['calls'], [])

    def test_static_same_name_does_not_merge(self):
        a, b = inventory('definition.c', True), inventory('caller.c', True)
        for item in (a, b):
            item['declarations'][0]['symbol'] = {'unit': item['unit'], 'static': 'format'}
        self.assertEqual(len(self.plan(a, b)['symbols']), 2)

    def test_reject_semantic_controls(self):
        for control, expected in [('export', 'exported_variadic_or_cursor_definition'),
                                  ('signature', 'signature_mismatch'), ('escape', 'address_escape'),
                                  ('indirect', 'unclassified_indirect_call'), ('va_arg', 'unsupported_va_arg'),
                                  ('tail', 'unsupported_tail_type')]:
            with self.subTest(control=control):
                a, b = inventory('definition.c', True), inventory('caller.c')
                exports = ['format'] if control == 'export' else []
                if control == 'signature':
                    b['declarations'][0]['signature']['canonical']['return'] = scalar('UInt')
                if control == 'escape':
                    b['non_call_references'] = [{'symbol': {'linker': 'format'}, 'location': 'caller.c:3'}]
                if control == 'indirect':
                    a['calls'] = [{'id': 1, 'owner': 1, 'callee': None, 'location': 'definition.c:4', 'arguments': []}]
                if control == 'va_arg':
                    a['va_arg'] = [{'owner': 1, 'location': 'definition.c:5'}]
                if control == 'tail':
                    b['calls'] = [{'id': 9, 'owner': None, 'callee': {'linker': 'format'},
                                   'location': 'caller.c:9', 'arguments': [{'type': scalar('Int')}, {'type': scalar('LongDouble')}]}]
                self.assertIn(expected, [d['code'] for d in self.plan(a, b, exports)['diagnostics']])

    def test_target_and_unit_must_match(self):
        a, b = inventory('definition.c', True), inventory('caller.c')
        b['target'] = 'x86_64-pc-windows-msvc'
        with self.assertRaisesRegex(PlanError, 'mixed target'):
            self.plan(a, b)
        with self.assertRaisesRegex(PlanError, 'input manifest'):
            build_plan([a], ['other.c'], [])

    def test_target_widths_come_from_target_not_host(self):
        a, b = inventory('definition.c', True), inventory('caller.c')
        for item in (a, b):
            item['target'] = 'x86_64-pc-windows-msvc'
        with self.assertRaisesRegex(PlanError, 'target C widths'):
            self.plan(a, b)
        for item in (a, b):
            item['target_c_widths_bits']['long'] = 32
        self.assertEqual(self.plan(a, b)['target_c_widths_bits']['long'], 32)

    def test_actual_probe_requires_exact_units_exports_and_inventory(self):
        from full_compiler import UNITS
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / 'source'
            raw = root / 'rust-raw'
            raw.mkdir()
            units = []
            for index, name in enumerate(UNITS):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('/* input */')
                units.append({'file': str(path)})
                item = inventory(str(path), index == 0)
                (raw / (str(index) + '.variadic.json')).write_text(json.dumps(item))
            (root / 'compile_commands.json').write_text(json.dumps(units))
            export_map = source / 'libs/vkd3d-shader/vkd3d_shader.map'
            export_map.write_text('VKD3D_1_0 { global: ' + ''.join('public_' + str(i) + ';' for i in range(23)) + ' local: *; };')
            result = collect_probe(root)
            self.assertEqual(len(result['source_sha256']), 24)
            self.assertEqual(result['authorization'], 'inventory_only')
            (raw / '0.variadic.json').unlink()
            with self.assertRaisesRegex(PlanError, 'input manifest'):
                collect_probe(root)
            export_map.write_text('VKD3D_1_0 { global: public; };')
            with self.assertRaisesRegex(PlanError, 'local wildcard'):
                collect_probe(root)

    def test_parameter_top_level_qualifiers_are_compatible(self):
        a, b = inventory('definition.c', True), inventory('caller.c')
        a['declarations'][0]['signature']['canonical']['parameters'][0].update(
            const=True, volatile=True, restrict=True)
        self.assertNotIn('signature_mismatch', [d['code'] for d in self.plan(a, b)['diagnostics']])

    def test_pointee_qualifiers_abi_and_real_types_still_mismatch(self):
        for control in ['pointee', 'abi', 'parameter', 'return', 'variadic']:
            with self.subTest(control=control):
                a, b = inventory('definition.c', True), inventory('caller.c')
                sig = b['declarations'][0]['signature']['canonical']
                if control == 'pointee':
                    for item in (a, b):
                        item['declarations'][0]['signature']['canonical']['parameters'] = [
                            {'canonical': {'pointer': scalar('Int')}, 'const': False, 'volatile': False, 'restrict': False}]
                    sig['parameters'][0]['canonical']['pointer']['const'] = True
                elif control == 'abi':
                    sig['abi'] = 'win64'
                elif control == 'parameter':
                    sig['parameters'] = [scalar('UInt')]
                elif control == 'return':
                    sig['return'] = scalar('UInt')
                else:
                    sig['variadic'] = False
                self.assertIn('signature_mismatch', [d['code'] for d in self.plan(a, b)['diagnostics']])

    def test_no_body_alias_chain_propagates_export_call_and_escape(self):
        a, b = inventory('definition.c', True), inventory('caller.c')
        for ident, name, target in [(2, 'alias_one', 'format'), (3, 'public_alias', 'alias_one')]:
            declaration = json.loads(json.dumps(b['declarations'][0]))
            declaration.update(id=ident, symbol={'linker': name}, aliases=[target])
            b['declarations'].append(declaration)
        b['calls'] = [{'id': 10, 'owner': None, 'callee': {'linker': 'public_alias'},
                       'location': 'caller.c:10', 'arguments': [{'type': scalar('Int')}, {'type': scalar('Double')}]}]
        b['non_call_references'] = [{'symbol': {'linker': 'alias_one'}, 'location': 'caller.c:11'}]
        plan = self.plan(a, b, ['public_alias'])
        candidate = plan['symbols'][0]
        self.assertEqual(candidate['calls'][0]['slots'], ['c_double'])
        codes = {d['code'] for d in plan['diagnostics'] if d['symbol'] == candidate['symbol']}
        self.assertTrue({'unsupported_linker_alias', 'exported_variadic_or_cursor_definition',
                         'address_escape', 'cursor_dataflow_unproved'} <= codes)

    def test_exported_alias_to_static_candidate_is_rejected(self):
        a, b = inventory('definition.c', True), inventory('caller.c')
        a['declarations'][0]['symbol'] = {'unit': 'definition.c', 'static': 'format'}
        alias = json.loads(json.dumps(a['declarations'][0]))
        alias.update(id=2, definition=False, symbol={'linker': 'public_alias'}, aliases=['format'])
        a['declarations'].append(alias)
        result = self.plan(a, b, ['public_alias'])
        self.assertIn('exported_variadic_or_cursor_definition', [d['code'] for d in result['diagnostics']])
        self.assertNotIn('unresolved_linker_alias', [d['code'] for d in result['diagnostics']])

    def test_pointer_parameter_top_level_qualification_is_compatible(self):
        a, b = inventory('definition.c', True), inventory('caller.c')
        for item in (a, b):
            item['declarations'][0]['signature']['canonical']['parameters'] = [
                {'canonical': {'pointer': scalar('Int')}, 'const': False, 'volatile': False, 'restrict': False}]
        a['declarations'][0]['signature']['canonical']['parameters'][0]['const'] = True
        self.assertNotIn('signature_mismatch', [d['code'] for d in self.plan(a, b)['diagnostics']])

    def test_alias_cycle_unresolved_and_private_alias_are_rejected(self):
        for aliases, expected in [({'format': 'missing'}, 'unresolved_linker_alias'),
                                  ({'format': 'other', 'other': 'format'}, 'cyclic_linker_alias'),
                                  ({'other': 'format'}, 'unsupported_linker_alias')]:
            with self.subTest(aliases=aliases):
                a, b = inventory('definition.c', True), inventory('caller.c')
                for index, (name, target) in enumerate(aliases.items()):
                    declaration = json.loads(json.dumps(b['declarations'][0]))
                    declaration.update(id=index + 2, symbol={'linker': name}, aliases=[target])
                    b['declarations'].append(declaration)
                self.assertIn(expected, [d['code'] for d in self.plan(a, b)['diagnostics']])

    def test_promoted_types_and_rejections(self):
        self.assertEqual(promoted_slot({'type': scalar('Int')}), 'c_int')
        self.assertEqual(promoted_slot({'type': scalar('UInt')}), 'c_uint')
        for kind in ['Int', 'UInt', 'Long', 'ULong', 'LongLong', 'ULongLong', 'Double']:
            self.assertIsInstance(promoted_slot({'type': scalar(kind)}), str)
        for kind in ['Float', 'UShort', 'UChar', 'Bool', 'LongDouble', 'Int128', 'UInt128']:
            with self.subTest(kind=kind), self.assertRaises(PlanError):
                promoted_slot({'type': scalar(kind)})
        for canonical in [{'record_kind': 'struct'}, {'record_kind': 'enum'}, {'kind': 'Vector'}]:
            with self.assertRaises(PlanError):
                promoted_slot({'type': {'canonical': canonical}})


def record_identity(tag='node', kind='struct', line=10):
    return {'kind': kind, 'tag': tag,
            'physical': {'path': '/shared/header.h', 'line': line, 'column': 1},
            'scope': {'file': True}}


def record_type(identity):
    return {'canonical': {'record': identity}, 'const': False, 'volatile': False, 'restrict': False}


def record_definition(identity):
    return {'identity': identity, 'state': 'complete', 'facts': {
        'layout': [False, None, None, 8, 8],
        'fields': [{'name': 'next', 'type': {'canonical': {'pointer': record_type(identity)}, 'const': False, 'volatile': False, 'restrict': False},
                    'bit_width': None, 'bit_offset': 0, 'type_bit_width': 64, 'alignment': None}]}}


class RecordEvidenceTests(unittest.TestCase):
    def pair(self):
        import copy
        a, b = inventory('a.c', True), inventory('b.c')
        identity = record_identity()
        for item in (a, b):
            item['record_definitions'] = [copy.deepcopy(record_definition(identity))]
            item['declarations'][0]['signature']['canonical']['parameters'] = [record_type(copy.deepcopy(identity))]
        return a, b

    def codes(self, a, b):
        return {d['code'] for d in build_plan([a, b], ['a.c', 'b.c'], [])['diagnostics']}

    def test_recursive_definition_terminates_and_stays_inventory_only(self):
        a, b = self.pair()
        plan = build_plan([a, b], ['a.c', 'b.c'], [])
        self.assertEqual(plan['schema'], 2)
        self.assertEqual(plan['authorization'], 'inventory_only')
        self.assertEqual({d['code'] for d in plan['diagnostics']}, {'cursor_dataflow_unproved'})

    def test_actual_layout_and_ordered_field_facts_must_match(self):
        mutations = [lambda f: f['layout'].__setitem__(0, True),
                     lambda f: f['layout'].__setitem__(1, 16),
                     lambda f: f['layout'].__setitem__(2, 1),
                     lambda f: f['layout'].__setitem__(3, 16),
                     lambda f: f['layout'].__setitem__(4, 16),
                     lambda f: f['fields'][0].__setitem__('name', 'renamed'),
                     lambda f: f['fields'][0].__setitem__('bit_offset', 1),
                     lambda f: f['fields'][0].__setitem__('bit_width', 3),
                     lambda f: f['fields'][0].__setitem__('type', scalar('Long'))]
        for mutate in mutations:
            a, b = self.pair()
            mutate(b['record_definitions'][0]['facts'])
            self.assertIn('signature_mismatch', self.codes(a, b))

    def test_unknown_evidence_never_proves_compatibility_even_when_identical(self):
        for mutation in (
                lambda i: i['record_definitions'][0].__setitem__('state', 'incomplete'),
                lambda i: i['record_definitions'][0]['facts'].__setitem__('layout', None),
                lambda i: i['declarations'][0]['signature']['canonical']['parameters'].__setitem__(0, {'unproved': 'depth limit'}),
                lambda i: i['record_definitions'][0]['identity']['physical'].__setitem__('line', 0),
                lambda i: i['record_definitions'][0]['identity'].__setitem__('scope', {'unknown': True}),
                lambda i: i['record_definitions'][0]['facts']['fields'][0].__setitem__('type', scalar('Unknown'))):
            a, b = self.pair()
            mutation(a)
            mutation(b)
            self.assertIn('record_compatibility_unproved', self.codes(a, b))

    def test_plain_char_signedness_is_required_and_compared_recursively(self):
        import copy
        wrappers = [lambda t: t,
                    lambda t: {'canonical': {'pointer': t}, 'const': False, 'volatile': False, 'restrict': False},
                    lambda t: {'canonical': {'array': t, 'length': 2}, 'const': False, 'volatile': False, 'restrict': False},
                    lambda t: {'canonical': {'return': scalar('Int'), 'parameters': [t],
                               'variadic': False, 'noreturn': False, 'prototype': True, 'abi': 'C'},
                               'const': False, 'volatile': False, 'restrict': False}]
        for wrap in wrappers:
            for signed in (True, False):
                a, b = self.pair()
                for item in (a, b):
                    typ = scalar('Char')
                    typ['canonical']['signed'] = signed
                    item['record_definitions'][0]['facts']['fields'][0]['type'] = wrap(typ)
                self.assertEqual(self.codes(a, b), {'cursor_dataflow_unproved'})
                typ_b = b['record_definitions'][0]['facts']['fields'][0]['type']
                def chars(tree):
                    if isinstance(tree, dict):
                        if tree.get('kind') == 'Char':
                            yield tree
                        for child in tree.values():
                            yield from chars(child)
                    elif isinstance(tree, list):
                        for child in tree:
                            yield from chars(child)
                next(chars(typ_b))['signed'] = not signed
                self.assertIn('signature_mismatch', self.codes(a, b))
                for value in (None, 'unknown', 1):
                    bad = copy.deepcopy(a)
                    char = next(chars(bad['record_definitions'][0]['facts']['fields'][0]['type']))
                    if value is None:
                        del char['signed']
                    else:
                        char['signed'] = value
                    other = copy.deepcopy(bad)
                    other['unit'] = 'b.c'
                    self.assertIn('record_compatibility_unproved', self.codes(bad, other))

    def test_actual_export_char_boundary_mutator_preserves_inputs(self):
        import copy
        from check_closed_variadic_inventory import check_char_boundaries
        a, b = self.pair()
        for item in (a, b):
            typ = scalar('Char')
            typ['canonical']['signed'] = True
            item['record_definitions'][0]['facts']['fields'][0]['type'] = typ
        originals = copy.deepcopy([a, b])
        results = check_char_boundaries([a, b], ['a.c', 'b.c'])
        self.assertEqual(set(results), {'missing', 'unknown', 'integer'})
        self.assertEqual([a, b], originals)
        for result in results.values():
            self.assertIn('record_compatibility_unproved',
                          {d['code'] for d in result['plan']['diagnostics']})

    def test_explicit_char_builtin_kinds_remain_distinct(self):
        a, b = self.pair()
        for kind in ('SChar', 'UChar'):
            for item in (a, b):
                item['record_definitions'][0]['facts']['fields'][0]['type'] = scalar(kind)
            self.assertEqual(self.codes(a, b), {'cursor_dataflow_unproved'})
        a['record_definitions'][0]['facts']['fields'][0]['type'] = scalar('SChar')
        self.assertIn('signature_mismatch', self.codes(a, b))

    def test_long_double_is_unproved_through_callback_record_and_array(self):
        for wrap in (lambda t: t,
                     lambda t: {'canonical': {'array': t, 'length': 2}, 'const': False, 'volatile': False, 'restrict': False},
                     lambda t: {'canonical': {'pointer': {'canonical': {'return': scalar('Int'), 'parameters': [t],
                         'variadic': False, 'noreturn': False, 'prototype': True, 'abi': 'C'},
                         'const': False, 'volatile': False, 'restrict': False}}, 'const': False, 'volatile': False, 'restrict': False}):
            for unsupported in (scalar('LongDouble'), {'canonical': {'unproved': 'long double ABI shape'},
                                                     'const': False, 'volatile': False, 'restrict': False}):
                a, b = self.pair()
                for item in (a, b):
                    item['record_definitions'][0]['facts']['fields'][0]['type'] = wrap(unsupported)
                self.assertIn('record_compatibility_unproved', self.codes(a, b))

    def test_actual_export_boundary_mutator_rejects_identical_unknowns(self):
        from check_closed_variadic_inventory import check_physical_boundaries
        a, b = self.pair()
        before = json.dumps([a, b], sort_keys=True)
        results = check_physical_boundaries([a, b], ['a.c', 'b.c'])
        self.assertEqual(set(results), {'unknown-path', 'zero-line', 'zero-column'})
        self.assertEqual(json.dumps([a, b], sort_keys=True), before)
        for result in results.values():
            self.assertEqual(result['origin'], 'actual-export-derived payload mutation')
            self.assertIn('record_compatibility_unproved', {d['code'] for d in result['plan']['diagnostics']})

    def test_nested_array_qualifiers_must_match(self):
        def array(t):
            return {'canonical': {'array': t, 'length': 2}, 'const': False, 'volatile': False, 'restrict': False}
        for qualifier in ('const', 'volatile', 'restrict'):
            a, b = self.pair()
            for item in (a, b):
                item['record_definitions'][0]['facts']['fields'][0]['type'] = array(array(scalar('Int')))
            b['record_definitions'][0]['facts']['fields'][0]['type']['canonical']['array']['canonical']['array'][qualifier] = True
            self.assertIn('signature_mismatch', self.codes(a, b))

    def test_schema_one_mixed_and_unknown_versions_are_rejected(self):
        for schema, evidence in ((1, 2), (2, 1), (3, 3), (2, None)):
            a, b = self.pair()
            b['schema'], b['record_evidence_schema'] = schema, evidence
            with self.assertRaisesRegex(PlanError, 'unsupported inventory contract'):
                self.codes(a, b)

    def test_nested_owner_is_part_of_identity(self):
        a, b = self.pair()
        b['record_definitions'][0]['identity']['scope'] = {'record': record_identity('owner')}
        b['declarations'][0]['signature']['canonical']['parameters'][0]['canonical']['record']['scope'] = {'record': record_identity('owner')}
        self.assertIn('signature_mismatch', self.codes(a, b))

    def test_mutual_recursive_records_terminate(self):
        a, b = self.pair()
        for item in (a, b):
            other = record_identity('other', line=20)
            item['record_definitions'].append(record_definition(other))
            item['record_definitions'][0]['facts']['fields'][0]['type']['canonical']['pointer'] = record_type(other)
            item['record_definitions'][1]['facts']['fields'][0]['type']['canonical']['pointer'] = record_type(record_identity())
        self.assertEqual(self.codes(a, b), {'cursor_dataflow_unproved'})

    def test_nominal_kind_tag_and_physical_position_are_required(self):
        for field, value in (('tag', 'other'), ('kind', 'union')):
            a, b = self.pair()
            b['record_definitions'][0]['identity'][field] = value
            b['declarations'][0]['signature']['canonical']['parameters'][0]['canonical']['record'][field] = value
            self.assertIn('signature_mismatch', self.codes(a, b))
        for path, line in (('?', 10), ('/shared/header.h', 0)):
            a, b = self.pair()
            for item in (a, b):
                for identity in (item['record_definitions'][0]['identity'], item['declarations'][0]['signature']['canonical']['parameters'][0]['canonical']['record']):
                    identity['physical'].update(path=path, line=line)
            self.assertIn('record_compatibility_unproved', self.codes(a, b))

    def test_enum_values_and_underlying_type_are_compared(self):
        for change in ('value', 'underlying'):
            a, b = self.pair()
            for item in (a, b):
                item['record_definitions'][0]['identity']['kind'] = 'enum'
                item['declarations'][0]['signature']['canonical']['parameters'][0]['canonical']['record']['kind'] = 'enum'
                item['record_definitions'][0]['facts'] = {'underlying': scalar('UInt'),
                    'variants': [{'name': 'value', 'signed': False, 'value': 1}]}
            if change == 'value':
                b['record_definitions'][0]['facts']['variants'][0]['value'] = 2
            else:
                b['record_definitions'][0]['facts']['underlying'] = scalar('Int')
            self.assertIn('signature_mismatch', self.codes(a, b))

    def test_incomplete_mix_and_missing_qualifiers_are_explicitly_unproved(self):
        a, b = self.pair()
        b['record_definitions'][0]['state'] = 'incomplete'
        self.assertIn('record_compatibility_unproved', self.codes(a, b))
        a, b = self.pair()
        del b['record_definitions'][0]['facts']['fields'][0]['type']['volatile']
        self.assertIn('record_compatibility_unproved', self.codes(a, b))

    def test_depth_limit_and_typedef_sentinels_are_not_equal_proof(self):
        for sentinel in ({'unsupported': 'recursive type'}, {'unproved': 'typedef cycle'}, {'kind': 'Attributed(None)'}):
            a, b = self.pair()
            for item in (a, b):
                item['record_definitions'][0]['facts']['fields'][0]['type']['canonical'] = sentinel
            self.assertIn('record_compatibility_unproved', self.codes(a, b))



def exercise_actual_cursor_payload(inventory, witness):
    import copy
    from closed_variadic_plan import SCALARS, _cursor_same, prove_cursor_witness
    symbol = {'unit': witness['unit'], 'static': 'vkd3d_spirv_build_op_member_name'}
    function = next(f for f in witness['functions'] if f['symbol'] == symbol)
    function_id = function['declaration']
    body_ids = {e['id'] for s in function['statements'] for e in s['expressions']}
    expressions = {e['id']: e for e in witness['expressions']}
    declarations = {d['id']: d for d in witness['declarations']}
    body_calls = [e for e in witness['calls'] if e['id'] in body_ids]
    incoming = next(c for c in inventory['calls'] if c['callee'] == symbol)
    result = prove_cursor_witness([inventory], [witness], symbol)
    if result['status'] != 'witness_proven' or result['stable_lowering'] != 'not_authorized':
        raise RuntimeError('actual positive witness was not proved with the narrow authorization')

    def expression(ident, edit):
        def mutate(inv, w):
            rows = [w['expressions'], w['calls'], *[s['expressions'] for f in w['functions'] for s in f['statements']]]
            for vector in rows:
                for row in vector:
                    if row['id'] == ident:
                        edit(row)
        return mutate

    def declaration(ident, edit):
        def mutate(inv, w):
            rows = [w['declarations'], *[f['parameter_declarations'] for f in w['functions']],
                    *[s['declarations'] for f in w['functions'] for s in f['statements']]]
            for vector in rows:
                for row in vector:
                    if row['id'] == ident:
                        edit(row)
        return mutate

    def target(w):
        return next(f for f in w['functions'] if f['declaration'] == function_id)

    mutations = []
    def add(name, mutate):
        mutations.append((name, mutate))

    for field, value in [('complete_body', False), ('full_statement_ids', []), ('parameters', []),
                         ('last_fixed_parameter', 0), ('cursors', []), ('parameter_declarations', []),
                         ('parameter_and_cursor_references', [])]:
        add('function-' + field, lambda i, w, field=field, value=value: target(w).__setitem__(field, value))
    add('missing-relations', lambda i, w: w.pop('required_relations'))
    add('float-schema', lambda i, w: w.__setitem__('schema', 2.0))
    add('old-schema', lambda i, w: w.__setitem__('schema', 1))
    for field, value in [('schema', 2), ('authorization', 'inventory_only')]:
        add('relation-' + field, lambda i, w, field=field, value=value: w['required_relations'].__setitem__(field, value))
    add('missing-statement', lambda i, w: target(w)['statements'].pop())
    add('duplicate-statement', lambda i, w: target(w)['statements'].append(copy.deepcopy(target(w)['statements'][0])))
    add('reordered-statements', lambda i, w: target(w)['statements'].reverse())
    add('missing-body-expression', lambda i, w: w.__setitem__('expressions',
        [x for x in w['expressions'] if x['id'] != function['statements'][4]['root']]))
    add('duplicate-expression', lambda i, w: w['expressions'].append(copy.deepcopy(w['expressions'][0])))
    add('duplicate-declaration', lambda i, w: w['declarations'].append(copy.deepcopy(w['declarations'][0])))
    add('inconsistent-call-numeric-type', lambda i, w: next(c for c in w['calls']
        if c['id'] == body_calls[0]['id'])['builtin'].__setitem__(0, float(body_calls[0]['builtin'][0])))
    integer_literal = next(e for e in function['statements'][6]['expressions'] if e['kind'] == 'literal' and e['literal'].get('integer') == 1)
    add('inconsistent-embedded-numeric-type', lambda i, w: next(e for e in target(w)['statements'][6]['expressions']
        if e['id'] == integer_literal['id'])['literal'].__setitem__('integer', 1.0))
    add('missing-call-set', lambda i, w: w.__setitem__('calls', []))
    add('duplicate-call', lambda i, w: w['calls'].append(copy.deepcopy(w['calls'][0])))
    add('missing-reference-set', lambda i, w: target(w)['parameter_and_cursor_references'].pop())
    add('duplicate-reference', lambda i, w: target(w)['parameter_and_cursor_references'].append(
        copy.deepcopy(target(w)['parameter_and_cursor_references'][0])))
    add('duplicate-type-row', lambda i, w: w['required_relations']['types'].append(
        copy.deepcopy(w['required_relations']['types'][0])))
    add('duplicate-root', lambda i, w: w['required_relations']['roots'].append(
        copy.deepcopy(w['required_relations']['roots'][0])))
    add('duplicate-native', lambda i, w: w['required_relations']['native_records'].append(
        copy.deepcopy(w['required_relations']['native_records'][0])))
    add('duplicate-endpoint', lambda i, w: w['required_relations']['builtin_endpoints'].append(
        copy.deepcopy(w['required_relations']['builtin_endpoints'][0])))
    add('native-origin', lambda i, w: w['required_relations']['native_records'][0].__setitem__('origin', 'tag_name'))
    add('native-boolean-layout', lambda i, w: w['required_relations']['native_records'][0].__setitem__('alignment', True))
    add('native-layout', lambda i, w: w['required_relations']['native_records'][0].__setitem__('size', 8))
    add('native-incomplete', lambda i, w: w['required_relations']['native_records'][0].__setitem__('complete', False))
    add('native-kind', lambda i, w: w['required_relations']['native_records'][0].__setitem__('kind', 'union'))
    for field, value in [('type_id', 0), ('const', True), ('volatile', True), ('restrict', True)]:
        add('cursor-source-' + field, lambda i, w, field=field, value=value:
            next(c for c in w['required_relations']['cursors'] if c['declaration'] == function['cursors'][0])['source'].__setitem__(field, value))
    add('semantic-alias-retarget', lambda i, w: next(r for r in w['required_relations']['types']
        if r['type_id'] == declarations[function['cursors'][0]]['type_id']).__setitem__('inner',
            next(r['type_id'] for r in w['required_relations']['types'] if r['kind'] == 'UInt')))
    for c in body_calls:
        add('builtin-' + str(c['id']), expression(c['id'], lambda x: x.__setitem__('builtin', [1, 'unknown'])))
        add('callee-' + str(c['id']), expression(c['id'], lambda x: x.__setitem__('callee_decl', 0)))
        add('arguments-' + str(c['id']), expression(c['id'], lambda x: x.__setitem__('arguments', [])))
        add('body-call-owner-' + str(c['id']), lambda i, w, ident=c['id']:
            next(row for row in i['calls'] if row['id'] == ident).__setitem__('owner', 0))
    for e in [expressions[k] for k in sorted(body_ids)]:
        ident, kind = e['id'], e['kind']
        if 'operator' in e:
            add('operator-' + str(ident), expression(ident, lambda x: x.__setitem__('operator', 'AddAssign')))
        if kind == 'implicit_cast':
            add('cast-' + str(ident), expression(ident, lambda x: x.__setitem__('cast', 'BitCast')))
        if kind == 'literal':
            add('literal-' + str(ident), expression(ident, lambda x: x.__setitem__('literal', {'integer': 99})))
        if kind == 'reference':
            add('reference-retarget-' + str(ident), expression(ident, lambda x: x.__setitem__('decl', 0)))
        if e['children']:
            add('dangling-child-' + str(ident), expression(ident, lambda x: x['children'].__setitem__(0, 0)))
            add('cyclic-child-' + str(ident), expression(ident, lambda x: x['children'].__setitem__(0, x['id'])))
        if len(e['children']) > 1:
            add('reordered-children-' + str(ident), expression(ident, lambda x: x['children'].reverse()))
    for d in function['parameter_declarations'] + [s['declarations'][0] for s in function['statements'][:4]]:
        for field, value in [('owning_function', 0), ('initializer', 0), ('type_id', 0), ('static', True)]:
            add('declaration-' + str(d['id']) + '-' + field,
                declaration(d['id'], lambda x, field=field, value=value: x.__setitem__(field, value)))
    alias_ids = {d['type_id'] for d in function['parameter_declarations']}
    alias_ids.add(next(d for d in declarations.values() if d['id'] == function['cursors'][0])['type_id'])
    for ident in alias_ids:
        row = next(r for r in witness['required_relations']['types'] if r['type_id'] == ident)
        if 'inner' in row:
            for value in [0, ident]:
                add('alias-edge-' + str(ident) + '-' + str(value), lambda i, w, ident=ident, value=value:
                    next(r for r in w['required_relations']['types'] if r['type_id'] == ident).__setitem__('inner', value))
    for end in witness['required_relations']['builtin_endpoints']:
        if end['expression'] not in body_ids:
            continue
        ident = end['expression']
        for field in ['expression', 'reference', 'declaration']:
            add('endpoint-' + str(ident) + '-' + field, lambda i, w, ident=ident, field=field:
                next(r for r in w['required_relations']['builtin_endpoints'] if r['expression'] == ident).__setitem__(field, 0))
        add('endpoint-input-cvr-' + str(ident), lambda i, w, ident=ident:
            next(r for r in w['required_relations']['builtin_endpoints'] if r['expression'] == ident)['input'].__setitem__('const', True))
    for semantic in ['va_start', 'va_end', 'vsnprintf']:
        add('semantic-id-' + semantic, lambda i, w, semantic=semantic:
            next(r for r in w['required_relations']['builtin_declarations'] if r['semantic'] == semantic).__setitem__('builtin_id', 1))
    enum = next(d for d in declarations.values() if d['kind'] == 'enum_constant' and d['name'] == 'SpvOpMemberName')
    add('enum-owner', lambda i, w: next(d for d in w['declarations'] if d['id'] == enum['id'])['owning_enum'].__setitem__('declaration', 0))
    add('enum-membership', lambda i, w: next(r for r in w['required_relations']['enum_owners']
        if r['declaration'] == enum['owning_enum']['declaration'])['variants'].clear())
    add('enum-float-value', lambda i, w: next(r for r in w['required_relations']['enum_owners']
        if r['declaration'] == enum['owning_enum']['declaration'])['variants'][-1].__setitem__('value', 6.0))
    add('enum-signed-value', lambda i, w: next(r for r in w['required_relations']['enum_owners']
        if r['declaration'] == enum['owning_enum']['declaration'])['variants'][-1].__setitem__('signed', False))
    name = function['statements'][2]['declarations'][0]
    add('name-array-length', lambda i, w: next(r for r in w['required_relations']['types']
        if r['type_id'] == name['type_id']).__setitem__('length', 12))
    add('name-array-element-cvr', lambda i, w: next(r for r in w['required_relations']['types']
        if r['type_id'] == name['type_id'])['element'].__setitem__('const', True))
    field_expr = next(e for e in expressions.values() if e['id'] in body_ids and e['kind'] == 'member')
    add('member-owner', expression(field_expr['id'], lambda x: x['member'].__setitem__('owners', [])))
    add('member-ID-collision', expression(field_expr['id'], lambda x: x['member'].__setitem__('id', function['parameters'][0])))
    add('member-name', expression(field_expr['id'], lambda x: x['member'].__setitem__('name', 'other_stream')))
    tail = expressions[incoming['id']]['arguments'][4]['direct_decl']
    add('tail-owner', declaration(tail, lambda d: d.__setitem__('owning_function', function_id)))
    add('tail-type', declaration(tail, lambda d: d.__setitem__('type', scalar('Int'))))
    add('tail-name', declaration(tail, lambda d: d.__setitem__('name', 'other_idx')))
    add('incoming-owner', lambda i, w: next(c for c in i['calls'] if c['id'] == incoming['id']).__setitem__('owner', function_id))
    add('extra-incoming-call', lambda i, w: i['calls'].append(copy.deepcopy(incoming)))
    add('target-noncall-reference', lambda i, w: i['non_call_references'].append({'symbol': symbol}))
    add('target-alias', lambda i, w: i['declarations'][0]['aliases'].append(symbol['static']))
    add('target-signature', lambda i, w: next(d for d in i['declarations'] if d['id'] == function_id)['signature']['canonical'].__setitem__('variadic', False))
    format_expr = next(e for e in expressions.values() if e['id'] == expressions[expressions[incoming['id']]['children'][4]]['children'][0])
    add('incoming-format', expression(format_expr['id'], lambda x: x.__setitem__('literal', {'width': 1, 'bytes': [37, 115]})))
    add('incoming-format-width', expression(format_expr['id'], lambda x: x['literal'].__setitem__('width', 2)))
    add('incoming-side-effect', expression(expressions[incoming['id']]['children'][1], lambda x: x.__setitem__('cast', 'IntegralCast')))
    add('hidden-statement-allocation', lambda i, w: target(w)['statements'][1]['expressions'].append(
        copy.deepcopy(target(w)['statements'][0]['expressions'].pop())))
    callee_decay = expressions[expressions[incoming['id']]['children'][0]]
    for expr in (callee_decay, format_expr):
        for value in (None, 0, -1, 'mapped-id', True, 1.25):
            add('incoming-qualified-ID-' + str(expr['id']) + '-' + repr(value),
                expression(expr['id'], lambda x, value=value: x.__setitem__('type_id', value)))
        other = format_expr if expr is callee_decay else callee_decay
        add('incoming-type-meaning-collision-' + str(expr['id']),
            expression(expr['id'], lambda x, ident=other['type_id']: x.__setitem__('type_id', ident)))
        add('incoming-existing-type-collision-' + str(expr['id']),
            expression(expr['id'], lambda x: x.__setitem__('type_id', declarations[tail]['type_id'])))
    for qualifier in ('const', 'restrict', 'volatile'):
        add('required-root-integer-' + qualifier, lambda i, w, qualifier=qualifier:
            [r.__setitem__(qualifier, int(r[qualifier])) for r in w['required_relations']['roots']])
    add('tail-float-owner', declaration(tail, lambda d: d.__setitem__('owning_function', float(d['owning_function']))))

    def scalar_copies(inv, w, edit):
        def transform(value):
            if isinstance(value, dict):
                row = {k: (v if k == 'native_inputs' else transform(v)) for k, v in value.items()}
                edit(row)
                return row
            if isinstance(value, list):
                return [transform(v) for v in value]
            return value
        for payload in (inv, w):
            replaced = transform(payload)
            payload.clear()
            payload.update(replaced)

    add('native-float-canonical-ID', lambda i, w: scalar_copies(i, w, lambda row:
        row.__setitem__('native_va_list_record', float(row['native_va_list_record']))
        if 'native_va_list_record' in row else None))
    add('native-float-membership-ID', lambda i, w:
        w.__setitem__('native_va_list_records', [float(v) for v in w['native_va_list_records']]))
    for value in (True, 1.0):
        add('native-canonical-array-length-' + repr(value), lambda i, w, value=value:
            scalar_copies(i, w, lambda row: row.__setitem__('length', value)
                if set(row) == {'array', 'length'} and row['length'] == 1 else None))
    for ident in [a['direct_decl'] for a in expressions[incoming['id']]['arguments'][:3]]:
        add('incoming-declaration-integer-local-' + str(ident),
            declaration(ident, lambda d: d.__setitem__('local', int(d['local']))))
    for endpoint in witness['required_relations']['builtin_endpoints']:
        if endpoint['expression'] in body_ids:
            for field in ('reference', 'declaration'):
                add('endpoint-float-' + str(endpoint['expression']) + '-' + field,
                    lambda i, w, ident=endpoint['expression'], field=field, value=float(endpoint[field]):
                    next(r for r in w['required_relations']['builtin_endpoints']
                         if r['expression'] == ident).__setitem__(field, value))
    affected_expressions = set(body_ids)
    pending = [incoming['id']]
    while pending:
        ident = pending.pop()
        if ident in affected_expressions:
            continue
        affected_expressions.add(ident)
        pending.extend(expressions[ident]['children'])
    relation_ids = {r['type_id'] for r in witness['required_relations']['types']} | {
        r['type_id'] for r in witness['required_relations']['roots']}
    for expr in (callee_decay, format_expr):
        candidate = next((e for e in witness['expressions']
            if e['id'] not in affected_expressions and type(e['type_id']) is int
            and e['type_id'] > 0 and e['type_id'] not in relation_ids
            and isinstance(e['type'], dict) and e['type'].get('canonical', {}).get('kind') in SCALARS
            and not _cursor_same(e['type']['canonical'], expr['type']['canonical'])), None)
        if candidate is not None:
            add('incoming-outside-closure-type-collision-' + str(expr['id']),
                expression(expr['id'], lambda x, ident=candidate['type_id']: x.__setitem__('type_id', ident)))
    affected_declarations = set(function['parameters']) | {tail} | {
        a['direct_decl'] for a in expressions[incoming['id']]['arguments'][:3]} | {
        d['id'] for s in function['statements'] for d in s['declarations']}
    unchanged = [witness['native_inputs']]
    for key in ('expressions', 'calls'):
        unchanged.extend(x for x in witness[key] if x['id'] not in affected_expressions)
    unchanged.extend(d for d in witness['declarations'] if d['id'] not in affected_declarations and d['id'] != enum['id'])
    unchanged.extend(f for f in witness['functions'] if f['declaration'] != function_id
                     and not any(d['id'] in affected_declarations for d in f['parameter_declarations'])
                     and not any(d['id'] in affected_declarations for s in f['statements'] for d in s['declarations'])
                     and not any(e['id'] in affected_expressions for s in f['statements'] for e in s['expressions']))
    unchanged.extend(d for d in inventory['declarations'] if d['id'] != function_id and d is not inventory['declarations'][0])
    unchanged.extend(c for c in inventory['calls'] if c['id'] not in affected_expressions)
    rejected = []
    for label, mutate in mutations:
        memo = {id(value): value for value in unchanged}
        inv, w = copy.deepcopy(inventory, memo), copy.deepcopy(witness, memo)
        mutate(inv, w)
        try:
            prove_cursor_witness([inv], [w], symbol)
        except PlanError as error:
            rejected.append({'case': label, 'reason': str(error)})
        else:
            raise RuntimeError('actual cursor mutation accepted: ' + label)

    id_keys = {'id', 'decl', 'declaration', 'callee_decl', 'owner', 'owning_function', 'initializer',
               'type_id', 'declared_type_id', 'builtin_type_id', 'body', 'last_fixed_parameter',
               'direct_decl', 'native_va_list_record', 'inner', 'expression', 'reference', 'root'}
    id_lists = {'children', 'parameters', 'cursors', 'full_statement_ids', 'native_va_list_records', 'va_parameters'}
    def rename(value, key=None):
        if isinstance(value, dict):
            return {k: (v if k == 'native_inputs' else rename(v, k)) for k, v in value.items()}
        if isinstance(value, list):
            return [v + 1000000 if key in id_lists and type(v) is int else rename(v) for v in value]
        return value + 1000000 if key in id_keys and type(value) is int else value
    renamed = prove_cursor_witness([rename(inventory)], [rename(witness)], symbol)
    if renamed['status'] != 'witness_proven' or renamed['declaration'] != function_id + 1000000:
        raise RuntimeError('total mapped-ID alpha-renaming changed proof meaning')
    equivalent = copy.deepcopy(witness, {id(value): value for value in unchanged})
    source = next(r for r in equivalent['required_relations']['cursors'] if r['declaration'] == function['cursors'][0])
    alias = next(r for r in equivalent['required_relations']['types'] if r['type_id'] == source['source']['type_id'])
    alias['inner'] = source['declared']['type_id']
    if prove_cursor_witness([inventory], [equivalent], symbol)['status'] != 'witness_proven':
        raise RuntimeError('equivalent closed native alias path changed proof meaning')
    fresh = copy.deepcopy(witness, {id(value): value for value in unchanged})
    for expr, ident in ((callee_decay, 1000001), (format_expr, 1000002)):
        if ident in {r['type_id'] for r in witness['required_relations']['types']}:
            raise RuntimeError('fresh mapped type control ID already exists')
        expression(expr['id'], lambda x, ident=ident: x.__setitem__('type_id', ident))(inventory, fresh)
    if prove_cursor_witness([inventory], [fresh], symbol)['status'] != 'witness_proven':
        raise RuntimeError('fresh omitted mapped type IDs changed proof meaning')
    return {'status': result['status'], 'mutations_rejected': rejected, 'alpha_renaming': 'accepted',
            'fresh_incoming_type_ids': 'accepted',
            'equivalent_alias_path': 'accepted; capture byte changes still require the independent receipt gate'}


class CursorWitnessTests(unittest.TestCase):
    def fixture(self):
        inv = inventory('/pilot.c', True)
        inv['declarations'][0]['symbol'] = {'unit': inv['unit'], 'static': 'cursor_pilot'}
        symbol = inv['declarations'][0]['symbol']
        typ = scalar('UInt')
        def operand(ident, decl=None, refs=(), literal=None):
            return {'id': ident, 'direct_decl': decl, 'references': list(refs), 'literal': literal, 'type': typ}
        statements = [{'id': 11, 'kind': 'declarations', 'root': None,
                       'declarations': [{'id': 9, 'initialized': False, 'type': typ}], 'expressions': []}]
        # Decreasing IDs force the proof to use compound statement order.
        for number, semantic, count, position in [(90, 'va_start', 2, 0), (60, 'vsnprintf', 4, 3), (30, 'va_end', 1, 0)]:
            ref = {'id': number + 1, 'decl': 9, 'kind': 'reference', 'type': typ}
            args = [operand(number + j + 10) for j in range(count)]
            args[position] = operand(number + 1, 9, [{'id': number + 1, 'decl': 9}])
            if semantic == 'va_start': args[1]['direct_decl'] = 2
            if semantic == 'vsnprintf': args[2]['direct_decl'] = 2
            call = {'id': number, 'kind': 'call', 'type': typ, 'callee_decl': number + 100,
                    'builtin': [number + 1000, semantic], 'arguments': args}
            statements.append({'id': number + 2, 'kind': 'expression', 'root': number,
                               'declarations': [], 'expressions': [call, ref]})
        raw_call = {'id': 200, 'kind': 'call', 'callee_decl': 1,
                    'arguments': [operand(201, literal=[99, 98, 37, 117]), operand(202)]}
        inv['calls'] = [{'id': 200, 'owner': None, 'callee': symbol, 'location': '/pilot.c:20',
                         'arguments': [{'id': a['id'], 'type': a['type']} for a in raw_call['arguments']]}]
        function = {'declaration': 1, 'symbol': symbol, 'body': 10, 'complete_body': True,
                    'parameters': [2], 'last_fixed_parameter': 2, 'cursors': [9], 'statements': statements,
                    'full_statement_ids': [10, *[s['id'] for s in statements]],
                    'cursor_references': [{'id': n + 1, 'decl': 9, 'type': typ} for n in (90, 60, 30)]}
        witness = {'schema': 1, 'authorization': 'witness_only', 'unit': inv['unit'], 'target': inv['target'],
                   'functions': [function], 'calls': [raw_call]}
        return inv, witness, symbol

    def test_raw_schema_one_and_relabelled_v2_capture_cannot_prove(self):
        from closed_variadic_plan import prove_cursor_witness
        for name in ('cursor_pilot', 'vkd3d_spirv_build_op_member_name'):
            for schema in (1, 2):
                inv, witness, symbol = self.fixture()
                symbol['static'], witness['schema'] = name, schema
                before = json.dumps([inv, witness], sort_keys=True)
                expected = 'schema 1 capture' if schema == 1 else 'unsupported'
                with self.assertRaisesRegex(PlanError, expected):
                    prove_cursor_witness([inv], [witness], symbol)
                self.assertEqual(before, json.dumps([inv, witness], sort_keys=True))

    def test_missing_pairs_cannot_prove(self):
        from closed_variadic_plan import prove_cursor_witness
        inv, witness, symbol = self.fixture()
        for inventories, witnesses in (([], []), ([inv], []), ([], [witness])):
            with self.assertRaisesRegex(PlanError, 'incomplete paired units'):
                prove_cursor_witness(inventories, witnesses, symbol)

class CursorFixtureCollectionTests(unittest.TestCase):
    def collect(self, root, export, receipt, semantic):
        from unittest.mock import patch
        from check_closed_variadic_inventory import collect_cursor_fixture
        with patch('check_closed_variadic_inventory.run', return_value=export,
                   side_effect=export if isinstance(export, Exception) else None), \
             patch('full_compiler.cursor_witness_receipt', side_effect=receipt), \
             patch('closed_variadic_plan.prove_cursor_witness', side_effect=semantic) as checker:
            try:
                result = collect_cursor_fixture(root / 'tool', root / 'database', root / 'paired', {'static': 'target'})
            except (OSError, RuntimeError, KeyError, TypeError, ValueError):
                self.assertEqual(checker.call_count, 0)
                raise
            self.assertEqual(checker.call_count, 1)
            return result

    def test_export_and_binding_failures_propagate(self):
        import tempfile
        from pathlib import Path
        for label, export, receipt, error in (
                ('export', {'exit_code': 1}, None, RuntimeError),
                ('export-crash', OSError('exporter failed to start'), None, OSError),
                ('missing-receipt', {'exit_code': 0}, OSError('missing output'), OSError),
                ('malformed-receipt', {'exit_code': 0}, ValueError('invalid receipt'), ValueError),
                ('native-input', {'exit_code': 0}, ValueError('cached input differs'), ValueError),
                ('source-binding', {'exit_code': 0}, ValueError('source receipt differs'), ValueError),
                ('malformed-pair', {'exit_code': 0}, {'pairs': [{}]}, KeyError),
                ('missing-pair', {'exit_code': 0}, {'pairs': [{'inventory': '/absent/pair'}]}, OSError)):
            with self.subTest(case=label), tempfile.TemporaryDirectory() as temp:
                receipt_fn = (lambda *args, value=receipt: value) if isinstance(receipt, dict) else receipt
                with self.assertRaises(error):
                    self.collect(Path(temp), export, receipt_fn, PlanError('semantic rejection'))
                self.assertFalse((Path(temp) / 'paired/proof.json').exists())

    def test_only_semantic_plan_error_is_negative_proof(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inv, witness = root / 'inventory.json', root / 'witness.json'
            inv.write_text('{}')
            witness.write_text('{}')
            receipt = {'pairs': [{'inventory': str(inv), 'witness': str(witness)}]}
            result = self.collect(root, {'exit_code': 0}, lambda *args: receipt, PlanError('intentional semantic rejection'))
            self.assertEqual(result['status'], 'rejected')
            self.assertEqual(result['reason'], 'intentional semantic rejection')
            self.assertIn('export_command', json.loads((root / 'paired/receipt.json').read_text()))
            self.assertEqual(json.loads((root / 'paired/export-result.json').read_text())['exit_code'], 0)


if __name__ == '__main__':
    unittest.main()
