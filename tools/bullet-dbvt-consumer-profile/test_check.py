import importlib.util
from pathlib import Path
import unittest
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('consumer_check', HERE / 'check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class ClassificationTests(unittest.TestCase):
    def profile(self, select='return(Proximity(o,a)<Proximity(o,b)?0:1);'):
        return '''bool Intersect(const A& a,const A& b) { return(a.mi.x()<=b.mx.x()); }
int Select(const A& o,const A& a,const A& b) { %s }
void Merge(const A& a,const A& b,A& r) { if(a.mi[i]<b.mi[i]) r=a; }
struct ICollide { virtual void Process();
};
static btDbvtVolume merge(const A& a,const A& b) { char locals[sizeof(btDbvtAabbMm)]; btDbvtVolume& res=*(btDbvtVolume*)locals; return res; }
static btDbvtVolume bounds(const Array& a) { char locals[sizeof(btDbvtVolume)]; btDbvtVolume& volume=*(btDbvtVolume*)locals; return volume; }
''' % select

    def test_inline_generic_with_post_undef_aligned_cpp(self):
        profile, extracts = check.classify(self.profile(), cpp=True)
        self.assertEqual(profile, dict(Intersect='generic', Select='generic', Merge='generic', policy='virtual', merge_local='aligned', bounds_local='aligned'))
        self.assertIn('locals[', extracts['merge'])

    def test_sse_is_observed_without_os_assumptions(self):
        profile, _ = check.classify(self.profile('return _mm_cmple_ss(a,b);'))
        self.assertEqual(profile['Select'], 'sse')

    def test_unknown_and_ambiguous_fail_closed(self):
        for body in ('return 0;', 'return _mm_cmple_ss(a,b) + (Proximity(o,a)<Proximity(o,b)?0:1);'):
            with self.assertRaises(ValueError):
                check.classify(self.profile(body))

    def test_missing_policy_and_truncated_body_fail_closed(self):
        with self.assertRaises(ValueError):
            check.classify(self.profile().replace('struct ICollide', 'struct Unknown'))
        with self.assertRaises(ValueError):
            check.function('void Merge(A a) { if(a) {', 'Merge')

    def test_malformed_aabb_fails_closed(self):
        valid = '\n'.join(f'{i}|' + ','.join(['0'] * 12) + '|' + ','.join(['0'] * 13) for i in range(51)).encode()
        self.assertEqual(len(check.validate_aabb(valid)), 51)
        for bad in (valid.splitlines()[0], valid.replace(b'0|', b'X|', 1), valid.replace(b',0', b',4294967296', 1)):
            with self.assertRaises(ValueError):
                check.validate_aabb(bad)

    def native_row(self):
        return '1,-1,0,0|1,0,0,0,1,1,1|0,|'

    def test_native_schema_and_ordinary_pointer_variability(self):
        row = self.native_row()
        check.validate_native((row + '\n').encode(), b'i 1 0 0 0 1 1 1\n')
        check.validate_native((row.replace('|0,|', '|4503599627370495,|') + '\n').encode(), b'i 1 0 0 0 1 1 1\n')
        maximum_rank = row.replace('|0,|', '|18446744073709551615,|')
        check.validate_native((maximum_rank + '\n').encode(), b'i 1 0 0 0 1 1 1\n')
        check.validate_native(b'1,-1,0,0|_||\n', b'c\n')
        for bad in ('malformed', row + '|extra',
                    row.replace('1,0,0,0,1,1,1', '128,0,0,0,1,1,1'),
                    row.replace(',1,1,1', ',4294967296,1,1'),
                    row.replace('|0,|', '|bad,|'), row.replace('|0,|', '||'),
                    row.replace('|0,|', '|18446744073709551616,|'),
                    row + '1,', row.replace('1,-1', '1,2147483648')):
            with self.subTest(row=bad), self.assertRaises(ValueError):
                check.validate_native((bad + '\n').encode(), b'i 1 0 0 0 1 1 1\n')
        with self.assertRaises(ValueError):
            check.validate_native((row + '\n').encode(), b'i\ni\n')
        malformed_rank = '2,-1,0,0|1,1065353216,0,0,1073741824,1065353216,1065353216|18446744073709551616,|'
        state_mismatch = self.comparison('assertion `left == right` failed: DBVT_COMPATIBILITY_MISMATCH order 0 operation 0: i 1')
        self.assertFalse(check.comparison_result(state_mismatch)['controlled_corpus'])
        with self.assertRaises(ValueError):
            check.validate_native((malformed_rank + '\n').encode(), b'i 1 0 0 0 1 1 1\n')
            check.comparison_result(state_mismatch)
        with self.assertRaises(ValueError):
            check.validate_native(b'malformed\n' * 2326, b'i\n' * 2326)

    def test_native_event_schema(self):
        row = self.native_row()
        for operation, event in [('p', '1,0,0,0,1,1,1'), ('v', '1,'),
                                 ('q', '1,'), ('s', '1:2,'), ('x', '1:100,')]:
            check.validate_native((row + event + '\n').encode(), operation.encode())
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                check.validate_native((row + 'bad\n').encode(), operation.encode())
        branch = '2,-1,0,0|B,0,0,0,1,1,1(1,0,0,0,1,1,1;2,0,0,0,1,1,1)|0,1,2,|'
        check.validate_native(branch.encode(), b'i')
        for bad in (branch.replace(';', ','), branch[:-1] + 'x', branch.replace(';2,', ';1,'), branch.replace(')|', ')trailing|')):
            with self.assertRaises(ValueError):
                check.validate_native(bad.encode(), b'i')

    def comparison(self, failure=None, code=None, failed_name='dbvt::tests::native_controlled_address_parity'):
        names = sorted(check.REQUIRED_TESTS)
        failed = int(failure is not None)
        text = 'running 11 tests\n'
        text += ''.join(f'test {name} ... {"FAILED" if failed and name == failed_name else "ok"}\n' for name in names)
        if failure is not None:
            text += f"\nfailures:\n\n---- {failed_name} stdout ----\n\nthread '{failed_name}' (5625252) panicked at fixtures.rs:168:13:\n{failure}\n  left: 1\n right: 2\n"
        text += f'\ntest result: {"FAILED" if failed else "ok"}. {11 - failed} passed; {failed} failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.05s\n'
        return subprocess.CompletedProcess([], (101 if failed else 0) if code is None else code, text.encode(), b'')

    def test_only_identified_semantic_mismatch_completes(self):
        self.assertTrue(all(check.comparison_result(self.comparison()).values()))
        self.assertFalse(check.comparison_result(self.comparison('assertion `left == right` failed: DBVT_COMPATIBILITY_MISMATCH order 0 operation 0: i 1'))['controlled_corpus'])
        for failure in ('called `Result::unwrap()` on an `Err` value: ParseIntError',
                        'run check.py to capture the real native oracle',
                        'index out of bounds: the len is 1 but the index is 1',
                        'unknown operation', 'assertion `left == right` failed'):
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                check.comparison_result(self.comparison(failure))
        mixed = self.comparison('assertion `left == right` failed: DBVT_COMPATIBILITY_MISMATCH order 0 operation 0')
        mixed.stdout += b"thread 'other' panicked at test.rs:1:1:\nunknown failure\n"
        with self.assertRaises(ValueError):
            check.comparison_result(mixed)
        for code in (-11, 1, 101):
            with self.subTest(code=code), self.assertRaises(ValueError):
                check.comparison_result(self.comparison(code=code))
        for text in (b'', b'error: could not compile', b'test result: FAILED.\n',
                     self.comparison().stdout.replace(b'0 ignored', b'1 ignored'),
                     self.comparison().stdout.replace(b'0 filtered out', b'1 filtered out')):
            with self.assertRaises(ValueError):
                check.comparison_result(subprocess.CompletedProcess([], 101, text, b''))

    def test_directed_select_requires_its_own_marker(self):
        name = 'select::directed_select_association_matches_native'
        marker = 'assertion `left == right` failed: DBVT_COMPATIBILITY_MISMATCH directed Select native'
        results = check.comparison_result(self.comparison(marker, failed_name=name))
        self.assertEqual(results, dict(directed_select=False, controlled_corpus=True, ordinary_corpus=True))
        for failure in ('assertion `left == right` failed',
                        'assertion `left == right` failed: DBVT_COMPATIBILITY_MISMATCH order 0',
                        'unknown operation'):
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                check.comparison_result(self.comparison(failure, failed_name=name))
        with self.assertRaises(ValueError):
            check.comparison_result(self.comparison(marker))

    def test_other_test_panics_and_nonzero_exits_are_not_compatibility(self):
        marker = 'assertion `left == right` failed: DBVT_COMPATIBILITY_MISMATCH order 0 operation 0'
        for name in check.REQUIRED_TESTS - check.COMPARISON_TESTS.keys():
            with self.subTest(name=name), self.assertRaises(ValueError):
                check.comparison_result(self.comparison(marker, failed_name=name))
        for code in (-11, -6, 1, 2, 102):
            with self.subTest(code=code), self.assertRaises(ValueError):
                check.comparison_result(self.comparison(marker, code=code))
        ordinary = self.comparison(
            'assertion `left == right` failed: DBVT_COMPATIBILITY_MISMATCH operation 0 i 1',
            failed_name='dbvt::tests::ordinary_native_and_production_allocator_query_sets')
        self.assertFalse(check.comparison_result(ordinary)['ordinary_corpus'])
        spoofed = self.comparison(marker)
        spoofed.stdout = spoofed.stdout.replace(b"thread 'dbvt::tests::native_controlled_address_parity'", b"thread 'other'")
        with self.assertRaises(ValueError):
            check.comparison_result(spoofed)

    def test_all_eleven_unique_tests_and_summary_are_required(self):
        original = self.comparison().stdout
        name = b'select::directed_select_association_matches_native'
        for text in (original.replace(name, b'unknown::test'),
                     original.replace(b'test ' + name + b' ... ok\n', b''),
                     original.replace(name, b'dbvt::tests::native_controlled_address_parity'),
                     original.replace(b'11 passed', b'10 passed'),
                     original.replace(b'0 measured', b'1 measured'),
                     original + original,
                     original + b'unknown panic transport panicked at elsewhere\n',
                     original + b"thread 'other' panicked at test.rs:1:1:\nunknown failure\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                check.comparison_result(subprocess.CompletedProcess([], 0, text, b''))

    def test_select_transport_must_be_a_complete_permutation(self):
        for data in (b'2,3,1,\n', b'3,2,1,\r\n'):
            check.validate_select(data)
        for data in (b'', b'2,3,1,', b'2,3,1,\nextra', b'1,1,2,\n', b'1,2,128,\n', b'bad\n'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                check.validate_select(data)

    def test_source_closure_and_open_log_exclusion(self):
        files = check.source_manifest()
        for path in ('rust/crates/mds-bullet/src/core/math.rs',
                     'rust/crates/mds-bullet/src/core/pair_cache.rs',
                     'rust/crates/mds-crtmath/src/lib.rs',
                     'rust/crates/mds-crtmath/src/trig.rs',
                     'rust/Cargo.toml', 'rust/rust-toolchain.toml'):
            self.assertIn(path, files)
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            (out / 'check.log').write_text('still open')
            (out / 'report.json').write_text('pending')
            (out / 'rust-tests.stdout').write_text('complete')
            manifest = check.artifact_manifest(out)
            (out / 'check.log').write_text('now finished')
            self.assertEqual(manifest, check.artifact_manifest(out))
            self.assertEqual(set(manifest), {'rust-tests.stdout'})

    def test_only_native_select_assertion_is_marked(self):
        source = (check.OLD / 'select.rs').read_text()
        self.assertEqual(source.count('DBVT_COMPATIBILITY_MISMATCH'), 1)
        self.assertIn('events, expected,\n        "DBVT_COMPATIBILITY_MISMATCH directed Select native"', source)

    def test_unset_hook_retains_normal_compile(self):
        source = (HERE / '../../rust/crates/mds-bullet-sys/build.rs').read_text()
        self.assertEqual(source.count('build.compile("mds_bullet_sys")'), 1)
        self.assertLess(source.index('build.compile("mds_bullet_sys")'), source.index('if let Some(out) = env::var_os("MDS_BT_CONSUMER_PROBE_OUT")'))
        self.assertNotIn('define("WIN32"', source)


if __name__ == '__main__':
    unittest.main()
