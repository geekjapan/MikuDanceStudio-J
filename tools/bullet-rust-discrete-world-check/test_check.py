import copy
import json
from pathlib import Path
import unittest

from cases import corpus
from hooks import CORE, NATIVE, OWNER, SHIM, MUTANTS, OBSERVATION_PATHS, instrument, inverse, mutate
from trace import bind_inputs, comparison, validate, validate_allocator, validate_noninterference, validate_physical, decode_json
import check


class MemoryPath:
    def __init__(self, files, name=''):
        self.files, self.name = files, name
    def __truediv__(self, name):
        return MemoryPath(self.files, self.name + ('/' if self.name else '') + str(name))
    def read_bytes(self):
        return self.files[self.name]
    def read_text(self):
        return self.read_bytes().decode().replace('\r\n','\n')
    def write_bytes(self, value):
        self.files[self.name] = value


def synthetic(native=False):
    commands = 'H synthetic injected\nC\nC\nD\nX\n'
    lines = ['O 0 H 0 0 0 1']
    zero = ' '.join(['00000000']*48)
    def body(row, i):
        return f'B {row} {i} 0 1 {i+1} 1 -1 {i} {zero}'
    for row, count in [(1,1),(2,2)]:
        lines.append(f'O {row} C {count} 0 0 1')
        lines.extend(body(row,i) for i in range(count))
    lines.extend(['E 3 A+ 1','E 3 M+ 1 0 1','O 3 D 2 1 1 1',body(3,0),body(3,1),
                  'P 3 0 0 1 1','M 3 0 1 1 0 1 00000000 00000000 0',
                  'E 4 U 1','E 4 M- 1','E 4 A- 1','E 4 U 0','O 4 X 0 0 0 1','Z 5'])
    if native:
        target=[]
        counts={0:0,1:1,2:2,3:2}
        for i,line in enumerate(lines):
            target.append(line)
            row=int(line.split()[1])
            if row in counts and line.split()[0]!='E' and (i+1==len(lines) or int(lines[i+1].split()[1])!=row):
                count=counts[row]
                nodes=[]
                if count==2:nodes.append('-1 128 '+ ' '.join(['00000000']*6))
                nodes.extend(f'{j} {256+j*128} '+ ' '.join(['00000000']*6) for j in range(count))
                target.append(f'T {row} 0 {len(nodes)} '+ ' '.join(nodes)+(' ' if nodes else '')+'0')
                target.append(f'T {row} 1 0 0')
        lines=target
    return commands, ('\n'.join(lines)+'\n').encode()


