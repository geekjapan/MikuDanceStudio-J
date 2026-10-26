#!/usr/bin/env python3
"""Every required island mutant must compile and fail the native behavioral comparison."""
import argparse
import json
import os
import re
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[2]

def change(text, old, new, count=1):
    compact = re.sub(r',(?=[})])', '', ''.join(old.split()))
    pattern = r'\s*'.join((r',?\s*' if c in '})' else '') + re.escape(c) for c in compact)
    result, found = re.subn(pattern, lambda _: new, text, count=count)
    assert found, old
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out-dir',type=Path,required=True)
    p.add_argument('--crt-rlib',type=Path,required=True)
    a=p.parse_args(); a.out_dir.mkdir(parents=True,exist_ok=True)
    source=(ROOT/'rust/crates/mds-bullet/src/core/islands.rs').read_text()
    test_source=(ROOT/'rust/crates/mds-bullet/tests/pure_bullet/islands.rs').read_text()
    mutations={
        'weighted-union':('let i = self.find(p);\n        let j = self.find(q);','let mut i = self.find(p);\n        let mut j = self.find(q);\n        if self.elements[i].size_or_body_index >= self.elements[j].size_or_body_index { std::mem::swap(&mut i, &mut j); }'),
        'reverse-union':('self.elements[i].id = j;\n            self.elements[j].size_or_body_index += self.elements[i].size_or_body_index;', 'self.elements[j].id = i;\n            self.elements[i].size_or_body_index += self.elements[j].size_or_body_index;'),
        'no-path-halving':('self.elements[x].id = self.elements[self.elements[x].id].id;', ''),
                'merge-guard-a':('objects[a].merges_simulation_islands() && objects[b].merges_simulation_islands()', 'objects[b].merges_simulation_islands()'),
        'merge-guard-b':('objects[a].merges_simulation_islands() && objects[b].merges_simulation_islands()', 'objects[a].merges_simulation_islands()'),
        'constraint-classification-a':('objects[a].classification == CollisionClassification::Dynamic\n                && objects[b].classification == CollisionClassification::Dynamic', 'objects[b].classification == CollisionClassification::Dynamic'),
        'constraint-classification-b':('objects[a].classification == CollisionClassification::Dynamic\n                && objects[b].classification == CollisionClassification::Dynamic', 'objects[a].classification == CollisionClassification::Dynamic'),
        'active-or-to-and':('objects[a].activation.is_active() || objects[b].activation.is_active()', 'objects[a].activation.is_active() && objects[b].activation.is_active()'),
        'omit-initial-tag':('object.island_tag = index as i32;', 'let _ = index;'),
        'omit-initial-companion':('object.companion_id = -1;', ''),
        'omit-hit-fraction':('object.hit_fraction = 1.0;', ''),
        'omit-stored-companion':('object.companion_id = -2;', ''),
        'omit-stored-tag':('object.island_tag = self.union_find.find(i) as i32;', 'let _ = i;'),
        'stable-sort':('quick_sort(&mut self.elements, |a, b| a.id < b.id);', 'self.elements.sort_by_key(|e| e.id);'),
        'rust-unstable-sort':('quick_sort(&mut self.elements, |a, b| a.id < b.id);', 'self.elements.sort_unstable_by_key(|e| e.id);'),
        'tie-break':('quick_sort(&mut self.elements, |a, b| a.id < b.id);','quick_sort(&mut self.elements, |a, b| (a.id,a.size_or_body_index) < (b.id,b.size_or_body_index));'),
        'awake-active-only':('ActivationState::Active | ActivationState::DisableDeactivation)', 'ActivationState::Active)'),
        'wants-is-awake':('ActivationState::Active | ActivationState::DisableDeactivation)', 'ActivationState::Active | ActivationState::DisableDeactivation | ActivationState::WantsDeactivation)'),
        'force-protected-sleep':('o.activation.set_activation_state(ActivationState::IslandSleeping);','o.activation.force_activation_state(ActivationState::IslandSleeping);'),
        'wake-after-response':('if objects[a].is_kinematic()', 'if objects[a].contact_response && objects[b].contact_response && objects[a].is_kinematic()'),
        'is-active-outer':('objects[a].activation.state != ActivationState::IslandSleeping || objects[b].activation.state != ActivationState::IslandSleeping','objects[a].activation.is_active() || objects[b].activation.is_active()'),
        'all-inactive-skip':('let mut sleeping = false;','let mut sleeping = true;'),
        'cursor-stale':('cursor = next;',''),
        'minmax-island-key':('if objects[a].island_tag >= 0 { objects[a].island_tag } else { objects[b].island_tag }', 'objects[a].island_tag.min(objects[b].island_tag)'),
        'unsorted-manifolds':('quick_sort(&mut self.ordered_manifolds, |a, b| { island_key(objects, manifolds[a].bodies) < island_key(objects, manifolds[b].bodies) });',''),
        'unsorted-constraints':('quick_sort(&mut sorted, |a, b| { island_key(objects, constraints[a].bodies) < island_key(objects, constraints[b].bodies) });',''),
        'prepare-after-all-solved':('callback(objects, SolverEvent::Prepare { num_bodies: objects.len(), num_manifolds: manifolds.len() });',''),
        'all-solved-before-build':('self.build_and_process(objects, manifolds, split, |objects, island| {','callback(objects, SolverEvent::AllSolved);\n        self.build_and_process(objects, manifolds, split, |objects, island| {'),
    }
    results={}
    environment={k:v for k,v in os.environ.items() if not k.startswith('MDS_ISLANDS_')}
    for name in [*mutations,'manifold-only-union','drop-empty','far-threshold','batch-128']:
        changed=source; tests=test_source
        if name in mutations:
            old,new=mutations[name]; changed=change(source,old,new)
            if name=='all-inactive-skip': changed=change(changed,'if !objects[body].activation.is_active() { sleeping = true; }','sleeping &= !objects[body].activation.is_active();')
            if name=='prepare-after-all-solved': changed=change(changed,'callback(objects, SolverEvent::AllSolved);','callback(objects, SolverEvent::AllSolved);\n        callback(objects, SolverEvent::Prepare { num_bodies: objects.len(), num_manifolds: manifolds.len() });')
        elif name == 'manifold-only-union':
            tests=change(tests,'let mut s=SimulationIslands::default();','let pairs: Vec<_> = manifolds.iter().map(|m|m.bodies).collect(); let mut s=SimulationIslands::default();')
        elif name in ('drop-empty','far-threshold'):
            # Mutate the compiled dispatcher endpoint adaptation, since the kernel deliberately borrows endpoints only.
            old='let _points=input.n(); let _distance=input.f(); IslandManifold{bodies}}).collect();'
            predicate = 'p != 0' if name=='drop-empty' else 'd <= 0.02'
            new='let p=input.n(); let d=input.f(); (IslandManifold{bodies},p,d)}).filter(|&(_,p,d)| { let _ = (p,d); '+predicate+' }).map(|(m,_,_)|m).collect();'
            tests=change(tests,old,new)
        else:
            changed=change(changed,'        self.build_and_process(objects, manifolds, split, |objects, island| {','        let mut bb=Vec::new(); let mut mm=Vec::new(); let mut cc=Vec::new();\n        self.build_and_process(objects, manifolds, split, |objects, island| {')
            old='callback(objects, SolverEvent::SolveGroup { island, constraints: &sorted[start..start + count] });'
            new='bb.extend_from_slice(island.bodies); mm.extend_from_slice(island.manifolds); cc.extend_from_slice(&sorted[start..start+count]);\n                if mm.len()+cc.len() >= 128 { callback(objects, SolverEvent::SolveGroup { island: IslandCallback { island_id: -1, bodies: &bb, manifolds: &mm }, constraints: &cc }); bb.clear(); mm.clear(); cc.clear(); }'
            changed=change(changed,old,new).replace('        callback(objects, SolverEvent::AllSolved);','        if !mm.is_empty() || !cc.is_empty() { callback(objects, SolverEvent::SolveGroup { island: IslandCallback { island_id: -1, bodies: &bb, manifolds: &mm }, constraints: &cc }); }\n        callback(objects, SolverEvent::AllSolved);')
        directory=a.out_dir/name; directory.mkdir(exist_ok=True); kernel=directory/'islands.rs';kernel.write_text(changed)
        # Keep include_str paths relative to the original test while isolating its compiled source.
        tests=tests.replace('"../islands_data/', '"'+str(ROOT/'rust/crates/mds-bullet/tests/islands_data')+'/')
        test=directory/'tests.rs';test.write_text(tests)
        math=ROOT/'rust/crates/mds-bullet/src/core/math.rs'; activation=ROOT/'rust/crates/mds-bullet/src/core/activation.rs'
        harness=directory/'harness.rs';harness.write_text(f'#![allow(dead_code,unused_variables,unused_mut)]\nmod core {{ #[path="{math}"] pub mod math; #[path="{activation}"] pub mod activation; #[path="{kernel}"] pub mod islands; }}\n#[path="{test}"] mod tests;\n')
        binary=directory/'test'
        subprocess.run(['rustup','run','1.95.0','rustc','--edition=2021','--test','-O',str(harness),'--extern',f'mds_crtmath={a.crt_rlib.resolve()}','-o',str(binary)],cwd=ROOT/'rust',check=True,env=environment)
        result=subprocess.run([binary],capture_output=True,text=True,env=environment,cwd=ROOT/'rust')
        log=result.stdout+result.stderr; (directory/'test.log').write_text(log)
        assert result.returncode != 0 and ('native snapshot' in log or 'left == right' in log),(name,'did not fail semantically',log)
        results[name]='compiled-semantic-failure'; print(name,results[name],flush=True)
    (a.out_dir/'results.json').write_text(json.dumps(results,indent=2)+'\n')
if __name__=='__main__': main()
