"""Small inert helper tests. Hosted suites do not substitute for actual capture."""
import unittest
import struct
import copy
import ast
from pathlib import Path
import re

from cases import corpus, dynamics_corpus, word
from hooks import MUTANTS, DYNAMICS_MUTANTS, OWNER, inverse, mutate, replace, instrument, observation_paths
from trace import frames, validate_lifetimes, semantic_projection, common, visibility


class Memory:
    def __init__(self, files, name=''):
        self.files, self.name = files, name
    def __truediv__(self, name):
        return Memory(self.files, self.name + ('/' if self.name else '') + str(name))
    def read_bytes(self):
        return self.files[self.name]
    def write_bytes(self, raw):
        self.files[self.name] = raw
    def read_text(self):
        return self.read_bytes().decode().replace('\r\n', '\n')


class CorpusTests(unittest.TestCase):
    def test_mmd_allocator_roles_use_unchanged_active_raw_archive_path(self):
        directory = Path(__file__).resolve().parent
        allocator = (directory / 'allocator.hpp').read_text()
        native = (directory.parents[1] / 'recipes/bullet275/bullet-src/src/LinearMath/btAlignedAllocator.cpp').read_text()
        self.assertIn('btAlignedAllocSetCustom(mmd_allocate,mmd_deallocate)', allocator)
        self.assertNotIn('btAlignedAllocSetCustomAligned', allocator)
        self.assertNotIn('BT_HAS_ALIGNED_ALLOCATOR', allocator)
        allocate = native.split('void*\tbtAlignedAllocInternal\t(size_t size, int alignment)', 1)[1]
        allocate = allocate.split('#endif  // defined (BT_HAS_ALIGNED_ALLOCATOR)', 1)[0]
        self.assertIn('sAlignedAllocFunc(size, alignment);\n#else', allocate)
        self.assertIn('sAllocFunc(size + sizeof(void *) + (alignment-1))', allocate)
        free = native.split('void\tbtAlignedFreeInternal\t(void* ptr)', 1)[1]
        self.assertIn('sAlignedFreeFunc(ptr);\n#else', free)
        self.assertIn('real = *((void **)(ptr)-1);\n    sFreeFunc(real);', free)

    def test_include_acquisition_preserves_resolved_windows_case_and_raw_alias(self):
        import ntpath
        from pathlib import PureWindowsPath
        from types import SimpleNamespace
        from unittest.mock import Mock, MagicMock
        from evidence import digest, require
        tree = ast.parse((Path(__file__).resolve().parent / 'check.py').read_text())
        acquire = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                       and node.name == 'acquire')
        physical = r'C:\capture\generated\BulletCollision\btBroadphaseInterface.h'
        target = Mock()
        target.__str__ = Mock(return_value=physical)
        target.is_file.return_value = True
        target.read_bytes.return_value = b'header'
        alias = r'c:\capture\generated\bulletcollision\btbroadphaseinterface.h'
        source = Mock()
        source.is_absolute.return_value = True
        source.resolve.return_value = target
        out, recorder = MagicMock(), Mock()
        namespace = dict(Path=Mock(return_value=source), out=out, recorder=recorder,
                         digest=digest, require=require, os=SimpleNamespace(path=SimpleNamespace(normcase=ntpath.normcase)))
        exec(compile(ast.Module(body=[acquire], type_ignores=[]), 'include-acquisition', 'exec'), namespace)
        occurrence = {'stream': 'stdout', 'ordinal': 3, 'raw': alias}
        self.assertEqual(namespace['acquire']([occurrence], PureWindowsPath('C:/source')),
                         [{**occurrence, 'target': physical, 'sha256': digest(b'header')}])
        source.resolve.assert_called_once_with(strict=True)
        source.resolve.side_effect = FileNotFoundError(alias)
        with self.assertRaises(FileNotFoundError):
            namespace['acquire']([occurrence], PureWindowsPath('C:/source'))
        preservation = next(node for node in ast.walk(tree) if isinstance(node, ast.Expr)
                            and isinstance(node.value, ast.Call) and node.value.args
                            and isinstance(node.value.args[-1], ast.Constant)
                            and node.value.args[-1].value == 'discovery pre-use/measured include preservation')
        manifest = {physical: digest(b'header')}
        aliases = {alias: (physical, digest(b'header'))}
        code = compile(ast.Module(body=[preservation], type_ignores=[]), 'include-preservation', 'exec')
        exec(code, dict(require=require, pre_manifest=manifest, post_manifest=manifest,
                        pre_aliases=aliases, post_aliases=aliases))
        with self.assertRaisesRegex(ValueError, 'include preservation'):
            exec(code, dict(require=require, pre_manifest=manifest,
                            post_manifest={physical: digest(b'changed')},
                            pre_aliases=aliases, post_aliases=aliases))

    def test_expanded_commands_preserve_source_and_policy_names(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        tree = ast.parse((Path(__file__).resolve().parent / 'check.py').read_text())
        block = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                     and ast.unparse(node.test) == "source.stem in {'btDbvt', 'btDbvtBroadphase'}")
        code = compile(ast.Module(body=[block], type_ignores=[]), 'expanded-producer', 'exec')
        labels = []
        for stem, label in [('btDbvt', 'expanded-btdbvt'),
                            ('btDbvtBroadphase', 'expanded-btdbvtbroadphase')]:
            for system in ['posix', 'nt']:
                source, root, out = Path('/source') / (stem + '.cpp'), Path('/source'), Path('/capture')
                recorder = Mock()
                recorder.run.return_value = b'inert-policy'
                observed = {'policy': 'mmd-win64-sse' if system == 'nt' else 'generic-reference'}
                def require(value, message):
                    if not value:
                        raise ValueError(message)
                exec(code, dict(source=source, ROOT=root, out=out, recorder=recorder,
                                native_flags=lambda root, dynamics=False: [], compiler='/inert/compiler', dynamics=False,
                                os=SimpleNamespace(name=system), policy=lambda raw: observed, require=require))
                args, kwargs = recorder.run.call_args
                self.assertEqual(args[0], label)
                self.assertRegex(args[0], r'^[a-z0-9-]+$')
                self.assertEqual(args[1][-1], source)
                self.assertEqual(kwargs['inputs'], [source])
                recorder.save.assert_called_once_with(out / ('policy-' + stem + '.json'), observed)
            labels.append(label)
        self.assertEqual(len(labels), len(set(labels)))

    def test_generated_rust_literal_dependencies_are_in_source_closure(self):
        here = Path(__file__).resolve().parent
        root = here.parents[1]
        manifest = ast.parse((here / 'check.py').read_text())
        declared = {node.targets[0].id: ast.literal_eval(node.value)
                    for node in manifest.body if isinstance(node, ast.Assign)
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id in {'FOLDERS', 'EXTRA'}}
        folders = [root / name for name in declared['FOLDERS']]
        extra = {root / name for name in declared['EXTRA']}
        pending = list((root / 'rust/crates/mds-bullet/src/core').rglob('*.rs'))
        pending.append(here / 'runner.rs')
        visited = set()
        dependencies = re.compile(
            r'#\[path\s*=\s*"([^"]+)"\]|include(?:_str|_bytes)?!\(\s*"([^"]+)"')
        while pending:
            source = pending.pop().resolve()
            if source in visited:
                continue
            visited.add(source)
            for match in dependencies.finditer(source.read_text()):
                target = (source.parent / (match[1] or match[2])).resolve()
                with self.subTest(source=source.relative_to(root), target=target):
                    self.assertTrue(target.is_relative_to(root), 'dependency escapes generated root')
                    self.assertTrue(target.is_file(), 'literal Rust dependency exists')
                    self.assertTrue(target in extra or any(target.is_relative_to(folder) for folder in folders),
                                    'literal Rust dependency belongs to generated source manifest')
                if target.suffix == '.rs':
                    pending.append(target)

    def test_source_derived_case_families_and_unique_names(self):
        inputs, cases = corpus()
        self.assertLessEqual(len(inputs.encode()), 64 * 1024)
        families = {'constructor': 1, 'ordered-shapes': 9, 'floor': 6, 'signed-filter': 8,
                    'mode': 9, 'motion': 3, 'joint': 6, 'huge-aabb': 12, 'multiway': 1}
        self.assertEqual({family: sum(c['family'] == family for c in cases) for family in families}, families)
        self.assertEqual(len(cases), sum(families.values()))
        self.assertEqual(len({c['name'] for c in cases}), len(cases))
        commands = inputs.splitlines()
        for case in cases:
            self.assertEqual(commands[case['start']].split()[1], case['name'])
            self.assertEqual(commands[case['end']], 'X')
        self.assertEqual(cases[0]['start'], 0)
        self.assertEqual(cases[-1]['end'], len(commands) - 1)
        self.assertTrue(all(b['start'] == a['end'] + 1 for a, b in zip(cases, cases[1:])))

    def test_dynamics_corpus_has_genuine_toggles_and_per_operation_classification(self):
        inputs, cases = dynamics_corpus()
        commands = inputs.splitlines()
        self.assertEqual(len(cases), 30)
        self.assertEqual(len(commands), 696)
        self.assertEqual(len({case['name'] for case in cases}), 30)
        self.assertEqual({family: sum(case['family'] == family for case in cases)
                          for family in ('clock', 'gravity-force-clear', 'motion-floor-uid', 'warmstart', 'shared-endpoint')},
                         {'clock': 1, 'gravity-force-clear': 1, 'motion-floor-uid': 3, 'warmstart': 1, 'shared-endpoint': 24})
        for case in cases:
            self.assertEqual([op['row'] for op in case['operations']], list(range(case['start'], case['end'] + 1)))
            for op in case['operations']:
                tag = commands[op['row']].split()[0]
                self.assertEqual(op['scope'], 'fixture-injection' if tag in {'L', 'FRC', 'W'} else 'genuine-mmd-operations')
            if case['family'] != 'shared-endpoint':
                continue
            operations = commands[case['start']:case['end'] + 1]
            toggles = [i for i, op in enumerate(operations) if op.startswith('K ')]
            self.assertEqual(len(toggles), 2)
            self.assertTrue(operations[toggles[0]].endswith(' 1'))
            self.assertTrue(operations[toggles[1]].endswith(' 0'))
            self.assertTrue(any(op.startswith('M ') for op in operations[toggles[0]:toggles[1]]))
            self.assertTrue(any(op.startswith('N ') for op in operations[toggles[0]:toggles[1]]))
            self.assertTrue(operations[toggles[1] + 1].startswith('N '))
            if '-joint-' in case['name']:
                self.assertTrue(all(op.split()[5] == '0' for op in [op for op in operations if op.startswith('C ')][:3]))

    def test_dynamics_hooks_and_mutants_have_exact_source_anchors_and_inverses(self):
        root = Path(__file__).resolve().parents[2]
        here = Path(__file__).resolve().parent
        names = set(observation_paths(True)) | {value[0] for value in DYNAMICS_MUTANTS.values()}
        names |= {f'tools/bullet-rust-mmd-collision-check/{name}' for name in ('fixture.rs', 'dynamics_fixture.rs')}
        originals = {name: (root / name).read_bytes() for name in names}
        memory = Memory(dict(originals))
        edits = instrument(memory, Memory(originals, 'tools/bullet-rust-mmd-collision-check'), True)
        inverse(memory, edits, {name: originals[name] for name in observation_paths(True)})
        for name, (_, _, _, field) in DYNAMICS_MUTANTS.items():
            generated = Memory(dict(memory.files))
            mutation = mutate(generated, name, True)
            self.assertEqual(len(mutation), 1)
            inverse(generated, mutation, {mutation[0]['path']: memory.files[mutation[0]['path']]})
            self.assertEqual(semantic_projection([], field), [])

    def test_dynamics_visibility_keeps_shim_status_distinct_from_bullet_return(self):
        commands = 'N 00000000 0 3c800000\nX\n'
        original = b'STATUS 0 0\nO 0 N 0 0 0\nO 1 X 0 0 0\nZ 2\n'
        observed = b'K 0 0 0 00000000 00000000\nR 0 0\n' + original
        native = frames(original, commands, observed=False, dynamics=True)
        rust = frames(observed, commands, dynamics=True)
        self.assertEqual(common(native, dynamics=True), common(rust, dynamics=True))
        for raw, seen in [(observed, False), (original, True),
                          (observed.replace(b'R 0 0\n', b''), True),
                          (observed.replace(b'STATUS 0 0', b'STATUS 0 1'), True)]:
            with self.assertRaises(ValueError):
                frames(raw, commands, observed=seen, dynamics=True)
        with self.assertRaises(ValueError):
            frames(original, commands)
        self.assertNotIn('R', visibility(True, False))
        self.assertIn('STATUS', visibility(True, False))

    def test_huge_boxes_keep_one_edge_unsaturated_and_use_reachable_flags(self):
        inputs, cases = corpus()
        lines = inputs.splitlines()
        for case in cases:
            if case['family'] != 'huge-aabb':
                continue
            body = lines[case['start'] + 1].split()
            self.assertEqual(body[6], body[10])
            flags = int(case['name'].split('-')[-1])
            self.assertEqual(body[3], '0' if flags & 1 else '1')
            self.assertEqual(lines[case['start'] + 2], f'K 1 {int(bool(flags & 2))}')

    def test_words_preserve_negative_zero(self):
        self.assertEqual(word(-0.0), '80000000')
        self.assertNotEqual(word(-0.0), word(0.0))

    def test_stop_at_has_its_own_nonzero_interpolation_marker(self):
        inputs, cases = corpus()
        lines = inputs.splitlines()
        for case in cases:
            if case['family'] != 'motion':
                continue
            operations = lines[case['start']:case['end']]
            stop = next(i for i, command in enumerate(operations) if command.startswith('O '))
            self.assertTrue(operations[stop - 1].startswith('V 1 '))
            self.assertNotIn('00000000', operations[stop - 1].split()[2:])

    def test_translated_huge_boundary_uses_float32_operations(self):
        f32 = lambda value: struct.unpack('<f', struct.pack('<f', value))[0]
        inputs, cases = corpus()
        lines = inputs.splitlines()
        for case in cases:
            if case['family'] != 'huge-aabb':
                continue
            words = lines[case['start'] + 1].split()
            extent = struct.unpack('<f', bytes.fromhex(words[6])[::-1])[0]
            half = f32(f32(extent - f32(.04)) + f32(.04))
            lo = f32(f32(extent - half) - f32(.02))
            hi = f32(f32(extent + half) + f32(.02))
            width = f32(hi - lo)
            side = f32(f32(1.0 + f32(.02)) - f32(-1.0 - f32(.02)))
            diagonal = f32(f32(f32(width * width) + f32(side * side)) + f32(side * side))
            expected = case['name'].split('-')[1]
            self.assertEqual('below' if diagonal < f32(1e12) else 'above' if diagonal > f32(1e12) else 'equal', expected)
            self.assertGreaterEqual(lo, -10000.0)

    def test_exact_hook_inverse_for_both_transports(self):
        for ending in (b'\n', b'\r\n'):
            original = b'one' + ending + b'two' + ending
            memory = Memory({'source': original})
            edits = []
            replace(memory, 'source', 'one\ntwo', 'one\nobserved\ntwo', edits)
            inverse(memory, edits, {'source': original})
            self.assertNotEqual(memory.files['source'], original)
            memory.files['source'] += b'changed'
            with self.assertRaises(ValueError):
                inverse(memory, edits, {'source': original})

    def test_each_mutant_is_an_exact_single_reversible_edit(self):
        for name, (path, old, new, field) in MUTANTS.items():
            self.assertTrue(field)
            self.assertEqual(semantic_projection([], field), [])
            self.assertNotEqual(old, new)
            memory = Memory({path: old.encode()})
            edits = mutate(memory, name)
            self.assertEqual(len(edits), 1)
            self.assertEqual(memory.files[path], new.encode())
            inverse(memory, edits, {path: old.encode()})

    def test_empty_trace_is_framed_without_claiming_actual_capture(self):
        commands = 'H empty genuine\nX\n'
        raw = b'O 0 H 0 0 0\nO 1 X 0 0 0\nZ 2\n'
        self.assertEqual(len(frames(raw, commands)), 2)
        for changed in (raw[:-4], raw + b'Z 2\n', raw.replace(b'O 1', b'O 2'), raw.replace(b'Z 2', b'Z 1')):
            with self.assertRaises(ValueError):
                frames(changed, commands)

    def test_inert_generation_ledger_checks_ownership_and_allows_delayed_release_control(self):
        manifold = ['M', '0', '0', '1', '1', '0', '1', '00000000', '00000000', '0']
        rows = [
            [['E', '0', 'A+', '1'], ['E', '0', 'M+', '1', '0', '1'], ['O', '0', 'D', '2', '1', '1'],
             ['P', '0', '0', '1', '2', '0', '1', '1'], manifold],
            [['E', '1', 'U+', '0'], ['E', '1', 'U-', '0'], ['O', '1', 'S', '2', '0', '1'],
             ['M', '1', *manifold[2:]]],
            [['E', '2', 'M-', '1'], ['E', '2', 'A-', '1'], ['O', '2', 'X', '0', '0', '0']],
        ]
        self.assertEqual(validate_lifetimes(rows), {'algorithm_generations': 1, 'manifold_generations': 1})
        for mutation in ['missing-manifold-free', 'duplicate-generation', 'wrong-owner', 'open-update']:
            changed = copy.deepcopy(rows)
            if mutation == 'missing-manifold-free':
                changed[2].pop(0)
            elif mutation == 'duplicate-generation':
                changed[0].insert(1, ['E', '0', 'A+', '1'])
            elif mutation == 'wrong-owner':
                changed[0][-1][4] = '2'
            else:
                changed[1].pop(1)
            with self.assertRaises(ValueError):
                validate_lifetimes(changed)


if __name__ == '__main__':
    unittest.main()
