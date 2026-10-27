"""Read-only replay of compiler-owned, report-only closed format fact packets."""
import argparse
from collections import namedtuple
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys

from full_compiler import UNITS, verify_cursor_tool, verify_native_cursor_inputs

MAX_FILE = 512 * 1024 * 1024
MAX_PACKET = 4 * 1024 * 1024 * 1024


class FactsError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise FactsError(message)


def same(left, right):
    if type(left) is not type(right): return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
    return left == right


def sha(data):
    return hashlib.sha256(data).hexdigest()


def loads(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'duplicate JSON key ' + key)
            result[key] = value
        return result
    def invalid_constant(value):
        raise FactsError('nonfinite JSON number ' + value)
    return json.loads(data, object_pairs_hook=unique, parse_constant=invalid_constant)


def key(symbol):
    need(isinstance(symbol, dict), 'missing compiler symbol identity')
    if set(symbol) == {'linker'}:
        need(isinstance(symbol['linker'], str) and symbol['linker'], 'invalid linker identity')
        return ('linker', symbol['linker'])
    need(set(symbol) == {'unit', 'static'} and all(isinstance(v, str) and v for v in symbol.values()),
         'invalid static identity')
    return ('static', symbol['unit'], symbol['static'])


def table(rows, field, label):
    need(isinstance(rows, list), 'missing ' + label)
    result = {}
    for row in rows:
        need(isinstance(row, dict) and type(row.get(field)) is int and 0 < row[field] < 2 ** 64,
             'invalid ' + label + ' ID')
        need(row[field] not in result, 'duplicate ' + label + ' ID')
        result[row[field]] = row
    return result


def safe_file(root, name):
    need(isinstance(name, str) and name == '/'.join(PurePosixPath(name).parts)
         and not name.startswith('/') and '\\' not in name
         and all(p not in ('.', '..', '.git') for p in PurePosixPath(name).parts), 'unsafe packet path')
    path = root
    for part in PurePosixPath(name).parts:
        path /= part
        need(not path.is_symlink(), 'symlink packet member')
    need(path.is_file() and path.stat().st_size <= MAX_FILE, 'missing or excessive packet member ' + name)
    return path


def manifest(root):
    need(root.is_dir() and not root.is_symlink(), 'missing packet directory')
    files = {}
    size = 0
    for path in sorted(root.rglob('*')):
        need(not path.is_symlink(), 'symlink in packet')
        if path.is_dir():
            continue
        name = path.relative_to(root).as_posix()
        if name == 'seal.json':
            continue
        data = safe_file(root, name).read_bytes()
        size += len(data)
        need(size <= MAX_PACKET and len(files) < 4096, 'packet size or file count limit')
        files[name] = {'sha256': sha(data), 'bytes': len(data)}
    return files


def location(row, buffers, buffer_paths):
    need(isinstance(row, dict), 'missing native location')
    if set(row) == {'unproved'}:
        need(isinstance(row['unproved'], str) and row['unproved'], 'empty native origin reason')
        return
    need(set(row) == {'spelling', 'expansion', 'presumed'}, 'invalid native location schema')
    need(isinstance(row['presumed'], dict) and set(row['presumed']) == {'path', 'line'}, 'invalid presumed display')
    for name in ('spelling', 'expansion'):
        span = row[name]
        need(isinstance(span, dict), 'missing physical interval')
        if set(span) == {'unproved'}:
            need(isinstance(span['unproved'], str) and span['unproved'], 'empty physical interval reason')
            continue
        need(set(span) == {'path', 'buffer_sha256', 'begin', 'end', 'bytes_hex'}, 'invalid physical interval schema')
        need(span['path'] in buffer_paths.get(span['buffer_sha256'], set()), 'physical source path differs from native buffer')
        data = buffers.get(span['buffer_sha256'])
        need(data is not None and type(span['begin']) is int and type(span['end']) is int
             and 0 <= span['begin'] <= span['end'] <= len(data), 'native physical interval outside buffer')
        need(data[span['begin']:span['end']].hex() == span['bytes_hex'], 'quoted physical source bytes differ')


def unproved(row):
    need(isinstance(row, dict) and set(row) == {'state', 'reason'} and row['state'] == 'Unproved'
         and isinstance(row.get('reason'), str) and row['reason'],
         'relation requires a concrete Unproved record; no proof is admitted')


def check_invocation(native, command):
    # AstExporter.cpp augment_argv and LLVM 18 ClangTool, retained all24 commands.
    additions = ['-fno-builtin-strlen', '-fparse-all-comments', '-Wwrite-strings',
                 '-D_FORTIFY_SOURCE=0', '-DC2RUST=1',
                 '-resource-dir=/usr/lib/llvm-18/bin/../lib/clang/18', '-fsyntax-only']
    need(native['adjusted_driver_argv'] == command['arguments'] + additions,
         'compile database differs from actual adjusted invocation')
    cc1 = native['regenerated_cc1_argv']
    for pair in (['-x', 'c'], ['-triple', native['target']],
                 ['-resource-dir', '/usr/lib/llvm-18/bin/../lib/clang/18']):
        need(any(cc1[i:i + 2] == pair for i in range(len(cc1) - 1)), 'regenerated invocation identity differs')
    need(command['file'] in cc1 and '-fdebug-compilation-dir=' + command['directory'] in cc1,
         'regenerated source or cwd differs')


def check_statements(statements, expressions, variables):
    for row in statements.values():
        need(type(row['edge_count']) is int and row['edge_count'] == len(row['children']), 'control statement edge coverage differs')
        if row.get('label_target') is not None:
            need(type(row['label_target']) is int and row['label_target'] in statements, 'goto label missing')
            need(statements[row['label_target']]['native_shape'] == 'Label', 'goto target is not a label')
        need((row['kind'] == 'goto') == (row.get('label_target') is not None), 'goto label reference missing')
        shape = row['native_shape']
        shapes = {
            'Compound': ('compound', {}, {'item': 'statement'}),
            'Expr': ('expression', {'expression': 'expression'}, {}),
            'Decls': ('declarations', {}, {'declaration': 'declaration'}),
            'ReturnValue': ('return', {'value': 'expression'}, {}), 'ReturnVoid': ('return', {}, {}),
            'If': ('branch', {'condition': 'expression', 'then': 'statement'}, {}),
            'IfElse': ('branch', {'condition': 'expression', 'then': 'statement', 'else': 'statement'}, {}),
            'Switch': ('branch', {'condition': 'expression', 'body': 'statement'}, {}),
            'While': ('loop', {'condition': 'expression', 'body': 'statement'}, {}),
            'DoWhile': ('loop', {'body': 'statement', 'condition': 'expression'}, {}),
            'Label': ('label', {'body': 'statement'}, {}), 'Default': ('label', {'body': 'statement'}, {}),
            'Case': ('label', {'value': 'expression', 'body': 'statement'}, {}),
            'Attributed': ('attributed', {'body': 'statement'}, {}),
            'Goto': ('goto', {}, {}), 'Break': ('break', {}, {}), 'Continue': ('continue', {}, {}),
            'Empty': ('empty', {}, {}), 'Asm': ('unsupported', {}, {'operand': 'expression'}),
            'BadStmt': ('unsupported', {}, {})}
        for mask in range(8):
            roles = {}
            for bit, role, target in ((4, 'init', 'statement'), (2, 'condition', 'expression'), (1, 'increment', 'expression')):
                if mask & bit:
                    roles[role] = target
            roles['body'] = 'statement'
            shapes['ForLoop' + format(mask, '03b')] = ('loop', roles, {})
        need(shape in shapes, 'unknown concrete statement schema')
        kind, required_roles, optional_roles = shapes[shape]
        need(row['kind'] == kind, 'statement classification contradicts concrete shape')
        roles = [e['role'] for e in row['children']]
        need(all(roles.count(r) == 1 for r in required_roles), 'mandatory statement role missing or repeated')
        repeated = {'item', 'declaration', 'operand'}
        need(all(r in required_roles or r in optional_roles for r in roles)
             and all(r in repeated or roles.count(r) == 1 for r in roles), 'incompatible statement roles')
        need(roles == list(required_roles) if required_roles else all(r in optional_roles for r in roles),
             'statement role order differs')
        need(all(e['kind'] == (required_roles | optional_roles)[e['role']] for e in row['children']),
             'statement role table differs')
        for edge in row['children']:
            target = {'statement': statements, 'expression': expressions, 'declaration': variables}.get(edge['kind'])
            need(target is not None and edge['id'] in target, 'structural control edge missing')
        unproved(row['flow'])

Relations = namedtuple('Relations', 'df structural normalization references required')


