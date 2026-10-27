"""Join actual C2Rust typed-AST inventories without authorizing stable lowering."""
import argparse
import hashlib
import json
import re
from pathlib import Path


class PlanError(ValueError):
    pass


def symbol_key(symbol):
    if set(symbol) == {'linker'}:
        return ('linker', symbol['linker'])
    if set(symbol) == {'unit', 'static'}:
        return ('static', symbol['unit'], symbol['static'])
    raise PlanError('invalid symbol identity')


def compatible_type(typ):
    if isinstance(typ, list):
        return [compatible_type(t) for t in typ]
    if not isinstance(typ, dict):
        return typ
    result = {key: compatible_type(value) for key, value in typ.items()}
    if 'parameters' in result:
        # C function compatibility ignores parameter CVR, not pointee CVR.
        result['parameters'] = [{k: v for k, v in parameter.items()
                                 if k not in ('const', 'volatile', 'restrict')}
                                for parameter in result['parameters']]
    return result


def function_signature(declaration):
    return compatible_type(declaration['signature']['canonical'])


def promoted_slot(argument):
    typ = argument['type']
    if typ is None:
        raise PlanError('missing promoted argument type')
    canonical = typ['canonical']
    if 'pointer' in canonical:
        if 'return' in canonical['pointer']['canonical']:
            raise PlanError('unsupported function pointer tail')
        return 'pointer'
    kind = canonical.get('kind')
    slots = {'Int': 'c_int', 'UInt': 'c_uint', 'Long': 'c_long',
             'ULong': 'c_ulong', 'LongLong': 'c_longlong',
             'ULongLong': 'c_ulonglong', 'Double': 'c_double'}
    if kind not in slots:
        raise PlanError('unsupported or unpromoted tail type ' + json.dumps(canonical, sort_keys=True))
    return slots[kind]


def build_plan(inventories, expected_units, exports):
    units = [item['unit'] for item in inventories]
    if len(units) != len(set(units)) or set(units) != set(expected_units):
        raise PlanError('translation unit inventory differs from closed input manifest')
    targets = {item['target'] for item in inventories}
    if len(targets) != 1:
        raise PlanError('mixed target inventories')
    widths = inventories[0]['target_c_widths_bits']
    expected_widths = {'char': 8, 'short': 16, 'int': 32, 'long': 64,
                       'long_long': 64, 'pointer': 64, 'float': 32, 'double': 64}
    target = next(iter(targets))
    if target.startswith('x86_64-') and 'windows' in target:
        expected_widths['long'] = 32
    elif not ((target.startswith(('aarch64-', 'arm64-')) and 'apple' in target)
              or (target.startswith(('aarch64-', 'x86_64-')) and 'linux' in target)):
        raise PlanError('unsupported target for closed variadic slots')
    if widths != expected_widths or any(i['target_c_widths_bits'] != widths for i in inventories):
        raise PlanError('Clang target C widths differ from supported slot contract')
    declarations = {}
    for item in inventories:
        if item['schema'] != 1 or item['authorization'] != 'inventory_only':
            raise PlanError('unsupported inventory contract')
        for declaration in item['declarations']:
            key = symbol_key(declaration['symbol'])
            declarations.setdefault(key, []).append(declaration)
    candidates = {}
    diagnostics = []

    def reject(code, key, location, detail=None):
        diagnostics.append({'code': code, 'symbol': list(key), 'location': location, 'detail': detail})

    alias_targets = {}
    for item in inventories:
        for declaration in item['declarations']:
            key = symbol_key(declaration['symbol'])
            for name in declaration.get('aliases', []):
                target = ('static', item['unit'], name)
                if target not in declarations:
                    target = ('linker', name)
                alias_targets.setdefault(key, set()).add(target)
                reject('unsupported_linker_alias', key, declaration['location'], list(target))
                if target not in declarations:
                    reject('unresolved_linker_alias', key, declaration['location'], list(target))

    alias_reachable = {}
    for key, targets in alias_targets.items():
        location = declarations[key][0]['location']
        if len(targets) != 1:
            reject('ambiguous_linker_alias', key, location)
        reachable = set()
        pending = [(key, ())]
        while pending:
            current, path = pending.pop()
            if current in path:
                reject('cyclic_linker_alias', key, location, [list(k) for k in (*path, current)])
                continue
            if current in reachable:
                continue
            reachable.add(current)
            pending.extend((target, (*path, current)) for target in sorted(alias_targets.get(current, ())))
        alias_reachable[key] = reachable

    for key, records in declarations.items():
        definitions = [d for d in records if d['definition']]
        if not definitions or not any(function_signature(d)['variadic'] or d['va_parameters'] for d in definitions):
            continue
        definition = definitions[0]
        signature = function_signature(definition)
        candidates[key] = {'symbol': list(key), 'definition': definition['location'],
                           'signature': signature, 'calls': []}
        if len(definitions) != 1:
            reject('multiple_definitions', key, definition['location'])
        if any(function_signature(d) != signature for d in records):
            reject('signature_mismatch', key, definition['location'])
        if key[0] == 'linker' and key[1] in exports:
            reject('exported_variadic_or_cursor_definition', key, definition['location'])
        if signature['abi'] != 'C' or not signature['prototype']:
            reject('unsupported_calling_convention_or_prototype', key, definition['location'])
        reject('cursor_dataflow_unproved', key, definition['location'])
    for alias, reachable in alias_reachable.items():
        for key in sorted(reachable & candidates.keys()):
            reject('unsupported_linker_alias', key, declarations[alias][0]['location'], list(alias))
            if alias[0] == 'linker' and alias[1] in exports:
                reject('exported_variadic_or_cursor_definition', key, declarations[alias][0]['location'], list(alias))

    def visible_candidates(key):
        return sorted(alias_reachable.get(key, {key}) & candidates.keys())

    for item in inventories:
        owners = {d['id']: symbol_key(d['symbol']) for d in item['declarations']}
        for escape in item['non_call_references']:
            key = symbol_key(escape['symbol'])
            for candidate in visible_candidates(key):
                reject('address_escape', candidate, escape['location'])
        for use in item['va_arg']:
            key = owners.get(use['owner'])
            if key in candidates:
                reject('unsupported_va_arg', key, use['location'])
        for call in item['calls']:
            owner = owners.get(call['owner'])
            if call['callee'] is None:
                if owner in candidates:
                    reject('unclassified_indirect_call', owner, call['location'])
                continue
            key = symbol_key(call['callee'])
            for key in visible_candidates(key):
                signature = candidates[key]['signature']
                fixed = len(signature['parameters'])
                if len(call['arguments']) < fixed or (not signature['variadic'] and len(call['arguments']) != fixed):
                    reject('argument_count_mismatch', key, call['location'])
                    continue
                slots = []
                for argument in call['arguments'][fixed:]:
                    try:
                        slots.append(promoted_slot(argument))
                    except PlanError as error:
                        reject('unsupported_tail_type', key, call['location'], str(error))
                candidates[key]['calls'].append({'unit': item['unit'], 'location': call['location'],
                                                 'expression': call['id'], 'slots': slots})
    return {'schema': 1, 'target': target, 'target_c_widths_bits': widths, 'authorization': 'inventory_only',
            'units': sorted(units), 'symbols': list(candidates.values()),
            'diagnostics': diagnostics,
            'remaining_gates': ['four_host_target_C_width_execution', 'cursor_alias_and_control_flow',
                                'generator_lowering', 'four_host_generated_code_ABI']}


