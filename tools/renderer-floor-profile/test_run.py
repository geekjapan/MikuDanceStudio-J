#!/usr/bin/env python3
import copy
from contextlib import ExitStack
import ast
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import struct
import string
import subprocess
import sys
import tarfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('profile',Path(__file__).with_name('run.py'))
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

HR=('GetDeclaration','GetVertexBuffer','VertexBufferGetDesc','GetIndexBuffer','IndexBufferGetDesc','LockVertexBuffer','UnlockVertexBuffer','LockIndexBuffer','UnlockIndexBuffer','LockAttributeBuffer','UnlockAttributeBuffer','GetAttributeTableSize')

def geometry(stage):
    return {'stage':stage,'positions':[[0,0,0],[r.word(1.),0,0],[0,r.word(1.),0]],'indices':[0,1,2],'attributes':[0],'table':[], 'material_count':1}


def packet(language,observed=True):
    rows=[{'stage':'begin','language':language}]
    current_case=None
    def fp(point):rows.append({'stage':'fp','point':point,'case':current_case,'mxcsr':8064})
    def hr(name):rows.append({'stage':'hr','operation':name,'value':0})
    def mesh(stage):
        for name in HR:hr(name)
        row=geometry(stage);row.pop('material_count');row.update(bounds=[3,1,12,0,36,6,2],initialized=['position'],unknown=['uv','padding','other-declaration-channels']);rows.append(row)
    if language=='native':
        rows.append({'stage':'cpu','vendor':[0]*3,'identity':0,'brand':[0]*12,'features':[0]*3})
        fp('device-before');hr('CreateDevice');fp('device-after')
        rows.append({'stage':'dll','path':'C:\\diagnostic.dll','size':1,'sha256':'0'*64,'base':4096,'rvas':[1,2,3],'import_target':4097})
    for id,_,_ in r.CASES:
        current_case=id
        rows.append({'stage':'case','id':id,'mxcsr':8064})
        if language=='native':
            fp('independent-before');hr('D3DXLoadMeshFromXW');fp('independent-after');mesh('independent-raw')
            rows.append({'stage':'independent-material-raw','material_count':1});fp('loader-before')
            if observed:fp('production-raw-before');mesh('production-raw');fp('production-raw-after')
            fp('loader-after');rows.append({'stage':'loader','success':True});mesh('before-observation')
            if observed:mesh('observation')
            mesh('final-adjusted');rows.append({'stage':'final-material-adjusted','material_count':1})
        else:
            if observed:
                rows.extend([{'stage':'parsed','kind':'Mesh','name':'Synthetic','path':[0],'values':[['int',3]]+[['float',v] for p in geometry('')['positions'] for v in p]}, {'stage':'parsed-end'}])
                row=geometry('premerge');row.pop('table');row.update(ordinal=0,matrix=list(map(r.word,r.IDENTITY)));rows.extend([row,{'stage':'premerge-end'},geometry('merged-raw')])
            row=geometry('final-adjusted');row.update(mxcsr=8064,id=id);rows.append(row)
    for m in range(3):
        for p in range(5):
            for op in (('TransformCoord','Transform') if language=='native' else ('TransformCoord',)):
                rows.append({'stage':'direct','operation':op,'matrix':m,'point':p,'words':[r.word(1.)]*3+([r.word(3. if m==2 else 1.)] if op=='Transform' else []),'sample_a':8064,'sample_b':8064})
                if m==2 and op=='TransformCoord':rows[-1]['words']=[r.word(1./3)]*3
    if language=='rust' and observed:rows.append({'stage':'runtime-imports','phase':'pre'})
    rows.append(dict(stage='runtime-read',words=r.corpus_words(r.operation_corpus()),**({'pointer':4096} if language=='rust' else {})))
    def op(kind,owner,input,output):
        row={'stage':'operation','kind':kind,'owner':owner,'input':input,'output':output,
             'samples':[8064,8064],'sites':[8200,8201] if kind=='DllCall' else [8200,8201,8202,8203,8204],'base':8192}
        if kind=='DllCall':row['target']=4098
        else:
            row.update(values=[r.word(1. if owner[1]==0 else 3.),0x3f7ff000 if owner[1]==0 else 0x3eaaa000,0x3f7fffff if owner[1]==0 else 0x3eaaaaaa],
                       destination=output[:] if owner[0]==2 else [0,0,0])
            if kind=='RustEndpoint':row['values']=[0]*3;row['sites']=[8200,0,8202,0,0]
        if language=='rust':
            raw=r.operation_corpus() if owner[0]==1 else r.inputs(lambda p:(r.ROOT/p).read_bytes())[1]['bytes']
            rows.append(witness_record(row,raw,r.WITNESS_ROLES[2 if owner[0]==2 else 1 if kind=='HardwareSeedWithFrozenRefinement' else 0],owner[1] if owner[0]==1 else 0,4096 if owner[0]==1 else 6144))
        rows.append(row)
    corpus=r.corpus_words(r.operation_corpus())
    for i in range(2):
        output=[0x3f7fffff,0x3f7fffff,0xbf7fffff] if i==0 else [0x3eaaaaaa,0x3eaaaaaa,0xbeaaaaaa]
        for kind in (('DllCall',) if language=='native' else (('RustTable' if observed else 'RustEndpoint'),'HardwareSeedWithFrozenRefinement')):
            op(kind,[1,i,0,0],corpus[i*19:(i+1)*19],output)
    if language=='rust':
        rows.append({'stage':'merge-read','bytes':list(r.inputs(lambda p:(r.ROOT/p).read_bytes())[1]['bytes']),'pointer':6144})
        if observed:rows.append(lineage())
        op('RustTable' if observed else 'RustEndpoint',[2,0,0,0],list(map(r.word,r.POINTS[0]+r.IDENTITY)) if observed else [0]*19,[0]*3)
        if observed:rows.append({'stage':'runtime-imports','phase':'post'})
    rows.append({'stage':'end','status':0})
    return rows


def witness_record(op,raw,role,ordinal,pointer):
    return {'stage':'witness','schema':2,'layout':r.witness_layout(),'role':role,'owner':op['owner'][:],'ordinal':ordinal,
            'received_ordinal':ordinal,'handoff_ordinal':ordinal,'handoff_kind':r.WITNESS_ROLES.index(role),
            'handoff_sites':[op['base']+0x1021,op['base']+0x1027],'handoff':[pointer,len(raw),16384],'received':[pointer,len(raw),16384],
            'bytes':list(raw),'sites':[op['base']+0x1001,op['base']+0x1002,op['base']+0x1007],'base':op['base']}


def wire(rows):return ('\n'.join('FP '+json.dumps(row) for row in rows)+'\n').encode()


def lineage():
    return {'stage':'merge-lineage','caller':[8192+0x1001,8192+0x1007],'rows':[[8,0,0,32,48,64,1,4,32,8192+0x1001],
        [64,1,4,64,48,64,2,4,32,8192+0x1001]],'returned':[64,2,4,64,8192+0x1001,0]}



def fixture_names(label):
    raw=(r.ROOT/('rust/crates/mds-accessory/tests/'+label+'.rs')).read_bytes()
    expected={'mesh_dump':'cf96765ec013b75ad16dd405214417ba7a54a4b3b3c10582f861ac57e6fcc8bb',
              'x_files':'9aec8203be9fa490d6439e68a5d875fce9c0e284c42178090b929ddd1ad769b8'}
    r.require(r.digest(raw)==expected[label],'frozen product fixture test source')
    return r.re.findall(r'#\[test\]\nfn ([a-z_0-9]+)\(',raw.decode())


def fixture_output(label):
    names=fixture_names(label);count=len(names)
    return ('\nrunning '+str(count)+(' test\n' if count==1 else ' tests\n')+
            ''.join('test '+name+' ... ok\n' for name in names)+
            f'\ntest result: ok. {count} passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s\n\n').encode()


def tar_bytes(entries):
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w') as archive:
        for name,kind,mode,value in entries:
            info=tarfile.TarInfo(name);info.mode=mode;info.type=kind;info.size=len(value)
            archive.addfile(info,io.BytesIO(value) if kind==tarfile.REGTYPE else None)
    return raw.getvalue()


def native_log(body,recipe,project='floor_profile',number='1'):
    root=r.PureWindowsPath(recipe['native_target']);parent=root/'floor_profile.vcxproj';owner=root/(project+'.vcxproj')
    lines=["Change Dir: '"+root.as_posix()+"'",'',
           'Run Build Command(s): "C:/VS/MSBuild.exe" floor_profile.vcxproj /p:Configuration=Release /p:Platform=x64 /p:VisualStudioVersion=17.0 /m:1 /v:n',
           '     1>Project "'+str(parent)+'" on node 1 (default targets).']
    if owner!=parent:lines.append('     1>Project "'+str(parent)+'" (1) is building "'+str(owner)+'" ('+number+') on node 1 (default targets).')
    prefix=('\n'.join(lines)+'\n').encode()
    suffix=('     '+number+'>Done Building Project "'+str(owner)+'" (default targets).\n').encode()
    if owner!=parent:suffix+=('     1>Done Building Project "'+str(parent)+'" (default targets).\n').encode()
    return prefix+body+suffix+b'Build succeeded.\n'


def code_fixture():
    raw=bytearray(2048);raw[:2]=b'MZ';struct.pack_into('<I',raw,60,128)
    raw[128:134]=b'PE\0\0d\x86';struct.pack_into('<H',raw,134,2);struct.pack_into('<H',raw,148,240)
    optional=152;struct.pack_into('<H',raw,optional,0x20b);struct.pack_into('<Q',raw,optional+24,0x140000000)
    struct.pack_into('<II',raw,optional+136,0x2000,24)
    for i,(name,va,size,offset,flags) in enumerate([(b'.text',0x1000,256,1024,0x60000020),(b'.pdata',0x2000,24,1280,0x40000040)]):
        at=392+i*40;raw[at:at+len(name)]=name;struct.pack_into('<IIII',raw,at+8,size,va,size,offset);struct.pack_into('<I',raw,at+36,flags)
    struct.pack_into('<III',raw,1280,0x1000,0x1008,0x3000);raw[1024:1032]=b'\x90'*7+b'\xc3'
    struct.pack_into('<III',raw,1292,0x1020,0x1028,0x3000);raw[1056:1064]=b'\xe8\xdb\xff\xff\xff\x90\x90\xc3'
    mapping=b' Preferred load address is 0000000140000000\n 0001:00000000 mds_accessory_transform_coord 0000000140001000 f object.obj\n'
    rows=[{'owner':[1,0,0,0],'base':8192,'sites':[8192+0x1001,0,8192+0x1007,0,0]}]
    mapping+=b' 0001:00000000 floor_profile_direct_witness 0000000140001000 f object.obj\n 0001:00000020 floor_profile_handoff 0000000140001020 f object.obj\n'
    rows[0]['witness']=dict(witness_record(rows[0],r.operation_corpus(),r.WITNESS_ROLES[0],0,4096),raw_sha256=r.digest(r.operation_corpus()),compiled_dataflow='UnprovedAwaitingIndependentReview')
    assembly=('\n'.join(f'14000100{i}:  {v:02x}  '+('ret' if i==7 else 'nop') for i,v in enumerate(raw[1024:1032]))+'\n').encode()
    return bytes(raw),mapping,rows,assembly


def instructions(span):
    raw=bytes.fromhex(span['bytes']);lines=[];i=0
    while i<len(raw):
        address=0x140000000+span['start_rva']+i
        if raw[i]==0xe8:
            encoded=raw[i:i+5];text='callq '+hex(address+5+struct.unpack_from('<i',encoded,1)[0]);i+=5
        else:
            encoded=raw[i:i+1];text='ret' if raw[i]==0xc3 else 'nop';i+=1
        lines.append(f'{address:x}: '+encoded.hex(' ')+' '+text+'\n')
    return ''.join(lines).encode()


def runtime_fixture():
    raw=bytearray(code_fixture()[0])+bytearray(2048)
    struct.pack_into('<H',raw,134,3);struct.pack_into('<II',raw,152+56,0x5000,1024)
    struct.pack_into('<I',raw,152+108,16);struct.pack_into('<II',raw,152+120,0x3000,40)
    at=472;raw[at:at+8]=b'.idata\0\0';struct.pack_into('<IIII',raw,at+8,256,0x3000,256,1536)
    struct.pack_into('<I',raw,at+36,0x40000040)
    struct.pack_into('<IIIII',raw,1536,0x3040,0,0,0x3080,0x3060)
    struct.pack_into('<Q',raw,1536+64,0x30a0);raw[1536+128:1536+140]=b'example.dll\0'
    raw[1536+160:1536+169]=b'\0\0memcpy\0'
    struct.pack_into('<II',raw,152+112,0x30b0,80)
    struct.pack_into('<IIIII',raw,1536+176+20,2,1,0x30d8,0x30e0,0x30e8)
    struct.pack_into('<II',raw,1536+216,0x1000,0x1008);struct.pack_into('<I',raw,1536+224,0x30f0)
    struct.pack_into('<H',raw,1536+232,0);raw[1536+240:1536+247]=b'memcpy\0'
    raw=bytes(raw);base=0x140000000;directory=Path('/synthetic-runtime');files={};snapshots=[]
    for phase in ('pre','post'):
        prefix=f'runtime-{phase}-0'
        files[directory/(prefix+'-module.bin')]=raw;files[directory/(prefix+'-headers.bin')]=raw[:1024]
        files[directory/(prefix+'-iat.bin')]=struct.pack('<Q',base+0x1000)
        sections=[]
        for i,s in enumerate(r.pe_code(raw)[1]):
            files[directory/(prefix+f'-section-{i}.bin')]=raw[s['offset']:s['offset']+s['size']]
            sections.append([i,s['rva'],s['size'],s['flags']])
        slots=[{'descriptor_rva':0x3000,'dll_rva':0x3080,'name_rva':0x30a0,'slot_rva':0x3060,
                'target_va':base+0x1000,'owner_base':base,'owner_size':0x5000,'path_utf16':list(map(ord,'C:\\example.dll')),'sections':sections}]
        snapshots.append({'stage':'runtime-imports','phase':phase,'process_id':123,'image_base':8192,'image_size':0x5000,'slots':slots})
    return raw,directory,files,{'runtime_imports':snapshots,'operations':[{'base':8192}]}


