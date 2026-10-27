import json
from pathlib import PureWindowsPath, PurePosixPath
import unittest
from unittest.mock import patch

import check
import evidence
from cases import corpus
from hooks import NATIVE, OWNER, MUTANTS, instrument, inverse, mutate
from test_check import MemoryPath


def encode(value): return (json.dumps(value,sort_keys=True)+'\n').encode()
def sha(raw): return evidence.digest(raw)


def traces(inputs,mode,native,observed=True,mutation=None):
    commands=inputs.splitlines();lines=[];alloc=[];bodies=[];joints=[];physical=[]
    ordinal=0;live=[];counters=[0,0,0,0];changed=False;algorithm=False
    header={'schema':1,'mode':mode,'arena_base':4096,'slots':65536,'stride':128,'node_bytes':56,'raw_node_bytes':79,'node_type_alignment':8}
    zero=' '.join(['00000000']*48)
    for row,command in enumerate(commands):
        op=command.split()[0];events=[]
        if op=='C':
            slot=ordinal
            if mode=='descending':slot=65535-ordinal
            if mode=='alternating':slot=ordinal//2 if ordinal%2==0 else 65535-ordinal//2
            pointer=4096+slot*128;ordinal+=1;bodies.append(pointer+16);live.append(pointer)
            if mode!='ordinary':
                counters[0]+=1;events.append({'op':'alloc','route':'raw','ordinal':counters[0],'pointer':pointer,'size':79,'alignment':0})
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
            if mode!='ordinary':
                for pointer in live:
                    counters[1]+=1;events.append({'op':'free','route':'raw','ordinal':counters[1],'pointer':pointer})
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
        alloc.append({'kind':row,'counters':list(counters),'events':events})
    lines.append('Z '+str(len(commands)))
    alloc.append({'kind':'final','counters':list(counters),'events':[]})
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
    tools={name:{'path':str(P('C:/tools' if win else '/tools')/(name+suffix)),'sha256':sha(('synthetic tool '+name).encode())} for name in tool_names}
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
    context={'schema':1,'system':system,'root':str(root),'out':str(out),'tools':{name:entry['path'] for name,entry in tools.items()},'archive_names':bindings['actual_names']}
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
    for name in ['observed-btCollisionDispatcher','observed-btCollisionWorld','native-consumer','observed-consumer']:files[name+ext]=('synthetic object '+name).encode()
    for name in ['native','observed']:
        selected=sorted(member+ext for member in ['btDbvt','btDbvtBroadphase','btDiscreteDynamicsWorld',*(['btCollisionWorld','btCollisionDispatcher'] if name=='native' else [])])
        if win:maptext='\n'.join(' 0001:00000000 symbol 0000000140001000 '+library+':'+member for member in selected)
        elif system=='Darwin':maptext='\n'.join('[  '+str(i)+'] '+str(out/library)+'('+member+')' for i,member in enumerate(selected))
        else:maptext='\n'.join(str(out/library)+'('+member+') symbol' for member in selected)
        if name=='observed':maptext+='\n'+ ' '.join('observed-'+member+ext for member in ['btCollisionDispatcher','btCollisionWorld'])
        files[name+'.map']=maptext.encode();files[name+'-link-selection.json']=encode(selected)
        files[name+'-binary.json']=encode({'produced_sha256':sha(files[name+suffix]),'consumer_object_sha256':sha(files[name+'-consumer'+ext]),'observed_override_objects':{member+ext:sha(files[member+ext]) for member in (['observed-btCollisionDispatcher','observed-btCollisionWorld'] if name=='observed' else [])}})
    T=context['tools'];rust=[T['rustup'],'run','1.95.0','rustc','--edition=2021','-O','-C','linker='+T['rust_linker']]
    rargs=[*rust,'--extern','mds_crtmath='+str(out/'libmds_crtmath.rlib')];here=root/'tools/bullet-rust-discrete-world-check';shadow=out/'generated';commands=[];includes={}
    def add(label,argv,data=None,cwd=None,outputs=(),compile=False):
        argv=list(map(str,argv))
        if compile:
            discovery=[]
            for produced in outputs:
                name='discovery/'+label+'/'+P(produced).relative_to(out).as_posix();files[name]=('synthetic discovery '+name).encode();discovery.append(out/name)
            add(label+'-discovery',argv,data,cwd,discovery)
            header=str(root/'rust/crates/mds-bullet-sys/shim/det_math.h');key=header.lower() if win else header;value=before['rust/crates/mds-bullet-sys/shim/det_math.h']
            include_raw=('Note: including file: '+header+'\n' if win else '. '+header+'\n').encode()
            for stage in [label+'-discovery',label]:files[stage+'.stdout']=include_raw;files[stage+'.stderr']=b''
            commands[-1]['stdout_sha256']=sha(include_raw);commands[-1]['stderr_sha256']=sha(b'')
            files['include-bytes/'+value]=source['rust/crates/mds-bullet-sys/shim/det_math.h'];includes[key]=value
            files[label+'-includes-pre.json']=encode({key:value});files[label+'-includes.json']=encode({key:value})
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
        commands.append({'label':label,'argv':argv,'cwd':str(cwd or root/'rust'),'stdin_sha256':stdin,'tool':exe,'tool_sha256':exe_hash,'executable_sha256':exe_hash,
                         'returncode':0,'timeout':False,'seconds':0.01,'stdout_sha256':sha(files[label+'.stdout']),'stderr_sha256':sha(files[label+'.stderr']),
                         'inputs':{value:sha(files[evidence.captured_path(value,context)]) for value in evidence.command_input_paths(argv,system)},
                         'generated_inputs':generated if label=='rust-observed-build' or label.startswith('baseline-build-') else controls[label[len('mutant-build-'):]]['source_after'] if label.startswith('mutant-build-') else None,
                         'outputs':{P(produced).relative_to(out).as_posix():sha(files[P(produced).relative_to(out).as_posix()]) for produced in outputs}})
    add('helpers-normal',[T['python'],'-B',here/'test_check.py','-v']);add('helpers-optimized',[T['python'],'-B','-O',here/'test_check.py','-v'])
    for label,args in [('git-head',['rev-parse','HEAD']),('git-status',['status','--porcelain=v1']),('git-transport',['ls-files','--eol']),('git-attributes',['check-attr','--stdin','text','eol'])]:add(label,[T['git'],*args], ('\n'.join(sorted(before))+'\n').encode() if label=='git-attributes' else None)
    add('rust-compiler-path',[T['rustup'],'which','--toolchain','1.95.0','rustc']);add('rust-version',[T['rustup'],'run','1.95.0','rustc','-Vv'])
    crt=out/('mds_crtmath.lib' if win else 'libmds_crtmath.a')
    add('crt-build',[*rust,'--crate-name','mds_crtmath','--crate-type','rlib,staticlib','--print','native-static-libs',root/'rust/crates/mds-crtmath/src/lib.rs','--out-dir',out],outputs=[crt,out/'libmds_crtmath.rlib'])
    for name,source_name,extra in [('dedicated','discrete_collision_world.rs',['discrete_world_']),('pure','pure_bullet.rs',[])]:
        add(name+'-build',[*rargs,'--test','-D','warnings',root/'rust/crates/mds-bullet/tests'/source_name,'-o',out/(name+suffix)],outputs=[out/(name+suffix)])
        add(name+'-run',[out/(name+suffix),*extra])
    add('rust-observed-build',[*rargs,'--cfg','test',shadow/'tools/bullet-rust-discrete-world-check/runner.rs','-o',out/('rust-world'+suffix)],outputs=[out/('rust-world'+suffix)])
    add('rust-ordinary',[out/('rust-world'+suffix),policy_name],inputs.encode())
    add('compiler-version',[T['compiler'],'/?' if win else '--version'])
    if not win:add('native-linker-path',[T['compiler'],'-print-prog-name=ld'])
    add('macro-build',[T['compiler'],*flags,out/'effective-macros.cpp','/Fe'+str(out/('effective-macros'+suffix)),'/Fo'+str(out)+'/'] if win else [T['compiler'],*flags,out/'effective-macros.cpp','-o',out/('effective-macros'+suffix)],outputs=[out/('effective-macros'+suffix),*([out/'effective-macros.obj'] if win else [])],compile=True)
    add('actual-macros',[out/('effective-macros'+suffix)])
    def obj(source_name,output,label,extra=()):add(label,[T['compiler'],*flags,*extra,'/c',source_name,'/Fo'+str(output)] if win else [T['compiler'],*flags,*extra,'-c',source_name,'-o',output],outputs=[output],compile=True)
    for i,(source_name,output) in enumerate(zip(sources,objects)):
        obj(root/source_name,out/output,f'compile-{i:03d}')
        if P(source_name).stem in {'btDbvt','btDbvtBroadphase'}:add('expanded-'+P(source_name).stem,[T['compiler'],*flags,'/E' if win else '-E',root/source_name])
    add('archive-build',[T['archiver'],'/NOLOGO','/OUT:'+str(out/library),*[out/name for name in objects]] if win else [T['archiver'],'rcs',out/library,*[out/name for name in objects]],outputs=[out/library])
    add('archive-list',[T['archiver'],'/NOLOGO','/LIST',out/library] if win else [T['archiver'],'t',out/library])
    if win:
        for output in objects:add('extract-'+P(output).stem,[T['archiver'],'/NOLOGO','/EXTRACT:'+output,'/OUT:'+str(out/'extracted'/output),out/library],outputs=[out/'extracted'/output])
    else:add('archive-extract',[T['archiver'],'x',out/library],cwd=out/'extracted',outputs=[out/'extracted'/name for name in objects])
    hook=['/FI'+str(here/'observer.h'),'/DDW_OBSERVED=1'] if win else ['-include',here/'observer.h','-DDW_OBSERVED=1']
    for name in ['btCollisionDispatcher','btCollisionWorld']:obj(shadow/(NATIVE+name+'.cpp'),out/('observed-'+name+ext),'observed-'+name,hook)
    for name in ['native','observed']:
        prefix=[out/('observed-'+member+ext) for member in ['btCollisionDispatcher','btCollisionWorld']] if name=='observed' else [];extra=hook if name=='observed' else [];src=(shadow if name=='observed' else root)/'tools/bullet-rust-discrete-world-check/oracle.cpp';consumer=out/(name+'-consumer'+ext);exe=out/(name+suffix);linkmap=out/(name+'.map')
        obj(src,consumer,name+'-consumer-build',extra);add(name+'-consumer-expanded',[T['compiler'],*flags,*extra,'/E' if win else '-E',src])
        libs=['kernel32.lib'] if win else ([] if system=='Darwin' else ['-ldl','-lpthread','-lm'])
        add(name+'-link',[T['compiler'],'/nologo','/MD','/EHsc',consumer,*prefix,out/library,crt,'/Fe'+str(exe),'/link','/MAP:'+str(linkmap),'/VERBOSE:LIB',*libs] if win else [T['compiler'],consumer,*prefix,out/library,crt,*libs,'-fuse-ld='+T['native_linker'],('-Wl,-map,' if system=='Darwin' else '-Wl,-Map,')+str(linkmap),'-o',exe],outputs=[exe,linkmap])
        for mode in evidence.MODES:add(name+'-'+mode,[exe,mode,out/(name+'-allocator-'+mode+'.jsonl')],inputs.encode(),outputs=[out/(name+'-allocator-'+mode+'.jsonl')])
    for mode in evidence.MODES:add('rust-bound-'+mode,[out/('rust-world'+suffix),policy_name],bound[mode])
    for name in MUTANTS:
        for prefix in ['baseline','mutant']:
            exe=out/(prefix+'-'+name+suffix);add(prefix+'-build-'+name,[*rargs,'--cfg','test',out/'mutants'/name/'tools/bullet-rust-discrete-world-check/runner.rs','-o',exe],outputs=[exe]);add(prefix+'-run-'+name,[exe,policy_name],inputs.encode())
    files['commands.json']=encode(commands);files['native-includes-end.json']=encode(includes)
    report={'schema':2,'status':'CONTROLLED_PASS','base':evidence.BASE,'policy':policy_name,'native':'ACTUAL_ORIGINAL_PUBLIC_SHIM_WITH_UNMODIFIED_ARCHIVE_CONTROL','compiled_controls':17,'public_world':'UNCHANGED_NATIVE_BACKEND','scope':'private default-DBVT discrete collision owner','host':{'system':system,'machine':'amd64' if win else 'arm64' if system=='Darwin' else 'x86_64','image':'synthetic'},'head':'1'*40,'compiler':tools['compiler'],'checkpoints':len(inputs.splitlines()),'cases':len(cases),'controlled':{mode:len(inputs.splitlines()) for mode in evidence.MODES},'ordinary_unbound':'EQUAL','limits':evidence.LIMITS}
    files['report.json']=encode(report);refresh(files)
    expected={'expected_head':'1'*40,'canonical_sources':source,'inputs':inputs,'cases':cases,'expected_host':{(system,report['host']['machine'])},'expected_policy':policy_name}
    return files,expected


