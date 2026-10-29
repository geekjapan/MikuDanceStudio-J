"""Source-route guards, not execution of the compiled exporter."""
from pathlib import Path
from itertools import product
import re
import tempfile
import unittest
from unittest.mock import patch

from check_closed_variadic_inventory import require_inventory_outputs


ROOT = Path(__file__).resolve().parent


def patched_lines(name):
    patch = (ROOT / 'patches/c2rust-win64-abi.patch').read_text()
    sections = patch.split('diff --git ')
    section = next((s for s in sections if s.startswith(f'a/{name} b/{name}\n')), '')
    return '\n'.join(line[1:] for line in section.splitlines()
                     if line.startswith((' ', '+')) and not line.startswith('+++'))


def inventory_condition(source):
    match = re.search(r'if ([^\n]+) \{\n\s*let inventory_path =', source)
    if not match:
        raise ValueError('missing typed inventory writer guard')
    condition = match[1]
    if condition != ('tcfg.emit_variadic_inventory || tcfg.emit_c_decl_map || '
                     'tcfg.emit_cursor_witness || tcfg.emit_closed_format_facts'):
        raise ValueError('typed inventory must follow inventory, map, witness, or format requests')
    return condition


def exporter_conditions(source):
    functions = re.findall(r'^fn prepare_single\([^\n]*(?:\n(?!}|(?:pub )?fn ).*)*\n}', source, re.M)
    if len(functions) != 1:
        raise ValueError('missing or duplicate prepare_single function')
    routes = re.findall(r'    let exported = (.*?)^    };', functions[0], re.S | re.M)
    expected = """if tcfg.diagnostic_common_plan {
        ast_exporter::get_prepared_untyped_ast(input_path, cc_db, extra_clang_args,
            tcfg.debug_ast_exporter, tcfg.emit_c_decl_map).map(|(ast, pp, instance)| (ast, pp, Some(instance)))
    } else {
        ast_exporter::get_untyped_ast(input_path, cc_db, extra_clang_args,
            tcfg.debug_ast_exporter, tcfg.emit_c_decl_map, retained).map(|(ast, pp)| (ast, pp, None))
"""
    if (len(routes) != 1 or routes[0].split() != expected.split()
            or functions[0].count('ast_exporter::') != 2):
        raise ValueError('exporter source collection must remain map-only')
    bindings = re.findall(
        r'    let retained = (.*?)\n    let \(typed_context, preprocessed_source, _\) = '
        r'prepare_single\(tcfg, input_path, cc_db, extra_clang_args, retained.as_deref\(\)\)\?;',
        source, re.S)
    retained = ('(tcfg.emit_cursor_witness || tcfg.emit_closed_format_facts)'
                '.then(|| output_path.with_extension("cursor.cbor"));')
    if len(bindings) != 1 or ''.join(bindings[0].split()) != ''.join(retained.split()):
        raise ValueError('ordinary retained CBOR must follow witness or format requests')
    return 'tcfg.emit_c_decl_map', '(tcfg.emit_cursor_witness || tcfg.emit_closed_format_facts)'


def check_source_tree(source):
    lib = (source / 'c2rust-transpile/src/lib.rs').read_text()
    inventory_condition(lib)
    exporter_conditions(lib)
    translator = (source / 'c2rust-transpile/src/translator/mod.rs').read_text()
    if 'let decl_source_ranges = if tcfg.emit_c_decl_map {' not in translator:
        raise ValueError('declaration source ranges must remain map-only')
    if any(flag in translator for flag in ('emit_variadic_inventory', 'emit_cursor_witness', 'emit_closed_format_facts')):
        raise ValueError('inventory flag must not enter source-map translation')
    for name in ('c2rust/src/bin/c2rust-transpile.rs',
                 'c2rust-transpile/tests/common/mod.rs',
                 'c2rust-transpile/tests/module_paths.rs'):
        text = (source / name).read_text()
        for flag in ('emit_variadic_inventory', 'emit_cursor_witness', 'emit_closed_format_facts'):
            value = 'args.' + flag if name.startswith('c2rust/') else 'false'
            if f'{flag}: {value},' not in text:
                raise ValueError('missing config initializer in ' + name)


