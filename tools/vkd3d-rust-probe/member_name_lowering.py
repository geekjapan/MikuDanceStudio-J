"""Exact member-name dependency-call-trace experiment, never product authorization.

Default replay reads retained artifacts only. Acquisition and --run-hosted write
artifacts; only --run-hosted compiles. Captured Linux aliases identify retained bytes.
"""
import argparse
import copy
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path, PosixPath, PurePosixPath
import posixpath
import re
import struct
import sys
import tarfile
import zipfile
from unittest.mock import patch

sys.dont_write_bytecode = True
BASE = '7874ace64a61496c3964a3af48ef8eb3f4ef2772'
SYMBOL = 'vkd3d_spirv_build_op_member_name'
MASK = 2**32 - 1
ARTIFACTS = {
    'all24': (12746124666, 171455537, '498e524875a122e886bb67833595dcef3cd919132403041e5b5ac955443d6ac0'),
    'setup': (12745818632, 44689319, '5ed3ac31c42b75eac1f3386142aff65cf58b1afd92096c909db928b59debbfd9'),
    'input': (12746627220, 13927470, '5b54935e36626f0930bbd14e5f943a91e5a52d4307c3030616605ff9a87f37c9'),
}
C_PATH = 'result/source/libs/vkd3d-shader/spirv.c'
R_PATH = 'result/rust-raw/src/vkd3d_shader/spirv.rs'
SNAPSHOTS = ('c4ec2ceee71dda9c3ad5d148f21c80d4317ad0f9c88b8d060a1bf18787a8e982',
             '1ac9f1c058480a7bad46ae26f2ed32d3e6ebe5afb7063d046929618adec61217')


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def loads(data):
    def pairs(rows):
        out = {}
        for key, value in rows:
            need(key not in out, 'duplicate JSON key')
            out[key] = value
        return out
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def safe_name(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and '..' not in p.parts and '\\' not in name and str(p) == name


def archive(path, name):
    raw = path.read_bytes()
    _, size, digest = ARTIFACTS[name]
    need(len(raw) == size and sha(raw) == digest, 'fixed artifact size/SHA ' + name)
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = z.namelist()
    need(len(names) == len(set(names)), 'duplicate ZIP names')
    for item in z.infolist():
        need(safe_name(item.filename) and (item.external_attr >> 16) & 0o170000 != 0o120000,
             'unsafe ZIP member')
    need(z.testzip() is None, 'ZIP CRC')
    return z


def cbor(data):
    position = 0
    stop = object()
    def item():
        nonlocal position
        need(position < len(data), 'truncated CBOR')
        lead = data[position]
        position += 1
        if lead == 255:
            return stop
        major, small = lead >> 5, lead & 31
        n = small
        if small in (24, 25, 26, 27):
            size = 1 << (small - 24)
            need(position + size <= len(data), 'truncated CBOR integer')
            n = int.from_bytes(data[position:position + size], 'big')
            position += size
        elif small == 31:
            n = None
        else:
            need(small < 24, 'CBOR additional info')
        if major == 0:
            return n
        if major == 1:
            return -1 - n
        if major in (2, 3):
            need(n is not None and position + n <= len(data), 'CBOR string')
            value = data[position:position + n]
            position += n
            return value if major == 2 else value.decode()
        if major == 4:
            values = []
            if n is None:
                while True:
                    value = item()
                    if value is stop:
                        break
                    values.append(value)
            else:
                for _ in range(n):
                    values.append(item())
            return values
        if major == 7 and small in (25, 26, 27):
            return struct.unpack({25: '>e', 26: '>f', 27: '>d'}[small], data[position-size:position])[0]
        if major == 7 and small in (20, 21, 22):
            return {20: False, 21: True, 22: None}[small]
        raise ValueError('unsupported captured CBOR')
    result = item()
    need(position == len(data), 'CBOR trailing bytes')
    return result


class Transport:
    def __init__(self, z, setup):
        self.z, self.setup = z, setup
        self.files, self.aliases = {}, {}
        self.retention = loads(setup.read('early-tool-identity/retention.json'))['files']
        for name, row in self.retention.items():
            raw = setup.read('early-tool-identity/' + name)
            need(len(raw) == row['bytes'] and sha(raw) == row['sha256'], 'tool retained bytes')
            self.files[row['source']] = raw
        self.receipt = loads(z.read('cursor-witness/receipt.json'))
        need(len(self.receipt['pairs']) == 24 and self.receipt['authentic_job_proof'] is False,
             'final 24-pair witness-only receipt')
        for pair in self.receipt['pairs']:
            for field in ('inventory', 'witness', 'cbor', 'typed_ast'):
                path = pair[field]
                member = path.split('/vkd3d-probe/evidence/', 1)[1]
                self.files[path] = ('zip', member)
            w = loads(self.read(pair['witness']))
            for record in w['native_inputs']['buffers']:
                if not record['physical_path']:
                    continue
                path, raw = record['physical_path'], bytes.fromhex(record['bytes_hex'])
                if path in self.files:
                    need(self.read(path) == raw, 'cross-TU cached bytes differ')
                self.files[path] = raw
                for alias in record['aliases']:
                    alias = posixpath.normpath(posixpath.join(w['native_inputs']['cwd'], alias))
                    need(alias not in self.aliases or self.aliases[alias] == path, 'conflicting captured alias')
                    self.aliases[alias] = path
        database = self.receipt['database']
        self.files[database] = ('zip', database.split('/vkd3d-probe/evidence/', 1)[1])

    def read(self, path):
        path = self.aliases.get(posixpath.normpath(str(path)), posixpath.normpath(str(path)))
        value = self.files[path]
        return self.z.read(value[1]) if isinstance(value, tuple) else value

    def context(self):
        import full_compiler as F
        import apply_c2rust_patch as A
        transport = self
        reviewed_patch = Path(F.__file__).parent / 'patches/c2rust-win64-abi.patch'
        class RetainedPath(PosixPath):
            def read_bytes(self):
                if self != reviewed_patch and (str(self).startswith('/home/') or posixpath.normpath(str(self)) in transport.files or posixpath.normpath(str(self)) in transport.aliases):
                    return transport.read(self)
                return super().read_bytes()
            def read_text(self, *args, **kwargs):
                return self.read_bytes().decode(kwargs.get('encoding') or 'utf-8')
            def resolve(self, *args, **kwargs):
                if self != reviewed_patch and (str(self).startswith('/home/') or posixpath.normpath(str(self)) in transport.files or posixpath.normpath(str(self)) in transport.aliases):
                    s = posixpath.normpath(str(self))
                    return RetainedPath(transport.aliases.get(s, s))
                return RetainedPath(super().resolve(*args, **kwargs))
            def is_file(self):
                if self != reviewed_patch and (str(self).startswith('/home/') or posixpath.normpath(str(self)) in transport.files or posixpath.normpath(str(self)) in transport.aliases):
                    return str(self.resolve()) in transport.files
                return super().is_file()
            def is_symlink(self):
                return False if self != reviewed_patch and str(self).startswith('/home/') else super().is_symlink()
        stack = ExitStack()
        stack.enter_context(patch.object(F, 'Path', RetainedPath))
        stack.enter_context(patch.object(A, 'Path', RetainedPath))
        return stack

    def admit(self):
        import full_compiler as F
        pair = next(p for p in self.receipt['pairs'] if p['unit'].endswith('/vkd3d-shader/spirv.c'))
        symbol = {'unit': pair['unit'], 'static': SYMBOL}
        with self.context():
            proof = F.prove_bound_cursor_witness(self.receipt, symbol)
        need(proof == loads(self.z.read('cursor-witness/proof.json')), 'actual bound proof differs')
        need(proof['authorization'] == 'witness_only' and proof['stable_lowering'] == 'not_authorized', 'proof scope')
        for p in self.receipt['pairs']:
            w, inv = loads(self.read(p['witness'])), loads(self.read(p['inventory']))
            raw = cbor(self.read(p['cbor']))
            need(len(raw) == 8 and loads(raw[7]) == w['native_inputs'], 'CBOR exact cached inputs')
            need(raw[4] == w['native_va_list_kind'] and raw[5] == w['target'] == p['target'], 'CBOR native target')
            need(raw[6] == [inv['target_c_widths_bits'][k] for k in ('char','short','int','long','long_long','pointer','float','double')], 'CBOR target widths')
            need(self.read(p['typed_ast']) and self.read(p['unit']), 'typed AST/source binding')
        w, inv = loads(self.read(pair['witness'])), loads(self.read(pair['inventory']))
        f = next(f for f in w['functions'] if f['symbol'] == symbol)
        need(f['declaration'] == proof['declaration'], 'source-bound declaration')
        expressions = {e['id']: e for s in f['statements'] for e in s['expressions']}
        need(len(f['statements']) == 13 and len(expressions) == 102 and sum(e['kind'] == 'call' for e in expressions.values()) == 9, 'frozen body shape')
        calls = [c for c in inv['calls'] if c['callee'] == symbol]
        need(len(calls) == 1 and len(calls[0]['arguments']) == 5, 'sole five-argument caller')
        need(self.z.read(C_PATH) == self.read(pair['unit']), 'authoritative extracted C differs')
        typed = typed_bindings(w,self.read(pair['typed_ast']).decode())
        return {'proof': proof, 'typed_AST_bindings':typed, 'pair_count': 24, 'path_transport': 'read-only captured lexical aliases to retained bytes; no live filesystem identity'}, w, inv


def typed_table(text, section, kind, wanted):
    start = re.search(r'^    '+section+r': ',text,re.M)
    need(start is not None, 'typed AST section '+section)
    end = re.search(r'^    \w+: ',text[start.end():],re.M)
    stop = start.end()+end.start() if end else len(text)
    matches = list(re.finditer(r'^        '+kind+r'\((\d+)\): ',text[start.end():stop],re.M))
    rows = {}
    for i, match in enumerate(matches):
        ident = int(match[1])
        if ident in wanted:
            need(ident not in rows, 'typed AST duplicate mapped ID')
            rows[ident] = text[start.end()+match.end():start.end()+matches[i+1].start() if i+1<len(matches) else stop]
    need(set(rows) == set(wanted), 'typed AST missing mapped IDs '+section)
    return rows


def typed_bindings(witness, typed):
    relation = witness['required_relations']
    def refs(text, kind):
        return [int(v) for v in re.findall(kind+r'\((\d+)\)',text)]
    def quals(text):
        pattern = r'CQualTypeId \{\s+qualifiers: Qualifiers \{\s+is_const: (true|false),\s+is_restrict: (true|false),\s+is_volatile: (true|false),\s+\},\s+ctype: CTypeId\((\d+)\),\s+\}'
        return [dict(zip(('const','restrict','volatile','type_id'),(a=='true',b=='true',c=='true',int(d)))) for a,b,c,d in re.findall(pattern,text)]
    types = {r['type_id']:r for r in relation['types']}
    tt = typed_table(typed,'c_types','CTypeId',types)
    typedefs = [r['declaration'] for r in types.values() if r['kind']=='typedef']
    ts = typed_table(typed,'source_typedef_types','CDeclId',typedefs)
    arrays = [r['type_id'] for r in types.values() if r['kind']=='array']
    ta = typed_table(typed,'source_array_elements','CTypeId',arrays)
    declarations = {r['declaration'] for r in relation['native_records']+relation['builtin_declarations']}
    declarations |= {r['declaration'] for r in relation['enum_owners']}
    declarations |= {v['declaration'] for r in relation['enum_owners'] for v in r['variants']}
    td = typed_table(typed,'c_decls','CDeclId',declarations)
    for ident, row in types.items():
        chunk, kind = tt[ident], row['kind']
        if kind in ('elaborated','paren','attributed','decayed'):
            need('kind: '+kind.title()+'(' in chunk and refs(chunk,'CTypeId') == [row['inner']], 'typed source alias edge')
        elif kind == 'typedef':
            need('kind: Typedef(' in chunk and refs(chunk,'CDeclId') == [row['declaration']] and quals(ts[row['declaration']]) == [row['original']], 'typed typedef/CVR')
        elif kind == 'array':
            need('kind: ConstantArray(' in chunk and quals(ta[ident]) == [row['element']] and refs(chunk,'CTypeId') == [row['element']['type_id']] and re.search(r'CTypeId\(\d+\),\s+'+str(row['length'])+',',chunk), 'typed array bounds/CVR')
        elif kind == 'pointer':
            need('kind: Pointer(' in chunk and quals(chunk) == [row['pointee']], 'typed pointer/CVR')
        elif kind == 'function':
            need('kind: Function(' in chunk and quals(chunk) == [row['return']]+row['parameters'], 'typed function signature')
            need(re.findall(r'^                (true|false),$',chunk,re.M) == [str(row[k]).lower() for k in ('variadic','noreturn','prototype')] and '\n                '+row['abi']+',\n' in chunk, 'typed function ABI/flags')
        elif kind in ('struct','enum'):
            need('kind: '+kind.title()+'(' in chunk and refs(chunk,'CDeclId') == [row['declaration']], 'typed record/enum identity')
        elif kind == 'builtin_function':
            need('kind: BuiltinFn,' in chunk and row['unproved'] == 'BuiltinFn requires a native endpoint relation', 'typed BuiltinFn remains unproved')
        else:
            need('kind: '+kind+',' in chunk, 'typed scalar kind')
    nc = typed_table(typed,'native_cursor_types','CDeclId',{r['declaration'] for r in relation['cursors']})
    for cursor in relation['cursors']:
        need(quals(nc[cursor['declaration']]) == [cursor['declared'],cursor['builtin']], 'typed declared/builtin cursor relation')
    for native in relation['native_records']:
        need(native == dict(declaration=native['declaration'],origin='ASTContext.getVaListTagDecl',kind='struct',complete=True,size=24,alignment=8), 'native cursor origin/layout')
        chunk = td[native['declaration']]
        need('platform_byte_size: 24,' in chunk and 'platform_alignment: 8,' in chunk, 'typed native layout')
    for enum in relation['enum_owners']:
        owner = td[enum['declaration']].split('variants:',1)[1].split('underlying_type_id:',1)[0]
        for variant in enum['variants']:
            need(variant['declaration'] in refs(owner,'CDeclId') and ('I(' if variant['signed'] else 'U(') in td[variant['declaration']], 'typed enum membership/sign')
    bi = typed_table(typed,'cursor_builtin_identity','CDeclId',{r['declaration'] for r in relation['builtin_declarations']})
    for builtin in relation['builtin_declarations']:
        chunk = bi[builtin['declaration']]
        need(re.search(r'\b'+str(builtin['builtin_id'])+r',',chunk) and '"'+builtin['semantic']+'"' in chunk, 'typed builtin semantic identity')
    endpoints = {r['expression'] for r in relation['builtin_endpoints']} | {r['reference'] for r in relation['builtin_endpoints']}
    te = typed_table(typed,'c_exprs','CExprId',endpoints)
    for endpoint in relation['builtin_endpoints']:
        need(quals(te[endpoint['expression']]) == [endpoint['output']] and quals(te[endpoint['reference']]) == [endpoint['input']], 'typed builtin endpoint CVR')
    target = next(f for f in witness['functions'] if f['symbol'].get('static') == SYMBOL)
    bodies = typed_table(typed,'c_stmts','CStmtId',{target['body']})
    need(refs(bodies[target['body']],'CStmtId') == [r['id'] for r in target['statements']], 'typed target statement order')
    return {'required_types':len(types),'builtin_endpoints':len(endpoints)//2,'native_cursors':len(nc)}


def boundary_controls(transport, witness):
    import full_compiler as F
    from closed_variadic_plan import PlanError
    rejected = []
    def reject(label, action):
        try:
            action()
        except (ValueError, PlanError, KeyError):
            rejected.append(label)
        else:
            raise ValueError('malformed admission accepted ' + label)
    receipt = transport.receipt
    pair = next(p for p in receipt['pairs'] if p['unit'] == witness['unit'])
    symbol = {'unit':pair['unit'], 'static':SYMBOL}
    with transport.context():
        for label, edit in (
            ('receipt schema', lambda r:r.update(schema=2)),
            ('receipt digest', lambda r:r['files'].update({r['database']:'0'*64})),
            ('TU command', lambda r:r['pairs'][0]['compile_command'].update(file='/wrong.c')),
            ('CBOR coverage', lambda r:r['pairs'][0]['files'].pop(r['pairs'][0]['cbor'])),
            ('typed AST digest', lambda r:r['pairs'][0]['files'].update({r['pairs'][0]['typed_ast']:'0'*64})),
        ):
            bad = copy.deepcopy(receipt)
            edit(bad)
            reject(label, lambda:F.prove_bound_cursor_witness(bad,symbol))
        for label, edit in (
            ('native cached bytes', lambda n:n['buffers'][0].update(sha256='0'*64)),
            ('native target', lambda n:n.update(target='wrong')),
            ('native invocation', lambda n:n.update(adjusted_driver_argv=[])),
            ('native lexer ledger', lambda n:n.update(lexer_events=[])),
        ):
            native = copy.deepcopy(witness['native_inputs'])
            edit(native)
            bad = dict(witness,native_inputs=native)
            reject(label, lambda:F.verify_native_cursor_inputs(bad,pair['unit'],pair['target'],pair['compile_command']))
        for label, suffix in (
            ('tool binary', '/bin/c2rust-transpile'),
            ('tool source', '/source-evidence/c2rust-applied-source/c2rust-transpile/src/c_ast/closed_variadic.rs'),
            ('tool source receipt', '/source-receipt.json'),
        ):
            root = receipt['tool'].removesuffix('/bin/c2rust-transpile')
            path = root+suffix
            original = transport.files[path]
            raw = transport.read(path)
            transport.files[path] = json.dumps(dict(loads(raw),patch_sha256='0'*64)).encode() if label == 'tool source receipt' else raw+b' '
            try:
                reject(label,lambda:F.verify_cursor_tool(F.Path(receipt['tool'])))
            finally:
                transport.files[path] = original
    return rejected


def focused_proof_controls(inv, witness):
    import inspect
    import test_closed_variadic_plan as T
    source = inspect.getsource(T.exercise_actual_cursor_payload)
    anchor = '    for label, mutate in mutations:'
    need(source.count(anchor) == 1, 'frozen bounded control loop anchor')
    source = source.replace(anchor, "    for label, mutate in [(n,m) for n,m in mutations if n.startswith(('incoming-outside-closure-type-collision-', 'builtin-input-outside-closure-type-collision-'))]:")
    namespace = dict(T.__dict__)
    exec(compile(source, '<bounded frozen actual-payload helper>', 'exec'),namespace)
    result = namespace['exercise_actual_cursor_payload'](inv,witness)
    need(len(result['mutations_rejected']) == 5 and result['alpha_renaming'] == result['fresh_incoming_type_ids'] == 'accepted', 'five collisions/total bijection/fresh IDs')
    return result


def extract_function(source, anchor):
    matches = list(re.finditer(r'^' + re.escape(anchor), source, re.M))
    need(len(matches) == 1, 'unique function anchor')
    start = matches[0].start()
    opening = source.index('{', matches[0].end())
    depth, i = 1, opening + 1
    while i < len(source):
        if source.startswith('//', i):
            i = source.index('\n', i) + 1
            continue
        if source.startswith('/*', i):
            i = source.index('*/', i + 2) + 2
            continue
        if source[i] in ('"', "'"):
            quote = source[i]
            i += 1
            while i < len(source) and source[i] != quote:
                i += 2 if source[i] == '\\' else 1
            need(i < len(source), 'unterminated source literal')
        elif source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
            if depth == 0:
                return source[start:i+1]
        i += 1
    raise ValueError('unterminated function')


EDITS = (
    ('mut c2rust_args: ...', 'mut tail: ::core::ffi::c_uint'),
    ('    let mut args: ::core::ffi::VaList;\n    args = c2rust_args.clone();\n', ''),
    ('    vsnprintf(\n', '    snprintf(\n'),
    ('        args.clone(),\n', '        tail,\n'),
)


def lower(original):
    need(sha(original.encode()) == SNAPSHOTS[1], 'unapproved generated target snapshot')
    result = original
    for old, new in EDITS:
        need(result.count(old) == 1, 'exact permitted edit')
        result = result.replace(old, new, 1)
    need(not any(s in result for s in ('VaList', 'c2rust_args', 'vsnprintf', '...','#![feature')), 'unstable isolated target')
    inverse = result
    for old, new in reversed(EDITS):
        if new:
            need(inverse.count(new) == 1, 'inverse edit anchor')
            inverse = inverse.replace(new, old, 1)
        else:
            anchor = '    vsnprintf(\n'
            need(inverse.count(anchor) == 1, 'inverse cursor anchor')
            inverse = inverse.replace(anchor, old + anchor, 1)
    need(inverse == original, 'independent inverse reconstruction')
    need(result[result.index('    name['):] == original[original.index('    name['):], 'NUL and downstream bytes changed')
    return result


def sources(z):
    c, r = z.read(C_PATH).decode(), z.read(R_PATH).decode()
    cf = extract_function(c, 'static void ' + SYMBOL + '(')
    rf = extract_function(r, 'unsafe extern "C" fn ' + SYMBOL + '(')
    need((sha(cf.encode()), sha(rf.encode())) == SNAPSHOTS, 'frozen exact target snapshots')
    caller_c = SYMBOL + '(builder, struct_id, j, "cb%u", reg_idx);'
    caller_r = '''vkd3d_spirv_build_op_member_name(
                builder,
                struct_id,
                j as uint32_t,
                b"cb%u\\0".as_ptr() as *const ::core::ffi::c_char,
                reg_idx,
            );'''
    need(c.count(caller_c) == r.count(caller_r) == 1, 'unchanged unique original caller')
    need(len(re.findall(r'\b' + SYMBOL + r'\b', c)) == len(re.findall(r'\b' + SYMBOL + r'\b', r)) == 2, 'additional target reference')
    declaration = re.findall(r'    unsafe fn snprintf\([\s\S]*?\) -> ::core::ffi::c_int;', r)
    need(len(declaration) == 1 and '...' in declaration[0] and 'VaList' not in declaration[0], 'existing C formatter declaration')
    raw_w = z.read('cursor-witness/raw/src/vkd3d_shader/spirv.rs').decode()
    need(extract_function(raw_w, 'unsafe extern "C" fn ' + SYMBOL + '(') == rf, 'bound export/generated target differs')
    return {'original.c': cf, 'original.rs': rf, 'lowered.rs': lower(rf),
            'snprintf.rs': declaration[0], 'caller.c': caller_c, 'caller.rs': caller_r}


def cases():
    values = {0, 1, MASK}
    for base, maximum in ((10, 10), (2, 32)):
        for k in range(maximum + 1):
            for d in (-1, 0, 1):
                v = base**k + d
                if 0 <= v <= MASK:
                    values.add(v)
    rows = []
    for i, v in enumerate(sorted(values)):
        q = (len(('cb' + str(v)).encode()) + 1 + 3) // 4
        rows.append({'builder': i % 3, 'type': (0x80000000 + i) & MASK,
                     'member': (MASK-i) & MASK, 'tail': v, 'q': q,
                     'w': ((3+q) << 16 | 6) & MASK, 'domain': 'normal'})
    for q in (0, 1, 2, 3, 4, MASK-3, MASK-2, MASK-1, MASK):
        for w in (0, 1, 0x80000000, MASK):
            rows.append({'builder': len(rows)%3, 'type': 7, 'member': 91,
                         'tail': MASK, 'q': q, 'w': w, 'domain': 'seam_stress'})
    validate_cases(rows)
    return rows


def validate_cases(rows):
    need(isinstance(rows, list) and rows, 'missing cases')
    for row in rows:
        need(set(row) == {'builder','type','member','tail','q','w','domain'}, 'case fields')
        need(all(type(row[k]) is int and 0 <= row[k] <= MASK for k in ('type','member','tail','q','w')), 'case UInt32 overflow/type')
        need(type(row['builder']) is int and 0 <= row['builder'] < 3, 'bounded process-local builder key')
        need(row['domain'] in ('normal','seam_stress'), 'case domain')
        if row['domain'] == 'normal':
            need(row['q'] == (len('cb'+str(row['tail']))+4)//4 and 1 <= row['q'] <= 4, 'normal word count')


def case_input(rows):
    validate_cases(rows)
    return ''.join(' '.join(str(r[k]) for k in ('builder','type','member','tail','q','w'))+'\n' for r in rows).encode()


def expected(rows, mutant=None):
    validate_cases(rows)
    need(mutant in (None, 'tail_plus_one', 'exchange_ids', 'missing_word', 'duplicate_word', 'ignore_q', 'ignore_w'), 'known semantic mutant')
    lines = ['prefix|0|17', 'prefix|1|29', 'prefix|2|43']
    for i, r in enumerate(rows):
        tail = (r['tail'] + (mutant == 'tail_plus_one')) & MASK
        name = ('cb'+str(tail)).encode().hex() + '00'
        b, q = r['builder'], r['q']
        used_q = 1 if mutant == 'ignore_q' else q
        words = [0 if mutant == 'ignore_w' else r['w'], r['type'], r['member']]
        if mutant == 'exchange_ids':
            words[1], words[2] = words[2], words[1]
        elif mutant == 'missing_word':
            words.pop()
        elif mutant == 'duplicate_word':
            words.append(r['member'])
        lines += [f'{i}|count|{name}|{q}', f'{i}|opcode|6|{(3+used_q) & MASK}|{r["w"]}']
        lines += [f'{i}|word|{b}|{v}' for v in words]
        lines += [f'{i}|string|{b}|{name}|{used_q}', f'{i}|suppliers|1|1|1|1|1']
    return ('\n'.join(lines)+'\n').encode()


def verify_execution(root, key, record, rows, generated):
    need(set(record) == {'argv','start','end','exit_code','stdout','stderr','environment',
                        'removed_environment','compile','compile_exit_code','binary',
                        'binary_sha256','source','source_sha256','input_sha256'}, 'execution record fields')
    source, mode = key.rsplit('-',1)
    need(source in generated and mode in ('normal','optimized'), 'execution identity')
    need(all(type(v) is int and v == 0 for v in (record['exit_code'],record['compile_exit_code'],record['compile']['exit_code'])), 'binary execution/compile rc')
    need(record['binary'] == key+'.bin' and record['source'] == source, 'source/binary names')
    for field in ('binary','source','stdout','stderr'):
        need(safe_name(record[field]) and '/' not in record[field], 'execution safe path')
    binary = (root/record['binary']).read_bytes()
    need(record['binary_sha256'] == sha(binary), 'binary binding')
    need(binary[:6] == b'\x7fELF\x02\x01' and int.from_bytes(binary[18:20],'little') == 62, 'Linux x64 ELF binary')
    need(record['source_sha256'] == sha(generated[source].encode()) == sha((root/source).read_bytes()), 'execution source binding')
    need(record['input_sha256'] == sha(case_input(rows)) and record['argv'] == ['./'+record['binary']], 'execution invocation')
    for stage in (record, record['compile']):
        need(stage['start'] <= stage['end'] and stage['start'].endswith('+00:00'), 'execution UTC timestamps')
        need(stage['removed_environment'] == ['RUSTC_BOOTSTRAP','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS'], 'stable environment cleanup')
        env = stage['environment']
        need(env['GITHUB_ACTIONS'] == 'true' and env['RUNNER_OS'] == 'Linux' and env['RUNNER_ARCH'] == 'X64', 'hosted Linux x64 identity')
        need(not any(k in env for k in stage['removed_environment']), 'bootstrap/flags present')
        need(safe_name(stage['stdout']) and safe_name(stage['stderr']), 'stage output safe paths')
        need((root/stage['stdout']).is_file() and (root/stage['stderr']).is_file(), 'raw stage output missing')
    command = record['compile']['argv']
    expected_command = ['cc','-std=c11','-D_POSIX_C_SOURCE=200809L', '-O2' if mode=='optimized' else '-O0',source,'-o',record['binary']] if source.endswith('.c') else ['rustc','+1.95.0','--edition=2024','--crate-name','member_name_pilot','-C','opt-level=3' if mode=='optimized' else 'opt-level=0',source,'-o',record['binary']]
    need(command == expected_command, 'exact compiler argv')
    output = (root/record['stdout']).read_bytes()
    mutant = None if source in ('oracle.c','stable.rs') else source.removesuffix('.rs')
    need(output == expected(rows, mutant), 'strict exact trace/script consumption ' + key)
    if mutant:
        need(output != expected(rows), 'compiled semantic mutant survived ' + key)
    return sum(expected([r], mutant) != expected([r]) for r in rows) if mutant else 0


C_DRIVER = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define SpvOpMemberName 6
_Static_assert(sizeof(unsigned int)==4 && sizeof(uint32_t)==4 && sizeof(void*)==8, "Linux x64 widths");
struct vkd3d_spirv_stream { unsigned key; };
struct vkd3d_spirv_builder { struct vkd3d_spirv_stream debug_stream; };
static unsigned idx, scripted_q, scripted_w, suppliers[5];
static void hexname(const char *s) { size_t n=strnlen(s,1024); if(n==1024) exit(12); for(size_t i=0;i<=n;i++) printf("%02x",(unsigned char)s[i]); }
static unsigned vkd3d_spirv_string_word_count(const char *s) { printf("%u|count|",idx);hexname(s);printf("|%u\n",scripted_q);return scripted_q; }
static unsigned vkd3d_spirv_opcode_word(unsigned op,unsigned n) { printf("%u|opcode|%u|%u|%u\n",idx,op,n,scripted_w);return scripted_w; }
static void vkd3d_spirv_build_word(struct vkd3d_spirv_stream *s,uint32_t v) {printf("%u|word|%u|%u\n",idx,s->key,v);}
static void vkd3d_spirv_build_string(struct vkd3d_spirv_stream *s,const char *v,unsigned n) {printf("%u|string|%u|",idx,s->key);hexname(v);printf("|%u\n",n);}
@TARGET@
static struct vkd3d_spirv_builder *sb(struct vkd3d_spirv_builder *p) {suppliers[0]++;return p;}
static uint32_t su(unsigned k,uint32_t v) {suppliers[k]++;return v;}
static const char *sf(void) {suppliers[3]++;return "cb%u";}
int main(void) {
 struct vkd3d_spirv_builder builders[3]={{{0}},{{1}},{{2}}};unsigned b,t,m,v;
 puts("prefix|0|17\nprefix|1|29\nprefix|2|43");
 while(1) {int n=scanf("%u %u %u %u %u %u",&b,&t,&m,&v,&scripted_q,&scripted_w);if(n==EOF)break;if(n!=6||b>=3)return 10;
 memset(suppliers,0,sizeof(suppliers));
 vkd3d_spirv_build_op_member_name(sb(&builders[b]),su(1,t),su(2,m),sf(),su(4,v));
 printf("%u|suppliers|%u|%u|%u|%u|%u\n",idx,suppliers[0],suppliers[1],suppliers[2],suppliers[3],suppliers[4]);idx++;
 }return 0;
}
'''

R_DRIVER = r'''
#![allow(non_camel_case_types, non_upper_case_globals, unused_mut, unused_assignments, dead_code)]
use std::io::Read;
type uint32_t = u32;
type size_t = usize;
struct vkd3d_spirv_stream { key: u32 }
struct vkd3d_spirv_builder { debug_stream: vkd3d_spirv_stream }
struct SpvOp_;
impl SpvOp_ { const SpvOpMemberName: u32 = 6; }
unsafe extern "C" {
@DECL@
}
static mut IDX: u32 = 0;
static mut Q: u32 = 0;
static mut W: u32 = 0;
static mut SUPPLIERS: [u32;5] = [0;5];
unsafe fn hexname(p: *const std::ffi::c_char) -> String {
 let mut result=String::new();
 for i in 0..1024 { let c=unsafe{*p.add(i)} as u8;result.push_str(&format!("{c:02x}"));if c==0{return result;} }
 std::process::exit(12)
}
unsafe fn vkd3d_spirv_string_word_count(p:*const std::ffi::c_char)->u32 {unsafe{let i=IDX;let q=Q;println!("{i}|count|{}|{q}",hexname(p));q}}
unsafe fn vkd3d_spirv_opcode_word(op:u32,n:u32)->u32 {unsafe{let i=IDX;let w=W;println!("{i}|opcode|{op}|{n}|{w}");w}}
unsafe fn vkd3d_spirv_build_word(s:*mut vkd3d_spirv_stream,v:u32) {unsafe{let i=IDX;println!("{i}|word|{}|{v}",(*s).key);}}
unsafe fn vkd3d_spirv_build_string(s:*mut vkd3d_spirv_stream,p:*const std::ffi::c_char,n:u32) {unsafe{let i=IDX;println!("{i}|string|{}|{}|{n}",(*s).key,hexname(p));}}
@TARGET@
unsafe fn sb(p:*mut vkd3d_spirv_builder)->*mut vkd3d_spirv_builder {unsafe{SUPPLIERS[0]+=1;}p}
unsafe fn su(k:usize,v:u32)->u32 {unsafe{SUPPLIERS[k]+=1;}v}
unsafe fn sf()->*const std::ffi::c_char {unsafe{SUPPLIERS[3]+=1;}b"cb%u\0".as_ptr().cast()}
fn main() {
 let mut input=String::new();std::io::stdin().read_to_string(&mut input).unwrap();
 let mut builders=[vkd3d_spirv_builder{debug_stream:vkd3d_spirv_stream{key:0}},vkd3d_spirv_builder{debug_stream:vkd3d_spirv_stream{key:1}},vkd3d_spirv_builder{debug_stream:vkd3d_spirv_stream{key:2}}];
 println!("prefix|0|17\nprefix|1|29\nprefix|2|43");
 for (i,line) in input.lines().enumerate() {let a:Vec<u32>=line.split_whitespace().map(|s|s.parse().unwrap()).collect();if a.len()!=6||a[0]>=3{std::process::exit(10);}
 unsafe {IDX=i.try_into().unwrap();Q=a[4];W=a[5];SUPPLIERS=[0;5];
 vkd3d_spirv_build_op_member_name(sb(&raw mut builders[a[0] as usize]),su(1,a[1]),su(2,a[2]),sf(),su(4,a[3]));
 let s=SUPPLIERS;println!("{i}|suppliers|{}|{}|{}|{}|{}",s[0],s[1],s[2],s[3],s[4]);}
 }
}
'''


def programs(src):
    c = C_DRIVER.replace('@TARGET@', src['original.c'])
    r = R_DRIVER.replace('@DECL@', src['snprintf.rs']).replace('@TARGET@', src['lowered.rs'])
    mutants = {
        'tail_plus_one': ('        tail,\n', '        tail.wrapping_add(1),\n'),
        'exchange_ids': ('vkd3d_spirv_build_word(stream, type_id);\n    vkd3d_spirv_build_word(stream, member);', 'vkd3d_spirv_build_word(stream, member);\n    vkd3d_spirv_build_word(stream, type_id);'),
        'missing_word': ('    vkd3d_spirv_build_word(stream, member);\n', ''),
        'duplicate_word': ('    vkd3d_spirv_build_word(stream, member);\n', '    vkd3d_spirv_build_word(stream, member);\n    vkd3d_spirv_build_word(stream, member);\n'),
        'ignore_q': ('name_size = vkd3d_spirv_string_word_count(&raw mut name as *mut ::core::ffi::c_char);', 'name_size = vkd3d_spirv_string_word_count(&raw mut name as *mut ::core::ffi::c_char);\n    name_size = 1;'),
        'ignore_w': ('    vkd3d_spirv_build_word(\n        stream,\n        vkd3d_spirv_opcode_word(', '    vkd3d_spirv_build_word(\n        stream,\n        { let _ignored = vkd3d_spirv_opcode_word('),
    }
    out = {'oracle.c': c, 'stable.rs': r}
    for name, (old, new) in mutants.items():
        need(r.count(old) == 1, 'mutant exact anchor ' + name)
        value = r.replace(old, new, 1)
        if name == 'ignore_w':
            anchor = '            (3 as ::core::ffi::c_uint).wrapping_add(name_size),\n        ),'
            need(value.count(anchor) == 1, 'ignore w closing anchor')
            value = value.replace(anchor, '            (3 as ::core::ffi::c_uint).wrapping_add(name_size),\n        ); 0 },', 1)
        out[name+'.rs'] = value
    return out


def admission(paths):
    z = archive(paths['all24'], 'all24')
    setup = archive(paths['setup'], 'setup')
    input_zip = archive(paths['input'], 'input')
    bundle = input_zip.read('prepared.tar.gz')
    need(setup.read('bundle-sha256.txt').decode().split()[0] == sha(bundle), 'prepared bundle digest')
    with tarfile.open(fileobj=io.BytesIO(bundle), mode='r:gz') as tar:
        members = tar.getmembers()
        need(len({m.name for m in members}) == len(members), 'duplicate prepared tar member')
        by_name = {m.name:m for m in members}
        for m in members:
            need(safe_name(m.name), 'unsafe prepared tar path')
            if m.issym():
                target = posixpath.normpath(posixpath.join(posixpath.dirname(m.name),m.linkname))
                need(safe_name(m.linkname) and target in by_name and by_name[target].isfile(), 'unsafe prepared tar symlink')
            else:
                need(m.isfile() or m.isdir(), 'unsafe prepared tar type')
        prepared = {m.name:tar.extractfile(m).read() for m in members if m.isfile()}
        need(all(len(prepared[m.name]) == m.size for m in members if m.isfile()), 'prepared tar lengths')
    transport = Transport(z, setup)
    for name, raw in transport.files.items():
        if '/vkd3d-probe/prepared/' in name:
            member = 'prepared/'+name.split('/vkd3d-probe/prepared/',1)[1]
            need(prepared[member] == transport.read(name), 'prepared/native cached input binding')
    result, witness, inv = transport.admit()
    result['boundary_controls_rejected'] = boundary_controls(transport,witness)
    result['focused_actual_proof_controls'] = focused_proof_controls(inv,witness)
    src = sources(z)
    return result, src


def tooling_sources():
    folder = Path(__file__).resolve().parent
    names = ('member_name_lowering.py','test_member_name_lowering.py','full_compiler.py',
             'closed_variadic_plan.py','apply_c2rust_patch.py','test_closed_variadic_plan.py',
             'patches/c2rust-win64-abi.patch')
    out = {'tooling/'+name:(folder/name).read_bytes() for name in names}
    out['tooling/member-name-lowering-pilot.yml'] = (folder.parent.parent/'.github/workflows/member-name-lowering-pilot.yml').read_bytes()
    return out


def manifest(root):
    return {str(p.relative_to(root)): sha(p.read_bytes()) for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'seal.json'}


def verify_command_receipts(root, identities, records):
    commands = {name if name == 'pinned-rustc-path' else name+'-identity': record
                for name, record in identities.items()}
    for key, record in records.items():
        commands[key+'-compile'] = record['compile']
        commands[key+'-run'] = {field: record[field] for field in record['compile']}
    need({p.name for p in root.glob('*.command.json')} == {stem+'.command.json' for stem in commands},
         'individual command receipt coverage')
    for stem, command in commands.items():
        receipt = loads((root/(stem+'.command.json')).read_bytes())
        need(set(receipt) == {'status','command','failure','stdout_sha256','stderr_sha256'}, 'command receipt fields')
        need(receipt['status'] == 'succeeded' and receipt['failure'] is None
             and type(command['exit_code']) is int and command['exit_code'] == 0,
             'unsuccessful command receipt')
        need(receipt['command'] == command, 'aggregate/individual command receipt differs')
        for field in ('stdout','stderr'):
            need(command[field] == stem+'.'+field, 'command output identity')
            need(receipt[field+'_sha256'] == sha((root/command[field]).read_bytes()), 'command output hash')


def replay(root, paths):
    before = manifest(root) if root else None
    proof, src = admission(paths)
    rows = cases()
    generated = programs(src)
    result = {'scope': 'dependency_call_trace', 'admission': proof, 'cases': len(rows),
              'actual_compiled_pilot': 'UNRUN', 'source_sha256': {k:sha(v.encode()) for k,v in generated.items()}}
    if root:
        seal = loads((root/'seal.json').read_bytes())
        for name, raw in tooling_sources().items():
            need((root/name).read_bytes() == raw, 'retained proof/runner source differs '+name)
        need(seal == before, 'bounded evidence seal differs')
        need(loads((root/'cases.json').read_bytes()) == rows, 'missing/changed cases')
        need((root/'input.txt').read_bytes() == case_input(rows), 'case input binding')
        for name, value in {**src, **generated}.items():
            need((root/name).read_bytes() == value.encode(), 'retained source differs ' + name)
        compiler = loads((root/'compilers.json').read_bytes())
        need(set(compiler['identities']) == {'rustc','cc','pinned-rustc-path'} and set(compiler['files']) == {'rustc','cc'}, 'compiler identity coverage')
        for identity in compiler['identities'].values():
            need(type(identity['exit_code']) is int and identity['exit_code'] == 0, 'compiler identity rc')
            need((root/identity['stdout']).is_file() and (root/identity['stderr']).is_file(), 'compiler identity output')
        version = (root/'rustc-identity.stdout').read_text()
        need('release: 1.95.0\n' in version and 'host: x86_64-unknown-linux-gnu\n' in version and 'nightly' not in version, 'retained pinned stable compiler')
        records = loads((root/'executions.json').read_bytes())
        need(set(records) == {name+'-'+mode for name in generated for mode in ('normal','optimized')}, 'execution coverage')
        verify_command_receipts(root, compiler['identities'], records)
        result['mutant_mismatch_cases'] = {key:verify_execution(root,key,record,rows,generated) for key,record in records.items()}
        result['actual_compiled_pilot'] = 'PASS retained Linux x64 normal/optimized executions'
        need(manifest(root) == before, 'replay wrote evidence')
    return result


def run_hosted(root, paths):
    import datetime
    import platform
    import subprocess
    import shutil
    need(sys.platform == 'linux' and platform.machine() == 'x86_64' and os.environ.get('GITHUB_ACTIONS') == 'true', 'hosted Linux x64 only')
    need(not root.exists(), 'hosted output must be fresh')
    proof, src = admission(paths)
    root.mkdir(parents=True)
    for name, raw in tooling_sources().items():
        path = root/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    env = dict(os.environ)
    for key in ('RUSTC_BOOTSTRAP','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS'):
        env.pop(key, None)
    env['LC_ALL'] = 'C'
    required_env = {k:env[k] for k in ('GITHUB_ACTIONS','GITHUB_SHA','RUNNER_OS','RUNNER_ARCH','PATH','LC_ALL')}
    need(env['RUNNER_OS'] == 'Linux' and env['RUNNER_ARCH'] == 'X64', 'runner identity')
    def run(argv, stem, stdin=None):
        start = datetime.datetime.now(datetime.timezone.utc).isoformat()
        output, errors, code, failure, caught = b'', b'', None, None, None
        try:
            process = subprocess.run(argv, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=root, env=env, timeout=120)
            output, errors, code = process.stdout, process.stderr, process.returncode
            status = 'succeeded' if code == 0 else 'failed'
            if code != 0:
                failure = {'kind':'nonzero_exit','message':str(code)}
        except (subprocess.TimeoutExpired, OSError) as error:
            caught = error
            status = 'timeout' if isinstance(error, subprocess.TimeoutExpired) else 'launch_error'
            failure = {'kind':status,'message':str(error)}
            if isinstance(error, subprocess.TimeoutExpired):
                output, errors = error.stdout or b'', error.stderr or b''
        command = {'argv':argv, 'start':start, 'end':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'exit_code':code, 'stdout':stem+'.stdout','stderr':stem+'.stderr','environment':required_env,
                   'removed_environment':['RUSTC_BOOTSTRAP','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS']}
        (root/command['stdout']).write_bytes(output)
        (root/command['stderr']).write_bytes(errors)
        (root/(stem+'.command.json')).write_text(json.dumps({'status':status,'command':command,'failure':failure,
            'stdout_sha256':sha(output),'stderr_sha256':sha(errors)},indent=2)+'\n')
        if caught is not None:
            raise caught
        return command
    identities = {}
    for name, argv in [('rustc',['rustc','+1.95.0','-vV']), ('cc',['cc','--version'])]:
        identities[name] = run(argv, name+'-identity')
        need(identities[name]['exit_code'] == 0, 'compiler identity')
    rust_version = (root/'rustc-identity.stdout').read_text()
    need('release: 1.95.0\n' in rust_version and 'host: x86_64-unknown-linux-gnu\n' in rust_version and 'nightly' not in rust_version, 'pinned stable compiler')
    identities['pinned-rustc-path'] = run(['rustup','which','--toolchain','1.95.0','rustc'],'pinned-rustc-path')
    need(identities['pinned-rustc-path']['exit_code'] == 0, 'pinned compiler path')
    pinned_rustc = Path((root/'pinned-rustc-path.stdout').read_text().strip())
    need(pinned_rustc.is_absolute() and pinned_rustc.is_file(), 'pinned compiler file')
    compiler_files = {}
    for name in ('cc','rustc'):
        p = pinned_rustc.resolve() if name == 'rustc' else Path(shutil.which(name)).resolve()
        compiler_files[name] = {'path':str(p), 'sha256':sha(p.read_bytes())}
    (root/'compilers.json').write_text(json.dumps({'identities':identities,'files':compiler_files},indent=2)+'\n')
    generated, rows = programs(src), cases()
    for name, value in {**src, **generated}.items():
        (root/name).write_text(value)
    (root/'cases.json').write_text(json.dumps(rows,indent=2)+'\n')
    (root/'admission.json').write_text(json.dumps(proof,indent=2)+'\n')
    data = case_input(rows)
    (root/'input.txt').write_bytes(data)
    records = {}
    for name in generated:
        for mode in ('normal','optimized'):
            key = name+'-'+mode
            binary = key+'.bin'
            argv = ['cc','-std=c11','-D_POSIX_C_SOURCE=200809L', '-O2' if mode=='optimized' else '-O0',name,'-o',binary] if name.endswith('.c') else ['rustc','+1.95.0','--edition=2024','--crate-name','member_name_pilot','-C','opt-level=3' if mode=='optimized' else 'opt-level=0',name,'-o',binary]
            compiled = run(argv,key+'-compile')
            need(compiled['exit_code'] == 0, 'hosted compile failed ' + key)
            executed = run(['./'+binary],key+'-run',data)
            need(executed['exit_code'] == 0, 'hosted execution failed ' + key)
            executed.update(compile=compiled,compile_exit_code=compiled['exit_code'],binary=binary,binary_sha256=sha((root/binary).read_bytes()),source=name,source_sha256=sha((root/name).read_bytes()),input_sha256=sha(data))
            records[key] = executed
    (root/'scope.json').write_text(json.dumps({'scope':'dependency_call_trace','proof_authorization':'witness_only','stable_lowering':'not_authorized','authentic_job_proof':False,'host':'Linux x64','limitations':['conditional helper correspondence','no allocator, padding, emitted-state, OOM or whole-translator acceptance','existing stable E0554 and bootstrap 46/48 result remain unresolved','other 32 variadic definitions excluded without modification']},indent=2)+'\n')
    (root/'executions.json').write_text(json.dumps(records,indent=2)+'\n')
    (root/'seal.json').write_text(json.dumps(manifest(root),indent=2)+'\n')
    return replay(root, paths)


def acquire(root, *, helper_inputs=False):
    import urllib.request
    need(os.environ.get('GITHUB_ACTIONS') == 'true' and sys.platform == 'linux', 'artifact acquisition is hosted-only')
    need(not root.exists(), 'acquisition output must be fresh')
    root.mkdir(parents=True)
    token = os.environ['GH_TOKEN']
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, message, headers, url):
            redirected = super().redirect_request(request,fp,code,message,headers,url)
            if redirected is not None:
                redirected.remove_header('Authorization')
            return redirected
    opener = urllib.request.build_opener(Redirect())
    for name in (('all24', 'setup') if helper_inputs else ARTIFACTS):
        ident, size, digest = ARTIFACTS[name]
        base = 'https://api.github.com/repos/geekjapan/MikuDanceStudio-J/actions/artifacts/'+str(ident)
        def fetch(url):
            request = urllib.request.Request(url,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
            with opener.open(request,timeout=120) as response:
                return response.read()
        metadata = loads(fetch(base))
        need(metadata['id'] == ident and metadata['size_in_bytes'] == size and metadata['digest'] == 'sha256:'+digest and metadata['workflow_run']['id'] == 40531027355 and metadata['workflow_run']['head_sha'] == BASE, 'fixed API artifact metadata')
        raw = fetch(base+'/zip')
        need(len(raw) == size and sha(raw) == digest, 'acquired fixed artifact bytes')
        (root/(name+'.zip')).write_bytes(raw)
        (root/(name+'-api.json')).write_text(json.dumps(metadata,indent=2)+'\n')
        archive(root/(name+'.zip'),name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path)
    parser.add_argument('--all24', type=Path)
    parser.add_argument('--setup', type=Path)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--replay', type=Path)
    parser.add_argument('--run-hosted', type=Path)
    parser.add_argument('--acquire', type=Path)
    parser.add_argument('--acquire-helper-inputs', type=Path)
    args = parser.parse_args()
    need(sum(x is not None for x in (args.replay,args.run_hosted,args.acquire,args.acquire_helper_inputs)) <= 1, 'exclusive operation')
    if args.acquire:
        acquire(args.acquire)
        return
    if args.acquire_helper_inputs:
        acquire(args.acquire_helper_inputs, helper_inputs=True)
        return
    paths = {k: getattr(args,k) or (args.artifacts/(k+'.zip') if args.artifacts else None) for k in ARTIFACTS}
    need(all(paths.values()), 'all three fixed artifact paths required')
    result = run_hosted(args.run_hosted,paths) if args.run_hosted else replay(args.replay,paths)
    print(json.dumps(result,sort_keys=True))


if __name__ == '__main__':
    main()
