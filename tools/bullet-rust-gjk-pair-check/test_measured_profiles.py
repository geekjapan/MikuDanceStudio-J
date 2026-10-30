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


class MmdCollisionAdmissionTests(unittest.TestCase):
    def test_verification_git_layer_requires_exact_paths_modes_and_scope(self):
        blobs = measured_profiles.VERIFICATION_BASE_BLOBS
        head = '2' * 40
        changed = dict(blobs)
        path = 'tools/bullet-rust-gjk-pair-check/measured_profiles.py'
        changed[path] = '3' * 40
        def records(mapping, mode='100644'):
            return b''.join(f'{mode} blob {blob}\t{name}\0'.encode() for name, blob in mapping.items())
        def run(mapping, mode='100644'):
            measured_profiles.git_verification_maps.cache_clear()
            def git(argv):
                if 'ls-tree' in argv:
                    return records(blobs) if measured_profiles.VERIFICATION_BASE in argv else records(mapping, mode)
                return argv[-1].encode() + b'\n'
            with patch.object(measured_profiles.subprocess, 'check_output', side_effect=git):
                return measured_profiles.git_verification_maps(head, 'linux-x64')
        baseline, current = run(changed)
        self.assertEqual(set(current), set(blobs))
        self.assertNotEqual(baseline[path], current[path])
        invalid = [({p: b for p, b in changed.items() if p != path}, '100644'),
                   (dict(changed, **{'unexpected.py': '4' * 40}), '100644'),
                   (changed, '100755'), (changed, '120000')]
        foreign = next(p for p in blobs if p not in measured_profiles.VERIFICATION_LAYER_PATHS)
        invalid.append((dict(changed, **{foreign: '4' * 40}), '100644'))
        try:
            for mapping, mode in invalid:
                with self.subTest(mode=mode, paths=set(mapping)), self.assertRaisesRegex(ValueError, 'schema'):
                    run(mapping, mode)
        finally:
            measured_profiles.git_verification_maps.cache_clear()

    def test_fixed_unrun_source_layer_and_physical_transport(self):
        manifest = measured_profiles.load_manifest(measured_profiles.HERE / 'measured-profiles.json')
        layer = manifest['mmd_collision_world_source_admission']
        self.assertEqual(layer['execution'], 'UNRUN')
        self.assertEqual(measured_profiles.source_map_digest(layer), measured_profiles.MMD_COLLISION_WORLD_SHA256)
        for host in measured_profiles.HOSTS:
            current = measured_profiles.approved_source_map(manifest, host)
            delta = layer['hosts'][host]
            for path in measured_profiles.MMD_COLLISION_WORLD_ADDITIONS | measured_profiles.MMD_COLLISION_WORLD_REPLACEMENTS:
                raw = (check.ROOT / path).read_bytes().replace(b'\r\n', b'\n')
                physical = raw.replace(b'\n', b'\r\n') if host == 'windows-x64' and '/tests/' not in path else raw
                self.assertEqual(current[path], measured_profiles.sha(physical))
            previous = manifest['dynamics_world_source_admission']['hosts'][host]['replacements']
            for path, identity in delta['replacements'].items():
                self.assertEqual(identity['old_sha256'], previous[path]['new_sha256'])

    def test_no_execution_claim_scope_drift_or_coordinated_hash_edit(self):
        manifest = measured_profiles.load_manifest(measured_profiles.HERE / 'measured-profiles.json')
        key = 'mmd_collision_world_source_admission'
        changes = [lambda v: v.pop(key), lambda v: v[key].update(execution='PASS'),
                   lambda v: v[key].update(base_head='0' * 40),
                   lambda v: v[key]['hosts'].pop('windows-x64'),
                   lambda v: v[key]['hosts']['linux-x64']['additions'].update({'foreign.rs': '0' * 64}),
                   lambda v: v[key]['hosts']['linux-x64']['additions'].update(
                       {next(iter(measured_profiles.MMD_COLLISION_WORLD_ADDITIONS)): '0' * 64})]
        for change in changes:
            value = copy.deepcopy(manifest)
            change(value)
            with self.assertRaises((ValueError, KeyError)):
                measured_profiles.load_manifest(SimpleNamespace(read_text=lambda: json.dumps(value)))


class DynamicsFormatAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.manifest = measured_profiles.load_manifest(measured_profiles.HERE / 'measured-profiles.json')

    def test_source_derived_legal_maps_and_separate_receipt(self):
        class Capture:
            def __init__(self, data, name=''):
                self.data, self.name = data, name
            def __truediv__(self, name):
                return Capture(self.data, name)
            def read_bytes(self):
                return self.data[self.name]
            def read_text(self):
                return self.read_bytes().decode()
            def __str__(self):
                return '/inert-capture'
        fixture = check.ROOT / 'rust/crates/mds-bullet/tests/gjk_pair_data'
        layer = self.manifest['dynamics_world_format_admission']
        self.assertEqual(layer['execution'], 'UNRUN')
        self.assertEqual(measured_profiles.source_map_digest(layer), measured_profiles.DYNAMICS_WORLD_FORMAT_SHA256)
        for host, profile in self.manifest['profiles'].items():
            source = measured_profiles.approved_source_map(self.manifest, host)
            self.assertEqual(len(source), 482)
            for path, identity in layer['hosts'][host]['replacements'].items():
                self.assertEqual(identity['old_sha256'], self.manifest['dynamics_world_source_admission']['hosts'][host]['additions'][path])
                raw = (check.ROOT / path).read_bytes()
                self.assertNotIn(b'\r', raw)
                physical = raw.replace(b'\n', b'\r\n') if host == 'windows-x64' and '/tests/' not in path else raw
                self.assertEqual(source[path], measured_profiles.sha(physical))
                if path in measured_profiles.DYNAMICS_WORLD_C23_REPAIR_REPLACEMENTS:
                    self.assertEqual(identity['new_sha256'], self.manifest['dynamics_world_c23_repair_admission']['hosts'][host]['replacements'][path]['old_sha256'])
                else:
                    self.assertEqual(identity['new_sha256'], source[path])
            data = {'source-head.txt': b'1' * 40 + b'\n',
                    'full-rust-result.json': b'{"status":"passed","returncode":0}'}
            data.update({name: json.dumps(command).encode() for name, command in profile['commands'].items()})
            identities = {}
            compact = (fixture / ('native-x64.tsv' if host.endswith('x64') else 'native.tsv')).read_bytes().replace(b'\r\n', b'\n')
            for path, identity in profile['streams'].items():
                name = Path(path).name
                data[name] = name.encode()
                identities[data[name]] = (compact if name.startswith('compact-') and 'inputs' not in name else b'same-host-words', identity)
            def replay(data, count, start=0):
                return identities[data]
            for measurement in profile['measurements'] + [m for m in self.manifest['supplemental_measurements'] if m['host'] == host]:
                data['provenance.txt'] = measurement['compiler_provenance'].encode()
                receipt = measured_profiles.validate(Capture(data), host=lambda: host,
                    inventory=lambda *args: profile['exact_frozen_compact_differences'],
                    source_hashes=lambda: source, stream=replay, transport=replay)
                expected = {name: value for name, value in measurement.items() if name != 'compiler_provenance'}
                expected['role'] = 'supplemental-reference' if 'host' in measurement else 'historical-reference'
                self.assertEqual(receipt['measurement_reference'], expected)
                self.assertEqual(receipt['current_source']['dynamics_world_format_admission'],
                                 {name: value for name, value in layer.items() if name != 'hosts'})
                self.assertNotIn('dynamics_world_format_admission', receipt['measurement_reference'])
                repair = self.manifest['dynamics_world_c23_repair_admission']
                self.assertEqual(receipt['current_source']['dynamics_world_c23_repair_admission'],
                                 {name: value for name, value in repair.items() if name != 'hosts'})
                self.assertNotIn('dynamics_world_c23_repair_admission', receipt['measurement_reference'])
                formatting = self.manifest['dynamics_world_c23_test_format_admission']
                self.assertEqual(receipt['current_source']['dynamics_world_c23_test_format_admission'],
                                 {name: value for name, value in formatting.items() if name != 'hosts'})
                self.assertNotIn('dynamics_world_c23_test_format_admission', receipt['measurement_reference'])

    def test_exact_scope_metadata_and_composed_old_identity_refusals(self):
        key = 'dynamics_world_format_admission'
        for host in measured_profiles.HOSTS:
            path = sorted(measured_profiles.DYNAMICS_WORLD_ADDITIONS)[0]
            def layer(value): return value[key]
            def delta(value): return layer(value)['hosts'][host]
            def identity(value): return delta(value)['replacements'][path]
            changes = [lambda v: layer(v).update(kind='another-format'),
                       lambda v: layer(v).update(base_head='0' * 40),
                       lambda v: layer(v).update(base_tree='0' * 40),
                       lambda v: layer(v).update(execution='PASS'),
                       lambda v: layer(v).update(extra={}),
                       lambda v: layer(v)['hosts'].pop(host),
                       lambda v: layer(v)['hosts'].update(extra={}),
                       lambda v: delta(v).update(additions={}),
                       lambda v: delta(v)['replacements'].pop(path),
                       lambda v: delta(v)['replacements'].update({'foreign.rs': identity(v).copy()}),
                       lambda v: identity(v).update(old_sha256='0' * 64),
                       lambda v: identity(v).update(new_sha256=identity(v)['old_sha256']),
                       lambda v: identity(v).update(extra={})]
            for field in ['kind', 'base_head', 'base_tree', 'execution', 'hosts']:
                changes.append(lambda v, field=field: layer(v).pop(field))
            for field in ['old_sha256', 'new_sha256']:
                changes.append(lambda v, field=field: identity(v).pop(field))
            for change in changes:
                value = copy.deepcopy(self.manifest)
                change(value)
                with self.subTest(host=host, change=change), self.assertRaisesRegex(ValueError, 'schema'):
                    measured_profiles.load_manifest(SimpleNamespace(read_text=lambda: json.dumps(value)))
                with self.subTest(composed=host, change=change), self.assertRaisesRegex(ValueError, 'schema'):
                    measured_profiles.approved_source_map(value, host)

    def test_rollback_comment_literal_comma_and_transport_refusals(self):
        for host in measured_profiles.HOSTS:
            source = measured_profiles.approved_source_map(self.manifest, host)
            for path, identity in self.manifest['dynamics_world_format_admission']['hosts'][host]['replacements'].items():
                raw = (check.ROOT / path).read_bytes()
                physical = raw.replace(b'\n', b'\r\n') if host == 'windows-x64' and '/tests/' not in path else raw
                newline = b'\r\n' if b'\r\n' in physical else b'\n'
                bodies = [physical + b' ', physical + b'// unauthorized' + newline,
                          physical.replace(b'0', b'1', 1), physical + b',',
                          raw.replace(b'\n', b'\r\n') if '/tests/' in path or host != 'windows-x64' else raw,
                          physical.replace(newline, b'\r\n' if newline == b'\n' else b'\n', 1)]
                if '/src/' in path:
                    bodies.extend([physical.replace(b'capacity: usize }', b'capacity: usize, }', 1),
                                   physical.replace(b'//', b'// changed', 1)])
                hashes = [identity['old_sha256']] + [measured_profiles.sha(body) for body in bodies]
                for digest in hashes:
                    self.assertNotEqual(digest, source[path])
                    changed = dict(source, **{path: digest})
                    with self.subTest(host=host, path=path, digest=digest), self.assertRaisesRegex(ValueError, 'source closure'):
                        measured_profiles.validate(Path('/unused'), host=lambda: host, inventory=check.inventory,
                            source_hashes=lambda: changed, stream=check.stream, transport=check.transport)

    def test_coordinated_format_and_current_hash_refresh_is_refused(self):
        value = copy.deepcopy(self.manifest)
        for host in measured_profiles.HOSTS:
            delta = value['dynamics_world_format_admission']['hosts'][host]['replacements']
            for path in delta:
                delta[path]['new_sha256'] = '0' * 64
            value['verification_sha256'][host] = {path: '1' * 64 for path in value['verification_sha256'][host]}
        with self.assertRaisesRegex(ValueError, 'immutable dynamics world format admission'):
            measured_profiles.load_manifest(SimpleNamespace(read_text=lambda: json.dumps(value)))
        for host in measured_profiles.HOSTS:
            with self.assertRaisesRegex(ValueError, 'immutable dynamics world format admission'):
                measured_profiles.approved_source_map(value, host)