class Controls(unittest.TestCase):
    def test_01_fixed_inputs_and_wrapper_inverse(self):
        rows=r.inputs(lambda p:(r.ROOT/p).read_bytes())
        self.assertEqual([v['id'] for v in rows],[v[0] for v in r.CASES])
        floor=rows[0]['bytes'];self.assertEqual(len(floor),451)
        for row in rows[1:3]:
            prefix,suffix=bytes.fromhex(row['prefix']),bytes.fromhex(row['suffix'])
            self.assertEqual(row['bytes'][:16]+row['bytes'][16+len(prefix):-len(suffix)],floor)
        with self.assertRaises(ValueError):r.inputs(lambda p:b'bad' if p==r.FLOOR else (r.ROOT/p).read_bytes())
    def test_02_generated_copy_full_inverse(self):
        for observed in (False,True):
            generated,patches=r.generated(lambda p:(r.ROOT/p).read_bytes(),observed,Path('C:/fixed/inputs'))
            self.assertEqual(set(generated),{'CMakeLists.txt',r.MESH,'native.cpp','native_observer.hpp'}|({r.ACCESSORY} if observed else set()))
            for path,rows in patches.items():
                raw=generated[path]
                for row in reversed(rows):raw=r.inverse(raw,row)
                self.assertEqual(raw,(r.ROOT/path).read_bytes())
            original=(r.ROOT/r.MESH).read_bytes()
            transform=original[original.index(b'fn transform_coord('):original.index(b'/// `D3DXVec3TransformNormal`')]
            if not observed:self.assertIn(transform,generated[r.MESH])
            else:
                for expression in (b'let w = ((x * m[3] + y * m[7]) + z * m[11]) + m[15];',b'let e = rcp_estimate(w);',b'let r = (e + e) - w * (e * e);'):
                    self.assertEqual(generated[r.MESH].count(expression),1)
            self.assertNotIn(b'@',generated['native.cpp'])
            self.assertNotIn(b'@CASES@',generated[r.MESH])
            self.assertIn(b'#[cfg(mds_floor_profile)]\nmod floor_profile',generated[r.MESH])
            for literal in r.re.findall(r'(?:format!|println!)\("((?:\\.|[^"\\])*)"', (r.HERE/'observer.rs').read_text()):
                list(string.Formatter().parse(json.loads('"'+literal+'"')))
    def test_03_inverse_rejects_drift_and_duplicate_anchor(self):
        raw,p=r.insert(b'abc',b'b',b'added')
        with self.assertRaises(ValueError):r.inverse(raw+b'x',p)
        with self.assertRaises(ValueError):r.insert(b'aaa',b'a',b'x')
    def test_04_complete_synthetic_streams(self):
        for language in ('native','rust'):
            for observed in (False,True):
                parsed=r.parse(wire(packet(language,observed)),language,observed)
                self.assertEqual(list(parsed['cases']),[row[0] for row in r.CASES])
    def test_05_packet_rejections(self):
        mutations={
            'missing-case':lambda p:p.pop(next(i for i,v in enumerate(p) if v['stage']=='case')),
            'extra-case':lambda p:p.insert(-1,{'stage':'case','id':'extra'}),
            'duplicate-stage':lambda p:p.insert(next(i for i,v in enumerate(p) if v['stage']=='case'),{'stage':'case','id':'floor-top'}),
            'unknown-case':lambda p:next(v for v in p if v['stage']=='case').update(id='unknown'),
            'wrong-order':lambda p:next(v for v in p if v['stage']=='case').update(id='floor-identity'),
            'unknown-stage':lambda p:p.insert(-1,{'stage':'unknown'}),
            'wrong-operation':lambda p:next(v for v in p if v['stage']=='direct').update(operation='Transform'),
            'wrong-matrix':lambda p:next(v for v in p if v['stage']=='direct').update(matrix=2),
            'wrong-point':lambda p:next(v for v in p if v['stage']=='direct').update(point=4),
            'bad-bounds':lambda p:next(v for v in p if 'indices' in v)['indices'].__setitem__(0,999),
            'missing-terminal':lambda p:p.pop(),
            'failed-terminal':lambda p:p[-1].update(status=1),
            'nonfinite':lambda p:next(v for v in p if v['stage']=='direct')['words'].__setitem__(0,0x7f800000),
        }
        for language in ('native','rust'):
            for name,mutation in mutations.items():
                with self.subTest(language=language,control=name):
                    p=packet(language);mutation(p)
                    with self.assertRaises((ValueError,KeyError,IndexError)):r.parse(wire(p),language,True)
        for name,mutation in {
            'unknown-channel':lambda p:next(v for v in p if 'initialized' in v)['initialized'].append('uv'),
            'missing-hr':lambda p:p.pop(next(i for i,v in enumerate(p) if v['stage']=='hr')),
            'failed-hr':lambda p:next(v for v in p if v['stage']=='hr').update(value=0x80004005),
            'wrong-lock-bounds':lambda p:next(v for v in p if 'bounds' in v)['bounds'].__setitem__(4,999),
            'unbound-import':lambda p:next(v for v in p if v['stage']=='dll').update(import_target=55),
            'raw-adjusted-exchange':lambda p:next(v for v in p if v['stage']=='independent-material-raw').update(stage='final-material-adjusted'),
        }.items():
            with self.subTest(control=name):
                p=packet('native');mutation(p)
                with self.assertRaises((ValueError,KeyError,IndexError)):r.parse(wire(p),'native',True)
        for name,mutation in {
            'missing-merge':lambda p:p.pop(next(i for i,v in enumerate(p) if v['stage']=='merged-raw')),
            'container-order':lambda p:next(v for v in p if v['stage']=='premerge').update(ordinal=1),
            'matrix-width':lambda p:next(v for v in p if v['stage']=='premerge')['matrix'].pop(),
            'material-stage-exchange':lambda p:next(v for v in p if v['stage']=='merged-raw').update(stage='final-adjusted'),
        }.items():
            with self.subTest(control=name):
                p=packet('rust');mutation(p)
                with self.assertRaises((ValueError,KeyError,IndexError)):r.parse(wire(p),'rust',True)
    def test_06_finite_semantic_change_is_valid(self):
        before=packet('rust');after=copy.deepcopy(before)
        next(v for v in after if v['stage']=='direct')['words'][0]=r.word(.5)
        a,b=[r.parse(wire(p),'rust',True) for p in (before,after)]
        self.assertEqual(r.semantic(a,b)['classification'],'SemanticDifference')
        self.assertEqual(r.semantic(a,a)['classification'],'Equal')
    def test_07_legitimate_empty_table_and_material_stage(self):
        row=geometry('merged-raw');r.mesh(row)
        row['material_count']=0
        with self.assertRaises(ValueError):r.mesh(row)
    def test_08_hardened_archive_controls_in_memory(self):
        opener=tarfile.open
        def inspect(raw):
            with patch.object(r.c.tarfile,'open',lambda *a,**kw:opener(fileobj=io.BytesIO(raw),mode='r:')):
                return r.c.safe_tar('in-memory.tar')
        self.assertEqual(set(inspect(tar_bytes([('seal.json',tarfile.REGTYPE,0o644,b'{}')]))),{'seal.json'})
        for entries in [
            [('a',tarfile.REGTYPE,0o666,b'x')],
            [('../a',tarfile.REGTYPE,0o644,b'x')],
            [('/a',tarfile.REGTYPE,0o644,b'x')],
            [('a',tarfile.SYMTYPE,0o644,b'')],
            [('a',tarfile.CHRTYPE,0o644,b'')],
            [('a',tarfile.REGTYPE,0o644,b'x')]*2,
            [('a',tarfile.REGTYPE,0o644,b'x'),('a/b',tarfile.REGTYPE,0o644,b'x')],
        ]:
            with self.assertRaises(ValueError):inspect(tar_bytes(entries))
        with self.assertRaises(tarfile.TarError):inspect(b'corrupt')
    def test_09_missing_and_wrong_generation_replay(self):
        with self.assertRaises(OSError):r.replay(Path('/nonexistent-floor-profile-generation'))
        with patch.object(r,'load_json',return_value={'schema':'old-generation','files':{}}),patch.object(Path,'read_bytes',return_value=b'{}'):
            with self.assertRaises(ValueError):r.replay(Path('/nonexistent-floor-profile-generation'))
    def test_10_receipt_rejections_resealed_inner_controls(self):
        receipt={'argv':['fixed'],'cwd':'fixed','env':{},'start_ns':1,'end_ns':2,'start_utc':'start','end_utc':'end','status':0,'terminal':'exit'}
        for suffix in ('stdout','stderr'):receipt[suffix]={'name':'x.'+suffix,'size':0,'sha256':r.digest(b'')}
        def read(path):return json.dumps(receipt).encode() if path.suffix=='.json' else b''
        with patch.object(Path,'read_bytes',read):
            r.checked(Path('/in-memory'),'x')
            for key,value in [('status',1),('terminal','timeout'),('terminal','launch_failure')]:
                mutated=copy.deepcopy(receipt);mutated[key]=value
                with patch.object(r.c.h,'load_json',return_value=mutated):
                    with self.assertRaises(ValueError):r.checked(Path('/in-memory'),'x')
    def test_11_every_fp_site_is_strict(self):
        for language in ('native','rust'):
            base=packet(language)
            sites=[(i,key) for i,row in enumerate(base) for key in ('mxcsr','sample_a','sample_b') if key in row and (language=='rust' or row['stage']!='case')]
            for index,key in sites:
                for bad in (-1,65536,True,1.5,'8064',None):
                    with self.subTest(language=language,site=index,key=key,bad=bad):
                        rows=copy.deepcopy(base)
                        if bad is None:rows[index].pop(key)
                        else:rows[index][key]=bad
                        with self.assertRaises((ValueError,KeyError)):r.parse(wire(rows),language,True)
                rows=copy.deepcopy(base);row=rows[index]
                if row['stage']=='direct':row['point']=99
                elif row['stage']=='fp':row['point']='wrong-site'
                elif row['stage']=='case':row['id']='wrong-site'
                else:row['id']='wrong-site'
                with self.assertRaises(ValueError):r.parse(wire(rows),language,True)
        rows=packet('native');next(row for row in rows if row['stage']=='fp' and row['case'])['case']='frames'
        with self.assertRaises(ValueError):r.parse(wire(rows),'native',True)

    def test_12_fp_qualification_preserves_differences_and_held_causes(self):
        def classified(native=8064,rust=8064,device=8064):
            n=packet('native');p=packet('rust')
            next(row for row in p if row['stage']=='direct')['words'][0]=r.word(.5)
            for rows,value in ((n,native),(p,rust)):
                for row in rows:
                    for key in ('mxcsr','sample_a','sample_b'):
                        if key in row:row[key]=value
            next(row for row in n if row['stage']=='fp')['mxcsr']=device
            return r.classify(r.parse(wire(n),'native',True),r.parse(wire(p),'rust',True))
        baseline=classified()
        for n,p,status in [(8065,8064,'SampledDefaultControlsAgree'),(8064,8064,'SampledDefaultControlsAgree'),(0x9f80,0x9f80,'ObservedNondefaultControls'),(8064,0x9f80,'ObservedControlMismatch')]:
            result=classified(n,p)
            self.assertEqual(result['differences'],baseline['differences'])
            self.assertTrue(result['differences'])
            self.assertTrue(all(q['sampled_controls']==status and q['operation_environment']=='Unproved' for q in result['causal_qualification']))
            causes=[f for f in result['findings'] if 'cause_status' in f]
            self.assertTrue(causes)
            self.assertTrue(all(f['cause_status']=='Held' and f['reason']=='OperationEnvironmentUnproved' for f in causes))
        device=classified(device=0x9f80)
        self.assertEqual(device['causal_qualification'],baseline['causal_qualification'])
        self.assertNotEqual(device['fp_states'],baseline['fp_states'])

    def test_13_direct_merged_actual_correspondence(self):
        n=r.parse(wire(packet('native')),'native',True);rows=packet('rust')
        points=[list(map(r.word,p)) for p in r.POINTS[:4]]
        pre=next(row for row in rows if row['stage']=='premerge');pre['positions']=points
        merged=next(row for row in rows if row['stage']=='merged-raw');merged['positions']=copy.deepcopy(points)
        result=r.classify(n,r.parse(wire(rows),'rust',True));relation=result['output_relations'][0]
        self.assertEqual(relation['classification'],'SemanticDifference')
        for matrix in (r.AFFINE,[7.]*16):
            pre['matrix']=list(map(r.word,matrix))
            result=r.classify(n,r.parse(wire(rows),'rust',True))
            self.assertEqual(result['output_relations'][0]['classification'],'SemanticDifference' if matrix==r.AFFINE else 'NotComparable')
        pre['matrix']=list(map(r.word,r.IDENTITY))
        for row in rows:
            if row['stage']=='direct' and row['matrix']==0 and row['point']<4:row['words']=points[row['point']]
        self.assertEqual(r.classify(n,r.parse(wire(rows),'rust',True))['output_relations'][0]['classification'],'Equal')
        pre['positions'].reverse()
        result=r.classify(n,r.parse(wire(rows),'rust',True))
        self.assertEqual(result['output_relations'][0]['classification'],'NotComparable')

    def test_14_independent_material_domains(self):
        for language,stages in [('native',('independent-raw','production-raw','before-observation','observation','final-adjusted')),('rust',('premerge','merged-raw','final-adjusted'))]:
            for stage in stages:
                rows=packet(language);next(row for row in rows if row['stage']==stage)['attributes']=[999]
                with self.assertRaises(ValueError):r.parse(wire(rows),language,True)
        rows=packet('native')
        next(row for row in rows if row['stage']=='independent-material-raw')['material_count']=2
        next(row for row in rows if row['stage']=='independent-raw')['attributes']=[1]
        r.parse(wire(rows),'native',True)
        next(row for row in rows if row['stage']=='final-adjusted')['attributes']=[1]
        with self.assertRaises(ValueError):r.parse(wire(rows),'native',True)
        row=geometry('premerge');row['material_count']=0;r.mesh(row)
        row['attributes']=[1]
        with self.assertRaises(ValueError):r.mesh(row)
        row=geometry('final-adjusted');row['table']=[[999,0,1,0,3]]
        with self.assertRaises(ValueError):r.mesh(row)
        for path in ('observer.rs','native.cpp.in'):
            source=(r.HERE/path).read_text()
            self.assertNotIn('Words(m+i,17)',source);self.assertNotIn('m.ambient',source)

    def test_15_coordinated_recipe_and_receipt_controls(self):
        recipe=r.recipe('C:/runner/temp','observed','O2')
        manifest={'runner_temp':'C:/runner/temp','input_root':recipe['input_root']}
        build={key:copy.deepcopy(recipe[key]) for key in ('id','source','target','evidence','commands')}
        build.update(variant='observed',optimization='O2')
        r.admit_recipe(manifest,build)
        for key in ('source','target','evidence'):
            bad=copy.deepcopy(build);bad[key]='C:\\wrong'
            with self.assertRaises(ValueError):r.admit_recipe(manifest,bad)
        for label in recipe['commands']:
            receipt={'argv':copy.deepcopy(recipe['commands'][label]),'cwd':recipe['cwd'][label],
                     'env':{'CARGO_TARGET_DIR':recipe['target'],'CARGO_INCREMENTAL':'0','RUSTFLAGS':r.RUST_FLAGS,'CL':'','_CL_':''}}
            r.admit_command(receipt,recipe,label)
            for key in ('argv','cwd'):
                bad=copy.deepcopy(receipt);bad[key]=['wrong.exe'] if key=='argv' else 'C:\\wrong'
                resealed=copy.deepcopy(build)
                if key=='argv':resealed['commands'][label]=bad[key]
                with self.assertRaises(ValueError):r.admit_command(bad,recipe,label)
                if key=='argv':
                    with self.assertRaises(ValueError):r.admit_recipe(manifest,resealed)
        bad=copy.deepcopy(manifest);bad['input_root']='C:\\wrong'
        with self.assertRaises(ValueError):r.admit_recipe(bad,build)
        for value in ('/O1','/Od'):
            receipt['env']['_CL_']=value
            with self.assertRaises(ValueError):r.admit_command(receipt,recipe,label)

    def test_16_cargo_json_is_readmitted(self):
        recipe=r.recipe('C:/runner/temp','observed','O2');source=r.PureWindowsPath(recipe['source'])/'rust/crates/mds-accessory'
        exe=str(r.PureWindowsPath(recipe['target'])/'release/deps/mds_accessory-abcdef.exe')
        artifact={'reason':'compiler-artifact','package_id':'path+file:///'+source.as_posix()+'#0.1.0','manifest_path':str(source/'Cargo.toml'),
                  'target':{'name':'mds_accessory','src_path':str(source/'src/lib.rs'),'kind':['lib'],'crate_types':['lib'],'test':True},
                  'profile':{'opt_level':'3','debuginfo':0,'debug_assertions':False,'overflow_checks':False,'test':True},'executable':exe,'filenames':[exe]}
        def cargo(row):return b'\n'.join(json.dumps(v).encode() for v in [row,{'reason':'build-finished','success':True}])+b'\n'
        self.assertEqual(r.cargo_binary(cargo(artifact),recipe,'O2'),exe)
        for key,value in [('executable',exe.replace('release','debug')),('package_id',artifact['package_id'].replace('#0.1.0','#wrong@0.1.0')),('manifest_path','C:/wrong/Cargo.toml'),('filenames',[])]:
            bad=copy.deepcopy(artifact);bad[key]=value
            with self.assertRaises(ValueError):r.cargo_binary(cargo(bad),recipe,'O2')
        for key,value in [('src_path','C:/wrong/lib.rs'),('kind',['test']),('name','wrong')]:
            bad=copy.deepcopy(artifact);bad['target'][key]=value
            with self.assertRaises(ValueError):r.cargo_binary(cargo(bad),recipe,'O2')
        for key in artifact['profile']:
            bad=copy.deepcopy(artifact);bad['profile'][key]='wrong'
            with self.assertRaises(ValueError):r.cargo_binary(cargo(bad),recipe,'O2')
        with self.assertRaises(ValueError):r.cargo_binary(cargo(artifact)[:-1],recipe,'O2')

    def test_17_native_effective_options_objects_archive_and_link(self):
        recipe=r.recipe('C:/runner/temp','observed','Od');root=r.PureWindowsPath(recipe['native_target']);source=r.PureWindowsPath(recipe['source'])
        accessory=root/'mikudancestudio_core.dir/Release/accessory.obj';native=root/'floor_profile.dir/Release/native.obj';library=root/'Release/mikudancestudio_core.lib';exe=root/'Release/floor_profile.exe'
        commands=[['C:\\VS\\cl.exe','/c','/O2','/Od','/Fo'+str(accessory),str(source/r.ACCESSORY)],
                  ['C:\\VS\\cl.exe','/c','/O2','/Od','/Fo'+str(native),str(source/'native.cpp')],
                  ['C:\\VS\\lib.exe','/OUT:'+str(library),str(accessory)],
                  ['C:\\VS\\link.exe','/OUT:'+str(exe),str(native),str(library),'/MAP']]
        def member(raw):
            header=b'accessory.obj/'.ljust(16)+b'0'.ljust(12)+b'0'.ljust(6)+b'0'.ljust(6)+b'100644'.ljust(8)+str(len(raw)).encode().ljust(10)+b'`\n'
            return b'!<arch>\n'+header+raw+(b'\n' if len(raw)%2 else b'')
        objects={accessory.relative_to(root).as_posix():b'accessory',native.relative_to(root).as_posix():b'native'}
        archive=member(b'accessory')
        self.assertEqual(r.native_provenance(commands,recipe,'Od',objects,archive),str(exe))
        raw=native_log(('\n'.join('       '+task+':\n         '+' '.join('"'+v+'"' if ' ' in v else v for v in row) for task,row in zip(('ClCompile','ClCompile','Lib','Link'),commands))+'\n').encode(),recipe)
        self.assertEqual(r.native_commands(raw,b'',recipe),commands)
        spaced=copy.deepcopy(commands);spaced[0][0]='C:\\Program Files\\VS\\cl.exe'
        raw=native_log(('\n'.join('       '+task+':\n         '+' '.join(row) for task,row in zip(('ClCompile','ClCompile','Lib','Link'),spaced))+'\n').encode(),recipe)
        self.assertEqual(r.native_commands(raw,b'',recipe),spaced)
        for opt in ('Od','O2'):
            for index in (0,1):
                for override in ('/O1','-O1','/Ox'):
                    bad=copy.deepcopy(commands);bad[0][3]='/'+opt;bad[1][3]='/'+opt;bad[index].append(override)
                    with self.assertRaises(ValueError):r.native_provenance(bad,recipe,opt,objects,archive)
        for index,key,value in [(0,4,'/FoUNRELATED.obj'),(1,4,'/FoOTHER.obj'),(0,5,str(source/'wrong.cpp')),(2,2,str(native)),(3,2,'WRONG.obj'),(3,3,'wrong.lib'),(3,1,'/OUT:wrong.exe')]:
            bad=copy.deepcopy(commands);bad[index][key]=value
            with self.assertRaises(ValueError):r.native_provenance(bad,recipe,'Od',objects,archive)
        lines=[]
        for task,row in zip(('ClCompile','ClCompile','Lib','Link'),commands):
            lines.extend(['       '+task+':','         '+' '.join('"'+v+'"' for v in row[:-1]),'         "'+row[-1]+'"','       FinalizeBuildStatus:'])
        multiline=native_log(('\n'.join(lines)+'\n').encode(),recipe)
        def admitted(raw,stderr=b''):
            receipt={'argv':recipe['commands']['native-build'],'cwd':recipe['cwd']['native-build'],'env':{'CARGO_TARGET_DIR':recipe['target'],'CARGO_INCREMENTAL':'0','RUSTFLAGS':r.RUST_FLAGS,'CL':'','_CL_':''},'status':0,'terminal':'exit','start_ns':1,'end_ns':2,'start_utc':'start','end_utc':'end'}
            for suffix,value in [('stdout',raw),('stderr',stderr)]:receipt[suffix]={'name':'native-build.'+suffix,'sha256':r.digest(value),'size':len(value)}
            files={'.json':json.dumps(receipt).encode(),'.stdout':raw,'.stderr':stderr}
            with patch.object(Path,'read_bytes',lambda path:files[path.suffix]):
                checked,stdout,stderr=r.checked(Path('/resealed'),'native-build')
            r.admit_command(checked,recipe,'native-build')
            return r.native_provenance(r.native_commands(stdout,stderr,recipe),recipe,'Od',objects,archive)
        self.assertEqual(admitted(multiline),str(exe))
        for separator in (b'       ClCompile:\n',b'     1>ClCompile:\n',b'\n',('     1>'+str(source/r.ACCESSORY)+"(1,2): warning C4018: '<': signed/unsigned mismatch ["+str(root/'floor_profile.vcxproj')+']\n').encode()):
            for override in (b'/O1',b'-O1',b'/Ox'):
                raw=multiline.replace(b'       FinalizeBuildStatus:',separator+b'         '+override+b'\n       FinalizeBuildStatus:',1)
                self.assertEqual(r.native_commands(raw,b'',recipe)[0][-1],override.decode())
                with self.assertRaisesRegex(ValueError,'effective ordered optimization'):admitted(raw)
        self.assertEqual(admitted(multiline,b' \r\n\t'),str(exe))
        for forged in (b'       FinalizeBuildStatus:\n',b'         /O1\n',b'         /OUT:wrong.exe\n',multiline,multiline[multiline.index(b'       FinalizeBuildStatus:'):]):
            with self.assertRaisesRegex(ValueError,'unordered native stderr'):admitted(multiline,forged)
        for separator in (b'\n',b'\n\n',b'         unrecognized diagnostic\n'):
            with self.subTest(separator=separator),self.assertRaises(ValueError):
                admitted(multiline.replace(b'       FinalizeBuildStatus:',separator+b'         /O1\n       FinalizeBuildStatus:',1))
        for stderr in (b'',b'\n\n',b'         diagnostic\n         /O1\n'):
            with self.subTest(stderr=stderr),self.assertRaises(ValueError):
                admitted(multiline[:multiline.index(b'       FinalizeBuildStatus:')],stderr)
        for old,new in [(str(accessory).encode(),b'wrong.obj'),(str(native).encode(),b'wrong.obj'),(str(library).encode(),b'wrong.lib'),(str(exe).encode(),b'wrong.exe'),(str(source/r.ACCESSORY).encode(),b'wrong.cpp')]:
            with self.subTest(member=old),self.assertRaises(ValueError):admitted(multiline.replace(old,new))
        with self.assertRaises(ValueError):admitted(multiline.replace(('         "'+str(accessory)+'"\n').encode(),b''))
        with self.assertRaises(ValueError):admitted(multiline.replace(b'       FinalizeBuildStatus:',b'         /O1\n       FinalizeBuildStatus:',1))
        with self.assertRaises(ValueError):r.native_provenance(commands,recipe,'Od',objects,member(b'unrelated'))
        with self.assertRaises(ValueError):r.native_provenance(commands,recipe,'Od',{},archive)
        with self.assertRaises(ValueError):r.command_words('cl.exe @hidden.rsp')

    def test_20_compact_cargo_identity_and_escaping(self):
        recipe=r.recipe('C:/runner/temp','observed','Od');source=r.PureWindowsPath(recipe['source'])/'rust/crates/mds-accessory'
        exe=str(r.PureWindowsPath(recipe['target'])/'debug/deps/mds_accessory-abc.exe')
        package='path+file:///'+source.as_posix()+'#0.1.0'
        row={'reason':'compiler-artifact','package_id':package,'manifest_path':str(source/'Cargo.toml'),
             'target':{'name':'mds_accessory','src_path':str(source/'src/lib.rs'),'kind':['lib'],'crate_types':['lib'],'test':True},
             'profile':{'opt_level':'0','debuginfo':2,'debug_assertions':True,'overflow_checks':True,'test':True},'executable':exe,'filenames':[exe]}
        def cargo():return (json.dumps(row)+'\n'+json.dumps({'reason':'build-finished','success':True})+'\n').encode()
        self.assertEqual(r.cargo_binary(cargo(),recipe,'Od'),exe)
        for bad in (package.replace('mds-accessory#','other#'),package.replace('/rust/','/other/'),package.replace('#0.1.0','#0.2.0'),package+'#extra',package.replace('#0.1.0','#mds-accessory@0.1.0'),package.replace('/rust/','/%72ust/'),package.replace('/rust/','%2Frust/'),package.replace('/rust/','/%252e%252e/rust/'),package.replace('/rust/','/../rust/'),package.replace('/rust/','/%ZZ/rust/')):
            row['package_id']=bad
            with self.subTest(package=bad),self.assertRaises(ValueError):r.cargo_binary(cargo(),recipe,'Od')
        row['package_id']=package;row['profile']['test']=False;row['executable']=None
        with self.assertRaises(ValueError):r.cargo_binary(cargo(),recipe,'Od')

    def test_21_observed_msbuild_continuations(self):
        recipe=r.recipe('C:/runner/temp','observed','Od')
        body=b'       Lib:\r\n         C:\\Program Files\\Microsoft Visual Studio\\2022\\Enterprise\\VC\\Tools\\MSVC\\14.44.35207\\bin\\HostX64\\x64\\Lib.exe /OUT:"D:\\a\\_temp\\floor-native-build\\Release\\mikudancestudio_core.lib" /NOLOGO /MACHINE:X64  /machine:x64 mikudancestudio_core.dir\\Release\\mmd_app.obj\r\n         mikudancestudio_core.dir\\Release\\globals.obj\r\n         mikudancestudio_core.dir\\Release\\accessory.obj\r\n         mikudancestudio_core.dir\\Release\\model_renderers.obj\r\n         mikudancestudio_core.dir\\Release\\late_ports.obj\r\n         mikudancestudio_core.vcxproj -> D:\\a\\_temp\\floor-native-build\\Release\\mikudancestudio_core.lib\r\n'
        raw=native_log(body,recipe,'mikudancestudio_core','6')
        command=r.native_commands(raw,b'',recipe)[0]
        self.assertEqual(r.PureWindowsPath(command[0]).name,'Lib.exe')
        self.assertEqual([r.PureWindowsPath(v).name for v in command if v.endswith('.obj')],['mmd_app.obj','globals.obj','accessory.obj','model_renderers.obj','late_ports.obj'])
        clean=native_log(body+b'       UnrelatedTask:\r\n',recipe,'mikudancestudio_core','6')
        self.assertEqual(len(r.native_commands(clean,b'',recipe)),1)
        self.assertNotIn('foreign.obj',r.native_commands(clean,b'',recipe)[0])
        with self.assertRaises(ValueError):r.native_commands(native_log(body+b'       UnrelatedTask:\r\n         foreign.obj\r\n',recipe,'mikudancestudio_core','6'),b'',recipe)
        for bad in (raw.replace(b'accessory.obj',b'wrong.obj'),raw.replace(b'         mikudancestudio_core.dir\\Release\\accessory.obj\r\n',b'')):
            self.assertNotIn('mikudancestudio_core.dir\\Release\\accessory.obj',r.native_commands(bad,b'',recipe)[0])
        for bad in (raw[:raw.index(b'         mikudancestudio_core.vcxproj')],raw.replace(b'globals.obj',b'globals.obj : diagnostic'),raw.replace(b'mikudancestudio_core.dir\\Release\\globals.obj',b'@hidden.rsp'),raw.replace(b'globals.obj',b'"globals.obj')):
            with self.assertRaises(ValueError):r.native_commands(bad,b'',recipe)
        batch=b'       ClCompile:\n         C:\\VS\\cl.exe /c /O2 /Fo"core.dir\\Release\\\\" C:\\src\\one.cpp C:\\src\\accessory.cpp\n         /Od\n       Lib:\n'
        args=r.native_commands(native_log(batch,recipe),b'',recipe)[0]
        self.assertEqual(args[-1],'/Od');self.assertEqual(r.option(args[1:],'/Fo'),'core.dir\\Release\\')
        self.assertIn('C:\\src\\accessory.cpp',args)
        emitted=b'       ClCompile:\n         C:\\VS\\cl.exe /c C:\\src\\accessory.cpp\n         accessory.cpp\n       Lib:\n'
        self.assertEqual(r.native_commands(native_log(emitted,recipe),b'',recipe)[0],['C:\\VS\\cl.exe','/c','C:\\src\\accessory.cpp'])

    def test_22_native_boundaries_and_progress_do_not_drop_options(self):
        recipe=r.recipe('C:/runner/temp','observed','Od')
        compile=b'       ClCompile:\n         C:\\VS\\cl.exe /c /O2 /Od /Foaccessory.obj C:\\src\\accessory.cpp\n'
        progress=b'         accessory.cpp\n';boundary=b'       Lib:\n'
        def log(body):return native_log(body,recipe,'mikudancestudio_core','6')
        self.assertEqual(r.native_commands(log(compile+b'         C:\\src\\other.cpp\n'+boundary),b'',recipe)[0][-1],'C:\\src\\other.cpp')
        self.assertEqual(r.native_commands(log(compile+progress+b'\n         /O1\n'+boundary),b'',recipe)[0][-1],'/O1')
        project=str(r.PureWindowsPath(recipe['native_target'])/'mikudancestudio_core.vcxproj')
        warning=('     6>C:\\src\\accessory.cpp(1,2): warning C4018: \'<\': signed/unsigned mismatch ['+project+']\n').encode()
        self.assertEqual(r.native_commands(log(compile+warning+progress+b'         /O1\n'+boundary),b'',recipe)[0][-1],'/O1')
        for tail in (b'',b'\n',b'\n\n',progress,progress+b'\n',warning):
            with self.subTest(tail=tail),self.assertRaises(ValueError):r.native_commands(log(compile).split(b'     6>Done')[0]+tail,b'',recipe)
        for content in (b'         unrecognized diagnostic\n',b'         ClCompile:\n',b'         wrong.cpp\n',b'         @hidden.rsp\n',b'         "unterminated.cpp\n',b'       Lib:\n         C:\\VS\\cl.exe /c C:\\src\\accessory.cpp\n'):
            with self.subTest(content=content),self.assertRaises(ValueError):r.native_commands(log(compile+content+boundary),b'',recipe)
        self.assertEqual(len(r.native_commands(log(compile+progress+boundary),b'',recipe)),1)
        self.assertEqual(len(r.native_commands(log(compile+progress),b'',recipe)),1)
        for transition in (b'         foreign.vcxproj -> C:\\build\\core.lib\n',b'     5>Done Building Project "C:\\build\\core.vcxproj" (default targets).\n',b'     1>Project "C:\\build\\one.vcxproj" (1) is building "C:\\build\\two.vcxproj" (2) on node 1 (default targets).\n'):
            with self.assertRaises(ValueError):r.native_commands(log(compile+progress+transition),b'',recipe)

    def test_18_fixed_schema_contract_even_after_reseal(self):
        manifest={'schema':r.SCHEMA,'fp_observation_contract':copy.deepcopy(r.FP_CONTRACT),'base':r.BASE,'paths':r.PATHS,'head':'1'*40}
        manifest['operation_corpus']={'sha256':r.digest(r.operation_corpus()),'size':152,'words':r.corpus_words(r.operation_corpus())}
        r.admit_manifest(manifest)
        for key in ('schema','fp_observation_contract'):
            bad=copy.deepcopy(manifest);bad[key]='wrong'
            with self.assertRaises(ValueError):r.admit_manifest(json.loads(json.dumps(bad)))

    def test_19_synthetic_replay_resealed_result_and_coordinated_commands(self):
        out=Path('/synthetic-evidence');files={};receipts={};builds=[];parsed={}
        exports={name:i+1 for i,name in enumerate(('D3DXLoadMeshFromXW','D3DXVec3TransformCoord','D3DXVec3Transform'))}
        for opt in ('Od','O2'):
            for variant in ('control','observed'):
                recipe=r.recipe('C:/runner/temp',variant,opt);id=recipe['id'];directory=out/id
                n=packet('native',variant=='observed');p=packet('rust',variant=='observed')
                for rows in (n,p):
                    case=None
                    for row in rows:
                        if row['stage']=='case':case=row['id']
                        if case=='floor-affine' and row['stage'] in ('before-observation','observation','final-adjusted'):row['positions'][0][0]=r.word(.5)
                dll=next(row for row in n if row['stage']=='dll');dll.update(size=2,sha256=r.digest(b'MZ'))
                parsed[id]=(r.parse(wire(n),'native',variant=='observed'),r.parse(wire(p),'rust',variant=='observed'))
                binaries={name:{'sha256':r.digest(b'MZ'),'size':2} for name in ('floor_profile.exe','rust-profile.exe','d3dx9_43.dll')}
                b={key:copy.deepcopy(recipe[key]) for key in ('id','source','target','evidence','commands')}
                b.update(variant=variant,optimization=opt,objects={},binaries=binaries,actual_native_commands=[],
                         runtime_corpus={'sha256':r.digest(r.operation_corpus()),'size':152,'created_ns':3},compiled_capture={},
                         original_native_binary={'path':str(r.PureWindowsPath(recipe['native_target'])/'Release/floor_profile.exe'),'sha256':r.digest(b'MZ')},
                         original_rust_binary={'path':'synthetic-cargo-executable','sha256':r.digest(b'MZ')})
                builds.append(b)
                for name in binaries:files[directory/name]=b'MZ'
                files[directory/'mikudancestudio_core.lib']=b'synthetic-archive'
                files[directory/'operations.bin']=r.operation_corpus()
                for label in recipe['commands']:
                    stdout=(wire(n) if label=='native' else wire(p)+b'test result: ok. 1 passed; 0 failed; 0 ignored;\n' if label=='rust' else fixture_output(label) if label in ('mesh_dump','x_files') else b'')
                    receipt={'argv':copy.deepcopy(recipe['commands'][label]),'cwd':recipe['cwd'][label],
                             'start_ns':4 if label in ('native','rust') else 1,'end_ns':5 if label in ('native','rust') else 2,
                             'env':{'CARGO_TARGET_DIR':recipe['target'],'CARGO_INCREMENTAL':'0','RUSTFLAGS':r.RUST_FLAGS,'CL':'','_CL_':''}}
                    if label in ('native','rust'):receipt['executed_binary']={'path':recipe['commands'][label][0],'sha256':r.digest(b'MZ'),'size':2}
                    if label=='native-build':stdout=native_log(b'',recipe)
                    receipts[(id,label)]=(receipt,stdout,b'');files[directory/(label+'.stdout')]=stdout;files[directory/(label+'.stderr')]=b''
        manifest={'schema':r.SCHEMA,'fp_observation_contract':r.FP_CONTRACT,'base':r.BASE,'head':'1'*40,'paths':r.PATHS,'runner_temp':'C:/runner/temp','input_root':r.recipe('C:/runner/temp','control','Od')['input_root'],'builds':builds}
        manifest['operation_corpus']={'sha256':r.digest(r.operation_corpus()),'size':152,'words':r.corpus_words(r.operation_corpus())}
        result={'schema':r.SCHEMA,'fp_observation_contract':r.FP_CONTRACT,'head':'1'*40,'results':{opt:r.classify(*parsed['observed-'+opt]) for opt in ('Od','O2')},'hosted':'ExecutedWindowsOnly','profile_adoption':'NotAuthorized'}
        def encode(value):return json.dumps(value).encode()
        def inventory(_):return {path.relative_to(out).as_posix():{'sha256':r.digest(raw),'size':len(raw)} for path,raw in files.items() if path!=out/'seal.json'}
        def seal():
            files[out/'manifest.json']=encode(manifest);files[out/'result.json']=encode(result)
            files[out/'seal.json']=encode({'schema':r.SCHEMA,'files':inventory(out)})
        seal()
        read_bytes=Path.read_bytes;read_text=Path.read_text
        with patch.object(Path,'read_bytes',lambda path:files[path] if path in files else read_bytes(path)),patch.object(Path,'read_text',lambda path,**kwargs:files[path].decode() if path in files else read_text(path,**kwargs)),patch.object(r.previous,'evidence_inventory',inventory),patch.object(r,'verify_sources'),patch.object(r,'checked',lambda directory,label:receipts[(directory.name,label)]),patch.object(r,'native_provenance',lambda commands,recipe,*args:str(r.PureWindowsPath(recipe['native_target'])/'Release/floor_profile.exe')),patch.object(r,'cargo_binary',return_value='synthetic-cargo-executable'),patch.object(r,'pe_exports',return_value=exports),patch.object(r,'compiled_evidence',return_value={}):
            self.assertEqual(r.replay(out),result)
            complete=copy.deepcopy(builds[1])
            for field in ('objects','compiled_capture'):builds[1].pop(field)
            builds[1]['binaries'].pop('d3dx9_43.dll');seal()
            with self.assertRaises((ValueError,KeyError)):r.replay(out)
            builds[1].clear();builds[1].update(complete);seal()
            self.assertEqual(r.replay(out),result)
            result['results']['Od']['causal_qualification'][0]['operation_environment']='Proved';seal()
            with self.assertRaises(ValueError):r.replay(out)
            result['results']['Od']=r.classify(*parsed['observed-Od']);seal()
            for language in ('native','rust'):
                receipt=receipts[(builds[0]['id'],language)][0];original=copy.deepcopy(receipt['executed_binary'])
                receipt['executed_binary']['sha256']='0'*64;seal()
                with self.assertRaises(ValueError):r.replay(out)
                receipt['executed_binary']=original;seal()
            for label in ('native','rust','configure','native-build','rust-build'):
                old=copy.deepcopy(builds[0]['commands'][label]);receipt=receipts[(builds[0]['id'],label)][0]
                builds[0]['commands'][label]=['wrong-executable'];receipt['argv']=['wrong-executable'];seal()
                with self.assertRaises(ValueError):r.replay(out)
                builds[0]['commands'][label]=old;receipt['argv']=old;seal()

    def test_23_old_verbosity_receipt_rejected_after_reseal(self):
        for opt in ('Od','O2'):
            for variant in ('control','observed'):
                recipe=r.recipe('C:/runner/temp',variant,opt)
                self.assertEqual(recipe['commands']['native-build'][-1],'--verbose')
                self.assertEqual(recipe['commands']['native-build'][-3:],['--parallel','1','--verbose'])
                for argv in (recipe['commands']['native-build'][:-1]+['--','/v:diag'],recipe['commands']['native-build'][:-2]+['4','--verbose']):
                    receipt={'argv':argv,
                             'cwd':recipe['cwd']['native-build'],'env':{'CARGO_TARGET_DIR':recipe['target'],
                             'CARGO_INCREMENTAL':'0','RUSTFLAGS':r.RUST_FLAGS,
                             'CL':'','_CL_':''},'status':0,'terminal':'exit','start_ns':1,'end_ns':2,
                             'start_utc':'start','end_utc':'end'}
                    files={'.stdout':b'old diagnostic output\n','.stderr':b''}
                    for suffix in ('stdout','stderr'):
                        raw=files['.'+suffix]
                        receipt[suffix]={'name':'native-build.'+suffix,'sha256':r.digest(raw),'size':len(raw)}
                    files['.json']=json.dumps(receipt).encode()
                    with patch.object(Path,'read_bytes',lambda path:files[path.suffix]):
                        checked,_,_=r.checked(Path('/resealed'),'native-build')
                    with self.assertRaises(ValueError):r.admit_command(checked,recipe,'native-build')
                    build={key:copy.deepcopy(recipe[key]) for key in ('id','source','target','evidence','commands')}
                    build.update(variant=variant,optimization=opt)
                    build['commands']['native-build']=checked['argv']
                    with self.assertRaises(ValueError):
                        r.admit_recipe({'runner_temp':'C:/runner/temp','input_root':recipe['input_root']},build)

    def test_24_closed_diagnostics_owner_and_channel_boundaries(self):
        recipe=r.recipe('C:/runner/temp','observed','Od');root=r.PureWindowsPath(recipe['native_target']);source=r.PureWindowsPath(recipe['source'])
        project=str(root/'mikudancestudio_core.vcxproj');compiled=source/'src/model/model_skinning.cpp'
        location=str(source/'include/mikudancestudio/subrecord_layout.hpp')+'(206,11):'
        warning='     6>'+location+' warning C4200: nonstandard extension used: zero-sized array in struct/union ['+project+']'
        rows=[warning,"         (compiling source file '../../../floor-profile-evidence/sources/observed-Od/src/model/model_skinning.cpp')",
              '             '+location,'             This member will be ignored by a defaulted constructor or copy/move assignment operator',
              '             '+location,'             the template instantiation context (the oldest one first) is',
              '                 '+str(compiled)+'(667,20):',"                 see reference to class template instantiation 'mikudancestudio::mdl::SkinnedVertex<0>' being compiled"]
        compile=('       ClCompile:\n         C:\\VS\\cl.exe /c /Od "'+str(compiled)+'" "'+str(source/r.ACCESSORY)+'"\n').encode()
        c4018=('     6>'+str(source/r.ACCESSORY)+"(1,2): warning C4018: '<': signed/unsigned mismatch ["+project+']\n').encode()
        diagnostic=('\n'.join(rows)+'\n').encode()
        def log(body):return native_log(body,recipe,'mikudancestudio_core','6')
        baseline=log(compile+diagnostic+c4018)
        expected=r.native_commands(log(compile),b'',recipe)
        self.assertEqual(r.native_commands(baseline,b'',recipe),expected)
        self.assertEqual(r.native_commands(baseline+b'         '+warning.split('>',1)[1].encode()+b'\n',b'',recipe),expected)
        for separator in (b'     6>ClCompile:\n',diagnostic,c4018,b'\n',diagnostic+b'\n     6>ClCompile:\n'):
            for option in (b'/O1',b'-O1',b'/Ox'):
                self.assertEqual(r.native_commands(log(compile+separator+b'         '+option+b'\n'),b'',recipe)[0][-1],option.decode())
        for index in range(8):
            for change in ('missing','append','foreign'):
                bad=rows[:]
                if change=='missing':bad.pop(index)
                elif change=='append':bad[index]+=' /O1'
                else:bad[index]=bad[index].replace('model_skinning','foreign').replace('subrecord_layout','foreign').replace('This member','Unknown member').replace('the template','unknown template').replace('see reference','unknown reference')
                self.assertNotEqual(bad,rows)
                with self.subTest(index=index,change=change),self.assertRaises(ValueError):r.native_commands(log(compile+('\n'.join(bad)+'\n').encode()),b'',recipe)
        for bad in (diagnostic.replace(b'6>',b'5>',1),diagnostic.replace(b'mikudancestudio_core.vcxproj',b'foreign.vcxproj'),c4018.replace(b'accessory.cpp',b'foreign.cpp'),c4018.replace(b'C4018',b'C4999'),c4018.replace(b'signed/unsigned mismatch',b'unknown warning'),c4018.rstrip()+b' /O1\n'):
            with self.assertRaises(ValueError):r.native_commands(log(compile+bad),b'',recipe)
        for context in rows[1:]:
            with self.assertRaises(ValueError):r.native_commands(log((context+'\n').encode()),b'',recipe)
        for index in range(8):
            with self.assertRaises(ValueError):r.native_commands(log(compile)+b'\n'.join(row.encode() for row in rows[:index+1]),b'',recipe)
        for orphan in (b'/O1',b'-O1',b'/Ox',b'"/O1"',b'@hidden.rsp',b'foreign.obj'):
            with self.assertRaisesRegex(ValueError,'orphan native'):r.native_commands(log(b'         '+orphan+b'\n'),b'',recipe)
        for stderr in (diagnostic,c4018,b'     6>Done Building Project "'+project.encode()+b'" (default targets).\n'):
            with self.assertRaisesRegex(ValueError,'unordered native stderr'):r.native_commands(baseline,stderr,recipe)
        for marker in (b'/m:1',b'/v:n',b"Change Dir: '"):
            with self.assertRaises(ValueError):r.native_commands(baseline.replace(marker,marker+b'wrong',1),b'',recipe)
        parent=root/'floor_profile.vcxproj';child=root/'child.vcxproj'
        suspension=('       ClCompile:\n         C:\\VS\\cl.exe /c C:\\src\\one.cpp\n       FinalizeBuildStatus:\n'
                    '     1>Project "'+str(parent)+'" (1) is building "'+str(child)+'" (2) on node 1 (default targets).\n'
                    '     2>Done Building Project "'+str(child)+'" (default targets).\n').encode()
        self.assertEqual(len(r.native_commands(native_log(suspension,recipe),b'',recipe)),1)
        with self.assertRaisesRegex(ValueError,'serial project start'):r.native_commands(native_log(suspension.replace(b'       FinalizeBuildStatus:\n',b''),recipe),b'',recipe)

    def test_90_c4200_interleaved_active_compiler_progress(self):
        recipe=r.recipe('D:/a/_temp','observed','Od',census=True)
        compile=('ClCompile:\n'
                 '  C:\\Program Files\\Microsoft Visual Studio\\2022\\Enterprise\\VC\\Tools\\MSVC\\14.44.35207\\bin\\HostX64\\x64\\CL.exe /c /I"D:\\a\\_temp\\closure-census-evidence\\sources\\obs'
                 'erved-Od\\include" /I"D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\third_party\\mmeffect\\include" /I"D:\\a\\_temp\\closure-census-build\\observed-Od\\native\\'
                 'generated" /nologo /W3 /WX- /diagnostics:column /MP4 /Od /Ob2 /D _MBCS /D WIN32 /D _WINDOWS /D NDEBUG /D _CRT_SECURE_NO_WARNINGS /D "CMAKE_INTDIR=\\"Release\\"" /'
                 'EHsc /MD /GS /fp:precise /Zc:wchar_t /Zc:forScope /Zc:inline /openmp /std:c++17 /permissive- /Fo"mikudancestudio_core.dir\\Release\\\\" /Fd"D:\\a\\_temp\\closure-cens'
                 'us-build\\observed-Od\\native\\Release\\mikudancestudio_core.pdb" /external:W0 /Gd /TP /wd4267 /wd4244 /wd4245 /errorReport:queue  /external:I "C:/Users/runneradmin'
                 '/.conan2/p/b/bullebf46760ffc5b9/p/include" /utf-8 /Zc:alignedNew- "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\mmd_app.cpp" "D:\\a\\_temp\\closu'
                 're-census-evidence\\sources\\observed-Od\\src\\app\\globals.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\app_ctor.cpp" "D:\\a\\_temp\\closure-ce'
                 'nsus-evidence\\sources\\observed-Od\\src\\app\\app_defaults.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\main\\charset_conv.cpp" "D:\\a\\_temp\\closu'
                 're-census-evidence\\sources\\observed-Od\\src\\math\\color_lerp.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\path_utils.cpp" "D:\\a\\_temp\\c'
                 'losure-census-evidence\\sources\\observed-Od\\src\\window\\window_init.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_init.cpp" "D:\\a\\_te'
                 'mp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_font.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\wndproc.cpp" "D:\\a\\_te'
                 'mp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\localize_ui.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\wndproc_aux_window'
                 's.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\command_dispatch.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\wind'
                 'ow\\frame_line_edit.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\accessory_paste.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\obse'
                 'rved-Od\\src\\media\\wave_audio.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\media\\wave_data_chunk.cpp" "D:\\a\\_temp\\closure-census-evidence\\sou'
                 'rces\\observed-Od\\src\\media\\media_load.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\command_impl.cpp" "D:\\a\\_temp\\closure-census-evide'
                 'nce\\sources\\observed-Od\\src\\app\\frame_driver.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\playback_catchup.cpp" "D:\\a\\_temp\\closure-cens'
                 'us-evidence\\sources\\observed-Od\\src\\app\\playback_state.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\timeline_advance.cpp" "D:\\a\\_temp\\cl'
                 'osure-census-evidence\\sources\\observed-Od\\src\\app\\frame_modes.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\frame_modes_bone.cpp" "D:\\a\\_'
                 'temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\key_ladder.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\pump_edit_keys.cpp" "D:'
                 '\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\pump_navigation.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\physics\\physics_cr'
                 'eate.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\physics\\physics_frame.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\phy'
                 'sics\\scene_create.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\physics\\scene_dispose.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observ'
                 'ed-Od\\src\\render\\d3d_init.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\render\\render_states.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources'
                 '\\observed-Od\\src\\render\\stereo_nvapi.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\render\\frame_scene.cpp" "D:\\a\\_temp\\closure-census-evidenc'
                 'e\\sources\\observed-Od\\src\\render\\sprite_overlay.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\render\\overlay_producers.cpp" "D:\\a\\_temp\\closu'
                 're-census-evidence\\sources\\observed-Od\\src\\render\\capture_downsample.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\render\\debug_geometry.cpp"'
                 ' "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\render\\accessory.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\render\\model_rend'
                 'erers.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\render\\bg_overlay.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\render'
                 '\\device_reset.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\avi_record_start.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od'
                 '\\src\\app\\record_readback.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\dshow_record_graph.cpp" "D:\\a\\_temp\\closure-census-evidence\\source'
                 's\\observed-Od\\src\\model\\model_init.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\model\\path_resolve.cpp" "D:\\a\\_temp\\closure-census-evidence\\'
                 'sources\\observed-Od\\src\\model\\pmd_load.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\model\\bone_transform.cpp" "D:\\a\\_temp\\closure-census-evi'
                 'dence\\sources\\observed-Od\\src\\model\\model_keyframe_advance.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\model\\model_keyframe_edit.cpp" "D:\\a'
                 '\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\model\\model_key_reduction.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\model\\bone_edi'
                 't_undo.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\model\\model_frame_seek.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\'
                 'model\\vmd_load.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\model\\track_apply.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\s'
                 'rc\\model\\key_registrars.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\model\\morph_apply.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\obse'
                 'rved-Od\\src\\model\\model_skinning.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\model\\pmx_load.cpp" "D:\\a\\_temp\\closure-census-evidence\\source'
                 's\\observed-Od\\src\\model\\add_model.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\model\\model_query_helpers.cpp" "D:\\a\\_temp\\closure-census-evi'
                 'dence\\sources\\observed-Od\\src\\model\\model_dispose.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\model\\bone_sort.cpp" "D:\\a\\_temp\\closure-cens'
                 'us-evidence\\sources\\observed-Od\\src\\model\\post_load_init.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\render\\fill_panel.cpp" "D:\\a\\_temp\\clo'
                 'sure-census-evidence\\sources\\observed-Od\\src\\window\\wm_paint.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_timeline_gfx.cpp" "D:\\a\\'
                 '_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_control_text.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_ctlcolor'
                 '.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_edit_commit.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\'
                 'dialog_procs.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\frame_range_apply.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed'
                 '-Od\\src\\io\\pmm_save.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\io\\io_device_helpers.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\obser'
                 'ved-Od\\src\\io\\vpd_file.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\io\\vmd_save.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od'
                 '\\src\\io\\pmm_load_dispatch.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\io\\pmm_load_v2.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\obser'
                 'ved-Od\\src\\io\\pmm_playback_options.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\io\\pmm_load_v1.cpp" "D:\\a\\_temp\\closure-census-evidence\\sour'
                 'ces\\observed-Od\\src\\window\\ui_scroll_mouse.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_panel_paint.cpp" "D:\\a\\_temp\\closure-censu'
                 's-evidence\\sources\\observed-Od\\src\\window\\ui_refresh.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_notify.cpp" "D:\\a\\_temp\\closure-'
                 'census-evidence\\sources\\observed-Od\\src\\window\\ui_hscroll.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_dropfiles.cpp" "D:\\a\\_temp\\'
                 'closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_panel_sweep.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_view_refresh.cp'
                 'p" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_model_reload.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui'
                 '_selection_reeval.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_editor_click.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\obser'
                 'ved-Od\\src\\window\\timeline_selection.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_frame_step.cpp" "D:\\a\\_temp\\closure-census-evide'
                 'nce\\sources\\observed-Od\\src\\window\\ui_frame_refresh.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_mousemove.cpp" "D:\\a\\_temp\\closur'
                 'e-census-evidence\\sources\\observed-Od\\src\\window\\ui_windowsize.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\mic_window.cpp" "D:\\a\\_te'
                 'mp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\subsystem_init.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\reset_app_state.cpp" '
                 '"D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\scene_ownership.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\app_utiliti'
                 'es.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\shutdown_cleanup.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\on'
                 'i_kinect.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\oni_skeleton_pump.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src'
                 '\\io\\vsq_load.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\dialog_select_ops.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed'
                 '-Od\\src\\window\\ui_viewport_refresh.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_viewport_layout.cpp" "D:\\a\\_temp\\closure-census-ev'
                 'idence\\sources\\observed-Od\\src\\window\\ui_mouse_misc.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\ui_palette.cpp" "D:\\a\\_temp\\closure-'
                 'census-evidence\\sources\\observed-Od\\src\\window\\command_file_menu.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\command_view_menu.cpp" '
                 '"D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\physics_model_dialog.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\'
                 'model_order_dialog.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\gravity_setting_dialog.cpp" "D:\\a\\_temp\\closure-census-evidence\\sourc'
                 'es\\observed-Od\\src\\window\\english_name_dialog.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\enhance_model_io.cpp" "D:\\a\\_temp\\closure-'
                 'census-evidence\\sources\\observed-Od\\src\\window\\misc_dialogs.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\command_frame_edit.cpp" "D:\\'
                 'a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\frame_clipboard.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\model\\global_key'
                 '_registration.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\command_panel_toggles.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\obs'
                 'erved-Od\\src\\window\\bone_pose_clipboard.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\window\\bone_pose_edit.cpp" "D:\\a\\_temp\\closure-census-e'
                 'vidence\\sources\\observed-Od\\src\\window\\command_frame_register.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\features\\dialog_helpers.cpp" "D:\\'
                 'a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\features\\audio_pose_helpers.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\render\\draw'
                 '_glyph.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\render\\toon_textures.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\re'
                 'nder\\scene_font.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\render\\mme\\mme_bridge.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed'
                 '-Od\\src\\exports\\effect_api.cpp" "D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\app\\late_ports.cpp"'
                 '\n').encode()
        rows=['D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\include\\mikudancestudio\\subrecord_layout.hpp(206,11): warning C4200: nonstandard extension used: zero-sized array in struct/union [D:\\a\\_temp\\closure-census-build\\observed-Od\\native\\mikudancestudio_core.vcxproj]', '  bone_sort.cpp', "  (compiling source file '../../../closure-census-evidence/sources/observed-Od/src/model/model_skinning.cpp')", '      D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\include\\mikudancestudio\\subrecord_layout.hpp(206,11):', '      This member will be ignored by a defaulted constructor or copy/move assignment operator', '      D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\include\\mikudancestudio\\subrecord_layout.hpp(206,11):', '      the template instantiation context (the oldest one first) is', '          D:\\a\\_temp\\closure-census-evidence\\sources\\observed-Od\\src\\model\\model_skinning.cpp(667,20):', "          see reference to class template instantiation 'mikudancestudio::mdl::SkinnedVertex<0>' being compiled"]
        self.assertLess(len(compile)+len('\n'.join(rows).encode()),64*1024)
        def log(command,context):return native_log(command+('\n'.join(context)+'\n').encode(),recipe,'mikudancestudio_core','6')
        baseline=rows[:1]+rows[2:]
        expected=r.native_commands(native_log(compile,recipe,'mikudancestudio_core','6'),b'',recipe)
        self.assertEqual(r.native_commands(log(compile,baseline),b'',recipe),expected)
        self.assertEqual(r.native_commands(log(compile,rows),b'',recipe),expected)
        self.assertEqual(expected[0][1:],r.command_words(compile.decode().splitlines()[1].split('CL.exe ',1)[1]))
        self.assertIn('/MP4',expected[0]);self.assertEqual(len(expected[0]),184)
        for prefix in (['  bone_sort.cpp','  accessory.cpp'],['  BONE_SORT.CPP']):
            self.assertEqual(r.native_commands(log(compile,rows[:1]+prefix+rows[2:]),b'',recipe),expected)
        for flag in ('/O1','-O1','/Ox'):
            continued=log(compile,rows+["  "+flag])
            self.assertEqual(r.native_commands(continued,b'',recipe),[expected[0]+[flag]])
        bad_prefixes=[['  unknown.cpp'],['  bone_sort.cpp','  bone_sort.cpp'],['  bone_sort.cpp','  BONE_SORT.CPP'],
                      [' bone_sort.cpp'],['   bone_sort.cpp'],['  bone_sort.cpp /O1'],['  /O1'],['  -O1'],
                      ['  "bone_sort.cpp"'],["  'bone_sort.cpp'"],['  src/model/bone_sort.cpp'],
                      ['  C:\\src\\bone_sort.cpp'],['  @bone_sort.cpp'],['  -bone_sort.cpp'],['  /bone_sort.cpp'],
                      ['     6>bone_sort.cpp'],['     5>bone_sort.cpp'],['  '],['arbitrary text'],['Build succeeded.'],
                      ['Lib:'],['ClCompile:'],['  C:\\VS\\cl.exe /c bone_sort.cpp'],[rows[0]],
                      [rows[0].replace('mikudancestudio_core.vcxproj','foreign.vcxproj')],
                      ['     6>Done Building Project "'+str(r.PureWindowsPath(recipe['native_target'])/'mikudancestudio_core.vcxproj')+'" (default targets).'],
                      ['     1>Project "'+str(r.PureWindowsPath(recipe['native_target'])/'foreign.vcxproj')+'" on node 1 (default targets).']]
        for prefix in bad_prefixes:
            with self.subTest(prefix=prefix),self.assertRaises(ValueError):r.native_commands(log(compile,rows[:1]+prefix+rows[2:]),b'',recipe)
        bone=str(r.PureWindowsPath(recipe['source'])/'src/model/bone_sort.cpp').encode()
        for command in (compile.replace(bone,bone.replace(b'bone_sort',b'unknown')),
                        compile.rstrip()+b' "'+bone+b'"\n',
                        compile.rstrip()+b' "'+str(r.PureWindowsPath(recipe['source'])/'foreign/bone_sort.cpp').encode()+b'"\n',
                        compile.replace(b'model_skinning.cpp',b'foreign_skinning.cpp')):
            with self.subTest(command=command[-180:]),self.assertRaises(ValueError):r.native_commands(log(command,rows),b'',recipe)
        for index in range(2,len(rows)):
            for change in ('missing','altered','swapped'):
                bad=rows[:]
                if change=='missing':bad.pop(index)
                elif change=='altered':bad[index]+=' /O1'
                else:bad[index],bad[index-1]=bad[index-1],bad[index]
                with self.subTest(index=index,change=change),self.assertRaises(ValueError):r.native_commands(log(compile,bad),b'',recipe)
        for index in range(1,len(rows)):
            with self.subTest(truncated=index),self.assertRaises(ValueError):r.native_commands(log(compile,rows[:index]),b'',recipe)
        for index in range(3,len(rows)):
            with self.subTest(interior=index),self.assertRaises(ValueError):r.native_commands(log(compile,rows[:index]+['  bone_sort.cpp']+rows[index:]),b'',recipe)
        with self.assertRaises(ValueError):r.native_commands(log(compile,[rows[0],'  bone_sort.cpp']),b'',recipe)
        for stderr in (rows[0],rows[1],rows[2]):
            with self.subTest(stderr=stderr),self.assertRaisesRegex(ValueError,'unordered native stderr'):r.native_commands(log(compile,rows),stderr.encode(),recipe)

    def test_25_project_output_preserves_full_owner_path(self):
        recipe=r.recipe('D:/a/_temp','control','Od');root=r.PureWindowsPath(recipe['native_target'])
        owner=root/'mikudancestudio_core.vcxproj'
        def admitted(raw):
            receipt={'argv':recipe['commands']['native-build'],'cwd':recipe['cwd']['native-build'],'env':{'CARGO_TARGET_DIR':recipe['target'],'CARGO_INCREMENTAL':'0','RUSTFLAGS':r.RUST_FLAGS,'CL':'','_CL_':''},'status':0,'terminal':'exit','start_ns':1,'end_ns':2,'start_utc':'start','end_utc':'end'}
            for suffix,value in [('stdout',raw),('stderr',b'')]:receipt[suffix]={'name':'native-build.'+suffix,'sha256':r.digest(value),'size':len(value)}
            files={'.json':json.dumps(receipt).encode(),'.stdout':raw,'.stderr':b''}
            with patch.object(Path,'read_bytes',lambda path:files[path.suffix]):
                checked,stdout,stderr=r.checked(Path('/resealed-owner'),'native-build')
            r.admit_command(checked,recipe,'native-build')
            return r.native_commands(stdout,stderr,recipe)
        for task,tool,output in [('Lib','lib','Release/mikudancestudio_core.lib'),('Link','link','Release/mikudancestudio_core.exe')]:
            command=['C:\\VS\\'+tool+'.exe','/OUT:'+str(root/output),'accessory.obj']
            body=('       '+task+':\n         '+' '.join(command)+'\n').encode()
            baseline=native_log(body,recipe,'mikudancestudio_core','6')
            self.assertEqual(admitted(baseline),[command])
            for project in [owner.name,str(owner),owner.as_posix(),str(owner.with_suffix('')).upper()+'.vcxproj','./'+owner.name,'child/../'+owner.name]:
                raw=native_log(body+('     6>'+project+' -> '+str(root/output)+'\n').encode(),recipe,'mikudancestudio_core','6')
                with self.subTest(task=task,project=project):self.assertEqual(admitted(raw),[command])
            for project in ['C:/foreign/'+owner.name,'D:/foreign/'+owner.name,'foreign/'+owner.name,'../'+owner.name,'C:'+owner.name,'different.vcxproj']:
                raw=native_log(body+('     6>'+project+' -> '+str(root/output)+'\n').encode(),recipe,'mikudancestudio_core','6')
                with self.subTest(task=task,project=project),self.assertRaisesRegex(ValueError,'matching project output'):admitted(raw)

    def test_26_closed_build_system_progress(self):
        recipe=r.recipe('D:/a/_temp','control','Od');root=r.PureWindowsPath(recipe['native_target'])
        body=b'       CustomBuild:\n  1>Checking Build System\n'
        def log(value):return native_log(value,recipe,'ZERO_CHECK','2')
        baseline=log(body)
        self.assertEqual(r.native_commands(baseline,b'',recipe),[])
        command=b'       ClCompile:\n         C:\\VS\\cl.exe /c C:\\src\\accessory.cpp\n'
        after=baseline.replace(b'     1>Done Building',command+b'     1>Done Building',1)
        self.assertEqual(r.native_commands(after,b'',recipe),[['C:\\VS\\cl.exe','/c','C:\\src\\accessory.cpp']])
        for bad in [baseline.replace(b'  1>Checking',prefix+b'Checking') for prefix in (b'  2>',b'  9>',b'')]+[
                baseline.replace(b'ZERO_CHECK.vcxproj',b'OTHER.vcxproj'),
                baseline.replace(str(root/'ZERO_CHECK.vcxproj').encode(),str(root/'foreign/ZERO_CHECK.vcxproj').encode()),
                baseline.replace(str(root/'floor_profile.vcxproj').encode(),str(root/'foreign/floor_profile.vcxproj').encode()),
                log(body.replace(b'CustomBuild:',b'ClCompile:')),
                log(body.replace(b'Checking Build System',b'Checking Build System /O1')),
                log(body.replace(b'Checking Build System',b'Checking Build Systems')),
                baseline[:baseline.index(b'     2>Done Building')]]:
            with self.subTest(raw=bad),self.assertRaises(ValueError):r.native_commands(bad,b'',recipe)
        for task,tool in [('ClCompile','cl'),('Lib','lib'),('Link','link')]:
            pending=('       '+task+':\n         C:\\VS\\'+tool+'.exe /OUT:Release\\check.lib accessory.obj\n').encode()
            valid=log(pending)
            expected=r.native_commands(valid,b'',recipe)
            self.assertEqual(len(expected),1)
            for progress in (b'  1>Checking Build System\n',b'  2>Checking Build System\n'):
                with self.subTest(task=task,progress=progress),self.assertRaises(ValueError):r.native_commands(log(pending+progress),b'',recipe)
        for stderr in (body,b'  1>Checking Build System\n'):
            with self.assertRaisesRegex(ValueError,'unordered native stderr'):r.native_commands(baseline,stderr,recipe)

    def test_27_complete_fixture_output_boundary(self):
        emitter='fn emit(value: String) { ACTIVE.with(|a| if a.get() { println!("FP {value}"); }); }'
        self.assertEqual(r.FIXTURE_EMITTER,emitter)
        self.assertEqual((r.HERE/'observer.rs').read_text().splitlines().count(emitter),1)
        for opt in ('Od','O2'):
            for variant in ('control','observed'):
                generated,_=r.generated(lambda path:(r.ROOT/path).read_bytes(),variant=='observed','C:/runner/temp/floor-profile-evidence/inputs')
                source_lines=generated[r.MESH].decode().splitlines()
                self.assertEqual(source_lines.count(emitter),1)
                excerpt=(str(source_lines.index(emitter)+1)+' | '+emitter+'\n').encode()
                recipe=r.recipe('C:/runner/temp',variant,opt)
                for label in ('mesh_dump','x_files'):
                    names=fixture_names(label);count=len(names);stdout=fixture_output(label)
                    self.assertEqual(count,1 if label=='mesh_dump' else 13)
                    self.assertEqual(set(names),r.FIXTURE_TESTS[label])
                    def admitted(out,err,argv=None,coordinated=False):
                        command=recipe['commands'][label] if argv is None else argv
                        receipt={'argv':command,'cwd':recipe['cwd'][label],
                                 'env':{'CARGO_TARGET_DIR':recipe['target'],'CARGO_INCREMENTAL':'0','RUSTFLAGS':r.RUST_FLAGS,'CL':'','_CL_':''},
                                 'status':0,'terminal':'exit','start_ns':1,'end_ns':2,'start_utc':'start','end_utc':'end'}
                        files={label+'.stdout':out,label+'.stderr':err}
                        for suffix in ('stdout','stderr'):
                            raw=files[label+'.'+suffix];receipt[suffix]={'name':label+'.'+suffix,'sha256':r.digest(raw),'size':len(raw)}
                        files[label+'.json']=json.dumps(receipt).encode()
                        build={key:copy.deepcopy(recipe[key]) for key in ('id','source','target','evidence','commands')}
                        build.update(variant=variant,optimization=opt)
                        if coordinated:build['commands'][label]=command
                        manifest={'runner_temp':'C:/runner/temp','input_root':recipe['input_root'],'builds':[build]}
                        files['manifest.json']=json.dumps(manifest).encode()
                        inventory=lambda:{name:{'size':len(raw),'sha256':r.digest(raw)} for name,raw in files.items() if name!='seal.json'}
                        files['seal.json']=json.dumps({'schema':r.SCHEMA,'files':inventory()}).encode()
                        with patch.object(Path,'read_bytes',lambda path:files[path.name]):
                            self.assertEqual(r.load_json(files['seal.json'])['files'],inventory())
                            checked,a,b=r.checked(Path('/refreshed-fixture'),label)
                            fixed=r.admit_recipe(manifest,build);r.admit_command(checked,fixed,label)
                            r.fixture_result(label,a,b)
                    for err in (b'',b'warning: function emit is never used\n'+excerpt):
                        admitted(stdout,err)
                        admitted(stdout.replace(b'\n',b'\r\n'),err.replace(b'\n',b'\r\n'))
                    lines=stdout.split(b'\n');reordered=lines[:];reordered[2:2+count]=reversed(reordered[2:2+count])
                    admitted(b'\n'.join(reordered),excerpt)
                    bad_outputs={
                        'wrong-name':stdout.replace(names[0].encode(),b'wrong_name',1),
                        'missing-name':b'\n'.join(lines[:2]+lines[3:]),
                        'duplicate-row':b'\n'.join(lines[:3]+[lines[2]]+lines[3:]),
                        'wrong-header':stdout.replace(('running '+str(count)).encode(),b'running 99',1),
                        'wrong-summary':stdout.replace((str(count)+' passed;').encode(),b'99 passed;'),
                        'ignored':stdout.replace(b'0 ignored;',b'1 ignored;'),
                        'filtered':stdout.replace(b'0 filtered out;',b'1 filtered out;'),
                        'measured':stdout.replace(b'0 measured;',b'1 measured;'),
                        'failure':stdout.replace(b'0 failed;',b'1 failed;'),
                        'failed-status':stdout.replace(b'test result: ok.',b'test result: FAILED.'),
                        'ignored-row':stdout.replace(b' ... ok',b' ... ignored',1),
                        'skip':stdout+b'SKIP unsupported\n',
                        'zero':b'\nrunning 0 tests\n\ntest result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s\n\n',
                        'missing-header':b'\n'.join(lines[:1]+lines[2:]),
                        'missing-summary':b'\n'.join(lines[:-3]+lines[-2:]),
                        'multiple':stdout+stdout,'truncated':stdout[:-1],
                        'unknown':stdout+b'unknown output\n','no-leading-blank':stdout[1:],
                        'extra-blank':b'\n'+stdout,'bare-cr':stdout.replace(b'\n',b'\r'),
                        'invalid-utf8':stdout+b'\xff',
                    }
                    if count>1:
                        bad_outputs['duplicate-name']=stdout.replace(names[1].encode(),names[0].encode(),1)
                    for telemetry in (b'FP {"stage":"begin"}',b'FP {broken',b'FP',b'FP ',b'FP{truncated'):
                        bad_outputs['standalone-'+repr(telemetry)]=stdout+telemetry+b'\n'
                        bad_outputs['inline-'+repr(telemetry)]=stdout.replace(b' ... ok',b' ... '+telemetry+b' ok',1)
                    for name,bad in bad_outputs.items():
                        with self.subTest(variant=variant,opt=opt,label=label,case=name),self.assertRaises(ValueError):admitted(bad,excerpt)
                    bad_errors=[b'SKIP unsupported\n',b'FP {"stage":"begin"}\n',b'FP {broken\n',b'FP\n',b'prefix FP {broken\n',
                                b'running '+str(count).encode()+b' tests\n',lines[2]+b'\n',lines[-3]+b'\n',
                                b'prefix '+excerpt,excerpt.rstrip()+b' suffix\n',excerpt.replace(b'ACTIVE',b'INACTIVE'),
                                b'584 | FP {"stage":"begin"}\n',excerpt+b'FP {broken\n',excerpt+excerpt]
                    for bad in bad_errors:
                        with self.subTest(variant=variant,opt=opt,label=label,stderr=bad),self.assertRaises(ValueError):admitted(stdout,bad)
                    with self.assertRaises(ValueError):admitted(b'',stdout)
                    original=recipe['commands'][label]
                    wrong=[v for v in original if v!='--nocapture']
                    for argv in (wrong,original+['some_filter'],original+['--ignored'],original+['--include-ignored'],original+['--skip','some_test']):
                        with self.assertRaisesRegex(ValueError,'exact command/cwd binding'):admitted(stdout,excerpt,argv)
                        with self.assertRaisesRegex(ValueError,'closed command/source/target/evidence recipe'):admitted(stdout,excerpt,argv,True)

    def test_28_capture_and_replay_share_fixture_boundary(self):
        calls=[];validator=r.fixture_result
        def observed(label,stdout,stderr):
            validator(label,stdout,stderr);calls.append(label)
        with patch.object(r,'fixture_result',observed):
            self.test_19_synthetic_replay_resealed_result_and_coordinated_commands()
        self.assertEqual(calls[:8],['mesh_dump','x_files']*4)
        self.assertEqual(set(calls),{'mesh_dump','x_files'})
        recipe=r.recipe('C:/runner/temp','control','Od');out=Path('C:/runner/temp/floor-profile-evidence')
        build=Path('C:/runner/temp/floor-profile-build');toolchain=Path('C:/runner/temp/floor-profile-deps/build/generators/conan_toolchain.cmake')
        files={};captured=[];fixtures={label:fixture_output(label) for label in ('mesh_dump','x_files')}
        class Complete(Exception):pass
        def record(directory,label,argv,cwd,env,timeout=1200):
            raw=(r.ACCEPTED_MAIN['merge'].encode() if label in ('git-head','git-first-parent-ancestry') else '\n'.join(r.PATHS).encode() if label=='git-paths' else
                 fixtures[label] if label in ('mesh_dump','x_files') else b'')
            files[directory/(label+'.stdout')]=raw;files[directory/(label+'.stderr')]=b''
            return {'status':0}
        def boundary(label,stdout,stderr):
            validator(label,stdout,stderr);captured.append(label)
            if label=='x_files':raise Complete()
        def parse(raw,language,observed):return {'dll':{'path':'synthetic-dll'}} if language=='native' else {}
        with patch.object(r.sys,'platform','win32'),patch.dict(os.environ,{'GITHUB_ACTIONS':'true','RUNNER_TEMP':'C:/runner/temp','GITHUB_SHA':r.ACCEPTED_MAIN['merge']}), \
             patch.object(Path,'exists',return_value=False),patch.object(Path,'is_file',return_value=True),patch.object(Path,'mkdir'), \
             patch.object(Path,'read_bytes',lambda path:files.get(path,b'')),patch.object(Path,'read_text',lambda path,**kwargs:files.get(path,b'').decode()),patch.object(Path,'write_bytes'), \
             patch.object(r,'record',record),patch.object(r.shutil,'copyfile'),patch.object(r.shutil,'copytree'),patch.object(r.c,'safe_tar',return_value={}), \
             patch.object(r.c,'source_inventory',return_value={}),patch.object(r,'inputs',return_value=[]),patch.object(r,'source_expected',return_value=({}, {}, {})), \
             patch.object(r,'native_commands',return_value=[]),patch.object(r,'parse',parse),patch.object(r,'cargo_binary',return_value='synthetic-cargo'), \
             patch.object(r,'fixture_result',boundary),patch.multiple(r,write_json=unittest.mock.DEFAULT,acquire_source_admission=unittest.mock.DEFAULT):
            with self.assertRaises(Complete):r.run(out,build,toolchain)
        self.assertEqual(captured,['mesh_dump','x_files'])

    def test_29_operation_domains_and_finite_alternatives(self):
        n=r.parse(wire(packet('native')),'native',True);rows=packet('rust')
        baseline=r.parse(wire(rows),'rust',True);proof=r.operation_assessment(n,baseline)
        self.assertEqual(proof['proof_status'],'UnprovedAwaitingIndependentReview')
        self.assertEqual(proof['runtime_direct_vs_merge']['classification'],'NotComparable')
        self.assertTrue(all(v['cause_status']=='Held' for v in proof['relations']))
        hardware=next(v for v in rows if v.get('kind')=='HardwareSeedWithFrozenRefinement')
        hardware['values'][1]=r.word(.75);hardware['output'][0]=r.word(.5)
        result=r.operation_assessment(n,r.parse(wire(rows),'rust',True))
        self.assertEqual(result['relations'][0]['table_vs_hardware_seed']['classification'],'SemanticDifference')
        self.assertEqual(result['observations'][1]['numerical_oracle']['comparison']['classification'],'SemanticDifference')
        hardware['samples']=[0x9f81,0x9fa0]
        result=r.operation_assessment(n,r.parse(wire(rows),'rust',True))
        self.assertEqual(result['observations'][1]['numerical_oracle']['domain'],'UnprovedNondefaultControls')
        self.assertEqual(result['observations'][1]['observed']['fp'][0]['sticky_flags'],1)
        self.assertEqual(result['proof_status'],'UnprovedAwaitingIndependentReview')
        for w,e,refined in [(1.,0x3f7ff000,0x3f7fffff),(3.,0x3eaaa000,0x3eaaaaaa)]:
            observation=next(v for v in proof['observations'] if v['kind']=='RustTable' and v['owner']==[1,0 if w==1. else 1,0,0])
            self.assertEqual(observation['numerical_oracle']['derived']['values'],[r.word(w),e,refined])

    def test_30_operation_admission_rejects_malformed_provenance(self):
        self.assertEqual(len(r.operation_corpus()),152)
        for raw in (b'',r.operation_corpus()[:-1],r.operation_corpus()+b'\0',bytes(152)):
            with self.assertRaises(ValueError):r.corpus_words(raw)
        def mutate(rows,name):
            op=next(v for v in rows if v.get('kind')=='RustTable')
            if name=='duplicate':rows.insert(rows.index(op),copy.deepcopy(op))
            elif name=='missing':rows.remove(op)
            elif name=='owner':op['owner']=[2,0,0,0]
            elif name=='word':op['input'][0]=2**32
            elif name=='boolean':op['input'][0]=True
            elif name=='nan':op['values'][1]=0x7fc00000
            elif name=='missing-site':op['sites'][1]=0
            elif name=='bad-site':op['sites'][0]=op['base']-1
            elif name=='bad-sample':op['samples'][0]=65536
            elif name=='recipe-promotion':op['compiled_dataflow']='Proved'
            elif name=='corpus':next(v for v in rows if v['stage']=='runtime-read')['words'].pop()
            elif name=='corpus-boolean':next(v for v in rows if v['stage']=='runtime-read')['words'][4]=False
            elif name=='fixture':next(v for v in rows if v['stage']=='merge-read')['bytes'][0]^=1
            elif name=='destination':next(v for v in rows if v.get('kind')=='RustTable' and v.get('owner')==[2,0,0,0])['destination'][0]=r.word(.5)
        for name in ('duplicate','missing','owner','word','boolean','nan','missing-site','bad-site','bad-sample','recipe-promotion','corpus','corpus-boolean','fixture','destination'):
            rows=packet('rust');mutate(rows,name)
            with self.subTest(name=name),self.assertRaises((ValueError,KeyError,IndexError)):r.parse(wire(rows),'rust',True)
        for key,value in [('values',[1,2,3]),('target',1),('kind','RustTable')]:
            rows=packet('native');next(v for v in rows if v.get('kind')=='DllCall')[key]=value
            with self.assertRaises(ValueError):r.parse(wire(rows),'native',True)

    def test_31_executed_image_ranges_and_disassembly_bytes(self):
        raw,mapping,rows,assembly=code_fixture();witness=r.code_ranges(raw,rows,mapping);span=witness['ranges'][0]
        self.assertEqual(span['bytes'],(b'\x90'*7+b'\xc3').hex())
        r.disassembly_bytes(assembly,witness,span)
        self.assertEqual(witness['compiled_dataflow'],'UnprovedAwaitingIndependentReview')
        for changed in (assembly.replace(b'90',b'91',1),assembly.replace(b'140001000',b'140001001'),assembly.split(b'\n',1)[1],assembly.replace(b'nop',b'<unknown>',1),assembly+assembly):
            with self.subTest(assembly=changed),self.assertRaises(ValueError):r.disassembly_bytes(changed,witness,span)
        for sites in ([8192+0x2000],[8192+0x1100],[8192-1]):
            with self.assertRaises(ValueError):r.code_ranges(raw,[{'base':8192,'sites':sites}],mapping)
        for bad in (mapping.replace(b'140000000',b'150000000'),b'not a map'):
            with self.assertRaises(ValueError):r.code_ranges(raw,rows,bad)
        changed=bytearray(raw);struct.pack_into('<I',changed,428,0x40000040)
        with self.assertRaises(ValueError):r.code_ranges(bytes(changed),rows,mapping)
        bad=copy.deepcopy(span);bad['end_rva']+=1
        with self.assertRaises(ValueError):r.disassembly_bytes(assembly,witness,bad)

    def test_32_compiled_capture_requires_actual_capability_receipts(self):
        raw,mapping,rows,assembly=code_fixture();witness=r.code_ranges(raw,rows,mapping)
        witness['same_link_map']={'sha256':r.digest(mapping),'size':len(mapping)}
        witness.update(pending=[],decoded=[[s['start_rva'],s['end_rva']] for s in witness['ranges']])
        rust_witness=r.required_code_ranges(raw,rows,mapping)
        rust_witness['same_link_map']=witness['same_link_map']
        rust_witness['caller_windows']=r.caller_windows({'operations':rows,'merge_lineage':lineage()})
        rust_witness['data_requests']=[{'role':'SeedTable','size':8192,'synthetic':'seed bytes separately tested','resolution':'Resolved'}]
        rust_witness['copy_obligations']=[{'size':176,'role':'OperationReturn','status':'RequiresIndependentCallerRegionAndPathReview'},
                                         {'size':8192,'role':'OdSeedTable','status':'RequiresIndependentCallerRegionAndPathReview'}]
        for address in (lineage()['returned'][4],*[a[9] for a in lineage()['rows']]):
            r.request_range(rust_witness,raw,address-8192,'MergePointerLineage',{'kind':'RuntimeSite','role':'MergeStorage'})
        rust_witness['edges']=[]
        for span in rust_witness['ranges']:
            for edge in r.instruction_edges(instructions(span),rust_witness,span):
                r.follow_required_edge(None,[{'witness':rust_witness,'raw':raw}],0,span,edge);rust_witness['edges'].append(edge)
        rust_witness.update(pending=[],decoded=[[s['start_rva'],s['end_rva']] for s in rust_witness['ranges']],runtime_images=[])
        r.complete_closure([{'witness':rust_witness,'raw':raw}])
        recipe=r.recipe('C:/runner/temp','observed','Od');directory=Path('/synthetic-compiled-capture')
        files={}
        for language,binary,map_name in (('native','floor_profile.exe','native.map'),('rust','rust-profile.exe','rust.map')):
            files[directory/binary]=raw;files[directory/map_name]=mapping;files[directory/(language+'-code.json')]=json.dumps(witness if language=='native' else rust_witness).encode()
        tool_raw=b'retained tool bytes are data'
        files[directory/'instruction-tool.bin']=tool_raw
        tool={'path':str(r.DISASSEMBLER),'sha256':r.digest(tool_raw),'size':len(tool_raw)}
        help={'argv':[str(r.DISASSEMBLER),'--help'],'cwd':recipe['source'],'tool_binary':tool}
        receipts={'instruction-help':(help,b'--disassemble --start-address --stop-address',b'')}
        for language,name in (('native','floor_profile.exe'),('rust','rust-profile.exe')):
            view=witness if language=='native' else rust_witness
            for i,span in enumerate(view['ranges']):
                argv=r.disassembly_argv(r.PureWindowsPath(recipe['evidence'])/name,view,span)
                receipts[language+'-instructions-'+str(i)]=({'argv':argv,'cwd':recipe['source'],'tool_binary':copy.deepcopy(tool)},instructions(span),b'')
        parsed=({'operations':rows},{'operations':rows,'merge_lineage':lineage()})
        with patch.object(Path,'read_bytes',lambda path:files[path]),patch.object(r,'checked',lambda directory,label:receipts[label]),patch.object(r,'runtime_images',return_value=[]),patch.object(r,'seed_data',return_value={'role':'SeedTable','size':8192,'synthetic':'seed bytes separately tested','resolution':'Resolved'}):
            self.assertEqual(set(r.compiled_evidence(directory,parsed,recipe)),{'native','rust'})
            del files[directory/'instruction-tool.bin']
            with self.assertRaises(KeyError):r.compiled_evidence(directory,parsed,recipe)
            for bad in (tool_raw[:-1],b'x'*len(tool_raw)):
                files[directory/'instruction-tool.bin']=bad
                with self.assertRaisesRegex(ValueError,'retained hosted instruction tool identity'):r.compiled_evidence(directory,parsed,recipe)
            files[directory/'instruction-tool.bin']=tool_raw
            receipts['instruction-help']=(help,b'--disassemble',b'')
            with self.assertRaises(ValueError):r.compiled_evidence(directory,parsed,recipe)
            receipts['instruction-help']=(help,b'--disassemble --start-address --stop-address',b'')
            for key,value in [('argv',['foreign.exe']),('cwd','C:/wrong'),('tool_binary',dict(tool,sha256='2'*64))]:
                row=receipts['rust-instructions-0'][0];old=copy.deepcopy(row[key]);row[key]=value
                with self.assertRaises(ValueError):r.compiled_evidence(directory,parsed,recipe)
                row[key]=old
            bad=copy.deepcopy(rust_witness);bad['compiled_dataflow']='Proved'
            files[directory/'rust-code.json']=json.dumps(bad).encode()
            with self.assertRaises(ValueError):r.compiled_evidence(directory,parsed,recipe)

    def test_33_ordinary_generation_ancestry_keeps_frozen_parent(self):
        directory=Path('/synthetic-ancestry');files={};chain=[];parent=r.PARENT
        for message in ('operation diagnostic','strict runtime words'):
            raw=('tree '+'1'*40+'\nparent '+parent+'\nauthor Test <test@example.invalid> 0 +0000\ncommitter Test <test@example.invalid> 0 +0000\n\n'+message+'\n').encode()
            parent=r.h.git_hash('commit',raw);chain.append(parent);files[directory/'ancestry'/(parent+'.commit')]=raw
        manifest={'head':chain[-1],'generation_ancestry':chain}
        with patch.object(Path,'read_bytes',lambda path:files[path]):
            r.generation_ancestry(directory,manifest)
            for bad in ([],chain[::-1],chain+chain,chain[1:]):
                with self.assertRaises(ValueError):r.generation_ancestry(directory,dict(manifest,generation_ancestry=bad))
            raw=files[directory/'ancestry'/(chain[-1]+'.commit')]
            for changed in (raw.replace(('parent '+chain[0]).encode(),('parent '+r.PARENT).encode()),raw.replace(b'\nauthor',('\nparent '+'2'*40+'\nauthor').encode())):
                revision=r.h.git_hash('commit',changed);files[directory/'ancestry'/(revision+'.commit')]=changed
                with self.assertRaisesRegex(ValueError,'ordinary linear descent'):r.generation_ancestry(directory,{'head':revision,'generation_ancestry':[chain[0],revision]})
            files[directory/'ancestry'/(chain[-1]+'.commit')]=raw+b'corrupt'
            with self.assertRaisesRegex(ValueError,'ancestry commit hash'):r.generation_ancestry(directory,manifest)

    def admission_fixture(self):
        def entry(raw):return ['100644',r.h.git_hash('blob',raw)]
        def tree(entries):return b''.join((mode+' blob '+oid+'\t'+path).encode()+b'\0' for path,(mode,oid) in sorted(entries.items()))
        def commit(entries,parents,message):
            raw=('tree '+r.h.tree_hash(entries)+'\n'+''.join('parent '+p+'\n' for p in parents)+'author Test <test@example.invalid> 0 +0000\ncommitter Test <test@example.invalid> 0 +0000\n\n'+message+'\n').encode()
            return r.h.git_hash('commit',raw),raw
        common_bodies={p:b'o'+str(i).encode() for i,p in enumerate(list(r.FIXED_IMPORT_BLOBS)+['p'+str(i) for i in range(6)]+['stable'])}
        common={p:entry(raw) for p,raw in common_bodies.items()}
        tooling={p:b'frozen '+p.encode() for p in set(r.PATHS+r.CENSUS_PATHS)}
        additions={**tooling,**{'r'+str(i):b'r'+str(i).encode() for i in range(20)}}
        renderer=common|{p:entry(raw) for p,raw in additions.items()}
        imports={p:b'i'+str(i).encode() for i,p in enumerate(common) if p!='stable'}|{('main/0' if i==0 else 'm'+str(i)):b'n'+str(i).encode() for i in range(73)}
        main=common|{p:entry(raw) for p,raw in imports.items()}
        merged=main|{p:entry(raw) for p,raw in additions.items()}
        common_id,common_raw=commit(common,[],'common')
        renderer_id,renderer_raw=commit(renderer,[r.PARENT],'renderer')
        main_id,main_raw=commit(main,[common_id],'main')
        merge_id,merge_raw=commit(merged,[renderer_id,main_id],'accepted merge')
        base_bodies=common_bodies|{p:raw for p,raw in additions.items() if p not in tooling}
        base={p:('100644',raw) for p,raw in base_bodies.items()}
        base_entries={p:entry(raw) for p,raw in base_bodies.items()}
        base_id,base_raw=commit(base_entries,[],'frozen product')
        tooling['tools/renderer-floor-profile/run.py']=b'current reader'
        preceding=merged|{p:entry(raw) for p,raw in tooling.items()}
        preceding_id,preceding_raw=commit(preceding,[merge_id],'ordinary renderer followup')
        fixed_bodies={p:b'utf8'+str(i).encode() for i,p in enumerate(r.FIXED_IMPORT_BLOBS)}
        old={p:merged[p] for p in fixed_bodies};new={p:entry(raw) for p,raw in fixed_bodies.items()}
        origin_parent_id,origin_parent_raw=commit(merged,[main_id],'fixed origin parent')
        origin=merged|new
        origin_id,origin_raw=commit(origin,[origin_parent_id],'fixed origin')
        final=preceding|new
        head,head_raw=commit(final,[preceding_id],'fixed import')
        fixed={'parent':origin_parent_id,'origin':origin_id,'parent_tree':r.h.tree_hash(merged),
               'origin_tree':r.h.tree_hash(origin),'preceding':preceding_id,'applied':head,'applied_tree':r.h.tree_hash(final)}
        fixed_blobs={p:(old[p][1],new[p][1]) for p in old}
        anchors={'common':common_id,'renderer':renderer_id,'main':main_id,'merge':merge_id}
        frames={name+'.tree':tree(entries) for name,entries in [('common',common),('renderer',renderer),('main',main),('merge',merged),('head',final)]}
        frames.update({name+'.commit':raw for name,raw in [('common',common_raw),('renderer',renderer_raw),('main',main_raw),('merge',merge_raw),('base',base_raw),('head',head_raw)]})
        frames.update({'ancestry/'+oid+'.commit':raw for oid,raw in [(renderer_id,renderer_raw),(merge_id,merge_raw),(preceding_id,preceding_raw),(head,head_raw)]})
        frames['tail/'+preceding_id+'.tree']=tree(preceding)
        frames['tail/'+head+'.tree']=tree(final);frames['paths']='\n'.join(sorted(set(imports)|set(r.CENSUS_PATHS)|set(fixed_blobs))).encode()
        frames.update({'fixed-import/parent.commit':origin_parent_raw,'fixed-import/parent.tree':tree(merged),
                       'fixed-import/origin.commit':origin_raw,'fixed-import/origin.tree':tree(origin)})
        frames.update({'fixed-import/bodies/'+p:raw for p,raw in fixed_bodies.items()})
        bodies=base_bodies|imports|tooling|fixed_bodies
        current={p:{'sha256':r.digest(raw),'mode':0o644} for p,raw in bodies.items()}
        m={'head':head,'base':base_id,'paths':r.CENSUS_PATHS,'generation_ancestry':[renderer_id,merge_id,preceding_id,head],'source_admission':r.LEGACY_SOURCE_ADMISSION}
        patches=[patch.object(r,'FIXED_IMPORT',fixed),patch.object(r,'FIXED_IMPORT_BLOBS',fixed_blobs),patch.object(r,'ACCEPTED_MAIN',anchors),patch.object(r,'ACCEPTED_MERGE_TREE',r.h.tree_hash(merged)),patch.object(r,'BASE',base_id),patch.object(r,'BASE_TREE',r.h.tree_hash(base_entries))]
        return (m,frames,base,tooling,imports,current),patches,tree,commit

    def current_admission_fixture(self):
        args,patches,tree,commit=self.admission_fixture()
        m,frames,base,tooling,imports,current=args
        preceding=m['head'];previous=r.source_tree(frames['head.tree'])
        renderer=set(r.source_tree(frames['renderer.tree']))-set(r.source_tree(frames['common.tree']))
        bodies={p:b'current '+p.encode() for p in ['p'+str(i) for i in range(6)]+['stable']+['current/'+str(i) for i in range(21)]}
        entries={p:['100644',r.h.git_hash('blob',raw)] for p,raw in bodies.items()}
        applied_entries=previous|entries
        origin={p:row for p,row in applied_entries.items() if p not in renderer}
        parents=[m['generation_ancestry'][1],preceding]
        origin_id,origin_raw=commit(origin,parents,'fixed current main')
        applied,applied_raw=commit(applied_entries,[preceding],'preserve current main')
        tooling['tools/renderer-floor-profile/run.py']=b'admission reader'
        final=applied_entries|{p:['100644',r.h.git_hash('blob',raw)] for p,raw in tooling.items()}
        head,head_raw=commit(final,[applied],'current main admission')
        frames.update({'current-import/origin.commit':origin_raw,'current-import/origin.tree':tree(origin)})
        frames.update({'current-import/bodies/'+p:raw for p,raw in bodies.items()})
        for revision,raw,rows in ((applied,applied_raw,applied_entries),(head,head_raw,final)):
            frames['ancestry/'+revision+'.commit']=raw;frames['tail/'+revision+'.tree']=tree(rows)
        frames['head.commit']=head_raw;frames['head.tree']=tree(final)
        frames['paths']='\n'.join(sorted(set(imports)|set(r.CENSUS_PATHS)|set(r.FIXED_IMPORT_BLOBS)|set(entries))).encode()
        m.update(head=head,generation_ancestry=m['generation_ancestry']+[applied,head],source_admission=r.SOURCE_ADMISSION)
        current.update({p:{'sha256':r.digest(raw),'mode':0o644} for p,raw in (bodies|tooling).items()})
        fixed={'origin':origin_id,'origin_tree':r.h.tree_hash(origin),'origin_parents':parents,
               'preceding':preceding,'applied':applied,'applied_tree':r.h.tree_hash(applied_entries)}
        patches+=[patch.object(r,'CURRENT_IMPORT',fixed),patch.object(r,'CURRENT_IMPORT_ENTRIES',entries)]
        return args,patches,tree,commit

    def test_current_main_admission_preserves_both_import_generations(self):
        args,patches,_,_=self.current_admission_fixture()
        with ExitStack() as stack:
            for context in patches:stack.enter_context(context)
            entries=r.verify_source_data(*args)
            self.assertEqual(set(entries),set(args[-1]))
            self.assertEqual(len(set(r.CURRENT_IMPORT_ENTRIES)&set(args[4])),6)
            self.assertEqual(len(set(r.CURRENT_IMPORT_ENTRIES)-set(args[2])-set(args[4])),21)
            self.assertEqual(len(args[1]['paths'].splitlines()),108)
            old=args[4]['p0'];new=args[1]['current-import/bodies/p0']
            self.assertNotEqual(old,new)
            self.assertEqual(entries['p0'][1],r.h.git_hash('blob',new))
            ordinary=copy.deepcopy(args);ordinary[0]['paths']=r.PATHS
            ordinary[1]['paths']='\n'.join(sorted(set(args[4])|set(r.PATHS+r.CENSUS_PATHS)|set(r.FIXED_IMPORT_BLOBS)|set(r.CURRENT_IMPORT_ENTRIES))).encode()
            self.assertEqual(len(ordinary[1]['paths'].splitlines()),111)
            self.assertEqual(r.verify_source_data(*ordinary),entries)

    def test_current_main_admission_rejects_frame_and_body_drift(self):
        args,patches,_,_=self.current_admission_fixture()
        with ExitStack() as stack:
            for context in patches:stack.enter_context(context)
            r.verify_source_data(*args)
            for name in r.current_import_frames():
                for kind in ('missing','tamper','duplicate'):
                    bad=copy.deepcopy(args)
                    if kind=='missing':del bad[1][name]
                    elif kind=='tamper':bad[1][name]+=b'corrupt'
                    else:bad[1][name]+=bad[1][name]
                    with self.subTest(frame=name,kind=kind),self.assertRaises((ValueError,KeyError,UnicodeError)):r.verify_source_data(*bad)
            for name in ('current-import/extra.tree','current-import/bodies/extra'):
                bad=copy.deepcopy(args);bad[1][name]=b'extra'
                with self.assertRaisesRegex(ValueError,'closed complete source frame'):r.verify_source_data(*bad)
            for tag in (r.LEGACY_SOURCE_ADMISSION,None,'floating-main'):
                bad=copy.deepcopy(args);bad[0]['source_admission']=tag
                with self.assertRaises(ValueError):r.verify_source_data(*bad)
            for path in ('p0','stable','current/0'):
                bad=copy.deepcopy(args);bad[1]['paths']=b'\n'.join(p for p in bad[1]['paths'].splitlines() if p!=path.encode())
                with self.assertRaisesRegex(ValueError,'complete acquired source delta'):r.verify_source_data(*bad)

    def test_current_main_admission_rejects_import_transition_drift(self):
        args,patches,tree,commit=self.current_admission_fixture()
        with ExitStack() as stack:
            for context in patches:stack.enter_context(context)
            r.verify_source_data(*args)
            original=r.CURRENT_IMPORT['applied'];preceding=r.CURRENT_IMPORT['preceding']
            previous=r.source_tree(args[1]['tail/'+preceding+'.tree'])
            legal=r.source_tree(args[1]['tail/'+original+'.tree'])
            for kind in ('mode','rollback','deletion','renderer-loss','extra','inverse','wrong-parent','second-parent','omitted'):
                entries=copy.deepcopy(legal);parents=[preceding]
                if kind=='mode':entries['p0'][0]='100755'
                elif kind=='rollback':entries['p0']=previous['p0']
                elif kind=='deletion':del entries['main/0']
                elif kind=='renderer-loss':del entries['r0']
                elif kind=='extra':entries['unexpected']=['100644',r.h.git_hash('blob',b'extra')]
                elif kind=='inverse':entries['stable']=previous['stable']
                elif kind=='wrong-parent':parents=[r.PARENT]
                elif kind=='second-parent':parents.append(r.CURRENT_IMPORT['origin'])
                else:entries=previous
                revision,raw=commit(entries,parents,kind)
                frames=copy.deepcopy(args[1]);frames['ancestry/'+preceding+'.commit']=args[1]['ancestry/'+preceding+'.commit']
                with patch.dict(r.CURRENT_IMPORT,applied=revision,applied_tree=r.h.tree_hash(entries)):
                    with self.subTest(kind=kind),self.assertRaises(ValueError):r.verify_current_transition(frames,raw,previous,entries,set(r.source_tree(frames['renderer.tree']))-set(r.source_tree(frames['common.tree'])))
            for kind in ('omitted','duplicate','ordinary-extra'):
                bad=copy.deepcopy(args);m,frames=bad[:2]
                if kind=='omitted':m['generation_ancestry'].remove(original)
                elif kind=='duplicate':m['generation_ancestry'].insert(-1,original)
                else:
                    entries=r.source_tree(frames['head.tree']);entries['stable']=['100644',r.h.git_hash('blob',b'wrong')]
                    head,raw=commit(entries,[m['head']],'forbidden ordinary tail')
                    m['generation_ancestry'].append(head);m['head']=head
                    frames['ancestry/'+head+'.commit']=raw;frames['tail/'+head+'.tree']=tree(entries)
                    frames['head.commit']=raw;frames['head.tree']=tree(entries)
                with self.subTest(kind=kind),self.assertRaises((ValueError,KeyError)):r.verify_source_data(*bad)

    def test_current_main_admission_keeps_existing_history_bound(self):
        args,patches,tree,commit=self.current_admission_fixture()
        with ExitStack() as stack:
            for context in patches:stack.enter_context(context)
            entries=r.verify_source_data(*args);m,frames=args[:2]
            for ordinal in range(33-len(m['generation_ancestry'])):
                head,raw=commit(entries,[m['head']],'bounded current tail '+str(ordinal))
                m['generation_ancestry'].append(head);m['head']=head
                frames['ancestry/'+head+'.commit']=raw;frames['tail/'+head+'.tree']=tree(entries)
                frames['head.commit']=raw;frames['head.tree']=tree(entries)
            self.assertEqual(len(m['generation_ancestry']),33)
            self.assertEqual(r.verify_source_data(*args),entries)
            m['generation_ancestry'].append('f'*40);m['head']='f'*40
            with self.assertRaisesRegex(ValueError,'bounded ordinary'):r.verify_source_data(*args)

    def test_source_admission_authenticates_full_union_and_current_bodies(self):
        args,patches,_,_=self.admission_fixture()
        with ExitStack() as stack:
            for context in patches:stack.enter_context(context)
            result=r.verify_source_data(*args)
            self.assertEqual(set(result),set(args[-1]))
            for index in (2,3,4,5):
                for kind in ('missing','extra','changed'):
                    bad=copy.deepcopy(args);mapping=bad[index];key=next(iter(mapping))
                    if kind=='missing':del mapping[key]
                    elif kind=='extra':mapping['unexpected']=copy.deepcopy(mapping[key])
                    elif index==2:mapping[key]=('100755',mapping[key][1])
                    elif index==5:mapping[key]['mode']=0o755
                    else:mapping[key]+=b'corrupt'
                    with self.subTest(index=index,kind=kind),self.assertRaises((ValueError,KeyError)):r.verify_source_data(*bad)

    def test_source_admission_rejects_frames_tags_and_ancestry_drift(self):
        args,patches,_,_=self.admission_fixture()
        with ExitStack() as stack:
            for context in patches:stack.enter_context(context)
            r.verify_source_data(*args)
            for name in args[1]:
                for kind in ('missing','corrupt','duplicate'):
                    bad=copy.deepcopy(args)
                    if kind=='missing':del bad[1][name]
                    elif kind=='corrupt':bad[1][name]+=b'corrupt'
                    else:bad[1][name]+=bad[1][name]
                    with self.subTest(frame=name,kind=kind),self.assertRaises((ValueError,KeyError,UnicodeError)):r.verify_source_data(*bad)
            for tag in (None,'unknown',{},True):
                bad=copy.deepcopy(args);bad[0]['source_admission']=tag
                with self.subTest(tag=tag),self.assertRaises(ValueError):r.verify_source_data(*bad)
            bad=copy.deepcopy(args);bad[1]['unexplained.tree']=bad[1]['main.tree']
            with self.assertRaisesRegex(ValueError,'closed complete source frame'):r.verify_source_data(*bad)
            chain=args[0]['generation_ancestry']
            for ancestry in ([],chain[::-1],chain+chain,chain[1:],chain*6):
                bad=copy.deepcopy(args);bad[0]['generation_ancestry']=ancestry
                with self.subTest(ancestry=ancestry),self.assertRaises((ValueError,KeyError)):r.verify_source_data(*bad)

    def test_source_admission_rejects_unapproved_tail_and_non_single_parent(self):
        args,patches,tree,commit=self.admission_fixture()
        with ExitStack() as stack:
            for context in patches:stack.enter_context(context)
            legal=r.verify_source_data(*args)
            for kind in ('unapproved','second-parent','wrong-parent','deleted','mode'):
                bad=copy.deepcopy(args);m,frames=bad[:2];entries=copy.deepcopy(legal);merge=r.ACCEPTED_MAIN['merge'];parents=[merge]
                if kind=='unapproved':entries['main/0']=['100644',r.h.git_hash('blob',b'wrong')]
                elif kind=='second-parent':parents.append(r.ACCEPTED_MAIN['main'])
                elif kind=='wrong-parent':parents=[r.PARENT]
                elif kind=='deleted':del entries['main/0']
                else:entries['main/0'][0]='100755'
                head,raw=commit(entries,parents,kind);m['generation_ancestry'][-1]=head;m['head']=head
                frames['ancestry/'+head+'.commit']=raw;frames['tail/'+head+'.tree']=tree(entries)
                frames['head.commit']=raw;frames['head.tree']=tree(entries)
                with self.subTest(kind=kind),self.assertRaises(ValueError):r.verify_source_data(*bad)

    def test_source_history_counts_fixed_merge_separately(self):
        args,patches,tree,commit=self.admission_fixture()
        with ExitStack() as stack:
            for context in patches:stack.enter_context(context)
            entries=r.verify_source_data(*args)
            m,frames=args[:2]
            for ordinal in range(29):
                head,raw=commit(entries,[m['head']],'ordinary '+str(ordinal))
                m['generation_ancestry'].append(head);m['head']=head
                frames['ancestry/'+head+'.commit']=raw;frames['tail/'+head+'.tree']=tree(entries)
                frames['head.commit']=raw;frames['head.tree']=tree(entries)
            self.assertEqual(len(m['generation_ancestry']),33)
            self.assertEqual(r.verify_source_data(*args),entries)
            head,raw=commit(entries,[m['head']],'ordinary thirty-three')
            bad=copy.deepcopy(args);bad[0]['generation_ancestry'].append(head);bad[0]['head']=head
            bad[1]['ancestry/'+head+'.commit']=raw;bad[1]['tail/'+head+'.tree']=tree(entries)
            bad[1]['head.commit']=raw;bad[1]['head.tree']=tree(entries)
            with self.assertRaisesRegex(ValueError,'bounded ordinary'):r.verify_source_data(*bad)
            for chain in (m['generation_ancestry'][1:],m['generation_ancestry'][::-1],
                          [p for p in m['generation_ancestry'] if p!=r.ACCEPTED_MAIN['merge']],
                          m['generation_ancestry'][:-1]+[r.ACCEPTED_MAIN['merge']]):
                bad=copy.deepcopy(args);bad[0]['generation_ancestry']=chain
                with self.assertRaises((ValueError,KeyError)):r.verify_source_data(*bad)
            for parents in ([r.ACCEPTED_MAIN['main'],r.ACCEPTED_MAIN['renderer']],
                            [r.ACCEPTED_MAIN['renderer'],r.ACCEPTED_MAIN['main'],r.PARENT],
                            [r.ACCEPTED_MAIN['renderer'],r.PARENT]):
                with self.assertRaises(ValueError):r.source_commit(frames['merge.commit'],r.ACCEPTED_MAIN['merge'],parents=parents)
        chain=[];commits={};parent=r.PARENT
        for ordinal in range(17):
            head,raw=commit(entries,[parent],'legacy '+str(ordinal));chain.append(head);commits[head]=raw;parent=head
        r.source_ancestry({'generation_ancestry':chain[:16],'head':chain[15]},commits)
        with self.assertRaisesRegex(ValueError,'bounded ordinary'):r.source_ancestry({'generation_ancestry':chain,'head':head},commits)

    def test_fixed_import_requires_exact_three_path_overlay(self):
        args,patches,tree,commit=self.admission_fixture()
        with ExitStack() as stack:
            for context in patches:stack.enter_context(context)
            legal=r.verify_source_data(*args);m,frames=args[:2]
            preceding=r.source_tree(frames['tail/'+r.FIXED_IMPORT['preceding']+'.tree'])
            for kind in ('missing','extra','content','mode','reverse'):
                bad=copy.deepcopy(args);bm,bf=bad[:2];entries=copy.deepcopy(legal);path=next(iter(r.FIXED_IMPORT_BLOBS))
                if kind=='missing':entries[path]=preceding[path]
                elif kind=='extra':entries['unexpected']=['100644',r.h.git_hash('blob',b'extra')]
                elif kind=='content':entries[path]=['100644',r.h.git_hash('blob',b'wrong')]
                elif kind=='mode':entries[path][0]='100755'
                else:entries=copy.deepcopy(preceding)
                head,raw=commit(entries,[r.FIXED_IMPORT['preceding']],kind)
                old=bm['head'];bm['head']=head;bm['generation_ancestry'][-1]=head
                del bf['ancestry/'+old+'.commit'];del bf['tail/'+old+'.tree']
                bf['ancestry/'+head+'.commit']=raw;bf['tail/'+head+'.tree']=tree(entries)
                bf['head.commit']=raw;bf['head.tree']=tree(entries)
                with patch.dict(r.FIXED_IMPORT,applied=head,applied_tree=r.h.tree_hash(entries)):
                    with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'exact fixed import overlay'):r.verify_source_data(*bad)
            for chain in (m['generation_ancestry']+[m['head']],m['generation_ancestry'][:-2]+m['generation_ancestry'][-2:][::-1]):
                bad=copy.deepcopy(args);bad[0]['generation_ancestry']=chain
                with self.assertRaises(ValueError):r.verify_source_data(*bad)

    def test_34_selected_range_capacity_preserves_byte_caps(self):
        raw,mapping,rows,_=code_fixture()
        for count in (128,129):
            changed=bytearray(raw)+bytearray(2048)
            struct.pack_into('<II',changed,288,0x2000,count*12)
            struct.pack_into('<IIII',changed,440,count*12,0x2000,count*12,1280)
            mapping=b' Preferred load address is 0000000140000000\n'
            for i in range(count):
                struct.pack_into('<III',changed,1280+i*12,0x1000+i,0x1001+i,0x3000)
                mapping+=f' 0001:{i:08x} floor_profile_{i} {0x140001000+i:016x} f object.obj\n'.encode()
            if count==128:self.assertEqual(len(r.code_ranges(bytes(changed),rows,mapping)['ranges']),128)
            else:
                with self.assertRaisesRegex(ValueError,'small bounded operation code regions'):r.code_ranges(bytes(changed),rows,mapping)
        for spans in ([(1,131074)],[(i*131072,(i+1)*131072) for i in range(5)]):
            mapping=b' Preferred load address is 0000000140000000\n'+b''.join(f' 0001:00000000 floor_profile_{i} {0x140000000+a:016x} f object.obj\n'.encode() for i,(a,b) in enumerate(spans))
            with patch.object(r,'pe_code',return_value=(0x140000000,[],spans,None)),self.assertRaisesRegex(ValueError,'small bounded operation code regions'):
                r.code_ranges(b'',[],mapping)

    def test_35_retained_tool_bytes_follow_real_record_identity(self):
        directory=Path('/synthetic-tool-retention');tool_path=Path(str(r.DISASSEMBLER));raw=b'tool data'
        files={tool_path:raw}
        with patch.object(Path,'read_bytes',lambda p:files[p]),patch.object(Path,'write_bytes',lambda p,v:files.__setitem__(p,v)),patch.object(r.previous,'record',return_value={'env':{},'status':0}),patch.object(r,'write_json'):
            receipt=r.record(directory,'instruction-help',[str(r.DISASSEMBLER),'--help'],'source',{})
            self.assertEqual(files[directory/'instruction-tool.bin'],raw)
            self.assertEqual(receipt['tool_binary'],{'path':str(r.DISASSEMBLER),'sha256':r.digest(raw),'size':len(raw)})
            files[directory/'instruction-tool.bin']=b'changed'
            with self.assertRaisesRegex(ValueError,'retained hosted instruction tool changed'):
                r.record(directory,'rust-instructions-0',[str(r.DISASSEMBLER)],'source',{})

    def producer_receipts(self,failure):
        tree=ast.parse(Path(r.__file__).read_bytes());run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
        outer=next(n for n in run.body if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='opt');loop=outer.body[0]
        producer=next(n for n in loop.body if isinstance(n,ast.Try)).body
        start=next(i for i,n in enumerate(producer) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=='write_bytes')
        tail=run.body[run.body.index(outer)+1:]
        class ReturnAsExpression(ast.NodeTransformer):
            def visit_Return(self,node):return ast.copy_location(ast.Expr(node.value),node)
        block=compile(ast.fix_missing_locations(ReturnAsExpression().visit(ast.Module(body=producer[start:]+tail,type_ignores=[]))),str(r.__file__),'exec')
        directory=Path('/evidence/observed-Od');out=directory.parent;prior={'id':'control-Od','retained':'prior receipt'}
        state=dict(r.__dict__,census_mode=False,id='observed-Od',variant='observed',opt='Od',source=Path('/source'),target=Path('/target'),directory=directory,commands={n:[n] for n in ('native','rust','mesh_dump','x_files')},patches={'known':'patch'},expected={'known':'source'},actual=['compiler argv'],native_target=Path('/native'),executable='/rust.exe',parsed={'observed-O2':({}, {})},out=out,m={'builds':[copy.deepcopy(prior)]},r={},e={},head='synthetic-head')
        state['env']={}
        files={};retained=[];calls=[];parses=[];acquisitions=[];finalizations=[]
        def read(path):return files.get(path,b'compiled image')
        def write(path,raw):files[path]=raw;return len(raw)
        def save(path,value):files[path]=copy.deepcopy(value);retained.append((path,copy.deepcopy(value)))
        def record(directory,label,*args):
            calls.append(label)
            self.assertEqual(files[out/'manifest.json']['builds'][0],prior)
            self.assertEqual(files[out/'manifest.json']['builds'][1]['runtime_corpus']['created_ns'],123)
            if failure==label+'-exception':raise OSError(label+' launch failed')
            return {'status':1 if failure==label+'-nonzero' else 0}
        def parse(raw,language,observed):
            parses.append(language)
            if failure==language+'-parse':return r.parse(b'',language,observed)
            return {'dll':{'path':'/dll'}} if language=='native' else {}
        def acquire(*args):
            acquisitions.append(True)
            row=files[out/'manifest.json']['builds'][1]
            self.assertIn('after',row);self.assertIn('objects',row)
            self.assertEqual(set(row['binaries']),{'floor_profile.exe','rust-profile.exe','d3dx9_43.dll'})
            self.assertNotIn('compiled_capture',row)
            if failure=='llvm':raise ValueError('acquisition failed')
            if failure in ('budget','unknown'):
                raw,mapping,rows,_=code_fixture();view=r.required_code_ranges(raw,rows,mapping)
                view['copy_obligations']=copy.deepcopy(r.COPY_OBLIGATIONS)
                view['data_requests']=[{'role':'SeedTable','size':8192,'resolution':'Resolved'}]
                for span in view['ranges']:
                    for edge in r.instruction_edges(instructions(span),view,span):
                        r.follow_required_edge(None,[{'witness':view,'raw':raw}],0,span,edge);view['edges'].append(edge)
                view['decoded']=view['pending'];view['pending']=[]
                if failure=='budget':view['ranges']*=65
                else:view['edges'][0]['obligation']='Unresolved'
                try:r.complete_closure([{'witness':view,'raw':raw}])
                finally:save(directory/'rust-code-progress.json',{'schema':r.SCHEMA,'images':[{'witness':view}]})
            return {'native':{},'rust':{}}
        def finish(out,manifest,env):
            self.assertIs(out,state['out']);self.assertIs(manifest,state['m']);self.assertIs(env,state['env'])
            self.assertEqual(manifest['builds'][0],prior)
            row=manifest['builds'][1]
            self.assertEqual(row['after'],state['expected'])
            self.assertEqual(set(row['objects']),{'core/accessory.obj','console/native.obj'})
            self.assertEqual(row['compiled_capture'],{'native':{},'rust':{}})
            self.assertEqual(state['parsed'],{'observed-O2':({}, {}),'observed-Od':({'dll':{'path':'/dll'}},{})})
            self.assertNotIn(out/'result.json',files);self.assertNotIn(out/'seal.json',files)
            finalizations.append(True)
        state.update(record=record,parse=parse,write_json=save,compiled_evidence=acquire,finish_source_admission=finish,fixture_result=lambda *args:None,classify=lambda *args:{},replay=lambda *args:{})
        with patch.object(Path,'read_bytes',read),patch.object(Path,'write_bytes',write),patch.object(Path,'mkdir'),patch.object(Path,'rglob',return_value=[Path('/native/core/accessory.obj'),Path('/native/console/native.obj')]),patch.object(r.shutil,'copyfile',lambda source,target:write(target,read(source))),patch.object(r.c,'source_inventory',return_value=state['expected']),patch.object(r.previous.time,'time_ns',side_effect=[123]),patch.object(r.previous,'evidence_inventory',return_value={}):
            if failure:
                with self.assertRaises((OSError,ValueError)):exec(block,state)
            else:exec(block,state)
        self.assertEqual(finalizations,[] if failure else [True])
        manifests=[value for path,value in retained if path==out/'manifest.json']
        self.assertEqual(files[directory/'operations.bin'],r.operation_corpus())
        self.assertEqual(len(manifests[0]['builds']),2);self.assertEqual(manifests[0]['builds'][0],prior)
        partial=manifests[0]['builds'][1]
        self.assertEqual(partial['runtime_corpus'],{'sha256':r.digest(r.operation_corpus()),'size':152,'created_ns':123})
        self.assertEqual(set(partial['binaries']),{'floor_profile.exe','rust-profile.exe'})
        for field in ('after','objects','compiled_capture'):self.assertNotIn(field,partial)
        for value in manifests:
            self.assertEqual(len(value['builds']),2);self.assertEqual(value['builds'][0],prior)
            self.assertEqual(value['builds'][1]['runtime_corpus'],partial['runtime_corpus'])
        if failure:
            self.assertNotIn('observed-Od',state['parsed'])
            self.assertNotIn(out/'result.json',files);self.assertNotIn(out/'seal.json',files)
            self.assertNotIn('compiled_capture',manifests[-1]['builds'][1])
        else:
            self.assertIn('observed-Od',state['parsed'])
            self.assertEqual(manifests[-1]['builds'][1]['compiled_capture'],{'native':{},'rust':{}})
            self.assertIn(out/'result.json',files);self.assertIn(out/'seal.json',files)
        return manifests,calls,parses,acquisitions

    def test_36_build_row_survives_optional_acquisition_failure(self):
        for failure in ('llvm','budget','unknown',None):
            with self.subTest(failure=failure):
                manifests,calls,parses,acquisitions=self.producer_receipts(failure)
                self.assertEqual(len(manifests),2 if failure else 3)
                self.assertEqual(calls,['native','rust','mesh_dump','x_files'])
                self.assertEqual(parses,['native','rust']);self.assertEqual(acquisitions,[True])

    def test_47_early_runtime_failure_preserves_partial_receipts(self):
        for failure in ('native-nonzero','native-exception','native-parse','rust-nonzero','rust-exception','rust-parse'):
            with self.subTest(failure=failure):
                manifests,calls,parses,acquisitions=self.producer_receipts(failure)
                self.assertEqual(len(manifests),1);self.assertEqual(acquisitions,[])
                self.assertEqual(calls,['native','rust'] if failure.startswith('rust') else ['native'])
                self.assertEqual(parses,(['native','rust'] if failure=='rust-parse' else ['native']) if failure.startswith('rust') else (['native'] if failure=='native-parse' else []))

    def test_37_leaf_candidate_and_signed_import_thunk(self):
        raw,mapping,rows,_=code_fixture();changed=bytearray(raw)
        struct.pack_into('<II',changed,288,0,0)
        mapping+=b' 0001:00000008 next_leaf 0000000140001008 f object.obj\n'
        with self.assertRaisesRegex(ValueError,'exception-directory boundary'):r.required_code_ranges(bytes(changed),rows,mapping)
        extent,kind=r.range_extent(bytes(changed),0x1001,r.map_symbols(mapping,0x140000000,r.pe_code(bytes(changed))[1]),True)
        self.assertEqual(r.range_extent(bytes(changed),0x1001,r.map_symbols(mapping,0x140000000,r.pe_code(bytes(changed))[1]),True)[1],'NextDistinctExecutableSymbolCandidateOnly')
        self.assertEqual(extent[1],0x1008)
        for bad in (mapping.splitlines()[0]+b'\n',mapping.replace(b'140001008',b'140003008')):
            with self.assertRaises(ValueError):r.required_code_ranges(bytes(changed),rows,bad)
        changed[1024:1030]=b'\xff\x25'+struct.pack('<i',-14)
        extent,kind=r.range_extent(bytes(changed),0x1000,[])
        self.assertEqual((extent,kind),((0x1000,0x1006),'ImportThunkSixBytes'))
        view={'preferred_base':0x140000000};span=r.pe_code(bytes(changed))[3](*extent,True)
        text=b'140001000: ff 25 f2 ff ff ff jmpq *-14(%rip)\n'
        edge=r.instruction_edges(text,view,span)[0]
        self.assertEqual(edge['target'],{'kind':'RipRelativeIatSlot','slot_rva':0xff8})
        changed[1026:1030]=struct.pack('<i',-0x2000);span=r.pe_code(bytes(changed))[3](*extent,True)
        with self.assertRaisesRegex(ValueError,'signed FF25'):r.instruction_edges(b'140001000: ff 25 00 e0 ff ff jmpq *-8192(%rip)\n',view,span)

    def test_38_exact_required_branch_and_unknown_indirect(self):
        raw,mapping,rows,_=code_fixture();changed=bytearray(raw)
        changed[1024:1032]=b'\xe8\x03\x00\x00\x00\xff\xe0\xc3'
        witness=r.required_code_ranges(bytes(changed),rows,mapping)
        assembly=b'140001000: e8 03 00 00 00 callq 0x140001008\n140001005: ff e0 jmpq *%rax\n140001007: c3 retq\n'
        edges=r.instruction_edges(assembly,witness,witness['ranges'][0])
        self.assertEqual([e['target']['kind'] for e in edges],['DirectRva','Unresolved','Return'])
        self.assertEqual(edges[0]['target']['rva'],0x1008)
        with self.assertRaisesRegex(ValueError,'required leaf'):r.request_range(witness,bytes(changed),0x1008,'RequiredCallOrBranch',{'kind':'RequiredTarget'})

    def test_39_aggregate_instruction_and_section_budget(self):
        raw,mapping,rows,_=code_fixture();view=r.required_code_ranges(raw,rows,mapping)
        r.closure_budget([view]*48)
        with self.assertRaisesRegex(ValueError,'PE section budget'):r.closure_budget([view]*49)
        many=dict(view,ranges=view['ranges'][:1]*128,sections=[])
        r.closure_budget([many])
        with self.assertRaisesRegex(ValueError,'small bounded'):r.closure_budget([many,dict(view,sections=[])])

    def test_40_own_process_import_and_loaded_code_baseline(self):
        raw,directory,files,parsed=runtime_fixture()
        with patch.object(Path,'read_bytes',lambda path:files[path]),patch.object(r,'checked',return_value=({'pid':123},b'',b'')):
            modules=r.runtime_images(directory,parsed,raw)
            self.assertEqual(len(modules),1)
            self.assertEqual(modules[0]['witness']['compiled_dataflow'],'UnprovedAwaitingIndependentReview')
            for name in ('process','slot','target','owner','code','headers','missing-section'):
                p=copy.deepcopy(parsed);f=dict(files)
                if name=='process':p['runtime_imports'][0]['process_id']=124
                elif name=='slot':p['runtime_imports'][0]['slots'][0]['slot_rva']+=8
                elif name=='target':p['runtime_imports'][0]['slots'][0]['target_va']+=1
                elif name=='owner':p['runtime_imports'][0]['slots'][0]['owner_base']+=0x10000
                else:
                    suffix={'code':'section-0.bin','headers':'headers.bin','missing-section':'section-1.bin'}[name]
                    key=directory/('runtime-pre-0-'+suffix)
                    if name=='missing-section':del f[key]
                    else:f[key]=b'x'+f[key][1:]
                with patch.object(Path,'read_bytes',lambda path:f[path]),self.subTest(name=name),self.assertRaises((ValueError,KeyError)):
                    r.runtime_images(directory,p,raw)

    def test_48_loaded_header_base_is_bound_to_actual_owner(self):
        raw,_,_,_=runtime_fixture();preferred=r.pe_code(raw)[0];owner=preferred+0x10000000
        headers=bytearray(raw[:1024]);struct.pack_into('<Q',headers,176,owner)
        r.loaded_header_binding(raw,raw[:1024],preferred)
        r.loaded_header_binding(raw,bytes(headers),owner)
        self.assertEqual(r.pe_code(raw)[0],preferred)
        shifted=bytearray(raw);shifted[144:528]=raw[128:512];struct.pack_into('<I',shifted,60,144)
        loaded=bytearray(shifted[:1024]);struct.pack_into('<Q',loaded,192,owner)
        r.loaded_header_binding(bytes(shifted),bytes(loaded),owner)
        for name in ('preferred-in-loaded','wrong-base','wrong-owner','bool-owner','zero-owner','overflow-owner',
                     'wrong-slot','outside-byte','short','extra','magic','pe-bounds','optional-bounds','header-bounds'):
            file=bytearray(raw);loaded=bytearray(headers);actual=owner
            if name=='preferred-in-loaded':loaded=bytearray(raw[:1024])
            elif name=='wrong-base':struct.pack_into('<Q',loaded,176,owner+1)
            elif name=='wrong-owner':actual+=1
            elif name=='bool-owner':actual=True
            elif name=='zero-owner':actual=0
            elif name=='overflow-owner':actual=2**64
            elif name=='wrong-slot':loaded=bytearray(raw[:1024]);struct.pack_into('<Q',loaded,184,owner)
            elif name=='outside-byte':loaded[304]^=1
            elif name=='short':loaded=loaded[:-1]
            elif name=='extra':loaded+=b'\0'
            elif name=='magic':struct.pack_into('<H',file,152,0x10b)
            elif name=='pe-bounds':struct.pack_into('<I',file,60,len(file))
            elif name=='optional-bounds':struct.pack_into('<H',file,148,24)
            elif name=='header-bounds':struct.pack_into('<I',file,212,176)
            with self.subTest(name=name),self.assertRaises(ValueError):
                r.loaded_header_binding(bytes(file),bytes(loaded),actual)

    def test_49_rebased_runtime_images_use_file_preferred_relocations(self):
        raw,directory,_,parsed=runtime_fixture();changed=bytearray(raw);owner=0x150000000
        struct.pack_into('<H',changed,134,4)
        at=512;changed[at:at+8]=b'.reloc\0\0'
        struct.pack_into('<IIII',changed,at+8,12,0x4000,12,2048);struct.pack_into('<I',changed,at+36,0x40000040)
        struct.pack_into('<II',changed,152+112+5*8,0x4000,12)
        struct.pack_into('<IIHH',changed,2048,0x1000,12,0xa010,0)
        struct.pack_into('<Q',changed,1040,0x140005000);raw=bytes(changed);files={}
        for snapshot in parsed['runtime_imports']:
            phase=snapshot['phase'];slot=snapshot['slots'][0];slot.update(owner_base=owner,target_va=owner+0x1000)
            prefix=f'runtime-{phase}-0';headers=bytearray(raw[:1024]);struct.pack_into('<Q',headers,176,owner)
            files[directory/(prefix+'-module.bin')]=raw;files[directory/(prefix+'-headers.bin')]=bytes(headers)
            files[directory/(prefix+'-iat.bin')]=struct.pack('<Q',slot['target_va']);slot['sections']=[]
            for i,s in enumerate(r.pe_code(raw)[1]):
                loaded=bytearray(raw[s['offset']:s['offset']+s['size']])
                if i==0:struct.pack_into('<Q',loaded,16,owner+0x5000)
                files[directory/(prefix+f'-section-{i}.bin')]=bytes(loaded)
                slot['sections'].append([i,s['rva'],s['size'],s['flags']])
        with patch.object(Path,'read_bytes',lambda path:files[path]),patch.object(r,'checked',return_value=({'pid':123},b'',b'')):
            image=r.runtime_images(directory,parsed,raw)[0]
            self.assertEqual(image['witness']['preferred_base'],0x140000000)
            self.assertEqual(image['raw'],raw)
            self.assertEqual(image['pre']['runtime']['owner_base'],owner)
            self.assertEqual(image['post']['runtime']['owner_base'],owner)
            for phase in ('pre','post'):
                for suffix in ('headers.bin','section-0.bin'):
                    key=directory/(f'runtime-{phase}-0-'+suffix);original=files[key]
                    files[key]=original[:176]+raw[176:184]+original[184:] if suffix=='headers.bin' else raw[1024:1280]
                    with self.subTest(phase=phase,suffix=suffix),self.assertRaises(ValueError):
                        r.runtime_images(directory,parsed,raw)
                    files[key]=original

    def test_41_loaded_code_requires_exact_relocations(self):
        raw,_,_,_=runtime_fixture();changed=bytearray(raw)
        struct.pack_into('<II',changed,152+112+5*8,0x30c0,12)
        struct.pack_into('<IIHH',changed,1536+192,0x1000,12,0xa000,0)
        struct.pack_into('<Q',changed,1024,0x140005000)
        raw=bytes(changed);span=r.pe_code(raw)[3](0x1000,0x1008,True)
        relocated=r.relocated_code(raw,span,0x150000000)
        self.assertEqual(struct.unpack('<Q',relocated)[0],0x150005000)
        changed[1536+200:1536+202]=struct.pack('<H',0x3000)
        with self.assertRaisesRegex(ValueError,'DIR64'):r.relocated_code(bytes(changed),span,0x150000000)
        with self.assertRaisesRegex(ValueError,'relocation data required'):r.relocated_code(runtime_fixture()[0],span,0x150000000)

    def test_42_merge_return_requires_pointer_continuity(self):
        baseline=lineage();self.assertEqual(r.admit_lineage(baseline),baseline)
        grown=copy.deepcopy(baseline);grown['rows'][1][5:8]=[128,2,8];grown['returned'][:4]=[128,2,8,128]
        r.admit_lineage(grown)
        for name in ('same-values-other-destination','discontinuous-storage','missing-push','wrong-index','bad-offset'):
            changed=copy.deepcopy(baseline)
            if name=='same-values-other-destination':changed['returned'][3]+=32
            elif name=='discontinuous-storage':changed['rows'][1][0]+=32
            elif name=='missing-push':changed['rows'].pop()
            elif name=='wrong-index':changed['rows'][0][1]=1
            else:changed['returned'][5]=32
            with self.subTest(name=name),self.assertRaises(ValueError):r.admit_lineage(changed)

    def test_43_crt_export_candidate_is_not_function_size_proof(self):
        raw,_,_,_=runtime_fixture();changed=bytearray(raw);struct.pack_into('<II',changed,288,0,0)
        metadata,candidates=r.export_metadata(bytes(changed))
        extent,kind=r.range_extent(bytes(changed),0x1000,[],exports=candidates)
        self.assertEqual((extent,kind),((0x1000,0x1008),'ExportCandidateOnly'))
        self.assertEqual(candidates[0]['aliases'],['memcpy'])
        with self.assertRaisesRegex(ValueError,'export candidate'):r.range_extent(bytes(changed),0x1008,[],exports=candidates)
        struct.pack_into('<I',changed,1536+216,0x30f0)
        _,bad=r.export_metadata(bytes(changed))
        with self.assertRaises(ValueError):r.range_extent(bytes(changed),0x1000,[],exports=bad)

    def test_44_formatting_candidate_requires_caller_context(self):
        raw,mapping,rows,_=code_fixture();view=r.required_code_ranges(raw,rows,mapping)
        view['caller_windows']=[{'start_rva':0x1002,'end_rva':0x1004,'role':'ActualCallerInputThroughReturn','operation':0}]
        view['all_same_link_symbols'].append({'rva':0x1080,'symbol':'std2io5stdio6_print','object':'actual.obj'})
        edge={'instruction_rva':0x1001,'target':{'kind':'DirectRva','rva':0x1080},'text':'callq 0x140001080','obligation':'Required'}
        candidate=copy.deepcopy(edge);self.assertFalse(r.formatting_exclusion(candidate,view,view['ranges'][0]))
        self.assertEqual(candidate['obligation'],'Required')
        self.assertEqual(view['compiled_dataflow'],'UnprovedAwaitingIndependentReview')
        for name in ('inside','missing-window','non-formatting','indirect'):
            changed=copy.deepcopy(edge);v=copy.deepcopy(view)
            if name=='inside':changed['instruction_rva']=0x1003
            elif name=='missing-window':v['caller_windows']=[]
            elif name=='non-formatting':v['all_same_link_symbols'][-1]['symbol']='memcpy'
            else:changed['target']={'kind':'Unresolved'}
            with self.subTest(name=name):self.assertFalse(r.formatting_exclusion(changed,v,v['ranges'][0]))

    def test_45_required_loaded_dispatch_data_is_bound(self):
        raw,directory,files,parsed=runtime_fixture()
        for phase in ('pre','post'):
            path=directory/(f'runtime-{phase}-0-section-2.bin');data=bytearray(files[path]);struct.pack_into('<Q',data,0x60,0x140001000);files[path]=bytes(data)
        with patch.object(Path,'read_bytes',lambda path:files[path]),patch.object(r,'checked',return_value=({'pid':123},b'',b'')):
            image=r.runtime_images(directory,parsed,raw)[0]
            target,samples=r.loaded_dispatch_target(directory,image,0x3060)
            self.assertEqual(target,0x1000);self.assertEqual(len(samples),2)
            key=directory/'runtime-post-0-section-2.bin';original=files[key]
            files[key]=original[:0x60]+struct.pack('<Q',0x140001001)+original[0x68:]
            with self.assertRaisesRegex(ValueError,'retained loaded dispatch data'):r.loaded_dispatch_target(directory,image,0x3060)
            refreshed=r.runtime_images(directory,parsed,raw)[0]
            with self.assertRaisesRegex(ValueError,'changing sampled dispatch target'):r.loaded_dispatch_target(directory,refreshed,0x3060)
            files[key]=original
            with self.assertRaisesRegex(ValueError,'dispatch slot extent'):r.loaded_dispatch_target(directory,image,0x4000)

    def test_50_raw_witness_handoff_and_role_peers(self):
        legal=packet('rust');parsed=r.parse(wire(legal),'rust',True)
        self.assertEqual([op['witness']['role'] for op in parsed['operations']],
                         [r.WITNESS_ROLES[0],r.WITNESS_ROLES[1]]*2+[r.WITNESS_ROLES[2]])
        for name in ('old-schema','role','owner','ordinal','received-ordinal','pointer','length','sink','bytes',
                     'stale-handoff','base','missing-site','boolean','refreshed-extra-role','missing-sink','handoff-kind','handoff-ordinal','handoff-site','raw-sink-alias'):
            rows=copy.deepcopy(legal);row=next(v for v in rows if v['stage']=='witness')
            if name=='old-schema':row['schema']=0
            elif name=='role':row['role']=r.WITNESS_ROLES[1]
            elif name=='owner':row['owner'][0]=2
            elif name=='ordinal':row['ordinal']=1
            elif name=='received-ordinal':row['received_ordinal']=1
            elif name=='pointer':row['received'][0]+=4
            elif name=='length':row['received'][1]-=4
            elif name=='sink':row['received'][2]+=176
            elif name=='bytes':row['bytes'][0]^=1
            elif name=='stale-handoff':
                row['handoff'][0]+=4;row['received'][0]+=4
            elif name=='base':row['base']+=1
            elif name=='missing-site':row['sites'][2]=0
            elif name=='boolean':row['received'][0]=True
            elif name=='refreshed-extra-role':row['raw_sha256']=r.digest(bytes(row['bytes']))
            elif name=='handoff-kind':row['handoff_kind']=1
            elif name=='handoff-ordinal':row['handoff_ordinal']=1
            elif name=='handoff-site':row['handoff_sites'][0]=0
            elif name=='raw-sink-alias':row['handoff'][2]=row['received'][2]=row['handoff'][0]
            else:row['received'].pop()
            with self.subTest(name=name),self.assertRaises(ValueError):r.parse(wire(rows),'rust',True)
        refreshed=copy.deepcopy(legal)
        for row in refreshed:
            if row['stage']=='runtime-read':row['pointer']+=32
            if row['stage']=='witness' and row['owner'][0]==1:
                row['handoff'][0]+=32;row['received'][0]+=32
        r.parse(wire(refreshed),'rust',True)

    def test_51_collector_named_required_targets_are_retained(self):
        raw,mapping,rows,_=code_fixture();raw=bytearray(raw)
        struct.pack_into('<II',raw,288,0x2000,36);struct.pack_into('<IIII',raw,440,36,0x2000,36,1280)
        struct.pack_into('<III',raw,1292,0x1008,0x1010,0x3000)
        struct.pack_into('<III',raw,1304,0x1020,0x1028,0x3000)
        mapping+=b' 0001:00000008 floor_profile_runtime_imports_collector 0000000140001008 f object.obj\n'
        raw[1024:1032]=b'\xe8\x03\0\0\0\x90\x90\xc3';raw=bytes(raw)
        view=r.required_code_ranges(raw,rows,mapping);images=[{'witness':view,'raw':raw}]
        span=view['ranges'][0]
        assembly=b'140001000: e8 03 00 00 00 callq 0x140001008\n140001005: 90 nop\n140001006: 90 nop\n140001007: c3 retq\n'
        edge=r.instruction_edges(assembly,view,span)[0]
        view['caller_windows']=[{'start_rva':0x1000,'end_rva':0x1007}]
        self.assertFalse(r.formatting_exclusion(edge,view,span))
        r.follow_required_edge(None,images,0,span,edge)
        self.assertEqual(view['ranges'][-1]['start_rva'],0x1008)
        self.assertEqual(edge['resolution'],'Acquired')
        r.request_range(view,raw,0x1008,'RequiredReturn',{'kind':'RequiredTarget','instruction_rva':0x1005})
        self.assertEqual(len(view['ranges']),3)
        self.assertEqual(len([q for q in view['requests'] if q['target_rva']==0x1008]),2)
        denied=dict(edge,obligation='OutsideClaim')
        with self.assertRaisesRegex(ValueError,'unsupported edge waiver'):r.follow_required_edge(None,images,0,span,denied)
        self.assertEqual(edge['obligation'],'Required')

    def test_52_frontier_and_obligation_completion_is_strict(self):
        raw,mapping,rows,assembly=code_fixture();view=r.required_code_ranges(raw,rows,mapping)
        view['copy_obligations']=copy.deepcopy(r.COPY_OBLIGATIONS)
        view['data_requests']=[{'role':'SeedTable','size':8192,'resolution':'Resolved'}]
        view['edges']=[];images=[{'witness':view,'raw':raw}]
        for span in view['ranges']:
            for edge in r.instruction_edges(instructions(span),view,span):
                r.follow_required_edge(None,images,0,span,edge);view['edges'].append(edge)
        with self.assertRaisesRegex(ValueError,'pending'):r.complete_closure(images)
        view['decoded']=view['pending'];view['pending']=[];r.complete_closure(images)
        self.assertEqual(view['compiled_dataflow'],'UnprovedAwaitingIndependentReview')
        for name in ('pending','unknown-edge','unresolved-import','required-return','seed-copy','data','sink','range','missing-edge-resolution','missing-handoff-target'):
            peer=copy.deepcopy(images);v=peer[0]['witness']
            if name=='pending':v['pending']=[[0x1000,0x1008]]
            elif name in ('unknown-edge','unresolved-import'):v['edges'][0]['obligation']='Unresolved'
            elif name=='required-return':v['copy_obligations'].pop(0)
            elif name=='seed-copy':v['copy_obligations'].pop()
            elif name=='data':v['data_requests']=[]
            elif name=='sink':v['semantic_origins']=[]
            elif name=='range':v['requests'][0]['resolution']='Unresolved'
            elif name=='missing-edge-resolution':del v['edges'][0]['resolution']
            else:v['edges']=[e for e in v['edges'] if not e['text'].startswith('call')]
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'INCOMPLETE'):r.complete_closure(peer)
        import_raw=runtime_fixture()[0];v=copy.deepcopy(view);edge={'instruction_rva':0x1000,'obligation':'Required','target':{'kind':'RipRelativeIatSlot','slot_rva':0x3060}}
        r.follow_required_edge(None,[{'witness':v,'raw':import_raw}],0,v['ranges'][0],edge)
        self.assertEqual(edge['reason'],'MissingRequiredSameProcessImportTarget')
        self.assertEqual(v['data_requests'][-1]['resolution'],'Unresolved')

    def test_53_versioned_boundary_owner_is_not_a_name_waiver(self):
        raw,mapping,rows,_=code_fixture();r.required_code_ranges(raw,rows,mapping)
        for name in ('missing-role','wrong-role','wrong-owner','wrong-site','wrong-symbol','same-handoff-extent','wrong-handoff-owner'):
            peer=copy.deepcopy(rows);m=mapping
            if name=='missing-role':del peer[0]['witness']
            elif name=='wrong-role':peer[0]['witness']['role']='AcquisitionUtility'
            elif name=='wrong-owner':peer[0]['witness']['role']=r.WITNESS_ROLES[1]
            elif name=='wrong-site':peer[0]['witness']['sites'][2]=8192+0x2000
            elif name=='wrong-symbol':m=mapping.replace(b'direct_witness',b'runtime_imports')
            elif name=='same-handoff-extent':peer[0]['witness']['handoff_sites']=peer[0]['witness']['sites'][:2]
            else:m=mapping.replace(b'floor_profile_handoff',b'floor_profile_collector')
            with self.subTest(name=name),self.assertRaises((ValueError,KeyError)):r.required_code_ranges(raw,peer,m)

    def test_54_producer_and_default_reader_share_real_pure_boundaries(self):
        module,directory,files,runtime=runtime_fixture();own=bytearray(module)
        source=(r.ROOT/'rust/crates/mds-math/src/estimate_table.rs').read_text()
        table=b''.join(struct.pack('<I',int(v,16)) for v in r.re.findall(r'0x[0-9a-f]{8}',r.re.search(r'const RCP: \[u32; 2048\] = \[(.*?)\];',source,r.re.S)[1]))
        self.assertEqual(len(table),8192)
        struct.pack_into('<H',own,134,4);struct.pack_into('<II',own,152+56,0x8000,1024)
        at=512;own[at:at+8]=b'.seeds\0\0';struct.pack_into('<IIII',own,at+8,8192,0x5000,8192,4096);struct.pack_into('<I',own,at+36,0x40000040)
        own.extend(table);own=bytes(own)
        _,mapping,rows,_=code_fixture()
        for snap in runtime['runtime_imports']:snap['image_size']=0x8000
        runtime.update(operations=rows,merge_lineage=lineage());parsed=({'operations':rows},runtime)
        recipe=r.recipe('C:/runner/temp','observed','Od');tool_raw=b'pure fixture tool identity, never executed'
        tool={'path':str(r.DISASSEMBLER),'sha256':r.digest(tool_raw),'size':len(tool_raw)}
        for binary,map_name in (('floor_profile.exe','native.map'),('rust-profile.exe','rust.map')):
            files[directory/binary]=own;files[directory/map_name]=mapping
        files[directory/'instruction-tool.bin']=tool_raw
        def receipt(label,argv,stdout):
            row={'argv':list(map(str,argv)),'cwd':recipe['source'],'env':{},'status':0,'terminal':'exit',
                 'start_ns':1,'end_ns':2,'start_utc':'synthetic','end_utc':'synthetic','pid':123}
            if label.startswith('instruction-') or '-instructions-' in label:row['tool_binary']=tool
            for suffix,raw in (('stdout',stdout),('stderr',b'')):
                files[directory/(label+'.'+suffix)]=raw
                row[suffix]={'name':label+'.'+suffix,'size':len(raw),'sha256':r.digest(raw)}
            files[directory/(label+'.json')]=json.dumps(row).encode();return row
        receipt('rust',['synthetic-fixture-process'],b'')
        original_read=Path.read_bytes
        def read(path):return files[path] if path in files else original_read(path)
        def write(path,value):files[path]=value;return len(value)
        def emit(directory_arg,label,argv,*args):
            self.assertEqual(directory_arg,directory)
            if label=='instruction-help':return receipt(label,argv,b'--disassemble --start-address --stop-address')
            start=int(argv[2].split('=')[1],16)-0x140000000;end=int(argv[3].split('=')[1],16)-0x140000000
            binary=module if '-runtime-' in label else own
            span=r.pe_code(binary)[3](start,end,True)
            return receipt(label,argv,instructions(span))
        with patch.object(Path,'read_bytes',read),patch.object(Path,'write_bytes',write),patch.object(Path,'write_text',lambda path,value,**kw:write(path,value.encode())),patch.object(Path,'is_file',return_value=True),patch.object(r,'record',emit):
            captured=r.compiled_evidence(directory,parsed,recipe,True,{})
            self.assertEqual(r.compiled_evidence(directory,parsed,recipe),captured)
            self.assertTrue(all(not view['pending'] for view in (captured['rust'],captured['rust']['runtime_images'][0]['witness'])))
            for name in ('required-return','seed-copy','data','sink','layout','owner','role','pending','unresolved-import'):
                key=directory/'rust-code.json';legal=files[key];peer=json.loads(legal)
                if name=='required-return':peer['copy_obligations'].pop(0)
                elif name=='seed-copy':peer['copy_obligations'].pop()
                elif name=='data':peer['data_requests']=[]
                elif name=='sink':peer['semantic_origins'][0]['received'][2]+=176
                elif name=='layout':peer['semantic_origins'][0]['layout']['facts'][0]=176
                elif name=='owner':peer['semantic_origins'][0]['owner']=[2,0,0,0]
                elif name=='role':peer['semantic_origins'][0]['role']='AcquisitionUtility'
                elif name=='pending':peer['pending']=[[0x1000,0x1008]]
                else:peer['edges'][0]['obligation']='Unresolved'
                files[key]=json.dumps(peer).encode()
                with self.subTest(name=name),self.assertRaisesRegex(ValueError,'rederived executed-image'):r.compiled_evidence(directory,parsed,recipe)
                files[key]=legal
            old=files[directory/'rust-code.json'];del files[directory/'rust-code.json']
            broken=copy.deepcopy(parsed);broken[1]['operations'][0]['witness']['handoff_sites'][0]=8192+0x2000
            with self.assertRaisesRegex(ValueError,'handoff site'):r.compiled_evidence(directory,broken,recipe,True,{})
            progress=json.loads(files[directory/'rust-code-progress.json'])
            self.assertTrue(progress['images'][0]['witness']['pending'])
            self.assertNotIn(directory/'rust-code.json',files)
            self.assertNotIn(directory/'seal.json',files)
            files[directory/'rust-code.json']=old

    def test_55_full_witness_ranges_and_exact_adjacency(self):
        for role in r.WITNESS_ROLES:
            raw=r.operation_corpus();op={'owner':[1,0,0,0],'base':8192}
            size=r.witness_layout()['facts'][0]
            def admit(pointer,sink):
                row=witness_record(op,raw,role,0,pointer)
                row['handoff'][2]=row['received'][2]=sink
                return r.admit_witness(row,op,raw,role,0,pointer)
            self.assertEqual(admit(4096,16384)['layout']['facts'][0],2664)
            for pointer,sink in ((4096-152,4096),(4096+size,4096)):
                self.assertEqual(admit(pointer,sink)['compiled_dataflow'],'UnprovedAwaitingIndependentReview')
            for name,pointer,sink in (
                ('exact-coordinated-3920',4096,3920),
                ('raw-beyond-operation',4096+176,4096),
                ('sink-start-inside-raw',4096,4104),
                ('partial-sink-start',4096-151,4096),
                ('partial-sink-end',4096+size-1,4096)):
                with self.subTest(role=role,name=name),self.assertRaisesRegex(ValueError,'full Witness sink do not alias'):
                    admit(pointer,sink)
            for name,pointer,sink in (
                ('raw-end-overflow',2**64-128,4096),
                ('full-sink-end-overflow',4096,2**64-256),
                ('sink-zero',4096,0),('sink-boolean',4096,True),
                ('raw-zero',0,16384),('raw-boolean',True,16384),
                ('sink-unaligned',4096,16385),('raw-noncanonical',2**47,4096),
                ('sink-noncanonical',4096,2**47)):
                with self.subTest(role=role,name=name),self.assertRaises(ValueError):admit(pointer,sink)

    def test_56_closed_full_layout_peers_use_real_admission(self):
        legal=packet('rust');r.parse(wire(legal),'rust',True)
        for name in ('missing','extra-record','stale-schema','zero','boolean','short-size','long-size',
                     'forged-offset','forged-align','forged-operation','forged-usize','short-facts','long-facts',
                     'missing-target','extra-layout','unknown-target','boolean-offset','coordinated-3920'):
            rows=copy.deepcopy(legal);row=next(v for v in rows if v['stage']=='witness');layout=row['layout']
            if name=='missing':del row['layout']
            elif name=='extra-record':row['sink_size']=2664
            elif name=='stale-schema':row['schema']=1
            elif name=='zero':layout['facts'][0]=0
            elif name=='boolean':layout['facts'][0]=True
            elif name=='short-size':layout['facts'][0]=176
            elif name=='long-size':layout['facts'][0]+=8
            elif name=='forged-offset':layout['facts'][-1]-=8
            elif name=='forged-align':layout['facts'][1]=4
            elif name=='forged-operation':layout['facts'][4]=168
            elif name=='forged-usize':layout['facts'][2]=4
            elif name=='short-facts':layout['facts'].pop()
            elif name=='long-facts':layout['facts'].append(0)
            elif name=='missing-target':del layout['target']
            elif name=='extra-layout':layout['size']=2664
            elif name=='unknown-target':layout['target']='untrusted-layout'
            elif name=='coordinated-3920':row['handoff'][2]=row['received'][2]=3920
            else:layout['facts'][6]=False
            with self.subTest(name=name),self.assertRaises(ValueError):r.parse(wire(rows),'rust',True)

    def test_57_witness_repr_c_source_type_contract(self):
        source=(r.HERE/'observer.rs').read_text()
        body=r.re.search(r'#\[repr\(C\)\]\nstruct Witness \{(.*?)\n\}',source,r.re.S)[1]
        fields=r.re.findall(r'(\w+):\s*(Operation|usize|u32|\[u8; 1024\]|\[usize; \d+\]|\[\[usize; 10\]; 16\])\s*,',body)
        types={'Operation':(176,8),'usize':(8,8),'u32':(4,4),'[u8; 1024]':(1024,1),'[[usize; 10]; 16]':(1280,8)}
        actual=[]
        for name,kind in fields:
            if kind.startswith('[usize;'):size,align=int(r.re.search(r'\d+',kind)[0])*8,8
            else:size,align=types[kind]
            actual.append((name,size,align))
        self.assertEqual(tuple(actual),r.WITNESS_FIELDS)
        self.assertEqual(r.re.sub(r'\s+','',body),''.join(name+':'+r.re.sub(r'\s+','',kind)+',' for name,kind in fields))
        layout=r.re.search(r'fn layout\(&self\) -> \[usize; 21\] \{(.*?)\n    \}',source,r.re.S)[1]
        self.assertEqual(r.re.findall(r'offset_of!\(Self, (\w+)\)',layout),[field[0] for field in r.WITNESS_FIELDS])
        self.assertIn('std::mem::size_of_val(self), std::mem::align_of::<Self>()',layout)
        self.assertIn('std::mem::size_of::<usize>(), std::mem::align_of::<usize>()',layout)
        self.assertIn('std::mem::size_of::<Operation>(), std::mem::align_of::<Operation>()',layout)
        self.assertIn('cfg!(all(target_os = "windows", target_arch = "x86_64"))',source)

    def test_zz_real_effects_rejected_before_effects(self):
        target=Path('/Users/geekjapan/.codex/orchestrate/mikudance-rust-20261027/renderer-operation-boundary/effect-probe')
        self.assertFalse(target.exists());r.readonly()
        probes=[lambda:target.write_bytes(b'forbidden'),lambda:target.mkdir(),lambda:subprocess.run([sys.executable,'-c','raise SystemExit(99)'],check=True),lambda:socket.socket()]
        for probe in probes:
            with self.assertRaises(ValueError):probe()
        self.assertFalse(target.exists())


