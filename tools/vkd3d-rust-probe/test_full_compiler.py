import contextlib
import io
import json
import os
import shutil
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import full_compiler as full
import probe
import shader_matrix
import validate

PARSER = '''pub type size_t = usize;
pub struct parse_initializer {
    pub args_count: ::core::ffi::c_uint,
}
pub struct hlsl_attribute {
    pub args_count: ::core::ffi::c_uint,
    pub args: [hlsl_src; 0],
}
let size = offset_of!(
    hlsl_attribute, args[(* yyvsp.offset(- 2isize)).initializer
    .args_count as usize]
) as size_t;
'''


class FullCompilerTests(unittest.TestCase):
    def collect_fixture(self, root, invalid=None, valid_new=False, working_success=False):
        artifacts = root / 'artifacts'
        artifacts.mkdir()
        output = artifacts / 'rust'
        shutil.copytree(Path(__file__).parent / 'full-compiler-fixtures/generated', output)
        parser = output / 'src/vkd3d_shader/hlsl_tab.rs'
        if invalid == 'missing':
            parser.unlink()
        elif invalid == 'ambiguous':
            shutil.copy2(parser, output / 'src/hlsl_tab.rs')
        elif invalid in ('outside', 'inside'):
            target = root / 'hlsl_tab.rs' if invalid == 'outside' else output / 'src/parser-target.rs'
            parser.rename(target)
            parser.symlink_to(target)
        if valid_new:
            parser.write_text('pub unsafe extern "C" fn new_generator_output() {}\n')
        before = {p.relative_to(output): full.digest(p) for p in output.rglob('*') if p.is_file()}
        calls = []

        def execute(command, log, **kwargs):
            calls.append(log.stem)
            log.write_text('')
            if log.stem in ('cargo-stable', 'cargo-working-stable'):
                self.assertNotIn('RUSTC_BOOTSTRAP', kwargs['env'])
                self.assertNotIn('RUSTFLAGS', kwargs['env'])
            if working_success and log.stem == 'cargo-working-stable':
                return {'exit_code': 0}
            return {'exit_code': 101 if log.stem.startswith('cargo-') else 0}

        result = {}
        full.collect(result, SimpleNamespace(rust_toolchain='1.95.0', build_timeout=5),
                     root, output, [{'arguments': ['clang', '-c', 'fixture.c']}], artifacts,
                     execute, lambda: None)
        self.assertEqual(before, {p.relative_to(output): full.digest(p)
                                  for p in output.rglob('*') if p.is_file()})
        return result, calls, artifacts

    def test_new_generator_output_reaches_working_build_without_source_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, artifacts = self.collect_fixture(Path(directory), valid_new=True)
            self.assertNotIn('working_copy_failure', result)
            self.assertTrue(result['working_source_identity']['equal'])
            self.assertEqual(full.source_manifest(artifacts / 'rust'),
                             full.source_manifest(artifacts / 'rust-working'))
            self.assertIn('cargo-working-stable', calls)
            self.assertEqual(result['stable_build']['exit_code'], 101)
            self.assertEqual(result['working_stable_build']['exit_code'], 101)
            self.assertEqual(result['bootstrap_build']['exit_code'], 101)
            self.assertEqual(result['prototype_build']['exit_code'], 101)
            self.assertEqual(probe.outcome(dict(result, complete_translation=True,
                             transpile={'exit_code': 0})), 'compiler_failure')

    def test_working_stable_success_skips_bootstrap_and_preserves_raw_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, _ = self.collect_fixture(Path(directory), working_success=True)
            self.assertEqual(result['stable_build']['exit_code'], 101)
            self.assertEqual(result['working_stable_build']['exit_code'], 0)
            self.assertNotIn('cargo-bootstrap', calls)
            self.assertNotIn('cargo-prototype', calls)
            self.assertEqual(probe.outcome(dict(result, complete_translation=True,
                             transpile={'exit_code': 0})), 'linker_failure')

    def test_changed_working_copy_is_rejected_before_build(self):
        copytree = shutil.copytree
        def corrupt(source, target, *args, **kwargs):
            result = copytree(source, target, *args, **kwargs)
            if Path(target).name == 'rust-working':
                (Path(target) / 'lib.rs').write_text('changed source')
            return result
        with tempfile.TemporaryDirectory() as directory, patch.object(full.shutil, 'copytree', corrupt):
            result, calls, _ = self.collect_fixture(Path(directory))
            self.assertFalse(result['working_source_identity']['equal'])
            self.assertIn('manifest differs', result['working_copy_failure'])
            self.assertEqual(calls, ['cargo-stable'])

    def test_missing_or_ambiguous_nested_parser_stops_before_working_build(self):
        for invalid in ('missing', 'ambiguous'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                result, calls, artifacts = self.collect_fixture(Path(directory), invalid)
                self.assertIn('missing, ambiguous, or outside-owned generated parser', result['working_copy_failure'])
                self.assertEqual(calls, ['cargo-stable'])
                self.assertNotIn('working_stable_build', result)

    def test_collect_rejects_outside_parser_before_copy_and_working_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, calls, artifacts = self.collect_fixture(root, 'outside')
            self.assertIn('outside-owned generated parser', result['working_copy_failure'])
            self.assertEqual(calls, ['cargo-stable'])
            self.assertNotIn('working_stable_build', result)
            self.assertFalse((artifacts / 'rust-working').exists())
            parser = artifacts / 'rust/src/vkd3d_shader/hlsl_tab.rs'
            self.assertTrue(parser.is_symlink())
            fixture = Path(__file__).parent / 'full-compiler-fixtures/generated/src/vkd3d_shader/hlsl_tab.rs'
            self.assertEqual((root / 'hlsl_tab.rs').read_bytes(), fixture.read_bytes())

    def test_collect_accepts_parser_symlink_inside_owned_output(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, _ = self.collect_fixture(Path(directory), 'inside')
            self.assertNotIn('working_copy_failure', result)
            self.assertTrue(result['working_source_identity']['equal'])
            self.assertIn('cargo-working-stable', calls)

    def test_outside_generated_parser_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            working = root / 'working'
            (working / 'src').mkdir(parents=True)
            outside = root / 'hlsl_tab.rs'
            outside.write_text(PARSER)
            (working / 'src/hlsl_tab.rs').symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'outside-owned'):
                full.generated_parser(working)
            self.assertEqual(outside.read_text(), PARSER)

    def test_stable_environment_clears_inherited_experimental_flags(self):
        with patch.dict(os.environ, {key: 'injected' for key in (
            'RUSTC_BOOTSTRAP', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC_WRAPPER',
            'RUSTC_WORKSPACE_WRAPPER', 'RUSTDOCFLAGS')}):
            env = full.stable_env(Path('/tmp/probe-target'))
        for key in ('RUSTC_BOOTSTRAP', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC_WRAPPER'):
            self.assertNotIn(key, env)

    def test_all_unit_outcomes_require_link_and_real_comparison(self):
        result = {'all_unit_prototype': True, 'complete_translation': True,
                  'transpile': {'exit_code': 0}, 'stable_build': {'exit_code': 101},
                  'bootstrap_build': {'exit_code': 0}}
        self.assertEqual(probe.outcome(result), 'linker_failure')
        result['link'] = {'status': 'success'}
        self.assertEqual(probe.outcome(result), 'runtime_unverified')
        result['runtime_comparison'] = {'status': 'success'}
        self.assertEqual(probe.outcome(result), 'prototype_success')

    def test_validator_checks_exact_inventory_not_count_and_rejects_prototype(self):
        result = {'all_unit_prototype': True, 'status': 'prototype_success', 'complete_translation': True,
                  'transpile': {'exit_code': 0}, 'stable_build': {'exit_code': 101},
                  'working_stable_build': {'exit_code': 0}, 'link': {'status': 'success'},
                  'runtime_comparison': {'status': 'success'},
                  'input_sha256': {unit: 'hash' for unit in full.UNITS},
                  'translated_sources': list(full.UNITS), 'syntax': [{'exit_code': 0}] * 24}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'result.json'
            for wrong_inventory in (False, True):
                if wrong_inventory:
                    result['input_sha256']['libs/vkd3d-shader/imposter.c'] = result['input_sha256'].pop(full.UNITS[0])
                path.write_text(json.dumps(result))
                with patch('sys.argv', ['validate.py', str(path), '--all-units']), contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(validate.main(), 1)
                self.assertIn('incomplete' if wrong_inventory else 'prototype_success', output.getvalue())

    def test_matching_native_rejections_are_not_runtime_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = root / 'native.so'
            library.touch()
            def reject(command, log, **kwargs):
                output = Path(command[4])
                output.write_bytes(b'')
                Path(str(output) + '.status').write_text('-4')
                Path(str(output) + '.diagnostics').write_text('rejected')
                return {'exit_code': 0}
            result = shader_matrix.compare(root / 'driver', library, root, reject)
            self.assertEqual(len(result['cases']), 48)
            self.assertEqual(result['status'], 'comparison_failure')
            self.assertTrue(all(case['status'] == 'compile_failure' for case in result['cases']))



def native_inputs_fixture(source, target):
    import hashlib
    def record(role, identifier, data, path=''):
        return {'role': role, 'identifier': identifier, 'physical_path': path,
                'aliases': [path] if path else [], 'native_device': '1' if path else '0',
                'native_file': '2' if path else '0', 'length': len(data), 'bytes_hex': data.hex(),
                'sha256': hashlib.sha256(data).hexdigest(), 'lexed': True,
                'lexer_file_ids': ['1' if role == 'main' else '2']}
    return {'schema': 2, 'main_input': str(source), 'cwd': str(source.parent),
            'adjusted_driver_argv': ['clang', '-resource-dir=/llvm/lib/clang/18', str(source)],
            'regenerated_cc1_argv': ['-triple', target], 'target': target, 'cpu': '', 'abi': '',
            'features': [], 'features_as_written': [], 'vfs': 'clangtool_empty_overlay_on_real_filesystem', 'unsupported': [],
            'lexer_events': [{'file_id': str(i), 'reason': 'enter', 'characteristic': 0} for i in (1, 2)],
            'buffers': [record('main', str(source), source.read_bytes(), str(source)),
                        record('predefines', '<built-in>', b'#define __clang__ 1\n')]}


class CursorBindingTests(unittest.TestCase):
    def fixture(self, root):
        from test_closed_variadic_plan import CursorWitnessTests
        root = root.resolve()
        inv, witness, symbol = CursorWitnessTests().fixture()
        source = root / 'pilot.c'
        source.write_text('/* synthetic binding fixture */\n')
        inv['unit'] = witness['unit'] = symbol['unit'] = str(source)
        witness['native_inputs'] = native_inputs_fixture(source, inv['target'])
        database = root / 'compile_commands.json'
        database.write_text(json.dumps([{'file': str(source), 'directory': str(root),
                                        'arguments': ['clang', '-c', str(source)]}]))
        tool = root / 'tool/bin/c2rust-transpile'
        tool.parent.mkdir(parents=True)
        tool.write_bytes(b'synthetic exporter identity')
        from apply_c2rust_patch import REVISION, patch_destinations
        tool.with_name('c2rust').write_bytes(b'synthetic driver identity')
        evidence = tool.parent.parent / 'source-evidence'
        evidence.mkdir()
        patch_path = Path(__file__).parent / 'patches/c2rust-win64-abi.patch'
        shutil.copy2(patch_path, evidence / 'c2rust-source.patch')
        sources = {}
        for name in patch_destinations(patch_path):
            path = evidence / 'c2rust-applied-source' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic source binding: ' + name)
            sources[name] = full.digest(path)
        record = {'original_revision': REVISION, 'patch_sha256': full.digest(patch_path),
                  'applied_diff_sha256': full.digest(patch_path), 'modified_source_sha256': sources}
        (evidence / 'c2rust-patch.json').write_text(json.dumps(record))
        (tool.parent.parent / 'source-receipt.json').write_text(json.dumps({
            'source_receipt_sha256': full.digest(evidence / 'c2rust-patch.json'),
            'patch_sha256': full.digest(patch_path),
            'binary_sha256': {name: full.digest(tool.with_name(name)) for name in ('c2rust', 'c2rust-transpile')}}))
        output = root / 'raw'
        output.mkdir()
        for suffix, data in [('.variadic.json', json.dumps(inv)), ('.cursor-witness.json', json.dumps(witness)),
                             ('.cursor.cbor', 'synthetic cbor'), ('.typed-ast.txt', 'synthetic typed AST')]:
            (output / ('pilot' + suffix)).write_text(data)
        receipt = full.cursor_witness_receipt(tool, database, output)
        return receipt, symbol

    def test_complete_receipt_binds_every_artifact_and_command(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt, symbol = self.fixture(Path(directory))
            self.assert_binding_valid(receipt, symbol)
            from closed_variadic_plan import PlanError
            with self.assertRaisesRegex(PlanError, 'schema 1 capture'):
                full.prove_bound_cursor_witness(receipt, symbol)
            self.assertEqual(receipt['source_input_consistency'], 'cached_inputs_revalidated')
            self.assertFalse(receipt['authentic_job_proof'])
            self.assertEqual(len(receipt['pairs'][0]['files']), 5)
            self.assertEqual(len(receipt['files']), 3)

    def test_tampered_or_missing_binding_is_rejected(self):
        from copy import deepcopy
        from closed_variadic_plan import PlanError
        with tempfile.TemporaryDirectory() as directory:
            receipt, symbol = self.fixture(Path(directory))
            for index, record in enumerate([receipt, receipt['pairs'][0]]):
                for name in record['files']:
                    with self.subTest(name=name):
                        tampered = deepcopy(receipt)
                        target = tampered if index == 0 else tampered['pairs'][0]
                        target['files'][name] = '0' * 64
                        with self.assertRaises(PlanError): full.prove_bound_cursor_witness(tampered, symbol)
                        del target['files'][name]
                        with self.assertRaises(PlanError): full.prove_bound_cursor_witness(tampered, symbol)
            receipt['pairs'][0]['compile_command']['arguments'].append('-funsigned-char')
            with self.assertRaises(PlanError): full.prove_bound_cursor_witness(receipt, symbol)

    def assert_binding_valid(self, receipt, symbol):
        # Transport check only; the real proof checker must still reject capture.
        with patch('closed_variadic_plan.prove_cursor_witness', return_value='binding-only') as prove:
            self.assertEqual(full.prove_bound_cursor_witness(receipt, symbol), 'binding-only')
            prove.assert_called_once()

    def test_nested_tool_inputs_rechecked_on_every_attempt(self):
        from closed_variadic_plan import PlanError
        with tempfile.TemporaryDirectory() as directory:
            receipt, symbol = self.fixture(Path(directory))
            tool_root = Path(receipt['tool']).parent.parent
            for path in sorted(tool_root.rglob('*')):
                if not path.is_file(): continue
                with self.subTest(path=str(path)):
                    data = path.read_bytes()
                    try:
                        path.write_bytes(data + b'changed')
                        with self.assertRaises(PlanError):
                            full.prove_bound_cursor_witness(receipt, symbol)
                    finally:
                        path.write_bytes(data)
            self.assert_binding_valid(receipt, symbol)

    def test_self_consistent_unreviewed_patch_rejected(self):
        from closed_variadic_plan import PlanError
        with tempfile.TemporaryDirectory() as directory:
            receipt, symbol = self.fixture(Path(directory))
            root = Path(receipt['tool']).parent.parent
            saved = root / 'source-evidence/c2rust-source.patch'
            saved.write_bytes(saved.read_bytes() + b'\n')
            record_path = root / 'source-evidence/c2rust-patch.json'
            record = json.loads(record_path.read_text())
            record['patch_sha256'] = record['applied_diff_sha256'] = full.digest(saved)
            record_path.write_text(json.dumps(record))
            source_receipt = Path(receipt['source_receipt'])
            record = json.loads(source_receipt.read_text())
            record['patch_sha256'] = full.digest(saved)
            record['source_receipt_sha256'] = full.digest(record_path)
            source_receipt.write_text(json.dumps(record))
            receipt['files'][str(source_receipt)] = full.digest(source_receipt)
            with self.assertRaisesRegex(PlanError, 'reviewed patch'):
                full.prove_bound_cursor_witness(receipt, symbol)

    def test_source_pairs_are_bijective(self):
        from copy import deepcopy
        from closed_variadic_plan import PlanError
        with tempfile.TemporaryDirectory() as directory:
            receipt, symbol = self.fixture(Path(directory))
            duplicate = deepcopy(receipt)
            duplicate['pairs'].append(deepcopy(duplicate['pairs'][0]))
            with self.assertRaisesRegex(PlanError, 'unit manifest'):
                full.prove_bound_cursor_witness(duplicate, symbol)
            database = Path(receipt['database'])
            entries = json.loads(database.read_text())
            entries[0]['file'] = 'other.c'
            database.write_text(json.dumps(entries))
            receipt['files'][str(database)] = full.digest(database)
            receipt['pairs'][0]['compile_command'] = entries[0]
            with self.assertRaisesRegex(PlanError, 'command binding'):
                full.prove_bound_cursor_witness(receipt, symbol)

    def test_directory_relative_commands_and_duplicate_canonical_units(self):
        units = full.cursor_command_units([{'directory': '/tmp', 'file': 'pilot.c'}])
        self.assertEqual(set(units), {str(Path('/tmp/pilot.c').resolve())})
        entries = [{'directory': '/tmp', 'file': 'pilot.c'}, {'directory': '/tmp', 'file': './pilot.c'}]
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            full.cursor_command_units(entries)
        with self.assertRaisesRegex(ValueError, 'absolute'):
            full.cursor_command_units([{'directory': '.', 'file': 'pilot.c'}])

    def test_paired_witness_unit_and_target_rechecked(self):
        from closed_variadic_plan import PlanError
        with tempfile.TemporaryDirectory() as directory:
            receipt, symbol = self.fixture(Path(directory))
            pair = receipt['pairs'][0]
            path = Path(pair['witness'])
            original = path.read_text()
            for field in ('unit', 'target'):
                raw = json.loads(original)
                raw[field] = 'different'
                path.write_text(json.dumps(raw))
                pair['files'][str(path)] = full.digest(path)
                with self.assertRaisesRegex(PlanError, 'binding identity'):
                    full.prove_bound_cursor_witness(receipt, symbol)

    def test_all_transported_headers_rechecked_on_every_proof(self):
        from closed_variadic_plan import PlanError
        from copy import deepcopy
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            receipt, symbol = self.fixture(root)
            pair = receipt['pairs'][0]
            path = Path(pair['witness'])
            raw = json.loads(path.read_text())
            for name in ('macro-only.h', 'generated.h', 'forced.h', 'system.h'):
                header = root / name
                header.write_bytes(b'#define EXPORTED_VALUE 1\n')
                record = deepcopy(raw['native_inputs']['buffers'][0])
                record.update(role='file', identifier=name, physical_path=str(header), aliases=[name],
                              native_file=str(len(raw['native_inputs']['buffers']) + 10),
                              bytes_hex=header.read_bytes().hex(), length=len(header.read_bytes()),
                              sha256=full.digest(header))
                record['lexer_file_ids'] = [record['native_file']]
                raw['native_inputs']['lexer_events'].append(
                    {'file_id': record['native_file'], 'reason': 'enter', 'characteristic': 1})
                raw['native_inputs']['buffers'].append(record)
            path.write_text(json.dumps(raw))
            pair['files'][str(path)] = full.digest(path)
            self.assert_binding_valid(receipt, symbol)
            for record in raw['native_inputs']['buffers'][2:]:
                header = Path(record['physical_path'])
                original = header.read_bytes()
                header.write_bytes(original + b'changed')
                with self.assertRaisesRegex(PlanError, 'current input differs'):
                    full.prove_bound_cursor_witness(receipt, symbol)
                header.write_bytes(original)
            self.assert_binding_valid(receipt, symbol)
            raw['native_inputs']['buffers'].pop()
            path.write_text(json.dumps(raw))
            pair['files'][str(path)] = full.digest(path)
            with self.assertRaisesRegex(PlanError, 'unaccounted native lexer event'):
                full.prove_bound_cursor_witness(receipt, symbol)

    def test_native_input_manifest_missing_tampered_or_unsupported_rejects(self):
        from copy import deepcopy
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory).resolve() / 'pilot.c'
            source.write_text('int x;')
            facts = native_inputs_fixture(source, 'x86_64-linux-gnu')
            command = {'directory': str(source.parent)}
            def check(value):
                full.verify_native_cursor_inputs({'native_inputs': value}, str(source), facts['target'], command)
            check(facts)
            for field in facts:
                invalid = deepcopy(facts)
                del invalid[field]
                with self.subTest(missing=field), self.assertRaises((ValueError, KeyError, TypeError)):
                    check(invalid)
            for field, value in [('unsupported', ['pch_or_preamble']), ('vfs', 'unknown'),
                                 ('main_input', '/different.c'), ('target', 'other'),
                                 ('adjusted_driver_argv', []), ('regenerated_cc1_argv', []),
                                 ('lexer_events', []), ('lexer_events', [
                                     {'file_id': '9', 'reason': 'enter', 'characteristic': 0}])]:
                invalid = deepcopy(facts); invalid[field] = value
                with self.subTest(field=field), self.assertRaises(ValueError): check(invalid)
            for field, value in [('bytes_hex', '00'), ('length', True), ('sha256', '0' * 64),
                                 ('lexed', False), ('role', 'unknown'), ('aliases', ['missing.h']),
                                 ('native_file', 'not-a-native-id'), ('lexer_file_ids', ['unknown'])]:
                invalid = deepcopy(facts); invalid['buffers'][0][field] = value
                with self.subTest(buffer=field), self.assertRaises((ValueError, OSError)): check(invalid)
            for buffers in ([], facts['buffers'][:1], facts['buffers'] * 2):
                invalid = deepcopy(facts); invalid['buffers'] = buffers
                with self.assertRaises(ValueError): check(invalid)

    def test_failed_capture_retains_attempted_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for status in (0, 1):
                with self.subTest(status=status):
                    output = root / str(status)
                    def run(command, log, **kwargs):
                        log.write_text('synthetic exporter failure' if status else 'synthetic empty capture')
                        return {'exit_code': status}
                    proof = full.collect_cursor_witness(root / 'missing/bin/c2rust-transpile',
                        root / 'compile_commands.json', output, run, {'unit': '/pilot.c', 'static': 'pilot'})
                    self.assertEqual(proof['status'], 'rejected')
                    self.assertEqual(json.loads((output / 'proof.json').read_text()), proof)
                    self.assertTrue((output / 'export.log').is_file())

class WorkflowFactsCaptureTests(unittest.TestCase):
    def workflow(self):
        repository = Path(__file__).resolve().parents[2]
        workflow = (repository / '.github/workflows/vkd3d-rust-probe.yml').read_text()
        script = workflow.split("          python3 - <<'PY_CAPTURE'\n", 1)[1].split('          PY_CAPTURE\n', 1)[0]
        return repository, workflow, compile('\n'.join(line[10:] for line in script.splitlines()), 'workflow-capture', 'exec')

    def run_capture(self, invalid=None, target=1):
        repository, _, script = self.workflow()
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory).resolve()
            prepared = temporary / 'prepared/work-linux-native/vkd3d-2.1'
            production = prepared / 'libs/vkd3d-shader/spirv.c'
            production.parent.mkdir(parents=True)
            production.write_text('mock production input, never compiled')
            calls = []
            def collect(tool, database, output, execute, symbol):
                entry, = json.loads(database.read_text())
                calls.append((tool, entry, output, execute, symbol))
                raw = output / 'raw/src'
                raw.mkdir(parents=True)
                witness = raw / 'unit.cursor-witness.json'
                bad = invalid if len(calls) - 1 == target else None
                facts = {'schema': 1 if bad == 'schema' else 2,
                         'unit': '/wrong.c' if bad == 'unit' else entry['file'],
                         'native_inputs': {} if bad == 'inputs' else {'mock': True}}
                if bad != 'missing-witness': witness.write_text(json.dumps(facts))
                if bad == 'duplicate-witness': (raw / 'duplicate.cursor-witness.json').write_text(json.dumps(facts))
                for suffix in ('.cursor.cbor', '.typed-ast.txt', '.variadic.json'):
                    if bad != suffix: (raw / ('unit' + suffix)).write_text('mock artifact')
                return {'status': 'rejected'}
            old_cwd = Path.cwd()
            try:
                os.chdir(repository)
                with patch.dict(os.environ, {'RUNNER_TEMP': str(temporary),
                        'MDS_VKD3D_OUT': str(temporary / 'prepared')}), patch.object(full, 'collect_cursor_witness', collect):
                    if invalid:
                        with self.assertRaises(SystemExit): exec(script, {})
                    else:
                        exec(script, {})
            finally:
                os.chdir(old_cwd)
            logs = temporary / 'vkd3d-probe/logs'
            if invalid:
                failed = logs / ('cursor-native-facts' if target == 0 else 'cursor-production-facts')
                self.assertFalse((failed / 'capture.json').exists())
                if target == 1:
                    pilot_capture = json.loads((logs / 'cursor-native-facts/capture.json').read_text())
                    self.assertEqual(pilot_capture['proof_status'], 'rejected')
                return
            self.assertEqual(len(calls), 2)
            pilot = logs / 'cursor-native-facts/pilot.c'
            flags = ['-DHAVE_CONFIG_H', '-D_WIN32_WINNT=0x0600', '-std=c99']
            flags += ['-I' + str(prepared / part) for part in ('.', 'include', 'include/private', 'libs/vkd3d-shader')]
            flags += ['-I' + str(prepared.parent / part / 'include') for part in ('hdr', 'spv')]
            flags += ['-DLIBVKD3D_SHADER_SOURCE', '-DVKD3D_DEBUG_ENV=VKD3D_SHADER_DEBUG']
            for call, source, cwd, arguments, name in zip(calls, (pilot, production), (pilot.parent, prepared),
                    (['-std=c11'], flags), ('cursor-native-facts', 'cursor-production-facts')):
                tool, entry, output, execute, symbol = call
                self.assertEqual(tool, temporary / 'vkd3d-probe/tool/bin/c2rust-transpile')
                self.assertIs(execute, probe.run)
                self.assertEqual(entry, {'directory': str(cwd), 'file': str(source),
                    'arguments': ['/usr/bin/clang-18', *arguments, '-c', str(source)]})
                self.assertEqual(symbol, {'unit': str(source), 'static': 'vkd3d_spirv_build_op_member_name'})
                self.assertEqual(source, source.resolve())
                self.assertEqual(output, logs / name / 'paired')
                self.assertEqual(json.loads((logs / name / 'capture.json').read_text()),
                    {'status': 'raw_facts_captured', 'authorization': 'witness_only', 'proof_status': 'rejected'})
            self.assertEqual(production.read_text(), 'mock production input, never compiled')
            self.assertEqual(pilot.read_bytes(),
                (repository / 'tools/vkd3d-rust-probe/fixtures/cursor-witness/pilot.c').read_bytes())

    def test_both_captures_use_exact_inputs_and_retain_rejected_status(self):
        self.run_capture()

    def test_both_captures_reject_missing_or_invalid_artifacts(self):
        for target in (0, 1):
            for invalid in ('schema', 'unit', 'inputs', 'missing-witness', 'duplicate-witness',
                            '.cursor.cbor', '.typed-ast.txt', '.variadic.json'):
                with self.subTest(target=target, invalid=invalid): self.run_capture(invalid, target)

    def test_capture_order_and_setup_retention(self):
        _, workflow, _ = self.workflow()
        capture = workflow.index("python3 - <<'PY_CAPTURE'")
        receipt = workflow.index('--tool "$RUNNER_TEMP/vkd3d-probe/tool"')
        self.assertLess(workflow.index('cargo +1.95.0 install'), receipt)
        self.assertLess(receipt, capture)
        self.assertLess(capture, workflow.index('--tests --no-run'))
        self.assertLess(capture, workflow.index('check_closed_variadic_inventory.py'))
        upload = workflow.split('      - name: Preserve setup evidence\n', 1)[1].split('      - name:', 1)[0]
        for required in ('if: always()', 'path: ${{ runner.temp }}/vkd3d-probe/logs/',
                         'retention-days: 7', 'if-no-files-found: error'):
            self.assertIn(required, upload)


if __name__ == '__main__':
    unittest.main()
