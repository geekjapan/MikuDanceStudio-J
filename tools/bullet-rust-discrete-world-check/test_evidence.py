import json
from pathlib import PureWindowsPath, PurePosixPath
import unittest
from unittest.mock import patch

import check
import evidence
from cases import corpus
from hooks import NATIVE, OWNER, MUTANTS, NATIVE_OBSERVATIONS, instrument, inverse, mutate
from test_check import MemoryPath


def encode(value): return (json.dumps(value,sort_keys=True)+'\n').encode()
def sha(raw): return evidence.digest(raw)


def traces(inputs,mode,native,observed=True,mutation=None):
    commands=inputs.splitlines();lines=[];alloc=[];bodies=[];joints=[];physical=[]
    ordinal=0;live=[];counters=[0,0,0,0];changed=False;algorithm=False
    header={'schema':2,'domain':'generated-dbvt-node-sites' if observed else 'unmodified-control','mode':mode,'arena_base':4096,'slots':65536,'stride':128,'node_bytes':56,'raw_node_bytes':79,'node_type_alignment':8}
    world=0; sequence=0; call=0; node_counts=[0]*4; generations={}
    zero=' '.join(['00000000']*48)
    for row,command in enumerate(commands):
        op=command.split()[0];events=[];typed=[]
        if op=='H':world+=1
        def node_event(kind,pointer,generation):
            nonlocal sequence,call
            if not observed:return 0
            sequence+=1
            if kind in {'alloc','free'}:call+=1
            node_counts[{'alloc':0,'free':1,'reuse':2,'cache':3}[kind]]+=1
            typed.append({'op':kind,'sequence':sequence,'call':call if kind in {'alloc','free'} else 0,'world':world,'tree':0,'pointer':pointer,'generation':generation})
            return call

        if op=='C':
            slot=ordinal
            if mode=='descending':slot=65535-ordinal
            if mode=='alternating':slot=ordinal//2 if ordinal%2==0 else 65535-ordinal//2
            pointer=4096+slot*128;ordinal+=1;bodies.append(pointer+16);live.append(pointer)
            generations[pointer]=ordinal;node_id=node_event('alloc',pointer+16,ordinal)
            if mode!='ordinary':
                counters[0]+=1;events.append({'op':'alloc','route':'raw','ordinal':counters[0],'pointer':pointer,'size':79,'alignment':0,'node_call':node_id})
        if op=='J':
            pointer=1048576+row;joints.append(pointer);physical.append(f'JOINT_CREATE {row} {len(joints)-1} {pointer}')
        if algorithm:
            lines.append(f'E {row} A- 1');algorithm=False
        special=mutation in {'omit-pair-calculation','omit-dispatch','recreate-dispatcher','reverse-owner-order','reverse-dispatch-order','omit-linear-preclean'}
        if special and not changed and len(bodies)>=2 and op!='X':
            lines.append(f'E {row} A+ 1');algorithm=True;changed=True
        if op=='X':
            if observed:lines.extend(f'E {row} U {i}' for i in reversed(range(len(bodies))))
            physical.extend(f'PHYSICAL {row} joint {pointer} -1' for pointer in reversed(joints));joints=[]
            physical.extend(f'PHYSICAL {row} body {pointer} {i}' for i,pointer in reversed(list(enumerate(bodies))))
            for pointer in live:
                node_event('cache',pointer+16,generations[pointer])
                node_id=node_event('free',pointer+16,generations[pointer])
                if mode!='ordinary':
                    counters[1]+=1;events.append({'op':'free','route':'raw','ordinal':counters[1],'pointer':pointer,'node_call':node_id})
            bodies=[];live=[]
        force=0 if mutation=='default-force' and not changed else 1
        if force==0:changed=True
        lines.append(f'O {row} {op} {len(bodies)} {int(algorithm)} 0 {force}')
        for i in range(len(bodies)):
            flags=1 if mutation and not special and mutation!='default-force' and not changed else 0
            if flags:changed=True
            lines.append(f'B {row} {i} {flags} 1 {i+1} 1 -1 {i} {zero}')
        if algorithm:lines.append(f'P {row} 0 0 1 1')
        if native and op!='X':
            nodes=' '.join(f'{i} {pointer} '+ ' '.join(['00000000']*6) for i,pointer in enumerate(bodies))
            lines.append(f'T {row} 0 {len(bodies)} '+(nodes+' ' if nodes else '')+'0');lines.append(f'T {row} 1 0 0')
        alloc.append({'kind':row,'counters':list(counters),'events':events,'world':world,'trees':[1024+world*256,1152+world*256],'node_counters':list(node_counts),'nodes':typed})
    lines.append('Z '+str(len(commands)))
    alloc.append({'kind':'final','counters':list(counters),'events':[],'world':world,'trees':[1024+world*256,1152+world*256],'node_counters':list(node_counts),'nodes':[]})
    return ('\n'.join(lines)+'\n').encode(), b''.join(encode(item) for item in [header,*alloc]), ('\n'.join(physical)+'\n').encode()


def archive(payloads):
    result=b'!<arch>\n';longs=b'';entries=[]
    for name,raw in payloads.items():
        entries.append(('/'+str(len(longs)),raw));longs+=name.encode()+b'/\n'
    for name,raw in [('//',longs),*entries]:
        result+=name.encode().ljust(16)+b'0'.ljust(12)+b'0'.ljust(6)+b'0'.ljust(6)+b'100644'.ljust(8)+str(len(raw)).encode().ljust(10)+b'`\n'+raw+(b'\n' if len(raw)%2 else b'')
    return result


