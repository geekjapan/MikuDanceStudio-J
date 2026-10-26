"""Compile wrong persistent workspace semantics and require behavioral rejection."""
import argparse
import json
from pathlib import Path
import re
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
CORE=ROOT/'rust/crates/mds-bullet/src/core'


def once(s,old,new):
    assert s.count(old)==1,(old,s.count(old))
    return s.replace(old,new)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out-dir',type=Path,required=True)
    p.add_argument('--crt-rlib',type=Path,required=True)
    p.add_argument('--native-capture',type=Path,required=True)
    args=p.parse_args();out=args.out_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    solver=(CORE/'solver.rs').read_text();contact=(CORE/'contact_solver.rs').read_text()
    runner=(HERE/'runner.rs').read_text()
    variants={
        'retained-zeroing':(once(solver,'self.workspace.live_len = 0;','self.workspace.live_len = 0; for b in &mut self.workspace.slots { b.delta_linear=Vec3::ZERO; b.delta_angular=Vec3::ZERO; }'),contact),
        'retired-writeback':(once(solver,'for solver_body in self.bodies.live_entries() {','for solver_body in &self.bodies.workspace.slots {'),contact),
        'append-keeps-old-slot':(once(solver,'self.slots[index] = body;','let _ = body;'),contact),
        'capacity-plus-one':(once(solver,'else { 2 * index }','else { index + 1 }'),contact),
        'live-capacity-conflation':(once(solver,'&self.slots[..self.live_len]','&self.slots[..]'),contact),
        'per-group-companion-reset':(once(solver,'assert_eq!(workspace.live_len, 0, "unfinished solver group");','assert_eq!(workspace.live_len, 0, "unfinished solver group"); for o in objects.iter_mut() {o.companion_id=-1;}'),contact),
        'simultaneous-alias-write':(once(solver,'SolverMode::Simd => bodies[ib].delta_linear.sub(linear_b.scale(impulse)),','SolverMode::Simd => b.delta_linear.sub(linear_b.scale(impulse)),'),contact),
        'wrong-endpoint-mass':(solver,once(contact,'let original = manifold.bodies[side];','let original = pool.slot(id).unwrap().original.unwrap_or(manifold.bodies[side]);')),
        'reorder-global-manifolds':(solver,once(contact,'for &mi in selection {','for &mi in selection.iter().rev() {')),
        'reorder-global-joints':(once(solver,'for &index in selection.joints {','for &index in selection.joints.iter().rev() {'),contact),
    }
    reports=[]
    def execute(command,label):
        p=subprocess.run(list(map(str,command)),capture_output=True,cwd=ROOT/'rust')
        (directory/(label+'.stdout')).write_bytes(p.stdout);(directory/(label+'.stderr')).write_bytes(p.stderr)
        return p
    for name,(s,c) in variants.items():
        directory=out/name;directory.mkdir(exist_ok=True)
        (directory/'solver.rs').write_text(s);(directory/'contact_solver.rs').write_text(c)
        mod=(CORE/'mod.rs').read_text()
        mod=re.sub(r'pub mod (\w+);',lambda m:'#[path = '+json.dumps((directory/(m[1]+'.rs') if m[1] in ['solver','contact_solver'] else CORE/(m[1]+'.rs')).as_posix())+']\npub mod '+m[1]+';',mod)
        (directory/'core.rs').write_text(mod)
        harness='#![allow(dead_code)]\n#[path='+json.dumps((directory/'core.rs').as_posix())+'] mod core;\n#[path='+json.dumps((ROOT/'rust/crates/mds-bullet/tests/pure_bullet/persistent_solver.rs').as_posix())+'] mod persistent_solver;\n'
        (directory/'harness.rs').write_text(harness)
        binary=directory/('test.exe' if __import__('os').name=='nt' else 'test')
        compiled=execute(['rustup','run','1.95.0','rustc','--edition=2021','--test','-O',directory/'harness.rs','--extern',f'mds_crtmath={args.crt_rlib.resolve()}','-o',binary],'compile')
        assert compiled.returncode==0,(name,'must compile',compiled.stderr.decode())
        actual=execute([binary,'persistent_solver'],'test')
        assert actual.returncode!=0 and b'test result: FAILED' in actual.stdout,(name,'survived or crashed')
        reports.append({'mutation':name,'compiled':True,'behavior_rejected':True})
    # Step clearing lives in the caller; exercise its compiled real scheduling replay.
    directory=out/'step-workspace-clearing';directory.mkdir(exist_ok=True)
    core_path=json.dumps((CORE/'mod.rs').as_posix())
    mutated=re.sub(r'#\[path = "[^"]+/core/mod.rs"\]',f'#[path = {core_path}]',runner)
    mutated=once(mutated,'for step in 0..2 {','for step in 0..2 { workspace=SolverWorkspace::default();')
    (directory/'runner.rs').write_text(mutated)
    binary=directory/('runner.exe' if __import__('os').name=='nt' else 'runner')
    assert execute(['rustup','run','1.95.0','rustc','--edition=2021','-O',directory/'runner.rs','--extern',f'mds_crtmath={args.crt_rlib.resolve()}','-o',binary],'compile').returncode==0
    incoming=args.native_capture/'k0-o012-n2.input'
    actual=execute([binary,incoming],'test')
    baseline=(args.native_capture/'k0-o012-n2-rust.stdout').read_bytes()
    assert actual.returncode==0 and actual.stdout!=baseline,'step clearing must change defined capacity observation'
    reports.append({'mutation':'step-workspace-clearing','compiled':True,'behavior_rejected':True})
    (out/'results.json').write_text(json.dumps(reports,indent=2)+'\n')
    print(json.dumps(reports,indent=2))


if __name__=='__main__':main()
