import tempfile
from pathlib import Path
import unittest
from trace import compare, records, validate
from check import hooks, SOLVER
from cases import corpus


class TraceTests(unittest.TestCase):
    def test_exact_word_comparison_preserves_nan_and_signed_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            a,b=[Path(directory)/name for name in ['a','b']]
            a.write_text('0\t0\t0\t-1\t-1\t7fc00000\t80000000\n')
            b.write_text(a.read_text());self.assertIsNone(compare(a,b))
            b.write_text(a.read_text().replace('80000000','00000000'))
            self.assertEqual(compare(a,b)['word'],6)
            b.write_text(a.read_text().replace('7fc00000','ffc00000'))
            self.assertEqual(compare(a,b)['word'],5)

    def test_schema_consumes_all_words_and_rejects_missing_or_extra_fields(self):
        valid='0\t0\t0\t-1\t-1'+'\t00000000'*6+'\n'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace'
            path.write_text(valid);self.assertEqual(len(list(records(path))),1)
            for bad in [valid.rstrip()+'\t00000000\n',valid.replace('00000000','z0000000',1),valid.rsplit('\t',1)[0]+'\n']:
                path.write_text(bad)
                with self.assertRaises((ValueError,IndexError)):list(records(path))
            path.write_text(valid)
            with self.assertRaises(ValueError):validate(path)

    def test_hooks_cover_both_native_modes_and_corpus_is_deterministic(self):
        source=hooks(SOLVER.read_text())
        for kind in range(1,10):
            self.assertEqual(source.count(f'MIXED({kind}, iteration, j)'),2)
        self.assertEqual(corpus(),corpus())
        self.assertEqual(len(corpus().splitlines()),96)

if __name__=='__main__':unittest.main()