class CensusControls(unittest.TestCase):
    def view(self,count=1):
        return {'image_sha256':'a'*64,'sections':[{}],
                'ranges':[{'start_rva':i*8,'end_rva':i*8+8,'bytes':'00'*8} for i in range(count)],
                'requests':[],'edges':[],'data_requests':[],'pending':[],'decoded':[]}

    def test_default_cap_and_exact_first_violation(self):
        view=self.view(128);r.closure_budget([view]);census=r.ClosureCensus();census.register(view);census.check()
        self.assertIsNone(census.first_ordinary_violation)
        view['ranges'].append({'start_rva':1024,'end_rva':1032,'bytes':'00'*8})
        with self.assertRaisesRegex(ValueError,'small bounded operation'):r.closure_budget([view])
        census.check();saved=copy.deepcopy(census.first_ordinary_violation)
        self.assertEqual(saved['error'],'small bounded operation code regions')
        self.assertEqual(len(saved['images'][0]['ranges']),129)
        view['ranges'].append({'start_rva':1032,'end_rva':1040,'bytes':'00'*8});census.check()
        self.assertEqual(census.first_ordinary_violation,saved)
        self.assertNotEqual(r.SCHEMA,r.CENSUS_SCHEMA)
        with self.assertRaisesRegex(ValueError,'generation/head'):r.admit_manifest({'schema':r.CENSUS_SCHEMA,'fp_observation_contract':r.FP_CONTRACT})

    def test_finite_ceilings_are_independent_and_keep_lower_bound(self):
        for name in r.CENSUS_LIMITS:
            with patch.object(r.previous.time,'monotonic',side_effect=[100,101]):
                census=r.ClosureCensus();view=self.view(2);census.register(view)
                limits=dict(r.CENSUS_LIMITS);limits[name]=0
                with self.subTest(ceiling=name),patch.dict(r.CENSUS_LIMITS,limits),self.assertRaisesRegex(r.CensusLimit,'diagnostic '+name):census.check()
            view['pending']=[[0,8],[8,16]]
            summary=census.summary([{'witness':view}])
            self.assertEqual(summary['status'],'CENSUS_INCOMPLETE_UNRESOLVED')
            self.assertEqual(summary['count_interpretation'],'LowerBound')
            self.assertEqual(len(summary['pending']),2)
        empty=r.ClosureCensus().summary([])
        self.assertEqual(empty['status'],'CENSUS_INCOMPLETE_UNRESOLVED')

    def test_seconds_ceiling_accepts_equal_elapsed_and_refuses_above(self):
        for deadline in (0,2):
            with self.subTest(deadline=deadline),patch.dict(r.CENSUS_LIMITS,{'seconds':deadline}),patch.object(r.previous.time,'monotonic',side_effect=[100,100+deadline,101+deadline]):
                census=r.ClosureCensus();census.register(self.view(2))
                self.assertEqual(census.check()['seconds'],deadline)
                with self.assertRaisesRegex(r.CensusLimit,'diagnostic seconds'):census.check()

    def test_unique_ranges_logical_roots_shared_reachability(self):
        raw,mapping,rows,_=code_fixture();census=r.ClosureCensus()
        view=r.required_code_ranges(raw,rows,mapping,census=census)
        before=len(view['ranges'])
        r.request_range(view,raw,0x1001,'SecondRoot',{'kind':'RuntimeSite','owner':'other'},census)
        for span in list(view['ranges']):
            for edge in r.instruction_edges(instructions(span),view,span):
                view['edges'].append(edge);r.follow_required_edge(None,[{'raw':raw,'witness':view}],0,span,edge,census)
        view['decoded']=view['pending'];view['pending']=[]
        result=census.summary([{'raw':raw,'witness':view},{'raw':raw,'witness':view}])
        self.assertEqual(result['physical_unique'],before)
        self.assertGreater(result['logical_requests'],before)
        self.assertTrue(result['shared_sets'])
        self.assertTrue(any(len(nodes)==2 for nodes in result['root_reachability'].values()))

    def test_unresolved_edge_does_not_block_next_known_edge(self):
        raw,mapping,rows,_=code_fixture();view=r.required_code_ranges(raw,rows,mapping);census=r.ClosureCensus();census.register(view)
        span=view['ranges'][0];images=[{'raw':raw,'witness':view}]
        unknown={'instruction_rva':0x1000,'bytes':'ffd0','text':'callq *%rax','obligation':'Required','target':{'kind':'Unresolved'}}
        known={'instruction_rva':0x1002,'bytes':'e819000000','text':'callq 0x140001020','obligation':'Required','target':{'kind':'DirectRva','rva':0x1020}}
        for edge in (unknown,known):
            view['edges'].append(edge);r.follow_required_edge(None,images,0,span,edge,census)
        self.assertEqual(unknown['obligation'],'Unresolved');self.assertEqual(known['resolution'],'Acquired')
        result=census.summary(images)
        self.assertEqual(result['unresolved_edges'][0]['bytes'],'ffd0')
        self.assertEqual(result['status'],'CENSUS_INCOMPLETE_UNRESOLVED')

    def test_ceiling_request_retains_unknown_without_acquiring_range(self):
        raw,mapping,rows,_=code_fixture();view=r.required_code_ranges(raw,rows,mapping);census=r.ClosureCensus();census.register(view)
        view['ranges']=view['ranges'][:1];view['pending']=[[0x1000,0x1008]];view['requests']=[]
        with patch.dict(r.CENSUS_LIMITS,{'ranges':1}),self.assertRaises(r.CensusLimit):
            r.request_range(view,raw,0x1020,'KnownBeyondCeiling',{'kind':'RequiredTarget','caller_extent':[0x1000,0x1008]},census)
        self.assertEqual(len(view['ranges']),1);self.assertEqual(len(view['pending']),1)
        self.assertEqual(view['requests'][-1]['resolution'],'Unresolved')
        self.assertEqual(view['requests'][-1]['start_rva'],0x1020)

    def test_import_owner_binding_negative_retained(self):
        raw,directory,files,parsed=runtime_fixture();parsed['runtime_imports'][0]['slots'][0]['owner_base']+=1
        census=r.ClosureCensus()
        with patch.object(Path,'read_bytes',lambda path:files[path]),patch.object(r,'checked',return_value=({'pid':123},b'',b'')):
            self.assertEqual(r.runtime_images(directory,parsed,raw,census),[])
        self.assertTrue(census.unknowns)
        self.assertEqual(census.unknowns[0]['kind'],'RequiredImportOwnerBinding')
        self.assertIn('slot_rva',census.unknowns[0]['slot'])

    def test_memset_import_is_diagnostic_only_and_owner_authenticated(self):
        raw,directory,files,parsed=runtime_fixture();changed=bytearray(raw)
        changed[1536+162:1536+169]=b'memset\0';raw=bytes(changed)
        with self.assertRaisesRegex(ValueError,'copy import slots'):r.import_slots(raw)
        self.assertEqual(r.import_slots(raw,r.ClosureCensus())[0]['imported_symbol'],'memset')
        for phase in ('pre','post'):
            files[directory/(f'runtime-{phase}-0-module.bin')]=raw
            files[directory/(f'runtime-{phase}-0-section-2.bin')]=raw[1536:1792]
        census=r.ClosureCensus()
        with patch.object(Path,'read_bytes',lambda path:files[path]),patch.object(r,'checked',return_value=({'pid':123},b'',b'')):
            images=r.runtime_images(directory,parsed,raw,census)
        self.assertEqual(len(images),1);self.assertFalse(census.unknowns)
        self.assertEqual(images[0]['pre']['slot']['imported_symbol'],'memset')
        self.assertIn('post',images[0])

    def test_sampled_loaded_dispatch_is_not_universal_target_set(self):
        raw,mapping,rows,_=code_fixture();view=r.required_code_ranges(raw,rows,mapping);census=r.ClosureCensus();census.register(view)
        edge={'instruction_rva':0x1000,'bytes':'ff1500100000','text':'callq *slot','obligation':'Required','target':{'kind':'RipRelativeIatSlot','slot_rva':0x1000}}
        image={'raw':raw,'witness':view,'pre':{},'post':{}}
        with patch.object(r,'loaded_dispatch_target',return_value=(0x1020,[{'target_va':123}])):
            r.follow_required_edge(None,[image],0,view['ranges'][0],edge,census)
        self.assertEqual(edge['reason'],'SampledDispatchIsNotCompleteFiniteTargetSet')
        self.assertEqual(edge['obligation'],'Unresolved')
        self.assertEqual(view['data_requests'][-1]['resolution'],'Unresolved')

    def test_actual_worklist_continues_after_unknown_and_decode_failure(self):
        raw,mapping,rows,_=code_fixture();directory=Path('/synthetic-census');recipe={'source':'source','evidence':str(directory)}
        files={directory/name:raw for name in ('floor_profile.exe','rust-profile.exe')}
        files.update({directory/name:mapping for name in ('native.map','rust.map')});files[directory/'instruction-tool.bin']=b'tool'
        tool={'path':str(r.DISASSEMBLER),'sha256':r.digest(b'tool'),'size':4};commands={};outputs={};saved={}
        def record(out,label,argv,cwd,env,timeout=1200):
            commands[label]=list(argv)
            return {'status':1 if label=='census-0-instructions-0' else 0}
        def checked(out,label):
            argv=commands[label];receipt={'argv':argv,'cwd':'source','tool_binary':tool}
            if label=='instruction-help':return receipt,b'--disassemble --start-address --stop-address',b''
            first=int(argv[2].split('=')[1],16)-0x140000000;last=int(argv[3].split('=')[1],16)-0x140000000
            return receipt,instructions(r.pe_code(raw)[3](first,last,True)),b''
        census=r.ClosureCensus();parsed=({'operations':rows},{'operations':rows})
        with patch.object(Path,'read_bytes',lambda path:files[path]),patch.object(Path,'is_file',return_value=True),patch.object(r,'record',record),patch.object(r,'checked',checked),patch.object(r,'write_json',lambda path,value:saved.__setitem__(path,copy.deepcopy(value))),patch.object(r,'write_bound_document',lambda path,value:saved.__setitem__(path,copy.deepcopy(value))),patch.object(r,'seed_data',return_value={'role':'SeedTable','size':8192,'resolution':'Resolved'}):
            result=r.census_evidence(directory,parsed,recipe,{},census)
        self.assertEqual(result['status'],'CENSUS_INCOMPLETE_UNRESOLVED')
        self.assertEqual(len([label for label in commands if '-instructions-' in label]),4)
        self.assertTrue(result['pending']);self.assertEqual(result['decoded'],3)
        self.assertIn(directory/'closure-census.json',saved)
        self.assertTrue(any(item['kind']=='Decode' for item in result['unknowns']))
        self.assertTrue(any(item['kind']=='RequiredRuntimeImports' for item in result['unknowns']))

    def test_observed_runtime_worklist_preserves_decode_journal(self):
        for failed in (None,'census-2-instructions-1'):
            with self.subTest(failed=failed):
                raw,directory,files,observed=runtime_fixture()
                changed=bytearray(raw);changed[1024:1032]=b'\xe8\x1b\x00\x00\x00\x90\x90\xc3';raw=bytes(changed)
                for phase in ('pre','post'):
                    files[directory/(f'runtime-{phase}-0-module.bin')]=raw
                    files[directory/(f'runtime-{phase}-0-section-0.bin')]=raw[1024:1280]
                _,mapping,rows,_=code_fixture();observed['operations']=rows
                files.update({directory/name:raw for name in ('floor_profile.exe','rust-profile.exe')})
                files.update({directory/name:mapping for name in ('native.map','rust.map')})
                files[directory/'instruction-tool.bin']=b'tool'
                tool={'path':str(r.DISASSEMBLER),'sha256':r.digest(b'tool'),'size':4}
                commands={};saved={};progress=[]
                def record(out,label,argv,cwd,env,timeout=1200):
                    commands[label]=list(argv)
                    return {'status':int(label==failed)}
                def checked(out,label):
                    if label=='rust':return {'pid':123},b'',b''
                    argv=commands[label];receipt={'argv':argv,'cwd':'source','tool_binary':tool}
                    if label=='instruction-help':return receipt,b'--disassemble --start-address --stop-address',b''
                    first=int(argv[2].split('=')[1],16)-0x140000000
                    last=int(argv[3].split('=')[1],16)-0x140000000
                    return receipt,instructions(r.pe_code(raw)[3](first,last,True)),b''
                def save(path,value):
                    saved[path]=json.loads(json.dumps(value))
                    self.assertEqual(saved[path],value)
                    if path.name=='closure-census-progress.json':progress.append(saved[path])
                with patch.object(Path,'read_bytes',lambda path:files[path]),patch.object(Path,'is_file',return_value=True),patch.object(r,'record',record),patch.object(r,'checked',checked),patch.object(r,'write_json',save),patch.object(r,'write_bound_document',save),patch.object(r,'seed_data',return_value={'role':'SeedTable','size':8192,'resolution':'Resolved'}):
                    result=r.census_evidence(directory,({'operations':rows},observed),{'source':'source','evidence':str(directory)},{},r.ClosureCensus())
                runtime=lambda summary:next(image['witness'] for image in summary['images'] if image['file']=='runtime-pre-0-module.bin')
                first,last=[0x1000,0x1008],[0x1020,0x1028]
                self.assertEqual(runtime(progress[0])['pending'],[first])
                self.assertEqual(runtime(progress[0])['decoded'],[])
                after_first=next(runtime(row) for row in progress if runtime(row)['decoded']==[first])
                self.assertEqual(after_first['pending'],[last])
                journal=runtime(result)
                self.assertEqual(journal['decoded'],[first] if failed else [first,last])
                self.assertEqual(journal['pending'],[last] if failed else [])
                self.assertEqual(len(journal['ranges']),2)
                self.assertEqual([label for label in commands if label.startswith('census-2-instructions-')],['census-2-instructions-0','census-2-instructions-1'])
                decode=[item for item in result['unknowns'] if item['kind']=='Decode']
                self.assertEqual(decode,[{'kind':'Decode','image':'runtime-pre-0-module.bin','extent':last,'reason':'diagnostic bounded disassembly'}] if failed else [])
                self.assertEqual(saved[directory/'closure-census.json'],result)
                for field in ('pending','decoded','ranges','requests','compiled_dataflow'):
                    self.assertEqual(runtime(progress[-1])[field],journal[field])
                self.assertEqual(result['status'],'CENSUS_INCOMPLETE_UNRESOLVED')
                self.assertEqual(result['admission'],'NotAuthorized')
                self.assertEqual(journal['compiled_dataflow'],'UnprovedAwaitingIndependentReview')
                self.assertTrue(any(item['kind']=='RequiredNonBranchDataTargets' for item in result['unknowns']))
                self.assertFalse(any(item['kind']=='RequiredRuntimeImports' for item in result['unknowns']))

    def test_four_variants_continue_only_after_proven_writer_closure(self):
        recorder=r.record
        for failure_at in (None,'git-head','native-build','expired-fourth'):
            files={};calls=[];fixtures=[];acquired=[];saved={}
            out=Path('C:/runner/temp/closure-census-evidence');build=Path('C:/runner/temp/closure-census-build');toolchain=Path('C:/runner/temp/floor-profile-deps/build/generators/conan_toolchain.cmake')
            def save(path,value):saved[path]=copy.deepcopy(value);files[path]=json.dumps(value).encode()
            def record(directory,label,argv,cwd,env,timeout=1200):
                calls.append((directory.name,label))
                raw=r.ACCEPTED_MAIN['merge'].encode() if label in ('git-head','git-first-parent-ancestry') else '\n'.join(r.CENSUS_PATHS).encode() if label=='git-paths' else b''
                files[directory/(label+'.stdout')]=raw;files[directory/(label+'.stderr')]=b''
                r.census_custody(out)
                if label==failure_at:
                    save(out/'writer-pending.json',{'state':'unknown'})
                    save(out/'writer-custody.json',{'schema':r.CUSTODY_SCHEMA,'state':'unknown','receipts':[]})
                    raise ValueError('unclosed diagnostic writers')
                row={'status':0,'argv':list(argv),'writer_closure':True}
                save(directory/(label+'.json'),row)
                prior=saved[out/'writer-custody.json']['receipts']
                save(out/'writer-custody.json',{'schema':r.CUSTODY_SCHEMA,'state':'closed','receipts':prior+[(directory/(label+'.json')).relative_to(out).as_posix()]})
                return row
            def acquire(directory,*args):
                acquired.append(directory.name)
                if len(acquired)==1:raise ValueError('closed diagnostic failure')
                if failure_at=='expired-fourth' and len(acquired)==4:clock['now']+=1201
                return {'status':'CENSUS_INCOMPLETE_UNRESOLVED'}
            def glob(path,pattern):return [file for file in files if file.parent==path and file.suffix=='.json']
            def inventory(path):
                self.assertNotIn(out/'writer-pending.json',files,'source read while writer closure unknown')
                return {}
            recipe=r.recipe
            clock={'now':0.};finalized=[];finalizer=r.finish_source_admission
            def finish(directory,m,env):
                if failure_at=='expired-fourth':
                    self.assertGreater(clock['now'],float(env['MDS_CENSUS_DEADLINE']))
                    error,launched,_,_,_,_=SourceFinalizationControls().exercise(out=directory,manifest=m,environment=env,finalizer=finalizer,recorder=recorder)
                    if error is not None:raise error
                    self.assertEqual(len(launched),3);finalized.append(True)
            def inert_recipe(*args):return {key:value.replace('\\','/') if isinstance(value,str) else value for key,value in recipe(*args).items()}
            patches=[
                patch.object(r,'acquire_source_admission'),
                patch.object(r,'finish_source_admission',side_effect=finish) if failure_at!='expired-fourth' else patch.object(r.previous.time,'monotonic',lambda:clock['now']),
                patch.object(r,'recipe',inert_recipe),
                patch.object(r.sys,'platform','win32'),
                patch.dict(os.environ,{'GITHUB_ACTIONS':'true','RUNNER_TEMP':'C:/runner/temp','GITHUB_SHA':r.ACCEPTED_MAIN['merge']}),
                patch.object(Path,'exists',lambda path:path in files),
                patch.object(Path,'is_file',return_value=True),
                patch.object(Path,'mkdir'),
                patch.object(Path,'read_bytes',lambda path:files.get(path,b'binary')),
                patch.object(Path,'read_text',lambda path,**kwargs:files.get(path,b'').decode()),
                patch.object(Path,'write_bytes',lambda path,raw:files.__setitem__(path,raw)),
                patch.object(Path,'glob',glob),
                patch.object(Path,'rglob',lambda path,pattern:[path/'core/accessory.obj',path/'console/native.obj']),
                patch.object(r.shutil,'copyfile'),
                patch.object(r.shutil,'copytree'),
                patch.object(r.c,'safe_tar',return_value={}),
                patch.object(r.c,'source_inventory',inventory),
                patch.object(r,'inputs',return_value=[]),
                patch.object(r,'source_expected',return_value=({}, {}, {})),
                patch.object(r,'record',record),
                patch.object(r,'write_json',save),
                patch.object(r,'write_bound_document',save),
                patch.object(r,'native_commands',return_value=[]),
                patch.object(r,'cargo_binary',return_value='synthetic-cargo'),
                patch.object(r,'parse',lambda raw,language,observed:{'dll':{'path':'dll'}} if language=='native' else {}),
                patch.object(r,'fixture_result',lambda label,*args:fixtures.append(label)),
                patch.object(r,'census_evidence',acquire),
                patch.object(r.previous,'evidence_inventory',return_value={}),
            ]
            with ExitStack() as stack:
                for context in patches:stack.enter_context(context)
                if failure_at in (None,'expired-fourth'):
                    if failure_at=='expired-fourth':
                        with patch.object(r,'finish_source_admission',side_effect=finish):result=r.run(out,build,toolchain,True)
                        self.assertEqual(finalized,[True])
                    else:result=r.run(out,build,toolchain,True)
                    self.assertEqual(len(result['variants']),4)
                    self.assertEqual(len(acquired),4,{str(k):v for k,v in saved.items() if k.name=='variant-failure.json'});self.assertEqual(fixtures,['mesh_dump','x_files']*4)
                    self.assertNotIn(out/'seal.json',saved)
                    self.assertIn(out/'closure-census-seal.json',saved)
                else:
                    with self.assertRaisesRegex(ValueError,'unclosed diagnostic writers'):r.run(out,build,toolchain,True)
                    self.assertEqual(len(acquired),0)
                    self.assertNotIn(out/'closure-census-seal.json',saved)
                    self.assertFalse(any(path.name in ('source-after.json','variant-closure.json') for path in saved))
                    self.assertNotIn(out/'closure-census-result.json',saved)
                    self.assertNotIn(out/'manifest.json',saved)
                    self.assertNotIn('observed-Od',[directory for directory,label in calls])

    def test_diagnostic_recipe_and_default_reader_remain_separate(self):
        for opt in ('Od','O2'):
            for variant in ('control','observed'):
                ordinary=r.recipe('C:/runner/temp',variant,opt);diagnostic=r.recipe('C:/runner/temp',variant,opt,True)
                self.assertIn('floor-profile-evidence',ordinary['evidence']);self.assertIn('closure-census-evidence',diagnostic['evidence'])
                self.assertEqual(ordinary['commands']['rust-build'],diagnostic['commands']['rust-build'])
                self.assertEqual(set(r.FIXTURE_TESTS),{'mesh_dump','x_files'})
                self.assertEqual(sum(map(len,r.FIXTURE_TESTS.values())),14)
        with patch.object(sys,'argv',['run.py','--closure-census','--out','/inert']),self.assertRaisesRegex(ValueError,'explicit hosted --run'):r.main()
        with patch.object(r,'load_json',return_value={'schema':r.CENSUS_SCHEMA}),patch.object(Path,'read_bytes',return_value=b'{}'),self.assertRaises((ValueError,KeyError)):
            r.replay(Path('/inert-census'))


