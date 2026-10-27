"""Exercise the actual patched translator's two-TU inventory, not stable lowering."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil

from closed_variadic_plan import build_plan
from full_compiler import stable_env
from probe import run


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_inventory_outputs(output, stems):
    for stem in stems:
        for suffix in ('.rs', '.variadic.json'):
            if not (output / 'src' / (stem + suffix)).is_file():
                raise RuntimeError('missing inventory translation output ' + stem + suffix)
    if any(output.rglob('*.c_decls.json')):
        raise RuntimeError('inventory-only translation emitted C declaration source maps')


def check(tool, root, clang):
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    fixtures = Path(__file__).resolve().parent / 'variadic-fixtures'
    for path in fixtures.iterdir():
        shutil.copy2(path, root / path.name)
    units = [root / 'definition.c', root / 'caller.c']
    database = root / 'compile_commands.json'
    database.write_text(json.dumps([{'directory': str(root), 'file': str(p),
                                     'arguments': [clang, '-std=c11', '-c', str(p)]} for p in units], indent=2))
    result = {'status': 'incomplete', 'stable_lowering': 'not_implemented',
              'machine': platform.platform(), 'stages': {},
              'input_sha256': {p.name: digest(p) for p in root.iterdir() if p.is_file()},
              'tool_sha256': digest(tool), 'translator_sha256': digest(tool.with_name('c2rust-transpile'))}
    env = stable_env(root / 'target')

    def stage(name, argv, timeout=60):
        record = run(argv, root / (name + '.log'), cwd=root, env=env, timeout=timeout)
        result['stages'][name] = record
        (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        if record['exit_code']:
            raise RuntimeError(name + ' failed')

    try:
        stage('clang-version', [clang, '--version'])
        stage('native-build', [clang, '-std=c11', '-Wall', '-Wextra', '-Werror',
                               *map(str, units), str(root / 'consumer.c'), '-o', str(root / 'native-check')])
        stage('native-run', [str(root / 'native-check')])
        stage('transpile', [str(tool.with_name('c2rust-transpile')), '--fail-on-error',
                            '--disable-rustfmt', '--edition', '2024', '--emit-variadic-inventory',
                            '--output-dir', str(root / 'rust'), str(database)], 120)
        require_inventory_outputs(root / 'rust', [p.stem for p in units])
        paths = [root / 'rust/src' / (p.stem + '.variadic.json') for p in units]
        if sorted(root.glob('rust/**/*.variadic.json')) != sorted(paths):
            raise RuntimeError('unexpected actual inventory paths')
        plan = build_plan([json.loads(p.read_text()) for p in paths], list(map(str, units)), ['fixture_entry'])
        symbols = {tuple(p['symbol']): p for p in plan['symbols']}
        if set(symbols) != {('linker', 'private_format'), ('linker', 'private_zero')}:
            raise RuntimeError('private globals were not joined across both translation units')
        calls = symbols[('linker', 'private_format')]['calls']
        expected = ['c_int', 'c_uint', 'c_long', 'c_ulong', 'c_longlong', 'c_ulonglong',
                    'pointer', 'pointer', 'c_double', 'c_double', 'c_int', 'c_int', 'c_int', 'c_int']
        if len(calls) != 1 or calls[0]['slots'] != expected:
            raise RuntimeError('promoted actual tail inventory differs')
        zero_calls = symbols[('linker', 'private_zero')]['calls']
        if len(zero_calls) != 1 or zero_calls[0]['slots'] != []:
            raise RuntimeError('zero-tail nested call missing')
        if {d['code'] for d in plan['diagnostics']} != {'cursor_dataflow_unproved', 'unclassified_indirect_call'}:
            raise RuntimeError('unexpected fixture diagnostic')
        (root / 'closed-plan.json').write_text(json.dumps(plan, indent=2) + '\n')
        result['generated_sha256'] = {str(p.relative_to(root)): digest(p) for p in (root / 'rust').rglob('*') if p.is_file()}
        label_root = root / 'late-asm-label'
        label_root.mkdir()
        label_input = fixtures.parent / 'exporter-fixtures/late_asm_label.c'
        label_source = label_root / label_input.name
        shutil.copy2(label_input, label_source)
        label_database = label_root / 'compile_commands.json'
        label_database.write_text(json.dumps([{'directory': str(label_root), 'file': str(label_source),
                                               'arguments': [clang, '-std=c11', '-c', str(label_source)]}]))
        stage('late-asm-label-export', [str(tool.with_name('c2rust-transpile')), '--fail-on-error',
                                       '--disable-rustfmt', '--edition', '2024', '--emit-variadic-inventory',
                                       '--output-dir', str(label_root / 'rust'), str(label_database)], 120)
        require_inventory_outputs(label_root / 'rust', ['late_asm_label'])
        label_inventory = json.loads((label_root / 'rust/src/late_asm_label.variadic.json').read_text())
        label_declarations = [d for d in label_inventory['declarations']
                              if d['symbol'] == {'linker': 'effective_late_label'}]
        if len(label_declarations) != 1 or not any(
                c['callee'] == {'linker': 'effective_late_label'} for c in label_inventory['calls']):
            raise RuntimeError('later asm label missing from actual exporter declaration or call')
        if any(d['symbol'] == {'linker': 'declared_first'} for d in label_inventory['declarations']):
            raise RuntimeError('canonical declaration lost the effective later asm label')
        result['late_asm_label_sha256'] = {str(p.relative_to(root)): digest(p)
                                         for p in label_root.rglob('*') if p.is_file()}
        result['status'] = 'inventory_fixture_success'
    except (RuntimeError, OSError, ValueError) as error:
        result['status'] = 'failure'
        result['error'] = str(error)
    finally:
        (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2rust', required=True, type=Path)
    parser.add_argument('--artifacts', required=True, type=Path)
    parser.add_argument('--clang', default='/usr/bin/clang-18')
    args = parser.parse_args()
    result = check(args.c2rust.resolve(), args.artifacts, args.clang)
    if result['status'] != 'inventory_fixture_success':
        raise SystemExit(result.get('error', result['status']))


if __name__ == '__main__':
    main()
