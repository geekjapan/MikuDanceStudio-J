import difflib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import mutations


class BuildReached(Exception):
    pass


class MutationTests(unittest.TestCase):
    def test_actual_sources_reach_build_with_intended_mutation(self):
        changes = {
            'recreate-algorithm': [('        if !needs_collision(input_bodies, objects) {', '        if let Some(old) = pair_algorithm.take() { self.release(old); }\n        if !needs_collision(input_bodies, objects) {')],
            'inactive-clear': [('        if !needs_collision(input_bodies, objects) {\n            return;', '        if !needs_collision(input_bodies, objects) {\n            if let Some(key) = *pair_algorithm { if let Some(i) = self.algorithms[key.0 as usize].as_ref().unwrap().manifold_index { self.manifolds[i].manifold.clear_contacts(); } }\n            return;')],
            'both-body-exclusions': [('    (objects[a].activation.is_active() || objects[b].activation.is_active())', '    !objects[b].constraints.iter().any(|c|c.bodies.contains(&a))\n        && (objects[a].activation.is_active() || objects[b].activation.is_active())')],
            'plane-endpoint-reversal': [('            bodies,\n            manifold:', '            bodies: [a, b],\n            manifold:')],
            'stable-remove': [('            self.manifolds.swap_remove(index);\n            if let Some(moved) = self.manifolds.get(index) {\n                self.algorithms[moved.owner.0 as usize]\n                    .as_mut()\n                    .unwrap()\n                    .manifold_index = Some(index);\n            }', '            self.manifolds.remove(index);\n            for j in index..self.manifolds.len() { self.algorithms[self.manifolds[j].owner.0 as usize].as_mut().unwrap().manifold_index = Some(j); }')],
            'omit-moved-owner-update': [('            if let Some(moved) = self.manifolds.get(index) {', '            if let Some(moved) = self.manifolds.get(usize::MAX) {')],
            'drop-empty-manifolds': [('        algorithm.manifold_index = Some(self.manifolds.len());', '        if objects[a].contact.world.origin.sub(objects[b].contact.world.origin).length2() > 100.0 { return; }\n        algorithm.manifold_index = Some(self.manifolds.len());')],
            'per-pair-simplex': [('&mut self.simplex,', '&mut VoronoiSimplexSolver::default(),')],
            'delayed-release': [('        let index = self.algorithms[key.0 as usize]', '        return;\n        let index = self.algorithms[key.0 as usize]')],
            'no-response-generation': [('dispatcher.near_pair(key,proxies.map(|p|p.0 as usize),&views);', 'if proxies.iter().all(|p|objects[p.0 as usize].contact_response) { dispatcher.near_pair(key,proxies.map(|p|p.0 as usize),&views); }')],
            'contact-clone-copyback': [('let mut views=dispatcher.manifolds_mut().iter_mut().map(DispatcherManifold::contact_view).collect::<Vec<_>>();', 'let mut copied=dispatcher.manifolds().iter().map(|m|m.manifold.contacts().to_vec()).collect::<Vec<_>>(); let mut views=dispatcher.manifolds().iter().zip(copied.iter_mut()).map(|(m,points)|core::contact_solver::ContactManifold { bodies:m.bodies,points,processing_threshold:m.processing_threshold }).collect::<Vec<_>>();'), ('                drop(views);', '                drop(views);\n                for (m,points) in dispatcher.manifolds_mut().iter_mut().zip(copied) { m.manifold.contacts_mut().copy_from_slice(&points); }')],
        }
        self.assertEqual(set(changes), set(mutations.MUTATIONS))
        for name, replacements in changes.items():
            with self.subTest(mutation=name), tempfile.TemporaryDirectory() as temporary:
                out = Path(temporary)
                (out / 'inputs.tsv').write_bytes(b'')
                relative = Path('tools/bullet-rust-dispatcher-check/runner.rs' if name in ['no-response-generation', 'contact-clone-copyback'] else 'rust/crates/mds-bullet/src/core/dispatcher.rs')
                original = (mutations.ROOT / relative).read_text()
                expected = original
                for anchor, replacement in replacements:
                    self.assertEqual(expected.count(anchor), 1)
                    expected = expected.replace(anchor, replacement)
                self.assertNotEqual(expected, original)

                def run(command, **kwargs):
                    if command[0] == 'rustup':
                        raise BuildReached()
                    return subprocess.CompletedProcess(command, 0, b'', b'')

                with patch.object(sys, 'argv', ['mutations.py', '--out-dir', str(out), '--capture-dir', str(out), '--only', name]), patch.object(mutations.subprocess, 'run', side_effect=run), patch.object(mutations, 'validate'), patch.object(mutations, 'instrument_rust', side_effect=lambda source: source):
                    with self.assertRaises(BuildReached):
                        mutations.main()
                folder = out / name
                self.assertEqual((folder / 'generated-sources' / relative).read_text(), expected)
                self.assertEqual((folder / 'mutation.diff').read_text(), ''.join(difflib.unified_diff(original.splitlines(True), expected.splitlines(True))))


if __name__ == '__main__': unittest.main()
