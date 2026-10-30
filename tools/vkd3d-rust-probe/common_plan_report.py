"""Bounded schema-2 common-plan records and complete incremental validation."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile

JSON_BYTES = 8 * 1024 * 1024
PAGE_BYTES = 4 * 1024 * 1024
RECORD_BYTES = 64 * 1024
TEXT_BYTES = 8192
PAGE_RECORDS = CATALOG_PAGES = 4096
MEMBERS = 200000
TOTAL_BYTES = 32 * 1024**3
RECORDS = TOTAL_BYTES // 2
BLOCKERS = ('CursorDataflowUnproved', 'UnknownSignature', 'SignatureMismatch', 'MultipleDefinitions',
            'ExternalUnresolved', 'Exported', 'AliasUnresolved', 'AliasCycle', 'AddressEscape', 'IndirectCall',
            'ExportPolicyUnknown', 'CallOwnerUnproved', 'UnknownAttributes', 'MissingRedeclarationEvidence')
ISSUES = frozenset(('MissingType', 'MissingTypedef', 'Cycle', 'Depth', 'Attributed', 'MissingArrayElement',
                    'MissingRecord', 'RecordScope', 'Unsupported', 'MissingCharSignedness'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def uint(value, maximum=2**64 - 1):
    return type(value) is int and 0 <= value <= maximum


def optional_uint(value):
    return value is None or uint(value)


def digest(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate report key')
        result[key] = value
    return result


def exact(value, keys):
    require(type(value) is dict and set(value) == set(keys), 'report object fields differ')


def file_seal(path, limit):
    require(not path.is_symlink() and path.is_file(), 'report file is missing or a symlink')
    length = path.stat().st_size
    require(0 < length <= limit, 'report file byte bound')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        observed = 0
        for chunk in iter(lambda: stream.read(65536), b''):
            observed += len(chunk)
            require(observed <= limit, 'report file byte bound')
            h.update(chunk)
    require(observed == length and path.stat().st_size == length, 'report changed during sealing')
    return dict(bytes=length, sha256=h.hexdigest())


def report_members(root):
    require(not root.is_symlink() and root.is_dir(), 'report root is not a directory')
    folder = root / 'closed-variadic-plan'
    require(not folder.is_symlink() and folder.is_dir(), 'report directory is missing or a symlink')
    result = {'closed-variadic-plan.json'}
    require(not (root / 'closed-variadic-plan.json').is_symlink(), 'symlink report index')
    for path in folder.iterdir():
        require(len(result) < MEMBERS and not path.is_symlink() and path.is_file(), 'report member bound or type')
        require(re.fullmatch(r'(?:page|catalog)-[0-9]{8}\.json', path.name) is not None, 'unexpected report member')
        result.add('closed-variadic-plan/' + path.name)
    return result


def seal_live_report(root, receipt):
    """Called after probe.run has waited and closed the producer's streams."""
    require(type(receipt) is dict and receipt.get('exit_code') == 0
            and type(receipt.get('exit_code')) is int and receipt.get('process_exit_code') == 0
            and type(receipt.get('process_exit_code')) is int
            and receipt.get('timed_out') is False and receipt.get('ended_utc'), 'producer is not closed successfully')
    names = report_members(root)
    seals = {}
    total = 0
    for name in sorted(names):
        limit = PAGE_BYTES if '/page-' in name else JSON_BYTES
        seals[name] = file_seal(root / name, limit)
        total += seals[name]['bytes']
        require(total <= TOTAL_BYTES, 'report total byte bound')
    return dict(authority='closed_producer_filesystem', files=seals)


def bounded_json(root, name, authority, limit, with_raw=False):
    require(name in authority, 'report member lacks external authority')
    expected = authority[name]
    exact(expected, ('bytes', 'sha256'))
    require(uint(expected['bytes'], limit) and expected['bytes'] > 0 and digest(expected['sha256']),
            'report external authority fields differ')
    path = root / name
    require(not path.is_symlink() and path.is_file(), 'report file is missing or a symlink')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) == expected['bytes'] <= limit and hashlib.sha256(raw).hexdigest() == expected['sha256'],
            'report external length or hash differs')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                       parse_constant=lambda _: require(False, 'nonfinite report number'))
    return (value, raw) if with_raw else value


