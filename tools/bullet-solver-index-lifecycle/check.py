#!/usr/bin/env python3
"""Bounded native Bullet companion-index lifecycle characterization (no Rust oracle)."""
import argparse
import difflib
import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SOLVER = Path('BulletDynamics/ConstraintSolver/btSequentialImpulseConstraintSolver.cpp')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def execute(command, output, env, timeout=120):
    try:
        p = subprocess.run(list(map(str, command)), capture_output=True, env=env, timeout=timeout, cwd=ROOT / 'rust')
        result = {'command': list(map(str, command)), 'returncode': p.returncode, 'timeout': False}
        stdout, stderr = p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        result = {'command': list(map(str, command)), 'returncode': None, 'timeout': True}
        stdout, stderr = e.stdout or b'', e.stderr or b''
    output.with_suffix('.stdout').write_bytes(stdout)
    output.with_suffix('.stderr').write_bytes(stderr)
    output.with_suffix('.result.json').write_text(json.dumps(result, indent=2)+'\n')
    return result, stdout, stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    out = args.out_dir.resolve(); out.mkdir(parents=True, exist_ok=True)
    src = ROOT / 'recipes/bullet275/bullet-src/src'
    shim = ROOT / 'rust/crates/mds-bullet-sys/shim'
    env = {k:v for k,v in os.environ.items() if not k.startswith('OPENMMD_DUMP_')}
    env['ASAN_OPTIONS'] = 'detect_leaks=0:halt_on_error=1'
    msvc = platform.system()=='Windows'
    compiler = os.environ.get('CXX', 'cl' if msvc else 'clang++')
    provenance = {'host': platform.platform(), 'machine': platform.machine(), 'source_hashes': {}}
    for label, command in [('compiler',[compiler] if msvc else [compiler,'--version']),('rustc',['rustup','run','1.95.0','rustc','-Vv']),('git',['git','rev-parse','HEAD'])]:
        r, stdout, stderr = execute(command,out / label,env)
        assert r['returncode']==0 or (label=='compiler' and msvc and r['returncode']==2), label
        provenance[label]=(stdout+stderr).decode(errors='replace')
    sources = sorted(p for directory in ['LinearMath','BulletCollision','BulletDynamics'] for p in (src/directory).rglob('*.cpp'))
    for p in sorted(src.rglob('*')):
        if p.is_file() and p.suffix in ('.h','.cpp'):
            provenance['source_hashes'][str(p.relative_to(src))]=digest(p.read_bytes())
    for p in [HERE/'driver.cpp',HERE/'check.py',shim/'det_math.h',ROOT/'rust/crates/mds-crtmath/src/lib.rs',*sorted((shim/'sse_emu').glob('*'))]:
        if p.is_file(): provenance['source_hashes'][str(p.relative_to(ROOT))]=digest(p.read_bytes())
    def checked(command, label):
        r, _, _ = execute(command,out/label,env)
        assert r['returncode']==0 and not r['timeout'], f'{label}: see saved terminal results'
    crt=out/('mds_crtmath.lib' if msvc else 'libmds_crtmath.a')
    checked(['rustup','run','1.95.0','rustc','--edition=2021','--crate-name','mds_crtmath','--crate-type','staticlib','-O',ROOT/'rust/crates/mds-crtmath/src/lib.rs','-o',crt], 'build-crt')
    flags=['-std=c++17','-O2','-ffp-contract=off','-fno-fast-math','-fdeclspec','-w','-DBT_NO_PROFILE=1','-fsanitize=address','-fno-omit-frame-pointer','-g','-I',str(shim/'sse_emu'),'-I',str(src),'-I',str(shim),'-include',str(shim/'det_math.h')]
    if msvc:
        flags=['/nologo','/std:c++17','/O2','/MD','/EHsc','/fp:precise','/W0','/DBT_NO_PROFILE=1','/fsanitize=address','/Zi','/Fd'+str(out/'native.pdb'),'/I'+str(src),'/I'+str(shim),'/FI'+str(shim/'det_math.h')]
    provenance['flags']=flags.copy()
    original=(src/SOLVER).read_text()
    # These additions only read initialized identities, indices, and solver fields.
    observed=re.sub(r'm_tmpSolverBodyPool\[([^\]]+)\]', r'lifecyclePoolAccess(m_tmpSolverBodyPool, \1, __LINE__)', original)
    helper='''
// Test-only observer. The final access is the original unchecked operator[].
static btSolverBody& lifecyclePoolAccess(btAlignedObjectArray<btSolverBody>& pool, int index, int line) {
    int owner=-3;
    if (index>=0 && index<pool.size()) {
        btRigidBody* b=pool[index].m_originalBody;
        owner=b ? *static_cast<int*>(b->getUserPointer()) : -1;
    }
    fprintf(stderr,"access line=%d index=%d size=%d capacity=%d owner=%d\\n",line,index,pool.size(),pool.capacity(),owner);
    return pool[index];
}
'''
    observed=observed.replace('// OpenMMD task#8:', '#include <cstdio>\n'+helper+'\n// OpenMMD task#8:',1)
    observed=observed.replace('int\tbtSequentialImpulseConstraintSolver::getOrInitSolverBody(btCollisionObject& body)\n{', '''int\tbtSequentialImpulseConstraintSolver::getOrInitSolverBody(btCollisionObject& body)
{
    fprintf(stderr,"lookup body=%d companion=%d size=%d capacity=%d\\n", *static_cast<int*>(body.getUserPointer()), body.getCompanionId(), m_tmpSolverBodyPool.size(), m_tmpSolverBodyPool.capacity());''')
    anchor='\tsolveGroupCacheFriendlyIterations(bodies, numBodies, manifoldPtr,  numManifolds,constraints, numConstraints,infoGlobal,debugDrawer, stackAlloc);'
    hook='''
    fprintf(stderr,"pool size=%d capacity=%d\\n",m_tmpSolverBodyPool.size(),m_tmpSolverBodyPool.capacity());
    for (int oi=0;oi<m_tmpSolverBodyPool.size();++oi) {
        const btSolverBody& ob=m_tmpSolverBodyPool[oi];
        fprintf(stderr,"entry index=%d body=%d\\n",oi,ob.m_originalBody ? *static_cast<int*>(ob.m_originalBody->getUserPointer()) : -1);
    }
'''
    assert observed!=original and observed.count(anchor)==1
    observed=observed.replace(anchor,hook+anchor)
    row_hook='''
    for (int ci=0;ci<m_tmpSolverContactConstraintPool.size();++ci) {
        const btSolverConstraint& cr=m_tmpSolverContactConstraintPool[ci];
        fprintf(stderr,"row index=%d a=%d b=%d\\n",ci,cr.m_solverBodyIdA,cr.m_solverBodyIdB);
    }
'''
    observed=observed.replace(anchor,row_hook+anchor)
    (out/'observed.cpp').write_text(observed)
    (out/'observer.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True), observed.splitlines(True),fromfile=str(SOLVER),tofile='observed.cpp')))
    reset=observed.replace('\tm_tmpSolverBodyPool.resize(0);', '\tfor (int ri=0;ri<m_tmpSolverBodyPool.size();++ri)\n\t\tif (m_tmpSolverBodyPool[ri].m_originalBody) m_tmpSolverBodyPool[ri].m_originalBody->setCompanionId(-1);\n\tm_tmpSolverBodyPool.resize(0);')
    assert reset!=observed
    reset_solver=out/'reset.cpp'; reset_solver.write_text(reset)
    (out/'reset-control.diff').write_text(''.join(difflib.unified_diff(observed.splitlines(True),reset.splitlines(True),fromfile='observed.cpp',tofile='diagnostic-reset.cpp')))
    # Copy includes resolve the native solver's private headers via its original directory.
    flags += ['/I'+str((src/SOLVER).parent)] if msvc else ['-I',str((src/SOLVER).parent)]
    def compile_source(p,obj,label):
        checked([compiler,*flags,'/c',p,'/Fo'+str(obj)] if msvc else [compiler,*flags,'-c',p,'-o',obj],label)
    objects=[]
    for i,p in enumerate([HERE/'driver.cpp',*[p for p in sources if p!=src/SOLVER]]):
        obj=out/f'base-{i}.o'; compile_source(p,obj,f'compile-{i}'); objects.append(obj)
    binaries={}
    for name,p in [('original',src/SOLVER),('observed',out/'observed.cpp'),('reset',reset_solver)]:
        obj=out/f'{name}.o'; compile_source(p,obj,f'compile-{name}')
        exe=out/(name+'.exe' if msvc else name)
        link=[compiler,'-fsanitize=address',*objects,obj,crt,'-o',exe]
        if msvc:
            link=[compiler,'/nologo','/MD','/fsanitize=address',*objects,obj,crt,'/Fe'+str(exe),'/link','/INCREMENTAL:NO','advapi32.lib','userenv.lib','ws2_32.lib','ntdll.lib','bcrypt.lib']
        elif platform.system()!='Darwin': link+=['-ldl','-lpthread','-lm']
        checked(link,f'link-{name}'); binaries[name]=exe
    cases=[{'kind':kind,'order':''.join(order),'count':count,'steps':2,'dt':'float32(1)/float32(60)' , 'position_y_u32':'3f666666', 'dt_u32':'3c888889','gravity':[0,-10,0],'platform_half_extents':[5,0.5,1],'sphere_radius':0.5,'positions':[[0,0,0],[-2,0.9,0],[2,0.9,0]],'iterations':10,'friction':0,'mass':[0 if kind==1 else 1,1,1],'activation':'DISABLE_DEACTIVATION','broadphase':'DBVT'} for kind in range(3) for order in itertools.permutations('012') for count in (1,2)]
    inputs=json.dumps(cases,sort_keys=True,indent=2)+'\n'; (out/'inputs.json').write_text(inputs); provenance['input_sha256']=digest(inputs.encode())
    (out/'provenance.json').write_text(json.dumps(provenance,sort_keys=True,indent=2)+'\n')
    summary=[]
    for case in cases:
        key=f"k{case['kind']}-o{case['order']}-n{case['count']}"
        results={}
        for name,exe in binaries.items():
            r,stdout,stderr=execute([exe,case['kind'],case['order'],case['count']],out/f'{key}-{name}',env,timeout=10)
            results[name]={'terminal':r,'stdout_sha256':digest(stdout),'stdout':stdout.decode(),'stderr':stderr.decode(errors='replace')}
        a,b=results['original'],results['observed']
        assert not a['terminal']['timeout'] and not b['terminal']['timeout'], key
        assert a['terminal']['returncode']==b['terminal']['returncode'] and a['stdout']==b['stdout'], f'observer changed behavior: {key}'
        assert a['terminal']['returncode']==0, f'native failure quarantined: {key}; see ASan/terminal evidence'
        assert results['reset']['terminal']['returncode']==0 and not results['reset']['terminal']['timeout'], key
        lines=b['stderr'].splitlines()
        lookups=[]; retained=[]; seen=set()
        for line in lines:
            if line.startswith('group '): seen=set()
            if not line.startswith('lookup '): continue
            x=dict(item.split('=') for item in line.split()[1:]); lookups.append(x)
            if int(x['companion'])>=0 and x['body'] not in seen: retained.append(x)
            seen.add(x['body'])
        stale=[x for x in lookups if int(x['companion'])>=int(x['size'])]
        groups=[line for line in lines if line.startswith('group ')]
        assert len(groups)==(4 if case['kind']!=2 and case['count']==2 else 2), (key,groups)
        if case['kind']==0 and case['count']==2:
            assert len(retained)==2 and all(x['body']=='0' for x in retained), f'missing shared-kinematic retained index: {key}'
        else:
            assert not retained, f'unexpected retained shared body: {key}'
        assert not any(line.startswith('lookup body=0 companion=1 ') or line.startswith('lookup body=0 companion=2 ') for line in results['reset']['stderr'].splitlines() if case['kind']==0 and case['count']==2), key
        def velocities(text):
            return [line.split()[:4]+line.split()[5:] for line in text.splitlines() if line.startswith('state ')]
        accesses=[dict(item.split('=') for item in line.split()[1:]) for line in lines if line.startswith('access ')]
        outside=[x for x in accesses if int(x['index'])>=int(x['size']) or int(x['index'])<0]
        assert all(int(x['index'])<int(x['capacity']) for x in outside), key
        assert (bool(outside)==(case['kind']==0 and case['count']==2 and case['order'] not in ('012','021'))), key
        summary.append({'case':key, 'accesses_outside_live_size':outside,'groups':groups,'retained_at_group_entry':retained,'out_of_logical_range_lookups':stale,'observer_stdout_equal':True,'reset_velocity_equal':velocities(a['stdout'])==velocities(results['reset']['stdout']),'native_returncodes':{n:v['terminal']['returncode'] for n,v in results.items()}})
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(f'PASS: {len(cases)} real-World scenes; original/observer outputs equal; retained-index and control assertions passed. See summary.json; this is characterization, not a physics safety verdict.')

if __name__=='__main__':
    main()
