import unittest
from evidence import admit_capture


class AdmissionBoundaryTests(unittest.TestCase):
    def test_no_source_or_synthetic_input_is_admitted(self):
        for input in (None, {}, {'status': 'PASS'}, b'legal-looking-source'):
            with self.assertRaisesRegex(ValueError, 'context'):
                admit_capture(input)


class ByteAuthorityTests(unittest.TestCase):
    def test_exact_identity_types_and_deep_immutable_members(self):
        from evidence import ByteIdentity, ExpectedEvidence, digest, freeze
        for size in (True, False, 1.0, -1):
            with self.assertRaises(ValueError):
                ByteIdentity(size, digest(b'x'))
        members = {'tiny.json': ByteIdentity.of(b'{}')}
        expected = ExpectedEvidence(members, [])
        members.clear()
        self.assertEqual(expected.members['tiny.json'].size, 2)
        with self.assertRaises(TypeError):
            expected.members['other'] = ByteIdentity.of(b'')
        original = {'argv': ['one'], 'nested': {'items': [1]}}
        frozen = freeze(original)
        original['argv'].append('two')
        self.assertEqual(frozen['argv'], ('one',))
        with self.assertRaises(TypeError):
            frozen['nested']['items'][0] = 2

    def test_cached_same_path_never_reopens_after_authentication(self):
        import io
        import stat
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch, Mock
        from evidence import ByteIdentity, Capture, ExpectedEvidence, json_value
        first, replacement = b'{"value":1}', b'{"value":2}'
        expected = ExpectedEvidence({'tiny.json': ByteIdentity.of(first)}, [])
        info = SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_nlink=1, st_size=len(first),
                               st_dev=1, st_ino=1, st_mtime_ns=1, st_ctime_ns=1)
        directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755)
        def status(path):
            return directory if str(path) == '/inert-cache' else info
        streams = [io.BytesIO(first), io.BytesIO(replacement)]
        for stream in streams:
            stream.fileno = lambda: 123
        opened = Mock(side_effect=streams)
        with patch('evidence.os.walk', return_value=[('/inert-cache', [], ['tiny.json'])]), \
             patch.object(Path, 'lstat', status), patch.object(Path, 'open', opened), \
             patch('evidence.os.fstat', return_value=info):
            capture = Capture.open('/inert-cache', expected=expected)
            self.assertEqual(json_value(capture['tiny.json']), {'value': 1})
            self.assertIs(capture['tiny.json'], capture['tiny.json'])
            self.assertEqual(capture['tiny.json'], first)
            self.assertEqual(opened.call_count, 1)
        with self.assertRaises(TypeError):
            capture.content['tiny.json'] = replacement

    def test_corrupted_length_and_hash_fail_before_json_parser(self):
        from unittest.mock import patch
        from evidence import ByteIdentity, Capture, ExpectedEvidence
        expected = ExpectedEvidence({'tiny.json': ByteIdentity.of(b'{"a":1}')}, [])
        for raw, reason in [(b'{"a":2}', 'SHA256'), (b'{}', 'length')]:
            with patch('evidence.json_value') as parser:
                with self.assertRaisesRegex(ValueError, reason):
                    Capture({'tiny.json': raw}, expected)
                parser.assert_not_called()

    def test_missing_authority_and_declared_json_size_fail_before_open(self):
        from pathlib import Path
        from unittest.mock import patch
        from evidence import ByteIdentity, Capture, ExpectedEvidence, MAX_JSON, digest, read_authority
        with self.assertRaises(TypeError):
            Capture.open('/inert-cache')
        with self.assertRaisesRegex(ValueError, 'mandatory'):
            Capture.open('/inert-cache', expected=None)
        with patch.object(Path, 'open') as opened, patch('evidence.decode_json') as parser:
            with self.assertRaisesRegex(ValueError, 'JSON byte bounds'):
                ExpectedEvidence({'tiny.json': ByteIdentity(MAX_JSON + 1, digest(b''))}, [])
            with self.assertRaisesRegex(ValueError, 'JSON byte bounds'):
                read_authority(Path('/never-opened'), size=MAX_JSON + 1, sha256=digest(b''))
            opened.assert_not_called()
            parser.assert_not_called()

    def test_declared_length_refusal_precedes_member_open(self):
        import stat
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from evidence import ByteIdentity, Capture, ExpectedEvidence
        expected = ExpectedEvidence({'tiny.json': ByteIdentity.of(b'{}')}, [])
        def status(path):
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755) if str(path) == '/inert-cache' else \
                   SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_nlink=1, st_size=1)
        with patch('evidence.os.walk', return_value=[('/inert-cache', [], ['tiny.json'])]), \
             patch.object(Path, 'lstat', status), patch.object(Path, 'open') as opened:
            with self.assertRaisesRegex(ValueError, 'member size'):
                Capture.open('/inert-cache', expected=expected)
            opened.assert_not_called()

    def test_closed_inventory_kinds_and_links_precede_member_open(self):
        import stat
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from evidence import ByteIdentity, Capture, ExpectedEvidence
        expected = ExpectedEvidence({'tiny.json': ByteIdentity.of(b'{}')}, [])
        for mode, links in [(stat.S_IFLNK | 0o777, 1), (stat.S_IFREG | 0o644, 2),
                            (stat.S_IFREG | 0o4644, 1)]:
            def status(path):
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755) if str(path) == '/inert-cache' else \
                       SimpleNamespace(st_mode=mode, st_nlink=links, st_size=2)
            with patch('evidence.os.walk', return_value=[('/inert-cache', [], ['tiny.json'])]), \
                 patch.object(Path, 'lstat', status), patch.object(Path, 'open') as opened:
                with self.assertRaisesRegex(ValueError, 'member size'):
                    Capture.open('/inert-cache', expected=expected)
                opened.assert_not_called()
        with patch('evidence.os.walk', return_value=[('/inert-cache', [], ['other.json'])]), \
             patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=stat.S_IFDIR | 0o755)), \
             patch.object(Path, 'open') as opened:
            with self.assertRaisesRegex(ValueError, 'expected capture member'):
                Capture.open('/inert-cache', expected=expected)
            opened.assert_not_called()

    def test_json_duplicate_nonfinite_overflow_and_boolean_receipts(self):
        from evidence import json_value
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1e999}', b'{"pid":true}'):
            with self.assertRaises(ValueError):
                json_value(raw)
        self.assertEqual(json_value(b'{"pid":1,"normal_exit":true}'), {'pid':1, 'normal_exit':True})

    def test_detached_receipt_is_authenticated_before_decode(self):
        import io
        import stat
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from evidence import ByteIdentity, ExpectedEvidence, digest, read_authority
        expected = ExpectedEvidence({'tiny.json': ByteIdentity.of(b'{}')}, [])
        raw = expected.receipt()
        info = SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_nlink=1, st_size=len(raw),
                               st_dev=1, st_ino=1, st_mtime_ns=1, st_ctime_ns=1)
        stream = io.BytesIO(raw)
        stream.fileno = lambda: 123
        with patch.object(Path, 'lstat', return_value=info), patch.object(Path, 'open', return_value=stream), \
             patch('evidence.os.fstat', return_value=info):
            restored = read_authority(Path('/inert-receipt'), size=len(raw), sha256=digest(raw))
            self.assertEqual(restored, expected)
        stream = io.BytesIO(raw.replace(b'"schema": 2', b'"schema": 3'))
        stream.fileno = lambda: 123
        with patch.object(Path, 'lstat', return_value=info), patch.object(Path, 'open', return_value=stream), \
             patch('evidence.os.fstat', return_value=info), patch('evidence.json_value') as parser:
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                read_authority(Path('/inert-receipt'), size=len(raw), sha256=digest(raw))
            parser.assert_not_called()


