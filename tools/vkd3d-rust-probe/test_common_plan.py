import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from check_common_plan import canonical, validate_plan


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
        declaration = dict(id=7, key=dict(unit=identity['key'], declaration=7), name='fixture', definition=True, signature=dict(shape={'Unknown': 'Attributed'}),
                           blockers=['UnknownSignature'])
        call = dict(id=9, key=dict(unit=identity['key'], expression=9), owner=dict(unit=identity['key'], declaration=7), direct=7, disposition={'Deferred': ['UnknownSignature']})
        self.plan = dict(status='ClosedDiagnosticPlan', lowering='not_authorized', units=[dict(identity=identity,
            native_ast_exports=1, typed_imports=1, source_sha256=sources, declarations=[declaration], calls=[call])])
        self.assertEqual(validate_plan(self.plan, [self.row])['units'], 1)

    def cleanup_fixture(self):
        for path in self.root.iterdir():
            path.unlink()
        self.root.rmdir()

    def reject(self, mutation, reason):
        changed = copy.deepcopy(self.plan)
        mutation(changed['units'][0])
        with self.assertRaisesRegex(ValueError, reason):
            validate_plan(changed, [self.row])

    def test_effective_command_and_source_binding(self):
        self.reject(lambda u: u['identity'].update(command='b' * 64), 'effective-command binding')
        self.reject(lambda u: u['identity'].update(source='/different.c'), 'effective-command binding')

    def test_target_and_ast_instance_binding(self):
        self.reject(lambda u: u['identity'].update(target='other-target'), 'UnitKey differs')
        self.reject(lambda u: u['identity'].update(ast_instance='unknown'), 'AST instance digest')
        self.reject(lambda u: u['identity'].update(widths=[0] * 8), 'target facts')

    def test_original_buffer_is_checked_without_identity_mocks(self):
        Path(self.row['file']).write_text('changed\n')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            validate_plan(self.plan, [self.row])

    def test_complete_universe_and_exact_node_membership(self):
        with self.assertRaisesRegex(ValueError, 'command universe'):
            validate_plan(dict(self.plan, units=[]), [self.row])
        self.reject(lambda u: u['declarations'].append(u['declarations'][0]), 'declaration ID')
        self.reject(lambda u: u['calls'][0].update(direct=99), 'unknown declaration')
        self.reject(lambda u: u['declarations'][0]['key'].update(unit='other-unit'), 'semantic scope')
        self.reject(lambda u: u['calls'][0]['key'].update(expression=10), 'semantic scope')

    def test_unknown_signatures_remain_blocked(self):
        self.reject(lambda u: u['declarations'][0].update(blockers=[]), 'lost its blocker')
        self.reject(lambda u: u['calls'][0].update(disposition='Lower'), 'call disposition')

    def test_native_counts_are_not_substituted_by_reimports(self):
        self.reject(lambda u: u.update(typed_imports=2), 'export/import count')
        self.reject(lambda u: u.update(native_ast_exports=0), 'export/import count')


if __name__ == '__main__':
    unittest.main()
