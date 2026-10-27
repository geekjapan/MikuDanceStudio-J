"""Compiler-free boundary checks for the finite CMP experiment."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import check_cmp_sequencing as cmp


def inventory():
    data = {'schema': 2, 'authorization': 'inventory_only', 'unit': cmp.UNIT,
            'declarations': [{'id': 104190, 'definition': True, 'symbol': {
                'static': 'spirv_compiler_emit_movc', 'unit': cmp.UNIT}, 'location': 'x:7614:1'}], 'calls': []}
    data['calls'].append({'id': 104281, 'owner': 104190,
        'callee': {'static': 'vkd3d_spirv_build_op_tr2', 'unit': cmp.UNIT}, 'location': 'x:7633:28',
        'arguments': [{'id': 0} for _ in range(6)]})
    for slot, node, helper, line in ((3, 104287, 'spirv_get_type_id', 7634),
                                   (5, 104289, 'spirv_compiler_get_constant_float_vector', 7635)):
        data['calls'][0]['arguments'][slot] = {'id': node, 'type': {'canonical': {'kind': 'UInt'},
            'const': False, 'restrict': False, 'volatile': False}}
        data['calls'].append({'id': node, 'owner': 104190, 'callee': {'static': helper, 'unit': cmp.UNIT},
                              'location': 'x:' + str(line) + ':21'})
    return data


class SequencingTests(unittest.TestCase):
    def test_typed_boundary_rejects_missing_duplicate_wrong_owner_type_slot_callee(self):
        valid = inventory()
        cmp.validate_inventory(valid)
        mutations = []
        d = copy.deepcopy(valid); d['calls'].pop(); mutations.append(d)
        d = copy.deepcopy(valid); d['calls'].append(d['calls'][0]); mutations.append(d)
        d = copy.deepcopy(valid); d['calls'][1]['owner'] = 7; mutations.append(d)
        d = copy.deepcopy(valid); d['calls'][0]['arguments'][3]['type']['canonical']['kind'] = 'Int'; mutations.append(d)
        d = copy.deepcopy(valid); d['calls'][0]['arguments'][3]['id'] = 104289; mutations.append(d)
        d = copy.deepcopy(valid); d['calls'][1]['callee']['static'] = 'other'; mutations.append(d)
        d = copy.deepcopy(valid); d['unit'] = 'other.c'; mutations.append(d)
        d = copy.deepcopy(valid); d['declarations'][0]['definition'] = False; mutations.append(d)
        for data in mutations:
            with self.subTest(data=data), self.assertRaises(ValueError):
                cmp.validate_inventory(data)

    def test_real_writer_isolates_three_variants(self):
        source = ('prefix\nunsafe extern "C" fn spirv_compiler_emit_movc(\n) {\nif VSIR_OP_CMP.0 {\n' + cmp.CALL
                  + '\n}\nunsafe extern "C" fn untouched() {}\n').encode()
        body = source.decode()[source.decode().index('unsafe extern "C" fn spirv_compiler_emit_movc('):source.decode().index('\nunsafe extern', 40)]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / 'original'
            (original / cmp.RUST_PATH).parent.mkdir(parents=True)
            (original / cmp.RUST_PATH).write_bytes(source)
            raw = json.dumps(inventory()).encode()
            (original / 'src/vkd3d_shader/spirv.variadic.json').write_bytes(raw)
            (original / 'Cargo.lock').write_bytes(b'lock')
            (original / 'Cargo.toml').write_text('manifest')
            c_source = root / 'spirv.c'; c_source.write_bytes(b'C source')
            hashes = {'RUST_SHA': cmp.sha(source), 'BODY_SHA': cmp.sha((body.rstrip() + '\n').encode()),
                      'INVENTORY_SHA': cmp.sha(raw), 'LOCK_SHA': cmp.sha(b'lock'), 'C_SHA': cmp.sha(b'C source')}
            before = cmp.manifest(original)
            with patch.multiple(cmp, **hashes), patch.object(cmp.subprocess, 'run', side_effect=AssertionError('no process')):
                records = cmp.write_variants(original, root / 'variants', c_source)
                self.assertEqual(cmp.manifest(original), before)
                self.assertEqual(records['R0']['changed_paths'], [])
                r0 = (root / 'variants/R0/rust' / cmp.RUST_PATH).read_bytes()
                self.assertEqual(r0, source)
                for mode, first, second in [('Rzero', 'cmp_zero_id', 'cmp_type_id'), ('Rtype', 'cmp_type_id', 'cmp_zero_id')]:
                    result = (root / 'variants' / mode / 'rust' / cmp.RUST_PATH).read_text()
                    self.assertLess(result.index('let ' + first), result.index('let ' + second))
                    self.assertEqual(result.count(cmp.TYPE), 1)
                    self.assertEqual(result.count(cmp.ZERO), 1)
                    self.assertTrue(result.endswith('unsafe extern "C" fn untouched() {}\n'))
                with self.assertRaises(ValueError):
                    cmp.transform(source + b' ', inventory(), 'Rzero')
                with self.assertRaises(ValueError):
                    cmp.transform(source, inventory(), 'other')

    def test_duplicate_call_fails_even_with_matching_whole_file_hash(self):
        source = ('unsafe extern "C" fn spirv_compiler_emit_movc() {\n' + cmp.CALL + '\n' + cmp.CALL
                  + '\n}\nunsafe extern "C" fn other() {}').encode()
        with patch.object(cmp, 'RUST_SHA', cmp.sha(source)), self.assertRaises(ValueError):
            cmp.transform(source, inventory(), 'Rzero')

    def test_observer_preserves_sibling_call_shape_and_global_helpers(self):
        source = ('helper declarations\nstatic void spirv_compiler_emit_movc() {\n' + cmp.C_CALL + '\n}').encode()
        with patch.object(cmp, 'C_SHA', cmp.sha(source)):
            output = cmp.instrument(source).decode()
        expected = cmp.C_CALL.replace('spirv_get_type_id(', 'cmp_type(').replace('spirv_compiler_get_constant_float_vector(', 'cmp_zero(')
        self.assertIn(expected, output)
        self.assertIn('result = spirv_get_type_id(compiler, type, n);', output)
        self.assertIn('result = spirv_compiler_get_constant_float_vector(compiler, value, n);', output)
        with self.assertRaises(ValueError):
            cmp.instrument(source + b' ')

    def test_trace_requires_actual_order_and_both_directed_cases(self):
        valid = 'zero entry 4 27 0 0 26 5 70 0\nzero return 4 28 27 0 26 5 77 27\ntype entry 4 28 0 0 26 5 77 27\ntype return 4 29 28 28 26 5 81 27\n'
        with tempfile.TemporaryDirectory() as temp:
            paths = []
            for name in sorted(cmp.DIRECTED):
                path = Path(temp) / (name + '.native.trace'); path.write_text(valid); paths.append(path)
            cmp.verify_trace(paths)
            paths[0].write_text(valid.replace('zero entry', 'type entry', 1))
            with self.assertRaises(ValueError): cmp.verify_trace(paths)
            with self.assertRaises(ValueError): cmp.verify_trace([])

    def test_archive_traversal_duplicates_and_symlinks_reject(self):
        for names in (['../escape'], ['/escape'], ['a', 'a']):
            data = io.BytesIO()
            with zipfile.ZipFile(data, 'w') as z:
                for name in names: z.writestr(name, b'x')
            with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
                cmp.unzip(data.getvalue(), Path(temp))
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            member = zipfile.ZipInfo('link'); member.external_attr = 0o120777 << 16; z.writestr(member, 'target')
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            cmp.unzip(data.getvalue(), Path(temp))

    def test_native_baseline_requires_all_150_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); a = root / 'a'; b = root / 'b'; a.mkdir(); b.mkdir()
            for i in range(50):
                for suffix in ('.native', '.native.status', '.native.diagnostics'):
                    for target in (a, b): (target / (str(i) + suffix)).write_bytes(b'exact')
            cmp.require_baseline(a, b)
            (a / '0.native').write_bytes(b'different')
            with self.assertRaises(ValueError): cmp.require_baseline(a, b)

    def test_finite_outcomes_do_not_accept_wrong_order_or_failed_negative(self):
        with tempfile.TemporaryDirectory() as temp:
            matrix = Path(temp)
            cases = []
            for name in sorted(cmp.DIRECTED) + [str(i) for i in range(46)]:
                cases.append({'name': name, 'status': 'mismatch' if name in cmp.DIRECTED else 'success',
                    'return_codes': ['0', '0'], 'diagnostics_equal': True, 'output_sha256': ['a', 'b'],
                    'native': {'exit_code': 0}, 'rust': {'exit_code': 0}})
            negatives = []
            for name, diagnostic in [('missing_float_controls', b'E2004'), ('invalid_pixel_semantic', b'E5013')]:
                negatives.append({'name': name, 'status': 'expected_rejection', 'return_codes': ['-4', '-4'],
                    'diagnostics_equal': True, 'native': {'exit_code': 0}, 'rust': {'exit_code': 0}})
                for side in ('native', 'rust'):
                    (matrix / (name + '.' + side)).write_bytes(b'')
                    (matrix / (name + '.' + side + '.diagnostics')).write_bytes(diagnostic)
            for case in cases:
                for suffix in ('.rust', '.rust.status', '.rust.diagnostics'):
                    (matrix / (case['name'] + suffix)).write_bytes(b'exact')
            result = {'cases': cases, 'negative_controls': negatives}
            self.assertFalse(cmp.check_outcome(result, matrix, 'R0', matrix)['production_acceptance'])
            with self.assertRaises(ValueError): cmp.check_outcome(result, matrix, 'Rzero', matrix)
            for case in cases: case['status'] = 'success'
            cmp.check_outcome(result, matrix, 'Rzero', matrix)
            negatives[0]['return_codes'] = ['0', '0']
            with self.assertRaises(ValueError): cmp.check_outcome(result, matrix, 'Rzero', matrix)

    def test_dependency_bytes_are_retained_and_missing_inputs_reject(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / 'source'; source.mkdir()
            header = source / 'header.h'; header.write_bytes(b'header bytes')
            dep = source / 'unit.Plo'; dep.write_text('unit.lo: header.h\nheader.h:\n')
            records = cmp.retain_dependencies(source, root / 'bytes')
            digest = cmp.sha(b'header bytes')
            self.assertEqual(records[str(header.resolve())]['sha256'], digest)
            self.assertEqual((root / 'bytes' / digest).read_bytes(), b'header bytes')
            header.unlink()
            with self.assertRaises(ValueError): cmp.retain_dependencies(source, root / 'missing')

    def test_artifact_api_rejects_wrong_head_run_digest_and_expiry(self):
        run = {'head_sha': cmp.HEAD, 'id': cmp.RUN, 'run_attempt': 1,
               'repository': {'full_name': cmp.REPO}, 'path': '.github/workflows/vkd3d-rust-probe.yml'}
        artifact_id, digest = cmp.ARTIFACTS['all-units']
        metadata = {'id': artifact_id, 'name': 'vkd3d-probe-all-units', 'expired': False,
                    'workflow_run': {'id': cmp.RUN, 'head_sha': cmp.HEAD}, 'digest': 'sha256:' + digest}
        for key, value in [('id', 0), ('expired', True), ('digest', 'sha256:wrong')]:
            changed = copy.deepcopy(metadata); changed[key] = value
            with tempfile.TemporaryDirectory() as temp, patch.object(cmp.subprocess, 'run', side_effect=[
                    type('Response', (), {'stdout': json.dumps(run).encode()})(),
                    type('Response', (), {'stdout': json.dumps(changed).encode()})()]), self.assertRaises(ValueError):
                cmp.fetch_inputs(Path(temp))
        for key, value in [('head_sha', 'other'), ('id', 0), ('run_attempt', 2)]:
            changed = copy.deepcopy(run); changed[key] = value
            with tempfile.TemporaryDirectory() as temp, patch.object(cmp.subprocess, 'run', return_value=
                    type('Response', (), {'stdout': json.dumps(changed).encode()})()), self.assertRaises(ValueError):
                cmp.fetch_inputs(Path(temp))

    def test_full_experiment_with_only_processes_and_download_mocked(self):
        from contextlib import ExitStack
        import probe
        historical = Path(__file__).resolve().parents[2]
        source = ('prefix\nunsafe extern "C" fn spirv_compiler_emit_movc(\n) {\nif VSIR_OP_CMP.0 {\n'
                  + cmp.CALL + '\n}\n}\nunsafe extern "C" fn untouched() {}\n').encode()
        text = source.decode(); start = text.index('unsafe extern "C" fn spirv_compiler_emit_movc(')
        body = text[start:text.index('\nunsafe extern', start + 1)]
        c_source = ('static void spirv_compiler_emit_movc() {\n' + cmp.C_CALL + '\n}').encode()
        raw = json.dumps(inventory()).encode()
        hashes = {'RUST_SHA': cmp.sha(source), 'BODY_SHA': cmp.sha((body.rstrip() + '\n').encode()),
                  'INVENTORY_SHA': cmp.sha(raw), 'LOCK_SHA': cmp.sha(b'lock'), 'C_SHA': cmp.sha(c_source),
                  'LICENSE_SHA': cmp.sha(b'license')}
        trace = ('zero entry 4 27 0 0 26 5 70 0\nzero return 4 28 27 0 26 5 77 27\n'
                 'type entry 4 28 0 0 26 5 77 27\ntype return 4 29 28 28 26 5 81 27\n')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def downloads(destination, run):
                actual = destination / 'all-units/result'
                project = actual / 'rust-working'
                (project / cmp.RUST_PATH).parent.mkdir(parents=True)
                (project / cmp.RUST_PATH).write_bytes(source)
                (project / 'src/vkd3d_shader/spirv.variadic.json').write_bytes(raw)
                (project / 'Cargo.lock').write_bytes(b'lock')
                (project / 'Cargo.toml').write_text('manifest')
                (actual / 'VKD3D-LICENSE').write_bytes(b'license')
                for target in (actual / 'source', destination / 'prepared-input/prepared/work-linux-native/vkd3d-2.1'):
                    target = target / 'libs/vkd3d-shader/spirv.c'
                    target.parent.mkdir(parents=True); target.write_bytes(c_source)
                matrix = actual / 'matrix'; matrix.mkdir()
                from shader_matrix import CASES
                names = [f'{name}-{stage}-{model}-{target}' for name in CASES for stage in ('vs', 'ps')
                         for model in ('2_0', '3_0') for target in (1, 3, 4)]
                for name in names + ['missing_float_controls', 'invalid_pixel_semantic']:
                    negative = name not in names
                    diagnostic = b'E2004' if name == 'missing_float_controls' else b'E5013' if negative else b''
                    for side in ('native', 'rust'):
                        output = b'' if negative else b'wrong' if side == 'rust' and name in cmp.DIRECTED else b'exact'
                        (matrix / (name + '.' + side)).write_bytes(output)
                        (matrix / (name + '.' + side + '.status')).write_text('-4' if negative else '0')
                        (matrix / (name + '.' + side + '.diagnostics')).write_bytes(diagnostic)
            def process(command, log, **kwargs):
                log.parent.mkdir(parents=True, exist_ok=True); log.write_text('')
                exit_code = 0
                if command[0] == 'bash':
                    out = Path(kwargs['env']['MDS_VKD3D_OUT'])
                    src = out / 'work-linux-native/vkd3d-2.1/libs/vkd3d-shader/spirv.c'
                    src.parent.mkdir(parents=True); src.write_bytes(c_source)
                    deps = src.parent / '.deps/spirv.Plo'; deps.parent.mkdir()
                    deps.write_text('spirv.lo: libs/vkd3d-shader/spirv.c\n')
                    library = out / 'linux-native/lib/libvkd3d-shader.so.1'
                    library.parent.mkdir(parents=True); library.write_bytes(b'native library')
                elif command[0] == 'cargo':
                    if kwargs['env'].get('RUSTC_BOOTSTRAP') == '1':
                        archive = Path(kwargs['env']['CARGO_TARGET_DIR']) / 'debug/librust.a'
                        archive.parent.mkdir(parents=True); archive.write_bytes(b'archive')
                    else:
                        exit_code = 101; log.write_text('error[E0554]')
                elif command[0] == 'rustc' and '-o' in command:
                    Path(command[command.index('-o') + 1]).write_bytes(b'driver')
                elif Path(command[0]).name == 'shader-driver':
                    output = Path(command[4]); name = output.name.rsplit('.', 1)[0]
                    negative = name in ('missing_float_controls', 'invalid_pixel_semantic')
                    wrong = (command[5] == '-' and name in cmp.DIRECTED and 'Rzero' not in command[0])
                    output.write_bytes(b'' if negative else b'wrong' if wrong else b'exact')
                    output.with_suffix(output.suffix + '.status').write_text('-4' if negative else '0')
                    output.with_suffix(output.suffix + '.diagnostics').write_bytes(
                        b'E2004' if name == 'missing_float_controls' else b'E5013' if negative else b'')
                    if name in cmp.DIRECTED and 'MDS_CMP_TRACE' in kwargs.get('env', {}):
                        Path(kwargs['env']['MDS_CMP_TRACE']).write_text(trace)
                return {'command': command, 'exit_code': exit_code, 'timed_out': False, 'log': str(log)}
            with ExitStack() as stack:
                stack.enter_context(patch.multiple(cmp, **hashes))
                stack.enter_context(patch.object(cmp, 'fetch_inputs', downloads))
                stack.enter_context(patch.object(cmp.subprocess, 'check_output', return_value=cmp.HEAD + '\n'))
                stack.enter_context(patch.object(cmp.subprocess, 'run', side_effect=AssertionError('unmocked process')))
                stack.enter_context(patch.object(probe, 'run', process))
                cmp.execute(root, historical)
            result = json.loads((root / 'result.json').read_text())
            self.assertEqual(result['stable_gate'], 'FAIL_E0554')
            self.assertEqual(result['variants']['Rzero']['experimental_outcome'], 'exact_positive_match')
            self.assertFalse(result['production_acceptance'])
            self.assertEqual(len(json.loads((root / 'native-baselines.json').read_text())['fresh']), 150)
            commands = json.loads((root / 'commands.json').read_text())
            self.assertEqual(len([c for c in commands if c['command'][0] == 'cargo']), 6)
            self.assertTrue(all('timeout_seconds' in c and 'cwd' in c for c in commands))


if __name__ == '__main__':
    unittest.main()
