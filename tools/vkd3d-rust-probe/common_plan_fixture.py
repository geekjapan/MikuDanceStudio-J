"""Test-only logical plan to schema-2 fixture encoder, independent of the Rust writer."""
import hashlib
import json
from pathlib import Path
from common_plan_report import TEXT_BYTES, PAGE_RECORDS, PAGE_BYTES, CATALOG_PAGES, UnknownLedger


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def text_records(text):
    data = text.encode('utf-8')
    if len(data) <= TEXT_BYTES:
        yield ['text', text]
        return
    parts = []
    start = 0
    while start < len(data):
        end = min(len(data), start + TEXT_BYTES)
        while end < len(data) and data[end] & 0xc0 == 0x80:
            end -= 1
        parts.append(data[start:end].decode())
        start = end
    yield ['text-start', len(text.encode()), len(parts)]
    for i, part in enumerate(parts):
        yield ['text-part', i, part]
    yield ['text-end']


def identity_records(identity, depth=0):
    yield ['record-identity', depth, identity['tag'] is not None, identity['line'], identity['column'], identity['owner'] is not None]
    yield from text_records(identity['kind'])
    if identity['tag'] is not None:
        yield from text_records(identity['tag'])
    yield from text_records(identity['file'])
    if identity['owner'] is not None:
        yield from identity_records(identity['owner'], depth + 1)


def type_records(typ, depth=0):
    variant, value = next(iter(typ['shape'].items()))
    row = ['type', depth, typ['qualifiers'], variant]
    if variant == 'Scalar':
        yield row + [value[1]]
        yield from text_records(value[0])
    elif variant == 'Pointer':
        yield row
        yield from type_records(value, depth + 1)
    elif variant == 'Array':
        yield row + [value[1]]
        yield from type_records(value[0], depth + 1)
    elif variant == 'Unknown':
        yield row + [value]
    elif variant == 'Function':
        yield row + [len(value['parameters']), value['variadic'], value['prototype'], value['noreturn']]
        yield from text_records(value['abi'])
        yield from type_records(value['result'], depth + 1)
        for i, parameter in enumerate(value['parameters']):
            yield ['parameter', i]
            yield from type_records(parameter, depth + 1)
    elif variant == 'Record':
        yield row + [value[k] for k in ('packed', 'manual_alignment', 'max_field_alignment', 'size', 'alignment')] + [len(value['fields'])]
        yield from identity_records(value['identity'])
        for i, field in enumerate(value['fields']):
            yield ['field', i] + [field[k] for k in ('bitfield_width', 'bit_offset', 'type_bitwidth', 'alignment')]
            yield from type_records(field['typ'], depth + 1)
    else:
        yield row + [value]


def plan_records(plan):
    for i, unit in enumerate(plan['units']):
        identity = unit['identity']
        yield ['unit', i, identity['widths'], unit['native_ast_exports'], unit['typed_imports'],
               len(unit['source_sha256']), len(unit['declarations']), len(unit['calls'])]
        for field in ('key', 'command', 'domain', 'source', 'ast_instance', 'target'):
            yield from text_records(identity[field])
        for j, (name, digest) in enumerate(sorted(unit['source_sha256'].items(),
                                               key=lambda item: tuple(part.encode('utf-8') for part in Path(item[0]).parts))):
            yield ['source', j, digest]
            yield from text_records(name)
        for j, d in enumerate(unit['declarations']):
            yield ['declaration', j, d['id'], d['key']['declaration'], d['definition'], d['cursor_parameters'],
                   len(d['aliases']), len(d['redeclarations']), len(d['visibility']), len(d['native_attributes']), d['blockers']]
            yield from text_records(d['key']['unit'])
            variant, symbol = next(iter(d['symbol'].items()))
            yield ['symbol-external' if variant == 'External' else 'symbol-internal']
            for field in (('domain', 'linker') if variant == 'External' else ('unit', 'name')):
                yield from text_records(symbol[field])
            yield from text_records(d['name'])
            yield from type_records(d['signature'])
            for tag, key in (('alias', 'aliases'), ('redeclaration', 'redeclarations'), ('visibility', 'visibility'), ('attribute', 'native_attributes')):
                for ordinal, item in enumerate(d[key]):
                    yield [tag, ordinal, item[0]] if tag == 'visibility' else [tag, ordinal]
                    if tag == 'redeclaration':
                        yield from type_records(item)
                    else:
                        yield from text_records(item[1] if tag == 'visibility' else item)
            yield ['declaration-end']
        for j, c in enumerate(unit['calls']):
            disposition = c['disposition']
            yield ['call', j, c['id'], c['key']['expression'], c['owner']['declaration'] if c['owner'] else None,
                   c['callee_expression'], c['direct'], len(c['arguments']), len(c['promoted_arguments']),
                   'Existing' if disposition == 'Existing' else next(iter(disposition)),
                   [] if disposition == 'Existing' else next(iter(disposition.values()))]
            yield from text_records(c['key']['unit'])
            if c['owner']:
                yield from text_records(c['owner']['unit'])
            for ordinal, argument in enumerate(c['arguments']):
                yield ['argument', ordinal, argument]
            for ordinal, typ in enumerate(c['promoted_arguments']):
                yield ['promoted', ordinal]
                yield from type_records(typ)
            yield ['call-end']
        yield ['unit-end']


def write_records(root, records, units=1, page_records=PAGE_RECORDS):
    root = Path(root)
    folder = root / 'closed-variadic-plan'
    folder.mkdir()
    descriptors = []
    count = total_bytes = 0
    page = []
    page_bytes = 64
    def write(name, value, first, count):
        nonlocal total_bytes
        raw = encode(value)
        (root / name).write_bytes(raw)
        total_bytes += len(raw)
        return dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), first=first, count=count)
    def close_page():
        name = f'closed-variadic-plan/page-{len(descriptors):08}.json'
        descriptors.append(write(name, dict(schema=2, first=count - len(page), records=page), count - len(page), len(page)))
    for record in records:
        size = len(encode(record)) + 1
        if page and (len(page) == page_records or page_bytes + size > PAGE_BYTES):
            close_page()
            page = []
            page_bytes = 64
        page.append(record)
        page_bytes += size
        count += 1
    if page:
        close_page()
    catalogs = []
    for i in range(0, len(descriptors), CATALOG_PAGES):
        pages = descriptors[i:i + CATALOG_PAGES]
        name = f'closed-variadic-plan/catalog-{len(catalogs):08}.json'
        catalogs.append(write(name, dict(schema=2, first=i, pages=pages), i, len(pages)))
    index = dict(schema=2, logical_schema=1, status='ClosedDiagnosticPlan', lowering='not_authorized', units=units,
                 records=count, pages=len(descriptors), bytes=total_bytes, catalogs=catalogs)
    (root / 'closed-variadic-plan.json').write_bytes(encode(index))
    return index


def fixture_ledger(definitions):
    ledger = UnknownLedger()
    for definition in definitions:
        if 'UnknownSignature' not in definition.get('blockers', ['UnknownSignature']):
            continue
        refs = []
        for field in ('unit', 'name'):
            data = definition[field].encode()
            key = ledger.db.execute('INSERT INTO text(bytes,sha) VALUES(?,?)', (len(data), hashlib.sha256(data).digest())).lastrowid
            for i in range(0, len(data), TEXT_BYTES):
                ledger.db.execute('INSERT INTO chunk VALUES(?,?,?)', (key, i // TEXT_BYTES, data[i:i + TEXT_BYTES]))
            refs.append(key)
        ledger.db.execute('INSERT INTO unknown VALUES(?,?)', refs)
    return ledger
