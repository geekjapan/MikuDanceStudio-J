#!/usr/bin/env python3
"""Persistent slot schema v1: real World scheduling, safe live observations, Rust replay."""
import argparse
import difflib
import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    src = ROOT / 'recipes/bullet275/bullet-src/src'
    shim = ROOT / 'rust/crates/mds-bullet-sys/shim'
    env = {k:v for k,v in os.environ.items() if not k.startswith('OPENMMD_DUMP_')}
    commands = []
    status = {'schema':'persistent-solver-v1','status':'FAIL','limit':'Measured native compatibility; retained native object lifetime is not proven. Collision generation remains native input.'}
    sources = sorted(p for folder in ['LinearMath','BulletCollision','BulletDynamics'] for p in (src/folder).rglob('*.cpp'))
    rust_sources = list((ROOT/'rust/crates/mds-bullet/src/core').glob('*.rs'))
    frozen = [p for folder in ['solver_data','contact_solver_data','islands_data'] for p in (ROOT/'rust/crates/mds-bullet/tests'/folder).glob('*') if p.is_file()]
    paths = [*sources,*src.rglob('*.h'),*shim.rglob('*.h'),*rust_sources,*HERE.glob('*.*'),ROOT/'rust/crates/mds-bullet/tests/pure_bullet/persistent_solver.rs',ROOT/'rust/crates/mds-crtmath/src/lib.rs']
    def hashes(paths): return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before = hashes(paths)
    fixtures = hashes(frozen)
    (out/'source-sha256.json').write_text(json.dumps(before,indent=2)+'\n')
    (out/'frozen-fixture-sha256.json').write_text(json.dumps(fixtures,indent=2)+'\n')
    def run(command,label):
        command=list(map(str,command)); commands.append(command)
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        p=subprocess.run(command,cwd=ROOT/'rust',env=env,capture_output=True,timeout=240)
        (out/(label+'.stdout')).write_bytes(p.stdout);(out/(label+'.stderr')).write_bytes(p.stderr)
        if p.returncode: raise RuntimeError(f'{label} returned {p.returncode}: {p.stderr.decode(errors="replace")[-4000:]}')
        return p.stdout
    try:
        run(['rustup','run','1.95.0','rustc','-Vv'],'rust-version')
        compiler=os.environ.get('CXX','cl' if os.name=='nt' else 'clang++')
        if os.name!='nt':run([compiler,'--version'],'compiler')
        crt=out/('mds_crtmath.lib' if os.name=='nt' else 'libmds_crtmath.a')
        run(['rustup','run','1.95.0','rustc','--edition=2021','--crate-name','mds_crtmath','--crate-type','rlib,staticlib','--print','native-static-libs','-O',ROOT/'rust/crates/mds-crtmath/src/lib.rs','--out-dir',out],'crt')
        solver=src/'BulletDynamics/ConstraintSolver/btSequentialImpulseConstraintSolver.cpp'
        original=solver.read_text()
        anchor='\tsolveGroupCacheFriendlyIterations(bodies, numBodies, manifoldPtr,  numManifolds,constraints, numConstraints,infoGlobal,debugDrawer, stackAlloc);'
        hook='''
    fprintf(stderr,"S %d %d %d",m_tmpSolverBodyPool.size(),m_tmpSolverBodyPool.capacity(),m_tmpSolverContactConstraintPool.size());
    for(int pi=0;pi<m_tmpSolverContactConstraintPool.size();++pi) fprintf(stderr," %d %d",m_tmpSolverContactConstraintPool[pi].m_solverBodyIdA,m_tmpSolverContactConstraintPool[pi].m_solverBodyIdB);
    for(int pi=0;pi<m_tmpSolverBodyPool.size();++pi) {
        const btRigidBody* b=m_tmpSolverBodyPool[pi].m_originalBody;
        fprintf(stderr," %d",b?*static_cast<int*>(b->getUserPointer()):-1);
    }
    fprintf(stderr,"\\n");
'''
        assert original.count(anchor)==1
        observed=original.replace(anchor,hook+anchor)
        setup='\tBT_PROFILE("solveGroupCacheFriendlySetup");'
        assert observed.count(setup)==1
        observed=observed.replace(setup,setup+'\n    fprintf(stderr,"BPOOL %d %d\\n",m_tmpSolverBodyPool.size(),m_tmpSolverBodyPool.capacity());')
        altered=out/solver.name;altered.write_text(observed)
        (out/'observer.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True),observed.splitlines(True))))
        objects=[]
        if os.name=='nt':
            flags=['/nologo','/std:c++17','/O2','/MD','/EHsc','/fp:precise','/W0','/DBT_NO_PROFILE=1',f'/I{src}',f'/I{shim}',f'/I{solver.parent}',f'/FI{shim / "det_math.h"}']
        else:
            flags=['-std=c++17','-O2','-ffp-contract=off','-fno-fast-math','-fdeclspec','-w','-DBT_NO_PROFILE=1','-I',shim/'sse_emu','-I',src,'-I',shim,'-I',solver.parent,'-include',shim/'det_math.h']
        for i,p in enumerate([HERE/'oracle.cpp',*[p for p in sources if p!=solver]]):
            obj=out/(f'base-{i}.obj' if os.name=='nt' else f'base-{i}.o')
            run([compiler,*flags,'/c',p,f'/Fo{obj}'] if os.name=='nt' else [compiler,*flags,'-c',p,'-o',obj],f'compile-{i}')
            objects.append(obj)
        binaries=[]
        for label,p in [('original',solver),('observed',altered)]:
            exe=out/(label+'.exe' if os.name=='nt' else label)
            if os.name=='nt':
                # rustc records the platform native static libraries in the staticlib receipt.
                libs=(out/'crt.stderr').read_text().split('native-static-libs:')[-1].splitlines()[0].split()
                command=[compiler,*flags,p,*objects,crt,f'/Fe:{exe}',f'/Fo:{out / (label+".obj")}', '/link','/OPT:REF',*libs]
            else:
                command=[compiler,*flags,p,*objects,crt,'-o',exe]
                command+=['-Wl,-dead_strip'] if platform.system()=='Darwin' else ['-Wl,--gc-sections','-ldl','-lpthread','-lm']
            run(command,'link-'+label);binaries.append(exe)
        run(['rustup','run','1.95.0','rustc','--edition=2021','-O',HERE/'runner.rs','--extern',f'mds_crtmath={out / "libmds_crtmath.rlib"}','-o',out/('rust-replay.exe' if os.name=='nt' else 'rust-replay')],'rust-build')
        run(['rustup','run','1.95.0','rustc','--edition=2021','--test','-O',HERE/'harness.rs','--extern',f'mds_crtmath={out / "libmds_crtmath.rlib"}','-o',out/('rust-tests.exe' if os.name=='nt' else 'rust-tests')],'test-build')
        run([out/('rust-tests.exe' if os.name=='nt' else 'rust-tests'),'persistent_solver'],'focused-tests')
        reports=[]
        for order in itertools.permutations('012'):
            for kind,count in [(0,2),(1,2),(2,2),(0,1),(1,1),(2,1)]:
                label=f'k{kind}-o{"".join(order)}-n{count}'
                replay=out/(label+'.input')
                baseline=run([binaries[0],kind,''.join(order),count,out/(label+'.original.input')],label+'-original')
                observed=run([binaries[1],kind,''.join(order),count,replay],label+'-observed')
                assert baseline==observed,'observer changed native World output'
                assert replay.read_bytes()==(out/(label+'.original.input')).read_bytes(),'observer changed incoming inputs'
                actual=run([out/('rust-replay.exe' if os.name=='nt' else 'rust-replay'),replay],label+'-rust').decode().splitlines()
                expected=[line for line in (out/(label+'-observed.stderr')).read_text().splitlines() if line.startswith(('G ','S ','BPOOL '))]
                native_states=[]
                for line in observed.decode().splitlines():
                    if line.startswith('state '):
                        x=line.split();native_states.append('V '+' '.join(x[1:3]+x[5:]))
                assert len(native_states)==2*(count+1),'missing native final state'
                rust_events=[line for line in actual if line.startswith(('G ','S ','BPOOL '))]
                rust_states=[line for line in actual if line.startswith('V ')]
                assert rust_events==expected,(label,'scheduling/live pool',rust_events,expected)
                assert sorted(rust_states)==sorted(native_states),(label,'final velocities',rust_states,native_states)
                reports.append({'scene':label,'steps':2,'groups':sum(x.startswith('G ') for x in actual),'status':'BIT_EXACT'})
        run(['python' if os.name=='nt' else 'python3',HERE/'mutations.py','--out-dir',out/'mutations','--crt-rlib',out/'libmds_crtmath.rlib','--native-capture',out],'mutations')
        status.update(status='PASS_RAW_BIT_COMPARISON',scenes=reports,host=platform.platform(),mixed_source_profile='PENDING_CURRENT_SOURCE_APPROVAL')
    finally:
        assert before==hashes(paths),'compiled source changed during capture'
        assert fixtures==hashes(frozen),'protected fixture changed'
        (out/'status.json').write_text(json.dumps(status,indent=2)+'\n')
    print(json.dumps(status,indent=2))


if __name__=='__main__':main()
