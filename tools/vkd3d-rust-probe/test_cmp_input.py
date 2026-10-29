import argparse
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
import signal
import shutil
from unittest.mock import patch

import cmp_input as boundary
import run_cmp_input as wrapper
from run_cmp_input import checked_prepared, hosted, validate_result, DIRECTED


class CmpInputTests(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get('CMP_INPUT_TEST_TMP')
        self.temporary = tempfile.TemporaryDirectory(prefix='cmp-input-test-', dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'native/source'
        self.source.mkdir(parents=True)
        (self.source / 'libs/vkd3d-shader').mkdir(parents=True)
        self.reviewed = boundary.reviewed_contract()
        self.original = (b'static uint32_t spirv_get_type_id(struct spirv_compiler *compiler);\n'
                         b'static uint32_t spirv_compiler_get_constant_float_vector(struct spirv_compiler *compiler);\n'
                         b'static void spirv_compiler_emit_movc(void)\n{\n'
                         + self.reviewed['patches']['zero-first']['before'].encode()
                         + b'\n}\n\nstatic void next(void) {}\n')
        (self.source / boundary.SITE).write_bytes(self.original)
        (self.source / 'include').mkdir()
        (self.source / 'include/config.h').write_text('#define TEST 1\n')
        for key in ('hdr', 'spv'):
            directory = self.source.parent / key / 'include'
            directory.mkdir(parents=True)
            (directory / 'fixture.h').write_text('/* inert fixture */\n')
        self.library = self.root / 'oracle.data'
        self.library.write_bytes(b'INERT ORACLE DATA; NEVER EXECUTE')
        self.owned = self.root / 'owned'
        self.owned.mkdir()
        self.calls = 0
        self.contract = copy.deepcopy(self.reviewed)
        self.contract['source_sha256'] = boundary.sha(self.original)
        self.contract['source_size'] = len(self.original)
        self.contract['manifests'] = {'source': boundary.regular_tree(self.source),
            **{key: boundary.regular_tree(self.source.parent / key / 'include') for key in ('hdr', 'spv')}}
        identity = boundary.file_identity(self.library)
        self.contract['native_library'] = {k: identity[k] for k in ('sha256', 'size')}
        for data in self.contract['patches'].values():
            data['normalized_sha256'] = boundary.sha(self.original.replace(data['before'].encode(), data['after'].encode()))

    def normalize(self, **kwargs):
        self.calls += 1
        name = 'input' if self.calls == 1 else 'attempt-' + str(self.calls)
        with patch.object(boundary, 'reviewed_contract', return_value=self.contract):
            return boundary.normalize(self.source, self.contract['target'], self.library,
                                      self.owned / name, self.owned, **kwargs)

    def baseline(self):
        receipt = self.normalize()
        self.assertEqual(receipt['state'], 'ready')
        self.assertEqual((self.source / boundary.SITE).read_bytes(), self.original)
        self.assertEqual(self.library.read_bytes(), b'INERT ORACLE DATA; NEVER EXECUTE')
        self.assertFalse((self.owned / 'input/INCOMPLETE').exists())
        return receipt

    def test_copy_is_exact_except_reviewed_site_and_original_stays_unchanged(self):
        receipt = self.baseline()
        before = receipt['original_manifests']
        after = receipt['normalized_manifests']
        changed = [(key, name) for key in before for name in before[key] if before[key][name] != after[key][name]]
        self.assertEqual(changed, [('source', boundary.SITE)])
        c = (self.owned / 'input/source' / boundary.SITE).read_bytes()
        self.assertLess(c.index(b'uint32_t cmp_zero_id'), c.index(b'uint32_t cmp_bool_type_id'))
        self.assertEqual(c.count(b'= spirv_get_type_id('), 1)
        self.assertEqual(c.count(b'= spirv_compiler_get_constant_float_vector('), 1)
        self.assertEqual(c.replace(self.contract['patches']['zero-first']['after'].encode(),
                                   self.contract['patches']['zero-first']['before'].encode()), self.original)

    def test_opposite_control_is_type_first_and_marked_diagnostic(self):
        receipt = self.normalize(opposite_control=True)
        c = (self.owned / 'input/source' / boundary.SITE).read_bytes()
        self.assertTrue(receipt['diagnostic_opposite_control'])
        self.assertLess(c.index(b'uint32_t cmp_bool_type_id'), c.index(b'uint32_t cmp_zero_id'))
        self.assertEqual(receipt['target'], self.reviewed['target'])

    def test_reviewed_loader_refuses_fake_or_modified_contract(self):
        self.baseline()
        candidate = self.root / 'fake.json'
        candidate.write_text(json.dumps(self.contract))
        with self.assertRaisesRegex(ValueError, 'unknown or modified'):
            boundary.reviewed_contract(candidate)
        self.assertEqual(boundary.reviewed_contract()['id'], self.reviewed['id'])

    def test_unknown_target_fails_before_output(self):
        self.baseline()
        with self.assertRaisesRegex(ValueError, 'target'):
            boundary.normalize(self.source, 'aarch64-apple-darwin', self.library,
                               self.owned / 'unknown', self.owned)
        self.assertFalse((self.owned / 'unknown').exists())

    def test_source_header_config_library_negatives_after_legal_baseline(self):
        self.baseline()
        for path in (self.source / boundary.SITE, self.source / 'include/config.h',
                     self.source.parent / 'hdr/include/fixture.h', self.library):
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            with patch.object(boundary, 'reviewed_contract', return_value=self.contract):
                with self.assertRaisesRegex(ValueError, 'manifest differs|library differs'):
                    boundary.normalize(self.source, self.contract['target'], self.library,
                                       self.owned / 'invalid', self.owned)
            self.assertFalse((self.owned / 'invalid').exists())
            path.write_bytes(original)

    def test_output_reuse_and_outside_owned_root_refuse(self):
        self.baseline()
        with patch.object(boundary, 'reviewed_contract', return_value=self.contract):
            with self.assertRaisesRegex(ValueError, 'fresh direct child'):
                boundary.normalize(self.source, self.contract['target'], self.library,
                                   self.owned / 'input', self.owned)
        with patch.object(boundary, 'reviewed_contract', return_value=self.contract):
            with self.assertRaisesRegex(ValueError, 'fresh direct child'):
                boundary.normalize(self.source, self.contract['target'], self.library,
                                   self.root / 'outside', self.owned)
        self.assertFalse((self.root / 'outside').exists())

    def test_all_input_roots_reject_overlap_before_any_directory_change(self):
        self.baseline()
        roots = [self.source, self.source.parent / 'hdr/include', self.source.parent / 'spv/include']
        for root in roots:
            empty = root / 'already-empty'
            empty.mkdir()
            for parent in (root, empty, root.parent):
                with self.subTest(root=root, parent=parent):
                    before = {str(p): boundary.regular_tree(p) for p in roots}
                    members = {str(p): sorted(str(q.relative_to(p)) for q in p.rglob('*')) for p in roots}
                    output = parent / 'must-not-appear'
                    with patch.object(boundary, 'reviewed_contract', return_value=self.contract):
                        with self.assertRaisesRegex(ValueError, 'overlaps input root'):
                            boundary.normalize(self.source, self.contract['target'], self.library, output, parent)
                    self.assertFalse(output.exists())
                    self.assertEqual({str(p): boundary.regular_tree(p) for p in roots}, before)
                    self.assertEqual({str(p): sorted(str(q.relative_to(p)) for q in p.rglob('*')) for p in roots}, members)

    def test_extra_missing_symlink_and_mode_source_negatives(self):
        self.baseline()
        extra = self.source / 'extra.h'
        extra.write_text('extra')
        with self.assertRaisesRegex(ValueError, 'manifest differs'):
            self.normalize()
        extra.unlink()
        extra.symlink_to(self.library)
        with self.assertRaisesRegex(ValueError, 'nonregular'):
            self.normalize()
        extra.unlink()
        config = self.source / 'include/config.h'
        config.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'manifest differs'):
            self.normalize()
        config.unlink()
        with self.assertRaisesRegex(ValueError, 'manifest differs'):
            self.normalize()

    def test_changed_patch_unknown_order_and_duplicate_application_refuse(self):
        self.baseline()
        with self.assertRaisesRegex(ValueError, 'unknown CMP order'):
            boundary.rewrite(self.original, self.contract, 'guess-from-os')
        normalized = boundary.rewrite(self.original, self.contract, 'zero-first')
        with self.assertRaisesRegex(ValueError, 'identity differs'):
            boundary.rewrite(normalized, self.contract, 'zero-first')
        bad = copy.deepcopy(self.contract)
        bad['patches']['zero-first']['after'] += '\n'
        with self.assertRaisesRegex(ValueError, 'patch data differs'):
            boundary.rewrite(self.original, bad, 'zero-first')

    def test_partial_copy_is_closed_failure_and_not_reusable(self):
        self.baseline()
        with patch.object(boundary, 'reviewed_contract', return_value=self.contract):
            with patch.object(boundary.shutil, 'copytree', side_effect=OSError('injected copy failure')):
                with self.assertRaisesRegex(OSError, 'injected'):
                    boundary.normalize(self.source, self.contract['target'], self.library,
                                       self.owned / 'failed', self.owned)
        failed = self.owned / 'failed'
        self.assertTrue((failed / 'INCOMPLETE').is_file())
        self.assertFalse((failed / 'receipt.json').exists())
        self.assertEqual(json.loads((failed / 'failure.json').read_text())['state'], 'failed')

    def test_receipt_publication_failure_restores_incomplete_marker(self):
        self.baseline()
        with patch.object(boundary, 'reviewed_contract', return_value=self.contract):
            with patch.object(boundary.os, 'replace', side_effect=OSError('injected publication failure')):
                with self.assertRaisesRegex(OSError, 'injected publication'):
                    boundary.normalize(self.source, self.contract['target'], self.library,
                                       self.owned / 'publication-failed', self.owned)
        failed = self.owned / 'publication-failed'
        self.assertTrue((failed / 'INCOMPLETE').is_file())
        self.assertFalse((failed / 'receipt.json').exists())
        self.assertEqual(json.loads((failed / 'failure.json').read_text())['state'], 'failed')

    def test_archive_identity_failure_and_hosted_execution_guard(self):
        self.baseline()
        with self.assertRaisesRegex(ValueError, 'ZIP identity'):
            checked_prepared(b'not an archive', self.reviewed)
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}):
            with self.assertRaisesRegex(ValueError, 'hosted Linux only'):
                hosted()

    def wrapper_args(self):
        tool = self.root / 'tool'
        (tool / 'bin').mkdir(parents=True, exist_ok=True)
        (tool / 'bin/c2rust').write_bytes(b'INERT TOOL; NEVER EXECUTE')
        self.contract['tool_manifest'] = boundary.regular_tree(tool)
        return argparse.Namespace(source=self.source, native_library=self.library,
            c2rust=tool / 'bin/c2rust', clang=tool / 'bin/c2rust',
            target=self.contract['target'], artifacts=self.root / 'wrapper-output')

    def wrapper_patches(self, stack, args, invoke=None, *, real_custody=False):
        import apply_c2rust_patch as tool_verifier
        stack.enter_context(patch.object(wrapper, 'hosted'))
        if not real_custody:
            stack.enter_context(patch.object(wrapper, 'enable_custody'))
        stack.enter_context(patch.object(wrapper, 'reviewed_contract', return_value=self.contract))
        stack.enter_context(patch.object(boundary, 'reviewed_contract', return_value=self.contract))
        stack.enter_context(patch.object(tool_verifier, 'verify_tool'))
        stack.enter_context(patch.object(tool_verifier, 'verify_evidence', return_value={
            'patch_sha256': self.contract['compiler_patch_sha256'],
            'modified_source_sha256': dict.fromkeys(range(self.contract['compiler_patch_destinations']))}))
        retained = stack.enter_context(patch.object(tool_verifier, 'retain_tool_identity'))
        launched = stack.enter_context(patch.object(wrapper, 'invoke', side_effect=invoke))
        return retained, launched

    def synthetic_invoke(self, command, cwd, log, timeout):
        log.write_text('INERT MOCKED INVOCATION; NO PROCESS')
        if command[0] == 'rustc':
            log.write_text('INERT MOCK host: ' + self.contract['target'] + '\nhost: ' + self.contract['target'] + '\n')
        else:
            source = Path(command[command.index('--source') + 1])
            output = Path(command[command.index('--artifacts') + 1])
            shutil.copytree(source, output / 'source')
            (output / 'result.json').write_text('{}')
        return {'exit_code': 0, 'timed_out': False, 'custody_status': 'clean'}

    def test_wrapper_legal_baseline_and_full_domain_prewrite_refusals(self):
        args = self.wrapper_args()
        with ExitStack() as stack:
            self.wrapper_patches(stack, args, self.synthetic_invoke)
            stack.enter_context(patch.object(wrapper, 'validate_result', return_value={
                'stable_build': {'exit_code': 101}, 'working_stable_build': {'exit_code': 101}}))
            wrapper.run(args)
        self.assertTrue((args.artifacts / 'output-manifest.json').is_file())
        self.assertEqual(json.loads((args.artifacts / 'report.json').read_text())['status'], 'finite_cmp_boundary_pass')
        domains = [self.source, self.source.parent / 'hdr/include', self.source.parent / 'spv/include',
                   args.c2rust.parent.parent, self.library]
        for domain in domains:
            for destination in (domain, domain.parent, domain / 'NEW'):
                with self.subTest(domain=domain, destination=destination):
                    args.artifacts = destination
                    before = boundary.regular_tree(self.root)
                    members = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
                    with ExitStack() as stack:
                        retained, launched = self.wrapper_patches(stack, args)
                        with self.assertRaises(ValueError):
                            wrapper.run(args)
                    retained.assert_not_called()
                    launched.assert_not_called()
                    self.assertEqual(boundary.regular_tree(self.root), before)
                    self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')), members)

    def test_wrapper_alias_and_changed_input_refuse_without_write_or_launch(self):
        args = self.wrapper_args()
        cases = [('source', self.source), ('native_library', self.library), ('c2rust', args.c2rust)]
        for field, path in cases:
            alias = self.root / (field + '-alias')
            alias.symlink_to(path)
            original = getattr(args, field)
            setattr(args, field, alias)
            before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
            with ExitStack() as stack:
                retained, launched = self.wrapper_patches(stack, args)
                with self.assertRaisesRegex(ValueError, 'alias input'):
                    wrapper.run(args)
            retained.assert_not_called()
            launched.assert_not_called()
            self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')), before)
            setattr(args, field, original)
            alias.unlink()
        for path in (self.source / boundary.SITE, self.source.parent / 'hdr/include/fixture.h',
                     self.source.parent / 'spv/include/fixture.h', self.library, args.c2rust):
            data = path.read_bytes()
            path.write_bytes(data + b'CHANGED')
            before = boundary.regular_tree(self.root)
            members = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
            with ExitStack() as stack:
                retained, launched = self.wrapper_patches(stack, args)
                with self.assertRaisesRegex(ValueError, 'manifest|library differs'):
                    wrapper.run(args)
            retained.assert_not_called()
            launched.assert_not_called()
            self.assertEqual(boundary.regular_tree(self.root), before)
            self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')), members)
            path.write_bytes(data)
        alias = self.root / 'output-alias'
        alias.symlink_to(self.root / 'unused')
        args.artifacts = alias / 'NEW'
        with ExitStack() as stack:
            retained, launched = self.wrapper_patches(stack, args)
            with self.assertRaisesRegex(ValueError, 'alias output'):
                wrapper.run(args)
        retained.assert_not_called()
        launched.assert_not_called()
        self.assertFalse((self.root / 'unused').exists())

    def test_pidfd_preflight_denials_never_launch_and_close_open_descriptor(self):
        args = self.wrapper_args()
        for failure in ('open', 'send'):
            with self.subTest(failure=failure), ExitStack() as stack:
                stack.enter_context(patch.object(wrapper, 'hosted'))
                opened = stack.enter_context(patch.object(wrapper.os, 'pidfd_open', create=True,
                    side_effect=OSError('unsupported') if failure == 'open' else None, return_value=123))
                sent = stack.enter_context(patch.object(wrapper.signal, 'pidfd_send_signal', create=True,
                    side_effect=OSError('denied') if failure == 'send' else None))
                closed = stack.enter_context(patch.object(wrapper.os, 'close'))
                launched = stack.enter_context(patch.object(wrapper.subprocess, 'Popen'))
                libc = stack.enter_context(patch('ctypes.CDLL'))
                with self.assertRaises(OSError):
                    wrapper.invoke(['NEVER EXECUTE'], self.root, self.root / 'never.log', 1)
                opened.assert_called_once_with(os.getpid())
                if failure == 'send':
                    sent.assert_called_once_with(123, 0)
                    closed.assert_called_once_with(123)
                else:
                    closed.assert_not_called()
                launched.assert_not_called()
                libc.assert_not_called()
                self.assertFalse((self.root / 'never.log').exists())
                self.assertFalse((self.root / 'OWNED_WRITERS_UNPROVEN').exists())

    def test_wrapper_pidfd_refusal_precedes_artifact_creation(self):
        args = self.wrapper_args()
        for failure in ('open', 'send'):
            before = boundary.regular_tree(self.root)
            members = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
            with ExitStack() as stack:
                retained, launched = self.wrapper_patches(stack, args)
                stack.enter_context(patch.object(wrapper, 'enable_custody', side_effect=wrapper.preflight_pidfd))
                stack.enter_context(patch.object(wrapper.os, 'pidfd_open', create=True,
                    side_effect=OSError('unsupported') if failure == 'open' else None, return_value=123))
                stack.enter_context(patch.object(wrapper.signal, 'pidfd_send_signal', create=True,
                    side_effect=OSError('denied') if failure == 'send' else None))
                closed = stack.enter_context(patch.object(wrapper.os, 'close'))
                with self.assertRaises(OSError):
                    wrapper.run(args)
                self.assertEqual(closed.call_count, int(failure == 'send'))
            retained.assert_not_called()
            launched.assert_not_called()
            self.assertFalse(args.artifacts.exists())
            self.assertEqual(boundary.regular_tree(self.root), before)
            self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')), members)

    def test_wrapper_header_root_aliases_refuse_without_input_mutation(self):
        args = self.wrapper_args()
        for key in ('hdr', 'spv'):
            directory = self.source.parent / key / 'include'
            saved = directory.with_name('saved')
            directory.rename(saved)
            directory.symlink_to(saved)
            members = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
            data = boundary.regular_tree(saved)
            with ExitStack() as stack:
                retained, launched = self.wrapper_patches(stack, args)
                with self.assertRaisesRegex(ValueError, 'alias input'):
                    wrapper.run(args)
            retained.assert_not_called()
            launched.assert_not_called()
            self.assertEqual(boundary.regular_tree(saved), data)
            self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')), members)
            directory.unlink()
            saved.rename(directory)

    def test_wrapper_cancellation_outside_wait_has_no_final_manifest_and_restores_handlers(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            args = self.wrapper_args()
            args.artifacts = self.root / ('cancel-' + str(signum))
            handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
            def cancel_after_clean_probe(*unused):
                signal.getsignal(signum)(signum, None)
            with ExitStack() as stack:
                self.wrapper_patches(stack, args, self.synthetic_invoke)
                stack.enter_context(patch.object(wrapper, 'validate_result', side_effect=cancel_after_clean_probe))
                with self.assertRaises(KeyboardInterrupt):
                    wrapper.run(args)
            self.assertTrue((args.artifacts / 'CANCELLED').is_file())
            self.assertFalse(list(args.artifacts.rglob('receipt.json')))
            self.assertFalse((args.artifacts / 'output-manifest.json').exists())
            self.assertEqual(json.loads((args.artifacts / 'report.json').read_text())['status'], 'cancelled')
            self.assertEqual({sig: signal.getsignal(sig) for sig in handlers}, handlers)


    def test_wrapper_cancellation_during_manifest_and_after_atomic_publication_is_partial(self):
        for phase in ('hash', 'publish'):
            args = self.wrapper_args()
            args.artifacts = self.root / ('manifest-cancel-' + phase)
            actual_tree, actual_replace = wrapper.regular_tree, wrapper.os.replace
            def manifest_tree(path):
                if Path(path) == args.artifacts:
                    signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
                return actual_tree(path)
            def publish(source, destination):
                actual_replace(source, destination)
                if Path(destination).name == 'output-manifest.json':
                    signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            with ExitStack() as stack:
                self.wrapper_patches(stack, args, self.synthetic_invoke)
                stack.enter_context(patch.object(wrapper, 'validate_result', return_value={
                    'stable_build': {'exit_code': 101}, 'working_stable_build': {'exit_code': 101}}))
                stack.enter_context(patch.object(wrapper, 'regular_tree', side_effect=manifest_tree if phase == 'hash' else actual_tree))
                stack.enter_context(patch.object(wrapper.os, 'replace', side_effect=publish if phase == 'publish' else actual_replace))
                with self.assertRaises(KeyboardInterrupt):
                    wrapper.run(args)
            self.assertTrue((args.artifacts / 'CANCELLED').is_file())
            self.assertFalse(list(args.artifacts.rglob('receipt.json')))
            self.assertFalse((args.artifacts / 'output-manifest.json').exists())
            self.assertFalse((args.artifacts / 'output-manifest.pending').exists())



class CmpValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='cmp-validator-', dir=os.environ.get('CMP_INPUT_TEST_TMP'))
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.contract = copy.deepcopy(boundary.reviewed_contract())
        self.result = {'translation_units': 24, 'complete_translation': True,
            'transpile': {'exit_code': 0, 'timed_out': False},
            'syntax': [{'exit_code': 0, 'timed_out': False} for _ in range(24)],
            'invalid_output_markers': [], 'raw_preserved': True,
            'link': {'status': 'success', 'exit_code': 0, 'timed_out': False},
            'stable_build': {'exit_code': 101}, 'working_stable_build': {'exit_code': 101}}
        for name in ('rust-raw', 'rust', 'rust-working'):
            directory = self.root / name
            directory.mkdir()
            (directory / 'fixture.rs').write_text('// inert synthetic bytes; never compile\n')
            (directory / 'Cargo.toml').write_text('[package]\nname = "fixture"\nversion = "0.0.0"\n[dependencies]\n')
        identity = {k: v['sha256'] for k, v in boundary.regular_tree(self.root / 'rust').items()}
        self.result['raw_sha256'] = identity
        self.result['working_source_identity'] = {'equal': True, 'original_sha256': identity, 'working_sha256': identity}
        (self.root / 'shader-driver').write_bytes(b'INERT; NEVER EXECUTE')
        (self.root / 'compile_commands.json').write_text('[]')
        matrix = self.root / 'matrix'
        matrix.mkdir()
        (matrix / 'fixture.hlsl').write_bytes(b'INERT SYNTHETIC INPUT')
        self.contract['corpus'] = {'fixture.hlsl': {'sha256': boundary.sha(b'INERT SYNTHETIC INPUT'), 'size': len(b'INERT SYNTHETIC INPUT')}}
        positives, negatives = [], []
        for name in self.contract['oracle']:
            negative = name in ('missing_float_controls', 'invalid_pixel_semantic')
            output = b'' if negative else ('synthetic-' + name).encode()
            diagnostic = ((b'E2004' if name == 'missing_float_controls' else b'E5013') if negative else b'')
            status = '-4' if negative else '0'
            for mode in ('native', 'rust'):
                for suffix, data in (('', output), ('.status', status.encode()), ('.diagnostics', diagnostic), ('.log', b'')):
                    (matrix / (name + '.' + mode + suffix)).write_bytes(data)
            self.contract['oracle'][name] = {suffix: {'sha256': boundary.sha(data), 'size': len(data)}
                for suffix, data in (('', output), ('.status', status.encode()), ('.diagnostics', diagnostic), ('.log', b''))}
            step = {'exit_code': 0, 'timed_out': False}
            case = {'name': name, 'native': dict(step), 'rust': dict(step),
                    'return_codes': [status, status], 'status': 'expected_rejection' if negative else 'success'}
            (negatives if negative else positives).append(case)
        self.result['runtime_comparison'] = {'cases': positives, 'negative_controls': negatives}

    def check(self, opposite=False):
        return validate_result(self.root, self.result, self.contract, opposite)

    def test_correct_and_actual_opposite_prediction_checker(self):
        self.assertEqual(self.check()['positive_equal'], 48)
        for case in self.result['runtime_comparison']['cases']:
            if case['name'] in DIRECTED:
                (self.root / 'matrix' / (case['name'] + '.rust')).write_bytes(b'INERT WRONG ORDER BYTES')
                case['status'] = 'mismatch'
        self.assertEqual(self.check(True)['directed_mismatches'], sorted(DIRECTED))
        with self.assertRaisesRegex(ValueError, 'prediction failed'):
            self.check()

    def test_changed_native_raw_output_is_refused(self):
        self.check()
        name = self.result['runtime_comparison']['cases'][0]['name']
        (self.root / 'matrix' / (name + '.native')).write_bytes(b'CHANGED')
        with self.assertRaisesRegex(ValueError, 'immutable native oracle differs'):
            self.check()

    def test_timeout_and_negative_failure_are_refused(self):
        self.check()
        case = self.result['runtime_comparison']['negative_controls'][0]
        case['rust']['timed_out'] = True
        with self.assertRaisesRegex(ValueError, 'matrix process failed'):
            self.check()
        case['rust']['timed_out'] = False
        case['return_codes'] = ['0', '0']
        with self.assertRaisesRegex(ValueError, 'raw API status differs'):
            self.check()

    def test_raw_and_working_copy_tampering_are_refused(self):
        self.check()
        path = self.root / 'rust-raw/fixture.rs'
        original = path.read_bytes()
        path.write_bytes(b'altered generated Rust')
        with self.assertRaisesRegex(ValueError, 'generated source inventory differs'):
            self.check()
        path.write_bytes(original)
        (self.root / 'rust-working/fixture.rs').write_bytes(b'altered compilation copy')
        with self.assertRaisesRegex(ValueError, 'generated source inventory differs'):
            self.check()

    def add_locks(self):
        data = b'version = 4\n[[package]]\nname = "fixture"\nversion = "0.0.0"\n'
        for domain, stage in (('rust-raw', 'stable_build'), ('rust-working', 'working_stable_build')):
            (self.root / domain / 'Cargo.lock').write_bytes(data)
            log = self.root / (stage + '.log')
            log.write_bytes(b'INERT SYNTHETIC BUILD LOG')
            self.result[stage].update(command=['cargo', '+1.95.0', 'build', '--manifest-path',
                                               str(self.root / domain / 'Cargo.toml')],
                timed_out=False, process_exit_code=101, started_utc='synthetic fixture start',
                ended_utc='synthetic fixture end', log=str(log))

    def test_cargo_locks_are_separate_build_outputs_and_sources_remain_exact(self):
        self.check()
        self.add_locks()
        result = self.check()
        self.assertNotIn('Cargo.lock', result['pristine_rust_manifest'])
        self.assertNotIn('Cargo.lock', result['compilation_copy_manifest'])
        self.assertEqual(set(result['cargo_build_outputs']), {'rust-raw', 'rust-working'})
        self.assertEqual(result['cargo_build_outputs']['rust-raw']['parsed']['version'], 4)

    def test_unknown_extra_changed_toml_and_mode_refuse_with_locks(self):
        self.add_locks()
        self.check()
        for domain in ('rust-raw', 'rust-working', 'rust'):
            for name in ('unexpected.data', 'Cargo.toml', 'fixture.rs'):
                path = self.root / domain / name
                before = path.read_bytes() if path.exists() else None
                path.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'inventory differs|compilation copy differs'):
                    self.check()
                if before is None:
                    path.unlink()
                else:
                    path.write_bytes(before)
        path = self.root / 'rust-working/fixture.rs'
        path.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'compilation copy differs'):
            self.check()

    def test_invalid_mismatched_symlink_and_unattempted_build_locks_refuse(self):
        self.add_locks()
        self.check()
        path = self.root / 'rust-working/Cargo.lock'
        original = path.read_bytes()
        for data in (b'invalid toml', b'version = 3\n', original + b'other = "changed"\n'):
            path.write_bytes(data)
            with self.assertRaises((ValueError, KeyError)):
                self.check()
        path.write_bytes(original)
        path.unlink()
        path.symlink_to(self.root / 'rust-raw/Cargo.lock')
        with self.assertRaisesRegex(ValueError, 'nonregular'):
            self.check()
        path.unlink()
        path.write_bytes(original)
        del self.result['working_stable_build']['command']
        with self.assertRaisesRegex(ValueError, 'actual build-stage association'):
            self.check()

    def test_lock_dependency_versions_and_build_domain_are_bound(self):
        self.add_locks()
        for domain in ('rust-raw', 'rust-working', 'rust'):
            path = self.root / domain / 'Cargo.toml'
            path.write_text(path.read_text() + 'dependency = "0.2"\n')
        expected = {k: v['sha256'] for k, v in boundary.regular_tree(self.root / 'rust').items()}
        self.result['raw_sha256'] = expected
        self.result['working_source_identity'].update(original_sha256=expected, working_sha256=expected)
        lock = (b'version = 4\n[[package]]\nname = "fixture"\nversion = "0.0.0"\n'
                b'dependencies = ["dependency"]\n[[package]]\nname = "dependency"\nversion = "0.2.191"\n')
        for domain in ('rust-raw', 'rust-working'):
            (self.root / domain / 'Cargo.lock').write_bytes(lock)
        self.check()
        for domain in ('rust-raw', 'rust-working'):
            (self.root / domain / 'Cargo.lock').write_bytes(lock.replace(b'0.2.191', b'0.3.0'))
        with self.assertRaisesRegex(ValueError, 'dependency version differs'):
            self.check()
        for domain in ('rust-raw', 'rust-working'):
            (self.root / domain / 'Cargo.lock').write_bytes(lock)
        self.result['stable_build']['command'][-1] = str(self.root / 'unrelated/rust-raw/Cargo.toml')
        with self.assertRaisesRegex(ValueError, 'actual build-stage association'):
            self.check()