def refresh(files):
    files['artifact-manifest.json']=encode({name:sha(raw) for name,raw in files.items() if name!='artifact-manifest.json'})


class AdmissionControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.windows,cls.expected=fixture()

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
        for key,value in [('native','UNRUN'),('compiled_controls','UNRUN'),('schema',3),('checkpoints',True),('unrecognized','foreign')]:
            self.rejected(lambda files,key=key,value=value:edit_json(files,'report.json',lambda report:report.update({key:value})), 'complete genuine|completed native|boolean|fields')
        self.rejected(lambda files:files.update({'source-end.json':b'{}\n'}),'source-start equals source-end')
        self.rejected(lambda files:files.update({'git-attributes.stdout':files['git-attributes.stdout'].replace(b': unset',b': set')}),'exact trusted Git attributes')
        self.rejected(lambda files:files.update({'git-transport.stdout':files['git-transport.stdout'].replace(b'w/crlf',b'w/lf')}),'physical source/Git transport binding')
        for name in ['commands.json','archive-bindings.json','native-includes-end.json','native-link-selection.json','native-binary.json','semantic-controls.json','observed-ordinary.stdout']:
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

    def test_physical_source_object_archive_and_member_bindings(self):
        source='source/'+OWNER
        self.rejected(lambda files:files.update({source:files[source]+b'foreign'}),'physical canonical source')
        def foreign_object(files):
            name=json.loads(files['archive-bindings.json'])['members'][0]['object'];files[name]=b'foreign object'
            edit_json(files,'archive-bindings.json',lambda binding:binding['members'][0].update(sha256=sha(files[name])))
        self.rejected(foreign_object,'archive payload/extracted/object equality')
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
            name='macro-build';receipt=json.loads(files[name+'-includes.json']);key=next(iter(receipt));raw=b'foreign include';identity=sha(raw);files['include-bytes/'+identity]=raw
            for suffix in ['-includes.json','-includes-pre.json']:files[name+suffix]=encode({key:identity})
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

    def test_directed_mutant_witness_and_bool_integer_are_rejected(self):
        self.rejected(lambda files:edit_json(files,'semantic-controls.json',lambda controls:controls['default-force'].update(semantic_rows=[])), 'derived valid directed semantic witness')
        self.rejected(lambda files:edit_json(files,'semantic-controls.json',lambda controls:controls['default-force'].update(normal_exit='UNRUN')), 'derived valid directed semantic witness')
        self.rejected(lambda files:edit_json(files,'commands.json',lambda rows:rows[0].update(seconds=True)), 'boolean in integer receipt field')
        self.rejected(lambda files:files.update({'report.json':files['report.json'].replace(b'"schema": 2',b'"schema": 2, "schema": 2')}), 'duplicate')
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
            self.assertEqual(cwd,str(PureWindowsPath(context['root'])/'rust'))
            if '-o' in argv or label=='crt-build':self.assertEqual(argv[:6],[context['tools']['rustup'],'run','1.95.0','rustc','--edition=2021','-O'])
        report=json.loads(self.windows['report.json']);report.pop('compiler')
        report.update(schema=3,native='WINDOWS_SOURCE_REPLAY',producer_report_sha256=sha(self.windows['report.json']),ordinary_unbound='WINDOWS_SOURCE_REPLAY',limits=evidence.LIMITS+['replay Rust inner linker chain unobserved'])
        self.assertEqual(evidence.replay_report(report,self.expected['expected_head'],self.expected['inputs'],self.expected['cases']),report)
        for key,value in [('schema',2),('compiled_controls','UNRUN'),('producer_report_sha256','foreign'),('native','UNRUN')]:
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
            with self.assertRaises(ValueError):evidence.archive_members(raw)


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
