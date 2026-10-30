import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import common_plan_report as report
from common_plan_fixture import encode, plan_records, write_records


def logical_plan(root):
    source = root / 'source.c'
    source.write_bytes(b'int source;\n')
    row = dict(directory=str(root), file=str(source), arguments=['clang', '-c', str(source)])
    command = hashlib.sha256(report.canonical(dict(command=dict(row, output=None), extra=[]))).hexdigest()
    sources = {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}
    identity = dict(command=command, domain='fixture', source=str(source), ast_instance='a' * 64,
                    target='fixture-target', widths=[8, 16, 32, 64, 64, 64, 32, 64])
    identity['key'] = hashlib.sha256(report.canonical(dict(command=command, domain=identity['domain'],
        target=identity['target'], widths=identity['widths'], sources=sources))).hexdigest()
    unknown = dict(qualifiers=[False, True, False], shape=dict(Unknown='Attributed'))
    declaration = dict(id=2**64 - 1, key=dict(unit=identity['key'], declaration=2**64 - 1),
        symbol=dict(Internal=dict(unit=identity['key'], name='unknown')), name='unknown', signature=unknown,
        definition=True, cursor_parameters=False, aliases=[''], redeclarations=[unknown], visibility=[(False, '')],
        native_attributes=[''], blockers=['UnknownSignature'])
    call = dict(id=2**64 - 1, key=dict(unit=identity['key'], expression=2**64 - 1),
        owner=declaration['key'], callee_expression=4, direct=declaration['id'], arguments=[2**64 - 1],
        promoted_arguments=[unknown], disposition=dict(Deferred=['UnknownSignature']))
    plan = dict(units=[dict(identity=identity, source_sha256=sources, declarations=[declaration], calls=[call],
                           native_ast_exports=1, typed_imports=1)])
    return plan, row


def rebind_fixture(root, padding=None):
    def seal(path):
        raw = path.read_bytes()
        return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())

    def write(path, value):
        raw = encode(value)
        size = (padding or {}).get(path.relative_to(root).as_posix(), len(raw))
        if size < len(raw):
            raise ValueError('fixture padding would truncate JSON')
        path.write_bytes(raw + b' ' * (size - len(raw)))

    path = root / 'closed-variadic-plan.json'
    index = json.loads(path.read_bytes())
    for descriptor in index['catalogs']:
        catalog_path = root / descriptor['path']
        catalog = json.loads(catalog_path.read_bytes())
        for page in catalog['pages']:
            page.update(seal(root / page['path']))
        write(catalog_path, catalog)
        descriptor.update(seal(catalog_path))
    index['bytes'] = sum(seal(root / name)['bytes']
                         for name in report.report_members(root) if name != 'closed-variadic-plan.json')
    write(path, index)
    return dict(authority='external_artifact_inventory', files={name: seal(root / name)
                                                              for name in report.report_members(root)})


