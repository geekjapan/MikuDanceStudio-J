#!/usr/bin/env python3
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

from cases import corpus
from evidence import (Capture, ENVIRONMENT, LIMITS, admit_capture, digest, include_occurrences, include_projection, decode_archive, archive_listing, inventory,
                      macro_source, native_flags, policy, selected_members, semantic_fields, command_files, command_schedule, command_receipts, replay_report)
from hooks import CORE, NATIVE, OWNER, SHIM, MUTANTS, OBSERVATION_PATHS, NATIVE_OBSERVATIONS, instrument, inverse, mutate, require
from trace import validate_noninterference, bind_inputs, comparison, validate, validate_allocator, validate_physical

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = '816df8133b021359a2684c2ad5fd3666583c7c60'
MODES = ['ascending', 'descending', 'alternating', 'ordinary']
FOLDERS = ['recipes/bullet275/bullet-src/src', 'rust/crates/mds-bullet/src/core',
           'rust/crates/mds-bullet/tests', 'rust/crates/mds-bullet-sys/shim',
           'rust/crates/mds-crtmath/src', 'tools/bullet-rust-dynamics-world-check',
           'tools/bullet-rust-dbvt-check']
EXTRA = ['.github/workflows/bullet-dynamics-world.yml', 'rust/crates/mds-bullet-sys/build.rs',
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


def executable_identity(executable):
    invocation=shutil.which(str(executable))
    require(invocation is not None,'resolved executable '+str(executable))
    invocation=str(Path(invocation).absolute())
    target=Path(invocation).resolve(strict=True)
    return {'path':invocation,'target':str(target),'sha256':digest(target.read_bytes())}


def retain_outputs(outputs, out, *, success):
    retained={}
    for output in outputs:
        artifact=Path(output.physical)
        if not artifact.is_file():
            require(not success,'successful command missing output '+output.retained)
            continue
        target=out/output.retained
        if target!=artifact:
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(artifact.read_bytes())
        retained[output.retained]=digest(target.read_bytes())
    return retained


def acquire_include_bindings(occurrences, cwd, out):
    bindings=[]
    for occurrence in occurrences:
        path=Path(occurrence['raw'])
        if not path.is_absolute():path=Path(cwd)/path
        target=path.resolve(strict=True)
        require(target.is_file(), 'include resolves to regular file')
        raw=target.read_bytes(); value=digest(raw)
        retained=out/'include-bytes'/value;retained.parent.mkdir(exist_ok=True)
        if not retained.exists():retained.write_bytes(raw)
        bindings.append({**occurrence,'target':os.path.normcase(str(target)),'sha256':value})
    return bindings


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
    commands=[];include_aliases={}
    status={'schema':7 if args.replay_dir else 6,'status':'FAIL','base':BASE,'policy':args.policy,'native':'UNRUN','compiled_controls':'UNRUN',
            'public_world':'UNCHANGED_NATIVE_BACKEND','scope':'private default-DBVT dynamics owner',
            'host':{'system':platform.system(),'machine':platform.machine(),'image':os.environ.get('ImageVersion')}}
    save(out/'report.json',status)
    settings={key:os.environ.get(key) for key in ENVIRONMENT}
    save(out/'environment-start.json',settings)
    tools={}
    def tool(name, executable):
        binding=executable_identity(executable)
        tools[name]=binding
        save(out/'tools-start.json',tools)
        target=out/'tool-bytes'/binding['sha256'];target.parent.mkdir(exist_ok=True)
        if not target.exists():target.write_bytes(Path(binding['target']).read_bytes())
        return binding['path']
    python=tool('python',sys.executable);git=tool('git','git');rustup=tool('rustup','rustup')
    file_context={'system':platform.system(),'root':str(ROOT),'out':str(out),'archive_objects':tuple(
        p.stem+('.obj' if os.name=='nt' else '.o') for p in sorted((ROOT/'recipes/bullet275/bullet-src/src').rglob('*.cpp'))
        if p.relative_to(ROOT/'recipes/bullet275/bullet-src/src').parts[0] in {'BulletCollision','BulletDynamics','LinearMath'})}
    archive_indexes=()
    def run(argv,label,data=None,cwd=None,compile=False):
        require(snapshot()==before,'fixed source closure before '+label)
        require(not any(c['label']==label for c in commands),'unique command output label')
        argv=list(map(str,argv));binding=executable_identity(argv[0]);argv[0]=binding['path'];cwd=cwd or ROOT/'rust'
        before_includes=None
        if compile:
            run(argv,label+'-discovery',data,cwd)
            occurrences=include_occurrences((out/(label+'-discovery.stdout')).read_bytes(),(out/(label+'-discovery.stderr')).read_bytes(),platform.system())
            pre_bindings=acquire_include_bindings(occurrences,cwd,out)
            before_includes,pre_aliases=include_projection(pre_bindings,occurrences,platform.system())
            save(out/(label+'-includes-pre.json'),before_includes)
            save(out/(label+'-include-bindings.json'),{'schema':1,'label':label,'cwd':str(cwd),'pre':pre_bindings,'post':[]})
        for value in tools.values():require(executable_identity(value['path'])==value,'tool preserved before '+label)
        require(executable_identity(argv[0])==binding,'invocation target preserved before '+label)
        record={'label':label,'argv':argv,'cwd':str(cwd),'stdin_sha256':None if data is None else digest(data),
                'tool':argv[0],'tool_target':binding['target'],'tool_sha256':binding['sha256'],'executable_sha256':binding['sha256']}
        roles=command_files(label,argv,file_context,archive_indexes=archive_indexes)
        record['inputs']={value:digest(Path(value).read_bytes()) for value in roles.inputs}
        record['generated_inputs']=generated_snapshot(Path(argv[-3]).parents[2]) if label=='rust-observed-build' or label.startswith(('baseline-build-','mutant-build-')) else None
        commands.append(record);save(out/'commands.json',commands)
        start=time.monotonic()
        try:
            record['start_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
            with subprocess.Popen(argv,cwd=cwd,stdin=subprocess.PIPE if data is not None else None,
                                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={**os.environ,'VSLANG':'1033'}) as process:
                record['pid']=process.pid
                save(out/'commands.json',commands)
                try:
                    stdout,stderr=process.communicate(data,timeout=600)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout,stderr=process.communicate()
                    raise subprocess.TimeoutExpired(argv,600,output=stdout,stderr=stderr)
                result=subprocess.CompletedProcess(argv,process.returncode,stdout,stderr)
            record['end_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        except subprocess.TimeoutExpired as error:
            record.update(end_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),returncode=process.returncode,timeout=True,outputs=retain_outputs(roles.outputs,out,success=False),
                          stdout_sha256=digest(error.stdout or b''),stderr_sha256=digest(error.stderr or b''))
            (out/(label+'.stdout')).write_bytes(error.stdout or b'');(out/(label+'.stderr')).write_bytes(error.stderr or b'')
            save(out/'commands.json',commands);raise
        record.update(returncode=result.returncode,timeout=False,seconds=time.monotonic()-start,
                      stdout_sha256=digest(result.stdout),stderr_sha256=digest(result.stderr))
        (out/(label+'.stdout')).write_bytes(result.stdout);(out/(label+'.stderr')).write_bytes(result.stderr);save(out/'commands.json',commands)
        record['outputs']=retain_outputs(roles.outputs,out,success=False)
        save(out/'commands.json',commands)
        if result.returncode==0:require(set(record['outputs'])=={value.retained for value in roles.outputs},'successful command missing output '+label)
        if compile:
            occurrences=include_occurrences(result.stdout,result.stderr,platform.system())
            post_bindings=acquire_include_bindings(occurrences,cwd,out)
            found,post_aliases=include_projection(post_bindings,occurrences,platform.system())
            save(out/(label+'-include-bindings.json'),{'schema':1,'label':label,'cwd':str(cwd),'pre':pre_bindings,'post':post_bindings})
            save(out/(label+'-includes.json'),found)
            require(found==before_includes and post_aliases==pre_aliases,'discovery pre-use and measured compile includes preserved '+label)
            for spelling,binding in post_aliases.items():
                alias=(str(cwd),spelling)
                require(alias not in include_aliases or include_aliases[alias]==binding,'include alias preserved across compilations')
                include_aliases[alias]=binding
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
        run([git,'ls-files','--eol'],'git-transport',cwd=ROOT)
        run([git,'check-attr','--stdin','text','eol'],'git-attributes', ('\n'.join(sorted(before))+'\n').encode(),cwd=ROOT)
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
        run([*rargs,'--test','-D','warnings',ROOT/'rust/crates/mds-bullet/tests/discrete_dynamics_world.rs','-o',focused],'dedicated-build')
        focused_log=run([focused,'dynamics_world_'],'dedicated-run').decode()
        require('6 passed; 0 failed; 0 ignored' in focused_log,'six real focused behavior tests')
        pure=out/('pure'+suffix)
        run([*rargs,'--test','-D','warnings',ROOT/'rust/crates/mds-bullet/tests/pure_bullet.rs','-o',pure],'pure-build')
        pure_log=run([pure],'pure-run').decode()
        require('97 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out' in pure_log,'unchanged native-free97 gate')
        shadow=out/'generated'
        copy_sources(shadow)
        originals={path:(shadow/path).read_bytes() for path in OBSERVATION_PATHS}
        changes=instrument(shadow,HERE);inverse(shadow,changes,originals);save(out/'observation-edits.json',changes)
        generated=generated_snapshot(shadow);save(out/'generated-start.json',generated)
        rust_exe=out/('rust-world'+suffix)
        run([*rargs,'--cfg','test',shadow/'tools/bullet-rust-dynamics-world-check/runner.rs','-o',rust_exe],'rust-observed-build')
        plain_raw=run([rust_exe,args.policy],'rust-ordinary',inputs.encode());plain=validate(plain_raw,inputs)
        if args.replay_dir:
            require(args.policy=='mmd-win64-sse','Windows replay policy required')
            producer=admit_windows(args.replay_dir.absolute(),expected_head=status['head'],canonical_sources={p:(ROOT/p).read_bytes() for p in before},inputs=inputs,cases=cases)
            status['schema']=7;status['native']='WINDOWS_SOURCE_REPLAY';status['producer_report_sha256']=producer.report_sha256
        else:
            capture=out
            compiler=shutil.which(os.environ.get('CXX','cl' if os.name=='nt' else 'clang++'))
            require(compiler is not None,'actual compiler available');compiler=tool('compiler',compiler)
            status['compiler']=dict(tools['compiler'])
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
            parsed_archive=decode_archive(library.read_bytes())
            archive_indexes=tuple(parsed_archive.bsd_indexes) if system=='Darwin' else ()
            archive_listing(parsed_archive,[line.strip() for line in listing if line.strip()],system)
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
            for name,source_path in NATIVE_OBSERVATIONS:
                obj=out/('observed-'+name+extension)
                compile_object(shadow/source_path,obj,'observed-'+name,hook_flags);observed_objects.append(obj)
            libs=(out/'crt-build.stderr').read_text().split('native-static-libs:')[-1].splitlines()[0].split() if os.name=='nt' else ([] if system=='Darwin' else ['-ldl','-lpthread','-lm'])
            for name,source,extra,prefix in [('native',HERE/'oracle.cpp',[],[]),('observed',shadow/'tools/bullet-rust-dynamics-world-check/oracle.cpp',hook_flags,observed_objects)]:
                obj=out/(name+'-consumer'+extension);compile_object(source,obj,name+'-consumer-build',extra)
                expanded=run([compiler,*flags,*extra,'/E',source] if os.name=='nt' else [compiler,*flags,*extra,'-E',source],name+'-consumer-expanded')
                observed=policy(expanded.decode(errors='strict'));require(observed['policy']==args.policy,'actual public-shim consumer policy');save(out/(name+'-consumer-policy.json'),observed)
                exe=out/(name+suffix);linkmap=out/(name+'.map')
                link=[compiler,'/nologo','/MD','/EHsc',obj,*prefix,library,crt,'/Fe'+str(exe),'/link','/MAP:'+str(linkmap),'/VERBOSE:LIB',*libs] if os.name=='nt' else [compiler,obj,*prefix,library,crt,*libs,'-fuse-ld='+tools['native_linker']['path'],('-Wl,-map,' if system=='Darwin' else '-Wl,-Map,')+str(linkmap),'-o',exe]
                link_output=run(link,name+'-link')
                link_data=linkmap.read_bytes()
                if system!='Darwin':link_data+=b'\n'+link_output+b'\n'+(out/(name+'-link.stderr')).read_bytes()
                selected=selected_members(link_data,system,str(library))
                save(out/(name+'-link-selection.json'),sorted(selected))
                save(out/(name+'-binary.json'),{'produced_sha256':digest(exe.read_bytes()),'consumer_object_sha256':digest(obj.read_bytes()),'observed_override_objects':{p.name:digest(p.read_bytes()) for p in prefix}})
                for mode in MODES:
                    receipt=out/(name+'-allocator-'+mode+'.jsonl')
                    raw=run([exe,mode,receipt],name+'-'+mode,inputs.encode())
                    rows=validate(raw,inputs,native=True,observed=name=='observed');validate_allocator(receipt.read_bytes(),rows,mode,domain='unmodified-control' if name=='native' else 'generated-dbvt-node-sites')
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
                for name,rows in [('native',baseline),('observed',observed)]:validate_allocator((capture/(name+'-allocator-'+mode+'.jsonl')).read_bytes(),rows,mode,domain='unmodified-control' if name=='native' else 'generated-dbvt-node-sites')
                validate_noninterference((capture/('native-allocator-'+mode+'.jsonl')).read_bytes(),baseline,(capture/('observed-allocator-'+mode+'.jsonl')).read_bytes(),observed,mode)
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
            run([*rargs,'--cfg','test',target/'tools/bullet-rust-dynamics-world-check/runner.rs','-o',baseline_executable],'baseline-build-'+name)
            clean=validate(run([baseline_executable,args.policy],'baseline-run-'+name,inputs.encode()),inputs)
            require(comparison(clean)==comparison(plain),'clean same-host complete baseline '+name)
            require(generated_snapshot(target)==clean_source,'clean baseline source unchanged '+name)
            edits=mutate(target,name);save(out/('mutation-'+name+'.json'),edits)
            executable=out/('mutant-'+name+suffix)
            run([*rargs,'--cfg','test',target/'tools/bullet-rust-dynamics-world-check/runner.rs','-o',executable],'mutant-build-'+name)
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
        ending=[];end_dependencies={}
        for (cwd,spelling),binding in include_aliases.items():
            acquired=acquire_include_bindings([{'stream':'stdout','ordinal':0,'raw':spelling}],cwd,out)[0]
            ending.append({'cwd':cwd,'raw':spelling,'target':acquired['target'],'sha256':acquired['sha256']})
            end_dependencies[acquired['target']]=acquired['sha256']
            require((acquired['target'],acquired['sha256'])==binding,'actual native include alias end preserved')
        save(out/'native-include-bindings-end.json',{'schema':1,'bindings':ending})
        save(out/'native-includes-end.json',end_dependencies);save(out/'generated-end.json',generated_snapshot(shadow))
        status.update(status='CONTROLLED_PASS',compiled_controls=len(controls),checkpoints=len(inputs.splitlines()),cases=len(cases),controlled=controlled,
                      limits=LIMITS)
    except Exception as error:
        status.update(status='FAIL',error=str(error));raise
    finally:
        final=snapshot();save(out/'source-end.json',final)
        if final!=before: status.update(status='FAIL',error='fixed source closure changed')
        try:
            save(out/'environment-end.json',{key:os.environ.get(key) for key in ENVIRONMENT})
            end_tools={name:executable_identity(value['path']) for name,value in tools.items()}
            save(out/'tools-end.json',end_tools)
            require(end_tools==tools,'resolved tool end preservation')
            if status['status']=='CONTROLLED_PASS' and not args.replay_dir:
                save(out/'producer.json',{'schema':3,'system':system,'root':str(ROOT),'out':str(out),'tools':{name:value['path'] for name,value in tools.items()},'archive_names':members})
                finalize_native(out,status,expected_head=status['head'],canonical_sources={p:(ROOT/p).read_bytes() for p in before},inputs=inputs,cases=cases,
                                expected_host={(system,machine)},expected_policy=args.policy)
            else:
                if status['status']=='CONTROLLED_PASS':
                    status['limits']=LIMITS+['replay Rust inner linker chain unobserved']
                    replay_report(status,status['head'],inputs,cases)
                    schedule=command_schedule({'system':system,'root':str(ROOT),'out':str(out),'tools':{name:value['path'] for name,value in tools.items()}},[],args.policy,[],replay=True)
                    require([(record['label'],record['argv'],record['cwd']) for record in commands]==[(label,argv,cwd) for label,argv,cwd,_,_,_ in schedule], 'exact completed replay command schedule')
                    require(all(type(record['returncode']) is int and record['returncode']==0 and record['timeout'] is False for record in commands),'all current-Rust replay commands normally exit')
                    command_receipts(commands)
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
