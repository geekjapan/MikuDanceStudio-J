#!/usr/bin/env python3
"""Run compilable product mutations against complete captured dispatcher traces."""
import argparse
import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess
from trace import validate
from observe import instrument_rust, simplex_events
from check import generated_snapshot

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MUTATIONS = {
    'recreate-algorithm': ('        if !needs_collision(input_bodies, objects) {', '        if let Some(old) = pair_algorithm.take() { self.release(old); }\n        if !needs_collision(input_bodies, objects) {'),
    'inactive-clear': ('        if !needs_collision(input_bodies, objects) {\n            return;', '        if !needs_collision(input_bodies, objects) {\n            if let Some(key) = *pair_algorithm { if let Some(i) = self.algorithms[key.0 as usize].as_ref().unwrap().manifold_index { self.manifolds[i].manifold.clear_contacts(); } }\n            return;'),
    'both-body-exclusions': ('    (objects[a].activation.is_active() || objects[b].activation.is_active())', '    !objects[b].constraints.iter().any(|c|c.bodies.contains(&a))\n        && (objects[a].activation.is_active() || objects[b].activation.is_active())'),
    'plane-endpoint-reversal': ('            bodies,\n            manifold:', '            bodies: [a, b],\n            manifold:'),
    'stable-remove': ('self.manifolds.swap_remove(index)', 'self.manifolds.remove(index)'),
    'omit-moved-owner-update': ('            if let Some(moved) = self.manifolds.get(index) {', '            if let Some(moved) = self.manifolds.get(usize::MAX) {'),
    'drop-empty-manifolds': ('        algorithm.manifold_index = Some(self.manifolds.len());', '        if objects[a].contact.world.origin.sub(objects[b].contact.world.origin).length2() > 100.0 { return; }\n        algorithm.manifold_index = Some(self.manifolds.len());'),
    'per-pair-simplex': ('&mut self.simplex,', '&mut VoronoiSimplexSolver::default(),'),
}
MUTATIONS['stable-remove'] = (
    '            self.manifolds.swap_remove(index);\n            if let Some(moved) = self.manifolds.get(index) {\n                self.algorithms[moved.owner.0 as usize]\n                    .as_mut()\n                    .unwrap()\n                    .manifold_index = Some(index);\n            }',
    '            self.manifolds.remove(index);\n            for j in index..self.manifolds.len() { self.algorithms[self.manifolds[j].owner.0 as usize].as_mut().unwrap().manifold_index = Some(j); }',
)
MUTATIONS['delayed-release'] = (
    '        let index = self.algorithms[key.0 as usize]',
    '        return;\n        let index = self.algorithms[key.0 as usize]',
)
MUTATIONS['no-response-generation'] = ('RUNNER', 'response')
MUTATIONS['contact-clone-copyback'] = ('RUNNER', 'clone')