def source_order_plan(root):
    plan, row = logical_plan(root)
    unit = plan['units'][0]
    (root / 'types').mkdir()
    for name in ('types/wint_t.h', 'types.h', 'Z.h', 'a.h', '界.h'):
        path = root / name
        path.write_bytes(name.encode('utf-8'))
        unit['source_sha256'][str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    identity = unit['identity']
    identity['key'] = hashlib.sha256(report.canonical(dict(command=identity['command'], domain=identity['domain'],
        target=identity['target'], widths=identity['widths'], sources=unit['source_sha256']))).hexdigest()
    for declaration in unit['declarations']:
        declaration['key']['unit'] = identity['key']
        declaration['symbol']['Internal']['unit'] = identity['key']
    for call in unit['calls']:
        call['key']['unit'] = identity['key']
    return plan, row


class BoundedReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.plan, self.row = logical_plan(self.root)

    def write(self, mutate=None, page_records=4096):
        records = list(plan_records(self.plan))
        if mutate:
            mutate(records)
        write_records(self.root, records, page_records=page_records)
        return self.authority()

    def authority(self):
        return dict(authority='external_artifact_inventory', files={name: report.file_seal(self.root / name, report.JSON_BYTES)
                                                                  for name in report.report_members(self.root)})

    def validate(self, authority):
        return report.ReportValidation(self.root, [self.row], authority)

    def test_complete_pages_u64_and_full_byte_unknown_join(self):
        with self.validate(self.write(page_records=2)) as validation:
            self.assertEqual(validation.counts['unknown_definitions'], 1)
            self.assertGreater(validation.counts['report']['pages'], 10)
            self.assertTrue(validation.has_unknown(self.row['file'], 'unknown'))
            self.assertFalse(validation.has_unknown(self.row['file'], 'unknown!'))
            self.assertFalse(validation.has_unknown(self.row['file'] + '!', 'unknown'))

    def test_all_type_fields_are_walked(self):
        scalar = dict(qualifiers=[True, False, True], shape=dict(Scalar=['Int', 32]))
        identity = dict(kind='struct', tag=None, file=self.row['file'], line=1, column=1, owner=None)
        nested = dict(qualifiers=[False] * 3, shape=dict(Record=dict(identity=identity, packed=True,
            manual_alignment=0, max_field_alignment=None, size=0, alignment=0,
            fields=[dict(typ=dict(qualifiers=[False] * 3, shape=dict(Array=[scalar, None])),
                         bitfield_width=0, bit_offset=0, type_bitwidth=0, alignment=None)])))
        function = dict(qualifiers=[False] * 3, shape=dict(Function=dict(result=scalar, parameters=[nested],
                        variadic=True, prototype=False, noreturn=True, abi='C')))
        self.plan['units'][0]['declarations'][0]['signature'] = function
        with self.validate(self.write()) as validation:
            self.assertEqual(validation.counts['declarations'], 1)

    def test_late_page_corruption_is_not_skipped(self):
        def mutate(records):
            row = next(r for r in reversed(records) if r[0] == 'type')
            row[4] = 'InventedIssue'
        with self.assertRaisesRegex(ValueError, 'TypeIssue'):
            self.validate(self.write(mutate, page_records=2))

    def test_malformed_domain_records_fail_closed(self):
        changes = [('unit', 3, True), ('unit', 2, [True] * 8), ('declaration', 4, 1),
                   ('declaration', 10, ['UnknownSignature', 'UnknownSignature']),
                   ('declaration', 10, ['Authorized']), ('call', 6, 123), ('call', 9, 'Lower'),
                   ('argument', 2, True), ('visibility', 2, 0), ('type', 2, [False, False, 0]),
                   ('type', 1, 34), ('type', 4, 'InventedIssue')]
        for tag, position, value in changes:
            with self.subTest(tag=tag, position=position, value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                plan, row = logical_plan(root)
                records = list(plan_records(plan))
                next(r for r in records if r[0] == tag)[position] = value
                write_records(root, records, page_records=2)
                authority = dict(authority='external_artifact_inventory', files={name: report.file_seal(root / name, report.JSON_BYTES)
                                                                              for name in report.report_members(root)})
                with self.assertRaises(ValueError):
                    report.ReportValidation(root, [row], authority)

    def test_hash_is_external_and_checked_before_json(self):
        authority = self.write()
        page = self.root / 'closed-variadic-plan/page-00000000.json'
        page.write_bytes(b'not-json')
        with self.assertRaisesRegex(ValueError, 'external length or hash'):
            self.validate(authority)

    def test_duplicate_unknown_fields_nonfinite_and_bool_index(self):
        self.write()
        path = self.root / 'closed-variadic-plan.json'
        original = path.read_bytes()
        for raw in (original.replace(b'"schema":2', b'"schema":2,"schema":2'),
                    original[:-1] + b',"extra":0}', original.replace(b'"schema":2', b'"schema":NaN'),
                    original.replace(b'"schema":2', b'"schema":true')):
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                self.validate(self.authority())

    def test_descriptor_paths_counts_ranges_and_hashes(self):
        self.write()
        path = self.root / 'closed-variadic-plan.json'
        original = json.loads(path.read_bytes())
        for field, value in (('path', '../escape'), ('count', 0), ('count', True), ('first', 1), ('sha256', '0' * 64)):
            index = copy.deepcopy(original)
            index['catalogs'][0][field] = value
            path.write_bytes(encode(index))
            with self.assertRaises(ValueError):
                self.validate(self.authority())

    def test_duplicate_missing_extra_and_ordered_records(self):
        for mode in ('duplicate', 'missing', 'ordinal', 'extra'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                plan, row = logical_plan(root)
                records = list(plan_records(plan))
                if mode == 'duplicate':
                    position = next(i for i, r in enumerate(records) if r[0] == 'call')
                    records.insert(position, records[position].copy())
                elif mode == 'missing':
                    records.pop(-2)
                elif mode == 'ordinal':
                    next(r for r in records if r[0] == 'argument')[1] = 1
                else:
                    records.append(['unit-end'])
                write_records(root, records)
                authority = dict(authority='external_artifact_inventory', files={name: report.file_seal(root / name, report.JSON_BYTES)
                                                                              for name in report.report_members(root)})
                with self.assertRaises(ValueError):
                    report.ReportValidation(root, [row], authority)

    def test_noncanonical_short_multipart_and_surrogates(self):
        def mutate(records):
            position = next(i for i, r in enumerate(records) if r == ['text', 'unknown'])
            records[position:position + 1] = [['text-start', 7, 1], ['text-part', 0, 'unknown'], ['text-end']]
        with self.assertRaisesRegex(ValueError, 'multipart text'):
            self.validate(self.write(mutate))

    def test_text_chunk_boundaries_and_whole_name_are_checked(self):
        name = 'a' * 8191 + '界😀' * 100
        self.plan['units'][0]['declarations'][0]['name'] = name
        with self.validate(self.write()) as validation:
            self.assertTrue(validation.has_unknown(self.row['file'], name))
            self.assertFalse(validation.has_unknown(self.row['file'], name[:-1] + 'X'))

    def test_extra_page_is_rejected_against_external_membership(self):
        self.write()
        (self.root / 'closed-variadic-plan/page-00000001.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'unreferenced or extra'):
            self.validate(self.authority())

    def test_admission_caps_are_not_raised_by_index(self):
        self.write()
        path = self.root / 'closed-variadic-plan.json'
        index = json.loads(path.read_bytes())
        index['bytes'] = report.TOTAL_BYTES + 1
        path.write_bytes(encode(index))
        with self.assertRaisesRegex(ValueError, 'count bound'):
            self.validate(self.authority())


class SourceOrderTests(unittest.TestCase):
    def test_native_component_order_and_string_key_hash_across_pages_and_units(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plans, entries = [], []
            for name in ('first', 'second'):
                folder = root / name
                folder.mkdir()
                plan, row = source_order_plan(folder)
                unit = plan['units'][0]
                records = list(plan_records(plan))
                wire = [records[i + 1][1] for i, record in enumerate(records) if record[0] == 'source']
                self.assertLess(wire.index(str(folder / 'types/wint_t.h')), wire.index(str(folder / 'types.h')))
                self.assertNotEqual(wire, sorted(unit['source_sha256']))
                plans.append(unit)
                entries.append(row)
            plans.sort(key=lambda unit: unit['identity']['key'])
            write_records(root, plan_records(dict(units=plans)), units=2, page_records=1)
            authority = rebind_fixture(root)
            with report.ReportValidation(root, entries, authority) as validation:
                self.assertEqual(validation.counts['units'], 2)
                self.assertEqual(validation.db.execute('SELECT count(*) FROM source').fetchone()[0], 6)

    def test_source_order_and_semantic_guards(self):
        cases = [('lexical', 'source seal order or path differs'),
                 ('duplicate', 'source seal order or path differs'),
                 ('relative', 'source seal order or path differs'),
                 ('ordinal', 'domain collection ordinal differs'), ('sha', 'source SHA type'),
                 ('missing-main', 'missing original main buffer seal'),
                 ('changed-bytes', 'original native source changed'),
                 ('wrong-key', 'semantic UnitKey differs')]
        for mode, error in cases:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                plan, row = source_order_plan(root)
                records = list(plan_records(plan))
                positions = [i for i, record in enumerate(records) if record[0] == 'source']
                if mode == 'lexical':
                    pairs = sorted(([records[i], records[i + 1]] for i in positions), key=lambda pair: pair[1][1])
                    for ordinal, (i, pair) in enumerate(zip(positions, pairs)):
                        records[i:i + 2] = [[pair[0][0], ordinal, pair[0][2]], pair[1]]
                elif mode == 'duplicate':
                    records[positions[1] + 1] = records[positions[0] + 1].copy()
                elif mode == 'relative':
                    records[positions[0] + 1] = ['text', 'relative.h']
                elif mode == 'ordinal':
                    records[positions[0]][1] = 1
                elif mode == 'sha':
                    records[positions[0]][2] = 'wrong'
                elif mode == 'missing-main':
                    i = next(i for i in positions if records[i + 1] == ['text', row['file']])
                    del records[i:i + 2]
                    records[0][5] -= 1
                    for ordinal, record in enumerate(r for r in records if r[0] == 'source'):
                        record[1] = ordinal
                elif mode == 'changed-bytes':
                    (root / 'types.h').write_bytes(b'changed')
                else:
                    records[1] = ['text', '0' * 64]
                write_records(root, records, page_records=2)
                with self.assertRaisesRegex(ValueError, '^' + error + '$'):
                    report.ReportValidation(root, [row], rebind_fixture(root))


class HostedGiantReportTests(unittest.TestCase):
    def catalog_fixture(self, root, counts):
        plan, row = logical_plan(root)
        records = list(plan_records(plan))
        pages = sum(counts)
        plan['units'][0]['calls'][0]['arguments'].extend([0] * (pages - len(records)))
        records = list(plan_records(plan))
        self.assertEqual(len(records), pages)
        (root / 'closed-variadic-plan').mkdir()
        index = dict(schema=2, logical_schema=1, status='ClosedDiagnosticPlan', lowering='not_authorized',
                     units=1, records=len(records), pages=pages, bytes=0, catalogs=[])
        descriptors = []
        for i, record in enumerate(records):
            name = f'closed-variadic-plan/page-{i:08}.json'
            raw = encode(dict(schema=2, first=i, records=[record]))
            (root / name).write_bytes(raw)
            descriptors.append(dict(path=name, first=i, count=1))
        first = 0
        for i, count in enumerate(counts):
            name = f'closed-variadic-plan/catalog-{i:08}.json'
            (root / name).write_bytes(encode(dict(schema=2, first=first, pages=descriptors[first:first + count])))
            index['catalogs'].append(dict(path=name, first=first, count=count))
            first += count
        (root / 'closed-variadic-plan.json').write_bytes(encode(index))
        return row, rebind_fixture(root)

    def test_catalog_packing_boundaries(self):
        cases = [([4096, 1], None), ([4096, 4096], None),
                 ([4095, 1], 'nonfinal catalog packing differs'),
                 ([4096, 0], 'report descriptor range or path differs'),
                 ([4097], 'report descriptor range or path differs'),
                 ([1] * 50, 'report catalog count bound')]
        for counts, error in cases:
            with self.subTest(counts=counts), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                row, authority = self.catalog_fixture(root, counts)
                if error:
                    with self.assertRaisesRegex(ValueError, '^' + error + '$'):
                        report.ReportValidation(root, [row], authority)
                else:
                    with report.ReportValidation(root, [row], authority) as validation:
                        self.assertEqual(validation.counts['report']['pages'], sum(counts))

    def test_actual_encoded_page_catalog_and_index_byte_bounds(self):
        cases = [('closed-variadic-plan/page-00000000.json', report.PAGE_BYTES),
                 ('closed-variadic-plan/catalog-00000000.json', report.JSON_BYTES),
                 ('closed-variadic-plan.json', report.JSON_BYTES)]
        for name, limit in cases:
            for excess in (0, 1):
                with self.subTest(name=name, excess=excess), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory).resolve()
                    plan, row = logical_plan(root)
                    write_records(root, plan_records(plan))
                    if '/page-' in name:
                        path = root / name
                        raw = path.read_bytes()
                        path.write_bytes(raw + b' ' * (limit + excess - len(raw)))
                    authority = rebind_fixture(root, {name: limit + excess})
                    self.assertEqual((root / name).stat().st_size, limit + excess)
                    self.assertEqual(authority['files'][name]['bytes'], limit + excess)
                    if excess:
                        with self.assertRaisesRegex(ValueError, '^report external authority fields differ$'):
                            report.ReportValidation(root, [row], authority)
                    else:
                        with report.ReportValidation(root, [row], authority) as validation:
                            self.assertEqual(validation.counts['declarations'], 1)

    def test_surrogate_and_actual_encoded_record_length_are_rejected(self):
        for which in ('surrogate', 'record-bytes'):
            with self.subTest(which=which), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                plan, row = logical_plan(root)
                write_records(root, plan_records(plan))
                page = root / 'closed-variadic-plan/page-00000000.json'
                raw = page.read_bytes()
                if which == 'surrogate':
                    raw = raw.replace(b'"unknown"', b'"\\ud800"', 1)
                else:
                    raw = raw.replace(b'["type",', b'[' + b' ' * 65536 + b'"type",', 1)
                page.write_bytes(raw)
                with self.assertRaisesRegex(ValueError, 'UTF-8|encoded record bound'):
                    report.ReportValidation(root, [row], rebind_fixture(root))

    def test_all_unknown_reasons_are_preserved(self):
        for issue in sorted(report.ISSUES):
            with self.subTest(issue=issue), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                plan, row = logical_plan(root)
                plan['units'][0]['declarations'][0]['signature']['shape']['Unknown'] = issue
                write_records(root, plan_records(plan))
                authority = dict(authority='external_artifact_inventory', files={name: report.file_seal(root / name, report.JSON_BYTES)
                                                                              for name in report.report_members(root)})
                with report.ReportValidation(root, [row], authority) as validation:
                    self.assertEqual(validation.counts['unknown_definitions'], 1)

    def test_single_fact_over_8mib_has_no_whole_fact_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, row = logical_plan(root)
            name = '界😀\\\n' * 1100000
            plan['units'][0]['declarations'][0]['name'] = name
            self.assertGreater(len(encode(plan['units'][0]['declarations'][0])), report.JSON_BYTES)
            write_records(root, plan_records(plan))
            authority = dict(authority='external_artifact_inventory', files={name: report.file_seal(root / name, report.JSON_BYTES)
                                                                          for name in report.report_members(root)})
            with report.ReportValidation(root, [row], authority) as validation:
                self.assertTrue(validation.has_unknown(row['file'], name))
                self.assertGreater(validation.counts['report']['pages'], 1)

    def test_every_nested_metadata_position_rejects_wrong_types(self):
        scalar = dict(qualifiers=[False] * 3, shape=dict(Scalar=['Int', 32]))
        identity = dict(kind='struct', tag='', file='/fixture.c', line=1, column=1, owner=None)
        record = dict(qualifiers=[False] * 3, shape=dict(Record=dict(identity=identity, packed=False,
            manual_alignment=None, max_field_alignment=0, size=32, alignment=8,
            fields=[dict(typ=scalar, bitfield_width=None, bit_offset=0, type_bitwidth=32, alignment=0)])))
        function = dict(qualifiers=[False] * 3, shape=dict(Function=dict(result=scalar, parameters=[record],
                        variadic=False, prototype=True, noreturn=False, abi='C')))
        mutations = [('Function', 4, True), ('Function', 5, 0), ('Function', 6, None), ('Function', 7, 'false'),
                     ('Record', 4, 0), ('Record', 5, False), ('Record', 6, -1), ('Record', 7, True),
                     ('Record', 8, 2**64), ('Record', 9, True), ('field', 2, True), ('field', 3, -1),
                     ('field', 4, '32'), ('field', 5, False), ('record-identity', 1, 33),
                     ('record-identity', 2, 1), ('record-identity', 3, 0), ('record-identity', 5, 0)]
        for tag, position, value in mutations:
            with self.subTest(tag=tag, position=position), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                plan, row = logical_plan(root)
                plan['units'][0]['declarations'][0]['signature'] = function
                records = list(plan_records(plan))
                target = next(r for r in records if (r[0] == 'type' and r[3] == tag) or r[0] == tag)
                target[position] = value
                write_records(root, records, page_records=3)
                authority = dict(authority='external_artifact_inventory', files={name: report.file_seal(root / name, report.JSON_BYTES)
                                                                              for name in report.report_members(root)})
                with self.assertRaises(ValueError):
                    report.ReportValidation(root, [row], authority)

    def test_true_owner_and_type_depth_limits_are_enforced(self):
        for which in ('type', 'owner'):
            with self.subTest(which=which), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                plan, row = logical_plan(root)
                scalar = dict(qualifiers=[False] * 3, shape=dict(Scalar=['Int', 32]))
                if which == 'type':
                    for _ in range(34):
                        scalar = dict(qualifiers=[False] * 3, shape=dict(Pointer=scalar))
                else:
                    owner = None
                    for _ in range(34):
                        owner = dict(kind='struct', tag=None, file=row['file'], line=1, column=1, owner=owner)
                    scalar = dict(qualifiers=[False] * 3, shape=dict(Record=dict(identity=owner, packed=False,
                        manual_alignment=None, max_field_alignment=None, size=0, alignment=0, fields=[])))
                plan['units'][0]['declarations'][0]['signature'] = scalar
                write_records(root, plan_records(plan))
                authority = dict(authority='external_artifact_inventory', files={name: report.file_seal(root / name, report.JSON_BYTES)
                                                                              for name in report.report_members(root)})
                with self.assertRaisesRegex(ValueError, 'depth'):
                    report.ReportValidation(root, [row], authority)

    def test_late_blocker_and_duplicate_id_are_rejected(self):
        for which in ('blocker', 'id'):
            with self.subTest(which=which), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                plan, row = logical_plan(root)
                if which == 'id':
                    plan['units'][0]['calls'].append(copy.deepcopy(plan['units'][0]['calls'][0]))
                else:
                    plan['units'][0]['calls'][0]['disposition'] = dict(Deferred=['Authorized'])
                write_records(root, plan_records(plan), page_records=2)
                authority = dict(authority='external_artifact_inventory', files={name: report.file_seal(root / name, report.JSON_BYTES)
                                                                              for name in report.report_members(root)})
                with self.assertRaises(ValueError):
                    report.ReportValidation(root, [row], authority)


if __name__ == '__main__':
    unittest.main()