class ReportGraph:
    def __init__(self, facts):
        self.unit = facts['unit']
        need(isinstance(self.unit, str) and self.unit, 'invalid raw unit identity')
        graph = facts['graph']
        self.expressions = table(graph['expressions'], 'id', 'raw expression')
        self.statements = table(graph['statements'], 'id', 'raw statement')
        self.declarations = table(graph['declarations'], 'id', 'raw declaration')
        self.types = table(graph['types'], 'type_id', 'raw type')
        self.tables = {'expression': self.expressions, 'statement': self.statements,
                       'declaration': self.declarations, 'type': self.types}
        self.keys(graph, 'expressions statements declarations types declaration_order qualified_types')
        self.order = graph['declaration_order']
        need(isinstance(self.order, list) and all(type(i) is int for i in self.order), 'invalid raw declaration census order')
        need(len(self.order) == len(self.declarations) and set(self.order) == self.declarations.keys(),
             'raw declaration census order differs')
        self.relations = {}
        self.check_raw_constructors()
        self.qualified = {}
        need(isinstance(graph['qualified_types'], list), 'invalid qualified census')
        for row in graph['qualified_types']:
            self.keys(row, 'source path', 'unproved' if 'unproved' in row else 'normalized')
            need(('unproved' in row) != ('normalized' in row), 'invalid qualified normalization record')
            need(isinstance(row['path'], list) and all(type(i) is int and i in self.types for i in row['path']), 'invalid normalization path')
            source = self.qkey(row['source'])
            need(source not in self.qualified, 'duplicate qualified source key')
            self.qualified[source] = row
            path, current, seen = [], source[0], set()
            qualifiers = source[1:]
            reason = None
            for step in range(33):
                path.append(current)
                need(current in self.types, 'normalization type missing')
                if step == 32:
                    break
                if current in seen:
                    reason = 'typedef or wrapper cycle'
                    break
                seen.add(current)
                raw = self.types[current]
                relation = self.relations['type', current]
                if raw['native_shape'] == 'Typedef' and relation.normalization is None:
                    reason = 'missing original typedef'
                    break
                if raw['native_shape'] == 'Attributed':
                    reason = 'attributed type facts'
                    break
                if relation.normalization is None:
                    break
                if raw['native_shape'] == 'Typedef':
                    qualifiers = tuple(a or b for a, b in zip(qualifiers, self.qkey(raw['original'])[1:]))
                current = relation.normalization['id']
            need(row['path'] == path, 'qualified normalization path differs from raw edges')
            if reason:
                need(set(row) == {'source', 'path', 'unproved'} and row['unproved'] == reason,
                     'normalization Unproved relation differs')
            else:
                need(set(row) == {'source', 'path', 'normalized'} and self.qkey(row['normalized']) == (current, *qualifiers),
                     'normalized terminal disconnected from source qualified type')
        for ident, row in self.declarations.items():
            expected_owners = [owner for owner in self.order if self.declarations[owner]['kind'] == 'function'
                               and ident in self.declarations[owner]['parameters']]
            need(row['parameter_owners'] == expected_owners, 'complete raw parameter ownership differs')
            if row['kind'] == 'function':
                need(row['va_parameters'] == [p for p in row['parameters'] if self.declarations[p]['va_list']],
                     'compiler va parameter classification projection differs')
        for row in self.declarations.values():
            q = row.get('qualified_type')
            if q is not None:
                need(row['type_id'] == q['type_id'], 'declaration source qualified key differs')
                if 'type' in row:
                    need(same(row['type'], self.type_view(q, True)), 'declaration canonical projection differs')
            if row.get('native_va_list'):
                native = row['native_va_list']
                for prefix in ('declared', 'builtin'):
                    key = dict(type_id=native[prefix + '_type_id'], **{
                        flag: native[prefix + '_' + flag] for flag in ('const', 'volatile', 'restrict')})
                    need(same(native[prefix + '_canonical_type'], self.type_view(key, True)), 'native cursor qualified projection differs')
        for row in self.expressions.values():
            q = row['qualified_type']
            need(row['type_id'] == (q['type_id'] if q else None), 'expression source qualified key differs')
            if 'argument_qualified_type' in row:
                need(same(row['argument_type'], self.type_view(row['argument_qualified_type'], True)), 'unary qualified projection differs')
            if 'computation_qualified_types' in row:
                need(same(row['computation_types'], [self.type_view(q, True) if q else None for q in row['computation_qualified_types']]),
                     'computation qualified projection differs')

            self.expression(row['id'])

    @staticmethod
    def edge(kind, ident):
        need(type(ident) is int and 0 < ident < 2 ** 64, 'invalid raw constructor operand ID')
        return {'kind': kind, 'id': ident}

    def qkey(self, value):
        need(isinstance(value, dict) and set(value) == {'type_id', 'const', 'volatile', 'restrict'}
             and type(value['type_id']) is int and value['type_id'] in self.types
             and all(type(value[k]) is bool for k in ('const', 'volatile', 'restrict')), 'invalid source qualified key')
        return tuple(value[k] for k in ('type_id', 'const', 'volatile', 'restrict'))

    @staticmethod
    def keys(row, required, optional=''):
        required, optional = set(required.split()), set(optional.split())
        need(isinstance(row, dict) and required <= row.keys() <= required | optional,
             'raw constructor fields differ: ' + ','.join(sorted(required ^ row.keys())) if isinstance(row, dict) else 'raw record missing')

    @staticmethod
    def text(value, nullable=False):
        need(nullable and value is None or isinstance(value, str), 'invalid raw text')

    @staticmethod
    def integer(value, nullable=False, signed=False):
        need(nullable and value is None or type(value) is int and (-2 ** 63 <= value < 2 ** 63 if signed else 0 <= value < 2 ** 64), 'invalid raw integer')

    def ref(self, kind, value, declaration_kind=None):
        edge = self.edge(kind, value)
        need(value in self.tables[kind], 'raw ' + kind + ' reference missing')
        if declaration_kind is not None:
            need(self.declarations[value]['kind'] == declaration_kind, 'raw declaration reference kind differs')
        return edge

    def refs(self, kind, values, declaration_kind=None):
        need(isinstance(values, list), 'invalid raw reference list')
        return [self.ref(kind, value, declaration_kind) for value in values]

    def identity(self, value, depth=0):
        need(depth <= 33 and isinstance(value, dict), 'invalid raw record identity')
        if 'unproved' in value:
            self.keys(value, 'unproved')
            need(isinstance(value['unproved'], str) and value['unproved'], 'empty record identity reason')
            return
        need(depth <= 32, 'record identity exceeds producer depth')
        self.keys(value, 'kind tag physical scope')
        need(value['kind'] in ('struct', 'union', 'enum'), 'invalid record identity kind')
        self.text(value['tag'], True)
        physical = value['physical']
        self.keys(physical, 'path line column')
        need(isinstance(physical['path'], str) and physical['path'].startswith('/'), 'invalid record physical path')
        for name in ('line', 'column'):
            need(type(physical[name]) is int and physical[name] > 0, 'invalid record physical position')
        scope = value['scope']
        need(isinstance(scope, dict), 'invalid record scope')
        if 'file' in scope:
            self.keys(scope, 'file')
            need(scope['file'] is True, 'invalid file scope')
        else:
            self.keys(scope, 'record')
            self.identity(scope['record'], depth + 1)

    def raw_location(self, value):
        need(isinstance(value, dict), 'missing native location')
        if 'unproved' in value:
            self.keys(value, 'unproved')
            need(isinstance(value['unproved'], str) and value['unproved'], 'empty native origin reason')
            return
        self.keys(value, 'spelling expansion presumed')
        self.keys(value['presumed'], 'path line')
        self.text(value['presumed']['path'])
        self.integer(value['presumed']['line'])
        for name in ('spelling', 'expansion'):
            span = value[name]
            if isinstance(span, dict) and 'unproved' in span:
                self.keys(span, 'unproved')
                need(isinstance(span['unproved'], str) and span['unproved'], 'empty physical interval reason')
                continue
            self.keys(span, 'path buffer_sha256 begin end bytes_hex')
            self.text(span['path'])
            need(isinstance(span['buffer_sha256'], str) and len(span['buffer_sha256']) == 64
                 and all(c in '0123456789abcdef' for c in span['buffer_sha256']), 'invalid native buffer digest')
            self.integer(span['begin']); self.integer(span['end'])
            need(span['begin'] <= span['end'] and isinstance(span['bytes_hex'], str)
                 and len(span['bytes_hex']) == 2 * (span['end'] - span['begin'])
                 and all(c in '0123456789abcdef' for c in span['bytes_hex']), 'invalid physical interval bytes')

    def relation(self, kind, row, normalization=None, references=(), extra=()):
        ident = row['type_id' if kind == 'type' else 'id']
        structural = row['structural_children']
        required = [e for e in structural if not (kind == 'declaration' and row['kind'] == 'function' and e['kind'] == 'statement')]
        required += list(extra)
        self.relations[kind, ident] = Relations(tuple(row['df_children']), tuple(structural), normalization,
                                               tuple(references), tuple(required))

    def check_raw_constructors(self):
        need(not (self.expressions.keys() & self.statements.keys())
             and not (self.expressions.keys() & self.declarations.keys())
             and not (self.statements.keys() & self.declarations.keys()), 'impossible cross-table node identity')
        for rows in self.tables.values():
            for row in rows.values():
                for field in ('df_children', 'structural_children'):
                    need(isinstance(row.get(field), list), 'missing unfiltered raw child sequence')
                    for edge in row[field]:
                        self.keys(edge, 'kind id')
                        need(isinstance(edge['kind'], str) and edge['kind'] in self.tables, 'invalid raw edge table')
                        self.ref(edge['kind'], edge['id'])
        for row in self.types.values():
            self.check_type_edges(row)
        for row in self.expressions.values():
            self.check_expr_edges(row)
        for row in self.statements.values():
            self.keys(row, 'id kind label_target native_shape location edge_count children flow df_children structural_children')
            self.raw_location(row['location'])
            need(isinstance(row['children'], list), 'invalid statement children')
            for edge in row['children']:
                self.keys(edge, 'role kind id')
                self.text(edge['role'])
                need(isinstance(edge['kind'], str) and edge['kind'] in self.tables, 'invalid statement child kind')
                self.ref(edge['kind'], edge['id'])
            if row['label_target'] is not None:
                self.ref('statement', row['label_target'])
        check_statements(self.statements, self.expressions, self.declarations)
        for row in self.statements.values():
            need([{k: e[k] for k in ('kind', 'id')} for e in row['children']] == row['structural_children']
                 and row['df_children'] == row['structural_children'], 'raw statement sequence differs')
            references = [] if row['label_target'] is None else [self.edge('statement', row['label_target'])]
            self.relation('statement', row, references=references)
        for row in self.declarations.values():
            self.check_declaration(row)
        self.check_raw_owners()

    def check_declaration(self, row):
        kind = row['kind']
        fields = {
            'function': 'type_id qualified_type parameters body builtin symbol aliases va_parameters',
            'variable': 'name local va_list owning_function type type_id qualified_type initializer static thread externally_visible native_va_list',
            'field': 'name type type_id qualified_type owners bit_width bit_offset type_bit_width alignment',
            'typedef': 'type_id qualified_type',
            'struct': 'identity native_va_list_record fields layout state',
            'union': 'identity native_va_list_record fields layout state',
            'enum': 'identity native_va_list_record variants underlying state',
            'enum_constant': 'name owning_enum value signed',
            'unsupported': 'native_shape'}
        need(kind in fields, 'unknown raw declaration constructor')
        extra_fields = ''
        if kind == 'unsupported':
            need(row['native_shape'] in ('NonCanonicalDecl', 'StaticAssert', 'MacroObject', 'MacroFunction'), 'unknown raw declaration constructor')
            extra_fields = {'NonCanonicalDecl': 'canonical_decl', 'StaticAssert': 'assert_expr'}.get(row['native_shape'], '')
        self.keys(row, 'id kind diagnostic_location parameter_owners df_children structural_children ' + fields[kind] + ' ' + extra_fields)
        self.text(row['diagnostic_location'], True)
        self.refs('declaration', row['parameter_owners'], 'function')
        expected, references, extra = [], [], []
        if kind in ('function', 'variable', 'field', 'typedef'):
            self.qkey(row['qualified_type'])
            need(type(row['type_id']) is int and row['qualified_type']['type_id'] == row['type_id'], 'raw declaration qualified operand differs')
            expected = [self.ref('type', row['type_id'])]
        if kind == 'function':
            need(not any(row['qualified_type'][f] for f in ('const', 'volatile', 'restrict')), 'function source qualifiers differ')
            expected += self.refs('declaration', row['parameters'], 'variable')
            need(isinstance(row['va_parameters'], list) and all(type(i) is int and i in self.declarations
                 and self.declarations[i]['kind'] == 'variable' for i in row['va_parameters']), 'raw va parameter reference missing')
            self.refs('declaration', row['va_parameters'], 'variable')
            need(len(row['parameters']) == len(set(row['parameters'])), 'raw ordered parameters differ')
            if row['body'] is not None: expected += [self.ref('statement', row['body'])]
            symbol = key(row['symbol'])
            need(symbol[0] != 'static' or symbol[1] == self.unit, 'raw static symbol unit differs')
            need(isinstance(row['aliases'], list) and all(isinstance(a, str) for a in row['aliases']), 'invalid function aliases')
            if row['builtin'] is not None:
                need(isinstance(row['builtin'], list) and len(row['builtin']) == 2 and type(row['builtin'][0]) is int
                     and 0 <= row['builtin'][0] < 2 ** 64 and isinstance(row['builtin'][1], str) and row['builtin'][1], 'invalid builtin identity')
        elif kind in ('variable', 'field', 'enum_constant'):
            self.text(row['name'])
            if kind == 'variable':
                for name in ('local', 'va_list', 'static', 'thread', 'externally_visible'):
                    need(type(row[name]) is bool, 'invalid variable flag')
                owner = row['owning_function']
                if row['local']:
                    if isinstance(owner, dict):
                        self.keys(owner, 'unproved')
                        need(owner['unproved'] == 'missing or ambiguous lexical function owner', 'invalid lexical owner reason')
                    else: references += [self.ref('declaration', owner, 'function')]
                else: need(owner is None, 'nonlocal lexical owner differs')
                if row['initializer'] is not None: expected += [self.ref('expression', row['initializer'])]
                native = row['native_va_list']
                if native is not None:
                    native_fields = 'same_canonical_type target_kind'
                    native_fields += ''.join(' ' + prefix + '_' + field for prefix in ('declared', 'builtin')
                                             for field in ('type_id', 'canonical_type', 'const', 'volatile', 'restrict'))
                    self.keys(native, native_fields)
                    need(native['same_canonical_type'] is True, 'invalid cursor canonical relation')
                    self.integer(native['target_kind'])
                    for prefix in ('declared', 'builtin'):
                        q = dict(type_id=native[prefix + '_type_id'], **{f: native[prefix + '_' + f] for f in ('const', 'volatile', 'restrict')})
                        self.qkey(q)
                        extra += [self.ref('type', q['type_id'])]
            elif kind == 'field':
                need(isinstance(row['owners'], list), 'invalid field owners')
                owners = [self.declarations[i]['identity'] for i in self.order if self.declarations[i]['kind'] in ('struct', 'union')
                          for field in self.declarations[i]['fields'] or [] if field == row['id']]
                need(same(row['owners'], owners), 'raw field owner identity copies differ')
                for identity in row['owners']: self.identity(identity)
                for field in ('bit_width', 'alignment'): self.integer(row[field], True)
                for field in ('bit_offset', 'type_bit_width'): self.integer(row[field])
            else:
                need(type(row['signed']) is bool, 'invalid enum constant signedness')
                self.integer(row['value'], signed=row['signed'])
                owner = row['owning_enum']
                need(isinstance(owner, dict), 'invalid enum owner')
                if 'unproved' in owner:
                    self.keys(owner, 'unproved')
                    need(owner['unproved'] == 'missing or ambiguous enum variant owner', 'invalid enum owner reason')
                else:
                    self.keys(owner, 'declaration identity')
                    references += [self.ref('declaration', owner['declaration'], 'enum')]
                    target = self.declarations[owner['declaration']]
                    need(row['id'] in target['variants'] and same(owner['identity'], target['identity']), 'raw enum owner identity differs')
                    self.identity(owner['identity'])
        elif kind in ('struct', 'union', 'enum'):
            self.identity(row['identity'])
            if 'kind' in row['identity']: need(row['identity']['kind'] == kind, 'record identity classification differs')
            need(type(row['native_va_list_record']) is bool and row['state'] in ('complete', 'incomplete', 'unproved'), 'invalid raw record state')
            if kind == 'enum':
                expected = self.refs('declaration', row['variants'], 'enum_constant')
                if row['underlying'] is not None:
                    self.qkey(row['underlying']); expected += [self.ref('type', row['underlying']['type_id'])]
            else:
                if row['fields'] is not None: expected = self.refs('declaration', row['fields'], 'field')
                if row['layout'] is not None:
                    layout = row['layout']
                    need(isinstance(layout, list) and len(layout) == 5 and type(layout[0]) is bool, 'invalid record layout')
                    for value in layout[1:3]: self.integer(value, True)
                    for value in layout[3:]: self.integer(value)
        elif kind == 'unsupported':
            if row['native_shape'] == 'NonCanonicalDecl': expected = [self.ref('declaration', row['canonical_decl'])]
            elif row['native_shape'] == 'StaticAssert': expected = [self.ref('expression', row['assert_expr'])]
        need(row['df_children'] == expected == row['structural_children'], 'raw declaration mandatory edges differ')
        self.relation('declaration', row, references=references, extra=references + extra)

    def check_raw_owners(self):
        owners = {i: set() for i in self.declarations}
        for ident in self.order:
            row = self.declarations[ident]
            if row['kind'] == 'enum':
                for variant in row['variants']: owners[variant].add(ident)
            if row['kind'] != 'function' or row['body'] is None: continue
            pending, seen = [self.edge('statement', row['body'])], set()
            while pending:
                node = pending.pop()
                key = node['kind'], node['id']
                if key in seen: continue
                seen.add(key)
                if node['kind'] == 'type': continue
                if node['kind'] == 'declaration' and self.declarations[node['id']]['kind'] != 'variable': continue
                if node['kind'] == 'statement':
                    statement = self.statements[node['id']]
                    if statement['native_shape'] == 'Decls':
                        for edge in statement['children']:
                            decl = self.declarations[edge['id']]
                            if decl['kind'] == 'variable' and decl['local']: owners[decl['id']].add(ident)
                pending += self.relations[key].structural
        for ident, row in self.declarations.items():
            if row['kind'] == 'variable' and row['local']:
                expected = next(iter(owners[ident])) if len(owners[ident]) == 1 else {'unproved': 'missing or ambiguous lexical function owner'}
                need(row['owning_function'] == expected, 'complete raw lexical function owner differs')
            elif row['kind'] == 'enum_constant':
                expected = ({'declaration': next(iter(owners[ident])), 'identity': self.declarations[next(iter(owners[ident]))]['identity']}
                            if len(owners[ident]) == 1 else {'unproved': 'missing or ambiguous enum variant owner'})
                need(same(row['owning_enum'], expected), 'complete raw enum owner differs')

    def check_type_edges(self, row):
        shape = row['native_shape']
        mapped = {'Pointer': 'pointer', 'Function': 'function', 'ConstantArray': 'array', 'IncompleteArray': 'array',
                  'Struct': 'struct', 'Union': 'union', 'Enum': 'enum', 'Typedef': 'typedef', 'TypeOf': 'typeof',
                  'Paren': 'paren', 'Elaborated': 'elaborated', 'Decayed': 'decayed', 'Auto': 'auto',
                  'Attributed': 'attributed', 'BuiltinFn': 'builtin_function'}
        scalars = {'Void', 'Bool', 'Short', 'Int', 'Long', 'LongLong', 'UShort', 'UInt', 'ULong', 'ULongLong',
                   'SChar', 'UChar', 'Char', 'Double', 'LongDouble', 'Float', 'Int128', 'UInt128', 'Half'}
        need(row.get('kind') == mapped.get(shape, shape if shape in scalars else None),
             'raw type classification differs')
        fields = {
            'Pointer': 'pointee', 'Function': 'return parameters variadic noreturn prototype abi',
            'Struct': 'declaration', 'Union': 'declaration', 'Enum': 'declaration', 'Typedef': 'declaration',
            'TypeOf': 'inner', 'Paren': 'inner', 'Elaborated': 'inner', 'Decayed': 'inner', 'Auto': 'inner',
            'ConstantArray': 'element_type length', 'IncompleteArray': 'element_type length',
            'VariableArray': 'element_type count_expression', 'Complex': 'element_type',
            'Reference': 'original', 'BlockPointer': 'original', 'Vector': 'original', 'Atomic': 'original',
            'Attributed': 'original counted_by', 'TypeOfExpr': 'expression'}
        unsupported = {'BFloat16', 'UnhandledSveType', 'Float128', 'Int8', 'Int16', 'Int32', 'Int64', 'IntPtr',
                       'UInt8', 'UInt16', 'UInt32', 'UInt64', 'UIntPtr', 'IntMax', 'UIntMax', 'Size', 'SSize', 'PtrDiff', 'WChar'}
        need(shape in fields or shape in scalars | unsupported | {'BuiltinFn'}, 'unknown raw type constructor')
        required = 'type_id native_shape df_children structural_children ' + fields.get(shape, '')
        if shape in mapped or shape in scalars: required += ' kind'
        reason = None
        optional = ''
        if shape == 'Typedef':
            if 'original' in row: required += ' original'
            else: reason = 'missing original typedef declaration or type'
        elif shape in ('ConstantArray', 'IncompleteArray'):
            if 'element' in row: required += ' element'
            else: reason = 'missing or inconsistent qualified array element'
        elif shape == 'Char':
            if 'signed' in row:
                required += ' signed'
                need(type(row['signed']) is bool, 'invalid plain char signedness')
            else: reason = 'missing plain char signedness'
        elif shape == 'BuiltinFn': reason = 'BuiltinFn requires a native endpoint relation'
        elif shape in unsupported | {'LongDouble', 'Reference', 'BlockPointer', 'Vector', 'Atomic', 'Attributed', 'TypeOfExpr', 'VariableArray', 'Complex'}:
            reason = 'missing or unsupported required type'
        if reason is not None:
            required += ' unproved'
            need(row.get('unproved') == reason, 'raw type Unproved reason differs')
        self.keys(row, required, optional)
        expected, extra, references, normalization = [], [], [], None
        if shape in ('Struct', 'Union', 'Enum', 'Typedef'):
            references = [self.ref('declaration', row['declaration'], mapped[shape])]
            expected = references[:]
            if shape == 'Typedef' and 'original' in row:
                self.qkey(row['original'])
                normalization = self.ref('type', row['original']['type_id'])
                extra += [normalization]
        elif shape == 'Pointer':
            self.qkey(row['pointee'])
            expected = [self.ref('type', row['pointee']['type_id'])]
        elif shape == 'Function':
            need(isinstance(row['parameters'], list), 'invalid function type parameters')
            for q in [row['return'], *row['parameters']]: self.qkey(q)
            for flag in ('variadic', 'noreturn', 'prototype'):
                need(type(row[flag]) is bool, 'invalid function type flag')
            need(row['abi'] in ('C', 'win64', 'sysv64'), 'invalid function ABI')
            expected = [self.ref('type', q['type_id']) for q in [row['return'], *row['parameters']]]
        elif shape in ('TypeOf', 'Paren', 'Elaborated', 'Decayed', 'Auto'):
            normalization = self.ref('type', row['inner'])
            extra = [normalization]
            if shape != 'Elaborated': expected = [normalization]
        elif shape in ('ConstantArray', 'IncompleteArray', 'VariableArray', 'Complex'):
            expected = [self.ref('type', row['element_type'])]
            if shape in ('ConstantArray', 'IncompleteArray'):
                if shape == 'ConstantArray': self.integer(row['length'])
                else: need(row['length'] is None, 'incomplete array length differs')
                if 'element' in row:
                    self.qkey(row['element'])
                    need(row['element']['type_id'] == row['element_type'], 'raw array element operand differs')
            if shape == 'VariableArray' and row['count_expression'] is not None:
                expected += [self.ref('expression', row['count_expression'])]
        elif shape in ('Reference', 'BlockPointer', 'Vector', 'Atomic', 'Attributed'):
            self.qkey(row['original'])
            expected = [self.ref('type', row['original']['type_id'])]
            if shape == 'Attributed' and row['counted_by'] is not None:
                expected += [self.ref('expression', row['counted_by'])]
        elif shape == 'TypeOfExpr': expected = [self.ref('expression', row['expression'])]
        need(row['df_children'] == expected == row['structural_children'], 'raw type mandatory edges differ')

        self.relation('type', row, normalization, references, extra)

    def check_expr_edges(self, row):
        shape, operands = row['native_shape'], row['operands']
        kinds = {'Literal': 'literal', 'DeclRef': 'reference', 'Paren': 'paren', 'ImplicitCast': 'implicit_cast',
                 'ExplicitCast': 'explicit_cast', 'Unary': 'unary', 'UnaryType': 'unary_type', 'Binary': 'binary',
                 'Call': 'call', 'Member': 'member', 'ArraySubscript': 'subscript'}
        need(row['kind'] == kinds.get(shape, 'unsupported'), 'raw expression classification differs')
        fields = {'Literal': 'literal', 'DeclRef': 'decl', 'ImplicitCast': 'cast field', 'ExplicitCast': 'cast field',
                  'Unary': 'operator', 'UnaryType': 'operator argument_qualified_type argument_type',
                  'Binary': 'operator computation_qualified_types computation_types', 'Member': 'member access'}
        self.keys(row, 'id kind qualified_type type_id children operands native_shape diagnostic_location location statement_body va_list '
                  'df_children structural_children edge_count effect_relation ' + fields.get(shape, '')
                  + (' type_unproved' if shape == 'BadExpr' else ''))
        self.text(row['diagnostic_location'], True)
        self.raw_location(row['location'])
        unproved(row['effect_relation'])
        references, extra = [], []
        if shape == 'BadExpr':
            need(row['qualified_type'] is None and row['type_id'] is None and row['va_list'] is None
                 and row['type_unproved'] == 'importer expression has no qualified type', 'invalid typeless BadExpr')
        else:
            self.qkey(row['qualified_type'])
            need(type(row['type_id']) is int and row['type_id'] == row['qualified_type']['type_id']
                 and type(row['va_list']) is bool, 'expression source qualified key differs')
            extra = [self.ref('type', row['type_id'])]
        need(isinstance(row['children'], list) and all(type(i) is int and i in self.expressions for i in row['children']), 'invalid expression children')
        if shape != 'Statements': need(row['statement_body'] is None, 'unexpected statement expression body')
        if shape == 'DeclRef': references = [self.ref('declaration', row['decl'])]
        elif shape == 'Member':
            self.keys(row['member'], 'id')
            references = [self.ref('declaration', row['member']['id'])]
            need(row['access'] in ('Arrow', 'Dot'), 'invalid member access')
        elif shape in ('ImplicitCast', 'ExplicitCast'):
            need(row['cast'] in ('BitCast', 'LValueToRValue', 'NoOp', 'ToUnion', 'ArrayToPointerDecay', 'FunctionToPointerDecay',
                 'NullToPointer', 'IntegralToPointer', 'PointerToIntegral', 'ToVoid', 'IntegralCast', 'IntegralToBoolean',
                 'IntegralToFloating', 'FloatingToIntegral', 'FloatingToBoolean', 'BooleanToSignedIntegral', 'PointerToBoolean',
                 'FloatingCast', 'FloatingRealToComplex', 'FloatingComplexToReal', 'FloatingComplexCast',
                 'FloatingComplexToIntegralComplex', 'IntegralRealToComplex', 'IntegralComplexToReal', 'IntegralComplexToBoolean',
                 'IntegralComplexCast', 'IntegralComplexToFloatingComplex', 'BuiltinFnToFnPtr', 'VectorSplat', 'AtomicToNonAtomic',
                 'NonAtomicToAtomic'), 'invalid cast kind')
            if row['field'] is not None: references = [self.ref('declaration', row['field'], 'field')]
        elif shape == 'Literal':
            literal = row['literal']
            need(isinstance(literal, dict), 'invalid literal')
            if 'integer' in literal:
                self.keys(literal, 'integer'); self.integer(literal['integer'])
            elif 'character' in literal:
                self.keys(literal, 'character'); self.integer(literal['character'])
            elif 'bytes' in literal:
                self.keys(literal, 'bytes width')
                need(isinstance(literal['bytes'], list) and all(type(i) is int and 0 <= i <= 255 for i in literal['bytes']), 'invalid string bytes')
                need(type(literal['width']) is int and 0 <= literal['width'] <= 255, 'invalid string width')
            else:
                self.keys(literal, 'unsupported'); need(literal['unsupported'] is True, 'invalid unsupported literal')
        if shape in ('Unary', 'UnaryType', 'Binary'):
            operators = {
                'Unary': ('AddressOf', 'Deref', 'Plus', 'PostIncrement', 'PreIncrement', 'Negate', 'PostDecrement',
                          'PreDecrement', 'Complement', 'Not', 'Real', 'Imag', 'Extension', 'Coawait'),
                'UnaryType': ('SizeOf', 'AlignOf', 'PreferredAlignOf'),
                'Binary': ('Multiply', 'Divide', 'Modulus', 'Add', 'Subtract', 'ShiftLeft', 'ShiftRight', 'Less', 'Greater',
                           'LessEqual', 'GreaterEqual', 'EqualEqual', 'NotEqual', 'BitAnd', 'BitXor', 'BitOr', 'And', 'Or',
                           'Assign', 'AssignMultiply', 'AssignDivide', 'AssignModulus', 'AssignAdd', 'AssignSubtract',
                           'AssignShiftLeft', 'AssignShiftRight', 'AssignBitAnd', 'AssignBitXor', 'AssignBitOr', 'Comma')}
            need(row['operator'] in operators[shape], 'invalid expression operator')
        if shape == 'Binary':
            need(isinstance(row['computation_qualified_types'], list) and len(row['computation_qualified_types']) == 2
                 and isinstance(row['computation_types'], list) and len(row['computation_types']) == 2, 'invalid computation keys')
            for q in row['computation_qualified_types']:
                if q is not None: self.qkey(q)
        single = {'Unary', 'ConstantExpr', 'ImplicitCast', 'ExplicitCast', 'Paren', 'CompoundLiteral',
                  'ImaginaryLiteral', 'Predefined', 'VAArg', 'Member'}
        pair = {'Binary', 'ArraySubscript', 'BinaryConditional'}
        triple = {'Conditional', 'Choose'}
        fields = (['child'] if shape in single else ['left', 'right'] if shape in pair else
                  ['condition', 'then', 'else'] if shape in triple else
                  {'UnaryType': ['expression'], 'Call': ['callee', 'arguments'], 'InitList': ['initializers'],
                   'ShuffleVector': ['elements'], 'ConvertVector': ['elements'], 'Statements': ['body'],
                   'Atomic': ['ptr', 'order', 'val1', 'order_fail', 'val2', 'weak'],
                   'OffsetOf': ['type', 'index']}.get(shape, []))
        need(isinstance(operands, dict) and set(operands) == set(fields), 'raw expression operand schema differs')
        for field in ('arguments', 'initializers', 'elements'):
            if field in operands: need(isinstance(operands[field], list), 'invalid expression operand list')
        expr = lambda ident: self.edge('expression', ident)
        if shape in single | pair | triple:
            df = [expr(operands[f]) for f in fields]
        elif shape == 'UnaryType':
            df = [] if operands['expression'] is None else [expr(operands['expression'])]
        elif shape == 'Call':
            df = [expr(operands['callee']), *[expr(i) for i in operands['arguments']]]
        elif shape == 'InitList':
            df = [expr(i) for i in operands['initializers']]
        elif shape == 'Atomic':
            df = [expr(operands[f]) for f in fields if f in ('ptr', 'order') or operands[f] is not None]
        elif shape == 'Statements':
            need(operands['body'] == row['statement_body'], 'raw statement expression operand differs')
            df = [self.edge('statement', operands['body'])]
        else:
            need(shape in {'ShuffleVector', 'ConvertVector', 'OffsetOf', 'Literal', 'DeclRef', 'ImplicitValueInit',
                           'BadExpr', 'DesignatedInitExpr'}, 'unknown raw expression constructor')
            df = []
        structural = df
        if shape in ('ImplicitCast', 'ExplicitCast', 'Paren', 'CompoundLiteral', 'ImaginaryLiteral', 'VAArg'):
            self.qkey(row['qualified_type'])
            structural = [self.edge('type', row['type_id']), *df]
        elif shape == 'UnaryType':
            self.qkey(row['argument_qualified_type'])
            structural = [self.edge('type', row['argument_qualified_type']['type_id']), *df]
        elif shape in ('ShuffleVector', 'ConvertVector'):
            structural = [expr(i) for i in operands['elements']]
        elif shape == 'OffsetOf':
            need((operands['type'] is None) == (operands['index'] is None), 'raw offsetof operands differ')
            structural = [] if operands['type'] is None else [self.edge('type', operands['type']), expr(operands['index'])]
        need(row['df_children'] == df and row['structural_children'] == structural, 'raw expression mandatory edges differ')
        need(row['children'] == [e['id'] for e in structural if e['kind'] == 'expression']
             and type(row['edge_count']) is int and row['edge_count'] == len(row['children']),
             'raw structural expression sequence differs')

        self.relation('expression', row, references=references, extra=extra + references)

    def type_view(self, source, cursor=False, depth=0):
        if depth > 32:
            return {'unproved': 'type depth limit'}
        qualified = self.qualified.get(self.qkey(source))
        need(qualified is not None, 'qualified normalization owner missing')
        if 'unproved' in qualified:
            return {'unproved': qualified['unproved']}
        normalized = qualified['normalized']
        row = self.types[normalized['type_id']]
        kind = row.get('kind')
        child = lambda q: self.type_view(q, cursor, depth + 1)
        if kind == 'pointer':
            canonical = {'pointer': child(row['pointee'])}
        elif kind == 'function':
            canonical = {'return': child(row['return']), 'parameters': [child(q) for q in row['parameters']],
                         **{k: row[k] for k in ('variadic', 'noreturn', 'prototype', 'abi')}}
        elif kind == 'array':
            if 'element' not in row:
                return {'unproved': 'missing original qualified array element'}
            canonical = {'array': child(row['element'])}
            if row['length'] is not None:
                canonical['length'] = row['length']
        elif kind in ('struct', 'union', 'enum'):
            decl = self.declarations[self.relations['type', row['type_id']].references[0]['id']]
            canonical = {'native_va_list_record': decl['id']} if cursor and decl['native_va_list_record'] else {'record': decl['identity']}
        elif kind == 'Char':
            canonical = {'kind': kind, 'signed': row['signed']} if 'signed' in row else {'unproved': 'missing plain char signedness'}
        elif kind == 'LongDouble':
            canonical = {'unproved': 'long double ABI shape'}
        elif kind in ('Void', 'Bool', 'SChar', 'Short', 'Int', 'Long', 'LongLong', 'UChar', 'UShort',
                      'UInt', 'ULong', 'ULongLong', 'Float', 'Double', 'Int128', 'UInt128', 'Half'):
            canonical = {'kind': kind}
        else:
            canonical = {'unproved': 'unsupported type or wrapper limit'}
        return {'canonical': canonical, **{k: normalized[k] for k in ('const', 'volatile', 'restrict')}}

    def walk(self, root):
        result, path, cyclic = [], set(), False
        pending = [(root, False)]
        while pending:
            edge, leaving = pending.pop()
            key = (edge['kind'], edge['id'])
            if leaving:
                path.remove(key)
                continue
            if key in path:
                cyclic = True
                continue
            path.add(key)
            result.append(edge)
            pending.append((edge, True))
            relation = self.relations[edge['kind'], edge['id']]
            pending.extend((child, False) for child in reversed(relation.df))
        return result, cyclic

    def terminal(self, ident):
        seen = set()
        while self.expressions[ident]['kind'] in ('paren', 'implicit_cast'):
            need(ident not in seen, 'cyclic expression wrapper path')
            seen.add(ident)
            children = self.expressions[ident]['children']
            need(len(children) == 1, 'ambiguous expression wrapper path')
            ident = children[0]
        return ident

    def callee(self, ident):
        row = self.expressions[self.terminal(ident)]
        decl = self.relations['expression', row['id']].references[0]['id'] if row['kind'] == 'reference' else None
        return decl if self.declarations.get(decl, {}).get('kind') == 'function' else None

    def promotions(self, ident):
        result, seen = [], set()
        while True:
            need(ident not in seen, 'cyclic expression promotion path')
            seen.add(ident)
            row = self.expressions[ident]
            if row['qualified_type']:
                result.append(self.type_view(row['qualified_type']))
            if row['kind'] not in ('paren', 'implicit_cast'):
                return result
            ident = row['children'][0]

    def operand(self, ident):
        row = self.expressions[ident]
        terminal = self.expressions[self.terminal(ident)]
        literal = terminal.get('literal', {})
        references = []
        nodes, cyclic = self.walk(self.edge('expression', ident))
        for node in nodes:
            if node['kind'] == 'expression':
                expr = self.expressions[node['id']]
                if expr['kind'] == 'reference':
                    references.append({'id': expr['id'], 'decl': self.relations['expression', expr['id']].references[0]['id']})
        operand = {'id': ident, 'direct_decl': self.relations['expression', terminal['id']].references[0]['id'] if terminal['kind'] == 'reference' else None,
                'literal': literal.get('bytes') if literal.get('width') == 1 else None,
                'type': self.type_view(row['qualified_type'], True) if row['qualified_type'] else None,
                'references': references}
        if cyclic:
            operand['references_unproved'] = 'cyclic DF traversal retains raw edges'
        return operand

    def expression(self, ident):
        row = dict(self.expressions[ident])
        row['type'] = self.type_view(row['qualified_type'], True) if row['qualified_type'] else None
        row['promotion_chain'] = self.promotions(ident)
        if row['kind'] == 'member':
            row['member'] = self.declarations[self.relations['expression', ident].references[0]['id']]
        if row['kind'] == 'call':
            callee = row['children'][0]
            decl = self.callee(callee)
            row.update(callee_expression=callee, callee_reference=self.terminal(callee), callee_decl=decl,
                       builtin=self.declarations[decl]['builtin'] if decl else None,
                       arguments=[self.operand(a) for a in row['children'][1:]])
        return row

    def inventory(self, facts):
        declarations, owners = [], {}
        for ident in self.order:
            row = self.declarations[ident]
            if row['kind'] != 'function':
                continue
            declarations.append({'id': ident, 'symbol': row['symbol'], 'location': row['diagnostic_location'],
                                 'signature': self.type_view(row['qualified_type']), 'definition': row['body'] is not None,
                                 'aliases': row['aliases'], 'va_parameters': row['va_parameters']})
            if row['body'] is not None:
                for node in self.walk(self.edge('statement', row['body']))[0]:
                    if node['kind'] == 'expression':
                        owners[node['id']] = ident
        direct_refs, calls = set(), []
        for ident, row in sorted(self.expressions.items()):
            if row['kind'] != 'call':
                continue
            callee = row['children'][0]
            decl = self.callee(callee)
            if decl is not None:
                direct_refs.update(n['id'] for n in self.walk(self.edge('expression', callee))[0] if n['kind'] == 'expression')
            calls.append({'id': ident, 'owner': owners.get(ident), 'location': row['diagnostic_location'],
                          'callee': self.declarations[decl]['symbol'] if decl else None,
                          'arguments': [{'id': a, 'promotion_chain': self.promotions(a),
                                         'type': self.type_view(self.expressions[a]['qualified_type']) if self.expressions[a]['qualified_type'] else None,
                                         'va_list': self.expressions[a]['va_list']} for a in row['children'][1:]]})
        escapes, va_arg = [], []
        for ident, row in sorted(self.expressions.items()):
            if row['kind'] == 'reference' and ident not in direct_refs:
                decl = self.declarations[self.relations['expression', ident].references[0]['id']]
                if decl['kind'] == 'function':
                    escapes.append({'symbol': decl['symbol'], 'location': row['diagnostic_location']})
            if row['native_shape'] == 'VAArg':
                va_arg.append({'owner': owners.get(ident), 'location': row['diagnostic_location']})
        records = []
        for ident in self.order:
            row = self.declarations[ident]
            if row['kind'] not in ('struct', 'union', 'enum'):
                continue
            if row['kind'] == 'enum':
                fields = {'underlying': self.type_view(row['underlying']) if row['underlying'] else None,
                          'variants': [{k: self.declarations[v][k] for k in ('name', 'signed', 'value')}
                                       if self.declarations[v]['kind'] == 'enum_constant' else {'unproved': 'non-enumerator child'}
                                       for v in row['variants']]}
            else:
                fields = {'layout': row['layout'], 'fields': None if row['fields'] is None else [
                    {'name': self.declarations[v]['name'], 'type': self.type_view(self.declarations[v]['qualified_type']),
                     **{k: self.declarations[v][k] for k in ('bit_width', 'bit_offset', 'type_bit_width', 'alignment')}}
                    if self.declarations[v]['kind'] == 'field' else {'unproved': 'non-field record child'} for v in row['fields']]}
            records.append({'identity': row['identity'], 'state': row['state'], 'facts': fields, 'diagnostic_location': row['diagnostic_location']})
        return {'schema': 2, 'record_evidence_schema': 2, 'unit': facts['unit'], 'target': facts['target'],
                'target_c_widths_bits': facts['target_c_widths_bits'], 'authorization': 'inventory_only',
                'declarations': declarations, 'calls': calls, 'record_definitions': records, 'non_call_references': escapes, 'va_arg': va_arg}

    def check(self, facts, inventory):
        need(same(self.inventory(facts), inventory), 'full inventory graph projection differs')
        for name, raw in (('expressions', self.expressions), ('statements', self.statements),
                          ('variables', self.declarations), ('types', self.types)):
            field = 'type_id' if name == 'types' else 'id'
            selected = table(facts[name], field, 'selected ' + name)
            for ident, row in selected.items():
                need(ident in raw and same(row, self.expression(ident) if name == 'expressions' else raw[ident]),
                     'selected ' + name + ' graph projection differs')
        targets = {d['id'] for d in inventory['declarations']
                   if type(d['signature'].get('canonical', {}).get('variadic')) is bool
                   and (d['signature']['canonical']['variadic'] or d['va_parameters'])}
        pending = [self.edge('declaration', i) for i in targets]
        pending += [self.edge('statement', self.declarations[i]['body']) for i in targets if self.declarations[i]['body'] is not None]
        pending += [self.edge('expression', row['id']) for row in inventory['calls']
                    if self.callee(self.expressions[row['id']]['children'][0]) in targets]
        closure = {kind: set() for kind in self.tables}
        while pending:
            edge = pending.pop()
            kind, ident = edge['kind'], edge['id']
            if ident in closure[kind]:
                continue
            closure[kind].add(ident)
            pending += self.relations[kind, ident].required
        for field, kind in (('expressions', 'expression'), ('statements', 'statement'), ('variables', 'declaration'), ('types', 'type')):
            need({r['type_id' if kind == 'type' else 'id'] for r in facts[field]} == closure[kind],
                 'complete selected ' + kind + ' graph closure differs')
        expected_definitions = {i for i in targets if self.declarations[i]['body'] is not None}
        need({d['declaration'] for d in facts['definitions']} == expected_definitions, 'full definition census projection differs')
        unknowns = {d['id'] for d in inventory['declarations'] if d['definition']
                    and type(d['signature'].get('canonical', {}).get('variadic')) is not bool}
        need({d['declaration'] for d in facts['unclassified_definitions']} == unknowns, 'full unclassified definition census differs')
        for definition in facts['definitions']:
            raw = self.declarations[definition['declaration']]
            need(same(definition['signature'], self.type_view(raw['qualified_type'], True))
                 and same(definition['body'], raw['body']), 'definition source graph projection differs')
        selected = {e['id'] for e in facts['expressions']}
        expected = [{'expression': ident, 'native_shape': row['native_shape'], 'type': self.expression(ident)['type'],
                     'within_slice': ident in selected, 'location': row['location'], 'relevance': {
                         'state': 'Unproved', 'reason': 'selected unsupported expression retains its complete structural children'
                         if ident in selected else 'outside selected slice; influence on formatting, control and effects is not established'}}
                    for ident, row in sorted(self.expressions.items()) if row['kind'] == 'unsupported']
        need(same(facts['unsupported_expressions'], expected), 'full unsupported graph census differs')
        expected_records = [{'declaration': row['id'], 'identity': row['identity']} for row in facts['variables']
                            if row.get('native_va_list_record') is True]
        need(same(facts['native_record_identities'], expected_records), 'native record declaration projection differs')


