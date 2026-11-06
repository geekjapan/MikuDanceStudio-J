import unittest

from friction_dependencies import TARGET, parse, validate


class CompilerDependencies(unittest.TestCase):
    def test_compiler_rule_with_escaped_paths(self):
        raw = (TARGET + ': source.cpp forced.h \\\n folder/a\\ b.h hash\\#.h cash$$.h back\\\\slash.h\n').encode()
        self.assertEqual(parse(raw), ['source.cpp', 'forced.h', 'folder/a b.h',
                                      'hash#.h', 'cash$.h', 'back\\slash.h'])

    def test_malformed_rules_fail_closed(self):
        for body in ('', 'x x', 'x\nother: y', 'x # comment', '$(var)', 'x\\', 'x\\q', 'x\x00'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse((TARGET + ': ' + body).encode())
        with self.assertRaises(ValueError):
            parse(b'wrong: source.cpp')

    def test_continuation_separates_words(self):
        self.assertEqual(parse((TARGET + ': a\\\n' + 'b').encode()), ['a', 'b'])

    def test_forced_header_comes_from_depfile_not_trace_or_arguments(self):
        def bindings(raw, digest='a'):
            return [{'raw': p, 'target': '/' + p, 'sha256': digest} for p in parse(raw)]
        raw = (TARGET + ': source.cpp ordinary.h forced.h\n').encode()
        required = ['/source.cpp', '/forced.h']
        traced = ['/ordinary.h']
        before = validate(bindings(raw), required=required, traced=traced)
        self.assertIn(('forced.h', '/forced.h', 'a'), before)
        missing = (TARGET + ': source.cpp ordinary.h\n').encode()
        with self.assertRaises(ValueError):
            validate(bindings(missing), required=required, traced=traced)
        with self.assertRaises(ValueError):
            validate(bindings(raw), required=required, traced=['/unreported.h'])
        self.assertNotEqual(before, validate(bindings(raw, 'b'), required=required, traced=traced))
        extra = (TARGET + ': source.cpp ordinary.h forced.h extra.h\n').encode()
        self.assertNotEqual(before, validate(bindings(extra), required=required, traced=traced))


if __name__ == '__main__':
    unittest.main()
