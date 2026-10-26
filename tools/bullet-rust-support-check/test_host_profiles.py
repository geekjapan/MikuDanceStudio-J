import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import host_profiles as profiles


class HostProfiles(unittest.TestCase):
    def test_exact_reviewed_inventory(self):
        manifest, base = profiles.load()
        linux = manifest['profiles']['linux-x64']
        self.assertEqual(len(linux['differences']), 210)
        self.assertEqual(len({item[0] for item in linux['differences']}), 126)
        self.assertEqual(profiles.differences((base / 'native.tsv').read_bytes(),
                                             (base / linux['compact']).read_bytes(), 'support', 1600), linux['differences'])

    def test_reject_bad_schema_rows_and_case_ids(self):
        data = b'0\t' + b'00000000\t' * 8 + b'00000000\n'
        profiles.rows(data, 'support', 1)
        for changed in [data.replace(b'0\t', b'1\t', 1), data.replace(b'00000000', b'NaN', 1),
                        data + data, data.replace(b'00000000\t', b'', 1)]:
            with self.subTest(data=changed), self.assertRaises(ValueError):
                profiles.rows(changed, 'support', 1)

    def test_reject_finite_signed_zero_inf_and_unlisted_nan_changes(self):
        manifest, base = profiles.load()
        original = (base / 'native.tsv').read_bytes()
        for word in [b'3f800000', b'80000000', b'7f800000', b'ffc00000']:
            changed = original.replace(b'00000000', word, 1)
            diff = profiles.differences(original, changed, 'support', 1600)
            self.assertEqual(len(diff), 1)
            self.assertNotEqual(diff, manifest['profiles']['linux-x64']['differences'])
            with tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                shutil.copytree(base, directory / 'fixtures')
                (directory / 'fixtures/native-linux-x64.tsv').write_bytes(changed)
                modified = copy.deepcopy(manifest)
                modified['directory'] = 'fixtures'
                modified['sha256']['native-linux-x64.tsv'] = hashlib.sha256(changed).hexdigest()
                (directory / 'support-profiles.json').write_text(json.dumps(modified))
                with patch.object(profiles, 'ROOT', directory), patch.object(profiles, 'HERE', directory), self.assertRaisesRegex(ValueError, 'inventory'):
                    profiles.load()

    def test_reject_profile_hash_change(self):
        manifest, base = profiles.load()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            shutil.copytree(base, directory / 'fixtures')
            manifest['directory'] = 'fixtures'
            (directory / 'fixtures/native-linux-x64.tsv').write_bytes(b'changed')
            (directory / 'support-profiles.json').write_text(json.dumps(manifest))
            with patch.object(profiles, 'ROOT', directory), patch.object(profiles, 'HERE', directory), self.assertRaisesRegex(ValueError, 'hash'):
                profiles.load()

    def test_msvc_reuses_reviewed_flags_and_static_libraries(self):
        output = Path('/capture')
        src = profiles.ROOT / 'recipes/bullet275/bullet-src/src'
        shim = profiles.ROOT / 'rust/crates/mds-bullet-sys/shim'
        command = ['clang++', '-I', str(shim / 'sse_emu'), '-I', str(src), '-I', str(shim),
                   'oracle.cpp', 'shape.cpp', '-o', '/capture/native.exe']
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            result = SimpleNamespace(stdout=b'', stderr=b'note: native-static-libs: kernel32.lib userenv.lib\n')
            with patch.object(profiles, 'os', SimpleNamespace(name='nt')), patch.object(profiles.subprocess, 'run', return_value=result):
                translated = profiles.native_command(command, output, {})
            for flag in ['/O2', '/fp:precise', '/DWIN32', '/MD', 'kernel32.lib', 'userenv.lib', '/Fe:/capture/native.exe']:
                self.assertIn(flag, translated)
            self.assertFalse(any('sse_emu' in arg for arg in translated))
            self.assertIn('oracle.cpp', translated)
            self.assertIn('shape.cpp', translated)

    def test_capture_requires_same_host_exact_words_and_known_profile(self):
        manifest, base = profiles.load()
        native = (base / 'native.tsv').read_bytes()
        inputs = (base / 'inputs.tsv').read_bytes()
        manifest['full_rows'] = 1600
        manifest['full_inputs_sha256'] = hashlib.sha256(inputs).hexdigest()
        manifest['profiles']['macos-arm64']['full_sha256'] = hashlib.sha256(native).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            for filename, data in [('native.tsv', native), ('observed.tsv', native), ('rust.tsv', native), ('inputs.tsv', inputs)]:
                (output / filename).write_bytes(data)
            with patch.object(profiles, 'load', return_value=(manifest, base)), patch.object(profiles, 'host', return_value='macos-arm64'):
                self.assertEqual(profiles.validate_capture(output), base / 'native.tsv')
                for name in ['native.tsv', 'observed.tsv', 'rust.tsv', 'inputs.tsv']:
                    original = (output / name).read_bytes()
                    (output / name).write_bytes(original.replace(b'00000000', b'80000000', 1))
                    with self.subTest(name=name), self.assertRaises(ValueError):
                        profiles.validate_capture(output)
                    (output / name).write_bytes(original)
            with patch.object(profiles, 'load', return_value=(manifest, base)), patch.object(profiles, 'host', return_value='linux-arm64'), self.assertRaisesRegex(ValueError, 'Unreviewed'):
                profiles.validate_capture(output)
            report = json.loads((output / 'host-profile.json').read_text())
            self.assertFalse(report['profile_known'])
            self.assertTrue(report['full_same_host_rust_equal'])


if __name__ == '__main__':
    unittest.main()