def signal_custody_case(output, phase, signum, probe):
    import time
    hosted()
    output, probe = Path(output), Path(probe)
    fixture = CmpInputTests()
    fixture.setUp()
    args = fixture.wrapper_args()
    args.artifacts = output / 'actual'
    domains = {**{'source': fixture.source, 'hdr': fixture.source.parent / 'hdr/include',
                 'spv': fixture.source.parent / 'spv/include'}, 'tool': args.c2rust.parent.parent}
    before = {key: boundary.regular_tree(path) for key, path in domains.items()}
    members = {key: sorted(p.relative_to(path).as_posix() for p in path.rglob('*')) for key, path in domains.items()}
    library = boundary.file_identity(fixture.library)
    actual_invoke = wrapper.invoke
    def inert_invoke(command, cwd, log, timeout):
        if command[0] == 'rustc':
            return fixture.synthetic_invoke(command, cwd, log, timeout)
        writers = output / 'nested'
        writers.mkdir()
        execution = actual_invoke([wrapper.sys.executable, '-B', str(probe), str(writers),
                                   'timeout' if phase == 'wait' else 'clean'], output, log, 15)
        source = Path(command[command.index('--source') + 1])
        result = Path(command[command.index('--artifacts') + 1])
        shutil.copytree(source, result / 'source')
        (result / 'result.json').write_text('{}')
        return execution
    def validation(*unused):
        (output / 'signal-ready').write_text('Clean probe wait returned; wrapper validation active.\n')
        time.sleep(15)
        raise ValueError('Expected external signal did not arrive')
    started = wrapper.datetime.now(wrapper.timezone.utc).isoformat()
    try:
        with ExitStack() as stack:
            fixture.wrapper_patches(stack, args, inert_invoke, real_custody=True)
            stack.enter_context(patch.object(wrapper, 'validate_result', side_effect=validation))
            wrapper.run(args)
    except KeyboardInterrupt:
        boundary.require((args.artifacts / 'CANCELLED').is_file()
            and not (args.artifacts / 'output-manifest.json').exists()
            and not list(args.artifacts.rglob('receipt.json'))
            and not (args.artifacts / 'OWNED_WRITERS_UNPROVEN').exists()
            and not wrapper.owned_children(), 'cancelled wrapper published output or retained writers')
        boundary.require({key: boundary.regular_tree(path) for key, path in domains.items()} == before
            and {key: sorted(p.relative_to(path).as_posix() for p in path.rglob('*'))
                 for key, path in domains.items()} == members
            and boundary.file_identity(fixture.library) == library, 'cancelled wrapper changed immutable inputs')
        (output / 'signal-result.json').write_text(json.dumps({'status': 'cancelled_closed_partial',
            'pid': os.getpid(), 'session': os.getsid(0), 'signal': signum, 'phase': phase,
            'started_utc': started, 'ended_utc': wrapper.datetime.now(wrapper.timezone.utc).isoformat(),
            'original_manifests': before, 'original_members': members, 'native_identity': library}, indent=2) + '\n')
        raise SystemExit(130)
    raise ValueError('Cancelled wrapper unexpectedly completed')


