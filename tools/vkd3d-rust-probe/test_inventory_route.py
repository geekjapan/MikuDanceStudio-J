"""Source-route guards, not execution of the compiled exporter."""
from pathlib import Path
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
    if condition != 'tcfg.emit_variadic_inventory || tcfg.emit_c_decl_map || tcfg.emit_cursor_witness':
        raise ValueError('typed inventory must follow inventory, map, or witness requests')
    return condition


def check_source_tree(source):
    lib = (source / 'c2rust-transpile/src/lib.rs').read_text()
    inventory_condition(lib)
    exporter_call = re.search(r'ast_exporter::get_untyped_ast\((.*?)\) \{', lib, re.S)
    if not exporter_call or [line.strip() for line in exporter_call[1].strip().splitlines()[-2:]] != [
            'tcfg.emit_c_decl_map,',
            'tcfg.emit_cursor_witness.then(|| output_path.with_extension("cursor.cbor")).as_deref(),']:
        raise ValueError('exporter source collection must remain map-only')
    translator = (source / 'c2rust-transpile/src/translator/mod.rs').read_text()
    if 'let decl_source_ranges = if tcfg.emit_c_decl_map {' not in translator:
        raise ValueError('declaration source ranges must remain map-only')
    if any(flag in translator for flag in ('emit_variadic_inventory', 'emit_cursor_witness')):
        raise ValueError('inventory flag must not enter source-map translation')
    for name in ('c2rust/src/bin/c2rust-transpile.rs',
                 'c2rust-transpile/tests/common/mod.rs',
                 'c2rust-transpile/tests/module_paths.rs'):
        text = (source / name).read_text()
        for flag in ('emit_variadic_inventory', 'emit_cursor_witness'):
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
        condition = inventory_condition(patched_lines('c2rust-transpile/src/lib.rs'))
        for inventory, maps, witness, expected in (
                (False, False, False, False), (False, False, True, True),
                (False, True, False, True), (False, True, True, True),
                (True, False, False, True), (True, False, True, True),
                (True, True, False, True), (True, True, True, True)):
            expression = condition.replace('tcfg.emit_variadic_inventory', str(inventory))
            expression = expression.replace('tcfg.emit_c_decl_map', str(maps))
            expression = expression.replace('tcfg.emit_cursor_witness', str(witness)).replace('||', 'or')
            self.assertEqual(eval(expression, {'__builtins__': {}}), expected)

    def test_inventory_guard_rejects_changed_routes(self):
        source = patched_lines('c2rust-transpile/src/lib.rs')
        condition = inventory_condition(source)
        for changed in (
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
        lib = ('ast_exporter::get_untyped_ast(\n'
               'tcfg.emit_c_decl_map,\n'
               'tcfg.emit_cursor_witness.then(|| output_path.with_extension("cursor.cbor")).as_deref(),\n'
               ') {\n' + patched_lines('c2rust-transpile/src/lib.rs'))
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
            for key, old, new in (
                    ('lib.rs', 'tcfg.emit_c_decl_map,', 'tcfg.emit_c_decl_map || tcfg.emit_variadic_inventory,'),
                    ('lib.rs', 'tcfg.emit_c_decl_map,', 'tcfg.emit_c_decl_map || tcfg.emit_cursor_witness,'),
                    ('translator', 'tcfg.emit_c_decl_map {', 'tcfg.emit_c_decl_map || tcfg.emit_cursor_witness {'),
                    ('translator', 'tcfg.emit_c_decl_map {', 'tcfg.emit_c_decl_map || tcfg.emit_variadic_inventory {'),
                    ('c2rust/src/bin/c2rust-transpile.rs', 'emit_cursor_witness: args.emit_cursor_witness,', ''),
                    ('c2rust-transpile/tests/common/mod.rs', 'emit_cursor_witness: false,', ''),
                    ('c2rust-transpile/tests/module_paths.rs', 'emit_cursor_witness: false,', '')):
                with self.subTest(file=key, replacement=new):
                    original = files[key]
                    files[key] = original.replace(old, new)
                    with self.assertRaises(ValueError):
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
        for flag in ('emit_variadic_inventory', 'emit_cursor_witness'):
            self.assertIn(f'pub {flag}: bool,', patched_lines('c2rust-transpile/src/lib.rs'))
        for name in ('common/mod.rs', 'module_paths.rs'):
            for flag in ('emit_variadic_inventory', 'emit_cursor_witness'):
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