class SourceFinalizationControls(unittest.TestCase):
    def exercise(self,failure=None,*,out=None,manifest=None,environment=None,finalizer=None,recorder=None):
        from types import SimpleNamespace
        args,anchors,_,_=Controls().admission_fixture()
        m,frames,base,tooling,imports,current=args
        m['base_inventory']={p:{'mode':0o644,'sha256':r.digest(raw)} for p,(_,raw) in base.items()}
        if manifest is not None:manifest.update(m);m=manifest
        out=out or Path('/owned-finalization')
        files={out/'controller'/p:raw for p,raw in frames.items()}
        files.update({out/'sources/base'/p:raw for p,(_,raw) in base.items()})
        files.update({out/'tooling'/p:raw for p,raw in tooling.items()})
        files.update({out/'controller/imports'/p:raw for p,raw in imports.items()})
        bodies={p:raw for p,(_,raw) in base.items()}|tooling|imports|{p:frames['fixed-import/bodies/'+p] for p in r.FIXED_IMPORT_BLOBS}
        files.update({r.ROOT/p:raw for p,raw in bodies.items()})
        files[out/'controller-source-before.json']=json.dumps(current).encode()
        files[out/'writer-custody.json']=json.dumps({'schema':r.CUSTODY_SCHEMA,'state':'no_writer_started','receipts':[]}).encode()
        if failure=='unknown-before':files[out/'writer-pending.json']=b'unknown'
        env=environment if environment is not None else {'MDS_CENSUS_CUSTODY':str(out),'MDS_CENSUS_DEADLINE':'0','KEEP':'original'}
        original=dict(env);clock={'now':1201.,'calls':0};launched=[];streams=[];events=[]
        outputs=[(m['head']+'\n').encode(),b'',frames['head.tree']]
        if failure=='head-drift':outputs[0]=b'wrong\n'
        if failure=='status-drift':outputs[1]=b' M changed\n'
        if failure=='tree-drift':outputs[2]+=b'wrong'
        def monotonic():
            clock['calls']+=1
            if failure=='proof-overrun' and clock['calls']==8:clock['now']+=601
            return clock['now']
        def save(path,value):
            events.append(path.name);files[path]=json.dumps(value).encode()
        class Stream:
            def __init__(self,path):self.path=path;self.closed=False;files[path]=b''
            def close(self):self.closed=True
        class Job:
            def setup(self):pass
            def assign(self,child):pass
            def resume(self,child):pass
            def terminate(self):pass
            def accounting(self):return SimpleNamespace(active_processes=0)
            def resources(self,accounting):return {'peak':1}
            def close(self):
                if failure=='unknown-final':raise OSError('inert unknown handle closure')
        class Child:
            pid=123
            _handle=SimpleNamespace(Close=lambda:None)
            def __init__(self,index):self.index=index;self.waits=0
            def wait(self,timeout):
                self.waits+=1
                if self.waits==1:
                    if failure=='timeout':raise subprocess.TimeoutExpired('inert metadata',timeout)
                    if (failure,self.index) in (('before-second',0),('before-third',1)):clock['now']+=601
                return 0
            def kill(self):pass
        def launch(argv,**kwargs):
            index=len(launched);launched.append((list(argv),dict(kwargs['env'])))
            self.assertIn(out/'writer-pending.json',files)
            files[kwargs['stdout'].path]=outputs[index]
            return Child(index)
        def open_stream(path,mode):
            self.assertEqual(mode,'xb');stream=Stream(path);streams.append(stream);return stream
        def read(path):
            if path.name.endswith(('.stdout','.stderr')):self.assertTrue(all(s.closed for s in streams))
            return files[path]
        ordinary=[]
        def ordinary_record(directory,label,argv,cwd,env,timeout):
            index=len(ordinary);ordinary.append(dict(env));files[directory/(label+'.stdout')]=outputs[index]
            return {'status':0}
        contexts=anchors+[
            patch.object(r,'record',recorder or r.record),
            patch.object(r.sys,'platform','win32'),patch.dict(os.environ,{'GITHUB_ACTIONS':'true'}),
            patch.object(r,'census_windows_job',lambda:Job()),patch.object(r.previous.subprocess,'Popen',launch),
            patch.object(r.previous,'record',ordinary_record),patch.object(r.previous.time,'monotonic',monotonic),
            patch.object(Path,'exists',lambda path:path in files),patch.object(Path,'is_file',lambda path:path in files),
            patch.object(Path,'is_symlink',return_value=False),patch.object(Path,'stat',return_value=SimpleNamespace(st_mode=0o100644,st_nlink=1)),
            patch.object(Path,'read_bytes',read),patch.object(Path,'read_text',lambda path:read(path).decode()),
            patch.object(Path,'rglob',lambda path,pattern:[p for p in files if p!=path and p.is_relative_to(path)]),
            patch.object(Path,'open',open_stream),patch.object(Path,'unlink',lambda path:files.pop(path)),patch.object(r,'write_json',save)]
        error=None
        with ExitStack() as stack:
            for context in contexts:stack.enter_context(context)
            try:(finalizer or r.finish_source_admission)(out,m,env)
            except (ValueError,OSError,KeyError) as caught:error=caught
        self.assertEqual(env,original)
        return error,launched,clock,files,events,ordinary

    def test_expired_variant_has_one_finite_closed_source_phase(self):
        error,launched,clock,files,events,_=self.exercise()
        self.assertIsNone(error)
        self.assertEqual(len(launched),3)
        self.assertEqual({env['MDS_CENSUS_DEADLINE'] for _,env in launched},{'1801.0'})
        self.assertIn(Path('/owned-finalization/controller-source-after.json'),files)
        self.assertEqual(clock['calls'],8)
        for failure,count in [('before-second',1),('before-third',2)]:
            error,launched,_,files,_,_=self.exercise(failure)
            self.assertRegex(str(error),'wall time ceiling')
            self.assertEqual(len(launched),count)
            self.assertNotIn(Path('/owned-finalization/controller-source-after.json'),files)
        error,_,_,files,_,_=self.exercise('proof-overrun')
        self.assertRegex(str(error),'source finalization wall time ceiling')
        self.assertIn(Path('/owned-finalization/controller-source-after.json'),files)

    def test_unknown_closure_and_final_metadata_failure_never_complete(self):
        error,launched,clock,files,events,_=self.exercise('unknown-before')
        self.assertRegex(str(error),'unclosed diagnostic writers')
        self.assertEqual((launched,clock['calls'],events),([],0,[]))
        for failure in ('timeout','unknown-final','head-drift','status-drift','tree-drift'):
            with self.subTest(failure=failure):
                error,_,_,files,_,_=self.exercise(failure)
                self.assertIsNotNone(error)
                self.assertNotIn(Path('/owned-finalization/controller-source-after.json'),files)

    def test_ordinary_source_finalization_keeps_environment_and_no_new_deadline(self):
        error,launched,clock,_,_,ordinary=self.exercise(environment={'KEEP':'ordinary'})
        self.assertIsNone(error);self.assertEqual(launched,[]);self.assertEqual(clock['calls'],0)
        self.assertEqual(ordinary,[{'KEEP':'ordinary'}]*3)