class DynamicsC23RepairAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.manifest = measured_profiles.load_manifest(measured_profiles.HERE / 'measured-profiles.json')

    def test_complete_physical_projection_and_historical_links(self):
        layer = self.manifest['dynamics_world_c23_repair_admission']
        self.assertEqual(measured_profiles.source_map_digest(layer), measured_profiles.DYNAMICS_WORLD_C23_REPAIR_SHA256)
        self.assertEqual(layer['execution'], 'UNRUN')
        for host in measured_profiles.HOSTS:
            source = measured_profiles.approved_source_map(self.manifest, host)
            self.assertEqual(len(source), 482)
            replacements = layer['hosts'][host]['replacements']
            self.assertEqual(set(replacements), measured_profiles.DYNAMICS_WORLD_C23_REPAIR_REPLACEMENTS)
            for path, identity in replacements.items():
                previous = (self.manifest['dynamics_world_format_admission']['hosts'][host]['replacements'][path]['new_sha256']
                            if '/tests/' in path else self.manifest['dynamics_world_source_admission']['hosts'][host]['replacements'][path]['new_sha256'])
                self.assertEqual(identity['old_sha256'], previous)
                raw = (check.ROOT / path).read_bytes()
                self.assertNotIn(b'\r', raw)
                physical = raw.replace(b'\n', b'\r\n') if host == 'windows-x64' and '/tests/' not in path else raw
                if '/tests/' in path:
                    formatting = self.manifest['dynamics_world_c23_test_format_admission']['hosts'][host]['replacements'][path]
                    self.assertEqual(identity['new_sha256'], formatting['old_sha256'])
                    self.assertEqual(formatting['new_sha256'], measured_profiles.sha(physical))
                    self.assertEqual(source[path], formatting['new_sha256'])
                else:
                    self.assertEqual(identity['new_sha256'], measured_profiles.sha(physical))
                    self.assertEqual(source[path], identity['new_sha256'])

    def test_closed_schema_scope_and_composed_old_identity_refusals(self):
        key = 'dynamics_world_c23_repair_admission'
        for host in measured_profiles.HOSTS:
            path = sorted(measured_profiles.DYNAMICS_WORLD_C23_REPAIR_REPLACEMENTS)[0]
            def layer(value): return value[key]
            def delta(value): return layer(value)['hosts'][host]
            def identity(value): return delta(value)['replacements'][path]
            changes = [lambda v: v.update(schema_version=9),
                       lambda v: layer(v).update(kind='other'),
                       lambda v: layer(v).update(base_head='0' * 40),
                       lambda v: layer(v).update(base_tree='0' * 40),
                       lambda v: layer(v).update(execution='PASS'),
                       lambda v: layer(v).update(extra={}),
                       lambda v: layer(v)['hosts'].pop(host),
                       lambda v: layer(v)['hosts'].update(extra={}),
                       lambda v: delta(v).update(additions={}),
                       lambda v: delta(v)['replacements'].pop(path),
                       lambda v: delta(v)['replacements'].update({measured_profiles.MANIFEST_PATH: identity(v).copy()}),
                       lambda v: identity(v).update(old_sha256='0' * 64),
                       lambda v: identity(v).update(new_sha256=identity(v)['old_sha256']),
                       lambda v: identity(v).update(new_sha256='Z' * 64),
                       lambda v: identity(v).update(extra={})]
            for field in ['kind', 'base_head', 'base_tree', 'execution', 'hosts']:
                changes.append(lambda v, field=field: layer(v).pop(field))
            for field in ['old_sha256', 'new_sha256']:
                changes.append(lambda v, field=field: identity(v).pop(field))
            for change in changes:
                value = copy.deepcopy(self.manifest)
                change(value)
                with self.subTest(host=host, change=change), self.assertRaisesRegex(ValueError, 'schema'):
                    measured_profiles.load_manifest(SimpleNamespace(read_text=lambda: json.dumps(value)))
                if value['schema_version'] == 12:
                    with self.subTest(composed=host, change=change), self.assertRaisesRegex(ValueError, 'schema'):
                        measured_profiles.approved_source_map(value, host)

    def test_rollback_transport_body_and_coordinated_hash_refusals(self):
        for host in measured_profiles.HOSTS:
            source = measured_profiles.approved_source_map(self.manifest, host)
            replacements = self.manifest['dynamics_world_c23_repair_admission']['hosts'][host]['replacements']
            for path, identity in replacements.items():
                raw = (check.ROOT / path).read_bytes()
                physical = raw.replace(b'\n', b'\r\n') if host == 'windows-x64' and '/tests/' not in path else raw
                bodies = [physical + b' ', physical + b'// unauthorized\n',
                          physical.replace(b'0', b'1', 1),
                          raw.replace(b'\n', b'\r\n') if '/tests/' in path or host != 'windows-x64' else raw,
                          physical.replace(b'\n', b'\r\n', 1)]
                for digest in [identity['old_sha256']] + [measured_profiles.sha(body) for body in bodies]:
                    self.assertNotEqual(digest, source[path])
                    changed = dict(source, **{path: digest})
                    with self.subTest(host=host, path=path), self.assertRaisesRegex(ValueError, 'source closure'):
                        measured_profiles.validate(Path('/unused'), host=lambda: host, inventory=check.inventory,
                            source_hashes=lambda: changed, stream=check.stream, transport=check.transport)
        value = copy.deepcopy(self.manifest)
        for host in measured_profiles.HOSTS:
            for identity in value['dynamics_world_c23_repair_admission']['hosts'][host]['replacements'].values():
                identity['new_sha256'] = '0' * 64
            value['verification_sha256'][host] = {path: '1' * 64 for path in value['verification_sha256'][host]}
        with self.assertRaisesRegex(ValueError, 'immutable dynamics world c23 repair admission'):
            measured_profiles.load_manifest(SimpleNamespace(read_text=lambda: json.dumps(value)))
        for host in measured_profiles.HOSTS:
            with self.assertRaisesRegex(ValueError, 'immutable dynamics world c23 repair admission'):
                measured_profiles.approved_source_map(value, host)