class UnknownLedger:
    def __init__(self):
        self.directory = tempfile.TemporaryDirectory(prefix='common-plan-')
        self.db = sqlite3.connect(str(Path(self.directory.name) / 'facts.sqlite'))
        self.db.execute('PRAGMA cache_size=-2048')
        self.db.execute('PRAGMA temp_store=FILE')
        self.db.executescript('CREATE TABLE text(id INTEGER PRIMARY KEY, bytes INTEGER, sha BLOB);'
            'CREATE TABLE chunk(text INTEGER, ordinal INTEGER, data BLOB, PRIMARY KEY(text,ordinal));'
            'CREATE TABLE declaration(unit TEXT,id BLOB,PRIMARY KEY(unit,id));'
            'CREATE TABLE unknown(source INTEGER,name INTEGER);'
            'CREATE TABLE independent(source BLOB,name BLOB,PRIMARY KEY(source,name));')

    def close(self):
        self.db.close()
        self.directory.cleanup()

    def chunks(self, text):
        return (bytes(row[0]) for row in self.db.execute('SELECT data FROM chunk WHERE text=? ORDER BY ordinal', (text,)))

    def bytes(self, text, limit):
        size = self.db.execute('SELECT bytes FROM text WHERE id=?', (text,)).fetchone()[0]
        require(size <= limit, 'semantic text length bound')
        return b''.join(self.chunks(text))

    def same(self, text, data):
        row = self.db.execute('SELECT bytes,sha FROM text WHERE id=?', (text,)).fetchone()
        if row != (len(data), hashlib.sha256(data).digest()):
            return False
        position = 0
        for chunk in self.chunks(text):
            if data[position:position + len(chunk)] != chunk:
                return False
            position += len(chunk)
        return position == len(data)

    def same_refs(self, left, right):
        metadata = [self.db.execute('SELECT bytes,sha FROM text WHERE id=?', (key,)).fetchone() for key in (left, right)]
        return metadata[0] == metadata[1] and all(a == b for a, b in zip(self.chunks(left), self.chunks(right)))

    def has_unknown(self, source, name):
        source, name = source.encode('utf-8'), name.encode('utf-8')
        candidates = self.db.execute('SELECT u.source,u.name FROM unknown u JOIN text s ON s.id=u.source '
            'JOIN text n ON n.id=u.name WHERE s.bytes=? AND s.sha=? AND n.bytes=? AND n.sha=?',
            (len(source), hashlib.sha256(source).digest(), len(name), hashlib.sha256(name).digest()))
        return any(self.same(s, source) and self.same(n, name) for s, n in candidates)

    def independent(self, source, name):
        require(self.has_unknown(source, name), 'common plan lost an original unclassified definition')
        self.db.execute('INSERT OR IGNORE INTO independent VALUES(?,?)', (source.encode(), name.encode()))

    def independent_count(self):
        return self.db.execute('SELECT count(*) FROM independent').fetchone()[0]


