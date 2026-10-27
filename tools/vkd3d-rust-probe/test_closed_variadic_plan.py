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

    def test_promoted_types_and_rejections(self):
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