def check_unit(facts, inventory, command):
    need(facts.get('schema') == 2 and facts.get('authorization') == 'analysis_only'
         and facts.get('status') == 'CompleteReport' and facts.get('lowering') == 'not_authorized',
         'not a complete report-only compiler record')
    unit = facts['unit']
    need(unit == inventory['unit'] == command['file'] and facts['target'] == inventory['target']
         and facts['target_c_widths_bits'] == inventory['target_c_widths_bits'], 'unit target or width identity differs')
    need(facts['target'] == 'x86_64-pc-linux-gnu'
         and facts['target_c_widths_bits'] == dict(char=8, short=16, int=32, long=64,
              long_long=64, pointer=64, float=32, double=64), 'unretained target ABI')
    verify_native_cursor_inputs(facts, unit, facts['target'], command, read_current=False)
    native = facts['native_inputs']
    check_invocation(native, command)
    need(native.get('schema') == 2 and native.get('main_input') == unit and native.get('target') == facts['target']
         and native.get('unsupported') == [] and native.get('cwd') == command['directory'], 'native invocation mismatch')
    buffers = {}
    paths = {}
    buffer_paths = {}
    for row in native['buffers']:
        data = bytes.fromhex(row['bytes_hex'])
        need(len(data) == row['length'] and sha(data) == row['sha256'], 'cached native buffer identity differs')
        buffer_paths.setdefault(row['sha256'], set()).add(row['physical_path'])
        previous = buffers.setdefault(row['sha256'], data)
        need(previous == data, 'native buffer digest collision')
        if row['physical_path']:
            paths[row['physical_path']] = row['sha256']
    need(unit in paths, 'native main input missing')
    for rows in (facts['graph']['expressions'], facts['graph']['statements']):
        for row in rows:
            location(row['location'], buffers, buffer_paths)
    ReportGraph(facts).check(facts, inventory)
    declarations = table(facts['declarations'], 'id', 'declaration')
    need(same(facts['declarations'], inventory['declarations']), 'compiler declaration census differs from inventory')
    raw_calls = table(inventory['calls'], 'id', 'inventory call')
    calls = table(facts['calls'], 'id', 'format call')
    definitions = table(facts['definitions'], 'declaration', 'definition')
    unclassified = table(facts['unclassified_definitions'], 'declaration', 'unclassified definition')
    expressions = table(facts['expressions'], 'id', 'expression')
    statements = table(facts['statements'], 'id', 'statement')
    variables = table(facts['variables'], 'id', 'variable')
    function_edges = table(facts['function_edges'], 'declaration', 'function parameter edges')
    native_record_identities = table(facts['native_record_identities'], 'declaration', 'native record identity')
    for i, row in native_record_identities.items():
        need(i in variables and variables[i]['kind'] == 'struct'
             and isinstance(row.get('identity'), dict), 'native record identity reference differs')
    expected_edges = {i for i, d in declarations.items()
                      if type(d['signature'].get('canonical', {}).get('variadic')) is bool
                      and (d['signature']['canonical']['variadic'] or d['va_parameters'])}
    need(function_edges.keys() == expected_edges, 'target function parameter edge coverage differs')
    for i, declaration in declarations.items():
        parameters = variables.get(i, {}).get('parameters', [])
        va_parameters = declaration['va_parameters']
        need(isinstance(va_parameters, list) and len(set(va_parameters)) == len(va_parameters)
             and all(p in variables and variables[p]['kind'] == 'variable'
                     and variables[p]['parameter_owners'] == [i] and p in parameters for p in va_parameters),
             'va parameter reference missing or owned by another function')
        need([p for p in parameters if p in va_parameters] == va_parameters,
             'ordered va parameter references differ')
    for i, edge in function_edges.items():
        need(i in declarations and edge['fixed_count'] == len(edge['parameters'])
             and len(set(edge['parameters'])) == len(edge['parameters']), 'function parameter reference coverage differs')
        need(i in variables and variables[i]['kind'] == 'function' and same(variables[i]['parameters'], edge['parameters']),
             'ordered function declaration references differ')
        need(all(p in variables and variables[p]['kind'] == 'variable'
                 and variables[p]['parameter_owners'] == [i] for p in edge['parameters']),
             'parameter declaration missing or owned by another function')
        position = edge['format_position']
        need(position is None and edge['format_parameter'] is None or type(position) is int
             and 0 <= position < len(edge['parameters']) and edge['format_parameter'] == edge['parameters'][position], 'function format parameter edge differs')
    def reference(value, rows, label):
        need(type(value) is int and value in rows, label + ' reference missing')
    for i, row in variables.items():
        if row['kind'] == 'function' and i in function_edges:
            need(same(row['parameters'], function_edges[i]['parameters']), 'ordered function parameters differ')
    for i, row in definitions.items():
        need(i in function_edges and same(row['parameters'], function_edges[i]['parameters']),
             'ordered definition parameters differ')
    unsupported = table(facts['unsupported_expressions'], 'expression', 'unsupported expression')
    need(type(facts['unsupported_expression_count']) is int and facts['unsupported_expression_count'] == len(unsupported),
         'unsupported expression census coverage differs')
    for i, row in unsupported.items():
        need(type(row['within_slice']) is bool and row['within_slice'] == (i in expressions)
             and isinstance(row['native_shape'], str) and row['native_shape'], 'unsupported relevance or shape reference differs')
        unproved(row['relevance'])
        location(row['location'], buffers, buffer_paths)
        if row['within_slice']:
            need(expressions[i]['kind'] == 'unsupported' and expressions[i]['native_shape'] == row['native_shape'], 'selected unsupported shape differs')
    need({i for i, e in expressions.items() if e['kind'] == 'unsupported'} <= unsupported.keys(), 'selected unsupported expression omitted')
    events = table(facts['cursor_events'], 'expression', 'cursor event')
    expected_events = {i: e for i, e in expressions.items() if e['kind'] == 'call'}
    need(events.keys() == expected_events.keys(), 'cursor start copy forward format end coverage differs')
    for i, event in events.items():
        unproved(event['relation'])
        expr = expected_events[i]
        need(same(event['builtin'], expr['builtin']) and same(event['callee_declaration'], expr['callee_decl'])
             and same(event['operands'], expr['arguments']), 'cursor event operands or builtin edge differs')
    for row in [*definitions.values(), *unclassified.values()]:
        decl = declarations.get(row['declaration'])
        need(decl is not None and decl['definition'] and decl['symbol'] == row['symbol'], 'definition declaration edge differs')
        location(row['location'], buffers, buffer_paths)
    for row in unclassified.values():
        need(same(row['signature'], declarations[row['declaration']]['signature']) and row['state'] == 'Unproved'
             and row['reason'], 'unclassified native signature facts lost')
    for row in definitions.values():
        unproved(row['generated_origin'])
        unproved(row['control_effect_lifetime'])
        need(row['body'] in statements and set(row['parameters']) <= variables.keys(), 'definition body or parameter missing')
        need(row['va_parameters'] == declarations[row['declaration']]['va_parameters'], 'consumer parameter edge differs')
    for row in calls.values():
        location(row['native_location'], buffers, buffer_paths)
    for row in calls.values():
        raw = raw_calls.get(row['id'])
        need(raw is not None and all(same(row.get(k), v) for k, v in raw.items()), 'call inventory facts changed')
        need(type(row['callee_declaration']) is int and row['callee_declaration'] in declarations
             and declarations[row['callee_declaration']]['symbol'] == row['callee'], 'callee declaration edge differs')
        if row['owner'] is not None:
            reference(row['owner'], declarations, 'call owner')
        need(row['id'] in expressions, 'call expression missing')
        expr = expressions[row['id']]
        need(expr['kind'] == 'call' and same(expr['callee_decl'], row['callee_declaration'])
             and [a['id'] for a in expr['arguments']] == [a['id'] for a in row['arguments']],
             'inventory call callee or ordered operands contradict expression')
        need(type(row['fixed_count']) is int and 0 <= row['fixed_count'] <= len(row['arguments']), 'fixed argument coverage differs')
        need(row['callee_declaration'] in function_edges, 'call function parameter edges absent')
        edge = function_edges[row['callee_declaration']]
        need(row['fixed_count'] == edge['fixed_count'] and row['format_position'] == edge['format_position'], 'call format or fixed parameter position differs')
        position = row['format_position']
        need(position is None or type(position) is int and 0 <= position < row['fixed_count'], 'format position outside fixed arguments')
        if position is not None:
            need(row['format'].get('expression') == row['arguments'][position]['id'], 'format position expression edge differs')
        unproved(row['generated_origin'])
        unproved(row['evaluation'])
        unproved(row['format_position_relation'])
        for argument in row['arguments']:
            expr = expressions.get(argument['id'])
            need(expr is not None and expr['promotion_chain'] == argument['promotion_chain'], 'promotion chain reference differs')
            need(argument['type'] == (expr['promotion_chain'][0] if expr['type'] is not None else None),
                 'inventory argument type contradicts promotion head')
    reachable = set()
    pending = [row['body'] for row in definitions.values()]
    pending.extend(row['statement_body'] for row in expressions.values() if row.get('statement_body') is not None)
    need(set(pending) <= statements.keys(), 'statement expression body missing')
    while pending:
        node = pending.pop()
        need(node not in reachable, 'cyclic or shared statement ownership')
        reachable.add(node)
        pending.extend(e['id'] for e in statements[node]['children'] if e['kind'] == 'statement')
    need(reachable == statements.keys(), 'missing branch loop return or complete body edge')
    for owner, definition in definitions.items():
        pending, seen = [('statement', definition['body'])], set()
        while pending:
            kind, ident = pending.pop()
            if (kind, ident) in seen:
                continue
            seen.add((kind, ident))
            if kind == 'statement':
                pending.extend((e['kind'], e['id']) for e in statements[ident]['children'])
            elif kind == 'expression':
                expr = expressions[ident]
                pending.extend(('expression', e) for e in expr['children'])
                if expr.get('statement_body') is not None:
                    pending.append(('statement', expr['statement_body']))
                if ident in calls:
                    need(calls[ident]['owner'] == owner, 'call lexical ownership differs')
            else:
                decl = variables[ident]
                if decl.get('local'):
                    need(decl.get('owning_function') == owner, 'variable lexical ownership differs')
                if decl.get('initializer') is not None:
                    pending.append(('expression', decl['initializer']))
    def consumption(row, literal):
        need(isinstance(row, dict) and row.get('state') in ('Parsed', 'Unproved'), 'missing compiler format consumption')
        conversions = row.get('conversions', []) if row['state'] == 'Parsed' else row.get('prefix', [])
        if row['state'] == 'Unproved':
            need(isinstance(row.get('reason'), str) and row['reason'], 'unsupported syntax lost its reason')
        else:
            unproved(row['type_compatibility'])
        slots, previous = [], 0
        for conversion in conversions:
            begin, end = conversion['begin'], conversion['end']
            need(type(begin) is int and type(end) is int and previous <= begin < end <= len(literal)
                 and literal[begin] == 37 and literal[end - 1] == conversion['conversion'], 'conversion source interval differs')
            length = conversion['length']
            need(literal[end - 1 - len(length):end - 1] == length, 'conversion length bytes differ')
            for argument in conversion['arguments']:
                need(argument['role'] in ('width', 'precision', 'value'), 'invalid consumption role')
                slots.append(argument['slot'])
            previous = end
        need(slots == list(range(len(slots))), 'format argument consumption has missing or duplicate slots')
        if row['state'] == 'Parsed':
            need(type(row['arguments']) is int and row['arguments'] == len(slots), 'format consumption arity differs')
    def format_refs(row):
        need(isinstance(row, dict) and row.get('kind') in ('Wrapper', 'Literal', 'Conditional', 'Declaration', 'Unproved'), 'invalid format origin')
        if 'expression' in row:
            need(row['expression'] in expressions, 'format expression missing')
        if row['kind'] == 'Wrapper':
            need(expressions[row['expression']]['children'] == [row['inner']['expression']], 'format wrapper edge differs')
            format_refs(row['inner'])
        elif row['kind'] == 'Literal':
            need(expressions[row['expression']].get('literal', {}).get('bytes') == row['bytes'], 'format literal bytes differ')
            consumption(row['consumption'], row['bytes'])
        elif row['kind'] == 'Conditional':
            need(expressions[row['expression']]['children'] == [row['condition'], row['true']['expression'], row['false']['expression']], 'conditional format edges differ')
            format_refs(row['true']); format_refs(row['false'])
        elif row['kind'] == 'Declaration':
            need(expressions[row['expression']].get('decl') == row['declaration'], 'format declaration edge differs')
            unproved(row['relation'])
        else:
            need(row.get('reason'), 'missing runtime format reason')
    for row in calls.values():
        format_refs(row['format'])
    return definitions, calls, unclassified


