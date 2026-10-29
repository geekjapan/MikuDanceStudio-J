from contextlib import contextmanager
import io
import itertools
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import warnings
import zipfile

sys.dont_write_bytecode = True
import member_name_lowering as M


class AcquisitionTests(unittest.TestCase):
    def zip_bytes(self, entries=(('fixture.txt', b'inert fixture payload'),)):
        output = io.BytesIO()
        with warnings.catch_warnings(), zipfile.ZipFile(output, 'w') as archive:
            warnings.simplefilter('ignore', UserWarning)
            for name, data in entries:
                archive.writestr(zipfile.ZipInfo(name) if isinstance(name, str) else name, data)
        return output.getvalue()

    @contextmanager
    def fixture(self, raw=None, mutate_metadata=None, mutate_raw=None):
        raw = self.zip_bytes() if raw is None else raw
        pins = {name: (ident, len(raw), M.sha(raw)) for name, (ident, _, _) in M.ARTIFACTS.items()}
        metadata = {name: {'id': ident, 'size_in_bytes': size, 'digest': 'sha256:'+digest,
                         'workflow_run': {'id': 40531027355, 'head_sha': M.BASE}}
                    for name, (ident, size, digest) in pins.items()}
        if mutate_metadata:
            mutate_metadata(metadata['all24'])
        calls, handlers = [], []
        def open_request(request, timeout):
            self.assertEqual(timeout, 120)
            self.assertEqual(request.get_header('Authorization'), 'Bearer unit-test-only')
            self.assertEqual(request.get_header('Accept'), 'application/vnd.github+json')
            self.assertEqual(request.get_header('X-github-api-version'), '2022-11-28')
            url = request.full_url
            calls.append(url)
            for name, (ident, _, _) in pins.items():
                base = 'https://api.github.com/repos/geekjapan/MikuDanceStudio-J/actions/artifacts/'+str(ident)
                if url == base:
                    return io.BytesIO(json.dumps(metadata[name]).encode())
                if url == base+'/zip':
                    return io.BytesIO(mutate_raw(raw) if mutate_raw else raw)
            self.fail('unexpected request '+url)
        class Opener:
            open = staticmethod(open_request)
        def build(handler):
            handlers.append(handler)
            return Opener()
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GH_TOKEN': 'unit-test-only'}, clear=True), \
             patch.object(sys, 'platform', 'linux'), patch.object(M, 'ARTIFACTS', pins), \
             patch.object(urllib.request, 'build_opener', side_effect=build):
            yield Path(directory)/'inputs', calls, handlers, metadata

    def test_original_pins_remain_exact(self):
        self.assertEqual(M.BASE, '7874ace64a61496c3964a3af48ef8eb3f4ef2772')
        self.assertEqual(M.ARTIFACTS, {
            'all24': (12746124666, 171455537, '498e524875a122e886bb67833595dcef3cd919132403041e5b5ac955443d6ac0'),
            'setup': (12745818632, 44689319, '5ed3ac31c42b75eac1f3386142aff65cf58b1afd92096c909db928b59debbfd9'),
            'input': (12746627220, 13927470, '5b54935e36626f0930bbd14e5f943a91e5a52d4307c3030616605ff9a87f37c9'),
        })

    def test_helper_two_and_default_full_three(self):
        for helper_inputs, names in ((True, ('all24', 'setup')), (False, ('all24', 'setup', 'input'))):
            with self.subTest(helper_inputs=helper_inputs), self.fixture() as (root, calls, _, metadata):
                if helper_inputs:
                    M.acquire(root, helper_inputs=True)
                else:
                    M.acquire(root)
                expected = []
                for name in names:
                    base = 'https://api.github.com/repos/geekjapan/MikuDanceStudio-J/actions/artifacts/'+str(M.ARTIFACTS[name][0])
                    expected.extend((base, base+'/zip'))
                    self.assertEqual((root/(name+'.zip')).read_bytes(), self.zip_bytes())
                    self.assertEqual(json.loads((root/(name+'-api.json')).read_bytes()), metadata[name])
                self.assertEqual(calls, expected)
                self.assertEqual({p.name for p in root.iterdir()},
                                 {name+suffix for name in names for suffix in ('.zip', '-api.json')})
                self.assertNotIn('unit-test-only', ''.join(p.name for p in root.iterdir()))
                for path in root.glob('*-api.json'):
                    self.assertNotIn(b'unit-test-only', path.read_bytes())

    def test_each_metadata_binding_rejected_before_download(self):
        for field in ('id', 'size_in_bytes', 'digest', 'run_id', 'head_sha'):
            def mutate(metadata):
                if field == 'run_id':
                    metadata['workflow_run']['id'] += 1
                elif field == 'head_sha':
                    metadata['workflow_run']['head_sha'] = '0'*40
                elif field == 'digest':
                    metadata[field] = 'sha256:'+'0'*64
                else:
                    metadata[field] += 1
            for helper_inputs in (False, True):
                with self.subTest(field=field, helper_inputs=helper_inputs), self.fixture(mutate_metadata=mutate) as (root, calls, _, _):
                    with self.assertRaisesRegex(ValueError, 'fixed API artifact metadata'):
                        M.acquire(root, helper_inputs=helper_inputs)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(list(root.iterdir()), [])

    def test_raw_size_and_hash_rejected_before_write(self):
        for label, mutate in (('size', lambda raw: raw+b'x'),
                              ('hash', lambda raw: bytes([raw[0] ^ 1])+raw[1:])):
            with self.subTest(label=label), self.fixture(mutate_raw=mutate) as (root, calls, _, _):
                with self.assertRaisesRegex(ValueError, 'acquired fixed artifact bytes'):
                    M.acquire(root, helper_inputs=True)
                self.assertEqual(len(calls), 2)
                self.assertEqual(list(root.iterdir()), [])

    def test_malformed_unsafe_duplicate_symlink_and_crc_rejected(self):
        symlink = zipfile.ZipInfo('link')
        symlink.create_system = 3
        symlink.external_attr = 0o120777 << 16
        valid = self.zip_bytes()
        crc_bad = valid.replace(b'inert fixture payload', b'Xnert fixture payload', 1)
        cases = [('malformed', b'not a ZIP', zipfile.BadZipFile, None),
                 ('truncated', valid[:-16], zipfile.BadZipFile, None),
                 ('duplicate', self.zip_bytes((('same', b'a'), ('same', b'b'))), ValueError, 'duplicate ZIP names'),
                 ('symlink', self.zip_bytes(((symlink, b'target'),)), ValueError, 'unsafe ZIP member'),
                 ('crc', crc_bad, ValueError, 'ZIP CRC')]
        for name in ('../escape', '/absolute', 'a/../escape', 'a\\escape', './alias'):
            cases.append((name, self.zip_bytes(((name, b'data'),)), ValueError, 'unsafe ZIP member'))
        for label, raw, error, message in cases:
            with self.subTest(label=label), self.fixture(raw=raw) as (root, calls, _, _):
                with self.assertRaises(error) as caught:
                    M.acquire(root, helper_inputs=True)
                if message:
                    self.assertIn(message, str(caught.exception))
                self.assertEqual(len(calls), 2)
                self.assertEqual((root/'all24.zip').read_bytes(), raw)
                self.assertFalse((root/'setup.zip').exists())

    def test_redirect_removes_authorization(self):
        with self.fixture() as (root, _, handlers, _):
            M.acquire(root, helper_inputs=True)
            for url in ('https://api.github.com/redirect', 'https://storage.example.invalid/archive'):
                request = urllib.request.Request('https://api.github.com/original',
                                                 headers={'Authorization': 'Bearer unit-test-only', 'Accept': 'application/vnd.github+json'})
                request.add_unredirected_header('Authorization', 'Bearer unit-test-only')
                redirected = handlers[0].redirect_request(request, None, 302, 'Found', {}, url)
                self.assertEqual(redirected.full_url, url)
                self.assertFalse(redirected.has_header('Authorization'))
                self.assertEqual(redirected.get_header('Accept'), 'application/vnd.github+json')

    def test_hosted_linux_and_fresh_output_guards(self):
        for actions, platform in (('false', 'linux'), ('true', 'darwin'), ('TRUE', 'linux')):
            with self.subTest(actions=actions, platform=platform), self.fixture() as (root, calls, _, _), \
                 patch.dict(os.environ, {'GITHUB_ACTIONS': actions}), patch.object(sys, 'platform', platform):
                with self.assertRaisesRegex(ValueError, 'hosted-only'):
                    M.acquire(root, helper_inputs=True)
                self.assertFalse(root.exists())
                self.assertEqual(calls, [])
        with self.fixture() as (root, calls, _, _):
            root.mkdir()
            (root/'retained').write_bytes(b'unchanged')
            with self.assertRaisesRegex(ValueError, 'must be fresh'):
                M.acquire(root, helper_inputs=True)
            self.assertEqual((root/'retained').read_bytes(), b'unchanged')
            self.assertEqual(calls, [])

    def test_cli_dispatch_and_operation_exclusivity(self):
        for flag, kwargs in (('--acquire', {}), ('--acquire-helper-inputs', {'helper_inputs': True})):
            with self.subTest(flag=flag), patch.object(sys, 'argv', ['member_name_lowering.py', flag, '/unused']), \
                 patch.object(M, 'acquire') as acquire:
                M.main()
                acquire.assert_called_once_with(Path('/unused'), **kwargs)
        for first, second in itertools.combinations(('--replay', '--run-hosted', '--acquire', '--acquire-helper-inputs'), 2):
            with self.subTest(first=first, second=second), \
                 patch.object(sys, 'argv', ['member_name_lowering.py', first, '/unused', second, '/unused']), \
                 patch.object(M, 'acquire') as acquire, patch.object(M, 'run_hosted') as hosted, patch.object(M, 'replay') as replay:
                with self.assertRaisesRegex(ValueError, 'exclusive operation'):
                    M.main()
                acquire.assert_not_called()
                hosted.assert_not_called()
                replay.assert_not_called()
        with patch.object(sys, 'argv', ['member_name_lowering.py']), self.assertRaisesRegex(ValueError, 'all three fixed artifact paths required'):
            M.main()


if __name__ == '__main__':
    unittest.main()
