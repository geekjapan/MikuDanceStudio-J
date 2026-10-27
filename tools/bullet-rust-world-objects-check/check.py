#!/usr/bin/env python3
"""Compare raw registered objects from both unchanged native shims and Rust."""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = 'ba741bc903404a680481578b871a613213b4f949'

def hashes(root):
    return {p.relative_to(root).as_posix(): 'symlink:' + os.readlink(p) if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() or p.is_symlink()}

def source_snapshot():
    folders = ['recipes/bullet275/bullet-src/src', 'rust/crates/mds-bullet/src/core',
               'rust/crates/mds-bullet/tests', 'rust/crates/mds-bullet-sys/shim',
               'rust/crates/mds-crtmath/src', 'tools/bullet-rust-world-objects-check']
    result = {str(Path(folder) / name): digest for folder in folders for name, digest in hashes(ROOT / folder).items()
              if '__pycache__' not in name}
    result['.github/workflows/bullet-world-objects.yml'] = hashlib.sha256((ROOT / '.github/workflows/bullet-world-objects.yml').read_bytes()).hexdigest()
    return result

def includes(raw):
    pattern = r'^Note: including file:\s+(.+)$' if os.name == 'nt' else r'^\.+ (.+)$'
    return sorted({Path(m[1]).resolve() for line in raw.decode(errors='replace').splitlines()
                   if (m := re.match(pattern, line)) and Path(m[1]).is_file()})

def expected_records():
    records = []
    def snapshot(kind, row, bodies, joints):
        records.append((['W',kind,str(row)], None))
        records.extend((['B',kind,str(row),str(i)],120) for i in range(bodies))
        records.extend((['J',kind,str(row),str(i)],64 if kind == 'P' else 65) for i in range(joints))
    snapshot('P',0,0,0)
    for i in range(7):
        records.append((['C','P',str(i)],4));snapshot('P',i+1,i+1,0)
    for row in [8,9,10]: snapshot('P',row,7,0)
    for j in range(3):
        records.append((['K','P',str(j)],4));snapshot('P',11+j,7,j+1)
    records.extend([(['R','P','-2'],4),(['F','P','-1'],3)])
    snapshot('P',14,7,3);snapshot('M',0,1,0)
    for i in range(4):
        records.append((['C','M',str(i)],4));snapshot('M',i+1,i+2,0)
    for row in range(5,12):snapshot('M',row,5,0)
    for j in range(3):
        records.append((['K','M',str(j)],4));snapshot('M',12+j,5,j+1)
    return records


def validate(raw, reference=None):
    rows = raw.decode().splitlines(); records = expected_records()
    assert len(rows) == len(records), 'incomplete trace'
    for line, (prefix, width) in zip(rows, records):
        a = line.split()
        assert a[:len(prefix)] == prefix, 'trace record order or identity changed'
        if width is not None: assert len(a) == width, 'trace record width changed'
        if a[0] == 'W':
            assert a[6] == 'N' and len(a) == 8 + int(a[7]), 'registration trace width changed'
            assert all(re.fullmatch(r'[0-9a-f]{8}', v) for v in a[3:6])
        elif a[0] == 'B':
            assert all(re.fullmatch(r'[0-9a-f]{8}', v) for v in a[4:-5]), 'malformed body float bits'
            assert all(re.fullmatch(r'-?[0-9]+', v) for v in a[-5:]), 'malformed body metadata'
        else:
            assert all(re.fullmatch(r'-?[0-9]+|[0-9a-f]{8}',v) for v in a[len(prefix):]), 'malformed trace token'

