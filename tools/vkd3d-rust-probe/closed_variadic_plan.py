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


class SignatureUnproved(PlanError):
    pass


def function_signature(declaration):
    signature = declaration.get('signature')
    if isinstance(signature, dict) and set(signature) == {'unproved'}:
        if not isinstance(signature['unproved'], str) or not signature['unproved']:
            raise PlanError('invalid unproved function signature reason')
        raise SignatureUnproved(signature['unproved'])
    if not isinstance(signature, dict) or set(signature) != {'canonical', 'const', 'volatile', 'restrict'} or any(
            type(signature[k]) is not bool for k in ('const', 'volatile', 'restrict')):
        raise PlanError('invalid function signature envelope')
    canonical = signature['canonical']
    if not isinstance(canonical, dict) or set(canonical) != {'return', 'parameters', 'variadic', 'noreturn', 'prototype', 'abi'} or not (
            isinstance(canonical['return'], dict) and isinstance(canonical['parameters'], list)
            and all(isinstance(p, dict) for p in canonical['parameters']) and isinstance(canonical['abi'], str)) or any(
            type(canonical[k]) is not bool for k in ('variadic', 'noreturn', 'prototype')):
        raise PlanError('invalid canonical function signature facts')
    return compatible_type(canonical)


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
           'Int128', 'UInt128', 'Half'}


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
    if keys == {'kind'} and isinstance(canonical['kind'], str) and canonical['kind'] in SCALARS - {'Char'}:
        return
    if keys == {'kind', 'signed'} and canonical['kind'] == 'Char' and type(canonical['signed']) is bool:
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
    signatures = {}
    unproved_signatures = {}
    declaration_units = {}
    for item in inventories:
        if item.get('schema') != 2 or item.get('record_evidence_schema') != 2 or item['authorization'] != 'inventory_only':
            raise PlanError('unsupported inventory contract')
        table = record_table(item)
        for declaration in item['declarations']:
            tables[id(declaration)] = table
            declaration_units[id(declaration)] = item['unit']
            try:
                signatures[id(declaration)] = function_signature(declaration)
            except SignatureUnproved as error:
                unproved_signatures[id(declaration)] = str(error)
            key = symbol_key(declaration['symbol'])
            declarations.setdefault(key, []).append(declaration)
    candidates = {}
    diagnostics = []
    unclassified_definitions = []
    unclassified_keys = set()

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
        for definition in definitions:
            if id(definition) in unproved_signatures:
                reason = unproved_signatures[id(definition)]
                unclassified_keys.add(key)
                unclassified_definitions.append({
                    'symbol': list(key), 'unit': declaration_units[id(definition)],
                    'id': definition['id'], 'name': key[-1], 'location': definition['location'],
                    'signature': definition['signature'], 'reason': reason})
                reject('candidate_signature_unproved', key, definition['location'], reason)
        known_definitions = [d for d in definitions if id(d) in signatures]
        if not any(signatures[id(d)]['variadic'] or d['va_parameters'] for d in known_definitions):
            continue
        definition = known_definitions[0]
        signature = signatures[id(definition)]
        candidates[key] = {'symbol': list(key), 'definition': definition['location'],
                           'signature': signature, 'calls': []}
        if len(definitions) != 1:
            reject('multiple_definitions', key, definition['location'])
        try:
            for declaration in records:
                if id(declaration) in unproved_signatures:
                    raise SignatureUnproved(unproved_signatures[id(declaration)])
                validate_type(declaration['signature'], tables[id(declaration)])
            matches = [compare_evidence(signature, signatures[id(d)], tables[id(definition)], tables[id(d)]) for d in records]
            if not all(matches):
                reject('signature_mismatch', key, definition['location'])
        except SignatureUnproved as error:
            reject('candidate_signature_unproved', key, definition['location'], str(error))
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
            unknown_targets = alias_reachable.get(key, {key}) & unclassified_keys
            for unknown in sorted(unknown_targets):
                reject('call_signature_unproved', unknown, call['location'])
            for key in visible_candidates(key):
                if key in unknown_targets:
                    continue
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
    plan = {'schema': 2, 'record_evidence_schema': 2, 'target': target, 'target_c_widths_bits': widths, 'authorization': 'inventory_only',
            'units': sorted(units), 'symbols': list(candidates.values()),
            'record_definitions': {item['unit']: item['record_definitions'] for item in inventories},
            'diagnostics': diagnostics,
            'remaining_gates': ['four_host_target_C_width_execution', 'cursor_alias_and_control_flow',
                                'generator_lowering', 'four_host_generated_code_ABI']}
    if unclassified_definitions:
        plan['unclassified_definitions'] = unclassified_definitions
    return plan


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



def _cursor_need(condition, message):
    if not condition:
        raise PlanError('cursor witness: ' + message)


