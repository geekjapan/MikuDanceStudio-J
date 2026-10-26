import json
from pathlib import Path, PureWindowsPath
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import check
from integrity import producer_paths
from mutations import check_capture_syntax, relocate_runner, rust_path, run_mutations, check_stdout_syntax


class IntegrityTests(unittest.TestCase):
    def test_compiled_closure_includes_support_core_crt_and_sse(self):
        paths = {p.relative_to(check.ROOT).as_posix() for p in producer_paths(check.ROOT)}
        for name in ['body', 'math', 'joint_rows', 'joint_coordinates', 'time', 'shape', 'gjk_epa', 'gjk_pair', 'simplex', 'box_box', 'contact', 'contact_solver', 'solver']:
            self.assertIn('rust/crates/mds-bullet/src/core/' + name + '.rs', paths)
        self.assertIn('tools/bullet-rust-contact-solver-check/support.rs', paths)
        self.assertIn('rust/crates/mds-bullet-sys/shim/sse_emu/emmintrin.h', paths)
        self.assertIn('rust/crates/mds-crtmath/src/trig.rs', paths)

    def test_every_exception_checks_integrity_and_records_failure(self):
        for change in [False, True]:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); here = root / 'tools/check'; here.mkdir(parents=True)
                producer = root / 'producer.rs'; producer.write_text('frozen')
                out = root / 'out'
                def fail(*args, **kwargs):
                    if change:producer.write_text('changed')
                    raise RuntimeError('unknown profile or compiler failure')
                with patch.object(check, 'ROOT', root), patch.object(check, 'HERE', here), patch('integrity.producer_paths', return_value=[producer]), patch.object(check.subprocess, 'run', side_effect=fail), patch('sys.argv', ['check.py', '--out-dir', str(out)]):
                    with self.assertRaises((RuntimeError, ValueError)):check.main()
                self.assertEqual(json.loads((out / 'status.json').read_text())['status'], 'FAIL')
                result = json.loads((out / 'integrity.json').read_text())
                self.assertEqual(result['status'], 'FAIL' if change else 'PASS')
                self.assertTrue((out / 'commands.json').is_file())

    def test_snapshot_failure_never_leaves_running_or_pass_status(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'out'
            with patch('integrity.producer_paths',side_effect=FileNotFoundError('missing source')), patch('sys.argv',['check.py','--out-dir',str(out)]):
                with self.assertRaisesRegex(ValueError,'snapshot incomplete'):check.main()
            self.assertEqual(json.loads((out/'status.json').read_text())['status'],'FAIL')
            self.assertEqual(json.loads((out/'integrity.json').read_text())['status'],'FAIL')

    def test_windows_module_paths_are_rust_literals(self):
        path = PureWindowsPath('C:/Users/runner name/日本語/solver.rs')
        literal = rust_path(path)
        self.assertEqual(literal, '"C:/Users/runner name/日本語/solver.rs"')
        self.assertNotIn('\\', literal)
        source = '#[path = "../../rust/crates/mds-bullet/src/core/solver.rs"]\npub mod solver;'
        self.assertIn('#[path = ' + literal + ']', relocate_runner(source, Path('/tmp'), path, path))

    def test_generated_module_path_compiles_with_pinned_rust(self):
        with tempfile.TemporaryDirectory(prefix='mixed modules ') as directory:
            out=Path(directory)
            module=out/'日本語 module.rs';module.write_text('pub fn value() -> u32 { 7 }',encoding='utf-8')
            runner=out/'runner.rs'
            runner.write_text('#[path = '+rust_path(module)+']\nmod sample;\nfn main() { assert_eq!(sample::value(),7); }',encoding='utf-8')
            subprocess.run(['rustup','run','1.95.0','rustc','--edition=2021','--emit=metadata','--crate-name','path_check',str(runner),'-o',str(out/'runner.rmeta')],check=True,capture_output=True)

    def test_malformed_capture_is_not_semantic_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.trace'
            for capture in ['', 'parser failed\n', '0\t0\t0\t-1\t-1\t00000001\n']:
                path.write_text(capture)
                with self.assertRaisesRegex(ValueError, 'malformed mutation capture'):check_capture_syntax(path)
            for output in [b'parser failed\n',b'',b'0\t0\tinvalid\n']:
                with self.assertRaisesRegex(ValueError,'malformed mutation stdout'):check_stdout_syntax(output,b'0\t0\t00000000\n')

    def test_compile_or_config_failure_is_not_a_caught_mutant(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory); inputs = out / 'inputs.tsv'
            from cases import corpus
            inputs.write_text(corpus())
            def failed_run(command):
                if command[0] == 'native':return b'baseline'
                raise subprocess.CalledProcessError(1, command)
            with self.assertRaises(subprocess.CalledProcessError):
                run_mutations(check.ROOT, check.HERE, out, inputs, failed_run, lambda *args:['compiler'], '', 'native')
            self.assertFalse((out / 'mutations.json').exists())


if __name__ == '__main__':unittest.main()
