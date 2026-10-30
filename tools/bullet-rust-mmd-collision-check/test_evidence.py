import unittest
from evidence import admit_capture


class AdmissionBoundaryTests(unittest.TestCase):
    def test_no_source_or_synthetic_input_is_admitted(self):
        for input in (None, {}, {'status': 'PASS'}, b'legal-looking-source'):
            with self.assertRaisesRegex(ValueError, 'context'):
                admit_capture(input)


class NativeEvidenceFramingTests(unittest.TestCase):
    def test_exact_archive_payload_and_compiled_source_binding(self):
        from evidence import digest, verify_archive
        source = 'recipes/bullet275/bullet-src/src/LinearMath/tiny.cpp'
        payload = b'opaque-compiled-object'
        header = (b'tiny.o/         ' + b'0           ' + b'0     ' + b'0     ' + b'100644  ' +
                  str(len(payload)).encode().ljust(10) + b'`\n')
        raw = b'!<arch>\n' + header + payload + (b'\n' if len(payload) % 2 else b'')
        bindings = [{'source': source, 'source_sha256': digest(b'int tiny;'),
                     'object': 'tiny.o', 'object_sha256': digest(payload)}]
        archive = verify_archive(raw, ['tiny.o'], 'Linux', bindings, {'tiny.o': payload}, {source: b'int tiny;'})
        self.assertEqual(archive.payloads, {'tiny.o': payload})
        for changed in (raw[:-1], raw + b'bad', raw.replace(payload, b'x' * len(payload))):
            with self.assertRaises(ValueError):
                verify_archive(changed, ['tiny.o'], 'Linux', bindings, {'tiny.o': payload}, {source: b'int tiny;'})

    def test_include_occurrence_duplicates_and_spelling_are_preserved(self):
        from evidence import digest, include_occurrences, include_projection
        raw = b'. /inert/one.h\n.. /inert/two.h\n. /inert/one.h\n'
        occurrences = include_occurrences(b'', raw, 'Linux')
        bindings = [{**item, 'target': item['raw'], 'sha256': digest(item['raw'].encode())} for item in occurrences]
        manifest, aliases = include_projection(bindings, occurrences, 'Linux')
        self.assertEqual(len(occurrences), 3)
        self.assertEqual(len(manifest), 2)
        self.assertEqual(len(aliases), 2)
        with self.assertRaises(ValueError):
            include_projection(bindings[:-1], occurrences, 'Linux')
        changed = [dict(item) for item in bindings]
        changed[-1]['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            include_projection(changed, occurrences, 'Linux')


class NativeLifetimeFramingTests(unittest.TestCase):
    def test_inert_allocation_and_reverse_physical_lifetime_framing(self):
        from evidence import validate_native_lifetimes
        inputs = 'H inert genuine\nC\nJ 0 1 -2147483648 1\nX\n'
        raw = (b'ALLOC 0 1 1 4096 16 16\nBODY_REGISTER 0 0 101\nBODY_REGISTER 1 1 202\n'
               b'JOINT_CREATE 2 0 303 -2147483648\nPHYSICAL 3 joint 303 -1\n'
               b'PHYSICAL 3 body 202 1\nPHYSICAL 3 body 101 0\nALLOC 3 2 0 4096 0 0\n')
        self.assertEqual(validate_native_lifetimes(raw, inputs, observed=True)['allocation_events'], 2)
        for changed in (raw.replace(b'ALLOC 3 2', b'ALLOC 3 3'),
                        raw.replace(b'body 202 1', b'body 202 0'),
                        raw.replace(b'303 -2147483648', b'303 0'),
                        raw[:raw.rindex(b'ALLOC')]):
            with self.assertRaises(ValueError):
                validate_native_lifetimes(changed, inputs, observed=True)


class CommandRecipeTests(unittest.TestCase):
    def test_inert_command_recipe_preserves_order_roles_and_generation(self):
        from evidence import command_schedule
        from hooks import MUTANTS
        for system, root, out, exe in [('Linux','/source','/capture','/tool'),
                                      ('Darwin','/source','/capture','/tool'),
                                      ('Windows','C:/source','D:/capture','C:/tool.exe')]:
            context = {'schema':1,'system':system,'root':root,'out':out,
                       'tools':{name:exe for name in ['python','git','rustup','rustc','rust_linker','compiler','archiver','native_linker']}}
            sources = ['recipes/bullet275/bullet-src/src/BulletCollision/BroadphaseCollision/btDbvt.cpp']
            recipe = command_schedule(context,sources,[])
            labels = [entry.label for entry in recipe]
            self.assertEqual(len(labels),len(set(labels)))
            self.assertEqual(labels[:2],['git-head','git-status'])
            self.assertLess(labels.index('compile-000-discovery'),labels.index('compile-000'))
            self.assertLess(labels.index('native-run'),labels.index('observed-run'))
            self.assertEqual(sum(entry.label.startswith('mutant-run-') for entry in recipe),len(MUTANTS))
            for name in MUTANTS:
                baseline = next(entry for entry in recipe if entry.label == 'baseline-build-'+name)
                mutant = next(entry for entry in recipe if entry.label == 'mutant-build-'+name)
                self.assertEqual(baseline.generation,'baseline-'+name)
                self.assertEqual(mutant.generation,'mutant-'+name)
                self.assertEqual(len(mutant.outputs),2 if system == 'Windows' else 1)
                if system == 'Windows':
                    self.assertTrue(mutant.outputs[-1].endswith('.pdb'))
            self.assertTrue(next(entry for entry in recipe if entry.label == 'native-run').corpus)
            self.assertTrue(next(entry for entry in recipe if entry.label == 'observed-consumer-build').compile)
            self.assertTrue(all(len(entry.outputs)==1 for entry in recipe if entry.compile))


if __name__ == '__main__':
    unittest.main()