def replay(root):
    need(not root.is_symlink(), 'symlink packet directory')
    root = root.absolute()
    before = manifest(root)
    need(loads(safe_file(root, 'seal.json').read_bytes()) == before, 'packet seal differs')
    packet = loads(safe_file(root, 'packet.json').read_bytes())
    need(packet.get('schema') == 1 and packet.get('authorization') == 'analysis_only', 'invalid packet schema')
    def read(name):
        return loads(safe_file(root, name).read_bytes())
    need(set(packet['verifier_sources']) == {'closed_format_facts.py', 'full_compiler.py', 'probe.py', 'apply_c2rust_patch.py'}, 'incomplete verifier source identity')
    for name, snapshot in packet['verifier_sources'].items():
        need(safe_file(root, snapshot).read_bytes() == Path(__file__).with_name(name).read_bytes(), 'verifier source identity differs')
    commands = read(packet['database'])
    need(len(commands) == len(UNITS) and len({c['file'] for c in commands}) == len(UNITS), 'missing extra or duplicate TU commands')
    need(sorted(str(Path(c['file']).relative_to(c['directory'])) for c in commands) == list(UNITS), 'exact all24 units differ')
    command_map = {c['file']: c for c in commands}
    syntax = read(packet['native_syntax'])
    need(len(syntax) == len(commands), 'native syntax receipt coverage differs')
    for command, record in zip(commands, syntax):
        need(record.get('exit_code') == 0 and not record.get('timed_out') and record.get('command') ==
             command['arguments'][:-2] + ['-fsyntax-only', command['file']], 'native syntax receipt failed or differs')
    need(len(packet['units']) == len(command_map) and {u['unit'] for u in packet['units']} == command_map.keys(), 'fact TU coverage differs')
    expected_tools = {'compiler', 'source_receipt', 'patch', 'source_evidence'}
    need(set(packet['tool']) == expected_tools, 'incomplete compiler tool binding')
    for name in packet['tool'].values():
        safe_file(root, name)
    need(packet['tool'] == {'compiler': 'tool/bin/c2rust-transpile', 'source_receipt': 'tool/source-receipt.json',
         'patch': 'tool/source-evidence/c2rust-source.patch',
         'source_evidence': 'tool/source-evidence/c2rust-patch.json'}, 'unexpected retained tool layout')
    read(packet['tool']['source_receipt'])
    read(packet['tool']['source_evidence'])
    verify_cursor_tool(safe_file(root, packet['tool']['compiler']))
    need(read(packet['tool']['source_evidence'])['official_repository'] == 'https://github.com/immunant/c2rust.git',
         'wrong compiler source repository')
    native_files = read(packet['native_files'])
    observed_native_files = set()
    symbols, incoming, extras = {}, {}, {}
    need(len({u['rust_on'] for u in packet['units']}) == len(commands), 'generated TU module identity merged')
    for pair in packet['units']:
        required = {'facts', 'inventory', 'cbor', 'typed_ast', 'rust_off', 'rust_on'}
        need(set(pair) == required | {'unit', 'files'} and set(pair['files']) == required, 'incomplete paired AST binding')
        stem = Path(pair['unit']).stem.replace('.', '_')
        suffixes = {'facts': '.closed-format.json', 'inventory': '.variadic.json', 'cbor': '.cursor.cbor',
                    'typed_ast': '.typed-ast.txt', 'rust_on': '.rs', 'rust_off': '.rs'}
        for field, suffix in suffixes.items():
            need(Path(pair[field]).name == stem + suffix, 'generated module or paired AST unit origin differs')
        for field in required:
            need(sha(safe_file(root, pair[field]).read_bytes()) == pair['files'][field], 'paired raw AST or emission digest differs')
        facts, inventory = read(pair['facts']), read(pair['inventory'])
        need(pair['unit'] == facts['unit'], 'fact pair unit differs')
        need(facts['compiler_session'] == {
             'raw_cbor_sha256': sha(safe_file(root, pair['cbor']).read_bytes()),
             'typed_ast_sha256': sha(safe_file(root, pair['typed_ast']).read_bytes())},
             'raw CBOR or typed AST differs from compiler session')
        for field in ('cbor', 'typed_ast', 'rust_off', 'rust_on'):
            safe_file(root, pair[field])
        need(safe_file(root, pair['rust_off']).read_bytes() == safe_file(root, pair['rust_on']).read_bytes(), 'flag-only generated Rust bytes differ')
        for buffer in facts['native_inputs']['buffers']:
            if buffer['physical_path']:
                observed_native_files.add(buffer['physical_path'])
                need(native_files.get(buffer['physical_path']) == buffer['sha256'], 'native source or header manifest differs')
        definitions, calls, unclassified = check_unit(facts, inventory, command_map[pair['unit']])
        for row in definitions.values():
            symbol = key(row['symbol'])
            need(symbol not in symbols, 'duplicate compiler definition symbol')
            symbols[symbol] = (pair['unit'], row)
        for row in calls.values():
            call_key = (pair['unit'], row['id'])
            need(call_key not in incoming, 'cross-TU call identity merged or duplicated')
            incoming[call_key] = row
        for row in unclassified.values():
            extras[(pair['unit'], row['declaration'])] = row
    need(observed_native_files == native_files.keys(), 'native source or header manifest coverage differs')
    plan = read(packet['inventory_plan'])
    expected = {tuple(s['symbol']): s for s in plan['symbols']}
    need(len(expected) == len(plan['symbols']) == 40 and symbols.keys() == expected.keys(), 'missing extra or duplicate closed symbol or consumer')
    need(plan['units'] == sorted(command_map), 'independent inventory TU identity differs')
    for symbol, (_, row) in symbols.items():
        need(type(row['variadic']) is bool and row['variadic'] == expected[symbol]['signature']['variadic'], 'symbol variadic or cursor classification differs')
    expected_calls = {(c['unit'], c['expression']): symbol for symbol, row in expected.items() for c in row['calls']}
    need(len(expected_calls) == sum(len(row['calls']) for row in expected.values()), 'duplicate independent inventory call identity')
    selected = {k: key(v['callee']) for k, v in incoming.items() if key(v['callee']) in expected}
    need(selected == expected_calls and len(selected) == 4865, 'incoming call coverage differs from independent inventory')
    expected_extras = {(r['unit'], r['id']) for r in plan['unclassified_definitions']}
    need(extras.keys() == expected_extras and len(extras) == 5, 'five attributed blob signatures missing or extra')
    need(sum(bool(row[1]['variadic']) for row in symbols.values()) == 33, 'variadic definition census differs')
    need(sum(not row[1]['variadic'] for row in symbols.values()) == 7, 'cursor consumer census differs')
    need(sum(symbols[v][1]['variadic'] for v in selected.values()) == 4830, 'variadic call census differs')
    actual_manifests = {mode: {p.relative_to(root / mode).as_posix(): sha(p.read_bytes())
                              for p in (root / mode).rglob('*.rs')} for mode in ('off', 'on')}
    need(actual_manifests == packet['paired_rust'] and actual_manifests['off'] == actual_manifests['on']
         and len(actual_manifests['off']) >= len(UNITS), 'complete paired Rust module manifests differ')
    executions = read(packet['executions'])
    need(set(executions) == {'off', 'on'}, 'paired execution receipt missing')
    for mode, record in executions.items():
        need(record.get('command') == packet['commands'][mode] and record.get('exit_code') == 0
             and record.get('process_exit_code') == 0 and not record.get('timed_out'), 'paired compiler execution failed or differs')
    off, on = packet['commands']['off'], packet['commands']['on']
    need('--emit-closed-format-facts' not in off and on.count('--emit-closed-format-facts') == 1
         and [a for a in on if a != '--emit-closed-format-facts'] == off, 'paired command changes more than facts flag')
    need(manifest(root) == before, 'replay changed packet')
    return {'schema': 1, 'status': 'complete_coverage', 'authorization': 'analysis_only',
            'units': 24, 'symbols': 40, 'incoming_calls': 4865, 'unclassified': 5,
            'lowerability': 'blocked', 'whole_library_stable': 'unaccepted', 'four_host_ABI': 'unrun',
            'public_callback': 'unproved', 'corpus_48_positive_2_negative': 'unaccepted',
            'CMP': 'unresolved', 'scan': 'unaccepted', 'reflection': 'unaccepted',
            'product_integration': 'unaccepted', 'native_source_removal': 'not_authorized',
            'authentic_job_proof': False}


def guard(event, args):
    if event == 'open':
        mode, flags = args[1] or '', args[2] or 0
        need(not any(c in mode for c in 'wax+') and not flags &
             (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND), 'read-only replay write denied')
    need(event not in ('os.mkdir', 'os.remove', 'os.rename', 'os.rmdir', 'os.chmod', 'os.link',
         'os.symlink', 'os.truncate', 'os.utime', 'os.system', 'os.posix_spawn', 'os.fork', 'os.forkpty', 'os.exec')
         and not event.startswith(('subprocess.', 'socket.')), 'read-only replay effect denied ' + event)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, required=True)
    args = parser.parse_args()
    sys.addaudithook(guard)
    print(json.dumps(replay(args.replay), sort_keys=True))


if __name__ == '__main__':
    main()
