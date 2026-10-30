"""Check mutation module staging without compiling product sources."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import mutations


SOURCES = {
    'mod.rs': b'pub mod solver;\npub mod contact_solver;\npub mod contact;\n#[allow(dead_code)]\npub(crate) mod added_owner;\nmod private_owner;\n',
    'solver.rs': b'// original solver\n',
    'contact_solver.rs': b'// original contact solver\n',
    'contact.rs': b'#[cfg(test)]\n#[path = "../../tests/contact.rs"] mod tests;\n',
    'added_owner.rs': b'// newly declared restricted module\r\n// exact bytes\n',
    'private_owner.rs': b'// newly declared private module\r\n',
}
REPLACEMENTS = [
    {'solver': '// mutated solver\n', 'contact_solver': '// mutated contact solver\n'},
    {'solver': '// mutated reset\n'},
    {'added_owner': '// mutated restricted owner\n', 'private_owner': '// mutated private owner\n'},
]


class MutationStagingTests(unittest.TestCase):
    def test_all_module_visibilities_keep_paths_for_both_mutation_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = root/'original'
            core.mkdir()
            for name, contents in SOURCES.items():
                (core/name).write_bytes(contents)
            for index, replacements in enumerate(REPLACEMENTS):
                with self.subTest(replacements=replacements):
                    staged = root/str(index)
                    staged.mkdir()
                    with patch.object(mutations, 'CORE', core):
                        mutations.stage_core(staged, replacements)
                    for name, contents in SOURCES.items():
                        expected = replacements.get(Path(name).stem)
                        if expected is None:
                            self.assertFalse((staged/name).exists())
                        else:
                            self.assertEqual((staged/name).read_text(), expected)
                        self.assertEqual((core/name).read_bytes(), contents)
                    module = (staged/'core.rs').read_text()
                    declarations = {'solver': 'pub mod solver;',
                                    'contact_solver': 'pub mod contact_solver;',
                                    'contact': 'pub mod contact;',
                                    'added_owner': 'pub(crate) mod added_owner;',
                                    'private_owner': 'mod private_owner;'}
                    self.assertEqual(module.count('#[path = '), len(declarations))
                    for name, declaration in declarations.items():
                        target = (staged if name in replacements else core)/(name+'.rs')
                        self.assertIn('#[path = '+json.dumps(target.as_posix())+']\n'+declaration, module)
                    self.assertIn('#[allow(dead_code)]\n#[path = ', module)


if __name__ == '__main__':
    unittest.main()