def collect_probe(root):
    from full_compiler import UNITS
    database = root / 'compile_commands.json'
    entries = json.loads(database.read_text())
    source = root / 'source'
    units = [str(Path(e['file']).resolve()) for e in entries]
    actual = sorted(str(Path(p).relative_to(source.resolve())) for p in units)
    if actual != sorted(UNITS):
        raise PlanError('actual shader input paths differ from frozen 24-unit manifest')
    export_map = source / 'libs/vkd3d-shader/vkd3d_shader.map'
    text = export_map.read_text()
    match = re.fullmatch(r'\s*VKD3D_1_0\s*\{\s*global:\s*((?:\w+;\s*)+)local:\s*\*;\s*\};\s*', text)
    if not match:
        raise PlanError('unrecognized native export map; local wildcard required')
    exports = re.findall(r'(\w+);', match.group(1))
    if len(exports) != 23 or len(set(exports)) != 23:
        raise PlanError('native public export inventory differs from frozen 23 exports')
    paths = sorted((root / 'rust-raw').rglob('*.variadic.json'))
    plan = build_plan([json.loads(p.read_text()) for p in paths], units, exports)
    plan['inventory_sha256'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    plan['source_sha256'] = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in units}
    plan['native_export_map_sha256'] = hashlib.sha256(export_map.read_bytes()).hexdigest()
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', type=Path, help='actual all-24 probe artifact directory')
    parser.add_argument('--inventories', nargs='+', type=Path)
    parser.add_argument('--units', type=Path, help='JSON array of exact input unit paths')
    parser.add_argument('--exports', type=Path, help='JSON array from the native public export map')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.probe:
        if args.inventories or args.units or args.exports:
            parser.error('--probe cannot mix with an explicit inventory contract')
        plan = collect_probe(args.probe.resolve())
    else:
        if not args.inventories or not args.units or not args.exports:
            parser.error('--inventories, --units and --exports are required together')
        plan = build_plan([json.loads(p.read_text()) for p in args.inventories],
                          json.loads(args.units.read_text()), json.loads(args.exports.read_text()))
        plan['inventory_sha256'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in args.inventories}
        plan['exports_sha256'] = hashlib.sha256(args.exports.read_bytes()).hexdigest()
        plan['units_sha256'] = hashlib.sha256(args.units.read_bytes()).hexdigest()
    with args.output.open('x') as output:
        json.dump(plan, output, indent=2)
        output.write('\n')


if __name__ == '__main__':
    main()