MUTANTS = {
    'motion-body-confusion': ('self.data[i].motion.set_world_transform(world);\n        Ok(())', 'self.bodies[i].set_world_transform(world);\n        Ok(())'),
    'reseat-interpolation-write': ('self.bodies[i].set_interpolation_velocities(Vec3::ZERO, Vec3::ZERO);\n        Ok(())', 'self.bodies[i].set_interpolation_velocities(Vec3::ZERO, Vec3::ZERO);\n        self.bodies[i].set_interpolation_world_transform(world);\n        Ok(())'),
    'stop-interpolation-clear': ('let mut world = self.bodies[i].snapshot().world;\n        world.origin = origin;', 'self.bodies[i].set_interpolation_velocities(Vec3::ZERO, Vec3::ZERO);\n        let mut world = self.bodies[i].snapshot().world; world.origin = origin;'),
    'ignore-active': ('if self.objects[i].activation.is_active()', 'if true'),
    'rebuild-nonstatic': ('for &i in &self.non_static {', 'let rebuilt: Vec<_> = self.bodies.iter().enumerate().filter(|(_, b)| !b.snapshot().is_static && !b.snapshot().is_kinematic).map(|(i, _)| i).collect();\n        for &i in &rebuilt {'),
    'filter-sign-loss': ('filter: filter.unwrap_or(', 'filter: filter.map(|v| v.map(|x| x & 0x7fff)).unwrap_or('),
    'all-joints-disable-collisions': ('let disable_collisions = mmd_uid.is_none() && desc.disable_collisions;', 'let disable_collisions = true;'),
    'public-equilibrium-calculation': ('if mmd_uid.is_some() && state.springs.iter().any(|s| s.enabled)', 'if state.springs.iter().any(|s| s.enabled)'),
    'omit-mmd-equilibrium': ('if mmd_uid.is_some() && state.springs.iter().any(|s| s.enabled)', 'if false && state.springs.iter().any(|s| s.enabled)'),
    'global-zero-normalize': ('if mmd && v == 0.0 { 0.0 } else { v }', 'if v == 0.0 { 0.0 } else { v }'),
    'floor-mask-toggle': ('self.set_flags(0, if on { 1 } else { -1 });', 'self.data[0].filter[1] = if on { -1 } else { 0 };'),
}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--skip-mutations', action='store_true')
    parser.add_argument('--mutation', action='append', choices=sorted(MUTANTS))
    args = parser.parse_args()
    out = args.out_dir.resolve(); out.mkdir(parents=True, exist_ok=True)
    generated_root = out / 'generated-sources'; generated_root.mkdir()
    before = source_snapshot(); generated = {}; dependencies = {}; commands = []
    status = {'status': 'FAIL', 'base': BASE, 'product_world': 'NOT_MIGRATED', 'four_host': 'PENDING'}
    def save(name, value): (out / name).write_text(json.dumps(value, indent=2) + '\n')
    def dep_snapshot(): return {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() if Path(name).is_file() else None for name in dependencies}
    def run(argv, label, inputs=None):
        assert source_snapshot() == before, 'source closure changed before command'
        assert hashes(generated_root) == generated, 'generated closure changed before command'
        assert dep_snapshot() == dependencies, 'include closure changed before command'
        argv = list(map(str, argv)); commands.append({'label': label, 'argv': argv}); save('commands.json', commands)
        p = subprocess.run(argv, cwd=ROOT / 'rust', capture_output=True, env=env, input=inputs, timeout=240)
        (out / (label + '.stdout')).write_bytes(p.stdout); (out / (label + '.stderr')).write_bytes(p.stderr)
        included = includes(p.stdout + p.stderr)
        save(label + '-includes.json', list(map(str,included)))
        for path in included:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert dependencies.setdefault(str(path), digest) == digest
        save('native-includes.json', dependencies)
        assert p.returncode == 0, f'{label} failed ({p.returncode}): {p.stderr.decode(errors="replace")[-2000:]}'
        return p.stdout
    env = {k:v for k,v in os.environ.items() if not k.startswith('OPENMMD_DUMP_')}; env['VSLANG'] = '1033'
    save('source-start.json', before)
    try:
        machine = platform.machine().lower(); system = platform.system()
        assert machine in ['x86_64','amd64','aarch64','arm64']
        assert system != 'Darwin' or machine == 'arm64'
        assert system != 'Windows' or machine in ['amd64','x86_64']
        status['host'] = {'system': platform.platform(), 'architecture': machine, 'runner_image': os.environ.get('ImageOS'), 'runner_version': os.environ.get('ImageVersion')}
        variants = ['observed'] + ([] if args.skip_mutations else args.mutation or list(MUTANTS))
        source = (ROOT / 'rust/crates/mds-bullet/src/core/world_objects.rs').read_text()
        for name in variants:
            tree = generated_root / name
            shutil.copytree(ROOT / 'rust/crates/mds-bullet/src/core', tree / 'rust/crates/mds-bullet/src/core')
            runner = tree / 'tools/bullet-rust-world-objects-check/runner.rs'; runner.parent.mkdir(parents=True)
            code = (HERE / 'runner.rs').read_text()
            if name == 'observed':
                code = code.replace('// OBSERVER_ANCHOR', 'eprintln!("OBS {} {} {} {}",k,r,w.bodies().len(),w.joints().len());')
            else:
                old, new = MUTANTS[name]; assert source.count(old) == 1, f'missing or ambiguous mutant anchor {name}'
                (tree / 'rust/crates/mds-bullet/src/core/world_objects.rs').write_text(source.replace(old,new))
            runner.write_text(code)
        macro = generated_root / 'macros.cpp'
        code = '#include "LinearMath/btScalar.h"\n#include <cstdio>\n#define S_(x) #x\n#define S(x) S_(x)\nint main(){\n'
        for name in ['BT_USE_SSE','BT_USE_DOUBLE_PRECISION','BT_NO_PROFILE','_MSC_VER','_M_X64','__x86_64__','__aarch64__']:
            code += f'#ifdef {name}\nputs("{name}=" S({name}));\n#else\nputs("{name}=<undefined>");\n#endif\n'
        macro.write_text(code + 'printf("pointer_bits=%zu\\n",sizeof(void*)*8);}\n')
        generated = hashes(generated_root); save('generated-start.json', generated)
        assert all(not value.startswith('symlink:') for value in generated.values()), 'generated source symlink forbidden'
        compiler = os.environ.get('CXX', 'cl' if os.name == 'nt' else 'clang++')
        src = ROOT / 'recipes/bullet275/bullet-src/src'; shim = ROOT / 'rust/crates/mds-bullet-sys/shim'
        flags = ['/showIncludes','/nologo','/std:c++17','/O2','/MD','/EHsc','/fp:precise','/W0','/DBT_NO_PROFILE=1',f'/I{src}',f'/I{shim}',f'/FI{shim / "det_math.h"}'] if os.name == 'nt' else ['-H','-std=c++17','-O2','-ffp-contract=off','-fno-fast-math','-fdeclspec','-w','-DBT_NO_PROFILE=1','-I',shim/'sse_emu','-I',src,'-I',shim,'-include',shim/'det_math.h']
        save('compiler-flags.json', list(map(str,flags)))
        run([compiler,'/?'] if os.name == 'nt' else [compiler,'--version'],'compiler-version')
        run(['rustup','run','1.95.0','rustc','-Vv'],'rust-version')
        run(['git','-C',ROOT,'ls-files','--eol'],'git-transport')
        run(['git','-C',ROOT,'rev-parse','HEAD'],'git-head')
        run(['git','-C',ROOT,'status','--porcelain=v1'],'git-status')
        run(['git','-C',ROOT,'check-attr','--stdin','text','eol'],'source-attributes', ('\n'.join(before)+'\n').encode())
        run([sys.executable,'-m','unittest','discover','-s',HERE,'-p','test_*.py'],'checker-tests')
        rust = ['rustup','run','1.95.0','rustc','--edition=2021','-O']
        run([*rust,'--crate-name','mds_crtmath','--crate-type','rlib,staticlib','--print','native-static-libs',ROOT/'rust/crates/mds-crtmath/src/lib.rs','--out-dir',out],'crt')
        suffix = '.exe' if os.name == 'nt' else ''
        macro_exe = out / ('macros'+suffix)
        run([compiler,*flags,macro,f'/Fe:{macro_exe}',f'/Fo:{out}/'] if os.name == 'nt' else [compiler,*flags,macro,'-o',macro_exe],'macro-build');run([macro_exe],'effective-macros')
        objects = []
        sources = sorted(p for folder in ['LinearMath','BulletCollision','BulletDynamics'] for p in (src / folder).rglob('*.cpp'))
        save('compiled-cpp.json', [str(p.relative_to(ROOT)) for p in sources] + ['tools/bullet-rust-world-objects-check/'+n for n in ['public.cpp','mmd.cpp','main.cpp']])
        for i,path in enumerate(sources):
            obj = out / (f'native-{i}'+('.obj' if os.name == 'nt' else '.o'))
            run([compiler,*flags,'/c',path,f'/Fo{obj}'] if os.name == 'nt' else [compiler,*flags,'-c',path,'-o',obj],f'compile-{i}');objects.append(obj)
        crt = out / ('mds_crtmath.lib' if os.name == 'nt' else 'libmds_crtmath.a')
        for name, observer in [('native',False),('native-observed',True)]:
            exe = out / (name+suffix); defs = ['/DOBSERVER=1'] if os.name == 'nt' and observer else ['-DOBSERVER=1'] if observer else []
            units = [HERE/'public.cpp',HERE/'mmd.cpp',HERE/'main.cpp']
            if os.name == 'nt':
                libs = (out/'crt.stderr').read_text().split('native-static-libs:')[-1].splitlines()[0].split()
                command = [compiler,*flags,*defs,*units,*objects,crt,f'/Fe:{exe}',f'/Fo:{out}/','/link','/OPT:REF',*libs]
            else:
                command = [compiler,*flags,*defs,*units,*objects,crt,'-o',exe,*(['-Wl,-dead_strip'] if system=='Darwin' else ['-Wl,--gc-sections','-ldl','-lpthread','-lm'])]
            run(command,'build-'+name)
        original_headers = json.loads((out / 'build-native-includes.json').read_text())
        observer_headers = json.loads((out / 'build-native-observed-includes.json').read_text())
        assert original_headers and original_headers == observer_headers, 'observer include resolution differs'
        rargs = [*rust,'--extern',f'mds_crtmath={out / "libmds_crtmath.rlib"}']
        for name,path in [('rust',HERE/'runner.rs'),*[(name,generated_root/name/'tools/bullet-rust-world-objects-check/runner.rs') for name in variants]]:
            run([*rargs,path,'-o',out/(name+suffix)],'build-'+name)
        run([*rargs,'--test','-D','warnings',HERE/'harness.rs','-o',out/('tests'+suffix)],'build-tests');run([out/('tests'+suffix)],'focused-tests')
        native = run([out/('native'+suffix)],'native'); observed = run([out/('native-observed'+suffix)],'native-observed')
        actual = run([out/('rust'+suffix)],'rust'); robserved = run([out/('observed'+suffix)],'rust-observed')
        for raw in [native,observed,actual,robserved]:validate(raw,native)
        assert native == observed, 'native observer changed stdout';assert actual == robserved, 'Rust observer changed stdout'
        assert (out/'native-observed.stderr').read_bytes() == (out/'rust-observed.stderr').read_bytes(), 'observer counts differ'
        (out/'native-rust.diff').write_text(''.join(difflib.unified_diff(native.decode().splitlines(True),actual.decode().splitlines(True),fromfile='native',tofile='rust')))
        assert native == actual, 'raw mismatch; full capture retained; no numeric profile approved'
        results = {}
        for name in variants:
            if name == 'observed': continue
            raw = run([out/(name+suffix)],'mutant-'+name);validate(raw,native)
            results[name] = 'CAUGHT' if raw != native else 'SURVIVED';save('mutations.json',results)
            assert raw != native, f'mutant survived: {name}'
        status['status'] = 'PASS_FOCUSED_ONLY' if args.skip_mutations else 'PASS_SAME_HOST_RAW_AND_MUTATIONS'
        status['trace_lines'] = len(native.splitlines());status['mutants'] = results
        if args.mutation: status['status'] = 'PASS_SELECTED_MUTATIONS_ONLY'
        save('source-end.json',source_snapshot()); save('generated-end.json',hashes(generated_root)); save('native-includes-end.json',dep_snapshot())
    except BaseException as error:
        status['error'] = str(error);raise
    finally:
        after = source_snapshot(); generated_after=hashes(generated_root);deps_after=dep_snapshot()
        save('source-finally.json',after);save('generated-finally.json',generated_after);save('native-includes-finally.json',deps_after)
        status['integrity'] = 'PASS' if before==after and generated==generated_after and dependencies==deps_after else 'FAIL'
        save('status.json',status)
        assert status['integrity']=='PASS', 'source/include/generated closure changed'
    print(json.dumps(status,indent=2))

if __name__ == '__main__': main()