class ImportReachabilityControls(unittest.TestCase):
    def imported(self,shared=False):
        raw,directory,files,parsed=runtime_fixture()
        declarations=r.import_slots(raw,r.ClosureCensus())
        declarations.append(dict(declarations[0],slot_rva=0x3068,imported_symbol='memset'))
        for phase,snapshot in zip(('pre','post'),parsed['runtime_imports']):
            actual=dict(snapshot['slots'][0],slot_rva=0x3068,target_va=0x140000000+(0x1000 if shared else 0x1020))
            snapshot['slots'].append(actual)
            for path,body in list(files.items()):
                if f'runtime-{phase}-0-' in path.name:
                    files[path.with_name(path.name.replace('-0-','-1-'))]=body
            files[directory/f'runtime-{phase}-1-iat.bin']=struct.pack('<Q',actual['target_va'])
        caller_raw=raw[:1800]+b'x'+raw[1801:]
        census=r.ClosureCensus()
        with patch.object(Path,'read_bytes',lambda path:files[path]),patch.object(r,'checked',return_value=({'pid':123},b'',b'')),patch.object(r,'import_slots',return_value=declarations):
            imports=r.runtime_images(directory,parsed,caller_raw,census)
        self.assertFalse(census.unknowns);self.assertEqual(len(imports),2)
        view={'image_sha256':r.digest(caller_raw),'sections':r.pe_code(caller_raw)[1],
              'ranges':[],'requests':[],'edges':[],'data_requests':[],'pending':[],'decoded':[]}
        for i,slot in enumerate((0x3060,0x3068)):
            start=0x1040+i*16
            view['ranges'].append(r.pe_code(caller_raw)[3](start,start+8,True))
            view['requests'].append({'role':'CallerRoot','origin':{'kind':'RuntimeSite','owner':i},
                                     'resolution':'Resolved','start_rva':start,'end_rva':start+8})
            view['edges'].append({'instruction_rva':start,'obligation':'Required',
                                  'target':{'kind':'RipRelativeIatSlot','slot_rva':slot}})
        images=[{'raw':caller_raw,'witness':view}]+imports
        for span,edge in zip(view['ranges'],view['edges']):r.follow_required_edge(directory,images,0,span,edge,census)
        return census,images

    def callers(self,summary):
        return {json.loads(root)['origin']['owner']:set(nodes) for root,nodes in summary['root_reachability'].items()
                if json.loads(root)['role']=='CallerRoot'}

    def test_same_dll_distinct_slots_keep_exact_targets_and_roots(self):
        census,images=self.imported();result=census.summary(images);callers=self.callers(result)
        sha=images[1]['witness']['image_sha256'];first=sha+':4096:4104';second=sha+':4128:4136'
        self.assertIn(first,callers[0]);self.assertNotIn(second,callers[0])
        self.assertIn(second,callers[1]);self.assertNotIn(first,callers[1])
        self.assertEqual(result['physical_unique'],4);self.assertEqual(result['logical_requests'],4)
        for node,roots in result['shared_sets'].items():
            self.assertLessEqual(sum(json.loads(root)['role']=='CallerRoot' for root in roots),1)
        self.assertEqual(result['status'],'CENSUS_INCOMPLETE_UNRESOLVED')
        self.assertTrue(all(edge['reason']=='SampledDispatchIsNotCompleteFiniteTargetSet' for edge in images[0]['witness']['edges']))

    def test_two_slots_can_share_one_physical_target_without_losing_requests(self):
        census,images=self.imported(True);result=census.summary(images);callers=self.callers(result)
        target=images[1]['witness']['image_sha256']+':4096:4104'
        self.assertIn(target,callers[0]&callers[1]);self.assertEqual(result['physical_unique'],3)
        self.assertEqual(result['logical_requests'],4)
        self.assertEqual(sum(json.loads(root)['role']=='CallerRoot' for root in result['shared_sets'][target]),2)
        self.assertNotEqual(images[1]['witness']['requests'][0]['origin'],images[2]['witness']['requests'][0]['origin'])

    def test_same_dll_and_slot_from_different_root_images_stay_separate(self):
        census,images=self.imported();first,second=images[1:]
        caller=images[0];other=copy.deepcopy(caller)
        other['raw']=other['raw'][:1801]+b'y'+other['raw'][1802:]
        other['witness']['image_sha256']=r.digest(other['raw'])
        caller['witness']['ranges']=caller['witness']['ranges'][:1]
        caller['witness']['requests']=caller['witness']['requests'][:1]
        caller['witness']['edges']=caller['witness']['edges'][:1]
        other['witness']['ranges']=other['witness']['ranges'][1:]
        other['witness']['requests']=other['witness']['requests'][1:]
        other['witness']['edges']=other['witness']['edges'][1:]
        second['root_image_sha256']=other['witness']['image_sha256']
        for phase in ('pre','post'):second[phase]['slot']['slot_rva']=0x3060
        second['witness']['requests'][0]['origin'].update(root_image_sha256=second['root_image_sha256'],slot_rva=0x3060)
        edge=other['witness']['edges'][0];edge['target']['slot_rva']=0x3060;edge['obligation']='Required'
        edge.pop('target_image_sha256');edge.pop('target_import_request')
        images=[caller,other,first,second]
        r.follow_required_edge(None,images,1,other['witness']['ranges'][0],edge,census)
        result=census.summary(images);callers=self.callers(result);sha=first['witness']['image_sha256']
        self.assertIn(sha+':4096:4104',callers[0]);self.assertNotIn(sha+':4128:4136',callers[0])
        self.assertIn(sha+':4128:4136',callers[1]);self.assertNotIn(sha+':4096:4104',callers[1])
        self.assertEqual(result['physical_unique'],4);self.assertEqual(result['logical_requests'],4)

    def test_wrong_missing_ambiguous_import_identity_cannot_invent_edges(self):
        census,original=self.imported();legal=self.callers(census.summary(original))
        target=original[1]['witness']['image_sha256']+':4096:4104';self.assertIn(target,legal[0])
        def refreshed_hashes(images):
            owner=images[1];sha='f'*64;owner['witness']['image_sha256']=sha
            owner['pre']['module_sha256']=sha;owner['post']['module_sha256']=sha
            owner['witness']['requests'][0]['image_sha256']=sha
            edge=images[0]['witness']['edges'][0];edge['target_image_sha256']=sha;edge['target_import_request']['image_sha256']=sha
            owner['witness']['requests'][0]['origin']['root_image_sha256']='e'*64
        def refreshed_extent(images):
            request=images[1]['witness']['requests'][0];request['end_rva']=0x1007
            images[1]['witness']['ranges'][0]['end_rva']=0x1007
            images[0]['witness']['edges'][0]['target_import_request']['end_rva']=0x1007
        peers={
            'slot':lambda images:images[1]['witness']['requests'][0]['origin'].update(slot_rva=0x3068),
            'root':lambda images:images[1].update(root_image_sha256='e'*64),
            'origin-root':lambda images:images[1]['witness']['requests'][0]['origin'].update(root_image_sha256='e'*64),
            'extent':lambda images:images[1]['witness']['requests'][0].update(end_rva=0x1007),
            'actual-target':lambda images:images[1]['pre']['runtime'].update(target_va=0x140001020),
            'edge-extent':lambda images:images[0]['witness']['edges'][0]['target_import_request'].update(end_rva=0x1007),
            'missing-origin':lambda images:images[1]['witness']['requests'][0].pop('origin'),
            'missing-edge-key':lambda images:images[0]['witness']['edges'][0].pop('target_import_request'),
            'same-sha-alias':lambda images:images.append(copy.deepcopy(images[1])),
            'refreshed-incidental-hashes':refreshed_hashes,
            'refreshed-wrong-extent':refreshed_extent,
        }
        for name,mutate in peers.items():
            with self.subTest(peer=name):
                images=copy.deepcopy(original);mutate(images);result=census.summary(images);callers=self.callers(result)
                self.assertEqual(len(callers[0]),1)
                self.assertEqual(result['status'],'CENSUS_INCOMPLETE_UNRESOLVED')
                self.assertTrue(any(row.get('kind')=='RequiredImportReachability' for row in result['unknowns']))
                edge=images[0]['witness']['edges'][0];edge.pop('target_image_sha256',None);edge.pop('target_import_request',None);edge['obligation']='Required'
                r.follow_required_edge(None,images,0,images[0]['witness']['ranges'][0],edge,census)
                if name not in ('edge-extent','missing-edge-key'):
                    self.assertNotIn('target_import_request',edge)


