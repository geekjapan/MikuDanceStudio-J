import importlib.util
from pathlib import Path
import unittest

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

    def test_unset_hook_retains_normal_compile(self):
        source = (HERE / '../../rust/crates/mds-bullet-sys/build.rs').read_text()
        self.assertEqual(source.count('build.compile("mds_bullet_sys")'), 1)
        self.assertLess(source.index('build.compile("mds_bullet_sys")'), source.index('if let Some(out) = env::var_os("MDS_BT_CONSUMER_PROBE_OUT")'))
        self.assertNotIn('define("WIN32"', source)


if __name__ == '__main__':
    unittest.main()
