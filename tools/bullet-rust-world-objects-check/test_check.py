import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('objects_check', Path(__file__).with_name('check.py'))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

class TraceChecks(unittest.TestCase):
    def complete(self):
        rows = []
        for prefix,width in check.expected_records():
            if prefix[0] == 'W': suffix = ['00000000']*3 + ['N','0']
            elif prefix[0] == 'B': suffix = ['00000000']*111 + ['0']*5
            else: suffix = ['0']*(width-len(prefix))
            rows.append(' '.join(prefix+suffix))
        return ('\n'.join(rows)+'\n').encode()

    def test_complete_trace(self):
        check.validate(self.complete())
        self.assertEqual(len(check.expected_records()),206)

    def test_missing_duplicate_reordered_and_malformed_records_fail(self):
        raw = self.complete()
        for broken in [b'\n'.join(raw.splitlines()[:-1]), raw.replace(b'W P 0',b'W P 1',1),
                       raw.replace(b'00000000',b'NaN',1), raw+raw.splitlines()[0]+b'\n']:
            with self.assertRaises(AssertionError):check.validate(broken)

    def test_all_mutation_anchors_are_unique_and_change_source(self):
        source=(check.ROOT/'rust/crates/mds-bullet/src/core/world_objects.rs').read_text()
        for name,(old,new) in check.MUTANTS.items():
            self.assertEqual(source.count(old),1,name)
            self.assertNotEqual(source,source.replace(old,new),name)

    def test_generated_membership_and_raw_bytes_are_observed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/'source.rs';p.write_bytes(b'a\r\nb\n')
            first=check.hashes(root);p.write_bytes(b'a\nb\n')
            self.assertNotEqual(first,check.hashes(root))
            first=check.hashes(root);(root/'extra.rs').write_text('extra')
            self.assertNotEqual(first,check.hashes(root))
