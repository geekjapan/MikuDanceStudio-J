import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bullet-rust-support-check'))
import host_profiles as profiles


class GjkProfiles(unittest.TestCase):
    def test_exact_compact_and_raw_inventory(self):
        manifest, base = profiles.load('gjk-epa')
        profile = manifest['profiles']['linux-x64']
        self.assertEqual(len(profile['differences']), 864)
        self.assertEqual(len({d[0] for d in profile['differences']}), 55)
        self.assertEqual(len(profile['raw_differences']), 12)
        self.assertEqual({d[0] for d in profile['raw_differences']}, {6802, 6805})
        profiles.rows((base / profile['compact']).read_bytes(), 'gjk-epa', 1801)
        profiles.rows((base / profile['raw']).read_bytes(), 'gjk-epa', 9, 6801)

    def test_reject_status_schema_row_and_case_count_changes(self):
        manifest, base = profiles.load('gjk-epa')
        line = (base / 'native.tsv').read_bytes().splitlines()[0]
        words = line.split(b'\t')
        changes = [b'\t'.join(words[:1] + [b'2'] + words[2:]), b'\t'.join(words[:2] + [b'4'] + words[3:]),
                   b'\t'.join(words[:-1]), b'\t'.join([b'1'] + words[1:]), line + b'\n' + line, b'0\t1']
        for changed in changes:
            with self.subTest(data=changed), self.assertRaises(ValueError):
                profiles.rows(changed, 'gjk-epa', 1)

    def test_reject_unlisted_words_and_hash_changes_in_both_profiles(self):
        manifest, base = profiles.load('gjk-epa')
        for filename in ['native-linux-x64.tsv', 'raw-native-linux-x64.tsv']:
            original = (base / filename).read_bytes()
            for word in [b'3f800000', b'80000000', b'7f800000', b'ffc00000']:
                with tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    shutil.copytree(base, root / 'fixtures')
                    changed = original.replace(b'00000000', word, 1)
                    (root / 'fixtures' / filename).write_bytes(changed)
                    directory = root / 'tools/bullet-rust-gjk-epa-check'
                    directory.mkdir(parents=True)
                    modified = copy.deepcopy(manifest)
                    modified['directory'] = 'fixtures'
                    (directory / 'gjk-epa-profiles.json').write_text(json.dumps(modified))
                    with patch.object(profiles, 'ROOT', root), self.assertRaisesRegex(ValueError, 'hash'):
                        profiles.load('gjk-epa')
                    modified['sha256'][filename] = hashlib.sha256(changed).hexdigest()
                    (directory / 'gjk-epa-profiles.json').write_text(json.dumps(modified))
                    with patch.object(profiles, 'ROOT', root), self.assertRaisesRegex(ValueError, 'inventory'):
                        profiles.load('gjk-epa')

    def test_raw_capture_profile_is_checked_separately(self):
        manifest, base = profiles.load('gjk-epa')
        profile = manifest['profiles']['macos-arm64']
        native = (base / 'native.tsv').read_bytes() + (base / 'raw-native.tsv').read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            inputs = (base / 'inputs.tsv').read_bytes()
            for name, data in [('native.tsv', native), ('observed.tsv', native), ('rust.tsv', native), ('inputs.tsv', inputs)]:
                (output / name).write_bytes(data)
            manifest['full_rows'] = 1810
            manifest['full_inputs_sha256'] = hashlib.sha256(inputs).hexdigest()
            profile['full_sha256'] = hashlib.sha256(native).hexdigest()
            # This test isolates raw profile equality; full sequential IDs are tested above.
            with patch.object(profiles, 'load', return_value=(manifest, base)), patch.object(profiles, 'host', return_value='macos-arm64'), patch.object(profiles, 'rows'):
                self.assertEqual(profiles.validate_capture(output, 'gjk-epa'), base / 'native.tsv')
                changed = native[:-2] + b'1\n'
                for name in ['native.tsv', 'observed.tsv', 'rust.tsv']:
                    (output / name).write_bytes(changed)
                with self.assertRaisesRegex(ValueError, 'raw'):
                    profiles.validate_capture(output, 'gjk-epa')


if __name__ == '__main__':
    unittest.main()