class CustodyControls(unittest.TestCase):
    def exercise(self,failure=None):
        from types import SimpleNamespace
        root=Path('/owned-custody');out=root/'control-Od';files={};events=[];reads=[];streams=[]
        state={'schema':r.CUSTODY_SCHEMA,'state':'no_writer_started','receipts':[]}
        files[root/'writer-custody.json']=json.dumps(state).encode()
        def fail(name):
            events.append(name)
            if failure==name:raise OSError(name)
            if failure==name+'-interrupt':raise KeyboardInterrupt(name)
            if failure==name+'-base':raise BaseException(name)
        def save(path,value):
            fail('receipt' if path==out/'probe.json' else 'metadata')
            files[path]=json.dumps(value).encode()
        def read(path):
            reads.append(path)
            if path.suffix in ('.stdout','.stderr'):
                self.assertTrue(all(stream.closed for stream in streams))
                self.assertIn('handle-close',events);self.assertIn('job-close',events)
                self.assertNotIn(failure,('terminate','accounting','active','wait-reap','handle-close','job-close','stream-close'))
            return files[path]
        class Stream:
            closed=False
            def __init__(self,path):self.path=path
            def close(self):fail('stream-close');self.closed=True
        def open_stream(path,mode):
            fail('stream-open');stream=Stream(path);streams.append(stream);files[path]=b'partial';return stream
        class Job:
            def setup(self):fail('setup')
            def assign(self,child):fail('assign')
            def resume(self,child):fail('resume')
            def terminate(self):fail('terminate')
            def accounting(self):
                fail('accounting')
                return SimpleNamespace(active_processes=1 if failure=='active' else 0)
            def resources(self,accounting):fail('resources');return {'peak':1}
            def close(self):fail('job-close')
        class Child:
            pid=123
            _handle=SimpleNamespace(Close=lambda:fail('handle-close'))
            waits=0
            def wait(self,timeout):
                self.waits+=1;fail('wait-first' if self.waits==1 else 'wait-reap')
                if self.waits==1 and failure=='timeout':raise subprocess.TimeoutExpired('inert',timeout)
                return 7 if failure=='nonzero' else 0
            def kill(self):fail('kill')
        def launch(*args,**kwargs):
            self.assertIn(root/'writer-pending.json',files)
            self.assertEqual(json.loads(files[root/'writer-custody.json'])['state'],'unknown')
            self.assertEqual(kwargs['creationflags'],4)
            self.assertEqual(len(streams),2)
            fail('launch');return Child()
        clock=iter(range(1000))
        contexts=[patch.object(r.sys,'platform','win32'),patch.dict(os.environ,{'GITHUB_ACTIONS':'true'}),
                  patch.object(r,'census_windows_job',lambda:Job()),patch.object(r.previous.subprocess,'Popen',launch),
                  patch.object(r.previous.time,'monotonic',lambda:next(clock)),patch.object(r.previous.time,'sleep',lambda value:None),
                  patch.object(Path,'exists',lambda path:path in files),patch.object(Path,'open',open_stream),
                  patch.object(Path,'read_bytes',read),patch.object(Path,'unlink',lambda path:files.pop(path)),patch.object(r,'write_json',save)]
        error=None;row=None
        with ExitStack() as stack:
            for context in contexts:stack.enter_context(context)
            try:row=r.census_command(out,'probe',['owned.exe'],out,{'MDS_CENSUS_CUSTODY':str(root),'MDS_CENSUS_DEADLINE':'500'},20)
            except BaseException as caught:error=caught
            unknown=root/'writer-pending.json' in files
            if unknown:
                with self.assertRaisesRegex(ValueError,'unclosed diagnostic writers'):r.census_custody(root)
                if failure!='receipt':self.assertFalse(any(path.suffix in ('.stdout','.stderr') for path in reads))
                self.assertNotIn('stdout',json.loads(files.get(out/'probe.json',b'{}')))
                with self.assertRaisesRegex(ValueError,'unclosed diagnostic writers'):
                    r.record(out,'native',['must-not-be-read'],out,{'MDS_CENSUS_CUSTODY':str(root)})
                before=list(events)
                with self.assertRaisesRegex(ValueError,'unclosed diagnostic writers'):
                    r.census_command(out,'next',['unrelated.exe'],out,{'MDS_CENSUS_CUSTODY':str(root),'MDS_CENSUS_DEADLINE':'500'},20)
                self.assertEqual(events,before)
            else:
                self.assertEqual(r.census_custody(root)['state'],'closed')
                self.assertTrue(json.loads(files[out/'probe.json'])['writer_closure'])
        self.assertFalse(any('unrelated' in event for event in events))
        return row,error,unknown,events,files

    def test_legal_closed_first_and_closed_partial_nonzero_timeout(self):
        for failure in (None,'nonzero','timeout'):
            row,error,unknown,events,files=self.exercise(failure)
            self.assertIsNone(error);self.assertFalse(unknown)
            self.assertIn('stdout',row)
            self.assertEqual(row['terminal'],'timeout' if failure=='timeout' else 'exit')
            self.assertEqual(row['status'],None if failure=='timeout' else 7 if failure=='nonzero' else 0)

    def test_setup_assignment_resume_and_baseexception_close_owned_lifetime(self):
        for failure in ('setup','assign','resume','assign-interrupt','resume-interrupt','resume-base','wait-first-interrupt'):
            with self.subTest(failure=failure):
                row,error,unknown,events,files=self.exercise(failure)
                self.assertIsNotNone(error);self.assertFalse(unknown)
                self.assertIn('job-close',events)
                if failure not in ('setup','stream-open'):self.assertIn('handle-close',events)

    def test_unknown_launch_and_all_cleanup_failures_prohibit_reads_and_next(self):
        for failure in ('stream-open','launch','launch-interrupt','terminate','terminate-interrupt','kill','accounting','active','wait-reap','handle-close','job-close','stream-close'):
            with self.subTest(failure=failure):
                row,error,unknown,events,files=self.exercise(failure)
                self.assertIsNotNone(error);self.assertTrue(unknown)
                self.assertIn('job-close',events)

    def test_resource_error_after_process_closure_still_closes_streams(self):
        row,error,unknown,events,files=self.exercise('resources')
        self.assertIsInstance(error,OSError);self.assertFalse(unknown)
        self.assertIn('resource_error',json.loads(files[Path('/owned-custody/control-Od/probe.json')]))

    def test_unwritten_receipt_never_clears_pending_marker(self):
        row,error,unknown,events,files=self.exercise('receipt')
        self.assertIsNotNone(error);self.assertTrue(unknown)

    def test_zero_receipts_require_explicit_no_writer_startup(self):
        root=Path('/owned-custody')
        def state(value):return patch.object(Path,'read_bytes',return_value=json.dumps(value).encode())
        with patch.object(Path,'exists',return_value=False):
            with state({'schema':r.CUSTODY_SCHEMA,'state':'no_writer_started','receipts':[]}):
                self.assertEqual(r.census_custody(root)['state'],'no_writer_started')
            for value in ({'schema':r.CUSTODY_SCHEMA,'state':'closed','receipts':[]},
                          {'schema':r.CUSTODY_SCHEMA,'state':'unknown','receipts':[]},
                          {'schema':r.CUSTODY_SCHEMA,'state':'closed','receipts':['unwritten.json']}):
                with state(value),self.assertRaises((ValueError,KeyError)):r.census_custody(root)
            with patch.object(Path,'read_bytes',side_effect=FileNotFoundError),self.assertRaises(FileNotFoundError):r.census_custody(root)

    def test_cli_custody_rejects_unknown_false_and_unwritten_receipts(self):
        root=Path('/owned-custody')
        for closure in (True,False,None):
            state={'schema':r.CUSTODY_SCHEMA,'state':'closed','receipts':['command.json']}
            def read(path):return json.dumps(state if path.name=='writer-custody.json' else {'writer_closure':closure}).encode()
            output=io.StringIO()
            with patch.object(sys,'argv',['run.py','--custody-check','--out',str(root)]),patch.object(Path,'exists',return_value=False),patch.object(Path,'read_bytes',read),patch.object(sys,'stdout',output):
                if closure is True:r.main()
                else:
                    with self.assertRaisesRegex(ValueError,'unclosed diagnostic writers receipt'):r.main()
            self.assertEqual(bool(output.getvalue()),closure is True)

    def test_actual_workflow_upload_has_custody_selector(self):
        workflow=(r.ROOT/'.github/workflows/renderer-closure-census.yml').read_text()
        self.assertIn('id: custody',workflow)
        self.assertIn('if: always() && steps.custody.outputs.upload == \'true\'',workflow)
        gate=workflow.split('name: Derive diagnostic writer custody',1)[1].split('name: Retain closed',1)[0]
        self.assertIn('"upload=false" >> $env:GITHUB_OUTPUT',gate)
        self.assertIn('--custody-check --out $evidence',gate)
        self.assertLess(gate.index('if ($LASTEXITCODE)'),gate.index('"upload=true"'))
        self.assertIn("-eq 'no_acquisition_started'",gate)
        self.assertIn("throw 'Acquisition custody is unknown",gate)
        self.assertIn("branches: [w4-renderer-bounded-documents]",workflow)


