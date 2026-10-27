#!/usr/bin/env python3
"""Hosted-only original public-shim collision-world capture and strict Rust replay."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

from cases import corpus
from evidence import (Capture, ENVIRONMENT, LIMITS, admit_capture, digest, include_paths, inventory,
                      macro_source, native_flags, policy, selected_members, semantic_fields, command_input_paths, command_schedule, replay_report)
from hooks import CORE, NATIVE, OWNER, SHIM, MUTANTS, instrument, inverse, mutate, require
from trace import bind_inputs, comparison, validate, validate_allocator, validate_physical

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = 'c8dc8a387a9d37442a84dbd8a3b81c90898b6d6d'
MODES = ['ascending', 'descending', 'alternating', 'ordinary']
FOLDERS = ['recipes/bullet275/bullet-src/src', 'rust/crates/mds-bullet/src/core',
           'rust/crates/mds-bullet/tests', 'rust/crates/mds-bullet-sys/shim',
           'rust/crates/mds-crtmath/src', 'tools/bullet-rust-discrete-world-check',
           'tools/bullet-rust-dbvt-check']
EXTRA = ['.github/workflows/bullet-discrete-world.yml', 'rust/crates/mds-bullet-sys/build.rs',
         'rust/crates/mds-bullet/Cargo.toml', 'rust/Cargo.lock', '.gitattributes', 'rust/.gitattributes']


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def paths(root=ROOT):
    result = {p for folder in FOLDERS for p in (root / folder).rglob('*')
              if p.is_file() and '__pycache__' not in p.parts}
    result.update(root / path for path in EXTRA)
    require(all(not p.is_symlink() for p in result), 'source symlinks forbidden')
    return sorted(result)


def snapshot(root=ROOT):
    return {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in paths(root)}


def generated_snapshot(root):
    return {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in sorted(root.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


def copy_sources(target):
    for folder in FOLDERS:
        shutil.copytree(ROOT / folder, target / folder, ignore=shutil.ignore_patterns('__pycache__'))
    for path in EXTRA:
        dst = target / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, dst)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def atomic_bytes(path, raw):
    temporary = path.with_name(path.name+'.pending')
    temporary.write_bytes(raw)
    temporary.replace(path)


def finalize_native(out, status, **expected):
    report = encoded(status)
    candidate = Capture(out, {'report.json':report})
    manifest = encoded({name:digest(candidate[name]) for name in candidate if name!='artifact-manifest.json'})
    admitted = admit_capture(Capture(out, {'report.json':report,'artifact-manifest.json':manifest}), **expected)
    atomic_bytes(out/'artifact-manifest.json',manifest)
    atomic_bytes(out/'report.json',report)
    return admitted


def admit_windows(directory, **expected):
    return admit_capture(Capture(directory), expected_host={('Windows','amd64'),('Windows','x86_64')},
                         expected_policy='mmd-win64-sse', **expected)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--policy',choices=['generic-reference','mmd-win64-sse'],required=True)
    parser.add_argument('--replay-dir',type=Path)
    args=parser.parse_args()
    out=args.out_dir.resolve()
    require(not out.exists(),'fresh unique output directory required')
    out.mkdir(parents=True)
    before=snapshot();canonical={p:digest((ROOT/p).read_bytes().replace(b'\r\n',b'\n')) for p in before}
    save(out/'source-start.json',before);save(out/'source-canonical.json',canonical)
    for path in before:
        target=out/'source'/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/path).read_bytes())
    inputs,cases=corpus();(out/'inputs.txt').write_bytes(inputs.encode());save(out/'cases.json',cases)
    commands=[];dependencies={}
    status={'schema':3 if args.replay_dir else 2,'status':'FAIL','base':BASE,'policy':args.policy,'native':'UNRUN','compiled_controls':'UNRUN',
            'public_world':'UNCHANGED_NATIVE_BACKEND','scope':'private default-DBVT discrete collision owner',
            'host':{'system':platform.system(),'machine':platform.machine(),'image':os.environ.get('ImageVersion')}}
    save(out/'report.json',status)
    settings={key:os.environ.get(key) for key in ENVIRONMENT}
    save(out/'environment-start.json',settings)
    tools={}
    def tool(name, executable):
        resolved=shutil.which(str(executable))
        require(resolved is not None,'resolved executable '+str(executable))
        resolved=str(Path(resolved).resolve())
        raw=Path(resolved).read_bytes(); identity=digest(raw)
        tools[name]={'path':resolved,'sha256':identity}
        save(out/'tools-start.json',tools)
        target=out/'tool-bytes'/identity;target.parent.mkdir(exist_ok=True)
        if not target.exists():target.write_bytes(raw)
        return resolved
    python=tool('python',sys.executable);git=tool('git','git');rustup=tool('rustup','rustup')
    def resolve_executable(executable):
        if Path(executable).is_file():return str(Path(executable).resolve())
        resolved=shutil.which(executable);require(resolved is not None,'actual command executable')
        return str(Path(resolved).resolve())
    def produced(argv):
        result=[]
        for i,arg in enumerate(argv):
            if arg=='-o':result.append(Path(argv[i+1]))
            elif arg.startswith(('/Fo','/Fe','/OUT:')):
                value=arg[5:] if arg.startswith('/OUT:') else arg[3:]
                if value and not value.endswith(('/', '\\')):result.append(Path(value))
        return result
    def run(argv,label,data=None,cwd=None,compile=False):
        require(snapshot()==before,'fixed source closure before '+label)
        require(not any(c['label']==label for c in commands),'unique command output label')
        argv=list(map(str,argv));argv[0]=resolve_executable(argv[0]);cwd=cwd or ROOT/'rust'
        before_includes=None
        if compile:
            run(argv,label+'-discovery',data,cwd)
            found=include_paths((out/(label+'-discovery.stdout')).read_bytes()+(out/(label+'-discovery.stderr')).read_bytes(),platform.system())
            before_includes={}
            for name in found:
                path=Path(name).resolve();require(path.is_file(),'discovered compiler include exists')
                raw=path.read_bytes();identity=digest(raw)
                target=out/'include-bytes'/identity;target.parent.mkdir(exist_ok=True)
                if not target.exists():target.write_bytes(raw)
                key=os.path.normcase(str(path));before_includes[key]=identity
            require(before_includes,'actual discovery include closure '+label)
            save(out/(label+'-includes-pre.json'),before_includes)
        for value in tools.values():require(digest(Path(value['path']).read_bytes())==value['sha256'],'tool preserved before '+label)
        record={'label':label,'argv':argv,'cwd':str(cwd),'stdin_sha256':None if data is None else digest(data),
                'tool':argv[0],'tool_sha256':digest(Path(argv[0]).read_bytes()),'executable_sha256':digest(Path(argv[0]).read_bytes())}
        record['inputs']={value:digest(Path(value).read_bytes()) for value in command_input_paths(argv,platform.system())}
        record['generated_inputs']=generated_snapshot(Path(argv[-3]).parents[2]) if label=='rust-observed-build' or label.startswith(('baseline-build-','mutant-build-')) else None
        commands.append(record);save(out/'commands.json',commands)
        start=time.monotonic()
        try:
            result=subprocess.run(argv,cwd=cwd,input=data,capture_output=True,timeout=600,env={**os.environ,'VSLANG':'1033'})
        except subprocess.TimeoutExpired as error:
            record.update(returncode=None,timeout=True)
            (out/(label+'.stdout')).write_bytes(error.stdout or b'');(out/(label+'.stderr')).write_bytes(error.stderr or b'')
            save(out/'commands.json',commands);raise
        record.update(returncode=result.returncode,timeout=False,seconds=time.monotonic()-start,
                      stdout_sha256=digest(result.stdout),stderr_sha256=digest(result.stderr))
        (out/(label+'.stdout')).write_bytes(result.stdout);(out/(label+'.stderr')).write_bytes(result.stderr);save(out/'commands.json',commands)
        artifacts=produced(argv)
        if label=='crt-build':artifacts=[out/('mds_crtmath.lib' if os.name=='nt' else 'libmds_crtmath.a'),out/'libmds_crtmath.rlib']
        if label=='archive-extract':artifacts=list((out/'extracted').iterdir())
        if label.startswith('extract-'):artifacts=[Path(next(a[5:] for a in argv if a.startswith('/OUT:')))]
        if label.endswith('-link'):
            artifacts.append(out/(label[:-5]+'.map'))
        if label in [name+'-'+mode for name in ['native','observed'] for mode in MODES]:artifacts.append(Path(argv[-1]))
        if os.name=='nt' and label in {'macro-build','macro-build-discovery'}:artifacts.append(out/'effective-macros.obj')
        record['outputs']={}
        for artifact in artifacts:
            if not artifact.is_file():continue
            retained=artifact
            if label.endswith('-discovery'):
                retained=out/'discovery'/label[:-10]/artifact.relative_to(out)
                retained.parent.mkdir(parents=True,exist_ok=True);retained.write_bytes(artifact.read_bytes())
            record['outputs'][retained.relative_to(out).as_posix()]=digest(retained.read_bytes())
        save(out/'commands.json',commands)
        if compile:
            found={}
            for name in include_paths(result.stdout+result.stderr,platform.system()):
                path=Path(name).resolve();require(path.is_file(),'actual compiler include exists')
                key=os.path.normcase(str(path));found[key]=digest(path.read_bytes());dependencies[key]=found[key]
            require(found==before_includes,'discovery pre-use and measured compile includes preserved '+label)
            save(out/(label+'-includes.json'),found)
        require(result.returncode==0,label+' must exit normally with zero status')
        require(snapshot()==before,'fixed source closure after '+label)
        return result.stdout
    try:
        machine=platform.machine().lower();system=platform.system()
        require((system,machine) in {('Windows','amd64'),('Windows','x86_64'),('Darwin','arm64'),('Linux','x86_64'),('Linux','aarch64'),('Linux','arm64')},'supported actual native host')
        run([python,'-B',HERE/'test_check.py','-v'],'helpers-normal')
        run([python,'-B','-O',HERE/'test_check.py','-v'],'helpers-optimized')
        status['head']=run([git,'rev-parse','HEAD'],'git-head').decode().strip()
        run([git,'status','--porcelain=v1'],'git-status')
        run([git,'ls-files','--eol'],'git-transport')
        run([git,'check-attr','--stdin','text','eol'],'git-attributes', ('\n'.join(sorted(before))+'\n').encode())
        rustc_path=run([rustup,'which','--toolchain','1.95.0','rustc'],'rust-compiler-path').decode().strip()
        tool('rustc',rustc_path)
        run([rustup,'run','1.95.0','rustc','-Vv'],'rust-version')
        rust=[rustup,'run','1.95.0','rustc','--edition=2021','-O']
        if not args.replay_dir:
            linker=tool('rust_linker','link.exe' if os.name=='nt' else 'cc')
            rust += ['-C','linker='+linker]
        run([*rust,'--crate-name','mds_crtmath','--crate-type','rlib,staticlib','--print','native-static-libs',ROOT/'rust/crates/mds-crtmath/src/lib.rs','--out-dir',out],'crt-build')
        crt=out/('mds_crtmath.lib' if os.name=='nt' else 'libmds_crtmath.a')
        suffix='.exe' if os.name=='nt' else ''
        focused=out/('dedicated'+suffix)
        rargs=[*rust,'--extern',f'mds_crtmath={out/"libmds_crtmath.rlib"}']
        run([*rargs,'--test','-D','warnings',ROOT/'rust/crates/mds-bullet/tests/discrete_collision_world.rs','-o',focused],'dedicated-build')
        focused_log=run([focused,'discrete_world_'],'dedicated-run').decode()
        require('6 passed; 0 failed; 0 ignored' in focused_log,'six real focused behavior tests')
        pure=out/('pure'+suffix)
        run([*rargs,'--test','-D','warnings',ROOT/'rust/crates/mds-bullet/tests/pure_bullet.rs','-o',pure],'pure-build')
        pure_log=run([pure],'pure-run').decode()
        require('97 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out' in pure_log,'unchanged native-free97 gate')
        shadow=out/'generated'
        copy_sources(shadow)
        originals={path:(shadow/path).read_bytes() for path in [OWNER,CORE+'dispatcher.rs',CORE+'world_objects.rs',NATIVE+'btCollisionDispatcher.cpp',NATIVE+'btCollisionWorld.cpp',SHIM]}
        changes=instrument(shadow,HERE);inverse(shadow,changes,originals);save(out/'observation-edits.json',changes)
        generated=generated_snapshot(shadow);save(out/'generated-start.json',generated)
        rust_exe=out/('rust-world'+suffix)
        run([*rargs,'--cfg','test',shadow/'tools/bullet-rust-discrete-world-check/runner.rs','-o',rust_exe],'rust-observed-build')
        plain_raw=run([rust_exe,args.policy],'rust-ordinary',inputs.encode());plain=validate(plain_raw,inputs)
        if args.replay_dir:
            require(args.policy=='mmd-win64-sse','Windows replay policy required')
            producer=admit_windows(args.replay_dir.absolute(),expected_head=status['head'],canonical_sources={p:(ROOT/p).read_bytes() for p in before},inputs=inputs,cases=cases)
            status['schema']=3;status['native']='WINDOWS_SOURCE_REPLAY';status['producer_report_sha256']=producer.report_sha256
        else:
            capture=out
            compiler=shutil.which(os.environ.get('CXX','cl' if os.name=='nt' else 'clang++'))
            require(compiler is not None,'actual compiler available');compiler=tool('compiler',compiler)
            status['compiler']={'path':compiler,'sha256':digest(Path(compiler).read_bytes())}
            run([compiler,'/?'] if os.name=='nt' else [compiler,'--version'],'compiler-version')
            src=ROOT/'recipes/bullet275/bullet-src/src';shim=ROOT/'rust/crates/mds-bullet-sys/shim'
            if os.name=='nt':tool('native_linker','link.exe')
            else:
                discovered=run([compiler,'-print-prog-name=ld'],'native-linker-path').decode().strip()
                tool('native_linker',discovered)
            archiver=tool('archiver','lib' if os.name=='nt' else 'ar')
            flags=native_flags(system,str(ROOT))
            save(out/'compiler-flags.json',flags)
            macro=out/'effective-macros.cpp';macro.write_bytes(macro_source())
            macro_exe=out/('effective-macros'+suffix)
            run([compiler,*flags,macro,'/Fe'+str(macro_exe),'/Fo'+str(out)+'/'] if os.name=='nt' else [compiler,*flags,macro,'-o',macro_exe],'macro-build',compile=True)
            macro_output=run([macro_exe],'actual-macros').decode()
            require('pointer_bits=64' in macro_output and 'scalar_bytes=4' in macro_output and 'MDS_BT_SYSTEM_MATH=<undefined>' in macro_output and 'sinf=mds_crt_sinf' in macro_output and 'BT_NO_PROFILE=1' in macro_output,'actual ABI/deterministic math macro policy')
            objects=[];bindings=[]
            sources=sorted(p for directory in ['BulletCollision','BulletDynamics','LinearMath'] for p in (src/directory).rglob('*.cpp'))
            require(len(sources)==114,'complete actual Bullet source archive')
            extension='.obj' if os.name=='nt' else '.o'
            def compile_object(source,obj,label,extra=()):
                run([compiler,*flags,*extra,'/c',source,'/Fo'+str(obj)] if os.name=='nt' else [compiler,*flags,*extra,'-c',source,'-o',obj],label,compile=True)
            for i,source in enumerate(sources):
                obj=out/(source.stem+extension);require(obj not in objects,'unique archive object name')
                compile_object(source,obj,f'compile-{i:03d}')
                objects.append(obj);bindings.append({'source':source.relative_to(ROOT).as_posix(),'source_sha256':digest(source.read_bytes()),'object':obj.name,'sha256':digest(obj.read_bytes())})
                if source.stem in {'btDbvt','btDbvtBroadphase'}:
                    expanded=run([compiler,*flags,'/E',source] if os.name=='nt' else [compiler,*flags,'-E',source],'expanded-'+source.stem)
                    observed=policy(expanded.decode(errors='strict'));require(observed['policy']==args.policy,'actual archive policy');save(out/('policy-'+source.stem+'.json'),observed)
            library=out/('BulletWorld.lib' if os.name=='nt' else 'libBulletWorld.a')
            run([archiver,'/NOLOGO','/OUT:'+str(library),*objects] if os.name=='nt' else [archiver,'rcs',library,*objects],'archive-build')
            listing=run([archiver,'/NOLOGO','/LIST',library] if os.name=='nt' else [archiver,'t',library],'archive-list').decode().splitlines()
            extracted=out/'extracted';extracted.mkdir();members={}
            require(len([s for s in listing if s.strip()])==len(objects),'exact complete archive member inventory')
            for obj in objects:
                matched=[line.strip() for line in listing if line.strip().replace('\\','/').split('/')[-1].lower()==obj.name.lower()]
                require(len(matched)==1,'one actual archive member '+obj.name);members[obj.name]=matched[0]
                if os.name=='nt': run([archiver,'/NOLOGO','/EXTRACT:'+matched[0],'/OUT:'+str(extracted/obj.name),library],'extract-'+obj.stem)
            if os.name!='nt': run([archiver,'x',library],'archive-extract',cwd=extracted)
            require(all((extracted/obj.name).read_bytes()==obj.read_bytes() for obj in objects),'actual extracted member equality')
            save(out/'archive-bindings.json',{'members':bindings,'archive_sha256':digest(library.read_bytes()),'actual_names':members})
            observed_objects=[]
            hook_header=HERE/'observer.h'
            hook_flags=['/FI'+str(hook_header),'/DDW_OBSERVED=1'] if os.name=='nt' else ['-include',hook_header,'-DDW_OBSERVED=1']
            for name in ['btCollisionDispatcher','btCollisionWorld']:
                obj=out/('observed-'+name+extension)
                compile_object(shadow/(NATIVE+name+'.cpp'),obj,'observed-'+name,hook_flags);observed_objects.append(obj)
            libs=(out/'crt-build.stderr').read_text().split('native-static-libs:')[-1].splitlines()[0].split() if os.name=='nt' else ([] if system=='Darwin' else ['-ldl','-lpthread','-lm'])
            for name,source,extra,prefix in [('native',HERE/'oracle.cpp',[],[]),('observed',shadow/'tools/bullet-rust-discrete-world-check/oracle.cpp',hook_flags,observed_objects)]:
                obj=out/(name+'-consumer'+extension);compile_object(source,obj,name+'-consumer-build',extra)
                expanded=run([compiler,*flags,*extra,'/E',source] if os.name=='nt' else [compiler,*flags,*extra,'-E',source],name+'-consumer-expanded')
                observed=policy(expanded.decode(errors='strict'));require(observed['policy']==args.policy,'actual public-shim consumer policy');save(out/(name+'-consumer-policy.json'),observed)
                exe=out/(name+suffix);linkmap=out/(name+'.map')
                link=[compiler,'/nologo','/MD','/EHsc',obj,*prefix,library,crt,'/Fe'+str(exe),'/link','/MAP:'+str(linkmap),'/VERBOSE:LIB',*libs] if os.name=='nt' else [compiler,obj,*prefix,library,crt,*libs,'-fuse-ld='+tools['native_linker']['path'],('-Wl,-map,' if system=='Darwin' else '-Wl,-Map,')+str(linkmap),'-o',exe]
                link_output=run(link,name+'-link')
                selected=selected_members(linkmap.read_bytes()+b'\n'+link_output+b'\n'+(out/(name+'-link.stderr')).read_bytes(),system,str(library))
                save(out/(name+'-link-selection.json'),sorted(selected))
                save(out/(name+'-binary.json'),{'produced_sha256':digest(exe.read_bytes()),'consumer_object_sha256':digest(obj.read_bytes()),'observed_override_objects':{p.name:digest(p.read_bytes()) for p in prefix}})
                for mode in MODES:
                    receipt=out/(name+'-allocator-'+mode+'.jsonl')
                    raw=run([exe,mode,receipt],name+'-'+mode,inputs.encode())
                    rows=validate(raw,inputs,native=True,observed=name=='observed');validate_allocator(receipt.read_bytes(),rows,mode)
            status['native']='ACTUAL_ORIGINAL_PUBLIC_SHIM_WITH_UNMODIFIED_ARCHIVE_CONTROL'
        if not args.replay_dir:
            for mode in MODES:
                validate_physical((capture/('observed-'+mode+'.stderr')).read_bytes(),inputs)
        controlled={}
        for mode in MODES:
            if args.replay_dir:
                bound=producer.bound_input(mode)
            else:
                observed=validate((capture/('observed-'+mode+'.stdout')).read_bytes(),inputs,native=True)
                baseline=validate((capture/('native-'+mode+'.stdout')).read_bytes(),inputs,native=True,observed=False)
                for name,rows in [('native',baseline),('observed',observed)]:validate_allocator((capture/(name+'-allocator-'+mode+'.jsonl')).read_bytes(),rows,mode)
                require(comparison(observed,False)==comparison(baseline,False),'original observer unchanged common outputs '+mode)
                bound=bind_inputs(inputs,observed).encode()
            (out/('bound-'+mode+'.txt')).write_bytes(bound)
            bound_raw=run([rust_exe,args.policy],'rust-bound-'+mode,bound)
            actual=validate(bound_raw,inputs)
            if args.replay_dir:controlled[mode]=producer.compare(mode,bound_raw)
            else:
                require(comparison(actual)==comparison(observed),'exact ordered owner/manifold/numeric equality '+mode)
                controlled[mode]=len(actual)
        status['ordinary_unbound']='WINDOWS_SOURCE_REPLAY' if args.replay_dir else ('EQUAL' if comparison(plain)==comparison(observed) else 'DIVERGED_FINITE_ALLOCATOR_ORDER')
        controls={}
        for name in MUTANTS:
            target=out/'mutants'/name
            shutil.copytree(shadow,target)
            clean_source=generated_snapshot(target)
            baseline_executable=out/('baseline-'+name+suffix)
            run([*rargs,'--cfg','test',target/'tools/bullet-rust-discrete-world-check/runner.rs','-o',baseline_executable],'baseline-build-'+name)
            clean=validate(run([baseline_executable,args.policy],'baseline-run-'+name,inputs.encode()),inputs)
            require(comparison(clean)==comparison(plain),'clean same-host complete baseline '+name)
            require(generated_snapshot(target)==clean_source,'clean baseline source unchanged '+name)
            edits=mutate(target,name);save(out/('mutation-'+name+'.json'),edits)
            executable=out/('mutant-'+name+suffix)
            run([*rargs,'--cfg','test',target/'tools/bullet-rust-discrete-world-check/runner.rs','-o',executable],'mutant-build-'+name)
            rows=validate(run([executable,args.policy],'mutant-run-'+name,inputs.encode()),inputs)
            differences=[i for i,(a,b) in enumerate(zip(comparison(clean),comparison(rows))) if a!=b]
            require(differences,'valid normally exiting owner-connection semantic rejection '+name)
            fields = semantic_fields(name)
            directed = [i for i,(a,b) in enumerate(zip(clean,rows)) if any(a[field] != b[field] for field in fields)]
            require(directed,'intended semantic field witness '+name)
            controls[name]={'normal_exit':True,'full_schema':True,'different_rows':differences,'binary_sha256':digest(executable.read_bytes()),'semantic_fields':fields,'semantic_rows':directed,'baseline_binary_sha256':digest(baseline_executable.read_bytes()),'source_before':clean_source,'source_after':generated_snapshot(target)}
        save(out/'semantic-controls.json',controls)
        require(generated_snapshot(shadow)==generated,'generated observation source preserved')
        inverse(shadow,changes,originals)
        require(all(digest(Path(p).read_bytes())==identity for p,identity in dependencies.items()),'actual native include closure preserved')
        save(out/'native-includes-end.json',dependencies);save(out/'generated-end.json',generated_snapshot(shadow))
        status.update(status='CONTROLLED_PASS',compiled_controls=len(controls),checkpoints=len(inputs.splitlines()),cases=len(cases),controlled=controlled,
                      limits=LIMITS)
    except Exception as error:
        status.update(status='FAIL',error=str(error));raise
    finally:
        final=snapshot();save(out/'source-end.json',final)
        if final!=before: status.update(status='FAIL',error='fixed source closure changed')
        try:
            save(out/'environment-end.json',{key:os.environ.get(key) for key in ENVIRONMENT})
            for value in tools.values():require(digest(Path(value['path']).read_bytes())==value['sha256'],'resolved tool end preservation')
            save(out/'tools-start.json',tools);save(out/'tools-end.json',tools)
            if status['status']=='CONTROLLED_PASS' and not args.replay_dir:
                save(out/'producer.json',{'schema':1,'system':system,'root':str(ROOT),'out':str(out),'tools':{name:value['path'] for name,value in tools.items()},'archive_names':members})
                finalize_native(out,status,expected_head=status['head'],canonical_sources={p:(ROOT/p).read_bytes() for p in before},inputs=inputs,cases=cases,
                                expected_host={(system,machine)},expected_policy=args.policy)
            else:
                if status['status']=='CONTROLLED_PASS':
                    status['limits']=LIMITS+['replay Rust inner linker chain unobserved']
                    replay_report(status,status['head'],inputs,cases)
                    schedule=command_schedule({'system':system,'root':str(ROOT),'out':str(out),'tools':{name:value['path'] for name,value in tools.items()}},[],args.policy,[],replay=True)
                    require([(record['label'],record['argv'],record['cwd']) for record in commands]==[(label,argv,cwd) for label,argv,cwd,_,_,_ in schedule], 'exact completed replay command schedule')
                    require(all(type(record['returncode']) is int and record['returncode']==0 and record['timeout'] is False for record in commands),'all current-Rust replay commands normally exit')
                save(out/'report.json',status)
                save(out/'artifact-manifest.json',{p.relative_to(out).as_posix():digest(p.read_bytes()) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='artifact-manifest.json'})
        except Exception as error:
            status.update(status='FAIL',error=str(error));save(out/'report.json',status)
            save(out/'artifact-manifest.json',{p.relative_to(out).as_posix():digest(p.read_bytes()) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='artifact-manifest.json'})
            raise
        require(final==before,'unchanged source-before/end closure')
        print(json.dumps(status,sort_keys=True))


if __name__=='__main__':
    main()
