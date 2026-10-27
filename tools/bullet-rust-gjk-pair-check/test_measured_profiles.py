"""Measured profile controls reject producer, transport, and semantic drift."""
import copy
import json
import subprocess
import sys
import textwrap
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import check
import measured_profiles
from test_capture import mutations


class MeasuredProfileTests(unittest.TestCase):
    def test_x64_fixture_has_only_measured_nine_words(self):
        fixture = check.ROOT / 'rust/crates/mds-bullet/tests/gjk_pair_data'
        baseline = (fixture / 'native.tsv').read_bytes()
        x64 = (fixture / 'native-x64.tsv').read_bytes()
        expected = [[case, 'query.axis.' + axis, '7fc00000', 'ffc00000']
                    for case in [1252, 1253, 1411] for axis in 'xyz']
        self.assertEqual(check.inventory(baseline, x64, 1800), expected)
        manifest = json.loads(Path(measured_profiles.__file__).with_name('measured-profiles.json').read_text())
        self.assertEqual(set(manifest['profiles']), {'macos-arm64', 'linux-arm64', 'linux-x64', 'windows-x64'})
        for host, profile in manifest['profiles'].items():
            self.assertEqual(profile['exact_frozen_compact_differences'], expected if host.endswith('x64') else [])
            self.assertEqual(len(profile['streams']), 12)
            self.assertEqual(set(profile['commands']), {'native-command.json', 'effective-native-command.json', 'observed-command.json'})

    def test_windows_fixture_and_test_source_keep_binary_checkout_transport(self):
        manifest = json.loads(Path(measured_profiles.__file__).with_name('measured-profiles.json').read_text())
        for name in ['rust/crates/mds-bullet/tests/gjk_pair_data/native-x64.tsv',
                     'rust/crates/mds-bullet/tests/pure_bullet/gjk_pair.rs']:
            self.assertEqual(manifest['verification_sha256']['windows-x64'][name],
                             measured_profiles.sha((check.ROOT / name).read_bytes()))

    def test_unknown_host_and_changed_source_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(check, 'host', return_value='unknown'):
                with self.assertRaisesRegex(ValueError, 'Unknown'):
                    measured_profiles.validate(Path(temp), host=check.host, inventory=check.inventory,
                                               source_hashes=check.source_hashes, stream=check.stream,
                                               transport=check.transport)
            with patch.object(check, 'host', return_value='macos-arm64'), patch.object(check, 'source_hashes', return_value={}):
                with self.assertRaisesRegex(ValueError, 'source closure'):
                    measured_profiles.validate(Path(temp), host=check.host, inventory=check.inventory,
                                               source_hashes=check.source_hashes, stream=check.stream,
                                               transport=check.transport)

    def test_cli_main_with_support_first_reaches_real_validator(self):
        script = textwrap.dedent("""
            import ast
            import importlib.util
            from pathlib import Path
            import sys
            outer = Path(sys.argv[1]).resolve()
            output = Path(sys.argv[2])
            sys.path.insert(0, str(outer.parent))
            spec = importlib.util.spec_from_file_location('__main__', outer)
            module = importlib.util.module_from_spec(spec)
            sys.modules['__main__'] = module
            sys.argv = [str(outer), '--help']
            try:
                spec.loader.exec_module(module)
            except SystemExit as error:
                if error.code != 0:
                    raise RuntimeError('help failed')
            if Path(sys.path[0]).name != 'bullet-rust-support-check':
                raise RuntimeError('support path missing')
            import check
            if Path(check.__file__).parent.name != 'bullet-rust-support-check':
                raise RuntimeError('support module missing')
            from measured_profiles import validate
            capture = next(node for node in ast.parse(outer.read_text()).body
                           if isinstance(node, ast.FunctionDef) and node.name == 'capture')
            call, = [node for node in ast.walk(capture) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name) and node.func.id == 'validate']
            # Evaluate the production call with its real __main__ globals and validator.
            expression = compile(ast.Expression(call), str(outer), 'eval')
            scope = dict(vars(module), validate=validate, output=output)
            try:
                eval(expression, scope)
            except ValueError as error:
                if str(error) != 'Outer GJK compiler or toolchain differs from measured profile':
                    raise RuntimeError(str(error))
                print('real validator rejected compiler drift')
            else:
                raise AssertionError('Compiler drift was accepted')
        """)
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'provenance.txt').write_text('deliberately unreviewed compiler')
            result = subprocess.run([sys.executable, '-c', script, check.__file__, temp],
                                    capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('real validator rejected compiler drift', result.stdout)

    def test_command_root_relocation_keeps_every_flag(self):
        command = ['cl', '/O2', '/fp:precise', '/IC:\\repo\\shim', '/Fe:C:\\out\\native.exe']
        expected = ['cl', '/O2', '/fp:precise', '/I$ROOT/shim', '/Fe:$CAPTURE/native.exe']
        self.assertEqual(measured_profiles.canonical_command(command, 'C:/repo', 'C:/out'), expected)
        command[2] = '/fp:fast'
        self.assertNotEqual(measured_profiles.canonical_command(command, 'C:/repo', 'C:/out'), expected)

    def test_baseline_requires_intended_test_and_no_filtered_or_ignored_tests(self):
        good = f'test {mutations.TEST} ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;'
        self.assertEqual(mutations.classify(SimpleNamespace(returncode=0, stdout=good, stderr=''))['status'], 'passed')
        for broken in [good.replace('0 filtered', '3 filtered'), good.replace('0 ignored', '1 ignored'), good.replace(mutations.TEST, 'other')]:
            self.assertEqual(mutations.classify(SimpleNamespace(returncode=0, stdout=broken, stderr=''))['status'], 'validation-gap')


class FiniteMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.manifest = measured_profiles.load_manifest(measured_profiles.HERE / 'measured-profiles.json')

    def load_changed(self, change):
        value = copy.deepcopy(self.manifest)
        change(value)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_text(json.dumps(value))
            return measured_profiles.load_manifest(path)

    def test_five_actual_measurements_select_exact_history_in_any_order(self):
        for host, profile in self.manifest['profiles'].items():
            self.assertEqual(len(profile['measurements']), 2 if host == 'linux-x64' else 1)
            for measurement in profile['measurements']:
                provenance = measurement['compiler_provenance'].replace('\r\n', '\n')
                self.assertEqual(measured_profiles.select_measurement(profile, provenance), measurement)
                reversed_profile = dict(profile, measurements=list(reversed(profile['measurements'])))
                self.assertEqual(measured_profiles.select_measurement(reversed_profile, provenance), measurement)
                for broken in [provenance.replace(provenance.splitlines()[0], 'third kernel'),
                               provenance.replace('rustc', 'unmeasured-rustc'), provenance + 'extra\n',
                               provenance.replace('clang', 'unmeasured-clang'), provenance.replace('\n', '\r', 1),
                               provenance.replace('\n', '\r\n', 1)]:
                    if broken != provenance:
                        with self.assertRaisesRegex(ValueError, 'compiler or toolchain'):
                            measured_profiles.select_measurement(profile, broken)
        linux = self.manifest['profiles']['linux-x64']['measurements']
        self.assertEqual({m['artifact_id'] for m in linux}, {12739416224, 12735984749})
        self.assertEqual({m['zip_sha256'] for m in linux}, {
            '9bd0fcf71c58360f380ce319cdb31aaed26eacde1ffb5d4bb2ed945e831516b4',
            'df658e5f0d8caf792b1e7a975fe179b629da45e0d6a5f73e5caeed3aa37f76ac'})

    def test_schema_rejects_malformed_and_unselected_records(self):
        def profile(value):
            return value['profiles']['linux-x64']
        changes = [
            lambda v: v.update(schema_version=True), lambda v: v.update(schema_version=1),
            lambda v: v.update(evidence_head='0' * 40),
            lambda v: profile(v).update(measurements=[]),
            lambda v: profile(v).update(measurements={}),
            lambda v: profile(v).pop('measurements'),
            lambda v: profile(v)['measurements'].append(copy.deepcopy(profile(v)['measurements'][0])),
            lambda v: profile(v)['measurements'][1].update(artifact_id=profile(v)['measurements'][0]['artifact_id']),
            lambda v: profile(v)['measurements'][1].update(job_id=profile(v)['measurements'][0]['job_id']),
            lambda v: profile(v)['measurements'][1].update(compiler_provenance=profile(v)['measurements'][0]['compiler_provenance'].replace('\n', '\r\n')),
            lambda v: profile(v)['measurements'][1].update(capture_source_map_sha256='0' * 64),
            lambda v: profile(v)['measured_verification_sha256'].update({'extra': '0' * 64}),
            lambda v: v['verification_sha256']['linux-x64'].update({'extra': '0' * 64}),
            lambda v: profile(v)['protected_source_sha256'].pop(next(iter(profile(v)['protected_source_sha256']))),
            lambda v: profile(v).update(exact_frozen_compact_differences=[]),
            lambda v: profile(v)['commands'].pop('native-command.json'),
            lambda v: profile(v)['streams']['capture/native.tsv'].update(rows=True),
            lambda v: profile(v)['streams']['capture/native.tsv'].update(raw_sha256='invalid'),
            lambda v: profile(v)['protected_source_sha256'].update({next(iter(profile(v)['protected_source_sha256'])): True}),
            lambda v: profile(v)['measurements'][1].update(compiler_provenance=None),
        ]
        for field in measured_profiles.MEASUREMENT_FIELDS:
            changes.append(lambda v, field=field: profile(v)['measurements'][1].pop(field))
        for field in ['run_id', 'job_id', 'artifact_id']:
            for bad in [True, False, 0, -1, 1.5, '1', None]:
                changes.append(lambda v, field=field, bad=bad: profile(v)['measurements'][1].update({field: bad}))
        for field in ['evidence_head', 'zip_sha256', 'capture_source_map_sha256', 'source_before_sha256',
                      'source_after_sha256', 'provenance_sha256']:
            changes.append(lambda v, field=field: profile(v)['measurements'][1].update({field: 'invalid'}))
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'schema'):
                self.load_changed(change)

    def test_partition_overlap_and_duplicate_json_keys(self):
        def overlap(value):
            current = value['verification_sha256']['linux-x64']
            current.pop(next(iter(current)))
            path, identity = next(iter(value['profiles']['linux-x64']['protected_source_sha256'].items()))
            current[path] = identity
        with self.assertRaisesRegex(ValueError, 'partition overlap'):
            self.load_changed(overlap)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_text('{"schema_version": 2, "schema_version": 2}')
            with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                measured_profiles.load_manifest(path)

    def test_current_expectation_is_separate_from_historical_capture(self):
        for host, profile in self.manifest['profiles'].items():
            historical = {**profile['protected_source_sha256'], **profile['measured_verification_sha256']}
            self.assertEqual(len(historical), 467)
            for measurement in profile['measurements']:
                self.assertEqual(measurement['capture_source_map_sha256'], measured_profiles.source_map_digest(historical))
            self.assertEqual(set(profile['measured_verification_sha256']), set(self.manifest['verification_sha256'][host]))

    def test_receipts_and_all_contract_guards_with_current_expectation_bridge(self):
        # Pure bridge controls replay contracts; they do not claim native execution of current code.
        fixture = check.ROOT / 'rust/crates/mds-bullet/tests/gjk_pair_data'
        for host_name, profile in self.manifest['profiles'].items():
            source = {**profile['protected_source_sha256'], **self.manifest['verification_sha256'][host_name]}
            compact = (fixture / ('native-x64.tsv' if host_name.endswith('x64') else 'native.tsv')).read_bytes().replace(b'\r\n', b'\n')
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                for name, command in profile['commands'].items():
                    (output / name).write_text(json.dumps(command))
                (output / 'full-rust-result.json').write_text(json.dumps({'status': 'passed', 'returncode': 0}))
                identities = {}
                for path, identity in profile['streams'].items():
                    name = Path(path).name
                    token = name.encode()
                    (output / name).write_bytes(token)
                    normalized = compact if name.startswith('compact-') and 'inputs' not in name else b'same-host-words'
                    identities[token] = (normalized, identity)
                def replay(data, count, start=0):
                    return identities.get(data, (b'corrupt', {}))
                def validate():
                    return measured_profiles.validate(output, host=lambda: host_name, inventory=lambda *args: profile['exact_frozen_compact_differences'],
                        source_hashes=lambda: source, stream=replay, transport=replay)
                for measurement in profile['measurements']:
                    (output / 'provenance.txt').write_bytes(measurement['compiler_provenance'].encode())
                    receipt = validate()
                    for field in measured_profiles.MEASUREMENT_FIELDS - {'compiler_provenance'}:
                        self.assertEqual(receipt[field], measurement[field])
                    self.assertEqual(receipt['source_sha256'], source)
                    self.assertEqual(receipt['current_source_map_sha256'], measured_profiles.source_map_digest(source))
                for name in profile['commands']:
                    original = (output / name).read_bytes()
                    (output / name).write_text('["drift"]')
                    with self.assertRaisesRegex(ValueError, 'effective command drift'):
                        validate()
                    (output / name).write_bytes(original)
                for path in profile['streams']:
                    name = Path(path).name
                    original = (output / name).read_bytes()
                    (output / name).write_bytes(b'corrupt')
                    with self.assertRaisesRegex(ValueError, 'capture drift'):
                        validate()
                    (output / name).write_bytes(original)
                for change in ['missing', 'extra', 'changed']:
                    original = source.copy()
                    if change == 'missing': source.pop(next(iter(source)))
                    if change == 'extra': source['extra'] = '0' * 64
                    if change == 'changed': source[next(iter(source))] = '0' * 64
                    with self.assertRaisesRegex(ValueError, 'source closure'):
                        validate()
                    source.clear()
                    source.update(original)
                for result in [101, False, '0']:
                    (output / 'full-rust-result.json').write_text(json.dumps({'status': 'passed', 'returncode': result}))
                    with self.assertRaisesRegex(ValueError, 'baseline did not pass'):
                        validate()


if __name__ == '__main__':
    unittest.main()