class ReportValidation(UnknownLedger):
    def __init__(self, root, entries, authority):
        super().__init__()
        try:
            self.root = Path(root)
            exact(authority, ('authority', 'files'))
            require(authority['authority'] in ('closed_producer_filesystem', 'external_artifact_inventory'), 'missing report authority')
            self.authority = authority['files']
            require(type(self.authority) is dict and set(self.authority) == report_members(self.root), 'report exact membership differs')
            require(sum(a['bytes'] for a in self.authority.values()
                        if type(a) is dict and uint(a.get('bytes'))) <= TOTAL_BYTES, 'report total byte bound')
            self.index = bounded_json(self.root, 'closed-variadic-plan.json', self.authority, JSON_BYTES)
            exact(self.index, ('schema', 'logical_schema', 'status', 'lowering', 'units', 'records', 'pages', 'bytes', 'catalogs'))
            require(type(self.index['schema']) is int and self.index['schema'] == 2
                    and type(self.index['logical_schema']) is int and self.index['logical_schema'] == 1, 'report schema version')
            require(self.index['status'] == 'ClosedDiagnosticPlan' and self.index['lowering'] == 'not_authorized', 'compiler plan must remain diagnostic')
            for name, bound in (('units', 24), ('records', RECORDS), ('pages', MEMBERS - 1), ('bytes', TOTAL_BYTES)):
                require(uint(self.index[name], bound), 'report index count bound')
            require(type(self.index['catalogs']) is list and len(self.index['catalogs']) <= 49, 'report catalog count bound')
            self.used = {'closed-variadic-plan.json'}
            self.actual_bytes = 0
            self.actual_records = 0
            self.max_page_bytes = self.max_catalog_bytes = self.max_record_bytes = 0
            self.stream = iter(self.records())
            self.sources = set()
            self.counts = self.validate(entries)
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def descriptor(self, descriptor, name, first, maximum):
        exact(descriptor, ('path', 'bytes', 'sha256', 'first', 'count'))
        require(descriptor['path'] == name and uint(descriptor['first']) and descriptor['first'] == first
                and uint(descriptor['count'], maximum) and descriptor['count'] > 0, 'report descriptor range or path differs')
        require(uint(descriptor['bytes']) and digest(descriptor['sha256']) and name not in self.used, 'report descriptor types or duplicate')
        require(self.authority.get(name) == {k: descriptor[k] for k in ('bytes', 'sha256')}, 'descriptor differs from external authority')
        self.used.add(name)
        self.actual_bytes += descriptor['bytes']
        require(self.actual_bytes <= TOTAL_BYTES, 'report total byte bound')

    def records(self):
        page_number = first_record = 0
        catalogs = self.index['catalogs']
        for i, descriptor in enumerate(catalogs):
            name = f'closed-variadic-plan/catalog-{i:08}.json'
            self.descriptor(descriptor, name, page_number, CATALOG_PAGES)
            self.max_catalog_bytes = max(self.max_catalog_bytes, descriptor['bytes'])
            require(i == len(catalogs) - 1 or descriptor['count'] == CATALOG_PAGES, 'nonfinal catalog packing differs')
            catalog = bounded_json(self.root, name, self.authority, JSON_BYTES)
            exact(catalog, ('schema', 'first', 'pages'))
            require(type(catalog['schema']) is int and catalog['schema'] == 2
                    and uint(catalog['first']) and catalog['first'] == page_number
                    and type(catalog['pages']) is list and len(catalog['pages']) == descriptor['count'], 'catalog envelope differs')
            for page_descriptor in catalog['pages']:
                name = f'closed-variadic-plan/page-{page_number:08}.json'
                self.descriptor(page_descriptor, name, first_record, PAGE_RECORDS)
                self.max_page_bytes = max(self.max_page_bytes, page_descriptor['bytes'])
                page, raw = bounded_json(self.root, name, self.authority, PAGE_BYTES, with_raw=True)
                exact(page, ('schema', 'first', 'records'))
                require(type(page['schema']) is int and page['schema'] == 2
                        and uint(page['first']) and page['first'] == first_record
                        and type(page['records']) is list and len(page['records']) == page_descriptor['count'], 'page envelope differs')
                # Locate spans with stdlib's bounded-page decoder, never a streaming document parser.
                text = raw.decode('utf-8')
                match = re.search(r'"records"\s*:\s*\[', text)
                require(match is not None, 'page records span missing')
                position = match.end()
                decoder = json.JSONDecoder(object_pairs_hook=unique,
                    parse_constant=lambda _: require(False, 'nonfinite report number'))
                for record in page['records']:
                    while position < len(text) and text[position].isspace():
                        position += 1
                    start = position
                    decoded, position = decoder.raw_decode(text, position)
                    record_bytes = len(text[start:position].encode('utf-8'))
                    require(decoded == record and record_bytes <= RECORD_BYTES,
                            'report encoded record bound')
                    self.max_record_bytes = max(self.max_record_bytes, record_bytes)
                    while position < len(text) and text[position].isspace():
                        position += 1
                    if position < len(text) and text[position] == ',':
                        position += 1
                    require(type(record) is list and 1 <= len(record) <= 14 and type(record[0]) is str,
                            'domain record shape differs')
                    self.actual_records += 1
                    require(self.actual_records <= self.index['records'], 'report record count differs')
                    yield record
                first_record += page_descriptor['count']
                page_number += 1
        require(page_number == self.index['pages'] and first_record == self.index['records']
                and self.actual_bytes == self.index['bytes'], 'report totals differ')
        require(self.used == set(self.authority) == report_members(self.root), 'report unreferenced or extra member')

    def take(self, tag=None, arity=None):
        try:
            record = next(self.stream)
        except StopIteration:
            raise ValueError('report ended before domain record') from None
        require((tag is None or record[0] == tag) and (arity is None or len(record) == arity), 'domain record tag or arity differs')
        return record

    def ordinal(self, tag, i, arity=2):
        record = self.take(tag, arity)
        require(uint(record[1]) and record[1] == i, 'domain collection ordinal differs')
        return record

    def count(self, value):
        require(uint(value, self.index['records'] - self.actual_records), 'domain collection count bound')
        return value

    def text(self, keep=False, expected=None, limit=None, expected_ref=None):
        keep = keep or expected_ref is not None
        record = self.take()
        if record[0] == 'text':
            require(len(record) == 2 and type(record[1]) is str, 'inline text shape')
            parts = 1
            declared = None
        else:
            require(record[0] == 'text-start' and len(record) == 3
                    and uint(record[1], TOTAL_BYTES) and record[1] > TEXT_BYTES, 'multipart text shape')
            declared = record[1]
            parts = self.count(record[2])
            require(parts > 1 and parts <= declared and declared <= parts * TEXT_BYTES, 'multipart text count')
        text = self.db.execute('INSERT INTO text(bytes,sha) VALUES(0,?)', (b'',)).lastrowid if keep else None
        h = hashlib.sha256()
        length = 0
        previous_length = None
        small = bytearray() if limit is not None else None
        expected_bytes = expected.encode('utf-8') if expected is not None else None
        for i in range(parts):
            part = record[1] if declared is None else self.ordinal('text-part', i, 3)[2]
            require(type(part) is str, 'text part type')
            try:
                data = part.encode('utf-8')
            except UnicodeError:
                raise ValueError('invalid UTF-8 text') from None
            require(len(data) <= TEXT_BYTES and (declared is None or data), 'text part byte bound')
            if previous_length is not None:
                require(previous_length + len(part[0].encode('utf-8')) > TEXT_BYTES, 'noncanonical text chunk boundary')
            if expected_bytes is not None:
                require(expected_bytes[length:length + len(data)] == data, 'semantic text binding differs')
            if small is not None:
                require(length + len(data) <= limit, 'semantic text length bound')
                small.extend(data)
            if keep:
                self.db.execute('INSERT INTO chunk VALUES(?,?,?)', (text, i, data))
            length += len(data)
            h.update(data)
            previous_length = len(data)
        if declared is not None:
            self.take('text-end', 1)
            require(length == declared, 'text byte count differs')
        if expected_bytes is not None:
            require(length == len(expected_bytes), 'semantic text binding differs')
        if keep:
            self.db.execute('UPDATE text SET bytes=?,sha=? WHERE id=?', (length, h.digest(), text))
        if expected_ref is not None:
            require(self.same_refs(text, expected_ref), 'semantic text binding differs')
            self.db.execute('DELETE FROM chunk WHERE text=?', (text,))
            self.db.execute('DELETE FROM text WHERE id=?', (text,))
            text = None
        return small.decode('utf-8') if small is not None else text

    def blockers(self, values):
        require(type(values) is list and len(values) <= len(BLOCKERS)
                and all(type(v) is str and v in BLOCKERS for v in values), 'unknown blocker variant')
        require([BLOCKERS.index(v) for v in values] == sorted(set(BLOCKERS.index(v) for v in values)), 'blocker order or duplicate')
        return values

    def record_identity(self, depth=0):
        require(depth <= 32, 'record owner depth bound')
        row = self.take('record-identity', 6)
        require(uint(row[1]) and row[1] == depth and type(row[2]) is bool and type(row[5]) is bool
                and all(uint(row[i]) and row[i] > 0 for i in (3, 4)), 'record identity metadata differs')
        self.text()
        if row[2]:
            self.text()
        self.text()
        if row[5]:
            self.record_identity(depth + 1)

    def typ(self, depth=0):
        require(depth <= 33, 'TypeFact depth bound')
        row = self.take('type')
        require(len(row) >= 4 and uint(row[1]) and row[1] == depth and type(row[2]) is list
                and len(row[2]) == 3 and all(type(q) is bool for q in row[2]), 'type depth or qualifiers differ')
        variant = row[3]
        if variant == 'Unknown':
            require(len(row) == 5 and type(row[4]) is str and row[4] in ISSUES, 'unknown TypeIssue variant')
            return True
        if variant == 'Scalar':
            require(len(row) == 5 and uint(row[4]), 'scalar type metadata')
            self.text()
            return False
        if variant == 'Pointer' or variant == 'Array':
            require(len(row) == (4 if variant == 'Pointer' else 5)
                    and (variant == 'Pointer' or optional_uint(row[4])), 'pointer or array metadata')
            return self.typ(depth + 1)
        unknown = False
        if variant == 'Function':
            require(len(row) == 8 and all(type(v) is bool for v in row[5:]), 'function metadata')
            count = self.count(row[4])
            self.text()
            unknown = self.typ(depth + 1)
            for i in range(count):
                self.ordinal('parameter', i)
                unknown = self.typ(depth + 1) or unknown
        elif variant == 'Record':
            require(len(row) == 10 and type(row[4]) is bool and optional_uint(row[5])
                    and optional_uint(row[6]) and uint(row[7]) and uint(row[8]), 'record type metadata')
            count = self.count(row[9])
            self.record_identity()
            for i in range(count):
                field = self.ordinal('field', i, 6)
                require(optional_uint(field[2]) and uint(field[3]) and uint(field[4]) and optional_uint(field[5]), 'field layout metadata')
                unknown = self.typ(depth + 1) or unknown
        else:
            raise ValueError('unknown TypeShape variant')
        return unknown

    def declaration(self, unit, source, domain, ordinal, previous):
        row = self.ordinal('declaration', ordinal, 11)
        require(uint(row[2]) and row[2] > previous and uint(row[3]) and row[3] == row[2], 'declaration ID or semantic scope differs')
        require(type(row[4]) is bool and type(row[5]) is bool, 'declaration bool metadata')
        counts = [self.count(v) for v in row[6:10]]
        blockers = self.blockers(row[10])
        self.text(expected=unit)
        symbol = self.take()
        require(symbol in (['symbol-external'], ['symbol-internal']), 'symbol variant differs')
        if symbol[0] == 'symbol-internal':
            self.text(expected=unit)
        else:
            self.text(expected_ref=domain)
        self.text()
        name = self.text(keep=row[4] and 'UnknownSignature' in blockers)
        unknown = self.typ()
        for tag, count in zip(('alias', 'redeclaration', 'visibility', 'attribute'), counts):
            for i in range(count):
                child = self.ordinal(tag, i, 3 if tag == 'visibility' else 2)
                if tag == 'redeclaration':
                    unknown = self.typ() or unknown
                else:
                    if tag == 'visibility':
                        require(type(child[2]) is bool, 'visibility bool metadata')
                    self.text()
        require(not unknown or 'UnknownSignature' in blockers, 'unknown signature lost its blocker')
        self.take('declaration-end', 1)
        self.db.execute('INSERT INTO declaration VALUES(?,?)', (unit, row[2].to_bytes(8, 'big')))
        if name is not None:
            self.db.execute('INSERT INTO unknown VALUES(?,?)', (source, name))
        return row[2]

    def declared(self, unit, value):
        return self.db.execute('SELECT 1 FROM declaration WHERE unit=? AND id=?', (unit, value.to_bytes(8, 'big'))).fetchone() is not None

    def call(self, unit, ordinal, previous):
        row = self.ordinal('call', ordinal, 11)
        require(uint(row[2]) and row[2] > previous and uint(row[3]) and row[3] == row[2], 'Call ID or semantic scope differs')
        require(optional_uint(row[4]) and uint(row[5]) and optional_uint(row[6]), 'Call reference types')
        counts = [self.count(v) for v in row[7:9]]
        blockers = self.blockers(row[10])
        require(row[9] in ('Existing', 'Deferred') and (row[9] == 'Deferred' or not blockers), 'unsupported call disposition')
        self.text(expected=unit)
        if row[4] is not None:
            self.text(expected=unit)
            require(self.declared(unit, row[4]), 'Call owner scope differs')
        require(row[6] is None or self.declared(unit, row[6]), 'Call references an unknown declaration')
        for i in range(counts[0]):
            require(uint(self.ordinal('argument', i, 3)[2]), 'Call argument ID type')
        for i in range(counts[1]):
            self.ordinal('promoted', i)
            self.typ()
        self.take('call-end', 1)
        return row[2]

    def escaped_text(self, hasher, text):
        hasher.update(b'"')
        for chunk in self.chunks(text):
            hasher.update(canonical(chunk.decode('utf-8'))[1:-1])
        hasher.update(b'"')

    def validate(self, entries):
        require(type(entries) is list and 0 < len(entries) <= 24 and self.index['units'] == len(entries), 'incomplete common-plan command universe')
        expected = {}
        for row in entries:
            source = str((Path(row['directory']) / row['file']).resolve())
            command = dict(directory=str(Path(row['directory']).resolve()), file=source,
                           arguments=row['arguments'], output=row.get('output'))
            expected[hashlib.sha256(canonical(dict(command=command, extra=[]))).hexdigest()] = source
        require(len(expected) == len(entries), 'duplicate effective command')
        observed = set()
        declarations = calls = 0
        previous_key = ''
        first_target = first_widths = None
        for i in range(len(entries)):
            row = self.ordinal('unit', i, 8)
            widths = row[2]
            require(type(widths) is list and len(widths) == 8 and all(uint(w) and w > 0 for w in widths), 'unresolved target facts')
            require(all(type(v) is int and v == 1 for v in row[3:5]), 'native export/import count differs')
            source_count, declaration_count, call_count = [self.count(v) for v in row[5:8]]
            require(declaration_count <= 35879 and call_count <= 92781, 'fixed native per-unit fact ceiling')
            declarations += declaration_count
            calls += call_count
            require(declarations <= 213129 and calls <= 714273, 'fixed native total fact ceiling')
            key = self.text(limit=64)
            command = self.text(limit=64)
            require(digest(key) and key > previous_key, 'UnitKey ordering or digest differs')
            previous_key = key
            require(command in expected and command not in observed, 'source or effective-command binding differs')
            observed.add(command)
            domain = self.text(keep=True)
            source = self.text(keep=True, expected=expected[command])
            self.sources.add(expected[command])
            require(digest(self.text(limit=64)), 'missing actual native AST instance digest')
            target = self.text(keep=True)
            require(self.db.execute('SELECT bytes FROM text WHERE id=?', (target,)).fetchone()[0] > 0, 'unresolved target facts')
            if first_target is None:
                first_target, first_widths = target, widths
            else:
                require(widths == first_widths and self.same_refs(target, first_target), 'mixed native target facts')
            h = hashlib.sha256()
            h.update(b'{"command":' + canonical(command) + b',"domain":')
            self.escaped_text(h, domain)
            h.update(b',"sources":{')
            previous_path = ''
            main = False
            for ordinal in range(source_count):
                seal = self.ordinal('source', ordinal, 3)
                require(digest(seal[2]), 'source SHA type')
                # Native canonical source names must be usable by this filesystem.
                path = self.text(limit=os.pathconf('/', 'PC_PATH_MAX'))
                require(Path(path).is_absolute() and path > previous_path, 'source seal order or path differs')
                previous_path = path
                main = main or path == expected[command]
                source_hash = hashlib.sha256()
                with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0)), 'rb') as stream:
                    before = os.fstat(stream.fileno())
                    require(stat.S_ISREG(before.st_mode), 'native source is not a regular file')
                    remaining = before.st_size
                    while remaining:
                        chunk = stream.read(min(65536, remaining))
                        require(chunk, 'original native source changed')
                        source_hash.update(chunk)
                        remaining -= len(chunk)
                    after = os.fstat(stream.fileno())
                    require(not stream.read(1) and (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                            == (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'original native source changed')
                require(source_hash.hexdigest() == seal[2], 'original native source changed')
                if ordinal:
                    h.update(b',')
                h.update(canonical(path) + b':' + canonical(seal[2]))
            require(main, 'missing original main buffer seal')
            h.update(b'},"target":')
            self.escaped_text(h, target)
            h.update(b',"widths":' + canonical(widths) + b'}')
            require(h.hexdigest() == key, 'semantic UnitKey differs')
            previous = -1
            for ordinal in range(declaration_count):
                previous = self.declaration(key, source, domain, ordinal, previous)
            previous = -1
            for ordinal in range(call_count):
                previous = self.call(key, ordinal, previous)
            self.take('unit-end', 1)
        require(next(self.stream, None) is None, 'extra domain record')
        self.db.commit()
        return dict(schema=2, units=len(entries), declarations=declarations, calls=calls,
                    unknown_definitions=self.db.execute('SELECT count(*) FROM unknown').fetchone()[0],
                    report=dict(index='closed-variadic-plan.json', pages=self.index['pages'], records=self.index['records'],
                                bytes=sum(a['bytes'] for a in self.authority.values()),
                                members=len(self.authority), max_page_bytes=self.max_page_bytes,
                                max_catalog_bytes=self.max_catalog_bytes, max_record_bytes=self.max_record_bytes,
                                index_bytes=self.authority['closed-variadic-plan.json']['bytes'],
                                index_sha256=self.authority['closed-variadic-plan.json']['sha256']))


def parent_resources():
    import resource
    import sys
    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak = usage.ru_maxrss * (1024 if sys.platform.startswith('linux') else 1)
    require(type(peak) is int and peak > 0, 'parent validation peak RSS unavailable')
    return dict(status='measured', scope='validation_parent_process_peak_at_observation', peak_rss_bytes=peak,
                source='resource.RUSAGE_SELF', pid=os.getpid())