def fixture(system='Windows'):
    win=system=='Windows';P=PureWindowsPath if win else PurePosixPath
    root=P('C:/work/repo' if win else '/work/repo');out=P('C:/capture/world' if win else '/capture/world')
    suffix,ext=('.exe','.obj') if win else ('','.o')
    inputs,cases=corpus();files={};source={p.relative_to(check.ROOT).as_posix():p.read_bytes() for p in check.paths()}
    if win:
        source={name:raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n') if '/src/core/' in name else raw for name,raw in source.items()}
    before={name:sha(raw) for name,raw in source.items()}
    files.update({'source/'+name:raw for name,raw in source.items()})
    files['source-start.json']=encode(before);files['source-end.json']=encode(before)
    files['source-canonical.json']=encode({name:sha(raw.replace(b'\r\n',b'\n')) for name,raw in source.items()})
    files['inputs.txt']=inputs.encode();files['cases.json']=encode(cases)
    memory=MemoryPath({name:raw for name,raw in source.items()})
    edits=instrument(memory,check.HERE);inverse(memory,edits,{name:source[name] for name in evidence.TOUCHED})
    generated={name:sha(raw) for name,raw in memory.files.items()}
    files.update({'generated/'+name:raw for name,raw in memory.files.items()})
    files['observation-edits.json']=encode(edits);files['generated-start.json']=encode(generated);files['generated-end.json']=encode(generated)
    tool_names=['python','git','rustup','rustc','rust_linker','compiler','archiver','native_linker']
    tools={name:{'path':str(P('C:/tools' if win else '/tools')/(name+suffix)),'target':str(P('C:/targets' if win else '/targets')/(name+suffix)),'sha256':sha(('synthetic tool '+name).encode())} for name in tool_names}
    files.update({'tool-bytes/'+entry['sha256']:('synthetic tool '+name).encode() for name,entry in tools.items()})
    for stage in ['start','end']:
        files['tools-'+stage+'.json']=encode(tools);files['environment-'+stage+'.json']=encode(dict.fromkeys(evidence.ENVIRONMENT))
    flags=evidence.native_flags(system,str(root))
    files['compiler-flags.json']=encode(flags);files['effective-macros.cpp']=evidence.macro_source()
    policy_name='mmd-win64-sse' if win else 'generic-reference'
    sources=sorted((name for name in source if name.startswith('recipes/bullet275/bullet-src/src/') and name.endswith('.cpp') and name.split('/')[4] in {'BulletCollision','BulletDynamics','LinearMath'}),key=P)
    objects=[P(name).stem+ext for name in sources]
    for name in objects:files[name]=('synthetic object '+name).encode();files['extracted/'+name]=files[name]
    library='BulletWorld.lib' if win else 'libBulletWorld.a';files[library]=archive({name:files[name] for name in objects})
    bindings={'members':[{'source':name,'source_sha256':before[name],'object':obj,'sha256':sha(files[obj])} for name,obj in zip(sources,objects)],'archive_sha256':sha(files[library]),'actual_names':dict(zip(objects,objects))}
    files['archive-bindings.json']=encode(bindings)
    context={'schema':3,'system':system,'root':str(root),'out':str(out),'tools':{name:entry['path'] for name,entry in tools.items()},'archive_names':bindings['actual_names']}
    files['producer.json']=encode(context)
    plain,_,_=traces(inputs,'ordinary',False);files['rust-ordinary.stdout']=plain
    bound={};native_rows={}
    from trace import validate, comparison, bind_inputs
    for mode in evidence.MODES:
        for name in ['native','observed']:
            raw,alloc,physical=traces(inputs,mode,True,name=='observed')
            files[name+'-'+mode+'.stdout']=raw;files[name+'-'+mode+'.stderr']=physical if name=='observed' else b''
            files[name+'-allocator-'+mode+'.jsonl']=alloc
            if name=='observed':native_rows[mode]=validate(raw,inputs,native=True)
        bound[mode]=bind_inputs(inputs,native_rows[mode]).encode();files['bound-'+mode+'.txt']=bound[mode];files['rust-bound-'+mode+'.stdout']=plain
    controls={}
    for name in MUTANTS:
        target=MemoryPath(dict(memory.files));mutation=mutate(target,name)
        files.update({'mutants/'+name+'/'+path:raw for path,raw in target.files.items()})
        files['mutation-'+name+'.json']=encode(mutation)
        files['baseline-'+name+suffix]=('synthetic baseline '+name).encode();files['mutant-'+name+suffix]=('synthetic mutant '+name).encode()
        files['baseline-run-'+name+'.stdout']=plain;changed,_,_=traces(inputs,'ordinary',False,mutation=name);files['mutant-run-'+name+'.stdout']=changed
        clean=validate(plain,inputs);mutant=validate(changed,inputs)
        fields=['events','pairs','manifolds'] if name in {'omit-pair-calculation','omit-dispatch','recreate-dispatcher','reverse-owner-order','reverse-dispatch-order','omit-linear-preclean'} else ['header'] if name=='default-force' else ['bodies']
        controls[name]={'normal_exit':True,'full_schema':True,'different_rows':[i for i,(a,b) in enumerate(zip(comparison(clean),comparison(mutant))) if a!=b],
                        'binary_sha256':sha(files['mutant-'+name+suffix]),'semantic_fields':fields,'semantic_rows':[i for i,(a,b) in enumerate(zip(clean,mutant)) if any(a[field]!=b[field] for field in fields)],
                        'baseline_binary_sha256':sha(files['baseline-'+name+suffix]),'source_before':generated,'source_after':{path:sha(raw) for path,raw in target.files.items()}}
    files['semantic-controls.json']=encode(controls)
    parameters='const btDbvtAabbMm& a, const btDbvtAabbMm& b'
    expanded='Intersect('+parameters+'){return '+('_mm_cmplt_ps()' if win else '1')+';} Select('+parameters+', int c){return '+('_mm_cmple_ss()' if win else 'Proximity()')+';} Merge('+parameters+', int c){return '+('_mm_min_ps()' if win else '2')+';}'
    for label,receipt in [('expanded-btDbvt','policy-btDbvt.json'),('expanded-btDbvtBroadphase','policy-btDbvtBroadphase.json'),('native-consumer-expanded','native-consumer-policy.json'),('observed-consumer-expanded','observed-consumer-policy.json')]:
        files[label+'.stdout']=expanded.encode();files[receipt]=encode(evidence.policy(expanded))
    for name in ['dedicated','pure','rust-world','effective-macros','native','observed']:
        files[name+suffix]=('synthetic executable '+name).encode()
    files['mds_crtmath.lib' if win else 'libmds_crtmath.a']=b'synthetic CRT archive';files['libmds_crtmath.rlib']=b'synthetic CRT rlib'
    if win:files['effective-macros.obj']=b'synthetic macro object'
    for name in ['observed-'+member for member,_ in NATIVE_OBSERVATIONS]+['native-consumer','observed-consumer']:files[name+ext]=('synthetic object '+name).encode()
    for name in ['native','observed']:
        selected=sorted(member+ext for member in ['btDbvtBroadphase','btDiscreteDynamicsWorld',*([member for member,_ in NATIVE_OBSERVATIONS] if name=='native' else [])])
        if win:maptext='\n'.join(' 0001:00000000 symbol 0000000140001000 '+library+':'+member for member in selected)
        elif system=='Darwin':maptext='\n'.join('[  '+str(i)+'] '+str(out/library)+'('+member+')' for i,member in enumerate(selected))
        else:maptext='\n'.join(str(out/library)+'('+member+') symbol' for member in selected)
        if name=='observed':maptext+='\n'+ ' '.join('observed-'+member+ext for member in [member for member,_ in NATIVE_OBSERVATIONS])
        files[name+'.map']=maptext.encode();files[name+'-link-selection.json']=encode(selected)
        files[name+'-binary.json']=encode({'produced_sha256':sha(files[name+suffix]),'consumer_object_sha256':sha(files[name+'-consumer'+ext]),'observed_override_objects':{member+ext:sha(files[member+ext]) for member in (['observed-'+member for member,_ in NATIVE_OBSERVATIONS] if name=='observed' else [])}})
    T=context['tools'];rust=[T['rustup'],'run','1.95.0','rustc','--edition=2021','-O','-C','linker='+T['rust_linker']]
    rargs=[*rust,'--extern','mds_crtmath='+str(out/'libmds_crtmath.rlib')];here=root/'tools/bullet-rust-discrete-world-check';shadow=out/'generated';commands=[];includes={};include_aliases={}
    def add(label,argv,data=None,cwd=None,compile=False):
        argv=list(map(str,argv))
        roles=evidence.command_files(label,argv,{**context,'archive_objects':objects})
        if compile:
            for output in evidence.command_files(label+'-discovery',argv,{**context,'archive_objects':objects}).outputs:
                files[output.retained]=('synthetic discovery '+output.retained).encode()
            add(label+'-discovery',argv,data,cwd)
            header=str(root/'rust/crates/mds-bullet-sys/shim/det_math.h');key=header.lower() if win else header;value=before['rust/crates/mds-bullet-sys/shim/det_math.h']
            emit=lambda name:('Note: including file: '+name+'\n' if win else '. '+name+'\n').encode()
            alias=str(P('C:/sdk/alias/../header.h' if win else '/sdk/alias/../header.h'))
            external=str(P('C:/sdk/header.h' if win else '/sdk/header.h'));external=external.lower() if win else external
            external_raw=b'synthetic SDK header';external_sha=sha(external_raw)
            stdout=emit(header)+emit(header);stderr=emit(alias)
            for stage in [label+'-discovery',label]:files[stage+'.stdout']=stdout;files[stage+'.stderr']=stderr
            commands[-1]['stdout_sha256']=sha(stdout);commands[-1]['stderr_sha256']=sha(stderr)
            files['include-bytes/'+value]=source['rust/crates/mds-bullet-sys/shim/det_math.h'];includes[key]=value
            files['include-bytes/'+external_sha]=external_raw;includes[external]=external_sha
            manifest={key:value,external:external_sha}
            files[label+'-includes-pre.json']=encode(manifest);files[label+'-includes.json']=encode(manifest)
            occurrences=evidence.include_occurrences(stdout,stderr,system)
            bindings=[{**occurrence,'target':key if occurrence['raw']==header else external,'sha256':value if occurrence['raw']==header else external_sha} for occurrence in occurrences]
            files[label+'-include-bindings.json']=encode({'schema':1,'label':label,'cwd':str(cwd or root/'rust'),'pre':bindings,'post':bindings})
            include_aliases[(str(cwd or root/'rust'),header)]=(key,value)
            include_aliases[(str(cwd or root/'rust'),alias)]=(external,external_sha)
        files.setdefault(label+'.stdout',b'');files.setdefault(label+'.stderr',b'')
        if label=='git-head':files[label+'.stdout']=b'1'*40+b'\n'
        if label=='git-transport':files[label+'.stdout']=''.join('i/lf w/'+('crlf' if b'\r\n' in source[path] else 'lf' if b'\n' in source[path] else 'none')+' attr/\t'+path+'\n' for path in before).encode()
        if label=='git-attributes':files[label+'.stdout']=''.join(path+': '+attribute+': '+('unset' if attribute=='text' and path.startswith('rust/crates/') and '/tests/' in path else 'unspecified')+'\n' for path in before for attribute in ['text','eol']).encode()
        if label=='rust-compiler-path':files[label+'.stdout']=(T['rustc']+'\n').encode()
        if label=='rust-version':files[label+'.stdout']=b'rustc 1.95.0\nrelease: 1.95.0\n'
        if label=='native-linker-path':files[label+'.stdout']=(T['native_linker']+'\n').encode()
        if label=='dedicated-run':files[label+'.stdout']=b'6 passed; 0 failed; 0 ignored\n'
        if label=='pure-run':files[label+'.stdout']=b'97 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n'
        if label=='archive-list':files[label+'.stdout']=('\n'.join(objects)+'\n').encode()
        if label=='crt-build' and win:files[label+'.stderr']=b'native-static-libs: kernel32.lib\n'
        if label=='actual-macros':
            macros={key:'<undefined>' for key in evidence.MACROS};macros.update(BT_USE_SSE='',BT_NO_PROFILE='1',pointer_bits='64',scalar_bytes='4',sinf='mds_crt_sinf',cosf='mds_crt_cosf',atan2f='mds_crt_atan2f')
            if win:macros.update(WIN32='1',_MSC_VER='1944',_M_X64='100')
            else:macros['__aarch64__' if system=='Darwin' else '__x86_64__']='1'
            files[label+'.stdout']=''.join(key+'='+macros[key]+'\n' for key in evidence.MACROS).encode()
        stdin=None if data is None else sha(data)
        exe=argv[0];exe_hash=sha(files[P(exe).relative_to(out).as_posix()]) if P(exe).is_relative_to(out) else next(tool['sha256'] for tool in tools.values() if tool['path']==exe)
        commands.append({'label':label,'argv':argv,'cwd':str(cwd or root/'rust'),'stdin_sha256':stdin,'tool':exe,'tool_target':exe if P(exe).is_relative_to(out) else next(tool['target'] for tool in tools.values() if tool['path']==exe),'tool_sha256':exe_hash,'executable_sha256':exe_hash,
                         'returncode':0,'timeout':False,'seconds':0.01,'stdout_sha256':sha(files[label+'.stdout']),'stderr_sha256':sha(files[label+'.stderr']),
                         'inputs':{value:sha(files[evidence.captured_path(value,context)]) for value in roles.inputs},
                         'generated_inputs':generated if label=='rust-observed-build' or label.startswith('baseline-build-') else controls[label[len('mutant-build-'):]]['source_after'] if label.startswith('mutant-build-') else None,
                         'outputs':{output.retained:sha(files[output.retained]) for output in roles.outputs}})
    add('helpers-normal',[T['python'],'-B',here/'test_check.py','-v']);add('helpers-optimized',[T['python'],'-B','-O',here/'test_check.py','-v'])
    for label,args in [('git-head',['rev-parse','HEAD']),('git-status',['status','--porcelain=v1']),('git-transport',['ls-files','--eol']),('git-attributes',['check-attr','--stdin','text','eol'])]:add(label,[T['git'],*args], ('\n'.join(sorted(before))+'\n').encode() if label=='git-attributes' else None,cwd=root if label in {'git-transport','git-attributes'} else None)
    add('rust-compiler-path',[T['rustup'],'which','--toolchain','1.95.0','rustc']);add('rust-version',[T['rustup'],'run','1.95.0','rustc','-Vv'])
    crt=out/('mds_crtmath.lib' if win else 'libmds_crtmath.a')
    add('crt-build',[*rust,'--crate-name','mds_crtmath','--crate-type','rlib,staticlib','--print','native-static-libs',root/'rust/crates/mds-crtmath/src/lib.rs','--out-dir',out])
    for name,source_name,extra in [('dedicated','discrete_collision_world.rs',['discrete_world_']),('pure','pure_bullet.rs',[])]:
        add(name+'-build',[*rargs,'--test','-D','warnings',root/'rust/crates/mds-bullet/tests'/source_name,'-o',out/(name+suffix)])
        add(name+'-run',[out/(name+suffix),*extra])
    add('rust-observed-build',[*rargs,'--cfg','test',shadow/'tools/bullet-rust-discrete-world-check/runner.rs','-o',out/('rust-world'+suffix)])
    add('rust-ordinary',[out/('rust-world'+suffix),policy_name],inputs.encode())
    add('compiler-version',[T['compiler'],'/?' if win else '--version'])
    if not win:add('native-linker-path',[T['compiler'],'-print-prog-name=ld'])
    add('macro-build',[T['compiler'],*flags,out/'effective-macros.cpp','/Fe'+str(out/('effective-macros'+suffix)),'/Fo'+str(out)+'/'] if win else [T['compiler'],*flags,out/'effective-macros.cpp','-o',out/('effective-macros'+suffix)],compile=True)
    add('actual-macros',[out/('effective-macros'+suffix)])
    def obj(source_name,output,label,extra=()):add(label,[T['compiler'],*flags,*extra,'/c',source_name,'/Fo'+str(output)] if win else [T['compiler'],*flags,*extra,'-c',source_name,'-o',output],compile=True)
    for i,(source_name,output) in enumerate(zip(sources,objects)):
        obj(root/source_name,out/output,f'compile-{i:03d}')
        if P(source_name).stem in {'btDbvt','btDbvtBroadphase'}:add('expanded-'+P(source_name).stem,[T['compiler'],*flags,'/E' if win else '-E',root/source_name])
    add('archive-build',[T['archiver'],'/NOLOGO','/OUT:'+str(out/library),*[out/name for name in objects]] if win else [T['archiver'],'rcs',out/library,*[out/name for name in objects]])
    add('archive-list',[T['archiver'],'/NOLOGO','/LIST',out/library] if win else [T['archiver'],'t',out/library])
    if win:
        for output in objects:add('extract-'+P(output).stem,[T['archiver'],'/NOLOGO','/EXTRACT:'+output,'/OUT:'+str(out/'extracted'/output),out/library])
    else:add('archive-extract',[T['archiver'],'x',out/library],cwd=out/'extracted')
    hook=['/FI'+str(here/'observer.h'),'/DDW_OBSERVED=1'] if win else ['-include',here/'observer.h','-DDW_OBSERVED=1']
    for name,source_path in NATIVE_OBSERVATIONS:obj(shadow/source_path,out/('observed-'+name+ext),'observed-'+name,hook)
    for name in ['native','observed']:
        prefix=[out/('observed-'+member+ext) for member in [member for member,_ in NATIVE_OBSERVATIONS]] if name=='observed' else [];extra=hook if name=='observed' else [];src=(shadow if name=='observed' else root)/'tools/bullet-rust-discrete-world-check/oracle.cpp';consumer=out/(name+'-consumer'+ext);exe=out/(name+suffix);linkmap=out/(name+'.map')
        obj(src,consumer,name+'-consumer-build',extra);add(name+'-consumer-expanded',[T['compiler'],*flags,*extra,'/E' if win else '-E',src])
        libs=['kernel32.lib'] if win else ([] if system=='Darwin' else ['-ldl','-lpthread','-lm'])
        add(name+'-link',[T['compiler'],'/nologo','/MD','/EHsc',consumer,*prefix,out/library,crt,'/Fe'+str(exe),'/link','/MAP:'+str(linkmap),'/VERBOSE:LIB',*libs] if win else [T['compiler'],consumer,*prefix,out/library,crt,*libs,'-fuse-ld='+T['native_linker'],('-Wl,-map,' if system=='Darwin' else '-Wl,-Map,')+str(linkmap),'-o',exe])
        for mode in evidence.MODES:add(name+'-'+mode,[exe,mode,out/(name+'-allocator-'+mode+'.jsonl')],inputs.encode())
    for mode in evidence.MODES:add('rust-bound-'+mode,[out/('rust-world'+suffix),policy_name],bound[mode])
    for name in MUTANTS:
        for prefix in ['baseline','mutant']:
            exe=out/(prefix+'-'+name+suffix);add(prefix+'-build-'+name,[*rargs,'--cfg','test',out/'mutants'/name/'tools/bullet-rust-discrete-world-check/runner.rs','-o',exe]);add(prefix+'-run-'+name,[exe,policy_name],inputs.encode())
    files['commands.json']=encode(commands);files['native-includes-end.json']=encode(includes)
    files['native-include-bindings-end.json']=encode({'schema':1,'bindings':[{'cwd':cwd,'raw':raw,'target':target,'sha256':value} for (cwd,raw),(target,value) in include_aliases.items()]})
    report={'schema':6,'status':'CONTROLLED_PASS','base':evidence.BASE,'policy':policy_name,'native':'ACTUAL_ORIGINAL_PUBLIC_SHIM_WITH_UNMODIFIED_ARCHIVE_CONTROL','compiled_controls':17,'public_world':'UNCHANGED_NATIVE_BACKEND','scope':'private default-DBVT discrete collision owner','host':{'system':system,'machine':'amd64' if win else 'arm64' if system=='Darwin' else 'x86_64','image':'synthetic'},'head':'1'*40,'compiler':tools['compiler'],'checkpoints':len(inputs.splitlines()),'cases':len(cases),'controlled':{mode:len(inputs.splitlines()) for mode in evidence.MODES},'ordinary_unbound':'EQUAL','limits':evidence.LIMITS}
    files['report.json']=encode(report);refresh(files)
    expected={'expected_head':'1'*40,'canonical_sources':source,'inputs':inputs,'cases':cases,'expected_host':{(system,report['host']['machine'])},'expected_policy':policy_name}
    return files,expected


def refresh(files):
    files['artifact-manifest.json']=encode({name:sha(raw) for name,raw in files.items() if name!='artifact-manifest.json'})


class AdmissionControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.windows,cls.expected=fixture()
        evidence.admit_capture(cls.windows,**cls.expected)

    def test_complete_independent_native_closure(self):
        admitted=evidence.admit_capture(self.windows,**self.expected)
        self.assertEqual(admitted.compare('ordinary',self.windows['rust-ordinary.stdout']),707)
        self.assertEqual(admitted.bound_input('ascending'),self.windows['bound-ascending.txt'])
        self.assertFalse(hasattr(admitted,'report'));self.assertFalse(hasattr(admitted,'directory'))

    def test_unix_complete_closure(self):
        for system in ['Linux','Darwin']:
            files,expected=fixture(system);self.assertEqual(len(evidence.admit_capture(files,**expected).bound_input('ordinary').splitlines()),1333)

    def rejected(self, change, reason):
        files=dict(self.windows)
        change(files)
        rehash(files)
        with self.assertRaisesRegex(ValueError,reason):evidence.admit_capture(files,**self.expected)

    def test_completed_native_claims_source_end_and_required_families(self):
        for key,value in [('native','UNRUN'),('compiled_controls','UNRUN'),('schema',5),('checkpoints',True),('unrecognized','foreign')]:
            self.rejected(lambda files,key=key,value=value:edit_json(files,'report.json',lambda report:report.update({key:value})), 'complete genuine|completed native|boolean|fields')
        self.rejected(lambda files:edit_json(files,'report.json',lambda report:report['host'].update(image={})), 'host field types')
        self.rejected(lambda files:files.update({'source-end.json':b'{}\n'}),'source-start equals source-end')
        self.rejected(lambda files:files.update({'git-attributes.stdout':files['git-attributes.stdout'].replace(b': unset',b': set')}),'exact trusted Git attributes')
        self.rejected(lambda files:files.update({'git-transport.stdout':files['git-transport.stdout'].replace(b'w/crlf',b'w/lf')}),'physical source/Git transport binding')
        for name in ['commands.json','archive-bindings.json','native-includes-end.json','native-include-bindings-end.json','macro-build-include-bindings.json','native-link-selection.json','native-binary.json','semantic-controls.json','observed-ordinary.stdout']:
            self.rejected(lambda files,name=name:files.pop(name),'required capture file')

    def test_commands_flags_tools_environment_and_generated_use(self):
        self.rejected(lambda files:edit_json(files,'commands.json',lambda rows:rows.reverse()),'ordered unique command')
        self.rejected(lambda files:edit_json(files,'commands.json',lambda rows:rows[0]['argv'].append('--foreign')),'exact effective command')
        self.rejected(lambda files:edit_json(files,'commands.json',lambda rows:rows[0].update(tool_sha256='0'*64)),'resolved command tool')
        self.rejected(lambda files:edit_json(files,'commands.json',lambda rows:next(row for row in rows if row['label']=='rust-observed-build').update(generated_inputs={})), 'actual generated source pre-use')
        def injected(files):
            for stage in ['start','end']:edit_json(files,'environment-'+stage+'.json',lambda settings:settings.update(CL='/fp:fast'))
        self.rejected(injected,'no ambient CL flag injection')
        self.rejected(lambda files:edit_json(files,'compiler-flags.json',lambda flags:flags.append('/W0')),'exact effective native flags')
        self.rejected(lambda files:edit_json(files,'commands.json',lambda rows:next(row for row in rows if row['label']=='native-link')['argv'].append('foreign.lib')),'exact effective command')

    def test_alias_target_and_generated_dbvt_refusals(self):
        self.rejected(lambda files:edit_json(files,'tools-end.json',lambda tools:tools['rustup'].update(target='C:\\targets\\other.exe')), 'tool start/end preservation')
        self.rejected(lambda files:edit_json(files,'commands.json',lambda rows:rows[0].update(tool_target='C:\\targets\\other.exe')), 'resolved command tool')
        self.rejected(lambda files:edit_json(files,'commands.json',lambda rows:rows[0]['argv'].__setitem__(0,'C:\\tools\\other.exe')), 'exact effective command')
        from hooks import DBVT
        self.rejected(lambda files:files.update({'generated/'+DBVT:files['generated/'+DBVT]+b'foreign'}), 'generated physical source')
        self.rejected(lambda files:files.update({'observed-btDbvt.obj':b'foreign object'}), 'actual pre-use direct|genuine consumer')
        self.rejected(lambda files:files.update({'observed.map':files['observed.map'].replace(b'observed-btDbvt.obj',b'foreign-btDbvt.obj')}), 'actual selected override object')
        def original_dbvt(files):
            files['observed.map']+=b'\n 0001:00000000 symbol 0000000140001000 BulletWorld.lib:btDbvt.obj\n'
            edit_json(files,'observed-link-selection.json',lambda selected:selected.append('btDbvt.obj'))
        self.rejected(original_dbvt,'observed overrides exclude original')

    def test_physical_source_object_archive_and_member_bindings(self):
        source='source/'+OWNER
        self.rejected(lambda files:files.update({source:files[source]+b'foreign'}),'physical canonical source')
        def foreign_object(files):
            name=json.loads(files['archive-bindings.json'])['members'][0]['object'];files[name]=b'foreign object'
            edit_json(files,'archive-bindings.json',lambda binding:binding['members'][0].update(sha256=sha(files[name])))
        self.rejected(foreign_object,'archive payload/extracted/object equality')
        def reordered_payloads(files):
            entries=json.loads(files['archive-bindings.json'])['members']
            files['BulletWorld.lib']=archive({entry['object']:files[entry['object']] for entry in reversed(entries)})
            edit_json(files,'archive-bindings.json',lambda binding:binding.update(archive_sha256=sha(files['BulletWorld.lib'])))
        self.rejected(reordered_payloads,'actual pre-use direct source/object/archive/CRT inputs archive-list')
        files=dict(self.windows);reordered_payloads(files)
        archive_path=str(PureWindowsPath(json.loads(files['producer.json'])['out'])/'BulletWorld.lib')
        commands=json.loads(files['commands.json'])
        consumers={row['label'] for row in commands if archive_path in row['inputs']}
        entries=json.loads(files['archive-bindings.json'])['members']
        self.assertEqual(consumers,{'archive-list','native-link','observed-link',*('extract-'+PureWindowsPath(entry['object']).stem for entry in entries)})
        for row in commands:
            if row['label'] in consumers:row['inputs'][archive_path]=sha(files['BulletWorld.lib'])
        files['commands.json']=encode(commands);rehash(files)
        evidence.admit_capture(files,**self.expected)
        for label in ['archive-list','extract-'+PureWindowsPath(entries[0]['object']).stem,'native-link','observed-link']:
            for missing in [False,True]:
                with self.subTest(label=label,missing=missing):
                    malformed=dict(files);receipts=json.loads(malformed['commands.json'])
                    inputs=next(row for row in receipts if row['label']==label)['inputs']
                    if missing:inputs.pop(archive_path)
                    else:inputs[archive_path]=sha(self.windows['BulletWorld.lib'])
                    malformed['commands.json']=encode(receipts);rehash(malformed)
                    with self.assertRaisesRegex(ValueError,'actual pre-use direct source/object/archive/CRT inputs '+label):evidence.admit_capture(malformed,**self.expected)
        def foreign_payload(files):
            name=json.loads(files['archive-bindings.json'])['members'][0]['object']
            files['BulletWorld.lib']=files['BulletWorld.lib'].replace(files[name],b'X'+files[name][1:],1)
            edit_json(files,'archive-bindings.json',lambda binding:binding.update(archive_sha256=sha(files['BulletWorld.lib'])))
        self.rejected(foreign_payload,'archive payload/extracted/object equality')
        self.rejected(lambda files:files.update({'extracted/'+json.loads(files['archive-bindings.json'])['members'][0]['object']:b'foreign extracted'}),'archive payload/extracted/object equality')
        def foreign_member(files):
            for receipt in ['producer.json','archive-bindings.json']:
                edit_json(files,receipt,lambda value:value['archive_names' if receipt=='producer.json' else 'actual_names'].update(btDbvt= 'foreign'))
        self.rejected(foreign_member,'exact archive payload member membership')

    def test_include_policy_override_binary_and_mode_lifetime(self):
        def include_foreign(files):
            name='macro-build';receipt=json.loads(files[name+'-includes.json']);key=next(key for key in receipt if key.endswith('det_math.h'));raw=b'foreign include';identity=sha(raw);files['include-bytes/'+identity]=raw
            for suffix in ['-includes.json','-includes-pre.json']:edit_json(files,name+suffix,lambda receipt:receipt.update({key:identity}))
            edit_json(files,name+'-include-bindings.json',lambda receipt:[entry.update(sha256=identity) for stage in ['pre','post'] for entry in receipt[stage] if entry['target']==key])
        self.rejected(include_foreign,'source/generated include binding')
        self.rejected(lambda files:files.update({'expanded-btDbvt.stdout':files['expanded-btDbvt.stdout'].replace(b'_mm_cmplt_ps',b'_mm_cmpge_ps')}),'known unmixed DBVT numeric policy')
        def original_override(files):
            files['observed.map']+=b'\n 0001:00000000 symbol 0000000140001000 BulletWorld.lib:btCollisionWorld.obj\n'
            edit_json(files,'observed-link-selection.json',lambda selected:selected.append('btCollisionWorld.obj'))
        self.rejected(original_override,'observed overrides exclude original')
        self.rejected(lambda files:edit_json(files,'native-binary.json',lambda receipt:receipt.update(produced_sha256='0'*64)),'genuine consumer/overrides/produced/executed/end binary')
        self.rejected(lambda files:edit_json(files,'commands.json',lambda rows:next(row for row in rows if row['label']=='native-ascending').update(executable_sha256='0'*64)), 'executed binary identity')
        self.rejected(lambda files:files.update({'observed-ordinary.stderr':b'foreign\n'}),'physical joint creation|reverse native|native joint')
        self.rejected(lambda files:files.update({'observed-ascending.stdout':files['observed-ascending.stdout'].replace(b'E 11 U 1',b'E 11 M- 1')}),'event width|reverse logical|synchronous|strict trace')

    def test_required_temporal_include_receipts_and_refreshed_peers(self):
        evidence.admit_capture(self.windows,**self.expected)
        for stage in ['pre','post']:
            for key,value in [('raw','C:\\foreign.h'),('target','c:\\other.h'),('sha256','0'*64),('stream','stderr'),('ordinal',1)]:
                self.rejected(lambda files,stage=stage,key=key,value=value:edit_json(files,'macro-build-include-bindings.json',lambda receipt:receipt[stage][0].update({key:value})),'include')
        for key,value in [('schema',2),('label','compile-000'),('cwd','C:\\other')]:
            self.rejected(lambda files,key=key,value=value:edit_json(files,'macro-build-include-bindings.json',lambda receipt:receipt.update({key:value})),'include')
        self.rejected(lambda files:edit_json(files,'native-include-bindings-end.json',lambda receipt:receipt['bindings'].pop()),'end resolution/bytes')
        self.rejected(lambda files:edit_json(files,'native-include-bindings-end.json',lambda receipt:receipt['bindings'][0].update(target='c:\\same-bytes.h')),'end resolution/bytes')
        self.rejected(lambda files:edit_json(files,'producer.json',lambda receipt:receipt.update(schema=2)),'producer schema')
        self.rejected(lambda files:edit_json(files,'report.json',lambda receipt:receipt.update(schema=4)),'completed native schema')

    def test_directed_mutant_witness_and_bool_integer_are_rejected(self):
        self.rejected(lambda files:edit_json(files,'semantic-controls.json',lambda controls:controls['default-force'].update(semantic_rows=[])), 'derived valid directed semantic witness')
        self.rejected(lambda files:edit_json(files,'semantic-controls.json',lambda controls:controls['default-force'].update(normal_exit='UNRUN')), 'derived valid directed semantic witness')
        self.rejected(lambda files:edit_json(files,'commands.json',lambda rows:rows[0].update(seconds=True)), 'boolean in integer receipt field')
        self.rejected(lambda files:files.update({'report.json':files['report.json'].replace(b'"schema": 6',b'"schema": 6, "schema": 6')}), 'duplicate')
        self.rejected(lambda files:files.update({'report.json':files['report.json'].replace(b'"checkpoints": 707',b'"checkpoints": NaN')}), 'finite JSON number')

    def test_native_finalization_and_windows_entry_share_refusal_and_exact_publication(self):
        status=json.loads(self.windows['report.json']);writes=[]
        def capture(directory,overrides=None):return {**self.windows,**(overrides or {})}
        def publish(path,raw):writes.append((path.name,raw))
        from pathlib import Path
        with patch.object(check,'Capture',capture),patch.object(check,'atomic_bytes',publish):
            admitted=check.finalize_native(Path('/synthetic'),status,**self.expected)
            self.assertEqual([name for name,_ in writes],['artifact-manifest.json','report.json'])
            self.assertEqual(writes[-1][1],check.encoded(status));self.assertEqual(admitted.report_sha256,sha(writes[-1][1]))
            expected={name:value for name,value in self.expected.items() if name not in {'expected_host','expected_policy'}}
            self.assertEqual(check.admit_windows(Path('/synthetic'),**expected).report_sha256,sha(self.windows['report.json']))
            writes.clear();broken=dict(self.windows);broken['source-end.json']=b'{}\n';refresh(broken)
            fail=encode({'schema':2,'status':'FAIL'})
            def rejected_capture(directory,overrides=None):return {**broken,'report.json':fail,**(overrides or {})}
            with patch.object(check,'Capture',rejected_capture):
                with self.assertRaisesRegex(ValueError,'source-start equals source-end'):check.finalize_native(Path('/synthetic'),status,**self.expected)
                self.assertEqual(writes,[])
                self.assertEqual(json.loads(rejected_capture(None)['report.json'])['status'],'FAIL')
            with patch.object(check,'Capture',lambda directory:broken):
                with self.assertRaisesRegex(ValueError,'source-start equals source-end'):check.admit_windows(Path('/synthetic'),**expected)

    def test_replay_contract_is_distinct_and_has_exact_current_rust_schedule(self):
        context=json.loads(self.windows['producer.json'])
        schedule=evidence.command_schedule(context,[],'mmd-win64-sse',[],replay=True)
        prefix=['helpers-normal','helpers-optimized','git-head','git-status','git-transport','git-attributes','rust-compiler-path','rust-version','crt-build','dedicated-build','dedicated-run','pure-build','pure-run','rust-observed-build','rust-ordinary']
        labels=prefix+['rust-bound-'+mode for mode in ['ascending','descending','alternating','ordinary']]+[prefix+'-'+phase+'-'+name for name in MUTANTS for prefix,phase in [('baseline','build'),('baseline','run'),('mutant','build'),('mutant','run')]]
        self.assertEqual([row[0] for row in schedule],labels);self.assertEqual(len(labels),87)
        self.assertFalse(any(compile or '-C' in argv or any(arg.startswith('linker=') for arg in argv) for _,argv,_,_,_,compile in schedule))
        for label,argv,cwd,_,_,_ in schedule:
            self.assertEqual(cwd,str(PureWindowsPath(context['root']) if label in {'git-transport','git-attributes'} else PureWindowsPath(context['root'])/'rust'))
            if '-o' in argv or label=='crt-build':self.assertEqual(argv[:6],[context['tools']['rustup'],'run','1.95.0','rustc','--edition=2021','-O'])
        report=json.loads(self.windows['report.json']);report.pop('compiler')
        report.update(schema=7,native='WINDOWS_SOURCE_REPLAY',producer_report_sha256=sha(self.windows['report.json']),ordinary_unbound='WINDOWS_SOURCE_REPLAY',limits=evidence.LIMITS+['replay Rust inner linker chain unobserved'])
        self.assertEqual(evidence.replay_report(report,self.expected['expected_head'],self.expected['inputs'],self.expected['cases']),report)
        for key,value in [('schema',4),('schema',5),('schema',6),('compiled_controls','UNRUN'),('producer_report_sha256','foreign'),('native','UNRUN'),('host',{**report['host'],'image':{}})]:
            with self.assertRaises(ValueError):evidence.replay_report({**report,key:value},self.expected['expected_head'],self.expected['inputs'],self.expected['cases'])

    def test_bounds_closed_paths_and_container_payloads(self):
        with patch.object(evidence,'MAX_FILES',1):
            with self.assertRaisesRegex(ValueError,'count bound'):evidence.admit_capture(self.windows,**self.expected)
        for name in ['../escape','AUX','source/AUX','source/x.','source/../x']:
            files=dict(self.windows);files[name]=b'foreign';refresh(files)
            with self.assertRaisesRegex(ValueError,'safe capture path|closed complete'):evidence.admit_capture(files,**self.expected)
        self.rejected(lambda files:files.update({'Source-start.json':files['source-start.json']}),'capture case collision')
        malformed=[b'!<arch>\n'+b'x'*60, b'!<arch>\n'+b'//'.ljust(16)+b'0'.ljust(32)+b'1'.ljust(10)+b'`\n'+b'x', self.windows['BulletWorld.lib'][:-1]]
        for raw in malformed:
            with self.assertRaises(ValueError):evidence.decode_archive(raw)


class IncludeControls(unittest.TestCase):
    @staticmethod
    def sample(system='Linux'):
        P=PureWindowsPath if system=='Windows' else PurePosixPath
        root=P('C:/repo' if system=='Windows' else '/repo');out=P('C:/capture' if system=='Windows' else '/capture')
        context={'system':system,'root':str(root),'out':str(out)};cwd=str(root/'rust')
        owned=str(root/'owned.h');target=str(P('C:/sdk/header.h' if system=='Windows' else '/sdk/header.h'))
        alias=str(P('C:/compiler/../sdk/header.h' if system=='Windows' else '/compiler/../sdk/header.h'))
        generated=str(out/'generated/owned.h')
        raw=b'owned header';external=b'external header'
        emit=lambda name:('Note: including file: '+name+'\n' if system=='Windows' else '. '+name+'\n').encode()
        stdout=emit(owned)+emit(alias)+emit(alias);stderr=emit(alias)+emit(generated)
        occurrences=evidence.include_occurrences(stdout,stderr,system)
        bindings=[]
        for entry in occurrences:
            resolved=entry['raw'] if entry['raw'] in {owned,generated} else target
            bindings.append({**entry,'target':resolved.lower() if system=='Windows' else resolved,'sha256':sha(raw if entry['raw'] in {owned,generated} else external)})
        manifest,aliases=evidence.include_projection(bindings,occurrences,system)
        files={'source/owned.h':raw,'generated/owned.h':raw,'include-bytes/'+sha(raw):raw,'include-bytes/'+sha(external):external}
        for stage in ['compile-discovery','compile']:
            files[stage+'.stdout']=stdout;files[stage+'.stderr']=stderr
        files['compile-include-bindings.json']=encode({'schema':1,'label':'compile','cwd':cwd,'pre':bindings,'post':bindings})
        for name in ['compile-includes-pre.json','compile-includes.json','native-includes-end.json']:files[name]=encode(manifest)
        files['native-include-bindings-end.json']=encode({'schema':1,'bindings':[{'cwd':cwd,'raw':name,'target':value[0],'sha256':value[1]} for name,value in aliases.items()]})
        return files,[('compile',[],cwd,None,(),True)],context

    @staticmethod
    def verify(files,schedule,context):
        evidence.include_evidence(lambda name:evidence.json_value(files[name]),files.__getitem__,schedule,context,set(files))

    def test_platform_occurrences_duplicates_aliases_and_owned_bytes(self):
        for system in ['Windows','Linux','Darwin']:
            files,schedule,context=self.sample(system);self.verify(files,schedule,context)
            receipt=json.loads(files['compile-include-bindings.json'])
            self.assertEqual([(row['stream'],row['ordinal']) for row in receipt['pre']],[('stdout',0),('stdout',1),('stdout',2),('stderr',0),('stderr',1)])

    def test_refreshed_receipt_log_and_end_peers(self):
        import copy
        original,schedule,context=self.sample();self.verify(original,schedule,context)
        peers=[]
        for stage in ['pre','post']:
            for key,value in [('stream','stderr'),('ordinal',True),('ordinal',4),('raw','/false.h'),('target','/other.h'),('sha256','0'*64)]:
                peers.append(lambda files,stage=stage,key=key,value=value:edit_json(files,'compile-include-bindings.json',lambda receipt:receipt[stage][1].update({key:value})))
            peers.extend([lambda files,stage=stage:edit_json(files,'compile-include-bindings.json',lambda receipt:receipt[stage].pop()),lambda files,stage=stage:edit_json(files,'compile-include-bindings.json',lambda receipt:receipt[stage].reverse())])
        for key,value in [('schema',True),('schema',2),('label','other'),('cwd','/other')]:
            peers.append(lambda files,key=key,value=value:edit_json(files,'compile-include-bindings.json',lambda receipt:receipt.update({key:value})))
        peers.extend([
            lambda files:files.update({'compile.stderr':b'. /other.h\n'}),
            lambda files:edit_json(files,'native-include-bindings-end.json',lambda receipt:receipt['bindings'].pop()),
            lambda files:edit_json(files,'native-include-bindings-end.json',lambda receipt:receipt['bindings'].append(receipt['bindings'][0])),
            lambda files:edit_json(files,'native-include-bindings-end.json',lambda receipt:receipt['bindings'][0].update(target='/same-bytes-other.h')),
            lambda files:edit_json(files,'native-include-bindings-end.json',lambda receipt:receipt['bindings'][0].update(sha256='0'*64)),
            lambda files:edit_json(files,'native-includes-end.json',lambda receipt:receipt.update({'/extra.h':'0'*64})),
            lambda files:files.update({'source/owned.h':b'changed owned bytes'}),
            lambda files:files.update({'generated/owned.h':b'changed generated bytes'}),
        ])
        for change in peers:
            files=copy.deepcopy(original);change(files)
            with self.assertRaises(ValueError):self.verify(files,schedule,context)
        for missing in ['compile-include-bindings.json','native-include-bindings-end.json']:
            files=dict(original);files.pop(missing)
            with self.assertRaises(KeyError):self.verify(files,schedule,context)

    def test_same_byte_retarget_and_coordinated_source_reclassification(self):
        files,schedule,context=self.sample();self.verify(files,schedule,context)
        def retarget(files,stages):
            receipt=json.loads(files['compile-include-bindings.json'])
            for stage in stages:receipt[stage][0]['target']='/outside/owned.h'
            files['compile-include-bindings.json']=encode(receipt)
            for stage,suffix in [('pre','-includes-pre.json'),('post','-includes.json')]:
                if stage in stages:
                    manifest=json.loads(files['compile'+suffix]);manifest['/outside/owned.h']=manifest.pop('/repo/owned.h');files['compile'+suffix]=encode(manifest)
        for stages in [('post',),('pre','post')]:
            candidate=dict(files);retarget(candidate,stages)
            with self.assertRaisesRegex(ValueError,'raw source/generated include ownership|temporal include alias'):self.verify(candidate,schedule,context)

    def test_filesystem_resolution_temporal_bytes_and_cwd(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary).resolve();out=base/'capture';out.mkdir();physical=base/'physical';physical.mkdir();(physical/'sub').mkdir()
            header=physical/'header.h';header.write_bytes(b'original')
            other=base/'other.h';other.write_bytes(b'original')
            alias=base/'directory';alias.symlink_to(physical/'sub',target_is_directory=True)
            direct=base/'alias.h';direct.symlink_to(header)
            spelling=str(alias/'..'/'header.h')
            occurrences=evidence.include_occurrences(('. '+spelling+'\n. alias.h\n. alias.h\n').encode(),b'. alias.h\n','Linux')
            pre=check.acquire_include_bindings(occurrences,base,out)
            self.assertEqual({row['target'] for row in pre},{str(header)})
            self.assertEqual(len(pre),4)
            post=check.acquire_include_bindings(occurrences,base,out);self.assertEqual(post,pre)
            def verify(after,end):
                manifest,_=evidence.include_projection(pre,occurrences,'Linux');post_manifest,_=evidence.include_projection(after,occurrences,'Linux')
                files={name:path.read_bytes() for path in (out/'include-bytes').iterdir() for name in ['include-bytes/'+path.name]}
                for stage in ['compile','compile-discovery']:
                    files[stage+'.stdout']=('. '+spelling+'\n. alias.h\n. alias.h\n').encode();files[stage+'.stderr']=b'. alias.h\n'
                files['compile-include-bindings.json']=encode({'schema':1,'label':'compile','cwd':str(base),'pre':pre,'post':after})
                files['compile-includes-pre.json']=encode(manifest);files['compile-includes.json']=encode(post_manifest);files['native-includes-end.json']=encode(manifest)
                unique={row['raw']:(row['target'],row['sha256']) for row in end}
                files['native-include-bindings-end.json']=encode({'schema':1,'bindings':[{'cwd':str(base),'raw':raw,'target':target,'sha256':value} for raw,(target,value) in unique.items()]})
                self.verify(files,[('compile',[],str(base),None,(),True)],{'system':'Linux','root':str(base/'repo'),'out':str(out)})
            verify(post,check.acquire_include_bindings(occurrences,base,out))
            direct.unlink();direct.symlink_to(other)
            changed=check.acquire_include_bindings(occurrences,base,out)
            with self.assertRaisesRegex(ValueError,'temporal include alias|aliases preserved'):verify(changed,changed)
            with self.assertRaisesRegex(ValueError,'end resolution/bytes'):verify(post,changed)
            direct.unlink();direct.symlink_to(header);header.write_bytes(b'mutated')
            changed=check.acquire_include_bindings(occurrences,base,out)
            with self.assertRaises(ValueError):verify(changed,changed)
            with self.assertRaises(ValueError):verify(post,changed)
            relative=[{'stream':'stdout','ordinal':0,'raw':'header.h'}]
            self.assertEqual(check.acquire_include_bindings(relative,physical,out)[0]['target'],str(header))
            with self.assertRaises(FileNotFoundError):check.acquire_include_bindings(relative,base,out)
            direct.unlink();direct.symlink_to(base/'missing')
            with self.assertRaises(FileNotFoundError):check.acquire_include_bindings([occurrences[1]],base,out)
            direct.unlink();direct.symlink_to(physical,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'regular file'):check.acquire_include_bindings([occurrences[1]],base,out)

def edit_json(files,name,change):
    value=json.loads(files[name]);change(value);files[name]=encode(value)


def rehash(files):
    if 'commands.json' in files:
        commands=json.loads(files['commands.json'])
        for row in commands:
            for stream in ['stdout','stderr']:
                name=row['label']+'.'+stream
                if name in files:row[stream+'_sha256']=sha(files[name])
            for name in row['outputs']:
                if name in files:row['outputs'][name]=sha(files[name])
        files['commands.json']=encode(commands)
    refresh(files)


if __name__=='__main__':unittest.main()