class CommandRecordFramingTests(unittest.TestCase):
    def fixture(self):
        from evidence import ByteIdentity, Capture, ExpectedEvidence, command_index, command_path, digest, encode_json
        records = [{'label': label, 'argv': ['inert', label], 'pid': None,
                    'generated_before': {'generated/a.rs': digest(b'a'), 'mutants/x/b.rs': digest(b'b')},
                    'generated_end': {'generated/a.rs': digest(b'a'), 'mutants/x/b.rs': digest(b'b')},
                    'waited': False, 'streams_closed': False, 'outputs': {}, 'inputs_before': {}}
                   for label in ['first', 'second']]
        content, refs = {}, []
        for ordinal, record in enumerate(records, 1):
            raw = encode_json(record)
            path = command_path(ordinal)
            content[path] = raw
            refs.append({'ordinal': ordinal, 'label': record['label'], 'path': path,
                         'size': len(raw), 'sha256': digest(raw)})
        content['commands.json'] = encode_json(command_index(refs))
        expected = ExpectedEvidence({name: ByteIdentity.of(raw) for name, raw in content.items()}, refs)
        return records, content, expected

    def test_inert_record_roundtrip_and_immutable_commitments(self):
        import io
        import stat
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from evidence import Capture, command_records, digest, read_authority
        records, content, expected = self.fixture()
        raw = expected.receipt()
        info = SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_nlink=1, st_size=len(raw),
                               st_dev=1, st_ino=1, st_mtime_ns=1, st_ctime_ns=1)
        stream = io.BytesIO(raw)
        stream.fileno = lambda: 123
        with patch.object(Path, 'lstat', return_value=info), patch.object(Path, 'open', return_value=stream), \
             patch('evidence.os.fstat', return_value=info):
            restored = read_authority(Path('/inert-record-authority'), size=len(raw), sha256=digest(raw))
        capture = Capture(content, restored)
        self.assertEqual(command_records(capture.__getitem__, restored), records)
        self.assertIsNone(records[0]['pid'])
        with self.assertRaises(TypeError):
            restored.commands[0]['size'] = 0

    def test_held_authority_rejects_record_and_index_corruptions(self):
        import copy
        from unittest.mock import patch
        from evidence import Capture, command_index, command_records, digest, encode_json, json_value, thaw
        _, content, expected = self.fixture()
        for candidate in ({name: raw for name, raw in content.items() if name != expected.commands[0]['path']},
                          {**content, 'command-records/000003.json': b'{}'},
                          {**content, expected.commands[0]['path']: b'{}'}):
            with self.assertRaises(ValueError):
                Capture(candidate, expected)
        refs = thaw(expected.commands)
        variants = [list(reversed(refs)), [refs[0], refs[0]], refs[:1], [*refs, refs[-1]]]
        for field, value in [('size', refs[0]['size'] + 1), ('sha256', '0'*64),
                             ('ordinal', True), ('ordinal', 1.0), ('path', 'command-records/000002.json')]:
            changed = copy.deepcopy(refs)
            changed[0][field] = value
            variants.append(changed)
        for changed in variants:
            candidate = {**content, 'commands.json': encode_json(command_index(changed))}
            with patch('evidence.json_value') as parser:
                with self.assertRaises(ValueError):
                    Capture(candidate, expected)
                parser.assert_not_called()
            with self.assertRaises(ValueError):
                command_records(candidate.__getitem__, expected)
        changed = copy.deepcopy(refs)
        changed[0]['label'] = 'stale'
        with self.assertRaisesRegex(ValueError, 'external closed command authority'):
            command_records({**content, 'commands.json': encode_json(command_index(changed))}.__getitem__, expected)
        path = refs[0]['path']
        record = json_value(content[path])
        record['generated_end']['generated/a.rs'] = '0'*64
        changed_raw = encode_json(record)
        changed = copy.deepcopy(refs)
        changed[0].update(size=len(changed_raw), sha256=digest(changed_raw))
        candidate = {**content, path: changed_raw, 'commands.json': encode_json(command_index(changed))}
        with self.assertRaises(ValueError):
            command_records(candidate.__getitem__, expected)


