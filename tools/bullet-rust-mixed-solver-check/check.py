#!/usr/bin/env python3
"""Compare complete real solveGroup traces with the shared Rust solver on this host."""
import argparse
import atexit
import difflib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
from cases import corpus
from trace import compare, validate

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / 'recipes/bullet275/bullet-src/src'
SHIM = ROOT / 'rust/crates/mds-bullet-sys/shim'
SOLVER = SRC / 'BulletDynamics/ConstraintSolver/btSequentialImpulseConstraintSolver.cpp'
SOURCES = ['BulletCollision/NarrowPhaseCollision/btPersistentManifold',
           'BulletDynamics/ConstraintSolver/btGeneric6DofConstraint',
           'BulletDynamics/ConstraintSolver/btGeneric6DofSpringConstraint',
           'BulletDynamics/ConstraintSolver/btTypedConstraint',
           'BulletDynamics/ConstraintSolver/btSequentialImpulseConstraintSolver',
           'BulletDynamics/ConstraintSolver/btContactConstraint',
           'BulletDynamics/ConstraintSolver/btSolve2LinearConstraint',
           'BulletDynamics/Dynamics/btRigidBody',
           'BulletCollision/CollisionDispatch/btCollisionObject', 'LinearMath/btAlignedAllocator']


def hooks(source):
    start = source.index('btScalar btSequentialImpulseConstraintSolver::solveGroupCacheFriendlyIterations(')
    end = source.index('\n\t\t\tif (infoGlobal.m_splitImpulse)', start)
    iteration = source[start:end]
    pattern = r'(?m)^(\s*)(resolveSingleConstraintRow(?:Generic|LowerLimit)(?:SIMD)?\([^;]+;)'
    counts = [0] * 6
    def row(match):
        indent, call = match.groups()
        kind = 1 if 'constraint);' in call else 3 if 'LowerLimit' in call else 5
        counts[kind - 1] += 1
        return f'{indent}MIXED({kind}, iteration, j);\n{indent}{call}\n{indent}MIXED({kind+1}, iteration, j);'
    iteration = re.sub(pattern, row, iteration)
    assert counts == [2, 0, 2, 0, 2, 0], counts
    old = 'int bodyAid = getOrInitSolverBody(constraints[j]->getRigidBodyA());'
    assert iteration.count(old) == 2
    iteration = iteration.replace(old, 'MIXED(7, iteration, j);\n\t\t\t\t\t' + old)
    old = 'constraints[j]->solveConstraintObsolete(bodyA,bodyB,infoGlobal.m_timeStep);'
    assert iteration.count(old) == 2
    iteration = iteration.replace(old, old + '\n\t\t\t\t\tMIXED(8, iteration, j);')
    old = 'if (totalImpulse>btScalar(0))'
    assert iteration.count(old) == 2
    iteration = iteration.replace(old, 'if (!(totalImpulse>btScalar(0))) { MIXED(9, iteration, j); }\n\t\t\t\t\t' + old)
    declaration = '''extern void mixed_trace(int,int,int,const btAlignedObjectArray<btSolverBody>&,const btAlignedObjectArray<btSolverConstraint>&,const btAlignedObjectArray<btSolverConstraint>&,const btAlignedObjectArray<btSolverConstraint>&);
#define MIXED(k,t,i) mixed_trace(k,t,i,m_tmpSolverBodyPool,m_tmpSolverNonContactConstraintPool,m_tmpSolverContactConstraintPool,m_tmpSolverContactFrictionConstraintPool)
'''
    source = source[:start] + declaration + iteration + source[end:]
    old = 'solveGroupCacheFriendlyIterations(bodies, numBodies, manifoldPtr,  numManifolds,constraints, numConstraints,infoGlobal,debugDrawer, stackAlloc);'
    assert source.count(old) == 1
    source = source.replace(old, 'MIXED(0,-1,-1);\n\t' + old)
    old = '\n\tm_tmpSolverBodyPool.resize(0);'
    assert source.count(old) == 1
    source = source.replace(old, '\n\tMIXED(10,-1,-1);' + old)
    old = 'm_tmpSolverBodyPool[i].writebackVelocity();'
    assert source.count(old) == 1
    return source.replace(old, 'MIXED(11,-1,i);\n\t\t\t' + old + '\n\t\t\tMIXED(12,-1,i);')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--mutations', action='store_true')
    args = parser.parse_args()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    status_path = out / 'status.json'
    status_path.write_text('{"status":"RUNNING"}\n')
    def finalize_failure():
        if json.loads(status_path.read_text()).get('status') == 'RUNNING':
            status_path.write_text('{"status":"FAIL","details":"See commands and command stderr files"}\n')
    atexit.register(finalize_failure)
    environment = {k: v for k, v in os.environ.items() if not k.startswith('OPENMMD_DUMP_')}
    commands = []
    def run(command, **kwargs):
        command = list(map(str, command)); commands.append(command)
        result = subprocess.run(command, cwd=ROOT / 'rust', env=environment, capture_output=True, **kwargs)
        (out / f'command-{len(commands):03}.stderr').write_bytes(result.stderr)
        if result.returncode:
            print(result.stderr.decode(errors='replace'))
            result.check_returncode()
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        return result.stdout
    suffix = '.exe' if os.name == 'nt' else ''
    crt = ROOT / 'rust/crates/mds-crtmath/src/lib.rs'
    static = out / 'libmds_crtmath.a'
    libraries = run(['rustup','run','1.95.0','rustc','--edition=2021','--crate-name','mds_crtmath','--crate-type','staticlib','--print','native-static-libs','-O',crt,'-o',static])
    library_output = (out / 'command-001.stderr').read_text()
    native_libs = library_output.split('native-static-libs:')[-1].splitlines()[0].split() if os.name == 'nt' else []
    def compile_native(label, solver, oracle=HERE / "oracle.cpp"):
        sources = [solver if name.endswith('btSequentialImpulseConstraintSolver') else SRC / (name + '.cpp') for name in SOURCES]
        exe = out / (label + suffix)
        if os.name == 'nt':
            command = [os.environ.get('CXX','cl'),'/nologo','/std:c++17','/O2','/fp:precise','/EHsc','/W0','/MD','/DBT_NO_PROFILE=1',f'/I{SOLVER.parent}',f'/I{SRC}',f'/I{SHIM}',f'/FI{SHIM / "det_math.h"}',oracle,*sources,static,f'/Fe:{exe}',f'/Fo:{out}\\','/link','/OPT:REF',*native_libs]
        else:
            command = [os.environ.get('CXX','clang++'),'-std=c++17','-O2','-ffp-contract=off','-fno-fast-math','-fdeclspec','-w','-DBT_NO_PROFILE=1','-I',SOLVER.parent,'-I',SHIM / 'sse_emu','-I',SRC,'-I',SHIM,'-include',SHIM / 'det_math.h',oracle,*sources,static,'-o',exe]
            command += ['-Wl,-dead_strip'] if platform.system() == 'Darwin' else ['-ffunction-sections','-fdata-sections','-Wl,--gc-sections','-ldl','-lpthread','-lm']
        run(command)
        return exe
    compiler = os.environ.get('CXX','cl' if os.name == 'nt' else 'clang++')
    (out / 'compiler.txt').write_bytes(run([compiler,'/?'] if os.name == 'nt' else [compiler,'--version']))
    (out / 'rust-target.txt').write_bytes(run(['rustup','run','1.95.0','rustc','-vV']))
    profile = out / 'profile.cpp'
    profile_code = '#include "LinearMath/btScalar.h"\n#include <cstdio>\n#define S_(x) #x\n#define S(x) S_(x)\nint main(){\n'
    for macro in ['BT_USE_SSE','BT_USE_DOUBLE_PRECISION','BT_NO_PROFILE','WIN32','_WIN64','_M_X64','__x86_64__','__aarch64__','_M_ARM64']:
        profile_code += f'#ifdef {macro}\nputs("{macro}=" S({macro}));\n#else\nputs("{macro}=<undefined>");\n#endif\n'
    profile.write_text(profile_code+'printf("pointer_bits=%zu\\n",sizeof(void*)*8);\n}\n')
    profile_exe = compile_native('native-profile',SOLVER,profile)
    profile_data = run([profile_exe]);(out / 'effective-profile.txt').write_bytes(profile_data)
    macros = dict(line.split('=',1) for line in profile_data.decode().splitlines())
    assert macros['BT_USE_SSE'] != '<undefined>' and macros['pointer_bits'] == '64',macros
    if platform.system() == 'Darwin':
        assert macros['__aarch64__'] == '1', 'Apple Silicon is the supported macOS target'
    if os.name == 'nt':
        assert macros['_WIN64'] == '1' and macros['_M_X64'] == '100',macros
    tracked = [*SRC.rglob('*.h'),*[SRC / (name+'.cpp') for name in SOURCES],SHIM / 'det_math.h',crt,*HERE.glob('*.py'),HERE / 'runner.rs',HERE / 'oracle.cpp',ROOT / 'rust/crates/mds-bullet/src/core/solver.rs',ROOT / 'rust/crates/mds-bullet/src/core/contact_solver.rs']
    manifest = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
    (out / 'source-sha256.json').write_text(json.dumps(manifest,indent=2)+'\n')
    fixture_paths = [* (ROOT / 'rust/crates/mds-bullet/tests/solver_data').glob('*'),* (ROOT / 'rust/crates/mds-bullet/tests/contact_solver_data').glob('*')]
    fixtures = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in fixture_paths if p.is_file()}
    (out / 'frozen-fixture-sha256.json').write_text(json.dumps(fixtures,indent=2)+'\n')
    source = SOLVER.read_text()
    observed = hooks(source)
    patched = out / SOLVER.name; patched.write_text(observed)
    (out / 'observer.diff').write_text(''.join(difflib.unified_diff(source.splitlines(True),observed.splitlines(True),fromfile=str(SOLVER),tofile=str(patched))))
    inputs = out / 'inputs.tsv'; inputs.write_text(corpus())
    original = compile_native('native-original', SOLVER)
    native = compile_native('native-observed', patched)
    original_stdout = run([original, inputs, out / 'original.trace'])
    native_stdout = run([native, inputs, out / 'native.trace'])
    (out / 'original.tsv').write_bytes(original_stdout);(out / 'native.tsv').write_bytes(native_stdout)
    assert original_stdout == native_stdout, 'observer changes native stdout'
    run(['rustup','run','1.95.0','rustc','--edition=2021','--crate-name','mds_crtmath','--crate-type','rlib','-O',crt,'-o',out / 'libmds_crtmath.rlib'])
    run(['rustup','run','1.95.0','rustc','--edition=2021','--crate-name','bullet_core_support','--crate-type','rlib','-D','warnings','-O',ROOT / 'tools/bullet-rust-contact-solver-check/support.rs','--extern',f'mds_crtmath={out / "libmds_crtmath.rlib"}','-o',out / 'libbullet_core_support.rlib'])
    def rust_command(source, label, driver='rustc'):
        return ['rustup','run','1.95.0',driver,'--edition=2021','-D','warnings','-O',source,'-L',f'dependency={out}','--extern',f'bullet_core_support={out / "libbullet_core_support.rlib"}','--extern',f'mds_crtmath={out / "libmds_crtmath.rlib"}','-o',out / (label + suffix)]
    run(rust_command(HERE / 'runner.rs','rust-mixed'))
    actual = run([out / ('rust-mixed' + suffix), inputs, out / 'rust.trace'])
    (out / 'rust.tsv').write_bytes(actual)
    assert actual == native_stdout, 'mixed writeback differs'
    difference = compare(out / 'native.trace', out / 'rust.trace')
    comparison = {'status':'BIT_EXACT','raw_bit_equality':True}
    if difference is not None:
        from observation import verify
        comparison = verify(out,HERE / 'profiles')
    (out / 'comparison.json').write_text(json.dumps(comparison,indent=2)+'\n')
    coverage = validate(out / 'native.trace')
    (out / 'coverage.json').write_text(json.dumps(coverage,indent=2)+'\n')
    run(rust_command(HERE / 'runner.rs','clippy-mixed','clippy-driver'))
    if args.mutations:
        from mutations import run_mutations
        run_mutations(ROOT,HERE,out,inputs,run,rust_command,suffix,native)
    assert all(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest for path,digest in fixtures.items()), 'frozen fixtures changed'
    assert all(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest for path,digest in manifest.items()), 'source changed during comparison'
    provenance = {'schema_version':1,'platform':platform.platform(),'input_sha256':hashlib.sha256(inputs.read_bytes()).hexdigest(),'sources':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [SOLVER,HERE / 'oracle.cpp',HERE / 'runner.rs',SHIM / 'det_math.h']},'solves':len(actual.splitlines()),'trace_events':coverage['events'],'comparison':comparison,'status':'PASS' if comparison['raw_bit_equality'] else 'PASS_SOURCE_DEFINED_ARITHMETIC_OBSERVATION'}
    (out / 'status.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps(provenance,indent=2))

if __name__ == '__main__':
    main()
