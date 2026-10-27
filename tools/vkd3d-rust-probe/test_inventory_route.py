"""Source-route guards, not execution of the compiled exporter."""
from pathlib import Path
import re
import tempfile
import unittest

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
    if condition != 'tcfg.emit_variadic_inventory || tcfg.emit_c_decl_map':
        raise ValueError('typed inventory must be independent of source maps')
    return condition


def check_source_tree(source):
    lib = (source / 'c2rust-transpile/src/lib.rs').read_text()
    inventory_condition(lib)
    exporter_call = re.search(r'ast_exporter::get_untyped_ast\((.*?)\) \{', lib, re.S)
    if not exporter_call or exporter_call[1].strip().splitlines()[-1].strip() != 'tcfg.emit_c_decl_map,':
        raise ValueError('exporter source collection must remain map-only')
    translator = (source / 'c2rust-transpile/src/translator/mod.rs').read_text()
    if 'let decl_source_ranges = if tcfg.emit_c_decl_map {' not in translator:
        raise ValueError('declaration source ranges must remain map-only')
    if 'emit_variadic_inventory' in translator:
        raise ValueError('inventory flag must not enter source-map translation')
    for name in ('c2rust/src/bin/c2rust-transpile.rs',
                 'c2rust-transpile/tests/common/mod.rs',
                 'c2rust-transpile/tests/module_paths.rs'):
        text = (source / name).read_text()
        if not re.search(r'emit_variadic_inventory: (?:args.emit_variadic_inventory|false),', text):
            raise ValueError('missing config initializer in ' + name)


class InventoryRouteTests(unittest.TestCase):
    def test_inventory_only_and_legacy_map_route(self):
        condition = inventory_condition(patched_lines('c2rust-transpile/src/lib.rs'))
        for inventory, maps, expected in ((False, False, False), (True, False, True),
                                          (False, True, True), (True, True, True)):
            expression = condition.replace('tcfg.emit_variadic_inventory', str(inventory))
            expression = expression.replace('tcfg.emit_c_decl_map', str(maps)).replace('||', 'or')
            self.assertEqual(eval(expression, {'__builtins__': {}}), expected)

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
        self.assertIn('pub emit_variadic_inventory: bool,', patched_lines('c2rust-transpile/src/lib.rs'))
        for name in ('common/mod.rs', 'module_paths.rs'):
            self.assertIn('emit_variadic_inventory: false,', patched_lines('c2rust-transpile/tests/' + name))

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