class NativeEvidenceFramingTests(unittest.TestCase):
    def test_exact_archive_payload_and_compiled_source_binding(self):
        from evidence import digest, verify_archive
        source = 'recipes/bullet275/bullet-src/src/LinearMath/tiny.cpp'
        payload = b'opaque-compiled-object'
        header = (b'tiny.o/         ' + b'0           ' + b'0     ' + b'0     ' + b'100644  ' +
                  str(len(payload)).encode().ljust(10) + b'`\n')
        raw = b'!<arch>\n' + header + payload + (b'\n' if len(payload) % 2 else b'')
        bindings = [{'source': source, 'source_sha256': digest(b'int tiny;'),
                     'object': 'tiny.o', 'object_sha256': digest(payload)}]
        archive = verify_archive(raw, ['tiny.o'], 'Linux', bindings, {'tiny.o': payload}, {source: b'int tiny;'})
        self.assertEqual(archive.payloads, {'tiny.o': payload})
        for changed in (raw[:-1], raw + b'bad', raw.replace(payload, b'x' * len(payload))):
            with self.assertRaises(ValueError):
                verify_archive(changed, ['tiny.o'], 'Linux', bindings, {'tiny.o': payload}, {source: b'int tiny;'})

    def test_include_occurrence_duplicates_and_spelling_are_preserved(self):
        from evidence import digest, include_occurrences, include_projection
        raw = b'. /inert/one.h\n.. /inert/two.h\n. /inert/one.h\n'
        occurrences = include_occurrences(b'', raw, 'Linux')
        bindings = [{**item, 'target': item['raw'], 'sha256': digest(item['raw'].encode())} for item in occurrences]
        manifest, aliases = include_projection(bindings, occurrences, 'Linux')
        self.assertEqual(len(occurrences), 3)
        self.assertEqual(len(manifest), 2)
        self.assertEqual(len(aliases), 2)
        with self.assertRaises(ValueError):
            include_projection(bindings[:-1], occurrences, 'Linux')
        changed = [dict(item) for item in bindings]
        changed[-1]['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            include_projection(changed, occurrences, 'Linux')


class NativeLifetimeFramingTests(unittest.TestCase):
    def test_inert_allocation_and_reverse_physical_lifetime_framing(self):
        from evidence import validate_native_lifetimes
        inputs = 'H inert genuine\nC\nJ 0 1 -2147483648 1\nX\n'
        raw = (b'ALLOC 0 1 1 4096 16 16\nBODY_REGISTER 0 0 101\nBODY_REGISTER 1 1 202\n'
               b'JOINT_CREATE 2 0 303 -2147483648\nPHYSICAL 3 joint 303 -1\n'
               b'PHYSICAL 3 body 202 1\nPHYSICAL 3 body 101 0\nALLOC 3 2 0 4096 0 0\n')
        self.assertEqual(validate_native_lifetimes(raw, inputs, observed=True)['allocation_events'], 2)
        for changed in (raw.replace(b'ALLOC 3 2', b'ALLOC 3 3'),
                        raw.replace(b'body 202 1', b'body 202 0'),
                        raw.replace(b'303 -2147483648', b'303 0'),
                        raw[:raw.rindex(b'ALLOC')]):
            with self.assertRaises(ValueError):
                validate_native_lifetimes(changed, inputs, observed=True)


class CommandRecipeTests(unittest.TestCase):
    def test_inert_command_recipe_preserves_order_roles_and_generation(self):
        from evidence import command_schedule
        from hooks import MUTANTS
        for system, root, out, exe in [('Linux','/source','/capture','/tool'),
                                      ('Darwin','/source','/capture','/tool'),
                                      ('Windows','C:/source','D:/capture','C:/tool.exe')]:
            context = {'schema':1,'system':system,'root':root,'out':out,
                       'tools':{name:exe for name in ['python','git','rustup','rustc','rust_linker','compiler','archiver','native_linker']}}
            sources = ['recipes/bullet275/bullet-src/src/BulletCollision/BroadphaseCollision/btDbvt.cpp']
            recipe = command_schedule(context,sources,[])
            labels = [entry.label for entry in recipe]
            self.assertEqual(len(labels),len(set(labels)))
            self.assertEqual(labels[:2],['git-head','git-status'])
            self.assertLess(labels.index('compile-000-discovery'),labels.index('compile-000'))
            self.assertLess(labels.index('native-run'),labels.index('observed-run'))
            self.assertEqual(sum(entry.label.startswith('mutant-run-') for entry in recipe),len(MUTANTS))
            for name in MUTANTS:
                baseline = next(entry for entry in recipe if entry.label == 'baseline-build-'+name)
                mutant = next(entry for entry in recipe if entry.label == 'mutant-build-'+name)
                self.assertEqual(baseline.generation,'baseline-'+name)
                self.assertEqual(mutant.generation,'mutant-'+name)
                self.assertEqual(len(mutant.outputs),2 if system == 'Windows' else 1)
                if system == 'Windows':
                    self.assertTrue(mutant.outputs[-1].endswith('.pdb'))
            self.assertTrue(next(entry for entry in recipe if entry.label == 'native-run').corpus)
            self.assertTrue(next(entry for entry in recipe if entry.label == 'observed-consumer-build').compile)
            self.assertTrue(all(len(entry.outputs)==1 for entry in recipe if entry.compile))


if __name__ == '__main__':
    unittest.main()
