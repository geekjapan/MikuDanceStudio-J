import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import shutil
import unittest

from check_common_plan import canonical, preserved_unknowns
from common_plan_report import ReportValidation, file_seal, report_members
from common_plan_fixture import plan_records, write_records, fixture_ledger


def preserve_fixture(reports, counts, sources):
    ledger = fixture_ledger(counts['unknown_definitions'])
    try:
        return preserved_unknowns(reports, ledger, sources)
    finally:
        ledger.close()


class CommonPlanDataTests(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get('COMMON_PLAN_TEST_ROOT')
        self.root = Path(tempfile.mkdtemp(dir=parent)).resolve()
        self.addCleanup(self.cleanup_fixture)
        source = self.root / 'source.c'
        source.write_text('int source;\n')
        self.row = dict(directory=str(self.root), file=str(source), arguments=['clang', '-c', str(source)])
        command = hashlib.sha256(canonical(dict(command=dict(self.row, output=None), extra=[]))).hexdigest()
        sources = {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}
        identity = dict(command=command, domain='fixture', source=str(source), ast_instance='a' * 64,
                        target='fixture-target', widths=[8, 16, 32, 64, 64, 64, 32, 64])
        identity['key'] = hashlib.sha256(canonical(dict(command=command, domain='fixture', target=identity['target'],
                                                       widths=identity['widths'], sources=sources))).hexdigest()
        declaration = dict(id=7, key=dict(unit=identity['key'], declaration=7), name='fixture', definition=True,
                           signature=dict(qualifiers=[False, False, False], shape={'Unknown': 'Attributed'}),
                           symbol={'Internal': dict(unit=identity['key'], name='fixture')}, cursor_parameters=False,
                           aliases=[], redeclarations=[], visibility=[], native_attributes=[], blockers=['UnknownSignature'])
        call = dict(id=9, key=dict(unit=identity['key'], expression=9), owner=dict(unit=identity['key'], declaration=7), direct=7,
                    callee_expression=8, arguments=[], promoted_arguments=[], disposition={'Deferred': ['UnknownSignature']})
        self.plan = dict(status='ClosedDiagnosticPlan', lowering='not_authorized', units=[dict(identity=identity,
            native_ast_exports=1, typed_imports=1, source_sha256=sources, declarations=[declaration], calls=[call])])
        self.assertEqual(self.validate(self.plan)['units'], 1)

    def validate(self, plan):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            directory = Path(directory)
            write_records(directory, plan_records(plan), units=len(plan['units']))
            authority = dict(authority='external_artifact_inventory', files={name: file_seal(directory / name, 8 * 1024 * 1024)
                                                                          for name in report_members(directory)})
            with ReportValidation(directory, [self.row], authority) as validation:
                return validation.counts

    def cleanup_fixture(self):
        shutil.rmtree(self.root)

    def reject(self, mutation, reason):
        changed = copy.deepcopy(self.plan)
        mutation(changed['units'][0])
        with self.assertRaisesRegex(ValueError, reason):
            self.validate(changed)

    def test_effective_command_and_source_binding(self):
        self.reject(lambda u: u['identity'].update(command='b' * 64), 'effective-command binding')
        self.reject(lambda u: u['identity'].update(source='/different.c'), 'semantic text binding')

    def test_target_and_ast_instance_binding(self):
        self.reject(lambda u: u['identity'].update(target='other-target'), 'UnitKey differs')
        self.reject(lambda u: u['identity'].update(ast_instance='unknown'), 'AST instance digest')
        self.reject(lambda u: u['identity'].update(widths=[0] * 8), 'target facts')

    def test_original_buffer_is_checked_without_identity_mocks(self):
        Path(self.row['file']).write_text('changed\n')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            self.validate(self.plan)

    def test_complete_universe_and_exact_node_membership(self):
        with self.assertRaisesRegex(ValueError, 'command universe'):
            self.validate(dict(self.plan, units=[]))
        self.reject(lambda u: u['declarations'].append(u['declarations'][0]), 'declaration ID')
        self.reject(lambda u: u['calls'][0].update(direct=99), 'unknown declaration')
        self.reject(lambda u: u['declarations'][0]['key'].update(unit='other-unit'), 'semantic text binding')
        self.reject(lambda u: u['calls'][0]['key'].update(expression=10), 'semantic scope')

    def test_unknown_signatures_remain_blocked(self):
        self.reject(lambda u: u['declarations'][0].update(blockers=[]), 'lost its blocker')
        self.reject(lambda u: u['calls'][0].update(disposition={'Lower': []}), 'call disposition')

    def test_native_counts_are_not_substituted_by_reimports(self):
        self.reject(lambda u: u.update(typed_imports=2), 'export/import count')
        self.reject(lambda u: u.update(native_ast_exports=0), 'export/import count')


class IndependentUnknownSchemaTests(unittest.TestCase):
    def setUp(self):
        self.unit = '/fixture/blob.c'
        definition = dict(declaration=7, location={'unproved': 'native importer origin missing'},
                          signature={'unproved': 'unsupported type or wrapper limit'}, state='Unproved',
                          reason='native attributed function signature unclassified',
                          symbol=dict(unit=self.unit, static='vkd3d_blob_Release'))
        self.reports = json.loads(json.dumps([dict(unit=self.unit, unclassified_definitions=[definition])]))
        self.counts = dict(unknown_definitions=[dict(unit=self.unit, id=7, name='vkd3d_blob_Release',
                                                   blockers=['UnknownSignature'])])
        self.assertEqual(self.preserve()['count'], 1)

    def preserve(self):
        return preserve_fixture(self.reports, self.counts, {self.unit})

    def reject_definition(self, mutate, reason):
        mutate(self.reports[0]['unclassified_definitions'][0])
        with self.assertRaisesRegex(ValueError, reason):
            self.preserve()

    def test_static_source_name_is_preserved(self):
        self.counts['unknown_definitions'].append(dict(unit=self.unit, id=8, name='another_unknown'))
        self.assertEqual(self.preserve()['count'], 1)

    def test_missing_and_extra_record_fields_are_rejected(self):
        original = copy.deepcopy(self.reports)
        for field in original[0]['unclassified_definitions'][0]:
            self.reports = copy.deepcopy(original)
            self.reject_definition(lambda d: d.pop(field), 'schema differs')
        self.reports = copy.deepcopy(original)
        self.reject_definition(lambda d: d.update(name='guessed_alias'), 'schema differs')

    def test_scalar_field_types_are_rejected(self):
        original = copy.deepcopy(self.reports)
        for field in ('declaration', 'location', 'signature', 'symbol'):
            self.reports = copy.deepcopy(original)
            self.reject_definition(lambda d: d.update({field: True}), 'field types|static C source identity')
        for value in (-1, 2**64, '7', None):
            self.reports = copy.deepcopy(original)
            self.reject_definition(lambda d: d.update(declaration=value), 'field types')

    def test_state_and_reason_remain_unproved(self):
        original = copy.deepcopy(self.reports)
        for field, value in (('state', 'Proved'), ('reason', 'unknown'), ('state', True), ('reason', False)):
            self.reports = copy.deepcopy(original)
            self.reject_definition(lambda d: d.update({field: value}), 'evidence differs')

    def test_global_and_ambiguous_symbols_fail_closed(self):
        original = copy.deepcopy(self.reports)
        for symbol in (None, {'linker': 'vkd3d_blob_Release'}, {'unit': self.unit},
                       {'unit': self.unit, 'static': 'vkd3d_blob_Release', 'linker': 'alias'}):
            self.reports = copy.deepcopy(original)
            self.reject_definition(lambda d: d.update(symbol=symbol), 'static C source identity')

    def test_static_symbol_unit_and_name_are_required(self):
        original = copy.deepcopy(self.reports)
        for field, value in (('unit', '/other.c'), ('unit', True), ('static', ''), ('static', True), ('static', None)):
            self.reports = copy.deepcopy(original)
            self.reject_definition(lambda d: d['symbol'].update({field: value}), 'static source identity differs')

    def test_report_unit_is_bound_to_validated_plan_sources(self):
        for unit in ('/other.c', '', True, None):
            self.reports[0]['unit'] = unit
            with self.assertRaisesRegex(ValueError, 'independent unknown unit differs'):
                self.preserve()

    def test_missing_empty_and_wrongly_typed_census_is_rejected(self):
        for definitions in (None, {}, True, []):
            self.reports[0]['unclassified_definitions'] = definitions
            with self.assertRaisesRegex(ValueError, 'must be a list|missing independent'):
                self.preserve()
        self.reports = []
        with self.assertRaisesRegex(ValueError, 'missing independent'):
            self.preserve()

    def test_plan_names_and_units_cannot_be_replaced_by_matching_ids(self):
        original = copy.deepcopy(self.counts)
        for field, value in (('name', 'wrong_name'), ('unit', '/other.c')):
            self.counts = copy.deepcopy(original)
            self.counts['unknown_definitions'][0][field] = value
            with self.assertRaisesRegex(ValueError, 'lost an original'):
                self.preserve()
        self.counts['unknown_definitions'] = []
        with self.assertRaisesRegex(ValueError, 'lost an original'):
            self.preserve()

    def test_nonobject_reports_and_definitions_are_rejected(self):
        original = copy.deepcopy(self.reports)
        for value in (None, True, [], 'definition'):
            self.reports = copy.deepcopy(original)
            self.reports[0]['unclassified_definitions'] = [value]
            with self.assertRaisesRegex(ValueError, 'schema differs'):
                self.preserve()
            self.reports = [value]
            with self.assertRaisesRegex(ValueError, 'report must be an object'):
                self.preserve()

    def test_each_unknown_unit_and_name_pair_is_preserved(self):
        second = copy.deepcopy(self.reports[0])
        second['unit'] = '/fixture/other.c'
        second['unclassified_definitions'][0]['symbol']['unit'] = second['unit']
        reports = self.reports + [second]
        counts = copy.deepcopy(self.counts)
        counts['unknown_definitions'].append(dict(unit=second['unit'], id=7, name='vkd3d_blob_Release'))
        sources = {self.unit, second['unit']}
        self.assertEqual(preserve_fixture(reports, counts, sources)['count'], 2)
        with self.assertRaisesRegex(ValueError, 'lost an original'):
            preserve_fixture(reports, self.counts, sources)

    def test_coordinated_flat_name_alias_is_rejected(self):
        self.counts['unknown_definitions'][0]['name'] = 'wrong_name'
        self.reject_definition(lambda d: d.update(name='wrong_name'), 'schema differs')


class NestedUnknownEvidenceTests(IndependentUnknownSchemaTests):
    def native_origin(self):
        position = dict(path=self.unit, buffer_sha256='a' * 64, begin=0, end=1, bytes_hex='66')
        return dict(spelling=position, expansion=copy.deepcopy(position), presumed=dict(path=self.unit, line=1))

    def test_legitimate_nested_unproved_signature_and_native_origin(self):
        definition = self.reports[0]['unclassified_definitions'][0]
        definition.update(location=self.native_origin(), signature=dict(canonical={'unproved': 'unsupported type or wrapper limit'},
                          const=False, volatile=False, restrict=False))
        self.assertEqual(self.preserve()['count'], 1)
        definition['location']['spelling'] = {'unproved': 'invalid end of token'}
        self.assertEqual(self.preserve()['count'], 1)

    def test_empty_wrong_extra_and_mixed_evidence_tags(self):
        original = copy.deepcopy(self.reports)
        for field in ('location', 'signature'):
            for value in ({}, {'Unproved': 'reason'}, {'unproved': 'reason', 'extra': 1},
                          {'unproved': 'reason', 'canonical': {'kind': 'Int'}}, {'proved': True}):
                self.reports = copy.deepcopy(original)
                self.reject_definition(lambda d: d.update({field: value}), 'location evidence|signature must remain')

    def test_unproved_reasons_require_nonempty_strings(self):
        original = copy.deepcopy(self.reports)
        for field in ('location', 'signature'):
            for value in (True, False, None, 1, [], {}, '', '  '):
                self.reports = copy.deepcopy(original)
                self.reject_definition(lambda d: d.update({field: {'unproved': value}}), 'location evidence|signature must remain')

    def test_signature_wrapper_tags_and_qualifier_types_are_closed(self):
        original = copy.deepcopy(self.reports)
        valid = dict(canonical={'unproved': 'unsupported type or wrapper limit'}, const=False, volatile=False, restrict=False)
        bad = [dict(valid, extra=True), dict(valid, unproved='reason'), dict(valid, canonical={}),
               dict(valid, canonical={'unproved': True}), dict(valid, canonical={'unproved': ''})]
        for key in valid:
            value = copy.deepcopy(valid)
            value.pop(key)
            bad.append(value)
        for key in ('const', 'volatile', 'restrict'):
            for scalar in (0, 1, '', None, [], {}):
                bad.append(dict(valid, **{key: scalar}))
        for value in bad:
            self.reports = copy.deepcopy(original)
            self.reject_definition(lambda d: d.update(signature=value), 'signature must remain')

    def test_known_and_proved_signatures_cannot_claim_unknown_state(self):
        original = copy.deepcopy(self.reports)
        for value in ({'proved': {'kind': 'Int'}}, {'canonical': {'kind': 'Int'}, 'const': False, 'volatile': False, 'restrict': False},
                      {'canonical': {'variadic': False, 'parameters': [], 'return': {'kind': 'Int'}},
                       'const': False, 'volatile': False, 'restrict': False}):
            self.reports = copy.deepcopy(original)
            self.reject_definition(lambda d: d.update(signature=value), 'signature must remain')

    def test_native_location_nested_tags_are_closed(self):
        original = copy.deepcopy(self.reports)
        for key in ('spelling', 'expansion', 'presumed'):
            for value in ({}, True, [], {'unproved': ''}, {'unproved': True}, {'unproved': 'reason', 'path': self.unit}):
                self.reports = copy.deepcopy(original)
                origin = self.native_origin()
                origin[key] = value
                self.reject_definition(lambda d: d.update(location=origin), 'location evidence')
        for key in ('spelling', 'expansion', 'presumed'):
            self.reports = copy.deepcopy(original)
            origin = self.native_origin()
            origin.pop(key)
            self.reject_definition(lambda d: d.update(location=origin), 'location evidence')
        self.reports = copy.deepcopy(original)
        self.reject_definition(lambda d: d.update(location=dict(self.native_origin(), extra=True)), 'location evidence')

    def test_native_positions_require_typed_consistent_ranges(self):
        original = copy.deepcopy(self.reports)
        for key, values in [('path', ['', True, None]), ('buffer_sha256', ['', 'g' * 64, True]),
                            ('begin', [True, -1, 2, '0']), ('end', [True, -1, 2**63, '1']),
                            ('bytes_hex', [True, 'f', 'gg', 'ffff'])]:
            for value in values:
                self.reports = copy.deepcopy(original)
                origin = self.native_origin()
                origin['spelling'][key] = value
                self.reject_definition(lambda d: d.update(location=origin), 'location evidence')
        for key in ('path', 'buffer_sha256', 'begin', 'end', 'bytes_hex'):
            self.reports = copy.deepcopy(original)
            origin = self.native_origin()
            origin['expansion'].pop(key)
            self.reject_definition(lambda d: d.update(location=origin), 'location evidence')
        self.reports = copy.deepcopy(original)
        origin = self.native_origin()
        origin['expansion']['extra'] = 1
        self.reject_definition(lambda d: d.update(location=origin), 'location evidence')

    def test_presumed_location_types_are_exact(self):
        original = copy.deepcopy(self.reports)
        for value in ({'path': True, 'line': 1}, {'path': self.unit, 'line': True},
                      {'path': self.unit, 'line': -1}, {'path': self.unit, 'line': '1'},
                      {'path': self.unit}, {'path': self.unit, 'line': 1, 'extra': 0}):
            self.reports = copy.deepcopy(original)
            origin = self.native_origin()
            origin['presumed'] = value
            self.reject_definition(lambda d: d.update(location=origin), 'location evidence')

    def test_coordinated_state_signature_and_plan_mutation_is_rejected(self):
        self.counts['unknown_definitions'][0]['blockers'] = []
        self.reject_definition(lambda d: d.update(state='Proved', reason='classified', signature={'proved': {'kind': 'Int'}}),
                               'evidence differs')


class CommonPlanReceiptTests(unittest.TestCase):
    def test_report_writer_controls_require_source_discovery_and_execution(self):
        from check_common_plan import check_test_receipts
        names = ['closed_variadic_plan_command_reorder_preserves_owned_plan',
                 'closed_variadic_plan_paged_report_matches_legacy_logical',
                 'closed_variadic_plan_test_only_oracle_propagates_write_failure',
                 'closed_variadic_plan_report_flush_failure_publishes_no_partial_output',
                 'closed_variadic_plan_paged_file_failures_publish_no_partial_output',
                 'closed_variadic_plan_paged_report_giant_native_fact_is_lossless',
                 'closed_variadic_plan_paged_report_giant_text_vectors_and_owner_are_lossless',
                 'closed_variadic_plan_paged_report_caps_abort_before_index']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'c2rust-transpile/src'
            (source / 'c_ast').mkdir(parents=True)
            listing, execution = root / 'listing', root / 'execution'
            def write(source_names, listed, passed):
                (source / 'c_ast/closed_plan_tests.rs').write_text(''.join('fn ' + n + '() {}\n' for n in source_names[:-1]))
                (source / 'program.rs').write_text('fn ' + source_names[-1] + '() {}\n')
                listing.write_text(''.join('tests::' + n + ': test\n' for n in listed))
                execution.write_text(''.join('test tests::' + n + ' ... ok\n' for n in passed))
            write(names, names, names)
            self.assertEqual(check_test_receipts(root, listing, execution)['tests'], sorted(names))
            for name in names:
                reduced = [n for n in names if n != name]
                for source_names, listed, passed in [(reduced, reduced, reduced),
                                                      (names, reduced, names), (names, names, reduced)]:
                    with self.subTest(name=name, source=source_names, listing=listed, execution=passed):
                        write(source_names, listed, passed)
                        with self.assertRaises(ValueError):
                            check_test_receipts(root, listing, execution)


if __name__ == '__main__':
    unittest.main()