class BoundedDocumentControls(unittest.TestCase):
    def fixture(self,value=...):
        value={'created_ns':1781234567890123456,'nested':[{},[],None,True,False,1,1.0,-0.0,'雪😀\r\n'],
               'first_ordinary_violation':{'snapshot':['original']},'long':'雪😀'*150} if value is ... else value
        raw,binding,pages=r.bound_document(value,'manifest.json',1024)
        files={'manifest.json':raw,'manifest.json.binding.json':binding}|pages
        inventory={name:{'size':len(body),'sha256':r.digest(body)} for name,body in files.items()}
        return value,files,inventory

    def admit(self,files,inventory):
        reads=[]
        def read(name):
            self.assertNotEqual(name,'manifest.json','opaque original must never be read/parsed')
            reads.append(name);return files[name]
        return r.admit_bound_document('manifest.json.binding.json',inventory,read)

    def replace(self,files,inventory,name,value):
        body=r.bound_bytes(value);files[name]=body;inventory[name]={'size':len(body),'sha256':r.digest(body)}
        if '.pages/' in name:
            index=r.bound_json(files['manifest.json.binding.json'])
            for row in index['pages']:
                if row['name']==name:row.update(inventory[name])
            self.replace(files,inventory,'manifest.json.binding.json',index)

    def test_bound_roundtrip_types_and_same_original_bytes(self):
        value,files,inventory=self.fixture()
        self.assertEqual(self.admit(files,inventory),value)
        restored=self.admit(files,inventory)
        self.assertIs(type(restored['nested'][5]),int);self.assertIs(type(restored['nested'][6]),float)
        self.assertEqual(struct.pack('d',restored['nested'][7]),struct.pack('d',-0.0))
        self.assertTrue(all(len(raw)<=1024 for name,raw in files.items() if '.pages/' in name))
        self.assertGreater(sum('.pages/' in name for name in files),1)
        self.assertEqual(files['manifest.json'],r.bound_bytes(value))
        self.assertTrue(files['manifest.json'].endswith(b'\n'));self.assertNotIn(b'\r',files['manifest.json'])
        for scalar in ({},[],None,False,1,1.0,'',{'sentinel':{'$ref':0}}):
            _,files,inventory=self.fixture(scalar)
            self.assertEqual(self.admit(files,inventory),scalar)

    def test_bound_unicode_scalar_controls(self):
        for value in ('\U00010000',{'\U00010000':'😀'}):
            _,files,inventory=self.fixture(value)
            self.assertEqual(self.admit(files,inventory),value)
        peers=[(b'"\\ud800"\n',[['string',1],['fragment','\ud800']]),
               (b'"\\udfff"\n',[['string',1],['fragment','\udfff']]),
               (b'{\n  "\\ud800": 1\n}\n',
                [['object',1],['string',1],['fragment','\ud800'],['scalar',1]]),
               (b'"\\ud800\\udc00"\n',
                [['string',2],['fragment','\ud800'],['fragment','\udc00']])]
        for raw,records in peers:
            with self.subTest(raw=raw):
                _,files,inventory=self.fixture('a')
                files['manifest.json']=raw
                inventory['manifest.json']={'size':len(raw),'sha256':r.digest(raw)}
                page=next(n for n in files if '.pages/' in n)
                body=r.bound_json(files[page]);body['records']=records
                self.replace(files,inventory,page,body)
                index=r.bound_json(files['manifest.json.binding.json'])
                index['original'].update(inventory['manifest.json'])
                self.replace(files,inventory,'manifest.json.binding.json',index)
                self.assertEqual(index['original'],dict(name='manifest.json',**inventory['manifest.json']))
                for name,body in files.items():
                    self.assertEqual(inventory[name],{'size':len(body),'sha256':r.digest(body)})
                with self.assertRaisesRegex(ValueError,'bounded UTF-8 string fragment'):
                    self.admit(files,inventory)

    def test_bound_preflight_del_serialized_size(self):
        for value in ('\x7e','\x7f','\x80',{'\x7f':'\x7f'}):
            with self.subTest(value=value):
                self.assertGreaterEqual(r.bound_preflight(value),len(r.bound_bytes(value)))
        self.assertEqual(r.bound_bytes('\x7f'),b'"\\u007f"\n')
        self.assertEqual(r.bound_preflight('\x7f'),9)

    def test_bound_inventory_same_bytes_before_any_page_parse(self):
        for kind in ('missing','extra','size','sha','bytes','original','original-newline','alias','case-alias','slash-alias'):
            _,files,inventory=self.fixture();page=next(n for n in files if '.pages/' in n)
            if kind=='missing':del inventory[page]
            elif kind=='extra':inventory['manifest.json.pages/99999.json']=dict(inventory[page])
            elif kind=='size':inventory[page]['size']=True
            elif kind=='sha':inventory[page]['sha256']='0'*64
            elif kind=='bytes':files[page]+=b' '
            elif kind=='original':inventory['manifest.json']['sha256']='1'*64
            elif kind=='original-newline':
                raw=files['manifest.json'].replace(b'\n',b'\r\n');inventory['manifest.json']={'size':len(raw),'sha256':r.digest(raw)}
            elif kind=='case-alias':inventory[page.upper()]=dict(inventory[page])
            elif kind=='slash-alias':inventory[page.replace('/','\\')]=dict(inventory[page])
            else:
                index=r.bound_json(files['manifest.json.binding.json']);index['pages'][0]['name']='manifest.json.pages/../other'
                self.replace(files,inventory,'manifest.json.binding.json',index)
            with self.subTest(kind=kind),self.assertRaises((ValueError,KeyError)):self.admit(files,inventory)

    def test_bound_closed_index_and_order_controls(self):
        for kind in ('duplicate','reorder','missing','extra','root-bool','schema','serializer','limits','original-name'):
            _,files,inventory=self.fixture();index=r.bound_json(files['manifest.json.binding.json'])
            if kind=='duplicate':index['pages'].append(index['pages'][0])
            elif kind=='reorder':index['pages'].reverse()
            elif kind=='missing':index['pages'].pop()
            elif kind=='extra':index['unexpected']=0
            elif kind=='root-bool':index['root']=False
            elif kind=='schema':index['schema']='foreign'
            elif kind=='serializer':index['serializer']['newline']='CRLF'
            elif kind=='limits':index['limits']['depth']+=1
            else:index['original']['name']='../manifest.json'
            self.replace(files,inventory,'manifest.json.binding.json',index)
            with self.subTest(kind=kind),self.assertRaises((ValueError,KeyError)):self.admit(files,inventory)

    def test_bound_closed_typed_records_and_raw_binding(self):
        for records in ([['array',True]],[['array',2],['scalar',1]],
                        [['scalar',{'$ref':0}]],[['reference',0]],[['scalar',1],['scalar',2]],
                        [['object',2],['string',1],['fragment','a'],['scalar',1],['string',1],['fragment','a'],['scalar',2]],
                        [['object',2],['string',1],['fragment','z'],['scalar',1],['string',1],['fragment','a'],['scalar',2]],
                        [['string',1],['fragment','xx']],[['scalar',2]]):
            _,files,inventory=self.fixture(1);page=next(n for n in files if '.pages/' in n)
            body=r.bound_json(files[page]);body['records']=records
            self.replace(files,inventory,page,body)
            with self.subTest(records=records),self.assertRaises(ValueError):self.admit(files,inventory)

    def test_bound_strict_parser_and_finite_budgets(self):
        for raw in (b'{"a":0,"a":1}',b'NaN',b'Infinity',b'1e999',b'9'*100,b'"\xff"',b'['*129+b'0'+b']'*129):
            with self.subTest(raw=raw),self.assertRaises((ValueError,UnicodeError)):r.bound_json(raw)
        for value in (float('nan'),float('inf'),2**300,{1:'bad'},object()):
            with self.assertRaises(ValueError):r.bound_document(value,'manifest.json',1024)
        for budget in (True,511,r.BOUND_PAGE_BYTES+1):
            with self.assertRaises(ValueError):r.bound_document({},'manifest.json',budget)
        value={}
        for _ in range(r.BOUND_LIMITS['depth']+1):value=[value]
        with self.assertRaises(ValueError):r.bound_document(value,'manifest.json',1024)
        with patch.dict(r.BOUND_LIMITS,shards=1):
            with self.assertRaises(ValueError):self.fixture()
        with patch.dict(r.BOUND_LIMITS,document_bytes=64):
            with self.assertRaises(ValueError):self.fixture()

    def test_bound_writer_serializes_original_once_and_preserves_final_object(self):
        files={};path=Path('/inert/closure-census.json');value={'created_ns':456,'snapshot':[{},'雪']};calls=[]
        serializer=r.bound_bytes
        def serialize(item):
            if item is value:calls.append(True)
            return serializer(item)
        with patch.object(r,'bound_bytes',serialize),patch.object(Path,'write_bytes',lambda path,raw:files.__setitem__(path,raw)),patch.object(Path,'mkdir'):
            r.write_bound_document(path,value)
        self.assertEqual(len(calls),1)
        self.assertEqual(files[path],serializer(value))
        members={name.relative_to(path.parent).as_posix():raw for name,raw in files.items()}
        inventory={name:{'size':len(raw),'sha256':r.digest(raw)} for name,raw in members.items()}
        self.assertEqual(r.admit_bound_document('closure-census.json.binding.json',inventory,members.__getitem__),value)

    def test_bound_preflight_covers_serializer_and_small_limits(self):
        values=[{},[],None,True,False,0,-1,2**255,-2**255,1.0,-0.0,1e-300,
                {'z':'ascii','a':['\\\"\b\f\n\r\t\x00雪😀',{},[]]},'x'*32]
        for value in values:
            with self.subTest(value=value):
                self.assertGreaterEqual(r.bound_preflight(value),len(r.bound_bytes(value)))
        value='x'*32;size=len(r.bound_bytes(value))
        with patch.dict(r.BOUND_LIMITS,document_bytes=32*12+8):
            self.assertEqual(r.bound_preflight(value),size)
        nested=0
        for _ in range(4):nested=[nested]
        with patch.dict(r.BOUND_LIMITS,depth=4):r.bound_preflight(nested)
        with patch.dict(r.BOUND_LIMITS,depth=3):
            with self.assertRaises(r.BoundDocumentLimit):r.bound_preflight(nested)
        near=[]
        for _ in range(20):near=[near]
        size=len(r.bound_bytes(near))
        with patch.dict(r.BOUND_LIMITS,document_bytes=size):self.assertEqual(r.bound_preflight(near),size)
        with patch.dict(r.BOUND_LIMITS,document_bytes=size-1):
            with self.assertRaises(r.BoundDocumentLimit):r.bound_preflight(near)
        shared=[];r.bound_preflight([shared,shared])

    def test_bound_preflight_refusal_never_serializes_or_writes(self):
        cyclic=[];cyclic.append(cyclic)
        class StringSubclass(str):pass
        for value,limits in [('x'*33,{'document_bytes':32*12+8}),
                             ('x'*33,{'cumulative_bytes':64}),
                             ({'a':0},{'references':1}),([[[0]]],{'depth':2}),
                             (cyclic,{}),({'a':float('inf')},{}),(2**300,{}),
                             ({1:'bad'},{}),(StringSubclass('bad'),{}),('\ud800',{})]:
            path=Path('/inert/manifest.json');binding=path.with_name('manifest.json.binding.json')
            files={path:b'previous original\n',binding:b'previous binding\n'};before=dict(files)
            with self.subTest(kind=type(value),limits=limits),patch.dict(r.BOUND_LIMITS,limits),\
                 patch.object(r,'bound_bytes',side_effect=AssertionError('serializer before refusal')),\
                 patch.object(Path,'write_bytes',lambda path,raw:files.__setitem__(path,raw)):
                result=r.write_bound_document(path,value)
            self.assertEqual(files,before)
            self.assertEqual(result['kind'],'incomplete');self.assertFalse(result['original_created'])
            self.assertEqual(result['semantic_status'],'UNRUN')
        files={};path=Path('/inert/new.json')
        with patch.dict(r.BOUND_LIMITS,document_bytes=1),patch.object(r,'bound_bytes',side_effect=AssertionError('serializer')),\
             patch.object(Path,'write_bytes',lambda path,raw:files.__setitem__(path,raw)):
            r.write_bound_document(path,0)
        self.assertEqual(files,{})

    def test_bound_writer_retains_original_on_partition_overflow(self):
        files={};path=Path('/inert/manifest.json');value={'created_ns':123,'long':'x'*200}
        with patch.object(Path,'write_bytes',lambda path,raw:files.__setitem__(path,raw)),patch.object(r,'bound_document',side_effect=r.BoundDocumentLimit('partition overflow')):
            r.write_bound_document(path,value)
        self.assertEqual(files[path],r.bound_bytes(value))
        self.assertEqual(r.bound_json(files[path.with_name('manifest.json.binding.json')])['kind'],'incomplete')


if __name__=='__main__':unittest.main(verbosity=2)
