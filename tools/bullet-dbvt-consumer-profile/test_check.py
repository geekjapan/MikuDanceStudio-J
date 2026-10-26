import importlib.util
from pathlib import Path
import unittest
import subprocess

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
        self.assertFalse(check.comparison_result(state_mismatch))
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

    def comparison(self, failure=None, code=None):
        names = ['dbvt::tests::native_controlled_address_parity',
                 'dbvt::tests::ordinary_native_and_production_allocator_query_sets']
        failed = int(failure is not None)
        text = 'running 2 tests\n'
        text += ''.join(f'test {name} ... {"FAILED" if failed and i == 0 else "ok"}\n' for i, name in enumerate(names))
        if failure is not None:
            text += f"\nfailures:\n\n---- {names[0]} stdout ----\n\nthread '{names[0]}' (5625252) panicked at fixtures.rs:168:13:\n{failure}\n  left: 1\n right: 2\n"
        text += f'\ntest result: {"FAILED" if failed else "ok"}. {2 - failed} passed; {failed} failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.05s\n'
        return subprocess.CompletedProcess([], (101 if failed else 0) if code is None else code, text.encode(), b'')

    def test_only_identified_semantic_mismatch_completes(self):
        self.assertTrue(check.comparison_result(self.comparison()))
        self.assertFalse(check.comparison_result(self.comparison('assertion `left == right` failed: DBVT_COMPATIBILITY_MISMATCH order 0 operation 0: i 1')))
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

    def test_unset_hook_retains_normal_compile(self):
        source = (HERE / '../../rust/crates/mds-bullet-sys/build.rs').read_text()
        self.assertEqual(source.count('build.compile("mds_bullet_sys")'), 1)
        self.assertLess(source.index('build.compile("mds_bullet_sys")'), source.index('if let Some(out) = env::var_os("MDS_BT_CONSUMER_PROBE_OUT")'))
        self.assertNotIn('define("WIN32"', source)


if __name__ == '__main__':
    unittest.main()