def _cursor_same(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(_cursor_same(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_cursor_same(a, b) for a, b in zip(left, right))
    return left == right


def _cursor_index(rows, key='id'):
    result = {}
    for row in rows:
        ident = row[key]
        _cursor_need(type(ident) is int and ident > 0 and ident not in result,
                     'duplicate or invalid mapped ID')
        result[ident] = row
    return result


def _cursor_type(canonical, const=False):
    return {'canonical': canonical, 'const': const, 'volatile': False, 'restrict': False}


def _cursor_pointer(typ):
    return _cursor_type({'pointer': typ})


def _cursor_signature(result, parameters, variadic=False):
    return _cursor_type({'return': result, 'parameters': parameters, 'variadic': variadic,
                         'noreturn': False, 'prototype': True, 'abi': 'C'})


class _CursorBody:
    def __init__(self, inventory, witness, function):
        self.inv, self.w, self.f = inventory, witness, function
        self.e = _cursor_index(witness['expressions'])
        self.d = _cursor_index(witness['declarations'])
        self.calls = _cursor_index(witness['calls'])
        self.idecls = _cursor_index(inventory['declarations'])
        self.icalls = _cursor_index(inventory['calls'])
        _cursor_need(set(self.calls) == {k for k, v in self.e.items() if v['kind'] == 'call'}
                     and all(_cursor_same(self.e[k], v) for k, v in self.calls.items()), 'global call copies differ')
        _cursor_need(set(self.calls) == set(self.icalls), 'paired call set differs')
        self.records = record_table(inventory)
        r = witness['required_relations']
        _cursor_need(set(r) == {'schema', 'authorization', 'types', 'roots', 'cursors',
                               'native_records', 'enum_owners', 'builtin_declarations', 'builtin_endpoints'}
                     and type(r['schema']) is int and r['schema'] == 1
                     and r['authorization'] == 'witness_only', 'required relations schema')
        self.r = r
        self.types = _cursor_index(r['types'], 'type_id')
        self.roots = _cursor_index(r['roots'], 'type_id')
        self.native = _cursor_index(r['native_records'], 'declaration')
        self.enums = _cursor_index(r['enum_owners'], 'declaration')
        self.builtins = _cursor_index(r['builtin_declarations'], 'declaration')
        self.endpoints = _cursor_index(r['builtin_endpoints'], 'expression')
        self.decl_roles = {}
        for ident in self.idecls:
            self.declaration_role(ident, 'function')
        for ident, dec in self.d.items():
            self.declaration_role(ident, dec['kind'])
        for row in self.types.values():
            if row['kind'] in ('struct', 'enum', 'typedef'):
                self.declaration_role(row['declaration'], row['kind'])
        self.record_ids, self.record_identities = {}, {}
        self.type_meanings = {}
        self.supplied_type_meanings, self.conflicting_type_ids = {}, set()
        for expression in self.e.values():
            ident, typ = expression.get('type_id'), expression.get('type')
            if type(ident) is int and ident > 0 and isinstance(typ, dict) and 'canonical' in typ:
                canonical = typ['canonical']
                if not _cursor_same(self.supplied_type_meanings.get(ident, canonical), canonical):
                    self.conflicting_type_ids.add(ident)
                self.supplied_type_meanings[ident] = canonical
        self.seen, self.body_ids = set(), set()
        self.helpers = {}
        self.uint = _cursor_type({'kind': 'UInt'})
        self.int = _cursor_type({'kind': 'Int'})
        self.ulong = _cursor_type({'kind': 'ULong'})
        self.void = _cursor_type({'kind': 'Void'})
        self.char = _cursor_type({'kind': 'Char', 'signed': True})
        self.cchar = _cursor_type({'kind': 'Char', 'signed': True}, True)
        self.charptr, self.fmt_type = _cursor_pointer(self.char), _cursor_pointer(self.cchar)

    def declaration_role(self, ident, role):
        _cursor_need(type(ident) is int and ident > 0 and self.decl_roles.get(ident, role) == role,
                     'mapped declaration namespace collision')
        self.decl_roles[ident] = role

    def qualified(self, q):
        _cursor_need(set(q) == {'type_id', 'const', 'restrict', 'volatile'}
                     and type(q['type_id']) is int and q['type_id'] > 0
                     and all(type(q[k]) is bool for k in ('const', 'restrict', 'volatile')),
                     'invalid qualified mapped type')

    def type_meaning(self, q, typ):
        self.qualified(q)
        canonical = typ['canonical']
        _cursor_need(q['type_id'] not in self.conflicting_type_ids
                     and _cursor_same(self.supplied_type_meanings.get(q['type_id'], canonical), canonical),
                     'supplied mapped type canonical meaning collision')
        _cursor_need(_cursor_same(self.type_meanings.get(q['type_id'], canonical), canonical),
                     'mapped type canonical meaning collision')
        self.type_meanings[q['type_id']] = canonical

    def type_join(self, q, typ, active=()):
        self.type_meaning(q, typ)
        ident = q['type_id']
        _cursor_need(ident not in active and len(active) < 64, 'cyclic or excessive type chain')
        row = self.types[ident]
        k = row['kind']
        qualifiers = {k: q[k] for k in ('const', 'restrict', 'volatile')}
        _cursor_need(isinstance(typ, dict) and set(typ) == {'canonical', *qualifiers}, 'type envelope')
        active = (*active, ident)
        if k in ('elaborated', 'paren', 'attributed', 'decayed'):
            _cursor_need(set(row) == {'type_id', 'kind', 'inner'}, 'wrapper relation')
            return self.type_join(dict(q, type_id=row['inner']), typ, active)
        if k == 'typedef':
            _cursor_need(set(row) == {'type_id', 'kind', 'declaration', 'original'}
                         and type(row['declaration']) is int and row['declaration'] > 0, 'typedef relation')
            inner = dict(row['original'])
            self.qualified(inner)
            inner.update({k: q[k] or inner[k] for k in qualifiers})
            return self.type_join(inner, typ, active)
        _cursor_need(all(typ[k] is v for k, v in qualifiers.items()), 'type qualifiers differ')
        c = typ['canonical']
        if k == 'pointer':
            _cursor_need(set(row) == {'type_id', 'kind', 'pointee'} and set(c) == {'pointer'}, 'pointer relation')
            self.type_join(row['pointee'], c['pointer'], active)
        elif k == 'array':
            _cursor_need(set(row) == {'type_id', 'kind', 'length', 'element'}
                         and set(c) == {'array', 'length'} and type(row['length']) is int
                         and row['length'] >= 0 and _cursor_same(c['length'], row['length']), 'array relation')
            self.type_join(row['element'], c['array'], active)
        elif k == 'function':
            _cursor_need(set(row) == {'type_id', 'kind', 'return', 'parameters', 'variadic',
                                     'noreturn', 'prototype', 'abi'}
                         and set(c) == {'return', 'parameters', 'variadic', 'noreturn', 'prototype', 'abi'}
                         and row['abi'] == c['abi'] == 'C'
                         and all(type(row[x]) is bool and row[x] is c[x]
                                 for x in ('variadic', 'noreturn', 'prototype'))
                         and len(row['parameters']) == len(c['parameters']), 'function relation')
            self.type_join(row['return'], c['return'], active)
            for a, b in zip(row['parameters'], c['parameters']):
                self.type_join(a, b, active)
        elif k in ('struct', 'enum'):
            _cursor_need(set(row) == {'type_id', 'kind', 'declaration'}, 'record relation')
            dec = row['declaration']
            _cursor_need(type(dec) is int and dec > 0, 'record declaration ID')
            if dec in self.native:
                _cursor_need(k == 'struct' and _cursor_same(c, {'native_va_list_record': dec}), 'native terminal')
                native = self.native[dec]
                _cursor_need(_cursor_same(native, {'declaration': dec, 'origin': 'ASTContext.getVaListTagDecl',
                                        'kind': 'struct', 'complete': True, 'size': 24, 'alignment': 8})
                             and any(_cursor_same(dec, value) for value in self.w['native_va_list_records']), 'native origin or layout')
            else:
                _cursor_need(set(c) == {'record'} and c['record']['kind'] == k, 'physical record terminal')
                identity = record_key(c['record'])
                _cursor_need(self.record_ids.get(dec, identity) == identity
                             and self.record_identities.get(identity, dec) == dec, 'record mapped identity collision')
                self.record_ids[dec], self.record_identities[identity] = identity, dec
                validate_type(typ, self.records)
                if k == 'enum':
                    _cursor_need(_cursor_same(self.enums[dec]['identity'], c['record']), 'enum relation owner')
        else:
            expected = {'type_id': ident, **c}
            _cursor_need(k in SCALARS and _cursor_same(row, expected), 'unproved or mismatched required type')

    def expression_type(self, expression, typ, caller=False):
        _cursor_need(_cursor_same(expression['type'], typ), 'expression type differs')
        q = {k: typ[k] for k in ('const', 'restrict', 'volatile')}
        q['type_id'] = expression['type_id']
        self.type_meaning(q, typ)
        if caller and q['type_id'] not in self.types:
            _cursor_need(expression['kind'] == 'literal' and _cursor_same(expression['literal'], {'bytes': [99, 98, 37, 117], 'width': 1})
                         or expression['kind'] == 'implicit_cast' and expression['cast'] == 'FunctionToPointerDecay',
                         'missing caller declaration type relation')
            validate_type(typ, self.records)
        else:
            self.type_join(q, typ)
            root = self.roots[q['type_id']]
            _cursor_need(_cursor_same(root, q), 'missing or unproved required root')

    def variable(self, dec, name, typ, local, initializer, owner):
        _cursor_need(set(dec) == {'id', 'kind', 'name', 'type', 'type_id', 'local', 'static', 'thread',
                                 'externally_visible', 'initializer', 'native_va_list', 'owning_function'}
                     and dec['kind'] == 'variable' and dec['name'] == name and _cursor_same(dec['type'], typ)
                     and dec['local'] is local and dec['static'] is False and dec['thread'] is False
                     and dec['externally_visible'] is False and _cursor_same(dec['initializer'], initializer)
                     and _cursor_same(dec['owning_function'], owner), 'variable declaration differs')
        q = {k: typ[k] for k in ('const', 'restrict', 'volatile')}
        self.type_join(dict(q, type_id=dec['type_id']), typ)

    def refs(self, ident):
        x = self.e[ident]
        return ([{'id': ident, 'decl': x['decl']}] if x['kind'] == 'reference' else
                [v for child in x['children'] for v in self.refs(child)])

    def ordinary(self, typ):
        if isinstance(typ, list):
            return [self.ordinary(v) for v in typ]
        if not isinstance(typ, dict):
            return typ
        if set(typ) == {'native_va_list_record'}:
            _cursor_need(type(typ['native_va_list_record']) is int and typ['native_va_list_record'] in self.native, 'unknown native record')
            return {'record': {'unproved': 'physical record location or macro declaration'}}
        return {k: self.ordinary(v) for k, v in typ.items()}

    def promotion_chain(self, ident):
        x = self.e[ident]
        chain = [self.ordinary(x['type'])]
        while x['kind'] in ('implicit_cast', 'paren'):
            x = self.e[x['children'][0]]
            chain.append(self.ordinary(x['type']))
        return chain

    def argument(self, ident):
        x = self.e[ident]
        while x['kind'] in ('implicit_cast', 'paren'):
            x = self.e[x['children'][0]]
        return {'id': ident, 'type': self.e[ident]['type'], 'references': self.refs(ident),
                'direct_decl': x['decl'] if x['kind'] == 'reference' else None,
                'literal': x['literal'].get('bytes') if x['kind'] == 'literal' else None}

    def node(self, kind, typ, children=(), **facts):
        return kind, typ, list(children), facts

    def ref(self, dec, typ):
        return self.node('reference', typ, decl=dec)

    def cast(self, kind, typ, child):
        return self.node('implicit_cast', typ, [child], cast=kind, field=None)

    def value(self, dec, typ):
        return self.cast('LValueToRValue', typ, self.ref(dec, typ))

    def binary(self, op, typ, left, right):
        return self.node('binary', typ, [left, right], operator=op, computation_types=[None, None])

    def paren(self, typ, child):
        return self.node('paren', typ, [child])

    def literal(self, value, character=False):
        return self.node('literal', self.int, literal={'character' if character else 'integer': value})

    def match(self, ident, recipe, caller=False):
        _cursor_need(type(ident) is int and ident > 0 and ident not in self.seen,
                     'expression ID malformed, reused or cyclic')
        self.seen.add(ident)
        x = self.e[ident]
        kind, typ, children, facts = recipe
        _cursor_need(x['kind'] == kind and len(x['children']) == len(children), 'ordered expression shape')
        expected_keys = {'id', 'kind', 'type', 'type_id', 'children', *facts}
        if kind == 'call':
            expected_keys.add('arguments')
        _cursor_need(set(x) == expected_keys and all(_cursor_same(x[k], v) for k, v in facts.items()),
                     'expression operator, literal or identity differs')
        if kind == 'reference' and facts['decl'] in self.d and self.d[facts['decl']]['kind'] == 'variable':
            _cursor_need(_cursor_same(x['type_id'], self.d[facts['decl']]['type_id']), 'reference source type ID differs')
        if typ == 'builtin_endpoint':
            _cursor_need(_cursor_same(x['type'], _cursor_type({'unproved': 'unsupported type or wrapper limit'})),
                         'BuiltinFn reference envelope')
        else:
            self.expression_type(x, typ, caller)
        for child, expected in zip(x['children'], children):
            self.match(child, expected, caller)
        if kind == 'call':
            _cursor_need(_cursor_same(x['arguments'], [self.argument(a) for a in x['children'][1:]]), 'argument summaries differ')
            inv = self.icalls[ident]
            _cursor_need(len(inv['arguments']) == len(x['arguments'])
                         and all(_cursor_same(a['id'], b['id']) and _cursor_same(a['type'], self.ordinary(b['type']))
                                 for a, b in zip(inv['arguments'], x['arguments'])), 'paired call arguments differ')
            _cursor_need(inv['callee'] == self.idecls[x['callee_decl']]['symbol'], 'paired call callee differs')
            if not caller:
                _cursor_need(_cursor_same(inv['owner'], self.f['declaration']), 'body call owner differs')
            for a in inv['arguments']:
                expected_cursor = self.e[a['id']]['type']['canonical'].get('pointer', {}).get('canonical', {}).get('native_va_list_record')
                _cursor_need(a['va_list'] is bool(expected_cursor)
                             and _cursor_same(a['promotion_chain'], self.promotion_chain(a['id'])), 'argument promotion/cursor classification')
            if x['builtin'][1] in ('va_start', 'va_end'):
                end = self.endpoints[x['children'][0]]
                cast = self.e[end['expression']]
                ref = self.e[end['reference']]
                _cursor_need(set(end) == {'expression', 'reference', 'declaration', 'cast', 'input', 'output'}
                             and end['cast'] == cast['cast'] == 'BuiltinFnToFnPtr'
                             and _cursor_same(end['reference'], cast['children'][0])
                             and _cursor_same(end['declaration'], ref['decl']) and _cursor_same(ref['decl'], x['callee_decl']), 'builtin endpoint IDs')
                for field, expr in [('input', ref), ('output', cast)]:
                    q = end[field]
                    self.qualified(q)
                    _cursor_need(_cursor_same(q, dict(type_id=expr['type_id'], **{k: expr['type'][k]
                                 for k in ('const', 'restrict', 'volatile')})), 'builtin endpoint qualified type')
                row = self.types[end['input']['type_id']]
                _cursor_need(_cursor_same(row, {'type_id': row['type_id'], 'kind': 'builtin_function',
                                    'unproved': 'BuiltinFn requires a native endpoint relation'}), 'builtin endpoint input kind')
                _cursor_need(_cursor_same(self.roots[row['type_id']], dict(end['input'],
                             unproved='required type dependency, cycle or depth limit')), 'BuiltinFn root boundary')

    def helper(self, name, signature, builtin=None):
        if name in self.helpers:
            return self.helpers[name]
        candidates = [d for d in self.idecls.values() if d['symbol'].get('linker', d['symbol'].get('static')) == name]
        _cursor_need(len(candidates) == 1, 'helper identity is not unique')
        d = candidates[0]
        _cursor_need(d['aliases'] == [] and (set(d['symbol']) == {'linker'}
                     or d['symbol'] == {'unit': self.w['unit'], 'static': name}), 'helper alias or TU identity')
        if builtin:
            b = self.builtins[d['id']]
            _cursor_need(set(b) == {'declaration', 'name', 'symbol', 'type', 'signature', 'builtin_id', 'semantic'}
                         and b['symbol'] == d['symbol'] == {'linker': name}
                         and b['name'] == name and _cursor_same([b['builtin_id'], b['semantic']], builtin)
                         and _cursor_same(b['signature'], signature) and d['definition'] is False, 'native builtin identity/signature')
            self.type_join(b['type'], signature)
            _cursor_need(_cursor_same(d['signature'], self.ordinary(signature)), 'native builtin inventory signature')
        else:
            _cursor_need(_cursor_same(d['signature'], signature), 'helper signature')
            validate_type(signature, self.records)
        self.helpers[name] = d['id']
        return d['id']

    def call(self, name, signature, args, builtin=None):
        dec = self.helper(name, signature, builtin)
        callee = self.ref(dec, 'builtin_endpoint' if builtin and builtin[1] in ('va_start', 'va_end') else signature)
        callee = self.cast('BuiltinFnToFnPtr' if builtin and builtin[1] in ('va_start', 'va_end')
                           else 'FunctionToPointerDecay', _cursor_pointer(signature), callee)
        return self.node('call', signature['canonical']['return'], [callee, *args],
                         callee_decl=dec, builtin=builtin or [0, 'unknown'])

    def prove(self):
        f = self.f
        _cursor_need(set(f) == {'body', 'complete_body', 'cursors', 'declaration', 'full_statement_ids',
                               'last_fixed_parameter', 'parameter_declarations', 'parameters',
                               'parameter_and_cursor_references', 'signature', 'statements', 'symbol'}, 'function witness schema')
        _cursor_need(f['complete_body'] is True and len(f['statements']) == 13
                     and [s['kind'] for s in f['statements']] == ['declarations'] * 4 + ['expression'] * 9,
                     'exact 13 statement roles')
        statements = _cursor_index(f['statements'])
        _cursor_need(type(f['body']) is int and f['body'] > 0
                     and all(type(k) is int and k > 0 for k in f['full_statement_ids'])
                     and len(f['full_statement_ids']) == 14 and len(set(f['full_statement_ids'])) == 14
                     and set(f['full_statement_ids']) == {f['body'], *statements}, 'full statement closure')
        _cursor_need(len(f['parameters']) == len(set(f['parameters'])) == 4
                     and all(type(k) is int and k > 0 for k in f['parameters'])
                     and _cursor_same(f['last_fixed_parameter'], f['parameters'][-1]), 'four fixed parameters')
        builder, type_id, member, fmt = f['parameters']
        params = [self.d[k] for k in f['parameters']]
        _cursor_need(_cursor_same(f['parameter_declarations'], params), 'parameter copies differ')
        builder_type = params[0]['type']
        builder_record = builder_type['canonical']['pointer']['canonical']['record']
        _cursor_need(builder_record['tag'] == 'vkd3d_spirv_builder' and builder_record['kind'] == 'struct'
                     and _cursor_same(builder_record['scope'], {'file': True}), 'builder record')
        _cursor_need(_cursor_same(builder_type, _cursor_pointer(_cursor_type({'record': builder_record}))),
                     'builder pointer qualifiers')
        signature = _cursor_signature(self.void, [builder_type, self.uint, self.uint, self.fmt_type], True)
        _cursor_need(_cursor_same(f['signature'], signature) and _cursor_same(self.idecls[f['declaration']]['signature'], signature),
                     'target signature')
        validate_type(signature, self.records)
        for dec, name, typ in zip(params, ['builder', 'type_id', 'member', 'fmt'], signature['canonical']['parameters']):
            self.variable(dec, name, typ, False, None, None)
            _cursor_need(dec['native_va_list'] is None, 'unexpected parameter cursor')
        locals_ = []
        for s in f['statements'][:4]:
            _cursor_need(s['root'] is None and len(s['declarations']) == 1, 'single local declaration')
            dec = s['declarations'][0]
            _cursor_need(_cursor_same(self.d[dec['id']], dec), 'local declaration copy differs')
            locals_.append(dec)
        stream, size, name, args = [d['id'] for d in locals_]
        _cursor_need(len({*f['parameters'], stream, size, name, args}) == 8 and _cursor_same(f['cursors'], [args]), 'local/parameter ID collision')
        stream_type = locals_[0]['type']
        stream_record = stream_type['canonical']['pointer']['canonical']['record']
        _cursor_need(stream_record['tag'] == 'vkd3d_spirv_stream' and stream_record['kind'] == 'struct'
                     and _cursor_same(stream_record['scope'], {'file': True}), 'stream record')
        _cursor_need(_cursor_same(stream_type, _cursor_pointer(_cursor_type({'record': stream_record}))),
                     'stream pointer qualifiers')
        name_type = _cursor_type({'array': self.char, 'length': 1024})
        native_relation = _cursor_index(self.r['cursors'], 'declaration')[args]
        _cursor_need(set(native_relation) == {'declaration', 'source', 'declared', 'builtin', 'target_kind', 'same_canonical_type'}
                     and type(native_relation['target_kind']) is int and type(self.w['native_va_list_kind']) is int
                     and native_relation['target_kind'] == self.w['native_va_list_kind'] == 5
                     and native_relation['same_canonical_type'] is True, 'native cursor relation')
        args_type = locals_[3]['type']
        native_record = args_type['canonical']['array']['canonical']['native_va_list_record']
        native_type = _cursor_type({'native_va_list_record': native_record})
        _cursor_need(_cursor_same(args_type, _cursor_type({'array': native_type, 'length': 1})), 'native cursor array')
        native_ptr = _cursor_pointer(native_type)
        self.type_join(native_relation['source'], args_type)
        native = locals_[3]['native_va_list']
        expected_native = {'same_canonical_type': True, 'target_kind': 5}
        for prefix in ('declared', 'builtin'):
            q = native_relation[prefix]
            self.type_join(q, args_type)
            expected_native.update({prefix + '_type_id': q['type_id'], prefix + '_canonical_type': args_type,
                                    **{prefix + '_' + k: q[k] for k in ('const', 'restrict', 'volatile')}})
        _cursor_need(_cursor_same(native, expected_native) and _cursor_same(native_relation['source'], dict(type_id=locals_[3]['type_id'],
                     **{k: args_type[k] for k in ('const', 'restrict', 'volatile')})), 'native canonical/source joins')
        for dec, label, typ in zip(locals_, ['stream', 'name_size', 'name', 'args'],
                                   [stream_type, self.uint, name_type, args_type]):
            self.variable(dec, label, typ, True, dec['initializer'] if label == 'stream' else None, f['declaration'])
            if label != 'args':
                _cursor_need(dec['native_va_list'] is None, 'unexpected local cursor')
        init = self.e[locals_[0]['initializer']]
        field = self.e[init['children'][0]]['member']
        _cursor_need(set(field) == {'id', 'kind', 'name', 'type_id', 'type', 'owners'}
                     and field['kind'] == 'field' and field['name'] == 'debug_stream'
                     and _cursor_same(field['owners'], [builder_record]) and _cursor_same(field['type'], _cursor_type({'record': stream_record})),
                     'debug_stream member owner or type')
        self.declaration_role(field['id'], 'field')
        field_type = field['type']
        self.type_join(dict(type_id=field['type_id'], **{k: field_type[k] for k in ('const', 'restrict', 'volatile')}), field_type)
        fields = self.records[record_key(builder_record)]['facts']['fields']
        _cursor_need(sum(x['name'] == 'debug_stream' and _cursor_same(x['type'], field_type) for x in fields) == 1,
                     'debug_stream physical field')
        initializer = self.node('unary', stream_type,
            [self.node('member', field_type, [self.value(builder, builder_type)], access='Arrow', member=field)], operator='AddressOf')
        name_ref = self.ref(name, name_type)
        name_ptr = self.cast('ArrayToPointerDecay', self.charptr, name_ref)
        name_const = self.cast('NoOp', self.fmt_type, name_ptr)
        args_ptr = self.cast('ArrayToPointerDecay', native_ptr, self.ref(args, args_type))
        def array_size():
            numerator = self.node('unary_type', self.ulong, [self.paren(name_type, name_ref)],
                                  operator='SizeOf', argument_type=name_type)
            deref = self.node('unary', self.char,
                             [self.cast('ArrayToPointerDecay', self.charptr, self.paren(name_type, name_ref))], operator='Deref')
            denominator = self.node('unary_type', self.ulong, [self.paren(self.char, deref)],
                                    operator='SizeOf', argument_type=self.char)
            return self.paren(self.ulong, self.binary('Divide', self.ulong, numerator, denominator))
        enum_candidates = [d for d in self.d.values() if d['kind'] == 'enum_constant' and d['name'] == 'SpvOpMemberName']
        _cursor_need(len(enum_candidates) == 1, 'selected enum constant not unique')
        enum = enum_candidates[0]
        owner = self.enums[enum['owning_enum']['declaration']]
        _cursor_need(_cursor_same(enum['owning_enum'], {'declaration': owner['declaration'], 'identity': owner['identity']})
                     and type(enum['value']) is int and enum['value'] == 6
                     and _cursor_same(_cursor_index(owner['variants'], 'declaration')[enum['id']],
                         {'declaration': enum['id'], 'name': 'SpvOpMemberName', 'signed': True, 'value': 6}), 'selected enum membership')
        _cursor_need(owner['identity']['tag'] in ('SpvOp', 'SpvOp_')
                     and _cursor_same(owner['identity']['scope'], {'file': True}), 'opcode enum identity')
        enum_type = _cursor_type({'record': owner['identity']})
        validate_type(enum_type, self.records)
        _cursor_need(any(_cursor_same(variant, {'name': 'SpvOpMemberName', 'signed': True, 'value': 6})
                         for variant in self.records[record_key(owner['identity'])]['facts']['variants']), 'physical enum membership')
        word_sig = _cursor_signature(self.void, [stream_type, self.uint])
        opcode_sig = _cursor_signature(self.uint, [enum_type, self.uint])
        opcode = self.call('vkd3d_spirv_opcode_word', opcode_sig,
            [self.cast('IntegralCast', enum_type, self.ref(enum['id'], self.int)),
             self.binary('Add', self.uint, self.cast('IntegralCast', self.uint, self.literal(3)), self.value(size, self.uint))])
        recipes = [initializer,
            self.call('__builtin_va_start', _cursor_signature(self.void, [native_ptr], True),
                      [args_ptr, self.ref(fmt, self.fmt_type)], [415, 'va_start']),
            self.call('vsnprintf', _cursor_signature(self.int, [self.charptr, self.ulong, self.fmt_type, native_ptr]),
                      [name_ptr, array_size(), self.value(fmt, self.fmt_type), args_ptr], [907, 'vsnprintf']),
            self.binary('Assign', self.char,
                self.node('subscript', self.char, [name_ptr, self.binary('Subtract', self.ulong, array_size(),
                          self.cast('IntegralCast', self.ulong, self.literal(1)))]),
                self.cast('IntegralCast', self.char, self.literal(0, True))),
            self.call('__builtin_va_end', _cursor_signature(self.void, [native_ptr]), [args_ptr], [416, 'va_end']),
            self.binary('Assign', self.uint, self.ref(size, self.uint),
                self.call('vkd3d_spirv_string_word_count', _cursor_signature(self.uint, [self.fmt_type]), [name_const])),
            self.call('vkd3d_spirv_build_word', word_sig, [self.value(stream, stream_type), opcode]),
            self.call('vkd3d_spirv_build_word', word_sig, [self.value(stream, stream_type), self.value(type_id, self.uint)]),
            self.call('vkd3d_spirv_build_word', word_sig, [self.value(stream, stream_type), self.value(member, self.uint)]),
            self.call('vkd3d_spirv_build_string', _cursor_signature(self.void, [stream_type, self.fmt_type, self.uint]),
                      [self.value(stream, stream_type), name_const, self.value(size, self.uint)])]
        roots = [locals_[0]['initializer']] + [s['root'] for s in f['statements'][4:]]
        for s in f['statements']:
            _cursor_need(set(s) == {'id', 'kind', 'root', 'declarations', 'expressions'}, 'statement schema')
            embedded = _cursor_index(s['expressions'])
            _cursor_need(all(_cursor_same(self.e[k], v) for k, v in embedded.items()), 'embedded expression copy differs')
            _cursor_need(not self.body_ids.intersection(embedded), 'expression belongs to multiple statements')
            self.body_ids.update(embedded)
            if s['kind'] == 'expression':
                _cursor_need(s['declarations'] == [], 'hidden expression declaration')
        role_statements = [f['statements'][0], *f['statements'][4:]]
        for root, recipe, statement in zip(roots, recipes, role_statements):
            before = set(self.seen)
            self.match(root, recipe)
            _cursor_need(self.seen - before == {e['id'] for e in statement['expressions']},
                         'statement expression allocation differs')
        _cursor_need(all(s['expressions'] == [] for s in f['statements'][1:4]), 'hidden declaration expressions')
        _cursor_need(self.seen == self.body_ids and len(self.body_ids) == 102
                     and len(self.body_ids.intersection(self.calls)) == 9, 'complete body expression/call closure')
        local_ids = {stream, size, name, args, *f['parameters']}
        actual_refs = sorted([{'id': x['id'], 'decl': x['decl'], 'type': x['type']}
                              for x in self.e.values() if x['kind'] == 'reference'
                              and x['decl'] in set(f['parameters']) | {args}], key=lambda x: x['id'])
        _cursor_need(_cursor_same(sorted(f['parameter_and_cursor_references'], key=lambda x: x['id']), actual_refs),
                     'independent parameter/cursor reference set')
        _cursor_need(all(x['id'] in self.body_ids for x in self.e.values()
                         if x['kind'] == 'reference' and x['decl'] in local_ids), 'local or parameter reference escape')
        _cursor_need(all(x['owner'] != f['declaration'] for x in self.inv['va_arg']), 'unexpected va_arg')
        for other in self.w['functions']:
            for statement in other['statements']:
                for expression in statement['expressions']:
                    if expression['id'] in self.body_ids:
                        _cursor_need(_cursor_same(expression, self.e[expression['id']]), 'conflicting embedded graph copy')
        return signature


def prove_cursor_witness(inventories, witnesses, symbol):
    """Prove only the captured member-name body; never authorize stable lowering."""
    if not inventories or len(inventories) != len(witnesses):
        raise PlanError('cursor witness: incomplete paired units')
    if any(not isinstance(w, dict) or type(w.get('schema')) is not int or w['schema'] != 2 for w in witnesses):
        raise PlanError('cursor witness: schema 1 capture cannot establish a proof')
    try:
        _cursor_need(isinstance(symbol, dict) and set(symbol) == {'unit', 'static'}
                     and symbol['static'] == 'vkd3d_spirv_build_op_member_name', 'unsupported exact symbol')
        units = set()
        selected = []
        for inv, w in zip(inventories, witnesses):
            _cursor_need('required_relations' in w, 'missing required relations; witness v2 unsupported')
            _cursor_need(type(inv['schema']) is int and inv['schema'] == 2
                         and type(inv['record_evidence_schema']) is int and inv['record_evidence_schema'] == 2
                         and inv['authorization'] == 'inventory_only' and w['authorization'] == 'witness_only'
                         and inv['unit'] == w['unit'] and inv['target'] == w['target']
                         and w['target'] == 'x86_64-pc-linux-gnu' and w['unit'] not in units, 'paired TU/target contract')
            units.add(w['unit'])
            for d in inv['declarations']:
                _cursor_need(not (symbol['static'] in d['aliases']), 'target alias')
                if d['symbol'] == symbol:
                    _cursor_need(inv['unit'] == symbol['unit'] and d['definition'] is True
                                 and d['aliases'] == [] and d['va_parameters'] == [], 'unique static target definition')
                    selected.append((inv, w, d))
            _cursor_need(all(x['symbol'] != symbol for x in inv['non_call_references']), 'target non-call reference')
        _cursor_need(len(selected) == 1, 'unique target declaration')
        inv, w, d = selected[0]
        functions = [f for f in w['functions'] if f['declaration'] == d['id'] or f['symbol'] == symbol]
        _cursor_need(len(functions) == 1 and functions[0]['symbol'] == symbol
                     and _cursor_same(functions[0]['declaration'], d['id']), 'unique target witness')
        body = _CursorBody(inv, w, functions[0])
        signature = body.prove()
        incoming = [(i, c) for i in inventories for c in i['calls'] if c['callee'] == symbol]
        _cursor_need(len(incoming) == 1 and incoming[0][0]['unit'] == inv['unit'], 'sole incoming call')
        call = incoming[0][1]
        _cursor_need(type(call['owner']) is int and call['owner'] > 0, 'incoming caller owner ID')
        owner = body.idecls[call['owner']]
        _cursor_need(owner['definition'] is True and owner['id'] != d['id'], 'incoming caller owner')
        raw = body.calls[call['id']]
        _cursor_need(len(raw['arguments']) == 5, 'five incoming arguments')
        refs = [a['direct_decl'] for a in raw['arguments']]
        args = []
        for index, typ in enumerate(signature['canonical']['parameters'][:3]):
            dec = body.d[refs[index]]
            _cursor_need(dec['kind'] == 'variable' and _cursor_same(dec['type'], typ)
                         and dec['static'] is False and dec['thread'] is False
                         and (dec['local'] is False or dec['local'] is True
                              and _cursor_same(dec['owning_function'], owner['id'])), 'incoming declaration reference')
            args.append(body.value(dec['id'], typ))
        string_type = _cursor_type({'array': body.cchar, 'length': 5}, True)
        args.append(body.cast('ArrayToPointerDecay', body.fmt_type,
                             body.node('literal', string_type, literal={'bytes': [99, 98, 37, 117], 'width': 1})))
        tail = body.d[refs[4]]
        _cursor_need(tail['kind'] == 'variable' and tail['name'] == 'reg_idx' and _cursor_same(tail['type'], body.uint)
                     and tail['local'] is True and _cursor_same(tail['owning_function'], owner['id'])
                     and tail['static'] is False and tail['thread'] is False and tail['externally_visible'] is False
                     and tail['native_va_list'] is None, 'caller-owned UInt reg_idx')
        args.append(body.value(tail['id'], body.uint))
        callee = body.cast('FunctionToPointerDecay', _cursor_pointer(signature), body.ref(d['id'], signature))
        body.match(call['id'], body.node('call', body.void, [callee, *args],
                                        callee_decl=d['id'], builtin=[0, 'unknown']), caller=True)
        _cursor_need(all(x['owner'] != d['id'] or x['id'] in body.body_ids for x in inv['calls']),
                     'extra body call in paired inventory')
        target_refs = [x for x in body.e.values() if x['kind'] == 'reference' and x['decl'] == d['id']]
        _cursor_need(len(target_refs) == 1 and target_refs[0]['id'] == body.e[raw['children'][0]]['children'][0],
                     'extra target reference or alias')
        return {'schema': 1, 'authorization': 'witness_only', 'status': 'witness_proven',
                'symbol': symbol, 'unit': inv['unit'], 'declaration': d['id'], 'stable_lowering': 'not_authorized'}
    except (KeyError, TypeError, IndexError, AttributeError, RecursionError, RecordUnproved) as error:
        raise PlanError('cursor witness: missing or malformed required graph fact: ' + str(error)) from error


if __name__ == '__main__':
    main()
