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


def main_probe(case, directory):
    import contextlib
    import io
    import json
    import subprocess
    import sys
    from unittest.mock import patch

    out = Path(directory) / 'evidence'
    header = Path(directory) / 'header.h'; header.write_text('original')
    source = {'source': 'original'}
    rows = []
    for prefix, width in check.expected_records():
        fields = prefix + ['00000000'] * ((width or 8) - len(prefix))
        if prefix[0] == 'W': fields[6:] = ['N', '0']
        elif prefix[0] == 'B': fields[-5:] = ['0', '1', '0', '0', '0']
        elif prefix[0] == 'J':
            for i in (6,11,16,21,28,35,40,44,48,52,56,60): fields[i] = '0'
            if width == 65: fields[64] = '0'
        elif prefix[0] == 'V': fields[3:] = ['-2' if prefix[1] == 'Q' else '0', str(7 if prefix[1] == 'Q' else 6 + int(prefix[2]))]
        elif prefix[0] in ('C','K'): fields[3] = '0'
        elif prefix[0] == 'R': fields[3] = '7'
        rows.append(' '.join(fields))
    raw = ('\n'.join(rows) + '\n').encode()
    changed = raw.replace(b'00000000', b'80000000', 1)
    check.validate(raw); check.validate(changed)
    def command(argv, **kwargs):
        label = json.loads((out / 'commands.json').read_text())[-1]['label']
        stdout = b''; stderr = b''; code = 0
        if label == 'compiler-version':
            stderr = (f'Note: including file: {header}\n' if check.os.name == 'nt' else f'. {header}\n').encode()
            if case == 'nonzero': code = 9
        if label == 'rust-version':
            if case == 'include-closure': header.write_text('changed')
            if case == 'source-closure': source['source'] = 'changed'
            if case == 'generated-closure': (out / 'generated-sources/extra').write_text('changed')
        if label in ('build-native','build-native-observed'):
            path = header if case != 'observer-includes' or label == 'build-native' else Path(__file__)
            stderr = (f'Note: including file: {path}\n' if check.os.name == 'nt' else f'. {path}\n').encode()
        if label in ('native','native-observed','rust','rust-observed') or label.startswith('mutant-'):
            stdout = raw
            if label in ('native-observed','rust-observed'): stderr = b'OBS P 0 0 0\n'
            if case == 'native-observer' and label == 'native-observed': stdout = changed
            if case == 'rust-observer' and label == 'rust-observed': stdout = changed
            if case == 'observer-counts' and label == 'rust-observed': stderr = b'OBS P 0 1 0\n'
            if case == 'raw-mismatch' and label in ('rust','rust-observed'): stdout = changed
            if label.startswith('mutant-'):
                if case != 'survivor': stdout = changed
                if case == 'final-closure': source['source'] = 'changed'
        return subprocess.CompletedProcess(argv, code, stdout, stderr)
    with patch.object(sys, 'argv', ['check.py','--out-dir',str(out),'--mutation','ignore-active']), \
         patch.object(check, 'source_snapshot', side_effect=lambda: dict(source)), \
         patch.object(check.subprocess, 'run', side_effect=command), \
         contextlib.redirect_stdout(io.StringIO()):
        try: check.main()
        except AssertionError: pass


class RuntimeChecks(unittest.TestCase):
    def test_main_acceptance_boundaries_in_normal_and_optimized_python(self):
        import json
        import subprocess
        import sys
        errors = {
            'clean': None,
            'nonzero': 'compiler-version failed (9)',
            'native-observer': 'native observer changed stdout',
            'rust-observer': 'Rust observer changed stdout',
            'observer-counts': 'observer counts differ',
            'raw-mismatch': 'raw mismatch',
            'survivor': 'mutant survived: ignore-active',
            'observer-includes': 'observer include resolution differs',
            'include-closure': 'closure changed: include',
            'source-closure': 'closure changed: source',
            'generated-closure': 'closure changed: generated',
            'final-closure': 'closure changed: source',
        }
        for optimized in (False, True):
            for case, error in errors.items():
                with self.subTest(optimized=optimized, case=case), tempfile.TemporaryDirectory() as directory:
                    result = subprocess.run([sys.executable, *(['-O'] if optimized else []), '-c',
                        'import test_check; test_check.main_probe(*__import__("sys").argv[1:])', case, directory],
                        cwd=Path(__file__).parent, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    out = Path(directory) / 'evidence'
                    status = json.loads((out / 'status.json').read_text())
                    self.assertEqual(status['status'], 'FAIL' if error else 'PASS_SELECTED_MUTATIONS_ONLY')
                    if error: self.assertIn(error, status['error'])
                    else:
                        self.assertEqual(status['trace_lines'], 478)
                        self.assertEqual(status['mutants'], {'ignore-active': 'CAUGHT'})
                    self.assertEqual(len(json.loads((out / 'native-includes.json').read_text())), 1 if case != 'observer-includes' else 2)
                    if 'closure' in case:
                        self.assertEqual(status['integrity'], 'FAIL')
                        if case != 'final-closure': self.assertIn('before command', status['original_error'])
                    else: self.assertEqual(status['integrity'], 'PASS')