def targeted_inputs(name, ordinary):
    if name not in ['omit-moved-owner-update', 'delayed-release']:
        return ordinary
    from cases import word
    lines = ['F']
    for i in range(5):
        lines.append(' '.join(map(str, ['N', i, 0, word(i * .1), word(0), word(0), 1, 0, word(1e18)])))
    lines += ['P 0 1', 'P 0 2', 'P 0 3', 'D', 'R 0 2', 'P 0 4', 'A 0 2', 'A 3 2', 'D', 'A 0 1', 'A 3 1', 'T 3 ' + ' '.join(map(word, [1.4, 0, 0])), 'D']
    return ('\n'.join(lines) + '\n').encode()



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--capture-dir', type=Path, required=True)
    parser.add_argument('--only', action='append')
    args = parser.parse_args()
    out = args.out_dir.resolve();out.mkdir(parents=True, exist_ok=True)
    capture = args.capture_dir.resolve()
    ordinary_inputs = (capture / 'inputs.tsv').read_bytes()
    results = []
    for name in args.only or list(MUTATIONS):
        folder = out / name
        folder.mkdir(parents=True, exist_ok=True)
        inputs = targeted_inputs(name, ordinary_inputs)
        native = capture / ('original.exe' if os.name == 'nt' else 'original')
        baseline = subprocess.run([str(native)], input=inputs, capture_output=True, timeout=120)
        assert baseline.returncode == 0, 'native mutation baseline failed'
        expected = baseline.stdout;validate(expected, inputs)
        observed_native = capture / ('observed.exe' if os.name == 'nt' else 'observed')
        native_observation = subprocess.run([str(observed_native)], input=inputs, capture_output=True, timeout=120)
        assert native_observation.returncode == 0 and native_observation.stdout == expected, 'native observer altered mutation baseline'
        expected_simplex = simplex_events(native_observation.stderr)
        (folder / 'inputs.tsv').write_bytes(inputs);(folder / 'native.stdout').write_bytes(expected);(folder / 'native.stderr').write_bytes(baseline.stderr);(folder / 'native-observed.stderr').write_bytes(native_observation.stderr)
        generated_root = folder / 'generated-sources'
        generated_root.mkdir(exist_ok=True)
        assert not any(generated_root.iterdir()), 'mutation source directory must be empty'
        core = generated_root / 'rust/crates/mds-bullet/src/core'
        shutil.copytree(ROOT / 'rust/crates/mds-bullet/src/core', core, dirs_exist_ok=True)
        runner = generated_root / 'tools/bullet-rust-dispatcher-check/runner.rs';runner.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / 'runner.rs', runner)
        source = core / 'dispatcher.rs';original = source.read_text();anchor, replacement = MUTATIONS[name]
        if anchor == 'RUNNER':
            source = runner;original = runner.read_text()
            if replacement == 'response':
                anchor = 'dispatcher.near_pair(key,proxies.map(|p|p.0 as usize),&views);'
                replacement = 'if proxies.iter().all(|p|objects[p.0 as usize].contact_response) { dispatcher.near_pair(key,proxies.map(|p|p.0 as usize),&views); }'
                assert original.count(anchor) == 1
                mutated = original.replace(anchor, replacement)
            else:
                anchor = 'let mut views=dispatcher.manifolds_mut().iter_mut().map(DispatcherManifold::contact_view).collect::<Vec<_>>();'
                replacement = 'let mut copied=dispatcher.manifolds().iter().map(|m|m.manifold.contacts().to_vec()).collect::<Vec<_>>(); let mut views=dispatcher.manifolds().iter().zip(copied.iter_mut()).map(|(m,points)|core::contact_solver::ContactManifold { bodies:m.bodies,points,processing_threshold:m.processing_threshold }).collect::<Vec<_>>();'
                assert original.count(anchor) == 1
                mutated = original.replace(anchor, replacement)
                anchor = '                drop(views);'
                assert mutated.count(anchor) == 1
                mutated = mutated.replace(anchor, anchor + '\n                for (m,points) in dispatcher.manifolds_mut().iter_mut().zip(copied) { m.manifold.contacts_mut().copy_from_slice(&points); }')
        else:
            if original.count(anchor) != 1:
                results.append({'mutation': name, 'status': 'INVALID_MUTATOR', 'anchor_count': original.count(anchor)});continue
            mutated = original.replace(anchor, replacement)
        source.write_text(mutated)
        (folder / 'mutation.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True), mutated.splitlines(True))))
        dispatch_source = core / 'dispatcher.rs'
        unobserved = dispatch_source.read_text();observed = instrument_rust(unobserved);dispatch_source.write_text(observed)
        (folder / 'observer.diff').write_text(''.join(difflib.unified_diff(unobserved.splitlines(True), observed.splitlines(True))))
        exe = folder / ('mutant.exe' if os.name == 'nt' else 'mutant')
        command = ['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '-O', str(runner), '--extern', f'mds_crtmath={capture / "libmds_crtmath.rlib"}', '-o', str(exe)]
        (folder / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
        def sources():
            return generated_snapshot(generated_root)
        before = sources()
        (folder / 'producer-start.json').write_text(json.dumps(before, indent=2) + '\n')
        def guarded_run(argv, label, inputs=None):
            assert before == sources(), 'mutation compiled source membership or raw bytes changed before command'
            (folder / (label + '-command.json')).write_text(json.dumps(argv, indent=2) + '\n')
            try:
                return subprocess.run(argv, cwd=ROOT / 'rust', input=inputs, capture_output=True, timeout=120)
            finally:
                after = sources()
                (folder / (label + '-producer-finally.json')).write_text(json.dumps(after, indent=2) + '\n')
                assert before == after, 'mutation compiled source membership or raw bytes changed'
        built = guarded_run(command, 'build')
        (folder / 'build.stdout').write_bytes(built.stdout);(folder / 'build.stderr').write_bytes(built.stderr)
        if built.returncode:
            results.append({'mutation': name, 'status': 'COMPILE_FAILURE_NOT_DETECTION'});continue
        result = guarded_run([str(exe)], 'run', inputs)
        (folder / 'actual.stdout').write_bytes(result.stdout);(folder / 'actual.stderr').write_bytes(result.stderr)
        if result.returncode:
            results.append({'mutation': name, 'status': 'RUNTIME_FAILURE_NOT_DETECTION'});continue
        try: validate(result.stdout, inputs)
        except (AssertionError, StopIteration, UnicodeError, ValueError):
            results.append({'mutation': name, 'status': 'INVALID_TRACE_NOT_DETECTION'});continue
        difference = ''.join(difflib.unified_diff(expected.decode().splitlines(True), result.stdout.decode().splitlines(True)))
        actual_simplex = simplex_events(result.stderr)
        simplex_difference = ''.join(difflib.unified_diff([line + '\n' for line in expected_simplex], [line + '\n' for line in actual_simplex]))
        (folder / 'simplex.diff').write_text(simplex_difference)
        (folder / 'semantic.diff').write_text(difference)
        difference += simplex_difference
        after = sources()
        (folder / 'producer-end.json').write_text(json.dumps(after, indent=2) + '\n')
        assert before == after, 'mutation compiled source membership or raw bytes changed after capture'
        results.append({'mutation': name, 'status': 'SEMANTIC_MISMATCH' if difference else 'UNRESOLVED_UNOBSERVABLE'})
    (out / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    assert results and all(r['status'] == 'SEMANTIC_MISMATCH' for r in results), results


if __name__ == '__main__': main()
