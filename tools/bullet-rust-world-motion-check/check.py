#!/usr/bin/env python3
"""Compare world motion passes from both unchanged native shims and Rust."""
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
BASE = '781e5209dada4d2196ee966de741b35a14cd6bc4'

def require(ok, message):
    if not ok: raise AssertionError(message)

def hashes(root):
    return {p.relative_to(root).as_posix(): 'symlink:' + os.readlink(p) if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() or p.is_symlink()}

def source_snapshot():
    folders = ['recipes/bullet275/bullet-src/src', 'rust/crates/mds-bullet/src/core',
               'rust/crates/mds-bullet/tests', 'rust/crates/mds-bullet-sys/shim',
               'rust/crates/mds-crtmath/src', 'tools/bullet-rust-world-objects-check', 'tools/bullet-rust-world-motion-check']
    result = {str(Path(folder) / name): digest for folder in folders for name, digest in hashes(ROOT / folder).items()
              if '__pycache__' not in name}
    result['.github/workflows/bullet-world-objects.yml'] = hashlib.sha256((ROOT / '.github/workflows/bullet-world-objects.yml').read_bytes()).hexdigest()
    result['.github/workflows/bullet-world-motion.yml'] = hashlib.sha256((ROOT / '.github/workflows/bullet-world-motion.yml').read_bytes()).hexdigest()
    return result

def includes(raw):
    pattern = r'^Note: including file:\s+(.+)$' if os.name == 'nt' else r'^\.+ (.+)$'
    return sorted({Path(m[1]).resolve() for line in raw.decode(errors='replace').splitlines()
                   if (m := re.match(pattern, line)) and Path(m[1]).is_file()})

def expected_records():
    records = []
    for kind, count in [('P', 8), ('M', 9)]:
        for variant in range(4):
            for row in range(18):
                records.append((['W', kind, str(variant), str(row)], None))
                records.extend((['B', kind, str(variant), str(row), str(i)], 122) for i in range(count))
    return records


def validate(raw, reference=None):
    rows = raw.decode().splitlines(); records = expected_records()
    def integer(value, low, high):
        require(re.fullmatch(r'-?(0|[1-9][0-9]*)', value) is not None, 'malformed integer')
        require(low <= int(value) <= high, 'integer out of range')
    def words(values):
        require(all(re.fullmatch(r'[0-9a-f]{8}', v) for v in values), 'malformed float word')
    require(len(rows) == len(records), 'incomplete trace')
    for line, (prefix, width) in zip(rows, records):
        a = line.split()
        require(a[:len(prefix)] == prefix, 'trace record order or identity changed')
        if width is not None: require(len(a) == width, 'trace record width changed')
        if a[0] == 'W':
            require(len(a) >= 9 and a[7] == 'N', 'malformed registration trace')
            words(a[4:7]); integer(a[8], 0, 9)
            require(len(a) == 9 + int(a[8]), 'registration count differs')
            count = 8 if a[1] == 'P' else 9
            for value in a[9:]: integer(value, 0, count - 1)
            require(len(set(a[9:])) == len(a[9:]), 'duplicate registration index')
        else:
            words(a[5:-6]); words(a[-1:])
            integer(a[-6], -1, 127); integer(a[-5], 1, 5)
            for value in a[-4:-2]: integer(value, -32768, 32767)
            require(a[-2] == '0', 'unexpected constraint reference')