class InventoryRouteTests(unittest.TestCase):
    def test_include_callback_matches_llvm18_module_type(self):
        exporter = patched_lines('c2rust-ast-exporter/src/AstExporter.cpp')
        self.assertIn(
            'void InclusionDirective(SourceLocation, const Token &, StringRef, bool,\n'
            '                            CharSourceRange, OptionalFileEntryRef file, StringRef,\n'
            '                            StringRef, const clang::Module *, SrcMgr::CharacteristicKind) override {\n'
            '        inputs->included(file);\n'
            '    }', exporter)

    def test_inventory_only_and_legacy_map_route(self):
        source = patched_lines('c2rust-transpile/src/lib.rs')
        condition = inventory_condition(source)
        map_condition, cbor_condition = exporter_conditions(source)
        for inventory, maps, witness, formats in product((False, True), repeat=4):
            with self.subTest(inventory=inventory, maps=maps, witness=witness, formats=formats):
                for expression, expected in (
                        (condition, inventory or maps or witness or formats),
                        (map_condition, maps), (cbor_condition, witness or formats)):
                    for flag, value in (('emit_variadic_inventory', inventory), ('emit_c_decl_map', maps),
                                        ('emit_cursor_witness', witness), ('emit_closed_format_facts', formats)):
                        expression = expression.replace('tcfg.' + flag, str(value))
                    self.assertEqual(eval(expression.replace('||', 'or'), {'__builtins__': {}}), expected)

    def test_inventory_guard_rejects_changed_routes(self):
        source = patched_lines('c2rust-transpile/src/lib.rs')
        condition = inventory_condition(source)
        for changed in (
                *(condition.replace(' || ' + flag, '').replace(flag + ' || ', '') for flag in (
                    'tcfg.emit_variadic_inventory', 'tcfg.emit_c_decl_map',
                    'tcfg.emit_cursor_witness', 'tcfg.emit_closed_format_facts')),
                'tcfg.emit_c_decl_map',
                'tcfg.emit_variadic_inventory || tcfg.emit_c_decl_map',
                'tcfg.emit_c_decl_map || tcfg.emit_cursor_witness',
                '(tcfg.emit_variadic_inventory || tcfg.emit_cursor_witness) && tcfg.emit_c_decl_map',
                condition + ' || tcfg.unknown',
                condition.replace('||', '&&', 1),
                condition + ' ||', ''):
            with self.subTest(condition=changed):
                with self.assertRaises(ValueError):
                    inventory_condition(source.replace(condition, changed))
        with self.assertRaisesRegex(ValueError, 'missing typed inventory writer guard'):
            inventory_condition(source.replace('let inventory_path =', 'let other_path ='))

    def test_source_map_collection_guards(self):
        lib = patched_lines('c2rust-transpile/src/lib.rs')
        translator = 'let decl_source_ranges = if tcfg.emit_c_decl_map {'
        files = {'lib.rs': lib, 'translator': translator}
        for name in ('c2rust/src/bin/c2rust-transpile.rs',
                     'c2rust-transpile/tests/common/mod.rs',
                     'c2rust-transpile/tests/module_paths.rs'):
            files[name] = patched_lines(name)

        def read(path):
            name = str(path)
            if name.endswith('translator/mod.rs'):
                return files['translator']
            if name.endswith('src/lib.rs'):
                return files['lib.rs']
            return files[name]

        with patch.object(Path, 'read_text', read):
            check_source_tree(Path('.'))
            files['lib.rs'] = ('fn unrelated(extra_clang_args: &[&str]) {\n'
                               '    let file = other(extra_clang_args,);\n'
                               '    ast_exporter::get_untyped_ast(file);\n}\n' + lib)
            check_source_tree(Path('.'))
            files['lib.rs'] = lib
            for changed in (
                    lib + lib,
                    lib.replace('    };\n    let (untyped_context',
                                '    };\n    let exported = other();\n    let (untyped_context'),
                    lib.replace('    Ok((typed_context, preprocessed_source, instance))\n}',
                                '    Ok((typed_context, preprocessed_source, instance))'),
                    lib.replace('fn prepare_single(', 'fn other('),
                    lib.replace('    let exported =', '    let exported = if nested {'),
                    lib.replace('    };\n    let (untyped_context', '    ;\n    let (untyped_context'),
                    lib.replace('retained).map(', 'None).map('),
                    lib.replace('get_prepared_untyped_ast(', 'other_prepared('),
                    lib.replace('tcfg.emit_c_decl_map).map(', 'true).map('),
                    lib.replace('retained.as_deref())?;', 'None)?;')):
                with self.subTest(route=changed):
                    files['lib.rs'] = changed
                    with self.assertRaises(ValueError):
                        check_source_tree(Path('.'))
            files['lib.rs'] = lib
            for key, old, new in (
                    ('lib.rs', 'tcfg.emit_c_decl_map, retained', 'tcfg.emit_c_decl_map || tcfg.emit_variadic_inventory, retained'),
                    ('lib.rs', 'tcfg.emit_c_decl_map, retained', 'tcfg.emit_c_decl_map || tcfg.emit_cursor_witness, retained'),
                    ('lib.rs', 'tcfg.emit_c_decl_map, retained', 'tcfg.emit_c_decl_map || tcfg.emit_closed_format_facts, retained'),
                    ('lib.rs', 'ast_exporter::get_untyped_ast(', 'ast_exporter::other('),
                    ('lib.rs', 'tcfg.emit_c_decl_map, retained', ''),
                    ('lib.rs', 'tcfg.emit_c_decl_map, retained', 'tcfg.emit_c_decl_map, retained, tcfg.unknown'),
                    ('lib.rs', 'tcfg.emit_cursor_witness || tcfg.emit_closed_format_facts', 'tcfg.emit_cursor_witness'),
                    ('lib.rs', 'tcfg.emit_cursor_witness || tcfg.emit_closed_format_facts', 'tcfg.emit_closed_format_facts'),
                    ('lib.rs', 'tcfg.emit_cursor_witness || tcfg.emit_closed_format_facts', 'tcfg.emit_cursor_witness && tcfg.emit_closed_format_facts'),
                    ('lib.rs', 'tcfg.emit_cursor_witness || tcfg.emit_closed_format_facts', 'tcfg.emit_cursor_witness || tcfg.emit_closed_format_facts || tcfg.emit_variadic_inventory'),
                    ('lib.rs', 'tcfg.emit_cursor_witness || tcfg.emit_closed_format_facts', 'tcfg.unknown'),
                    ('translator', 'tcfg.emit_c_decl_map {', 'tcfg.emit_c_decl_map || tcfg.emit_cursor_witness {'),
                    ('translator', 'tcfg.emit_c_decl_map {', 'tcfg.emit_c_decl_map || tcfg.emit_variadic_inventory {'),
                    ('translator', 'tcfg.emit_c_decl_map {', 'tcfg.emit_c_decl_map || tcfg.emit_closed_format_facts {'),
                    ('translator', 'tcfg.emit_c_decl_map {', 'tcfg.other {'),
                    ('c2rust/src/bin/c2rust-transpile.rs', 'emit_cursor_witness: args.emit_cursor_witness,', ''),
                    ('c2rust-transpile/tests/common/mod.rs', 'emit_cursor_witness: false,', ''),
                    ('c2rust-transpile/tests/module_paths.rs', 'emit_cursor_witness: false,', ''),
                    *((name, f'{flag}: {value},', replacement)
                      for name in ('c2rust/src/bin/c2rust-transpile.rs',
                                   'c2rust-transpile/tests/common/mod.rs',
                                   'c2rust-transpile/tests/module_paths.rs')
                      for flag in ('emit_variadic_inventory', 'emit_cursor_witness', 'emit_closed_format_facts')
                      for value in ['args.' + flag if name.startswith('c2rust/') else 'false']
                      for replacement in ('', f'{flag}: true,'))):
                with self.subTest(file=key, replacement=new):
                    original = files[key]
                    self.assertIn(old, original)
                    files[key] = original.replace(old, new, 1)
                    error = 'exporter|ordinary retained' if key == 'lib.rs' else 'source|initializer'
                    with self.assertRaisesRegex(ValueError, error):
                        check_source_tree(Path('.'))
                    files[key] = original

    def test_fixture_requires_rust_inventory_and_no_source_maps(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / 'src').mkdir()
            for suffix in ('.rs', '.variadic.json'):
                with self.assertRaisesRegex(RuntimeError, 'missing inventory translation output'):
                    require_inventory_outputs(output, ['definition'])
                (output / 'src' / ('definition' + suffix)).touch()
            require_inventory_outputs(output, ['definition'])
            (output / 'src/definition.c_decls.json').touch()
            with self.assertRaisesRegex(RuntimeError, 'emitted C declaration source maps'):
                require_inventory_outputs(output, ['definition'])

    def test_cli_config_and_all_explicit_initializers(self):
        cli = patched_lines('c2rust/src/bin/c2rust-transpile.rs')
        self.assertIn('#[clap(long)]\n    emit_variadic_inventory: bool,', cli)
        self.assertIn('emit_variadic_inventory: args.emit_variadic_inventory,', cli)
        self.assertIn('#[clap(long)]\n    emit_cursor_witness: bool,', cli)
        self.assertIn('emit_cursor_witness: args.emit_cursor_witness,', cli)
        self.assertIn('#[clap(long)]\n    emit_closed_format_facts: bool,', cli)
        self.assertIn('emit_closed_format_facts: args.emit_closed_format_facts,', cli)
        for flag in ('emit_variadic_inventory', 'emit_cursor_witness', 'emit_closed_format_facts'):
            self.assertIn(f'pub {flag}: bool,', patched_lines('c2rust-transpile/src/lib.rs'))
        for name in ('common/mod.rs', 'module_paths.rs'):
            for flag in ('emit_variadic_inventory', 'emit_cursor_witness', 'emit_closed_format_facts'):
                self.assertIn(f'{flag}: false,', patched_lines('c2rust-transpile/tests/' + name))

    def test_inventory_commands_do_not_request_maps_and_abi_still_does(self):
        self.assertIn('"--emit-variadic-inventory"', (ROOT / 'probe.py').read_text())
        self.assertNotIn('"--emit-c-decl-map"', (ROOT / 'probe.py').read_text())
        fixture = (ROOT / 'check_closed_variadic_inventory.py').read_text()
        self.assertEqual(fixture.count("'--emit-variadic-inventory'"), 3)
        self.assertNotIn("'--emit-c-decl-map'", fixture)
        abi = (ROOT / 'abi_smoke.py').read_text()
        self.assertIn('--emit-c-decl-map', abi)
        self.assertIn('native_callback', abi)


if __name__ == '__main__':
    unittest.main()
