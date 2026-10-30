import unittest
from evidence import admit_capture


class AdmissionBoundaryTests(unittest.TestCase):
    def test_public_context_routes_both_explicit_boolean_modes(self):
        from unittest.mock import patch
        context = dict(authority=object(), expected_head='a' * 40, canonical_sources={'one': b'x'},
                       inputs='X\n', cases=[], expected_host={('Linux', 'x86_64')})
        for dynamics in (False, True):
            with patch('evidence._admit_capture', return_value='admitted') as admission:
                self.assertEqual(admit_capture('capture', **context, dynamics=dynamics), 'admitted')
                admission.assert_called_once_with('capture', **context, dynamics=dynamics)
        for changed in (context, {**context, 'dynamics': True, 'extra': 1},
                        *({**context, 'dynamics': value} for value in (0, 1, None, 'false', [], {}))):
            with self.subTest(context=changed), patch('evidence._admit_capture') as admission:
                with self.assertRaises(ValueError):
                    admit_capture('capture', **changed)
                admission.assert_not_called()

    def test_no_source_or_synthetic_input_is_admitted(self):
        for input in (None, {}, {'status': 'PASS'}, b'legal-looking-source'):
            with self.assertRaisesRegex(ValueError, 'context'):
                admit_capture(input)


class ByteAuthorityTests(unittest.TestCase):
    def test_casefold_collision_rejects_equal_and_different_bytes(self):
        from evidence import ByteIdentity, ExpectedEvidence
        for other in (b'header', b'different'):
            with self.assertRaisesRegex(ValueError, 'case collision'):
                ExpectedEvidence({'source/Header.h': ByteIdentity.of(b'header'),
                                  'source/header.h': ByteIdentity.of(other)}, [])

    def test_capture_references_require_exact_member_and_input_role(self):
        import ast
        from pathlib import Path, PureWindowsPath, PurePosixPath
        from evidence import digest, require, safe_name, sha_identity
        tree = ast.parse((Path(__file__).resolve().parent / 'evidence.py').read_text())
        admission = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                         and node.name == '_admit_capture')
        helpers = [node for node in admission.body if isinstance(node, ast.FunctionDef)
                   and node.name in {'raw', 'artifact'}]
        roles = next(node for node in ast.walk(admission) if isinstance(node, ast.Expr)
                     and isinstance(node.value, ast.Call) and node.value.args
                     and isinstance(node.value.args[-1], ast.Constant)
                     and node.value.args[-1].value == 'exact direct input roles and preservation')
        for system in ('Linux', 'Darwin', 'Windows'):
            path = PureWindowsPath if system == 'Windows' else PurePosixPath
            root = path('C:/source' if system == 'Windows' else '/source')
            out = path('C:/capture' if system == 'Windows' else '/capture')
            content = {'source/Header.h': b'header', 'generated/Header.h': b'header'}
            namespace = dict(names=set(content), capture=content, used=set(),
                             folded={name.casefold(): name for name in content},
                             require=require, safe_name=safe_name, sha_identity=sha_identity,
                             digest=digest, path=path, root=root, out=out)
            exec(compile(ast.Module(body=helpers, type_ignores=[]), 'exact-member-helpers', 'exec'), namespace)
            artifact = namespace['artifact']
            for base in (root, out / 'generated'):
                self.assertEqual(artifact(str(base / 'Header.h'), digest(b'header')), b'header')
                with self.assertRaisesRegex(ValueError, 'required capture member'):
                    artifact(str(base / 'header.h'), digest(b'header'))
                with self.assertRaisesRegex(ValueError, 'input identity'):
                    artifact(str(base / 'Header.h'), digest(b'different'))
            declared = [str(root / 'Header.h')]
            for name in (declared[0], str(out / 'generated/Header.h')):
                identities = {name: digest(b'header')}
                namespace.update(declared=declared, command={'inputs_before': identities, 'inputs_end': identities})
                code = compile(ast.Module(body=[roles], type_ignores=[]), 'exact-input-roles', 'exec')
                if name == declared[0]:
                    exec(code, namespace)
                else:
                    with self.assertRaisesRegex(ValueError, 'exact direct input roles'):
                        exec(code, namespace)

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
            return directory if path == Path('/inert-cache') else info
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
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755) if path == Path('/inert-cache') else \
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
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755) if path == Path('/inert-cache') else \
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
        records = [{'label': label, 'argv': ['inert', label], 'cwd': '/inert', 'pid': None,
                    'executable': {'path': '/inert/tool', 'target': '/inert/tool', 'sha256': digest(b'tool')},
                    'executable_end': {'path': '/inert/tool', 'target': '/inert/tool', 'sha256': digest(b'tool')},
                    'stdin_sha256': None, 'start_utc': None, 'end_utc': None, 'seconds': 0.0,
                    'stdout_sha256': digest(b''), 'stderr_sha256': digest(b''), 'returncode': None,
                    'generated_before': {'generated/a.rs': digest(b'a'), 'mutants/x/b.rs': digest(b'b')},
                    'generated_end': {'generated/a.rs': digest(b'a'), 'mutants/x/b.rs': digest(b'b')},
                    'waited': False, 'streams_closed': False, 'outputs': {}, 'inputs_before': {}, 'inputs_end': {}}
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
    def test_windows_include_projection_preserves_physical_case_and_raw_aliases(self):
        from evidence import digest, include_occurrences, include_projection
        physical = r'C:\capture\generated\BulletCollision\Header.h'
        alias = r'c:\capture\generated\bulletcollision\header.h'
        raw = ('Note: including file: ' + alias + '\nNote: including file: ' + physical + '\n').encode()
        occurrences = include_occurrences(raw, b'', 'Windows')
        bindings = [{**item, 'target': physical, 'sha256': digest(b'header')} for item in occurrences]
        manifest, aliases = include_projection(bindings, occurrences, 'Windows')
        self.assertEqual(manifest, {physical: digest(b'header')})
        self.assertEqual(aliases, {alias: (physical, digest(b'header')), physical: (physical, digest(b'header'))})
        for target in (r'C:\capture\..\Header.h', 'C:/capture/Header.h', r'capture\Header.h'):
            with self.assertRaises(ValueError):
                include_projection([{**bindings[0], 'target': target}], occurrences[:1], 'Windows')
        changed = [{**bindings[0], 'target': physical.lower()}, bindings[1]]
        self.assertEqual(len(include_projection(changed, occurrences, 'Windows')[0]), 2)

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
    def test_zero_payload_allocations_keep_ownership_and_alignment_guards(self):
        from evidence import validate_native_lifetimes
        inputs = 'H inert genuine\nX\nH inert genuine\nX\n'
        allocation = b'ALLOC 0 1 1 4096 0 16\n'
        release = b'ALLOC 1 2 0 4096 0 0\n'
        raw = allocation + release
        self.assertEqual(validate_native_lifetimes(raw, inputs, observed=True),
                         {'allocation_events': 2, 'physical_closure': True})
        reused = raw + b'ALLOC 2 3 1 4096 0 16\nALLOC 3 4 0 4096 0 0\n'
        self.assertEqual(validate_native_lifetimes(reused, inputs, observed=True)['allocation_events'], 4)
        for reason, changed in [
                ('missing free', allocation),
                ('duplicate live pointer', allocation + b'ALLOC 0 2 1 4096 0 16\n' + release),
                ('unknown free', raw.replace(b'0 4096 0 0', b'0 8192 0 0')),
                ('double free', raw + b'ALLOC 1 3 0 4096 0 0\n'),
                ('null pointer', raw.replace(b'4096', b'0')),
                ('zero alignment', raw.replace(b'0 16\n', b'0 0\n')),
                ('non-power-of-two alignment', raw.replace(b'0 16\n', b'0 3\n')),
                ('misaligned pointer', raw.replace(b'4096', b'4097')),
                ('negative payload', raw.replace(b'0 16\n', b'-1 16\n')),
                ('nonconsecutive sequence', raw.replace(b'ALLOC 1 2', b'ALLOC 1 3')),
                ('unclosed world', allocation + b'ALLOC 2 2 0 4096 0 0\n'),
                ('sequence reset', raw + b'ALLOC 2 1 1 4096 0 16\nALLOC 3 2 0 4096 0 0\n')]:
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                validate_native_lifetimes(changed, inputs, observed=True)

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
    def test_mmd_allocator_roles_refuse_ordinary_callbacks_and_wrong_address_order(self):
        from evidence import validate_native_lifetimes
        inputs = 'H empty mixed-explicit-operations\nX\n'
        ordinary = b'ROLE 0 START ordinary mmd-raw-request\nBODY_REGISTER 0 0 128\nROLE 1 END 0\n'
        summary = validate_native_lifetimes(ordinary, inputs, observed=False, role='ordinary')
        self.assertEqual(summary['domain'], 'mmd-raw-request')
        self.assertEqual(summary['callback_events'], 0)
        self.assertIs(summary['physical_closure'], False)
        custom = (b'ROLE 0 START ascending mmd-raw-request\nROLE 0 1 A 128 23\n'
                  b'ROLE 0 2 A 160 31\nBODY_REGISTER 0 0 128\n'
                  b'ROLE 1 3 F 160 0\nROLE 1 4 F 128 0\nROLE 1 END 0\n')
        self.assertEqual(validate_native_lifetimes(custom, inputs, observed=False, role='ascending')['callback_events'], 4)
        for changed, role in [(custom.replace(b'ascending', b'ordinary'), 'ordinary'),
                              (custom.replace(b'ascending', b'descending'), 'descending'),
                              (custom.replace(b'ROLE 1 4 F 128 0\n', b''), 'ascending')]:
            with self.assertRaises(ValueError):
                validate_native_lifetimes(changed, inputs, observed=False, role=role)

    def test_observed_ordinary_summary_roundtrips_admission_data(self):
        import ast
        import textwrap
        from pathlib import Path
        from evidence import encode_json, json_value, validate_native_lifetimes
        inputs = 'H empty mixed-explicit-operations\nX\n'
        raw = (b'ROLE 0 START ordinary mmd-raw-request\nALLOC 0 1 1 144 0 16\n'
               b'BODY_REGISTER 0 0 128\nPHYSICAL 1 body 128 0\nALLOC 1 2 0 144 0 0\nROLE 1 END 0\n')
        summary = validate_native_lifetimes(raw, inputs, observed=True, role='ordinary')
        self.assertEqual(summary, dict(allocation_events=2, physical_closure=True, role='ordinary',
                                     domain='mmd-raw-request', callback_events=0, raw_callback_absence=True))
        source = (Path(__file__).resolve().parent / 'evidence.py').read_text()
        start = source.index('    def data(name):', source.index('def _admit_capture('))
        data_source = textwrap.dedent(source[start:source.index('    manifest = data(', start)])
        content = {'observed-lifetime-summary.json': encode_json(summary)}
        namespace = dict(raw=content.__getitem__, json_value=json_value)
        exec(compile(ast.parse(data_source), 'admission-data', 'exec'), namespace)
        self.assertEqual(namespace['data']('observed-lifetime-summary.json'), summary)
        for field in ('allocation_events', 'callback_events'):
            for value in (False, True):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    json_value(encode_json({**summary, field: value}))
        for value in (0, 1, None, 'true', [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                json_value(encode_json({**summary, 'raw_callback_absence': value}))

    def test_raw_roles_preserve_separate_bullet_payload_chronology(self):
        from evidence import encode_json, json_value, validate_native_lifetimes
        inputs = 'H empty mixed-explicit-operations\nX\n'
        for role, bases in [('ascending', (128, 160)), ('descending', (160, 128)),
                            ('alternating', (128, 1024, 160, 992))]:
            lines = [f'ROLE 0 START {role} mmd-raw-request']
            for index, base in enumerate(bases):
                lines += [f'ROLE 0 {index + 1} A {base} 31', f'ALLOC 0 {index + 1} 1 {base + 16} 8 16']
            for index, base in enumerate(reversed(bases), len(bases) + 1):
                lines += [f'ALLOC 1 {index} 0 {base + 16} 0 0', f'ROLE 1 {index} F {base} 0']
            lines += ['ROLE 1 END 0']
            raw = ('\n'.join(lines) + '\n').encode()
            summary = validate_native_lifetimes(raw, inputs, observed=True, role=role)
            self.assertEqual(summary['callback_events'], 2 * len(bases))
            self.assertIs(summary['raw_callback_absence'], False)
            self.assertEqual(json_value(encode_json(summary)), summary)
            first = bases[0]
            for changed in (raw.replace(b' 31\n', b' 30\n', 1),
                            raw.replace(f'1 {first + 16} 8 16'.encode(), f'1 {first + 32} 8 16'.encode(), 1),
                            raw.replace(f'F {first} 0'.encode(), f'F {first + 1} 0'.encode(), 1),
                            raw.replace(f'ROLE 0 1 A {first} 31\nALLOC 0 1 1 {first + 16} 8 16'.encode(),
                                        f'ALLOC 0 1 1 {first + 16} 8 16\nROLE 0 1 A {first} 31'.encode()),
                            raw.replace(b'mmd-raw-request', b'mmd-aligned-request')):
                with self.subTest(role=role, changed=changed), self.assertRaises(ValueError):
                    validate_native_lifetimes(changed, inputs, observed=True, role=role)

    def test_dynamics_recipe_has_distinct_mode_all_allocator_roles_and_pdb_outputs(self):
        from evidence import command_schedule
        from hooks import DYNAMICS_MUTANTS
        for system, root, out, exe in [('Linux', '/source', '/capture', '/tool'),
                                      ('Windows', 'C:/source', 'D:/capture', 'C:/tool.exe')]:
            context = {'schema':1, 'system':system, 'root':root, 'out':out,
                       'tools':{name:exe for name in ['python','git','rustup','rustc','rust_linker','compiler','archiver','native_linker']}}
            source = 'recipes/bullet275/bullet-src/src/BulletCollision/BroadphaseCollision/btDbvt.cpp'
            recipe = command_schedule(context, [source], [], dynamics=True)
            commands = {entry.label:entry for entry in recipe}
            for consumer in ('native', 'observed'):
                for role in ('ordinary', 'ascending', 'descending', 'alternating'):
                    label = consumer + '-run' + ('-' + role if role != 'ordinary' else '')
                    self.assertEqual(commands[label].argv[-1], role)
                    self.assertTrue(commands[label].corpus)
            self.assertEqual(sum(entry.label.startswith('mutant-run-') for entry in recipe), len(DYNAMICS_MUTANTS))
            self.assertIn('mmd_dynamics', commands['rust-observed-build'].argv)
            self.assertIn('mmd_dynamics_', commands['dedicated-run'].argv)
            self.assertEqual(len(commands['rust-observed-build'].outputs), 2 if system == 'Windows' else 1)
            if system == 'Windows':
                self.assertTrue(commands['rust-observed-build'].outputs[-1].endswith('.pdb'))
            flag = '/DDW_DYNAMICS=1' if system == 'Windows' else '-DDW_DYNAMICS=1'
            self.assertIn(flag, commands['native-consumer-build'].argv)
            self.assertIn('observed-object-4', commands)

    def test_inert_command_recipe_preserves_order_roles_and_generation(self):
        from evidence import command_schedule
        from hooks import MUTANTS
        from pathlib import PureWindowsPath, PurePosixPath
        for system, root, out, exe in [('Linux','/source','/capture','/tool'),
                                      ('Darwin','/source','/capture','/tool'),
                                      ('Windows','C:/source','D:/capture','C:/tool.exe')]:
            context = {'schema':1,'system':system,'root':root,'out':out,
                       'tools':{name:exe for name in ['python','git','rustup','rustc','rust_linker','compiler','archiver','native_linker']}}
            sources = ['recipes/bullet275/bullet-src/src/BulletCollision/BroadphaseCollision/' + stem + '.cpp'
                       for stem in ['btDbvt', 'btDbvtBroadphase']]
            recipe = command_schedule(context,sources,[])
            labels = [entry.label for entry in recipe]
            self.assertEqual(len(labels),len(set(labels)))
            for label in labels:
                self.assertRegex(label, r'^[a-z0-9-]+$')
            for source, label in zip(sources, ['expanded-btdbvt', 'expanded-btdbvtbroadphase']):
                expanded = next(entry for entry in recipe if entry.label == label)
                path = PureWindowsPath if system == 'Windows' else PurePosixPath
                self.assertEqual(expanded.inputs, (str(path(root) / source),))
                self.assertEqual(expanded.argv[-1], expanded.inputs[0])
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

    def test_expanded_policy_streams_keep_independent_semantic_binding(self):
        import ast
        from pathlib import Path
        tree = ast.parse((Path(__file__).resolve().parent / 'evidence.py').read_text())
        block = next(node for node in ast.walk(tree) if isinstance(node, ast.For)
                     and isinstance(node.target, ast.Name) and node.target.id == 'stem'
                     and ast.literal_eval(node.iter) == ['btDbvt', 'btDbvtBroadphase'])
        code = compile(ast.Module(body=[block], type_ignores=[]), 'expanded-admission', 'exec')
        for win in [False, True]:
            policies = {'policy-btDbvt.json': {'policy': 'mmd-win64-sse' if win else 'generic-reference', 'source': 'tree'},
                        'policy-btDbvtBroadphase.json': {'policy': 'mmd-win64-sse' if win else 'generic-reference', 'source': 'broadphase'}}
            streams = {'expanded-btdbvt.stdout': b'tree', 'expanded-btdbvtbroadphase.stdout': b'broadphase'}
            def policy(raw):
                return {'policy': 'mmd-win64-sse' if win else 'generic-reference', 'source': raw}
            def require(value, message):
                if not value:
                    raise ValueError(message)
            bindings = dict(win=win, policy=policy, require=require, data=policies.__getitem__, raw=streams.__getitem__)
            exec(code, bindings)
            streams['expanded-btdbvt.stdout'], streams['expanded-btdbvtbroadphase.stdout'] = b'broadphase', b'tree'
            with self.assertRaisesRegex(ValueError, 'actual compiled native archive policy'):
                exec(code, bindings)


if __name__ == '__main__':
    unittest.main()
