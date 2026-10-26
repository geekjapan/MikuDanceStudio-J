"""Cheap checks of the mutation gate; the workflow also runs the real verifier."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_selector_mutation as mutation

from check_selector_mutation import GUARD, remove_guard, require_detection


class SelectorMutationTest(unittest.TestCase):
    def test_changes_exactly_one_guard(self):
        self.assertEqual(remove_guard("before\n" + GUARD + "after\n"), "before\nafter\n")
        for source in ("no guard", GUARD + GUARD):
            with self.assertRaises(ValueError):
                remove_guard(source)

    def test_requires_the_real_failure(self):
        log = "VIOLATION: invalid memory access\n1. paste display key at frame 0"
        asan = "SUMMARY: AddressSanitizer: heap-buffer-overflow /repo/src/model/key_registrars.cpp:738:31 in RegisterDisplayKeyFromRecord"
        require_detection(1, log, asan)
        for status, stdout, stderr in (
            (0, log, asan), (2, log, asan), (-11, log, asan),
            (1, "compiler error", asan), (1, log, ""),
            (1, log, asan.replace("key_registrars.cpp", "unrelated.cpp")),
            (1, log, asan.replace("heap-buffer-overflow", "SEGV")),
            (1, log, asan.replace("RegisterDisplayKeyFromRecord", "UnrelatedFunction")),
        ):
            with self.assertRaises(ValueError):
                require_detection(status, stdout, stderr)

    def test_disposable_copy_preserves_checkout_on_success_and_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for directory in ("include", "src/model", "tools/keypool_check", "rust/crates/mds-math/src"):
                (root / directory).mkdir(parents=True)
            source = root / "src/model/key_registrars.cpp"
            source.write_text(GUARD)
            (root / "rust/crates/mds-math/src/estimate_table.rs").write_text("fixture")
            runner = root / "tools/keypool_check/run.sh"
            artifacts = Path(temporary) / "artifacts"
            for status in (1, 2):
                runner.write_text("""#!/bin/sh
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
if grep -q continue "$root/src/model/key_registrars.cpp"; then exit 3; fi
mkdir -p "$TMPDIR/keypool_check"
echo 'SUMMARY: AddressSanitizer: heap-buffer-overflow key_registrars.cpp:738 in RegisterDisplayKeyFromRecord' > "$TMPDIR/keypool_check/asan.log"
echo 'VIOLATION: paste display key at frame 0'
exit """ + str(status) + "\n")
                with patch.object(mutation, "__file__", str(root / "tools/keypool_check/check_selector_mutation.py")), patch(
                    "sys.argv", ["check_selector_mutation.py", str(artifacts)]
                ):
                    if status == 1:
                        mutation.main()
                    else:
                        with self.assertRaises(ValueError):
                            mutation.main()
                self.assertEqual(source.read_text(), GUARD)
                self.assertEqual((artifacts / "mutation-exit.txt").read_text(), f"{status}\n")


if __name__ == "__main__":
    unittest.main()
