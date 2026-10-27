#!/usr/bin/env python3
"""Hosted-only original public-shim collision-world capture and strict Rust replay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

from cases import corpus
from hooks import CORE, NATIVE, OWNER, SHIM, MUTANTS, instrument, inverse, mutate, require
from trace import bind_inputs, comparison, validate, validate_allocator, validate_physical, decode_json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = 'c8dc8a387a9d37442a84dbd8a3b81c90898b6d6d'
MODES = ['ascending', 'descending', 'alternating', 'ordinary']
FOLDERS = ['recipes/bullet275/bullet-src/src', 'rust/crates/mds-bullet/src/core',
           'rust/crates/mds-bullet/tests', 'rust/crates/mds-bullet-sys/shim',
           'rust/crates/mds-crtmath/src', 'tools/bullet-rust-discrete-world-check',
           'tools/bullet-rust-dbvt-check']
EXTRA = ['.github/workflows/bullet-discrete-world.yml', 'rust/crates/mds-bullet-sys/build.rs',
         'rust/crates/mds-bullet/Cargo.toml', 'rust/Cargo.lock', '.gitattributes']


def digest(data):
    return hashlib.sha256(data).hexdigest()


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


def policy(text):
    functions = {}
    for name, count in [('Intersect',2),('Select',3),('Merge',3)]:
        pattern = name + r'\s*\(\s*const\s+btDbvtAabbMm\s*&\s*\w+\s*,\s*const\s+btDbvtAabbMm\s*&\s*\w+'
        pattern += (r'\s*,[^)]+' if count == 3 else '') + r'\s*\)\s*\{'
        matches = list(re.finditer(pattern,text)); require(len(matches)==1,'one expanded DBVT '+name)
        start = matches[0].end()-1; end = start+1; depth = 1
        while depth and end<len(text):
            depth += (text[end]=='{')-(text[end]=='}'); end += 1
        require(depth==0,'complete expanded DBVT body'); functions[name]=text[start:end]
    if all(token in functions[name] for name,token in [('Intersect','_mm_cmplt_ps'),('Select','_mm_cmple_ss'),('Merge','_mm_min_ps')]):
        name = 'mmd-win64-sse'
    else:
        require(all('_mm_' not in body for body in functions.values()) and 'Proximity' in functions['Select'], 'known unmixed DBVT numeric policy')
        name = 'generic-reference'
    return {'policy':name,'functions':functions}


def inventory(expected, actual):
    require(isinstance(expected, dict) and set(expected)==set(actual), 'exact capture inventory')
    for name, identity in expected.items():
        require(isinstance(name,str) and name and ':' not in name and '\\' not in name
                and not Path(name).is_absolute() and all(part not in {'','.','..'} for part in name.split('/')), 'safe capture path')
        require(isinstance(identity,str) and re.fullmatch('[0-9a-f]{64}',identity) is not None, 'capture digest framing')
        require(actual[name]==identity,'capture identity '+name)


def capture_valid(capture, canonical, inputs):
    manifest = decode_json((capture/'artifact-manifest.json').read_text())
    actual = {p.relative_to(capture).as_posix() for p in capture.rglob('*') if p.is_file()} - {'artifact-manifest.json'}
    require(all(not p.is_symlink() for p in capture.rglob('*')), 'capture symlinks forbidden')
    inventory(manifest,{name:digest((capture/name).read_bytes()) for name in actual})
    report = decode_json((capture/'report.json').read_text())
    require(report['status']=='CONTROLLED_PASS' and report['host']['system']=='Windows' and report['policy']=='mmd-win64-sse', 'actual current Windows producer')
    require(decode_json((capture/'source-canonical.json').read_text())==canonical,'current Windows source closure')
    physical = decode_json((capture/'source-start.json').read_text())
    require(set(physical)==set(canonical),'Windows physical source closure')
    for path, identity in physical.items():
        raw = (capture/'source'/path).read_bytes()
        require(digest(raw)==identity and digest(raw.replace(b'\r\n',b'\n'))==canonical[path], 'exact copied Windows physical source '+path)
    require((capture/'inputs.txt').read_bytes()==inputs.encode(),'exact Windows native input bytes')
    return report


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
    status={'schema':1,'status':'FAIL','base':BASE,'policy':args.policy,'native':'UNRUN','compiled_controls':'UNRUN',
            'public_world':'UNCHANGED_NATIVE_BACKEND','scope':'private default-DBVT discrete collision owner',
            'host':{'system':platform.system(),'machine':platform.machine(),'image':os.environ.get('ImageVersion')}}
    save(out/'report.json',status)
    def run(argv,label,data=None,cwd=None,compile=False):
        require(snapshot()==before,'fixed source closure before '+label)
        require(not any(c['label']==label for c in commands),'unique command output label')
        argv=list(map(str,argv));cwd=cwd or ROOT/'rust'
        record={'label':label,'argv':argv,'cwd':str(cwd),'stdin_sha256':None if data is None else digest(data)}
        if Path(argv[0]).is_file(): record['executable_sha256']=digest(Path(argv[0]).read_bytes())
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
        if compile:
            found={}
            for line in (result.stdout+result.stderr).decode(errors='replace').splitlines():
                match=re.match(r'^Note: including file:\s+(.+)$',line) if os.name=='nt' else re.match(r'^\.+ (.+)$',line)
                if match:
                    path=Path(match[1]).resolve();require(path.is_file(),'actual compiler include exists')
                    found[str(path)]=digest(path.read_bytes());dependencies[str(path)]=found[str(path)]
            require(found,'actual consumer/include closure '+label);save(out/(label+'-includes.json'),found)
        require(result.returncode==0,label+' must exit normally with zero status')
        require(snapshot()==before,'fixed source closure after '+label)
        return result.stdout
    try:
        machine=platform.machine().lower();system=platform.system()
        require((system,machine) in {('Windows','amd64'),('Windows','x86_64'),('Darwin','arm64'),('Linux','x86_64'),('Linux','aarch64'),('Linux','arm64')},'supported actual native host')
        run([sys.executable,'-B',HERE/'test_check.py','-v'],'helpers-normal')
        run([sys.executable,'-B','-O',HERE/'test_check.py','-v'],'helpers-optimized')
        status['head']=run(['git','rev-parse','HEAD'],'git-head').decode().strip()
        run(['git','status','--porcelain=v1'],'git-status')
        run(['git','ls-files','--eol'],'git-transport')
        run(['git','check-attr','--stdin','text','eol'],'git-attributes', ('\n'.join(before)+'\n').encode())
        run(['rustup','run','1.95.0','rustc','-Vv'],'rust-version')
        rust=['rustup','run','1.95.0','rustc','--edition=2021','-O']
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
            capture=args.replay_dir.resolve();producer=capture_valid(capture,canonical,inputs)
            require(producer['head']==status['head'],'current Windows producer commit')
            status['native']='WINDOWS_SOURCE_REPLAY';status['producer_report_sha256']=digest((capture/'report.json').read_bytes())
        else:
            capture=out
            compiler=shutil.which(os.environ.get('CXX','cl' if os.name=='nt' else 'clang++'))
            require(compiler is not None,'actual compiler available');compiler=str(Path(compiler).resolve())
            status['compiler']={'path':compiler,'sha256':digest(Path(compiler).read_bytes())}
            run([compiler,'/?'] if os.name=='nt' else [compiler,'--version'],'compiler-version')
            src=ROOT/'recipes/bullet275/bullet-src/src';shim=ROOT/'rust/crates/mds-bullet-sys/shim'
            flags=['/nologo','/std:c++17','/O2','/MD','/EHsc','/fp:precise','/W0','/DBT_NO_PROFILE=1','/DWIN32','/showIncludes','/I'+str(src),'/I'+str(shim),'/FI'+str(shim/'det_math.h')] if os.name=='nt' else ['-std=c++17','-O2','-ffp-contract=off','-fno-fast-math','-fdeclspec','-w','-DBT_NO_PROFILE=1','-H','-I',shim/'sse_emu','-I',src,'-I',shim,'-include',shim/'det_math.h']
            save(out/'compiler-flags.json',list(map(str,flags)))
            macro=out/'effective-macros.cpp'
            macro_code='#include "LinearMath/btScalar.h"\n#include <cstdio>\n#define S_(x) #x\n#define S(x) S_(x)\nint main(){\n'
            for key in ['BT_USE_SSE','BT_USE_DOUBLE_PRECISION','BT_NO_PROFILE','WIN32','_MSC_VER','_M_X64','__x86_64__','__aarch64__','MDS_BT_SYSTEM_MATH','sinf','cosf','atan2f']:
                macro_code+=f'#ifdef {key}\nputs("{key}=" S({key}));\n#else\nputs("{key}=<undefined>");\n#endif\n'
            macro.write_text(macro_code+'printf("pointer_bits=%zu\\nscalar_bytes=%zu\\n",sizeof(void*)*8,sizeof(btScalar));}\n')
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
            run(['lib','/NOLOGO','/OUT:'+str(library),*objects] if os.name=='nt' else ['ar','rcs',library,*objects],'archive-build')
            listing=run(['lib','/NOLOGO','/LIST',library] if os.name=='nt' else ['ar','t',library],'archive-list').decode().splitlines()
            extracted=out/'extracted';extracted.mkdir();members={}
            require(len([s for s in listing if s.strip()])==len(objects),'exact complete archive member inventory')
            for obj in objects:
                matched=[line.strip() for line in listing if line.strip().replace('\\','/').split('/')[-1].lower()==obj.name.lower()]
                require(len(matched)==1,'one actual archive member '+obj.name);members[obj.name]=matched[0]
                if os.name=='nt': run(['lib','/NOLOGO','/EXTRACT:'+matched[0],'/OUT:'+str(extracted/obj.name),library],'extract-'+obj.stem)
            if os.name!='nt': run(['ar','x',library],'archive-extract',cwd=extracted)
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
                link=[compiler,'/nologo','/MD','/EHsc',obj,*prefix,library,crt,'/Fe'+str(exe),'/link','/MAP:'+str(linkmap),'/VERBOSE:LIB',*libs] if os.name=='nt' else [compiler,obj,*prefix,library,crt,*libs,('-Wl,-map,' if system=='Darwin' else '-Wl,-Map,')+str(linkmap),'-o',exe]
                link_output=run(link,name+'-link');link_lines=(linkmap.read_bytes()+link_output).decode(errors='replace').splitlines()
                selected={}
                for member in ['btDbvt','btDbvtBroadphase','btDiscreteDynamicsWorld',*(['btCollisionWorld','btCollisionDispatcher'] if name=='native' else [])]:
                    matches=[line for line in link_lines if member+extension in line and library.stem in line]
                    require(matches,'actual selected public-shim archive member '+member);selected[member]=matches
                save(out/(name+'-link-selection.json'),selected)
                save(out/(name+'-binary.json'),{'produced_sha256':digest(exe.read_bytes()),'consumer_object_sha256':digest(obj.read_bytes()),'observed_override_objects':{p.name:digest(p.read_bytes()) for p in prefix}})
                for mode in MODES:
                    receipt=out/(name+'-allocator-'+mode+'.jsonl')
                    raw=run([exe,mode,receipt],name+'-'+mode,inputs.encode())
                    rows=validate(raw,inputs,native=True,observed=name=='observed');validate_allocator(receipt.read_bytes(),rows,mode)
            status['native']='ACTUAL_ORIGINAL_PUBLIC_SHIM_WITH_UNMODIFIED_ARCHIVE_CONTROL'
        for mode in MODES:
            validate_physical((capture/('observed-'+mode+'.stderr')).read_bytes(),inputs)
        controlled={}
        for mode in MODES:
            observed=validate((capture/('observed-'+mode+'.stdout')).read_bytes(),inputs,native=True)
            baseline=validate((capture/('native-'+mode+'.stdout')).read_bytes(),inputs,native=True,observed=False)
            for name,rows in [('native',baseline),('observed',observed)]: validate_allocator((capture/(name+'-allocator-'+mode+'.jsonl')).read_bytes(),rows,mode)
            require(comparison(observed,False)==comparison(baseline,False),'original observer unchanged common outputs '+mode)
            bound=bind_inputs(inputs,observed);(out/('bound-'+mode+'.txt')).write_bytes(bound.encode())
            actual=validate(run([rust_exe,args.policy],'rust-bound-'+mode,bound.encode()),inputs)
            require(comparison(actual)==comparison(observed),'exact ordered owner/manifold/numeric equality '+mode)
            controlled[mode]=len(actual)
        status['ordinary_unbound']='EQUAL' if comparison(plain)==comparison(observed) else 'DIVERGED_FINITE_ALLOCATOR_ORDER'
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
            fields = ['events','pairs','manifolds'] if name in {'omit-pair-calculation','omit-dispatch','recreate-dispatcher','reverse-owner-order','reverse-dispatch-order','omit-linear-preclean'} else ['header'] if name == 'default-force' else ['bodies']
            directed = [i for i,(a,b) in enumerate(zip(clean,rows)) if any(a[field] != b[field] for field in fields)]
            require(directed,'intended semantic field witness '+name)
            controls[name]={'normal_exit':True,'full_schema':True,'different_rows':differences,'binary_sha256':digest(executable.read_bytes()),'semantic_fields':fields,'semantic_rows':directed,'baseline_binary_sha256':digest(baseline_executable.read_bytes()),'source_before':clean_source,'source_after':generated_snapshot(target)}
        save(out/'semantic-controls.json',controls)
        require(generated_snapshot(shadow)==generated,'generated observation source preserved')
        inverse(shadow,changes,originals)
        require(all(digest(Path(p).read_bytes())==identity for p,identity in dependencies.items()),'actual native include closure preserved')
        save(out/'native-includes-end.json',dependencies);save(out/'generated-end.json',generated_snapshot(shadow))
        status.update(status='CONTROLLED_PASS',compiled_controls=len(controls),checkpoints=len(inputs.splitlines()),cases=len(cases),controlled=controlled,
                      limits=['finite allocator/corpus order only','debug drawer null','native physical deletes separate','no public backend or solver/CCD/MMD adoption'])
    except Exception as error:
        status['error']=str(error);raise
    finally:
        final=snapshot();save(out/'source-end.json',final)
        if final!=before: status.update(status='FAIL',error='fixed source closure changed')
        save(out/'report.json',status)
        manifest={p.relative_to(out).as_posix():digest(p.read_bytes()) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='artifact-manifest.json'}
        save(out/'artifact-manifest.json',manifest)
        require(final==before,'unchanged source-before/end closure')
        print(json.dumps(status,sort_keys=True))


if __name__=='__main__':
    main()
