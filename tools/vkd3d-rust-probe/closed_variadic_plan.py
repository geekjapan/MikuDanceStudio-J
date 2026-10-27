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


class RecordUnproved(PlanError):
    pass


def record_key(identity, depth=0):
    if depth > 32 or not isinstance(identity, dict) or set(identity) != {'kind', 'tag', 'physical', 'scope'}:
        raise RecordUnproved('missing structured physical record identity')
    if identity['kind'] not in ('struct', 'union', 'enum') or not (
            identity['tag'] is None or isinstance(identity['tag'], str) and identity['tag']):
        raise RecordUnproved('unsupported record kind or tag')
    physical = identity['physical']
    if not isinstance(physical, dict) or set(physical) != {'path', 'line', 'column'}:
        raise RecordUnproved('missing dedicated physical position')
    if not isinstance(physical['path'], str) or not Path(physical['path']).is_absolute() or any(
            type(physical[k]) is not int or physical[k] <= 0 for k in ('line', 'column')):
        raise RecordUnproved('invalid physical record position')
    scope = identity['scope']
    if not (isinstance(scope, dict) and set(scope) == {'file'} and scope['file'] is True):
        if not isinstance(scope, dict) or set(scope) != {'record'}:
            raise RecordUnproved('unproved owning scope')
        record_key(scope['record'], depth + 1)
    return json.dumps(identity, sort_keys=True)


def record_table(inventory):
    if not isinstance(inventory.get('record_definitions'), list):
        raise PlanError('missing finite record definition table')
    table = {}
    for entry in inventory['record_definitions']:
        if not isinstance(entry, dict) or set(entry) not in ({'identity', 'state', 'facts'}, {'identity', 'state', 'facts', 'diagnostic_location'}):
            raise PlanError('invalid record definition entry')
        if entry['state'] not in ('complete', 'incomplete', 'unproved'):
            raise PlanError('invalid record definition state')
        entry = {k: v for k, v in entry.items() if k != 'diagnostic_location'}
        try:
            key = record_key(entry['identity'])
        except RecordUnproved:
            continue  # Unreachable unknown records do not prove any required type.
        if key in table and table[key] != entry:
            table[key] = {'state': 'unproved'}
        else:
            table[key] = entry
    return table


SCALARS = {'Void', 'Bool', 'Char', 'SChar', 'Short', 'Int', 'Long', 'LongLong',
           'UChar', 'UShort', 'UInt', 'ULong', 'ULongLong', 'Float', 'Double',
           'LongDouble', 'Int128', 'UInt128', 'Half'}


def validate_type(typ, table, visited=None, depth=0):
    visited = set() if visited is None else visited
    if depth > 64 or not isinstance(typ, dict) or set(typ) != {'canonical', 'const', 'volatile', 'restrict'}:
        raise RecordUnproved('unknown or excessive required type evidence')
    if 'canonical' not in typ or any(type(v) is not bool for k, v in typ.items() if k != 'canonical'):
        raise RecordUnproved('missing canonical type or invalid qualifiers')
    canonical = typ['canonical']
    if not isinstance(canonical, dict):
        raise RecordUnproved('missing canonical type facts')
    keys = set(canonical)
    if keys == {'kind'} and isinstance(canonical['kind'], str) and canonical['kind'] in SCALARS:
        return
    if keys == {'pointer'}:
        validate_type(canonical['pointer'], table, visited, depth=depth + 1)
    elif keys in ({'array'}, {'array', 'length'}):
        if 'length' in canonical and (type(canonical['length']) is not int or canonical['length'] < 0):
            raise RecordUnproved('invalid array length')
        validate_type(canonical['array'], table, visited, depth=depth + 1)
    elif keys == {'return', 'parameters', 'variadic', 'noreturn', 'prototype', 'abi'}:
        if canonical['abi'] not in ('C', 'win64', 'sysv64') or not isinstance(canonical['parameters'], list) or any(
                type(canonical[k]) is not bool for k in ('variadic', 'noreturn', 'prototype')):
            raise RecordUnproved('invalid function ABI evidence')
        validate_type(canonical['return'], table, visited, depth=depth + 1)
        for arg in canonical['parameters']:
            validate_type(arg, table, visited, depth=depth + 1)
    elif keys == {'record'}:
        identity = canonical['record']
        key = record_key(identity)
        entry = table.get(key)
        if entry is None or entry['state'] != 'complete':
            raise RecordUnproved('required record has no proved complete definition')
        if key in visited:
            return
        visited.add(key)
        facts = entry['facts']
        if not isinstance(facts, dict):
            raise RecordUnproved('invalid record definition facts')
        if identity['kind'] == 'enum':
            if set(facts) != {'underlying', 'variants'} or not isinstance(facts['variants'], list):
                raise RecordUnproved('missing enum definition facts')
            validate_type(facts['underlying'], table, visited, depth=depth + 1)
            for variant in facts['variants']:
                if not isinstance(variant, dict) or set(variant) != {'name', 'signed', 'value'} or not isinstance(variant['name'], str) or type(variant['signed']) is not bool or type(variant['value']) is not int:
                    raise RecordUnproved('invalid enum variant evidence')
        else:
            if set(facts) != {'fields', 'layout'} or not isinstance(facts['fields'], list):
                raise RecordUnproved('missing ordered fields')
            layout = facts['layout']
            if not isinstance(layout, list) or len(layout) != 5 or type(layout[0]) is not bool or any(
                    v is not None and (type(v) is not int or v <= 0) for v in layout[1:3]) or any(
                    type(v) is not int or v < 0 for v in layout[3:]) or layout[4] == 0:
                raise RecordUnproved('missing record layout proof')
            for field in facts['fields']:
                if not isinstance(field, dict) or set(field) != {'name', 'type', 'bit_width', 'bit_offset', 'type_bit_width', 'alignment'} or not isinstance(field['name'], str):
                    raise RecordUnproved('invalid ordered field evidence')
                if any(type(field[k]) is not int or field[k] < 0 for k in ('bit_offset', 'type_bit_width')) or any(
                        field[k] is not None and (type(field[k]) is not int or field[k] < 0) for k in ('bit_width', 'alignment')):
                    raise RecordUnproved('invalid field layout evidence')
                validate_type(field['type'], table, visited, depth=depth + 1)
    else:
        raise RecordUnproved('unsupported required type evidence')