MUTANTS = {
    'save-membership': ('world_objects.rs', 'for i in 0..self.bodies.len() {\n            if self.data[i].collision_flags & 2', 'for &i in &self.non_static {\n            if self.data[i].collision_flags & 2'),
    'save-sleep-guard': ('world_objects.rs', '&& self.objects[i].activation.state != ActivationState::IslandSleeping', '&& self.objects[i].activation.is_active()'),
    'save-motion-source': ('world_objects.rs', 'let world = self.data[i].motion.get_world_transform();', 'let world = self.bodies[i].snapshot().world;'),
    'velocity-transpose': ('math.rs', '.multiply(self.basis.inverse())\n            .rotation()', '.multiply(self.basis.transpose())\n            .rotation()'),
    'prediction-active-guard': ('world_objects.rs', 'if self.data[i].collision_flags & 3 == 0 {\n                self.bodies[i].integrate_velocities(dt);', 'if self.data[i].collision_flags & 3 == 0 && self.objects[i].activation.is_active() {\n                self.bodies[i].integrate_velocities(dt);'),
    'prediction-world-target': ('world_objects.rs', 'self.bodies[i].set_interpolation_world_transform(predicted);', 'self.bodies[i].set_world_transform(predicted);'),
    'prediction-omit-damping': ('world_objects.rs', 'self.bodies[i].apply_damping(dt);', ''),
    'gravity-ignore-active': ('world_objects.rs', 'if self.objects[i].activation.is_active() {\n                self.bodies[i].apply_gravity();', 'if true {\n                self.bodies[i].apply_gravity();'),
    'clear-membership': ('world_objects.rs', 'for &i in &self.non_static {\n            self.bodies[i].clear_forces();', 'for i in 0..self.bodies.len() {\n            self.bodies[i].clear_forces();'),
    'sync-body-source': ('world_objects.rs', 'let interpolated = state.interpolation_world.integrate(', 'let interpolated = state.world.integrate('),
    'sync-ignore-hit': ('world_objects.rs', 'local_time * self.objects[i].hit_fraction,', 'local_time,'),
    'sync-ignore-all': ('world_objects.rs', 'if synchronize_all {', 'if synchronize_all && false {'),
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
        require(source_snapshot() == before, 'source closure changed before command')
        require(hashes(generated_root) == generated, 'generated closure changed before command')
        require(dep_snapshot() == dependencies, 'include closure changed before command')
        argv = list(map(str, argv)); commands.append({'label': label, 'argv': argv}); save('commands.json', commands)
        p = subprocess.run(argv, cwd=ROOT / 'rust', capture_output=True, env=env, input=inputs, timeout=240)
        (out / (label + '.stdout')).write_bytes(p.stdout); (out / (label + '.stderr')).write_bytes(p.stderr)
        included = includes(p.stdout + p.stderr)
        save(label + '-includes.json', list(map(str,included)))
        for path in included:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            previous = dependencies.setdefault(str(path), digest)
            require(previous == digest, 'include closure changed during command')
        save('native-includes.json', dependencies)
        require(p.returncode == 0, f'{label} failed ({p.returncode}): {p.stderr.decode(errors="replace")[-2000:]}')
        return p.stdout
    env = {k:v for k,v in os.environ.items() if not k.startswith('OPENMMD_DUMP_')}; env['VSLANG'] = '1033'
    save('source-start.json', before)
    try:
        machine = platform.machine().lower(); system = platform.system()
        require(machine in ['x86_64','amd64','aarch64','arm64'], 'unsupported host architecture')
        require(system != 'Darwin' or machine == 'arm64', 'unsupported macOS architecture')
        require(system != 'Windows' or machine in ['amd64','x86_64'], 'unsupported Windows architecture')
        status['host'] = {'system': platform.platform(), 'architecture': machine, 'runner_image': os.environ.get('ImageOS'), 'runner_version': os.environ.get('ImageVersion')}
        variants = ['observed'] + ([] if args.skip_mutations else args.mutation or list(MUTANTS))
        sources = {name: (ROOT / 'rust/crates/mds-bullet/src/core' / name).read_text() for name in ['world_objects.rs', 'math.rs']}
        for name in variants:
            tree = generated_root / name
            shutil.copytree(ROOT / 'rust/crates/mds-bullet/src/core', tree / 'rust/crates/mds-bullet/src/core')
            runner = tree / 'tools/bullet-rust-world-motion-check/runner.rs'; runner.parent.mkdir(parents=True)
            code = (HERE / 'runner.rs').read_text()
            if name == 'observed':
                code = code.replace('// OBSERVER_ANCHOR', 'eprintln!("OBS {} {} {} {}",k,variant,r,w.bodies().len());')
            else:
                file, old, new = MUTANTS[name]; source = sources[file]
                require(source.count(old) == 1, f'missing or ambiguous mutant anchor {name}')
                (tree / 'rust/crates/mds-bullet/src/core' / file).write_text(source.replace(old,new))
            runner.write_text(code)
        macro = generated_root / 'macros.cpp'
        code = '#include "LinearMath/btScalar.h"\n#include <cstdio>\n#define S_(x) #x\n#define S(x) S_(x)\nint main(){\n'
        for name in ['BT_USE_SSE','BT_USE_DOUBLE_PRECISION','BT_NO_PROFILE','_MSC_VER','_M_X64','__x86_64__','__aarch64__']:
            code += f'#ifdef {name}\nputs("{name}=" S({name}));\n#else\nputs("{name}=<undefined>");\n#endif\n'
        macro.write_text(code + 'printf("pointer_bits=%zu\\n",sizeof(void*)*8);}\n')
        generated = hashes(generated_root); save('generated-start.json', generated)
        require(all(not value.startswith('symlink:') for value in generated.values()), 'generated source symlink forbidden')
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
        save('compiled-cpp.json', [str(p.relative_to(ROOT)) for p in sources] + ['tools/bullet-rust-world-motion-check/'+n for n in ['public.cpp','mmd.cpp','main.cpp']])
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
        require(original_headers and original_headers == observer_headers, 'observer include resolution differs')
        rargs = [*rust,'--extern',f'mds_crtmath={out / "libmds_crtmath.rlib"}']
        for name,path in [('rust',HERE/'runner.rs'),*[(name,generated_root/name/'tools/bullet-rust-world-motion-check/runner.rs') for name in variants]]:
            run([*rargs,path,'-o',out/(name+suffix)],'build-'+name)
        run([*rargs,'--test','-D','warnings',HERE/'harness.rs','-o',out/('tests'+suffix)],'build-tests');run([out/('tests'+suffix)],'focused-tests')
        native = run([out/('native'+suffix)],'native'); observed = run([out/('native-observed'+suffix)],'native-observed')
        actual = run([out/('rust'+suffix)],'rust'); robserved = run([out/('observed'+suffix)],'rust-observed')
        for raw in [native,observed,actual,robserved]:validate(raw,native)
        require(native == observed, 'native observer changed stdout');require(actual == robserved, 'Rust observer changed stdout')
        require((out/'native-observed.stderr').read_bytes() == (out/'rust-observed.stderr').read_bytes(), 'observer counts differ')
        (out/'native-rust.diff').write_text(''.join(difflib.unified_diff(native.decode().splitlines(True),actual.decode().splitlines(True),fromfile='native',tofile='rust')))
        require(native == actual, 'raw mismatch; full capture retained; no numeric profile approved')
        results = {}
        for name in variants:
            if name == 'observed': continue
            raw = run([out/(name+suffix)],'mutant-'+name);validate(raw,native)
            results[name] = 'CAUGHT' if raw != native else 'SURVIVED';save('mutations.json',results)
            require(raw != native, f'mutant survived: {name}')
        status['status'] = 'PASS_FOCUSED_ONLY' if args.skip_mutations else 'PASS_SAME_HOST_RAW_AND_MUTATIONS'
        status['trace_lines'] = len(native.splitlines());status['mutants'] = results
        if args.mutation: status['status'] = 'PASS_SELECTED_MUTATIONS_ONLY'
        save('source-end.json',source_snapshot()); save('generated-end.json',hashes(generated_root)); save('native-includes-end.json',dep_snapshot())
    except BaseException as error:
        status['status'] = 'FAIL'; status['error'] = str(error);raise
    finally:
        after = source_snapshot(); generated_after=hashes(generated_root);deps_after=dep_snapshot()
        save('source-finally.json',after);save('generated-finally.json',generated_after);save('native-includes-finally.json',deps_after)
        status['integrity'] = 'PASS' if before==after and generated==generated_after and dependencies==deps_after else 'FAIL'
        if status['integrity'] != 'PASS':
            if 'error' in status: status['original_error'] = status['error']
            changed = [name for name, old, new in [('source',before,after), ('generated',generated,generated_after), ('include',dependencies,deps_after)] if old != new]
            status['status'] = 'FAIL'
            status['error'] = 'closure changed: ' + ', '.join(changed)
        save('status.json',status)
        if status['integrity'] != 'PASS': raise AssertionError(status['error'])
    print(json.dumps(status,indent=2))

if __name__ == '__main__': main()
