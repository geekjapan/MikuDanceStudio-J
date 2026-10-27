"""Exercise the actual patched translator's two-TU inventory, not stable lowering."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import platform
import re
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


RECORD_CASES = {
    'same-header': ([], 'compatible'),
    'char-signedness': (['-funsigned-char', '-UEXPECTED_CHAR_SIGNED', '-DEXPECTED_CHAR_SIGNED=0'], 'mismatch'),
    'char-signed-same': ([], 'compatible'),
    'char-unsigned-same': ([], 'compatible'),
    'explicit-signed-char': ([], 'compatible'),
    'explicit-unsigned-char': ([], 'compatible'),
    'parameter-cvr': (['-DPARAMETER_CONST='], 'compatible'),
    'array-const': (['-DARRAY_CVR=const'], 'mismatch'),
    'array-volatile': (['-DARRAY_CVR=volatile'], 'mismatch'),
    'array-const-volatile': (['-UARRAY_CVR', '-DARRAY_CVR=volatile'], 'mismatch'),
    'array-qualified-same': ([], 'compatible'),
    'array-restrict': (['-DPOINTER_ARRAY_CVR=restrict'], 'mismatch'),
    'array-restrict-same': ([], 'compatible'),
    'long-double-abi': (['-mlong-double-64', '-UEXPECTED_LONG_DOUBLE_SIZE', '-DEXPECTED_LONG_DOUBLE_SIZE=8'], 'unproved'),
    'deep-pointer': ([], 'unproved'),
    'unsupported-atomic': ([], 'unproved'),
    'field-type': (['-DFIELD_TYPE=long'], 'mismatch'),
    'field-name': (['-DFIELD_NAME=renamed'], 'mismatch'),
    'field-order': (['-DREVERSE_FIELDS'], 'mismatch'),
    'array-length': (['-DARRAY_LENGTH=3'], 'mismatch'),
    'different-tag': (['-DDIFFERENT_TAG'], 'mismatch'),
    'different-kind': (['-DUNION_KIND'], 'mismatch'),
    'packing': (['-DPACKING=1'], 'mismatch'),
    'alignment': (['-DRECORD_ALIGNMENT=16'], 'mismatch'),
    'union-alignment': (['-DUNION_ALIGNMENT=16'], 'mismatch'),
    'enum-value': (['-DENUM_VALUE=3'], 'mismatch'),
    'enum-underlying': (['-fshort-enums'], 'mismatch'),
    'pointee-cvr': (['-DPOINTER_CONST='], 'mismatch'),
    'function-abi': (['-DCALLBACK_ABI=__attribute__((ms_abi))'], 'reject'),
    'macro-declaration': (['-DMACRO_DECL'], 'unproved'),
    'prototype-scope': (['-DPROTOTYPE_SCOPE'], 'unproved'),
    'block-scope': (['-DBLOCK_SCOPE'], 'unproved'),
    'forward-only': (['-DFORWARD_ONLY'], 'unproved'),
}


RECORD_BASE_FLAGS = {
    'char-signedness': ['--target=x86_64-unknown-linux-gnu', '-DCALLBACK_ARGUMENT_TYPE=char', '-DEXPECTED_CHAR_SIGNED=1'],
    'char-signed-same': ['--target=x86_64-unknown-linux-gnu', '-fsigned-char', '-DCALLBACK_ARGUMENT_TYPE=char', '-DEXPECTED_CHAR_SIGNED=1'],
    'char-unsigned-same': ['--target=x86_64-unknown-linux-gnu', '-funsigned-char', '-DCALLBACK_ARGUMENT_TYPE=char', '-DEXPECTED_CHAR_SIGNED=0'],
    'explicit-signed-char': ['--target=x86_64-unknown-linux-gnu', '-funsigned-char', '-DCALLBACK_ARGUMENT_TYPE=signed char'],
    'explicit-unsigned-char': ['--target=x86_64-unknown-linux-gnu', '-funsigned-char', '-DCALLBACK_ARGUMENT_TYPE=unsigned char'],
    'array-const-volatile': ['-DARRAY_CVR=const'],
    'array-qualified-same': ['-DARRAY_CVR=const volatile'],
    'array-restrict-same': ['-DPOINTER_ARRAY_CVR=restrict'],
    'long-double-abi': ['--target=x86_64-unknown-linux-gnu', '-DCALLBACK_ARGUMENT_TYPE=long double', '-DEXPECTED_LONG_DOUBLE_SIZE=16'],
    'deep-pointer': ['-DDEEP_POINTER'],
    'unsupported-atomic': ['-DUNSUPPORTED_ATOMIC'],
}


def check_physical_boundaries(inventories, units):
    results = {}
    for name, field, value in [('unknown-path', 'path', '?'), ('zero-line', 'line', 0),
                                ('zero-column', 'column', 0)]:
        mutated = copy.deepcopy(inventories)

        def mutate(value_tree):
            if isinstance(value_tree, dict):
                if 'physical' in value_tree and isinstance(value_tree['physical'], dict):
                    value_tree['physical'][field] = value
                for child in value_tree.values():
                    mutate(child)
            elif isinstance(value_tree, list):
                for child in value_tree:
                    mutate(child)

        mutate(mutated)
        plan = build_plan(mutated, list(map(str, units)), [])
        if 'record_compatibility_unproved' not in {d['code'] for d in plan['diagnostics']}:
            raise RuntimeError('actual-export-derived physical boundary accepted ' + name)
        results[name] = {'origin': 'actual-export-derived payload mutation', 'inventories': mutated, 'plan': plan}
    return results


def check_char_boundaries(inventories, units):
    results = {}
    for name, value in [('missing', None), ('unknown', 'unknown'), ('integer', 1)]:
        mutated = copy.deepcopy(inventories)

        def mutate(tree):
            if isinstance(tree, dict):
                if tree.get('kind') == 'Char':
                    if value is None:
                        tree.pop('signed', None)
                    else:
                        tree['signed'] = value
                for child in tree.values():
                    mutate(child)
            elif isinstance(tree, list):
                for child in tree:
                    mutate(child)

        mutate(mutated)
        plan = build_plan(mutated, list(map(str, units)), [])
        if 'record_compatibility_unproved' not in {d['code'] for d in plan['diagnostics']}:
            raise RuntimeError('actual-export-derived char boundary accepted ' + name)
        results[name] = {'origin': 'actual-export-derived payload mutation', 'inventories': mutated, 'plan': plan}
    return results


def check_records(tool, root, clang, stage):
    fixtures = Path(__file__).resolve().parent / 'record-fixtures'
    summaries = {}
    for case, (flags, expected) in RECORD_CASES.items():
        case_root = root / ('record-' + case)
        case_root.mkdir()
        for path in fixtures.iterdir():
            shutil.copy2(path, case_root / path.name)
        units = [case_root / name for name in ('definition.c', 'caller.c')]
        entries = []
        for index, unit in enumerate(units):
            args = [clang, '-std=c11', '-DPACKING=8', *RECORD_BASE_FLAGS.get(case, []), *(flags if index else []), str(unit)]
            stage('record-' + case + '-syntax-' + str(index), [*args, '-fsyntax-only'])
            entries.append({'directory': str(case_root), 'file': str(unit), 'arguments': [*args, '-c']})
        database = case_root / 'compile_commands.json'
        database.write_text(json.dumps(entries, indent=2))
        stage('record-' + case + '-export', [str(tool.with_name('c2rust-transpile')), '--fail-on-error',
              '--disable-rustfmt', '--edition', '2024', '--emit-variadic-inventory',
              '--output-dir', str(case_root / 'rust'), str(database)], 120)
        require_inventory_outputs(case_root / 'rust', ['definition', 'caller'])
        inventories = [json.loads((case_root / 'rust/src' / (unit.stem + '.variadic.json')).read_text()) for unit in units]
        plan = build_plan(inventories, list(map(str, units)), [])
        codes = {d['code'] for d in plan['diagnostics']}
        rejects = codes & {'signature_mismatch', 'record_compatibility_unproved'}
        if expected == 'compatible' and rejects or expected == 'mismatch' and 'signature_mismatch' not in codes or expected == 'unproved' and 'record_compatibility_unproved' not in codes or expected == 'reject' and not rejects:
            raise RuntimeError('actual record evidence oracle failed for ' + case + ': ' + str(codes))
        if case.startswith('array-') or case == 'same-header':
            for index, inv in enumerate(inventories):
                definition = next(d for d in inv['record_definitions'] if d['identity'].get('tag') == 'shared_record')
                fields = {f['name']: f['type'] for f in definition['facts']['fields']}
                expected_cvr = {'const': case == 'array-qualified-same' or case == 'array-const' and index == 1 or case == 'array-const-volatile' and index == 0,
                                'volatile': case == 'array-qualified-same' or case in ('array-volatile', 'array-const-volatile') and index == 1}
                for name, levels in [('array', 1), ('nested_array', 2), ('flexible', 1)]:
                    element = fields[name]
                    for _ in range(levels):
                        element = element['canonical']['array']
                    if any(element[q] != expected for q, expected in expected_cvr.items()):
                        raise RuntimeError('actual array element qualifiers lost for ' + case + '/' + name)
                restricted = fields['pointer_array']['canonical']['array']['restrict']
                if restricted != (case == 'array-restrict-same' or case == 'array-restrict' and index == 1):
                    raise RuntimeError('actual restrict pointer array element qualifier lost')
        if case.startswith('char-') or case.startswith('explicit-'):
            for index, inv in enumerate(inventories):
                record = next(d for d in inv['record_definitions'] if d['identity'].get('tag') == 'shared_record')
                field = next(f for f in record['facts']['fields'] if f['name'] == 'abi_callback')
                argument = field['type']['canonical']['pointer']['canonical']['parameters'][0]['canonical']
                if case.startswith('char-'):
                    expected_char = {'kind': 'Char', 'signed': case != 'char-unsigned-same' and not (case == 'char-signedness' and index == 1)}
                else:
                    expected_char = {'kind': 'SChar' if case == 'explicit-signed-char' else 'UChar'}
                if argument != expected_char:
                    raise RuntimeError('actual compiler char metadata lost for ' + case)
            if case == 'char-signed-same':
                boundaries = check_char_boundaries(inventories, units)
                (case_root / 'char-boundary-mutations.json').write_text(json.dumps(boundaries, indent=2) + '\n')
        if case in ('deep-pointer', 'unsupported-atomic', 'long-double-abi'):
            sentinel = {'deep-pointer': 'type depth limit', 'unsupported-atomic': 'unsupported type or wrapper limit',
                        'long-double-abi': 'long double ABI shape'}[case]
            if not all(sentinel in json.dumps(inv['record_definitions']) for inv in inventories):
                raise RuntimeError('actual serializer did not emit expected unproved fact for ' + case)
        if case == 'same-header':
            boundaries = check_physical_boundaries(inventories, units)
            (case_root / 'physical-boundary-mutations.json').write_text(json.dumps(boundaries, indent=2) + '\n')
            declarations = [next(d for d in inv['record_definitions'] if d['identity'].get('tag') == 'shared_record') for inv in inventories]
            identities = [d['identity'] for d in declarations]
            fileids = [re.search(r'fileid (\d+)', d['diagnostic_location']) for d in declarations]
            if not all(fileids) or fileids[0][1] == fileids[1][1]:
                raise RuntimeError('fixture did not exercise different TU-local record file IDs')
            physical_line = next(index for index, line in enumerate((case_root / 'shared.h').read_text().splitlines(), 1) if line == 'struct shared_record {')
            if identities[0] != identities[1] or identities[0]['physical'] != {'path': str(case_root / 'shared.h'), 'line': physical_line, 'column': 1} or not all(int(re.search(r':(\d+):\d+$', d['diagnostic_location'])[1]) >= 700 for d in declarations):
                raise RuntimeError('#line changed dedicated physical identity')
        (case_root / 'closed-plan.json').write_text(json.dumps(plan, indent=2) + '\n')
        summaries[case] = {'expected': expected, 'diagnostics': sorted(codes),
                           'input_sha256': {p.name: digest(p) for p in case_root.iterdir() if p.is_file()},
                           'inventory_sha256': {unit.stem: digest(case_root / 'rust/src' / (unit.stem + '.variadic.json')) for unit in units},
                           'generated_sha256': {str(p.relative_to(case_root)): digest(p) for p in (case_root / 'rust').rglob('*') if p.is_file()}}
    return summaries


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
        result['record_cases'] = check_records(tool, root, clang, stage)
        result['cursor_witness_cases'] = check_cursor_cases(tool, root, clang, stage)
        result['status'] = 'inventory_fixture_success'
    except (RuntimeError, OSError, ValueError) as error:
        result['status'] = 'failure'
        result['error'] = str(error)
    finally:
        (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result



def check_cursor_cases(tool, root, clang, stage):
    from full_compiler import collect_cursor_witness
    fixture = Path(__file__).parent / 'fixtures/cursor-witness/pilot.c'
    results = {}
    for case in ('positive', 'ESCAPE', 'ASSIGNMENT', 'COPY', 'BRANCH', 'MISSING_END', 'UNKNOWN_CALL', 'UNKNOWN_BUILTIN'):
        case_root = root / ('cursor-' + case.lower())
        case_root.mkdir()
        source = case_root / 'pilot.c'
        shutil.copy2(fixture, source)
        database = case_root / 'compile_commands.json'
        flags = [] if case == 'positive' else ['-D' + case]
        argv = [clang, '-std=c11', *flags, '-c', str(source)]
        stage('cursor-' + case + '-syntax', [*argv, '-fsyntax-only'])
        database.write_text(json.dumps([{'directory': str(case_root), 'file': str(source), 'arguments': argv}]))
        proof = collect_cursor_witness(tool.with_name('c2rust-transpile'), database, case_root / 'paired', run,
                                       {'unit': str(source), 'static': 'cursor_pilot'})
        expected = 'witness_proven' if case == 'positive' else 'rejected'
        if proof['status'] != expected:
            raise RuntimeError('actual cursor fixture oracle differs for ' + case + ': ' + str(proof))
        results[case] = proof
        if case == 'positive':
            from full_compiler import prove_bound_cursor_witness
            from closed_variadic_plan import PlanError, prove_cursor_witness
            receipt = json.loads((case_root / 'paired/receipt.json').read_text())
            pair = receipt['pairs'][0]
            original = json.loads(Path(pair['witness']).read_text())
            inventory = json.loads(Path(pair['inventory']).read_text())
            mutations = {}
            for name in ('unknown-builtin', 'unknown-cursor-reference', 'incomplete-body', 'call-set'):
                witness = copy.deepcopy(original)
                function = next(f for f in witness['functions'] if f['symbol']['static'] == 'cursor_pilot')
                if name == 'unknown-builtin':
                    for statement in function['statements']:
                        for expression in statement['expressions']:
                            if expression.get('builtin') and expression['builtin'][1] == 'va_start':
                                expression['builtin'] = [0, 'va_start']
                elif name == 'unknown-cursor-reference':
                    function['cursor_references'].append({'id': -1, 'decl': function['cursors'][0], 'type': {}})
                elif name == 'incomplete-body':
                    function['complete_body'] = False
                else:
                    witness['calls'] = []
                try:
                    prove_cursor_witness([inventory], [witness], function['symbol'])
                except PlanError as error:
                    mutations[name] = {'origin': 'actual-export-derived payload mutation', 'witness': witness, 'reason': str(error)}
                else:
                    raise RuntimeError('cursor mutation accepted: ' + name)
            tampered = copy.deepcopy(receipt)
            tampered['pairs'][0]['files'][pair['witness']] = '0' * 64
            try:
                prove_bound_cursor_witness(tampered, {'unit': str(source), 'static': 'cursor_pilot'})
            except PlanError as error:
                mutations['tampered-binding'] = {'receipt': tampered, 'reason': str(error)}
            else:
                raise RuntimeError('cursor tampered binding accepted')
            (case_root / 'mutations.json').write_text(json.dumps(mutations, indent=2) + '\n')
    return results

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