def compare_evidence(left, right, left_table, right_table, visited=None):
    visited = set() if visited is None else visited
    if isinstance(left, dict) and isinstance(right, dict):
        for value in (left, right):
            if 'unproved' in value or 'unsupported' in value:
                raise RecordUnproved('unsupported or incomplete required type evidence')
            if 'kind' in value and 'physical' not in value and value['kind'] not in SCALARS:
                raise RecordUnproved('unsupported required type kind')
        if set(left) != set(right):
            return False
        if set(left) == {'record'}:
            lk, rk = record_key(left['record']), record_key(right['record'])
            for key, table in ((lk, left_table), (rk, right_table)):
                if key not in table or table[key]['state'] != 'complete':
                    raise RecordUnproved('required record has no proved complete definition')
            pair = (lk, rk)
            if pair in visited:
                return True
            visited.add(pair)
            if lk != rk:
                return False
            lf, rf = left_table[lk]['facts'], right_table[rk]['facts']
            for facts, identity in ((lf, left['record']), (rf, right['record'])):
                if identity['kind'] == 'enum':
                    if set(facts) != {'underlying', 'variants'} or facts['underlying'] is None or not isinstance(facts['variants'], list):
                        raise RecordUnproved('missing enum definition facts')
                elif set(facts) != {'fields', 'layout'} or not isinstance(facts['fields'], list) or not isinstance(facts['layout'], list) or len(facts['layout']) != 5:
                    raise RecordUnproved('missing record definition or layout facts')
            return compare_evidence(compatible_type(lf), compatible_type(rf), left_table, right_table, visited)
        results = [compare_evidence(left[k], right[k], left_table, right_table, visited) for k in left]
        return all(results)
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return False
        return all([compare_evidence(a, b, left_table, right_table, visited) for a, b in zip(left, right)])
    return type(left) is type(right) and left == right


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
    tables = {}
    for item in inventories:
        if item.get('schema') != 2 or item.get('record_evidence_schema') != 2 or item['authorization'] != 'inventory_only':
            raise PlanError('unsupported inventory contract')
        table = record_table(item)
        for declaration in item['declarations']:
            tables[id(declaration)] = table
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
        try:
            for declaration in records:
                validate_type(declaration['signature'], tables[id(declaration)])
            matches = [compare_evidence(signature, function_signature(d), tables[id(definition)], tables[id(d)]) for d in records]
            if not all(matches):
                reject('signature_mismatch', key, definition['location'])
        except RecordUnproved as error:
            reject('record_compatibility_unproved', key, definition['location'], str(error))
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
    return {'schema': 2, 'record_evidence_schema': 2, 'target': target, 'target_c_widths_bits': widths, 'authorization': 'inventory_only',
            'units': sorted(units), 'symbols': list(candidates.values()),
            'record_definitions': {item['unit']: item['record_definitions'] for item in inventories},
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