class DynamicsC23TestFormatAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.manifest = measured_profiles.load_manifest(measured_profiles.HERE / 'measured-profiles.json')

    def test_complete_physical_projection_and_historical_links(self):
        layer = self.manifest['dynamics_world_c23_test_format_admission']
        self.assertEqual(measured_profiles.source_map_digest(layer), measured_profiles.DYNAMICS_WORLD_C23_TEST_FORMAT_SHA256)
        self.assertEqual(layer['execution'], 'UNRUN')
        for host in measured_profiles.HOSTS:
            source = measured_profiles.approved_source_map(self.manifest, host)
            self.assertEqual(len(source), 482)
            replacements = layer['hosts'][host]['replacements']
            self.assertEqual(set(replacements), measured_profiles.DYNAMICS_WORLD_C23_TEST_FORMAT_REPLACEMENTS)
            for path, identity in replacements.items():
                previous = self.manifest['dynamics_world_c23_repair_admission']['hosts'][host]['replacements'][path]['new_sha256']
                self.assertEqual(identity['old_sha256'], previous)
                raw = (check.ROOT / path).read_bytes()
                self.assertNotIn(b'\r', raw)
                self.assertEqual(identity['new_sha256'], measured_profiles.sha(raw))
                self.assertEqual(source[path], identity['new_sha256'])
                old = b'    assert_eq!(current.interpolation_linear_velocity, Vec3([0.0, -1.0, 0.0]));'
                formatted = b'    assert_eq!(\n        current.interpolation_linear_velocity,\n        Vec3([0.0, -1.0, 0.0])\n    );'
                self.assertEqual(raw.count(formatted), 1)
                before = raw.replace(formatted, old)
                self.assertEqual(measured_profiles.sha(before), identity['old_sha256'])
                self.assertEqual(before.replace(old, formatted), raw)
                expected = (set(self.manifest['profiles'][host]['protected_source_sha256'])
                            | set(self.manifest['verification_sha256'][host]) | measured_profiles.ADDITIONS
                            | measured_profiles.BROADPHASE_ADDITIONS | measured_profiles.DISCRETE_WORLD_ADDITIONS
                            | measured_profiles.DYNAMICS_WORLD_ADDITIONS | measured_profiles.MMD_COLLISION_WORLD_ADDITIONS)
                self.assertEqual(set(source), expected)

    def test_closed_schema_scope_and_composed_old_identity_refusals(self):
        self.test_complete_physical_projection_and_historical_links()
        key = 'dynamics_world_c23_test_format_admission'
        for host in measured_profiles.HOSTS:
            path = sorted(measured_profiles.DYNAMICS_WORLD_C23_TEST_FORMAT_REPLACEMENTS)[0]
            def layer(value): return value[key]
            def delta(value): return layer(value)['hosts'][host]
            def identity(value): return delta(value)['replacements'][path]
            changes = [lambda v: v.update(schema_version=10),
                       lambda v: v.pop(key),
                       lambda v: layer(v).update(kind='other'),
                       lambda v: layer(v).update(base_head='0' * 40),
                       lambda v: layer(v).update(base_tree='0' * 40),
                       lambda v: layer(v).update(execution='PASS'),
                       lambda v: layer(v).update(extra={}),
                       lambda v: layer(v)['hosts'].pop(host),
                       lambda v: layer(v)['hosts'].update(extra={}),
                       lambda v: delta(v).update(additions={}),
                       lambda v: delta(v).update(replacements={}),
                       lambda v: delta(v)['replacements'].update({'rust/crates/mds-bullet/src/core/discrete_collision_world.rs': identity(v).copy()}),
                       lambda v: delta(v)['replacements'].pop(path),
                       lambda v: delta(v)['replacements'].update({measured_profiles.MANIFEST_PATH: identity(v).copy()}),
                       lambda v: identity(v).update(old_sha256='0' * 64),
                       lambda v: identity(v).update(new_sha256=identity(v)['old_sha256']),
                       lambda v: identity(v).update(new_sha256='Z' * 64),
                       lambda v: identity(v).update(extra={})]
            for field in ['kind', 'base_head', 'base_tree', 'execution', 'hosts']:
                changes.append(lambda v, field=field: layer(v).pop(field))
            for field in ['old_sha256', 'new_sha256']:
                changes.append(lambda v, field=field: identity(v).pop(field))
            for change in changes:
                value = copy.deepcopy(self.manifest)
                change(value)
                with self.subTest(host=host, change=change), self.assertRaisesRegex(ValueError, 'schema'):
                    measured_profiles.load_manifest(SimpleNamespace(read_text=lambda: json.dumps(value)))
                with self.subTest(composed=host, change=change), self.assertRaisesRegex(ValueError, 'schema'):
                    measured_profiles.approved_source_map(value, host)

    def test_rollback_transport_body_and_coordinated_hash_refusals(self):
        self.test_complete_physical_projection_and_historical_links()
        for host in measured_profiles.HOSTS:
            source = measured_profiles.approved_source_map(self.manifest, host)
            replacements = self.manifest['dynamics_world_c23_test_format_admission']['hosts'][host]['replacements']
            for path, identity in replacements.items():
                raw = (check.ROOT / path).read_bytes()
                physical = raw.replace(b'\n', b'\r\n') if host == 'windows-x64' and '/tests/' not in path else raw
                bodies = [physical + b' ', physical + b'// unauthorized\n',
                          physical.replace(b'0', b'1', 1), physical + b',',
                          raw.replace(b'\n', b'\r\n') if '/tests/' in path or host != 'windows-x64' else raw,
                          physical.replace(b'\n', b'\r\n', 1)]
                for digest in [identity['old_sha256']] + [measured_profiles.sha(body) for body in bodies]:
                    self.assertNotEqual(digest, source[path])
                    changed = dict(source, **{path: digest})
                    with self.subTest(host=host, path=path), self.assertRaisesRegex(ValueError, 'source closure'):
                        measured_profiles.validate(Path('/unused'), host=lambda: host, inventory=check.inventory,
                            source_hashes=lambda: changed, stream=check.stream, transport=check.transport)
        value = copy.deepcopy(self.manifest)
        for host in measured_profiles.HOSTS:
            for identity in value['dynamics_world_c23_test_format_admission']['hosts'][host]['replacements'].values():
                identity['new_sha256'] = '0' * 64
            value['verification_sha256'][host] = {path: '1' * 64 for path in value['verification_sha256'][host]}
        with self.assertRaisesRegex(ValueError, 'immutable dynamics world c23 test format admission'):
            measured_profiles.load_manifest(SimpleNamespace(read_text=lambda: json.dumps(value)))
        for host in measured_profiles.HOSTS:
            with self.assertRaisesRegex(ValueError, 'immutable dynamics world c23 test format admission'):
                measured_profiles.approved_source_map(value, host)


class DynamicsAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.manifest = measured_profiles.load_manifest(measured_profiles.HERE / 'measured-profiles.json')

    def test_complete_exact_physical_projection_and_fixed_layer(self):
        admission = self.manifest['dynamics_world_source_admission']
        self.assertEqual(admission['execution'], 'UNRUN')
        self.assertEqual(measured_profiles.source_map_digest(admission), measured_profiles.DYNAMICS_WORLD_SHA256)
        for host in measured_profiles.HOSTS:
            result = measured_profiles.approved_source_map(self.manifest, host)
            for path in measured_profiles.DYNAMICS_WORLD_REPLACEMENTS | measured_profiles.DYNAMICS_WORLD_ADDITIONS:
                raw = (check.ROOT / path).read_bytes().replace(b'\r\n', b'\n')
                physical = raw.replace(b'\n', b'\r\n') if host == 'windows-x64' and '/tests/' not in path else raw
                self.assertEqual(result[path], measured_profiles.sha(physical))

    def test_scope_identity_hosts_and_fixed_base_fail_closed(self):
        def delta(value): return value['dynamics_world_source_admission']['hosts']['linux-x64']
        path = next(iter(measured_profiles.DYNAMICS_WORLD_REPLACEMENTS))
        changes = [
            lambda value: value['dynamics_world_source_admission'].update(base_head='0'*40),
            lambda value: value['dynamics_world_source_admission'].update(base_tree='0'*40),
            lambda value: value['dynamics_world_source_admission'].update(execution='PASS'),
            lambda value: value['dynamics_world_source_admission']['hosts'].pop('windows-x64'),
            lambda value: value['dynamics_world_source_admission']['hosts'].update(extra={}),
            lambda value: delta(value)['replacements'].pop(path),
            lambda value: delta(value)['replacements'].update({'foreign.rs': {'old_sha256':'0'*64,'new_sha256':'1'*64}}),
            lambda value: delta(value)['replacements'][path].update(old_sha256='0'*64),
            lambda value: delta(value)['replacements'][path].update(new_sha256=delta(value)['replacements'][path]['old_sha256']),
            lambda value: delta(value)['additions'].update({path:'0'*64}),
            lambda value: delta(value)['additions'].pop(next(iter(measured_profiles.DYNAMICS_WORLD_ADDITIONS))),
        ]
        for change in changes:
            value = copy.deepcopy(self.manifest)
            change(value)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'schema'):
                measured_profiles.approved_source_map(value, 'linux-x64')
            reader = SimpleNamespace(read_text=lambda value=value: json.dumps(value))
            with self.subTest(pinned_change=change), self.assertRaisesRegex(ValueError, 'schema'):
                measured_profiles.load_manifest(reader)


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
            (Path(temp) / 'source-head.txt').write_bytes(b'1' * 40 + b'\n')
            (Path(temp) / 'provenance.txt').write_text('deliberately unreviewed compiler')
            result = subprocess.run([sys.executable, '-B', *(['-O'] if sys.flags.optimize else []), '-c', script, check.__file__, temp],
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
                self.assertEqual(measured_profiles.select_measurement(self.manifest, host, provenance), measurement)
                reversed_manifest = copy.deepcopy(self.manifest)
                reversed_manifest['profiles'][host]['measurements'].reverse()
                self.assertEqual(measured_profiles.select_measurement(reversed_manifest, host, provenance), measurement)
                for broken in [provenance.replace(provenance.splitlines()[0], 'third kernel'),
                               provenance.replace('rustc', 'unmeasured-rustc'), provenance + 'extra\n',
                               provenance.replace('clang', 'unmeasured-clang'), provenance.replace('\n', '\r', 1),
                               provenance.replace('\n', '\r\n', 1)]:
                    if broken != provenance:
                        with self.assertRaisesRegex(ValueError, 'compiler or toolchain'):
                            measured_profiles.select_measurement(self.manifest, host, broken)
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

    def test_history_anchor_rejects_coordinated_source_digest_refresh(self):
        def coordinated(value):
            profile = value['profiles']['linux-x64']
            path = next(iter(profile['protected_source_sha256']))
            profile['protected_source_sha256'][path] = '0' * 64
            identity = measured_profiles.source_map_digest({**profile['protected_source_sha256'],
                                                         **profile['measured_verification_sha256']})
            for measurement in profile['measurements']:
                measurement['capture_source_map_sha256'] = identity
        with self.assertRaisesRegex(ValueError, 'immutable historical projection'):
            self.load_changed(coordinated)
        with self.assertRaisesRegex(ValueError, 'immutable historical projection'):
            self.load_changed(lambda value: value['profiles']['linux-x64']['measurements'].reverse())
        self.assertEqual(measured_profiles.source_map_digest({name: self.manifest[name]
                         for name in ['profiles', 'frozen_fixtures']}),
                         'db3da5b75c9c53145e6be0aec4f83264f3a0bbce2a128ea321caf24ae0e7e501')

    def test_exact_bounded_source_admission_rejects_malformed_delta(self):
        def delta(value):
            return value['source_admission']['hosts']['linux-x64']
        replacement = next(iter(measured_profiles.REPLACEMENTS))
        addition = next(iter(measured_profiles.ADDITIONS))
        changes = [lambda v: v['source_admission'].update(extra={}),
                   lambda v: v['source_admission'].update(kind='another-bridge'),
                   lambda v: v['source_admission']['hosts'].pop('windows-x64'),
                   lambda v: v['source_admission']['hosts'].update(unknown={}),
                   lambda v: delta(v).update(extra={}),
                   lambda v: delta(v)['replacements'].update({replacement: v['profiles']['linux-x64']['protected_source_sha256'][replacement]})]
        for name in ['reviewed_base_head', 'integration_head', 'integration_tree']:
            for bad in [None, True, '0' * 40, 'invalid']:
                changes.append(lambda v, name=name, bad=bad: v['source_admission'].update({name: bad}))
        for name, path in [('replacements', replacement), ('additions', addition)]:
            changes.extend([lambda v, name=name, path=path: delta(v)[name].pop(path),
                            lambda v, name=name: delta(v)[name].update({'extra': '0' * 64}),
                            lambda v, name=name: delta(v).update({name: []})])
            for bad in [None, True, 1, 'A' * 64, '0' * 63]:
                changes.append(lambda v, name=name, path=path, bad=bad: delta(v)[name].update({path: bad}))
            for substitute in [replacement if name == 'additions' else addition,
                               'rust/crates/mds-bullet/src/core/math.rs', measured_profiles.MANIFEST_PATH,
                               '/absolute', '../escape', 'C:/drive', 'bad\\path', 'bad/./path', 'bad//path', 'bad\npath']:
                def change(v, name=name, path=path, substitute=substitute):
                    delta(v)[name][substitute] = delta(v)[name].pop(path)
                changes.append(change)
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'schema'):
                self.load_changed(change)
        for host in measured_profiles.HOSTS:
            current = measured_profiles.approved_source_map(self.manifest, host)
            self.assertEqual(set(current), set(self.manifest['profiles'][host]['protected_source_sha256'])
                             | measured_profiles.ADDITIONS | measured_profiles.BROADPHASE_ADDITIONS
                             | measured_profiles.DISCRETE_WORLD_ADDITIONS | measured_profiles.DYNAMICS_WORLD_ADDITIONS
                             | measured_profiles.MMD_COLLISION_WORLD_ADDITIONS
                             | set(self.manifest['verification_sha256'][host]))

    def test_discrete_world_current_only_admission_refuses_identity_and_scope_drift(self):
        admission = self.manifest['discrete_world_source_admission']
        self.assertEqual(measured_profiles.source_map_digest(admission), measured_profiles.DISCRETE_WORLD_SHA256)
        self.assertEqual(admission['execution'], 'UNRUN')
        self.assertEqual((check.ROOT / 'rust/.gitattributes').read_bytes().replace(b'\r\n', b'\n'),
                         b'crates/*/tests/** -text\n')
        for path in measured_profiles.DISCRETE_WORLD_ADDITIONS:
            raw = (check.ROOT / path).read_bytes().replace(b'\r\n', b'\n')
            windows = raw if '/tests/' in path else raw.replace(b'\n', b'\r\n')
            current = measured_profiles.approved_source_map(self.manifest, 'windows-x64')
            historical = admission['hosts']['windows-x64']['additions'][path]
            if path in measured_profiles.DYNAMICS_WORLD_REPLACEMENTS:
                dynamics = self.manifest['dynamics_world_source_admission']['hosts']['windows-x64']['replacements'][path]
                self.assertEqual(historical, dynamics['old_sha256'])
                repair = self.manifest['dynamics_world_c23_repair_admission']['hosts']['windows-x64']['replacements'][path]
                self.assertEqual(dynamics['new_sha256'], repair['old_sha256'])
                self.assertEqual(repair['new_sha256'], current[path])
            else:
                self.assertEqual(historical, current[path])
            self.assertEqual(current[path], measured_profiles.sha(windows))
        for field in admission:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'schema'):
                self.load_changed(lambda value: value['discrete_world_source_admission'].pop(field))
        for host in measured_profiles.HOSTS:
            delta = admission['hosts'][host]
            self.assertEqual(set(delta['additions']), measured_profiles.DISCRETE_WORLD_ADDITIONS)
            self.assertEqual(set(delta['replacements']), measured_profiles.DISCRETE_WORLD_REPLACEMENTS)
            for kind in ['replacements', 'additions']:
                for path in delta[kind]:
                    with self.subTest(host=host, path=path), self.assertRaisesRegex(ValueError, 'schema'):
                        self.load_changed(lambda value: value['discrete_world_source_admission']['hosts'][host][kind].pop(path))
            for path in measured_profiles.DISCRETE_WORLD_ADDITIONS | measured_profiles.DISCRETE_WORLD_REPLACEMENTS:
                source = measured_profiles.approved_source_map(self.manifest, host)
                for changed in [dict(source, **{path: '0' * 64}),
                                {p: h for p, h in source.items() if p != path},
                                dict(source, **{'unexpected-owner.rs': source[path]})]:
                    with self.subTest(host=host, path=path), self.assertRaisesRegex(ValueError, 'source closure'):
                        measured_profiles.validate(Path('/unused'), host=lambda: host,
                            inventory=check.inventory, source_hashes=lambda: changed,
                            stream=check.stream, transport=check.transport)

    def test_supplemental_exact_selection_and_global_identities(self):
        measurement, = self.manifest['supplemental_measurements']
        self.assertEqual(measurement['evidence_head'], '46b54133d247322027915733b4acf51574298c68')
        self.assertEqual((measurement['run_id'], measurement['job_id'], measurement['artifact_id']),
                         (40550671157, 122353217320, 12755645749))
        for provenance in [measurement['compiler_provenance'], measurement['compiler_provenance'].replace('\n', '\r\n')]:
            self.assertEqual(measured_profiles.select_measurement(self.manifest, 'linux-arm64', provenance), measurement)
            for host in measured_profiles.HOSTS - {'linux-arm64'}:
                with self.assertRaisesRegex(ValueError, 'compiler or toolchain'):
                    measured_profiles.select_measurement(self.manifest, host, provenance)
        duplicate = copy.deepcopy(self.manifest)
        duplicate['supplemental_measurements'].append(measurement)
        with self.assertRaisesRegex(ValueError, 'compiler or toolchain'):
            measured_profiles.select_measurement(duplicate, 'linux-arm64', measurement['compiler_provenance'])
        historical = [m for p in self.manifest['profiles'].values() for m in p['measurements']]
        self.assertLess(len({m['run_id'] for m in historical}), len(historical))
        self.assertEqual(len({m['job_id'] for m in historical}), len(historical))

    def test_unselected_supplement_and_coordinated_tampering_fail_closed(self):
        def supplemental(value):
            return value['supplemental_measurements'][0]
        def refresh_capture(value):
            measurement = supplemental(value)
            current = measured_profiles.bridge_protected_source_map(value, 'linux-arm64')
            current.update(value['verification_sha256']['linux-arm64'])
            measurement['capture_source_map_sha256'] = measured_profiles.source_map_digest({
                **current, **measurement['captured_verification_sha256']})
        def coordinated(value):
            path = sorted(measured_profiles.REPLACEMENTS)[0]
            value['source_admission']['hosts']['linux-arm64']['replacements'][path] = '0' * 64
            value['verification_sha256']['linux-arm64'] = dict(supplemental(value)['captured_verification_sha256'])
            refresh_capture(value)
        def current_as_capture(value):
            supplemental(value)['captured_verification_sha256'] = dict(value['verification_sha256']['linux-arm64'])
            refresh_capture(value)
        changes = [lambda v: v.update(supplemental_measurements=[]),
                   lambda v: v.update(supplemental_measurements={}),
                   lambda v: v['supplemental_measurements'].append(copy.deepcopy(supplemental(v))),
                   lambda v: supplemental(v).update(host='linux-x64'),
                   lambda v: supplemental(v).update(host=[]),
                   lambda v: supplemental(v)['captured_verification_sha256'].pop(next(iter(supplemental(v)['captured_verification_sha256']))),
                   lambda v: supplemental(v)['captured_verification_sha256'].update(extra='0' * 64),
                   coordinated, current_as_capture]
        for field in measured_profiles.MEASUREMENT_FIELDS | {'host', 'captured_verification_sha256'}:
            changes.append(lambda v, field=field: supplemental(v).pop(field))
        for field in ['job_id', 'artifact_id', 'compiler_provenance']:
            changes.append(lambda v, field=field: supplemental(v).update({field: v['profiles']['linux-x64']['measurements'][0][field]}))
        for field in ['run_id', 'job_id', 'artifact_id']:
            for bad in [True, 0, '1']:
                changes.append(lambda v, field=field, bad=bad: supplemental(v).update({field: bad}))
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'schema'):
                self.load_changed(change)
        with self.assertRaisesRegex(ValueError, 'immutable source admission'):
            self.load_changed(coordinated)
        captured = self.manifest['supplemental_measurements'][0]['captured_verification_sha256']
        self.assertNotEqual(captured, self.manifest['verification_sha256']['linux-arm64'])

    def test_protected_observer_stays_rejected_with_refreshed_verification(self):
        with self.assertRaisesRegex(ValueError, 'immutable baseline verification'):
            self.load_changed(lambda value: value['verification_sha256']['linux-arm64'].update(
                {path: '1' * 64 for path in value['verification_sha256']['linux-arm64']}))
        source = measured_profiles.approved_source_map(self.manifest, 'linux-arm64')
        source['tools/bullet-rust-gjk-pair-check/observe.py'] = '0' * 64
        with patch.object(measured_profiles, 'load_manifest', return_value=self.manifest):
            with self.assertRaisesRegex(ValueError, 'source closure'):
                measured_profiles.validate(Path('/unused'), host=lambda: 'linux-arm64',
                    inventory=check.inventory, source_hashes=lambda: source,
                    stream=check.stream, transport=check.transport)

    def test_fixed_registration_format_tuple_rejects_every_override(self):
        admission = self.manifest['registration_format_admission']
        self.assertEqual(set(admission), {'kind', 'parent_head', 'format_head', 'format_tree',
                                         'path', 'old_sha256', 'new_sha256'})
        changes = [lambda v: v.update(registration_format_admission=[]),
                   lambda v: v['registration_format_admission'].update(extra={}),
                   lambda v: v.update(registration_format_admissions=[admission])]
        for field in admission:
            changes.extend([lambda v, field=field: v['registration_format_admission'].pop(field),
                            lambda v, field=field: v['registration_format_admission'].update({field: '0' * 64})])
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'schema'):
                self.load_changed(change)

    def test_captured_bridge_is_independent_of_current_format_and_verification(self):
        measurement, = self.manifest['supplemental_measurements']
        self.assertEqual(measured_profiles.source_map_digest(self.manifest['source_admission']),
                         'f210f29ada5dfc664dc70bd738e561f84ce9c11c0db239674596fb557f5c6c63')
        for host in measured_profiles.HOSTS:
            old = measured_profiles.bridge_protected_source_map(self.manifest, host)
            self.assertEqual(len(old), 464)
            self.assertEqual(old[measured_profiles.REGISTRATION_FORMAT['path']],
                             measured_profiles.REGISTRATION_FORMAT['old_sha256'])
            current = measured_profiles.approved_source_map(self.manifest, host)
            historical=set(self.manifest['profiles'][host]['protected_source_sha256'])
            self.assertEqual(set(old),historical | measured_profiles.ADDITIONS)
            replacements={measured_profiles.REGISTRATION_FORMAT['path']}
            for layer in ['broadphase_source_admission','discrete_world_source_admission',
                          'dynamics_world_source_admission','dynamics_world_format_admission',
                          'dynamics_world_c23_repair_admission', 'dynamics_world_c23_test_format_admission',
                          'mmd_collision_world_source_admission']:
                replacements.update(self.manifest[layer]['hosts'][host]['replacements'])
            expected=replacements & historical
            self.assertEqual(expected,measured_profiles.REPLACEMENTS | {
                'rust/crates/mds-bullet/src/core/world_objects.rs'})
            self.assertEqual({path for path in old if old[path] != current[path]},expected)
        captured = {**measured_profiles.bridge_protected_source_map(self.manifest, 'linux-arm64'),
                    **measurement['captured_verification_sha256']}
        self.assertEqual(measured_profiles.source_map_digest(captured),
                         'db721138ff4e155d5c413144497d8718844b0ac95501f0499401b3a3929dbfb9')
        changed = copy.deepcopy(self.manifest)
        changed['registration_format_admission'] = None
        changed['verification_sha256'] = None
        self.assertEqual(measured_profiles.bridge_protected_source_map(changed, 'linux-arm64'),
                         measured_profiles.bridge_protected_source_map(self.manifest, 'linux-arm64'))

    def test_all_host_bridge_cannot_be_coordinated_with_current_and_captured_hashes(self):
        def coordinated(value):
            for host in measured_profiles.HOSTS:
                delta = value['source_admission']['hosts'][host]
                delta['replacements'][sorted(measured_profiles.REPLACEMENTS)[0]] = '0' * 64
                value['verification_sha256'][host] = {p: '1' * 64 for p in value['verification_sha256'][host]}
            supplemental = value['supplemental_measurements'][0]
            supplemental['captured_verification_sha256'] = dict(value['verification_sha256']['linux-arm64'])
            supplemental['capture_source_map_sha256'] = measured_profiles.source_map_digest({
                **measured_profiles.bridge_protected_source_map(value, 'linux-arm64'),
                **supplemental['captured_verification_sha256']})
        with self.assertRaisesRegex(ValueError, 'immutable source admission'):
            self.load_changed(coordinated)

    def test_exact_format_physical_bytes_and_source_refusals_on_every_host(self):
        admission = self.manifest['registration_format_admission']
        data = (check.ROOT / admission['path']).read_bytes()
        current_identity = self.manifest['broadphase_source_admission']['hosts']['macos-arm64']['replacements'][admission['path']]
        self.assertEqual(current_identity['old_sha256'], admission['new_sha256'])
        self.assertEqual(measured_profiles.sha(data), current_identity['new_sha256'])
        for host in measured_profiles.HOSTS:
            source = measured_profiles.approved_source_map(self.manifest, host)
            for broken in [b'\n' + data, data.replace(b'\n', b'\r\n'), data + b' ',
                           data.replace(b'mod ', b'mod changed_', 1)]:
                changed = dict(source, **{admission['path']: measured_profiles.sha(broken)})
                with self.subTest(host=host), self.assertRaisesRegex(ValueError, 'source closure'):
                    measured_profiles.validate(Path('/unused'), host=lambda: host, inventory=check.inventory,
                        source_hashes=lambda: changed, stream=check.stream, transport=check.transport)

    def test_fixed_broadphase_admission_and_all_metadata_refusals(self):
        admission = self.manifest['broadphase_source_admission']
        self.assertEqual(measured_profiles.source_map_digest(admission),
                         measured_profiles.BROADPHASE_SHA256)
        self.assertEqual(admission['integration_head'], '83ec9ed6208c10c5eb589a31214eab5f6b689775')
        self.assertEqual(admission['integration_tree'], '382a56bb424f08edfbef33922e852795877a4e59')
        self.assertEqual(admission['integration_parents'], [
            'ea13392ff8db43e1059c7037f571c136e72831f2',
            '06c1d0678ebf2abf62271a34d39311b2880757f7'])
        changes = [lambda v: v.pop('broadphase_source_admission'),
                   lambda v: v.update(broadphase_source_admissions=[admission]),
                   lambda v: v['broadphase_source_admission'].update(extra={}),
                   lambda v: v['broadphase_source_admission'].update(integration_parents=list(reversed(admission['integration_parents']))) ]
        for field in admission:
            changes.append(lambda v, field=field: v['broadphase_source_admission'].pop(field))
            changes.append(lambda v, field=field: v['broadphase_source_admission'].update({field: '0' * 40}))
        for host in measured_profiles.HOSTS:
            def delta(v):
                return v['broadphase_source_admission']['hosts'][host]
            for path in measured_profiles.REPLACEMENTS:
                for field in ['old_sha256', 'new_sha256']:
                    changes.append(lambda v, host=host, path=path, field=field:
                        v['broadphase_source_admission']['hosts'][host]['replacements'][path].update({field: '0' * 64}))
            for name, paths in [('replacements', measured_profiles.REPLACEMENTS),
                                ('additions', measured_profiles.BROADPHASE_ADDITIONS)]:
                path = sorted(paths)[0]
                changes.append(lambda v, host=host, name=name, path=path:
                    v['broadphase_source_admission']['hosts'][host][name].pop(path))
                for substitute in ['unknown.rs', measured_profiles.MANIFEST_PATH,
                                   '../escape', 'bad\\path', *measured_profiles.REPLACEMENTS,
                                   *measured_profiles.BROADPHASE_ADDITIONS]:
                    if substitute == path:
                        continue
                    def change(v, host=host, name=name, path=path, substitute=substitute):
                        d = v['broadphase_source_admission']['hosts'][host][name]
                        d[substitute] = d.pop(path)
                    changes.append(change)
        def coordinated(v):
            for host in measured_profiles.HOSTS:
                d = v['broadphase_source_admission']['hosts'][host]
                for identity in d['replacements'].values():
                    identity.update(old_sha256='0' * 64, new_sha256='1' * 64)
                d['additions'] = {p: '2' * 64 for p in d['additions']}
                v['verification_sha256'][host] = {p: '3' * 64 for p in v['verification_sha256'][host]}
        changes.append(coordinated)
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'schema'):
                self.load_changed(change)

    def test_current_collector_and_broadphase_physical_source_refusals(self):
        current = check.source_hashes()
        current.pop(measured_profiles.MANIFEST_PATH)
        self.assertEqual(current, measured_profiles.approved_source_map(self.manifest, check.host()))
        for host in measured_profiles.HOSTS:
            source = measured_profiles.approved_source_map(self.manifest, host)
            self.assertNotIn(measured_profiles.MANIFEST_PATH, source)
            for path in (measured_profiles.REPLACEMENTS | measured_profiles.BROADPHASE_ADDITIONS
                         | measured_profiles.DISCRETE_WORLD_ADDITIONS | measured_profiles.DYNAMICS_WORLD_ADDITIONS
                         | measured_profiles.MMD_COLLISION_WORLD_ADDITIONS | measured_profiles.MMD_COLLISION_WORLD_REPLACEMENTS):
                mutations = [dict(source, **{path: '0' * 64}),
                             {p: h for p, h in source.items() if p != path},
                             dict(source, **{'unknown.rs': source[path]})]
                data = (check.ROOT / path).read_bytes()
                physical = [data + b' ', data.replace(b'\n', b'\r\n')]
                if path in measured_profiles.REPLACEMENTS:
                    mutations.append(dict(source, **{path: self.manifest['broadphase_source_admission']['hosts'][host]['replacements'][path]['old_sha256']}))
                for body in physical:
                    identity = measured_profiles.sha(body)
                    if identity != source[path]:
                        mutations.append(dict(source, **{path: identity}))
                for changed in mutations:
                    with self.subTest(host=host, path=path), self.assertRaisesRegex(ValueError, 'source closure'):
                        measured_profiles.validate(Path('/unused'), host=lambda: host,
                            inventory=check.inventory, source_hashes=lambda: changed,
                            stream=check.stream, transport=check.transport)

    def test_physical_source_expectation_uses_exact_supported_host(self):
        path = 'rust/crates/mds-bullet/src/core/dbvt.rs'
        expectations = [
            ('Darwin', 'arm64', 'macos-arm64', 'f70819446e34a506b5c71bd74410b618647f9c3c16c1deee0c009e4dc5f76bfe'),
            ('Linux', 'x86_64', 'linux-x64', 'f70819446e34a506b5c71bd74410b618647f9c3c16c1deee0c009e4dc5f76bfe'),
            ('Linux', 'aarch64', 'linux-arm64', 'f70819446e34a506b5c71bd74410b618647f9c3c16c1deee0c009e4dc5f76bfe'),
            ('Windows', 'AMD64', 'windows-x64', '0dc9af5d7af0df8bf8492ab3c8ac5903fa27f29f674391679c372edaa147c26c'),
        ]
        for system, machine, host, identity in expectations:
            source = measured_profiles.approved_source_map(self.manifest, host)
            source[measured_profiles.MANIFEST_PATH] = measured_profiles.sha((measured_profiles.HERE / 'measured-profiles.json').read_bytes())
            self.assertEqual(source[path], identity)
            with self.subTest(host=host), patch('host_profiles.platform.system', return_value=system), \
                    patch('host_profiles.platform.machine', return_value=machine), \
                    patch.object(self, 'assertEqual', side_effect=lambda left, right: self.assertTrue(left == right)):
                self.assertEqual(check.host(), host)
                with patch.object(check, 'source_hashes', side_effect=lambda: dict(source)):
                    self.test_current_collector_and_broadphase_physical_source_refusals()
                crossed_host = 'macos-arm64' if host == 'windows-x64' else 'windows-x64'
                crossed = measured_profiles.approved_source_map(self.manifest, crossed_host)
                crossed[measured_profiles.MANIFEST_PATH] = source[measured_profiles.MANIFEST_PATH]
                with patch.object(check, 'source_hashes', side_effect=lambda: dict(crossed)), self.assertRaises(AssertionError):
                    self.test_current_collector_and_broadphase_physical_source_refusals()
        for system, machine in [('Darwin', 'x86_64'), ('Windows', 'x86')]:
            with self.subTest(system=system, machine=machine), patch('host_profiles.platform.system', return_value=system), \
                    patch('host_profiles.platform.machine', return_value=machine), self.assertRaisesRegex(ValueError, 'Unsupported host'):
                check.host()

    def test_synthetic_replay_receipts_and_contract_guards(self):
        fixture = check.ROOT / 'rust/crates/mds-bullet/tests/gjk_pair_data'
        for host_name, profile in self.manifest['profiles'].items():
            source = measured_profiles.approved_source_map(self.manifest, host_name)
            compact = (fixture / ('native-x64.tsv' if host_name.endswith('x64') else 'native.tsv')).read_bytes().replace(b'\r\n', b'\n')
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'capture'
                output.mkdir()
                (output / 'source-head.txt').write_bytes(b'1' * 40 + b'\n')
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
                candidates = profile['measurements'] + [m for m in self.manifest['supplemental_measurements'] if m['host'] == host_name]
                for measurement in candidates:
                    (output / 'provenance.txt').write_bytes(measurement['compiler_provenance'].encode())
                    receipt = validate()
                    for field in measured_profiles.MEASUREMENT_FIELDS - {'compiler_provenance'}:
                        self.assertEqual(receipt['measurement_reference'][field], measurement[field])
                    self.assertEqual(receipt['current_source']['source_sha256'], source)
                    self.assertEqual(receipt['current_source']['source_map_sha256'], measured_profiles.source_map_digest(source))
                    self.assertEqual(receipt['measurement_reference']['role'],
                                     'supplemental-reference' if 'host' in measurement else 'historical-reference')
                self.assertEqual(receipt['current_source']['capture_head'], '1' * 40)
                self.assertEqual(receipt['current_source']['bridge']['integration_head'], self.manifest['source_admission']['integration_head'])
                self.assertEqual(receipt['current_source']['verification_manifest_sha256'], measured_profiles.sha((measured_profiles.HERE / 'measured-profiles.json').read_bytes()))
                self.assertEqual(receipt['current_source']['registration_format_admission'], measured_profiles.REGISTRATION_FORMAT)
                self.assertEqual(receipt['current_source']['broadphase_source_admission'],
                    {k: v for k, v in self.manifest['broadphase_source_admission'].items() if k != 'hosts'})
                self.assertEqual(receipt['current_source']['status'], 'reviewed-current-source-expectation-execution-pending')
                self.assertIn('requires fresh four-host gates', receipt['approval'])
                (output.parent / 'source-head.txt').write_bytes(b'2' * 40 + b'\n')
                for valid in [b'1' * 40 + b'\n', b'1' * 40 + b'\r\n']:
                    (output / 'source-head.txt').write_bytes(valid)
                    self.assertEqual(validate()['current_source']['capture_head'], '1' * 40)
                for invalid in [b'', b'1' * 40, b'A' * 40 + b'\n', b'1' * 40 + b'\r\r\n',
                                b'1' * 40 + b'\n\n', b' ' + b'1' * 40 + b'\n', b'1' * 40 + b' \n',
                                b'1' * 40 + b'\n' + b'2' * 40 + b'\n', b'\xff' * 40 + b'\n']:
                    (output / 'source-head.txt').write_bytes(invalid)
                    with self.assertRaisesRegex(ValueError, 'head framing'):
                        validate()
                (output / 'source-head.txt').unlink()
                with self.assertRaises(FileNotFoundError):
                    validate()
                (output / 'source-head.txt').write_bytes(b'1' * 40 + b'\n')
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
