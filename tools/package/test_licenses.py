#!/usr/bin/env python3
"""Missing packaging inputs must leave the previous generated licenses intact."""

import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("package_licenses", Path(__file__).with_name("licenses.py"))
licenses = importlib.util.module_from_spec(spec)
spec.loader.exec_module(licenses)


class LicenseGeneration(unittest.TestCase):
    def test_failure_preserves_generated_files(self):
        for failure in ("vkd3d", "rust_std"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "licenses"
                out.mkdir()
                (out / "mingw-runtime").mkdir()
                for name in licenses.GENERATED:
                    (out / name).write_bytes(b"previous license\n")
                before = {p.relative_to(out): p.read_bytes() for p in out.rglob("*") if p.is_file()}
                with patch.object(licenses, "OUT", out), patch.object(licenses, "graph", return_value=[]), \
                        patch.object(licenses, "vkd3d"), patch.object(licenses, "rust_std"), \
                        patch.object(licenses, failure, side_effect=SystemExit("missing input")), \
                        patch("sys.argv", ["licenses.py"]):
                    with self.assertRaisesRegex(SystemExit, "missing input"):
                        licenses.main()
                after = {p.relative_to(out): p.read_bytes() for p in out.rglob("*") if p.is_file()}
                self.assertEqual(before, after)

    def test_success_replaces_generated_files_and_keeps_cached_notices(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "licenses"
            (out / "mingw-runtime").mkdir(parents=True)
            (out / "mingw-runtime/COPYING").write_text("runtime notice")
            (out / "fetched/dispatch-0.2.0").mkdir(parents=True)
            (out / "fetched/dispatch-0.2.0/NOTE").write_text("evidence gap")
            (out / "FORK.md").write_text("old version")
            with patch.object(licenses, "OUT", out), patch.object(licenses, "graph", return_value=[]), \
                    patch.object(licenses, "vkd3d", side_effect=lambda p: (p / "vkd3d").mkdir()), \
                    patch.object(licenses, "rust_std", side_effect=lambda p: (p / "rust").mkdir()), \
                    patch("sys.argv", ["licenses.py"]):
                licenses.main()
            self.assertTrue(all((out / name).exists() for name in licenses.GENERATED))
            self.assertEqual((out / "FORK.md").read_bytes(), (licenses.REPO / "docs/FORK.md").read_bytes())
            self.assertEqual((out / "mingw-runtime/COPYING").read_text(), "runtime notice")
            self.assertEqual((out / "fetched/dispatch-0.2.0/NOTE").read_text(), "evidence gap")
            self.assertEqual(list(Path(tmp).glob(".licenses-*")), [])

    def test_missing_rust_docs_has_setup_instruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(licenses.subprocess, "run", return_value=SimpleNamespace(stdout=tmp)):
                with self.assertRaisesRegex(SystemExit, "rustup component add rust-docs"):
                    licenses.rust_std(Path(tmp) / "output")


if __name__ == "__main__":
    unittest.main()