def signal_custody_test(output, probe):
    import subprocess
    import sys
    import time
    receipts = {}
    for phase in ('wait', 'after-wait'):
        for signum in (signal.SIGINT, signal.SIGTERM):
            root = output / (phase + '-' + str(signum))
            root.mkdir()
            command = [sys.executable, '-B', *(['-O'] if sys.flags.optimize else []), str(Path(__file__).resolve()),
                       '--signal-case', str(root), phase, str(signum), str(probe)]
            started = wrapper.datetime.now(wrapper.timezone.utc).isoformat()
            marker = root / 'OWNED_WRITERS_UNPROVEN'
            marker.write_text('Hosted signal-fixture writers not yet proven closed.\n')
            with (root / 'wrapper.log').open('w') as stream:
                process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                descriptor = os.pidfd_open(process.pid)
                try:
                    deadline = time.monotonic() + 10
                    while not ((root / 'signal-ready').exists() if phase == 'after-wait'
                               else list((root / 'nested').glob('*.identity'))):
                        boundary.require(process.poll() is None and time.monotonic() < deadline,
                                         'signal fixture did not reach requested wrapper phase')
                        time.sleep(0.01)
                    signal.pidfd_send_signal(descriptor, signum)
                    process.wait(timeout=15)
                finally:
                    os.close(descriptor)
                    descendants = wrapper.close_owned_children(process)
                    boundary.require(not wrapper.owned_children(), 'signal fixture cleanup unproven')
                    marker.unlink()
                    boundary.require(not descendants, 'signal fixture required forced cleanup; no acceptance')
            boundary.require(process.returncode == 130 and not wrapper.owned_children(), 'signal wrapper not closed')
            result = json.loads((root / 'signal-result.json').read_text())
            boundary.require(result['pid'] == process.pid and result['signal'] == signum
                             and result['phase'] == phase, 'signal identity/phase differs')
            closed = json.loads((root / 'actual/correct-probe.log.custody.json').read_text())
            boundary.require(closed['owned_writers_closed'], 'nested probe lacks closure receipt')
            identities = [json.loads(path.read_text()) for path in (root / 'nested').glob('*.identity')]
            reaped = {row['pid'] for row in closed['owned_descendants_reaped']}
            boundary.require(phase != 'wait' or identities, 'wait cancellation missed actual writer')
            for identity in identities:
                boundary.require(identity['pid'] in reaped and identity['pid'] == identity['session'],
                                 'cancelled separate-session writer lacks reap receipt')
                try:
                    os.kill(identity['pid'], 0)
                except ProcessLookupError:
                    pass
                else:
                    raise ValueError('cancelled writer remains live')
            boundary.require(not (root / 'actual/output-manifest.json').exists()
                             and not list(root.rglob('OWNED_WRITERS_UNPROVEN')), 'cancelled final publication')
            before = boundary.regular_tree(root)
            time.sleep(0.2)
            boundary.require(boundary.regular_tree(root) == before, 'cancelled outputs changed after terminal custody')
            receipts[root.name] = {'command': command, 'cwd': str(Path.cwd()), 'pid': process.pid,
                'started_utc': started, 'ended_utc': wrapper.datetime.now(wrapper.timezone.utc).isoformat(),
                'exit_code': process.returncode, 'log_identity': boundary.file_identity(root / 'wrapper.log'),
                'result': result, 'closure': closed, 'writer_identities': identities,
                'closed_partial_manifest': before, 'unchanged_after_seconds': 0.2}
            (output / (root.name + '-receipt.json')).write_text(json.dumps(receipts[root.name], indent=2) + '\n')
    return receipts


