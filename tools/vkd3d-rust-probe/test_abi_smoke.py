import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import abi_smoke


class AbiSmokeTests(unittest.TestCase):
    def test_failed_rust_build_aborts_before_link_or_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []

            def execute(command, log, **kwargs):
                name = log.stem
                calls.append(name)
                log.write_text('fixture\n')
                if name == 'transpile':
                    (root / 'rust').mkdir()
                    (root / 'rust/translated.rs').write_text('extern "win64" fn f() {} extern "C" fn g() {}')
                return {'exit_code': 1 if name == 'rust-build' else 0}

            with patch.object(sys, 'argv', ['abi_smoke.py', '--c2rust', str(root / 'c2rust'),
                                            '--artifacts', str(root)]):
                with patch.object(abi_smoke, 'run', side_effect=execute):
                    self.assertEqual(abi_smoke.main(), 1)
            result = json.loads((root / 'result.json').read_text())
            self.assertEqual(result['status'], 'failure')
            self.assertEqual(calls, ['clang-ast', 'transpile', 'rust-build'])


if __name__ == '__main__':
    unittest.main()