class SourceControls(unittest.TestCase):
    def test_complete_synthetic_lifetimes_and_no_manifold_algorithm(self):
        commands, raw = synthetic()
        rows=validate(raw,commands)
        self.assertEqual(rows[3]['pairs'],[[0,1,1]])
        changed=raw.replace(b'E 3 M+ 1 0 1\n',b'').replace(b' D 2 1 1 1',b' D 2 1 0 1').replace(b'M 3 0 1 1 0 1 00000000 00000000 0\n',b'').replace(b'E 4 M- 1\n',b'')
        self.assertEqual(len(validate(changed,commands)[3]['manifolds']),0)

    def test_missing_extra_corrupt_operation_and_lifetime_reject(self):
        commands,raw=synthetic()
        controls=[raw.replace(b'O 1 C 1 0 0 1\n',b''),raw+b'\n',raw.replace(b'O 2 C',b'O 2 D'),
                  raw.replace(b'E 4 M- 1\n',b''),raw.replace(b'E 4 U 1',b'E 4 U 0'),
                  raw.replace(b'P 3 0 0 1 1',b'P 3 0 0 1 2'),raw.replace(b'00000000',b'0000000g',1),
                  raw.replace(b'Z 5',b'Z 4'),raw.replace(b'B 2 1 ',b'B 2 0 '),raw.replace(b'E 3 A+ 1',b'E 3 A+ 2')]
        for changed in controls:
            with self.subTest(changed=changed[-30:]),self.assertRaises(ValueError): validate(changed,commands)

    def test_native_leaf_owner_and_cached_free_rank_binding(self):
        commands,raw=synthetic(True)
        rows=validate(raw,commands,native=True)
        bound=bind_inputs(commands,rows)
        self.assertEqual(bound.count('BIND'),4)
        for old,new in [(b'-1 128',b'-1 256'),(b'1 384',b'0 384')]:
            with self.assertRaises(ValueError):validate(raw.replace(old,new),commands,native=True)
        self.assertEqual(comparison(rows),comparison(validate(synthetic()[1],commands)))

    def test_allocator_rejects_orphan_free_and_false_mode(self):
        rows=validate(b'O 0 H 0 0 0 1\nO 1 X 0 0 0 1\nZ 2\n','H x public\nX\n')
        header={'schema':2,'domain':'unmodified-control','mode':'ascending','arena_base':4096,'slots':65536,'stride':128,'node_bytes':56,'raw_node_bytes':79,'node_type_alignment':8}
        records=[header,*[{'kind':kind,'counters':[0,0,0,0],'events':[],'world':1,'trees':[1024,2048],'node_counters':[0]*4,'nodes':[]} for kind in [0,1,'final']]]
        raw=lambda:('\n'.join(json.dumps(r) for r in records)+'\n').encode()
        validate_allocator(raw(),rows,'ascending',domain='unmodified-control')
        records[1]['events']=[{'op':'free','route':'raw','pointer':4096,'ordinal':1}]
        with self.assertRaises(ValueError):validate_allocator(raw(),rows,'ascending',domain='unmodified-control')
        records[1]['events']=[]
        with self.assertRaises(ValueError):validate_allocator(raw(),rows,'descending',domain='unmodified-control')

    def test_allocator_live_node_prefix_and_full_free_are_required(self):
        rows=[{'trees':[[[[0,4112,*(['00000000']*6)]],0],[[],0]]},{'trees':[]}]
        records=[{'schema':2,'domain':'unmodified-control','mode':'ascending','arena_base':4096,'slots':65536,'stride':128,'node_bytes':56,'raw_node_bytes':79,'node_type_alignment':8},
                 {'kind':0,'counters':[1,0,0,0],'events':[{'op':'alloc','route':'raw','ordinal':1,'pointer':4096,'size':79,'alignment':0,'node_call':0}],'world':1,'trees':[1024,2048],'node_counters':[0]*4,'nodes':[]},
                 {'kind':1,'counters':[1,1,0,0],'events':[{'op':'free','route':'raw','ordinal':1,'pointer':4096,'node_call':0}],'world':1,'trees':[1024,2048],'node_counters':[0]*4,'nodes':[]},
                 {'kind':'final','counters':[1,1,0,0],'events':[],'world':1,'trees':[1024,2048],'node_counters':[0]*4,'nodes':[]}]
        raw=lambda value:('\n'.join(json.dumps(v) for v in value)+'\n').encode()
        validate_allocator(raw(records),rows,'ascending',domain='unmodified-control')
        for field,value in [('ordinal',2),('pointer',4224),('size',80),('alignment',16)]:
            changed=copy.deepcopy(records);changed[1]['events'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate_allocator(raw(changed),rows,'ascending',domain='unmodified-control')
        changed=copy.deepcopy(records);changed[2]['events']=[]
        with self.assertRaises(ValueError):validate_allocator(raw(changed),rows,'ascending',domain='unmodified-control')

    def test_policy_classifier_rejects_unknown_mixed_and_incomplete_bodies(self):
        parameters='const btDbvtAabbMm& a, const btDbvtAabbMm& b'
        generic='Intersect('+parameters+'){return 1;} Select('+parameters+', int c){return Proximity();} Merge('+parameters+', int c){return 2;}'
        sse=generic.replace('return 1;', 'return _mm_cmplt_ps();').replace('return Proximity();','return _mm_cmple_ss();').replace('return 2;','return _mm_min_ps();')
        self.assertEqual(check.policy(generic)['policy'],'generic-reference')
        self.assertEqual(check.policy(sse)['policy'],'mmd-win64-sse')
        for changed in [generic+generic,generic[:-1],generic.replace('Proximity','Other'),sse.replace('_mm_min_ps','Other')]:
            with self.assertRaises(ValueError):check.policy(changed)

    def test_capture_inventory_rejects_missing_extra_corrupt_and_unsafe_paths(self):
        good={'source/a.cpp':'a'*64,'native.stdout':'b'*64}
        check.inventory(good,dict(good))
        with self.assertRaisesRegex(ValueError,'duplicate'):
            decode_json('{"status":"FAIL","status":"CONTROLLED_PASS"}')
        for expected,actual in [(good,{'source/a.cpp':'a'*64}),(good,{**good,'extra':'c'*64}),(good,{**good,'native.stdout':'c'*64}),({'../escape':'a'*64},{'../escape':'a'*64}),({'a':'INVALID'},{'a':'INVALID'})]:
            with self.assertRaises(ValueError):check.inventory(expected,actual)

    def test_native_physical_timing_is_separate_and_reverse_ordered(self):
        commands='H x public\nC\nC\nJ\nX\n'
        raw=b'JOINT_CREATE 3 0 123\nPHYSICAL 4 joint 123 -1\nPHYSICAL 4 body 456 1\nPHYSICAL 4 body 789 0\n'
        validate_physical(raw,commands)
        for changed in [raw.replace(b'joint 123',b'joint 999'),raw.replace(b'456 1',b'456 0'),raw.splitlines(keepends=True)[0]+b''.join(raw.splitlines(keepends=True)[2:])]:
            with self.assertRaises(ValueError):validate_physical(changed,commands)

    def test_actual_source_hook_inverse_lf_and_windows_transport(self):
        touched=OBSERVATION_PATHS
        for windows in [False,True]:
            originals={path:(check.ROOT/path).read_bytes().replace(b'\r\n',b'\n') for path in touched}
            if windows:originals={path:raw.replace(b'\n',b'\r\n') for path,raw in originals.items()}
            memory=MemoryPath(copy.deepcopy(originals))
            changes=instrument(memory,check.HERE)
            inverse(memory,changes,originals)
            for name in MUTANTS:
                mutant=MemoryPath(copy.deepcopy(memory.files));edits=mutate(mutant,name)
                self.assertEqual(len(edits),1)
                self.assertNotEqual(mutant.files[OWNER],memory.files[OWNER])
            memory.files[OWNER]+=b'corrupt'
            with self.assertRaises(ValueError):inverse(memory,changes,originals)

    def test_corpus_reaches_boundaries_and_preserves_public_fixture_separation(self):
        inputs,cases=corpus()
        names={c['name'] for c in cases}
        self.assertTrue({f'shapes-{a}-{b}' for a in range(4) for b in range(4)}<=names)
        self.assertTrue({f'force-{f}-activation-{a}' for f in (0,1) for a in range(6)}<=names)
        commands=inputs.splitlines()
        for case in cases:
            self.assertEqual(commands[case['start']].split()[0],'H')
            self.assertEqual(commands[case['end']],'X')
            if case['scope']=='public':self.assertFalse(any(line.split()[0] in {'A','I','V'} for line in commands[case['start']:case['end']]))
        import struct
        f32=lambda f:struct.unpack('<f',struct.pack('<f',f))[0]
        squared=[]
        for extent in [499999.9375,499999.96875,500000.0]:
            diagonal=f32(2*f32(extent+f32(.02)))
            squared.append(f32(f32(diagonal*diagonal)+f32(2.04*2.04*2)))
        self.assertLess(squared[0],f32(1e12));self.assertEqual(squared[1],f32(1e12));self.assertGreater(squared[2],f32(1e12))

    def test_literal_command_file_roles_and_success_outputs(self):
        from evidence import command_files
        from unittest.mock import patch
        context={'system':'Linux','root':'/repo','out':'/capture','archive_objects':('a.o','b.o')}
        def roles(label,argv,ctx=context):
            value=command_files(label,argv,ctx)
            return value.inputs,tuple((v.physical,v.retained) for v in value.outputs)
        self.assertEqual(roles('archive-build',['/tools/ar','rcs','/capture/lib.a','/capture/a.o']),
                         (('/capture/a.o',),(('/capture/lib.a','lib.a'),)))
        self.assertEqual(roles('archive-list',['/tools/ar','t','/capture/lib.a']), (('/capture/lib.a',),()))
        self.assertEqual(roles('archive-extract',['/tools/ar','x','/capture/lib.a']),
                         (('/capture/lib.a',),(('/capture/extracted/a.o','extracted/a.o'),('/capture/extracted/b.o','extracted/b.o'))))
        self.assertEqual(roles('crt-build',['/tools/rustup','/repo/lib.rs','--out-dir','/capture']),
                         (('/repo/lib.rs',),(('/capture/libmds_crtmath.a','libmds_crtmath.a'),('/capture/libmds_crtmath.rlib','libmds_crtmath.rlib'))))
        self.assertEqual(roles('native-link',['/tools/c++','/capture/a.o','/capture/lib.a','-o','/capture/native']),
                         (('/capture/a.o','/capture/lib.a'),(('/capture/native','native'),('/capture/native.map','native.map'))))
        self.assertEqual(roles('observed-ascending',['/capture/observed','ascending','/capture/receipt.jsonl']),
                         ((),(('/capture/receipt.jsonl','receipt.jsonl'),)))
        self.assertEqual(roles('compile-000-discovery',['/tools/c++','-include','/repo/det.h','-I','/repo/includes','-c','/repo/a.cpp','-o','/capture/a.o']),
                         (('/repo/det.h','/repo/a.cpp'),(('/capture/a.o','discovery/compile-000/a.o'),)))
        win={'system':'Windows','root':'C:/repo','out':'C:/capture','archive_objects':('a.obj','b.obj')}
        self.assertEqual(roles('extract-a',['C:/tools/lib','/EXTRACT:a.obj','/OUT:C:/capture/extracted/a.obj','C:/capture/Bullet.lib'],win),
                         (('C:\\capture\\Bullet.lib',),(('C:\\capture\\extracted\\a.obj','extracted/a.obj'),)))
        self.assertEqual(roles('macro-build-discovery',['C:/tools/cl','/FIC:/repo/det.h','C:/capture/effective-macros.cpp','/FeC:/capture/macro.exe','/FoC:/capture/'],win),
                         (('C:\\repo\\det.h','C:\\capture\\effective-macros.cpp'),(('C:\\capture\\macro.exe','discovery/macro-build/macro.exe'),('C:\\capture\\effective-macros.obj','discovery/macro-build/effective-macros.obj'))))
        files={'/capture/a.o':b'object'}
        class File:
            def __init__(self,name): self.name=str(name)
            def __truediv__(self,name): return File(self.name+'/'+name)
            def __eq__(self,other): return isinstance(other,File) and self.name==other.name
            def is_file(self): return self.name in files
            def read_bytes(self):
                if self.name not in files: raise FileNotFoundError(self.name)
                return files[self.name]
        argv=['/tools/ar','rcs','/capture/lib.a','/capture/a.o']
        with self.assertRaises(FileNotFoundError): File(argv[2]).read_bytes()
        value=command_files('archive-build',argv,context)
        self.assertEqual([File(name).read_bytes() for name in value.inputs],[b'object'])
        with patch.object(check,'Path',File):
            with self.assertRaisesRegex(ValueError,'successful command missing output'):
                check.retain_outputs(value.outputs,File('/capture'),success=True)
            self.assertEqual(check.retain_outputs(value.outputs,File('/capture'),success=False),{})
            files['/capture/lib.a']=b'archive'
            self.assertEqual(check.retain_outputs(value.outputs,File('/capture'),success=True),{'lib.a':check.digest(b'archive')})

    def test_tool_alias_persona_and_same_bytes_retarget_model(self):
        from unittest.mock import patch
        files={'/targets/rustup-init':b'one tool','/targets/other':b'one tool','/targets/clang':b'clang tool'}
        aliases={'/tools/rustup':'/targets/rustup-init','/tools/clang++':'/targets/clang'}
        class File:
            def __init__(self,name): self.name=str(name)
            def __str__(self): return self.name
            def absolute(self): return self
            def resolve(self,strict): return File(aliases.get(self.name,self.name))
            def read_bytes(self): return files[self.name]
        def dispatch_model(binding,args):
            return binding['path'].rsplit('/',1)[-1]=='rustup' and args[0]=='which'
        with patch.object(check,'Path',File),patch.object(check.shutil,'which',lambda name:name):
            binding=check.executable_identity('/tools/rustup')
            self.assertTrue(dispatch_model(binding,['which']))
            self.assertFalse(dispatch_model({**binding,'path':binding['target']},['which']))
            self.assertEqual(check.executable_identity('/tools/clang++')['path'],'/tools/clang++')
            aliases['/tools/rustup']='/targets/other'
            changed=check.executable_identity('/tools/rustup')
            self.assertEqual(binding['sha256'],changed['sha256']);self.assertNotEqual(binding,changed)

    def test_raw_scopes_follow_typed_calls_with_null_free_gaps(self):
        inputs='H synthetic public\nX\n'
        rows=validate(b'O 0 H 0 0 0 1\nT 0 0 0 0\nT 0 1 0 0\nO 1 X 0 0 0 1\nZ 2\n',inputs,native=True,observed=False)
        header=dict(schema=2,domain='generated-dbvt-node-sites',mode='ascending',arena_base=4096,slots=65536,stride=128,node_bytes=56,raw_node_bytes=79,node_type_alignment=8)
        def raw(op,pointer,ordinal,call):
            value=dict(op=op,route='raw',pointer=pointer,ordinal=ordinal,node_call=call)
            if op=='alloc':value.update(size=79,alignment=0)
            return value
        def node(op,sequence,call,pointer,generation):
            return dict(op=op,sequence=sequence,call=call,world=1,tree=0,pointer=pointer,generation=generation)
        def checkpoint(kind):
            return dict(kind=kind,counters=[2,2,0,0],events=[],world=1,trees=[1024,2048],node_counters=[2,2,0,2],nodes=[])
        good=[header,checkpoint(0),checkpoint(1),checkpoint('final')]
        good[1]['events']=[raw('alloc',4096,1,1),raw('alloc',4224,2,2),raw('free',4096,1,3),raw('free',4224,2,4)]
        good[1]['nodes']=[node('alloc',1,1,4112,1),node('alloc',2,2,4240,2),node('cache',3,0,4112,1),node('free',4,3,4112,1),node('cache',5,0,4240,2),node('free',6,4,4240,2)]
        control=copy.deepcopy(good);control[0]['domain']='unmodified-control'
        for record in control[1:]:
            record['nodes']=[];record['node_counters']=[0]*4
            for event in record['events']:event['node_call']=0
        def encoded(value):return b''.join((json.dumps(record,sort_keys=True)+'\n').encode() for record in value)
        control_bytes=encoded(control)
        def verify(value):
            validate_allocator(encoded(value),rows,'ascending',domain='generated-dbvt-node-sites')
            validate_noninterference(control_bytes,rows,encoded(value),rows,'ascending')
        validate_allocator(control_bytes,rows,'ascending',domain='unmodified-control')
        verify(good)
        bad=copy.deepcopy(good)
        for event,call in zip(bad[1]['events'],[2,1,4,3]):event['node_call']=call
        bad[1]['nodes']=[node('alloc',1,1,4240,1),node('alloc',2,2,4112,2),node('cache',3,0,4240,1),node('free',4,3,4240,1),node('cache',5,0,4112,2),node('free',6,4,4112,2)]
        def candidate_view(value):
            value=copy.deepcopy(value);value[0].pop('domain')
            for record in value[1:]:
                record.pop('nodes');record.pop('node_counters')
                for event in record['events']:event.pop('node_call')
            return value
        self.assertEqual(candidate_view(control),candidate_view(good))
        self.assertEqual(candidate_view(good),candidate_view(bad))
        with self.assertRaisesRegex(ValueError,'monotonic nonnested raw node call'):verify(bad)
        gaps=copy.deepcopy(good)
        gaps[1]['nodes'].insert(1,node('free',0,2,0,0))
        for sequence,event in enumerate(gaps[1]['nodes'],1):
            event['sequence']=sequence
            if event['call']>=2 and event['pointer']:event['call']+=1
        for event in gaps[1]['events'][1:]:event['node_call']+=1
        for record in gaps[1:]:record['node_counters'][1]+=1
        verify(gaps)
        for scopes in ([1,1,3,4],[1,2,4,3],[1,2,3,5]):
            changed=copy.deepcopy(good)
            for event,call in zip(changed[1]['events'],scopes):event['node_call']=call
            with self.subTest(scopes=scopes),self.assertRaises(ValueError):verify(changed)
        changed=copy.deepcopy(good)
        changed[2]['events']=changed[1]['events'][2:];changed[1]['events']=changed[1]['events'][:2]
        with self.assertRaisesRegex(ValueError,'typed scoped callback'):verify(changed)
        self.assertEqual(encoded(control),control_bytes)

    def test_candidate_and_proven_node_domains_and_transient_controls(self):
        from evidence import digest
        rows=[{'header':['H'],'trees':[[[],0],[[],0]]},
              {'trees':[[[[0,4368,*(['00000000']*6)]],0],[[],0]]},
              {'trees':[[[],4368],[[],0]]},
              {'trees':[[[[0,4368,*(['00000000']*6)]],0],[[],0]]}, {'trees':[]}]
        header={'schema':2,'domain':'generated-dbvt-node-sites','mode':'ascending','arena_base':4096,'slots':65536,'stride':128,'node_bytes':56,'raw_node_bytes':79,'node_type_alignment':8}
        def raw(op,pointer,ordinal,call):
            event={'op':op,'route':'raw','pointer':pointer,'ordinal':ordinal,'node_call':call}
            if op=='alloc':event.update(size=79,alignment=0)
            return event
        def node(op,seq,call,pointer,generation):
            return dict(op=op,sequence=seq,call=call,world=1,tree=0,pointer=pointer,generation=generation)
        def checkpoint(kind,counts,events,node_counts,nodes):
            return dict(kind=kind,counters=counts,events=events,world=1,trees=[1024,2048],node_counters=node_counts,nodes=nodes)
        records=[header,
                 checkpoint(0,[2,1,0,0],[raw('alloc',4096,1,0),raw('alloc',4224,2,1),raw('free',4224,1,2)],[1,1,0,1],[node('alloc',1,1,4240,1),node('cache',2,0,4240,1),node('free',3,2,4240,1)]),
                 checkpoint(1,[3,1,0,0],[raw('alloc',4352,3,3)],[2,1,0,1],[node('alloc',4,3,4368,2)]),
                 checkpoint(2,[3,1,0,0],[],[2,1,0,2],[node('cache',5,0,4368,2)]),
                 checkpoint(3,[3,1,0,0],[],[2,1,1,2],[node('reuse',6,0,4368,2)]),
                 checkpoint(4,[3,3,0,0],[raw('free',4352,2,4),raw('free',4096,3,0)],[2,2,1,3],[node('cache',7,0,4368,2),node('free',8,4,4368,2)]),
                 checkpoint('final',[3,3,0,0],[],[2,2,1,3],[])]
        def encoded(value):return b''.join((json.dumps(record)+'\n').encode() for record in value)
        def verify(value):return validate_allocator(encoded(value),rows,'ascending',domain='generated-dbvt-node-sites')
        self.assertEqual(verify(records)[1][0][2],((0,'raw',1),))
        changes=[]
        for record,field,value in [(2,'tree',1),(2,'generation',1),(3,'op','reuse'),(4,'op','cache'),(5,'pointer',4240)]:
            changed=copy.deepcopy(records);changed[record]['nodes'][0][field]=value;changes.append(changed)
        changed=copy.deepcopy(records);changed[2]['nodes']=[];changes.append(changed)
        changed=copy.deepcopy(records);changed[2]['nodes']*=2;changes.append(changed)
        changed=copy.deepcopy(records);changed[5]['events'].pop();changes.append(changed)
        changed=copy.deepcopy(records);changed[1]['nodes']=[]
        for record in changed[1:]:
            record['node_counters']=[a-b for a,b in zip(record['node_counters'],[1,1,0,1])]
            for event in record['nodes']:event['sequence']-=3
        changes.append(changed)
        changed=copy.deepcopy(records);changed[2]['events'][0]['route']='aligned';changes.append(changed)
        changed=copy.deepcopy(records);changed[3]['trees'][0]=3072;changes.append(changed)
        for changed in changes:
            with self.subTest(identity=digest(encoded(changed))),self.assertRaises(ValueError):verify(changed)
        control=copy.deepcopy(records);control[0]['domain']='unmodified-control'
        for record in control[1:]:
            record['nodes']=[];record['node_counters']=[0]*4
            for event in record['events']:event['node_call']=0
        validate_allocator(encoded(control),rows,'ascending',domain='unmodified-control')
        changed=copy.deepcopy(control);changed[5]['events'].pop()
        with self.assertRaisesRegex(ValueError,'all candidates'):validate_allocator(encoded(changed),rows,'ascending',domain='unmodified-control')
        self.assertEqual(control[1]['events'][0]['node_call'],0)


    def test_archive_payload_presentation_and_validated_specials(self):
        import evidence
        from test_evidence import archive
        def member(name,raw):
            return name.encode().ljust(16)+b'0'.ljust(12)+b'0'.ljust(6)+b'0'.ljust(6)+b'100644'.ljust(8)+str(len(raw)).encode().ljust(10)+b'`\n'+raw+(b'\n' if len(raw)%2 else b'')
        payload={'second.obj':b'second','first.obj':b'first'}
        parsed=evidence.decode_archive(archive(payload))
        self.assertEqual(list(parsed.payloads),list(payload))
        evidence.archive_listing(parsed,['first.obj','second.obj'],'Windows')
        for listing in [['first.obj'],['first.obj','second.obj','extra'],['first.obj','second.obj','second.obj'],['FIRST.obj','second.obj'],['first.obj','second.obj','__.SYMDEF']]:
            with self.assertRaises(ValueError):evidence.archive_listing(parsed,listing,'Windows')
        symbol=(0).to_bytes(4,'little')*2
        symname=b'__.SYMDEF'+b'\0'*3
        raw=b'!<arch>\n'+member('#1/12',symname+symbol)+member('first.o/',b'first')
        parsed=evidence.decode_archive(raw)
        self.assertEqual(parsed.specials,('__.SYMDEF',));self.assertEqual(parsed.payloads,{'first.o':b'first'})
        evidence.archive_listing(parsed,['__.SYMDEF','first.o'],'Darwin')
        for listing,system in [(['__.SYMDEF','first.o'],'Linux'),(['__.SYMDEF','__.SYMDEF','first.o'],'Darwin'),(['__.SYMDEF SORTED','first.o'],'Darwin')]:
            with self.assertRaises(ValueError):evidence.archive_listing(parsed,listing,system)
        malformed=[raw[:-1],raw.replace(b'#1/12',b'#1/99'),raw.replace(symname,b'__.SYMDEF_BAD'),
                   raw[:8]+member('#1/12',symname+symbol)+raw[8:],
                   b'!<arch>\n'+member('first.o/',b'x')+member('FIRST.o/',b'y'),
                   b'!<arch>\n'+member('//',b'longname.obj/\n')+member('/2',b'x'),
                   b'!<arch>\n'+member('//',b'unterminated')+member('/0',b'x'),
                   b'!<arch>\n'+member('//',b'longname.obj/\n')+member('/999',b'x'),
                   b'!<arch>\n'+member('/',(1).to_bytes(4,'big')+(999).to_bytes(4,'big')+b'symbol\0')+member('first.o/',b'x')]
        for candidate in malformed:
            with self.assertRaises(ValueError):evidence.decode_archive(candidate)
        first_table=(1).to_bytes(4,'big')+(154).to_bytes(4,'big')+b's\0'
        second_table=(1).to_bytes(4,'little')+(154).to_bytes(4,'little')+(1).to_bytes(4,'little')+(1).to_bytes(2,'little')+b's\0'
        coff=b'!<arch>\n'+member('/',first_table)+member('/',second_table)+member('first.obj/',b'x')
        self.assertEqual(evidence.decode_archive(coff).payloads,{'first.obj':b'x'})
        for broken in [second_table[:12]+(2).to_bytes(2,'little')+second_table[14:],second_table[:4]+(999).to_bytes(4,'little')+second_table[8:]]:
            with self.assertRaises(ValueError):evidence.decode_archive(b'!<arch>\n'+member('/',first_table)+member('/',broken)+member('first.obj/',b'x'))
        first=member('/',(0).to_bytes(4,'big')+b'\0')
        second=member('/',(0).to_bytes(4,'little')+(0).to_bytes(4,'little')+b'\0')
        evidence.decode_archive(b'!<arch>\n'+first+second+member('first.obj/',b'x'))
        with self.assertRaises(ValueError):evidence.decode_archive(b'!<arch>\n'+first+second+first+member('first.obj/',b'x'))

    def test_bsd_index_bodies_names_widths_endianness_and_offsets(self):
        import evidence
        from test_evidence import bsd_archive
        payloads={'first.o':b'first','second.o':b'second'}
        for name in ['__.SYMDEF','__.SYMDEF SORTED','__.SYMDEF_64','__.SYMDEF_64 SORTED']:
            for order in ['little','big']:
                raw,body=bsd_archive(payloads,name,order);parsed=evidence.decode_archive(raw)
                self.assertEqual(parsed.bsd_indexes,{name:body});self.assertEqual(parsed.payloads,payloads);self.assertEqual(parsed.specials,(name,))
                width=8 if '_64' in name else 4;start=68+len(name)+(-len(name)%4)
                def replace(offset,value):return raw[:start+offset]+value.to_bytes(width,order)+raw[start+offset+width:]
                for malformed in [replace(2*width,999),replace(width,1),replace(3*width,999),
                                  raw[:8]+raw[8:start+len(body)+(len(name)+(-len(name)%4)+len(body))%2]+raw[8:],
                                  raw.replace(name.encode(),(name+'_BAD').encode(),1),
                                  raw.replace(body[-17:],b'unterminatedtext!',1)]:
                    with self.subTest(name=name,order=order),self.assertRaises(ValueError):evidence.decode_archive(malformed)
        with self.assertRaisesRegex(ValueError,'known archive symbol table'):evidence.decode_archive(bsd_archive(payloads,'__.SYMDEF_BAD')[0])
        raw,body=bsd_archive(payloads)
        with self.assertRaisesRegex(ValueError,'inline name padding'):evidence.decode_archive(raw[:78]+b'X'+raw[79:])
        self.assertEqual(evidence.decode_archive(raw).bsd_indexes['__.SYMDEF'],body)

    def test_git_root_commands_preserve_independent_schedule(self):
        import evidence
        from pathlib import PurePosixPath, PureWindowsPath
        for system,P,root,out in [('Windows',PureWindowsPath,'C:/repo','C:/capture'),('Linux',PurePosixPath,'/repo','/capture'),('Darwin',PurePosixPath,'/repo','/capture')]:
            context={'system':system,'root':root,'out':out,'tools':{name:str(P(root)/'tools'/name) for name in ['python','git','rustup']}}
            rows=evidence.command_schedule(context,[],'mmd-win64-sse',[],replay=True)
            self.assertEqual(len(rows),87)
            for label,argv,cwd,data,outputs,compile in rows:
                self.assertEqual(cwd,str(P(root) if label in {'git-attributes','git-transport'} else P(root)/'rust'))
                if label=='git-attributes':self.assertEqual((argv[1:],data),(['check-attr','--stdin','text','eol'],'attributes'))
                if label=='git-transport':self.assertEqual((argv[1:],data),(['ls-files','--eol'],None))


def load_tests(loader, tests, pattern):
    from test_evidence import AdmissionControls, IncludeControls, PlatformControls, ArchiveIndexControls
    tests.addTests(loader.loadTestsFromTestCase(AdmissionControls))
    tests.addTests(loader.loadTestsFromTestCase(IncludeControls))
    tests.addTests(loader.loadTestsFromTestCase(PlatformControls))
    tests.addTests(loader.loadTestsFromTestCase(ArchiveIndexControls))
    return tests


if __name__=='__main__':
    unittest.main()