def process_custody_test(output):
    import sys
    import time
    from run_cmp_input import invoke, owned_children
    hosted()
    output = Path(output)
    if output.exists():
        raise ValueError('process test output must be new')
    output.mkdir()
    fixture = output / 'inert_probe.py'
    fixture.write_text('''import json, os, subprocess, sys, time
from pathlib import Path
root = Path(sys.argv[1])
mode = sys.argv[2]
if mode == 'writer':
    identity = {'pid': os.getpid(), 'session': os.getsid(0), 'started_ns': time.time_ns()}
    (root / (str(os.getpid()) + '.identity')).write_text(json.dumps(identity))
    with (root / (str(os.getpid()) + '.writes')).open('ab', buffering=0) as stream:
        while True:
            stream.write(b'inert task-only writer\\n')
            time.sleep(0.01)
elif mode == 'clean':
    pass
else:
    children = []
    for index in range(3 if mode == 'race' else 1):
        children.append(subprocess.Popen([sys.executable, '-B', __file__, str(root), 'writer'], start_new_session=True))
        if mode == 'race':
            time.sleep(0.07)
    deadline = time.monotonic() + 3
    while not list(root.glob('*.identity')) and time.monotonic() < deadline:
        time.sleep(0.01)
    if not list(root.glob('*.identity')):
        raise SystemExit('writer launch failed')
    if mode == 'orphan':
        raise SystemExit(0)
    time.sleep(10)
''')
    receipts = {}
    for mode in ('clean', 'orphan', 'timeout', 'race'):
        root = output / mode
        root.mkdir()
        receipt = invoke([sys.executable, '-B', str(fixture), str(root), mode], output,
                         root / 'probe.log', 0.18 if mode == 'race' else 0.8)
        boundary.require(receipt['owned_writers_closed'] and not owned_children(), 'owned children not closed')
        if mode == 'clean':
            boundary.require(receipt['custody_status'] == 'clean' and not receipt['timed_out'], 'clean fixture failed')
        elif mode == 'orphan':
            boundary.require(receipt['custody_status'] == 'contaminated' and not receipt['timed_out'],
                             'unexpected normal orphan was silently accepted')
        else:
            boundary.require(receipt['timed_out'], 'fixture did not time out')
        identities = [json.loads(path.read_text()) for path in root.glob('*.identity')]
        if mode in ('orphan', 'timeout'):
            boundary.require(identities, 'fixture writer did not start')
        reaped = {record['pid'] for record in receipt['owned_descendants_reaped']}
        for identity in identities:
            boundary.require(identity['pid'] in reaped and identity['pid'] == identity['session'],
                             'separate-session writer missing terminal receipt')
            try:
                os.kill(identity['pid'], 0)
            except ProcessLookupError:
                pass
            else:
                raise ValueError('writer still live after terminal custody receipt')
        before = boundary.regular_tree(root)
        time.sleep(0.2)
        boundary.require(boundary.regular_tree(root) == before, 'writes continued after terminal custody receipt')
        receipts[mode] = {'execution': receipt, 'writer_identities': identities,
                          'closed_partial_manifest': before, 'unchanged_after_seconds': 0.2}
        (output / (mode + '-receipt.json')).write_text(json.dumps(receipts[mode], indent=2) + '\n')
    signals = signal_custody_test(output, fixture)
    (output / 'result.json').write_text(json.dumps({'status': 'owned_process_test_pass',
        'cases': receipts, 'signal_cancellation': signals}, indent=2) + '\n')


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 6 and sys.argv[1] == '--signal-case':
        signal_custody_case(sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5])
    elif len(sys.argv) == 3 and sys.argv[1] == '--process-custody':
        process_custody_test(sys.argv[2])
    else:
        unittest.main()
