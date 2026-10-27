import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('objects_check', Path(__file__).with_name('check.py'))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

class TraceChecks(unittest.TestCase):
    def complete(self):
        return Path(__file__).with_name('retained-native.tsv').read_bytes()

    def test_complete_trace(self):
        check.validate(self.complete(), extended=False)
        self.assertEqual(len(check.expected_records(False)),206)

    def test_missing_duplicate_reordered_and_malformed_records_fail(self):
        raw = self.complete()
        for broken in [b'\n'.join(raw.splitlines()[:-1]), raw.replace(b'W P 0',b'W P 1',1),
                       raw.replace(b'00000000',b'NaN',1), raw+raw.splitlines()[0]+b'\n']:
            with self.assertRaises(AssertionError):check.validate(broken, extended=False)

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

    def test_retained_trace_typed_fields_and_counts(self):
        raw = Path(__file__).with_name('retained-native.tsv').read_bytes()
        check.validate(raw, extended=False)
        for kind, offset, value in [('W',8,'garbage'), ('J',4,'-1'), ('J',6,'ffffffff'), ('C',3,'deadbeef'), ('W',7,'999'), ('W',8,'999'), ('B',-4,'0'), ('B',-3,'65535'), ('B',-1,'999')]:
            rows = raw.decode().splitlines()
            at = next(i for i,row in enumerate(rows) if row.startswith(kind+' ') and (kind != 'W' or len(row.split()) > 8))
            fields = rows[at].split(); fields[offset] = value; rows[at] = ' '.join(fields)
            with self.subTest(kind=kind,offset=offset,value=value):
                with self.assertRaises(AssertionError): check.validate(('\n'.join(rows)+'\n').encode(), extended=False)
        for broken in [raw.splitlines()[0], b'\n'.join(raw.splitlines()[:-1]), raw.replace(b'W P 0',b'W P',1)]:
            with self.assertRaises(AssertionError): check.validate(broken, extended=False)
        rows = raw.decode().splitlines()
        at = next(i for i,row in enumerate(rows) if row.startswith('J '))
        fields=rows[at].split(); fields[4]='7fc01234'; rows[at]=' '.join(fields)
        check.validate(('\n'.join(rows)+'\n').encode(), extended=False)
