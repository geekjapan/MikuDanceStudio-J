import unittest
import json
from pathlib import Path
import tempfile

from closed_variadic_plan import PlanError, build_plan, collect_probe, promoted_slot


def scalar(kind):
    return {'canonical': {'kind': kind}, 'const': False, 'volatile': False}


def inventory(unit, definition=False):
    signature = {'canonical': {'return': scalar('Int'), 'parameters': [scalar('Int')],
                              'variadic': True, 'noreturn': False, 'prototype': True, 'abi': 'C'}}
    return {'schema': 1, 'authorization': 'inventory_only', 'unit': unit, 'target': 'x86_64-unknown-linux-gnu',
            'target_c_widths_bits': {'char': 8, 'short': 16, 'int': 32, 'long': 64, 'long_long': 64, 'pointer': 64, 'float': 32, 'double': 64},
            'declarations': [{'id': 1, 'symbol': {'linker': 'format'}, 'location': unit + ':1',
                              'signature': signature, 'definition': definition, 'va_parameters': []}],
            'calls': [], 'non_call_references': [], 'va_arg': []}


class ClosedPlanTests(unittest.TestCase):
    def plan(self, a=None, b=None, exports=()):
        return build_plan([a or inventory('definition.c', True), b or inventory('caller.c')],
                          ['definition.c', 'caller.c'], exports)

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
                            {'canonical': {'pointer': scalar('Int')}, 'const': False}]
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
                {'canonical': {'pointer': scalar('Int')}, 'const': False}]
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


if __name__ == '__main__':
    unittest.main()
