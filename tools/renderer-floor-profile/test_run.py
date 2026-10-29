#!/usr/bin/env python3
import copy
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
    rows.append({'stage':'runtime-read','words':r.corpus_words(r.operation_corpus())})
    def op(kind,owner,input,output):
        row={'stage':'operation','kind':kind,'owner':owner,'input':input,'output':output,
             'samples':[8064,8064],'sites':[8200,8201] if kind=='DllCall' else [8200,8201,8202,8203,8204],'base':8192}
        if kind=='DllCall':row['target']=4098
        else:
            row.update(values=[r.word(1. if owner[1]==0 else 3.),0x3f7ff000 if owner[1]==0 else 0x3eaaa000,0x3f7fffff if owner[1]==0 else 0x3eaaaaaa],
                       destination=output[:] if owner[0]==2 else [0,0,0])
            if kind=='RustEndpoint':row['values']=[0]*3;row['sites']=[8200,0,8202,0,0]
        rows.append(row)
    corpus=r.corpus_words(r.operation_corpus())
    for i in range(2):
        output=[0x3f7fffff,0x3f7fffff,0xbf7fffff] if i==0 else [0x3eaaaaaa,0x3eaaaaaa,0xbeaaaaaa]
        for kind in (('DllCall',) if language=='native' else (('RustTable' if observed else 'RustEndpoint'),'HardwareSeedWithFrozenRefinement')):
            op(kind,[1,i,0,0],corpus[i*19:(i+1)*19],output)
    if language=='rust':
        rows.append({'stage':'merge-read','bytes':list(r.inputs(lambda p:(r.ROOT/p).read_bytes())[1]['bytes'])})
        if observed:rows.append(lineage())
        op('RustTable' if observed else 'RustEndpoint',[2,0,0,0],list(map(r.word,r.POINTS[0]+r.IDENTITY)) if observed else [0]*19,[0]*3)
        if observed:rows.append({'stage':'runtime-imports','phase':'post'})
    rows.append({'stage':'end','status':0})
    return rows


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
    struct.pack_into('<II',raw,optional+136,0x2000,12)
    for i,(name,va,size,offset,flags) in enumerate([(b'.text',0x1000,256,1024,0x60000020),(b'.pdata',0x2000,12,1280,0x40000040)]):
        at=392+i*40;raw[at:at+len(name)]=name;struct.pack_into('<IIII',raw,at+8,size,va,size,offset);struct.pack_into('<I',raw,at+36,flags)
    struct.pack_into('<III',raw,1280,0x1000,0x1008,0x3000);raw[1024:1032]=b'\x90'*7+b'\xc3'
    mapping=b' Preferred load address is 0000000140000000\n 0001:00000000 mds_accessory_transform_coord 0000000140001000 f object.obj\n'
    rows=[{'owner':[1,0,0,0],'base':8192,'sites':[8192+0x1001,0,8192+0x1007,0,0]}]
    assembly=('\n'.join(f'14000100{i}:  {v:02x}  '+('ret' if i==7 else 'nop') for i,v in enumerate(raw[1024:1032]))+'\n').encode()
    return bytes(raw),mapping,rows,assembly


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
        def inventory(_):return {str(path.relative_to(out)):{'sha256':r.digest(raw),'size':len(raw)} for path,raw in files.items() if path!=out/'seal.json'}
        def seal():
            files[out/'manifest.json']=encode(manifest);files[out/'result.json']=encode(result)
            files[out/'seal.json']=encode({'schema':r.SCHEMA,'files':inventory(out)})
        seal()
        read_bytes=Path.read_bytes;read_text=Path.read_text
        with patch.object(Path,'read_bytes',lambda path:files[path] if path in files else read_bytes(path)),patch.object(Path,'read_text',lambda path,**kwargs:files[path].decode() if path in files else read_text(path,**kwargs)),patch.object(r.previous,'evidence_inventory',inventory),patch.object(r,'verify_sources'),patch.object(r,'checked',lambda directory,label:receipts[(directory.name,label)]),patch.object(r,'native_provenance',lambda commands,recipe,*args:str(r.PureWindowsPath(recipe['native_target'])/'Release/floor_profile.exe')),patch.object(r,'cargo_binary',return_value='synthetic-cargo-executable'),patch.object(r,'pe_exports',return_value=exports),patch.object(r,'compiled_evidence',return_value={}):
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
            raw=(b'1'*40 if label=='git-head' else '\n'.join(r.PATHS).encode() if label=='git-paths' else
                 fixtures[label] if label in ('mesh_dump','x_files') else b'')
            files[directory/(label+'.stdout')]=raw;files[directory/(label+'.stderr')]=b''
            return {'status':0}
        def boundary(label,stdout,stderr):
            validator(label,stdout,stderr);captured.append(label)
            if label=='x_files':raise Complete()
        def parse(raw,language,observed):return {'dll':{'path':'synthetic-dll'}} if language=='native' else {}
        with patch.object(r.sys,'platform','win32'),patch.dict(os.environ,{'GITHUB_ACTIONS':'true','RUNNER_TEMP':'C:/runner/temp','GITHUB_SHA':'1'*40}), \
             patch.object(Path,'exists',return_value=False),patch.object(Path,'is_file',return_value=True),patch.object(Path,'mkdir'), \
             patch.object(Path,'read_bytes',lambda path:files.get(path,b'')),patch.object(Path,'read_text',lambda path,**kwargs:files.get(path,b'').decode()),patch.object(Path,'write_bytes'), \
             patch.object(r,'record',record),patch.object(r.shutil,'copyfile'),patch.object(r.shutil,'copytree'),patch.object(r.c,'safe_tar',return_value={}), \
             patch.object(r.c,'source_inventory',return_value={}),patch.object(r,'inputs',return_value=[]),patch.object(r,'source_expected',return_value=({}, {}, {})), \
             patch.object(r,'native_commands',return_value=[]),patch.object(r,'parse',parse),patch.object(r,'cargo_binary',return_value='synthetic-cargo'), \
             patch.object(r,'fixture_result',boundary):
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
            elif name=='destination':next(v for v in rows if v.get('owner')==[2,0,0,0])['destination'][0]=r.word(.5)
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
        rust_witness=r.required_code_ranges(raw,rows,mapping)
        rust_witness['same_link_map']=witness['same_link_map']
        rust_witness['caller_windows']=r.caller_windows({'operations':rows,'merge_lineage':lineage()})
        rust_witness['data_requests']=[{'synthetic':'seed bytes separately tested'}]
        rust_witness['copy_obligations']=[{'size':176,'role':'OperationReturn','status':'RequiresIndependentCallerRegionAndPathReview'},
                                         {'size':8192,'role':'OdSeedTable','status':'RequiresIndependentCallerRegionAndPathReview'}]
        for address in (lineage()['returned'][4],*[a[9] for a in lineage()['rows']]):
            r.request_range(rust_witness,raw,address-8192,'MergePointerLineage',{'kind':'RuntimeSite','role':'MergeStorage'})
        rust_witness['edges']=r.instruction_edges(assembly,rust_witness,rust_witness['ranges'][0])
        rust_witness.update(runtime_images=[],logical_request_count=len(rust_witness['requests']),physical_range_count=len(rust_witness['ranges']))
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
            argv=r.disassembly_argv(r.PureWindowsPath(recipe['evidence'])/name,witness,witness['ranges'][0])
            receipts[language+'-instructions-0']=({'argv':argv,'cwd':recipe['source'],'tool_binary':copy.deepcopy(tool)},assembly,b'')
        parsed=({'operations':rows},{'operations':rows,'merge_lineage':lineage()})
        with patch.object(Path,'read_bytes',lambda path:files[path]),patch.object(r,'checked',lambda directory,label:receipts[label]),patch.object(r,'runtime_images',return_value=[]),patch.object(r,'seed_data',return_value={'synthetic':'seed bytes separately tested'}):
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

    def test_36_build_row_survives_optional_acquisition_failure(self):
        tree=ast.parse(Path(r.__file__).read_bytes());run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
        loop=next(n for n in run.body if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='opt').body[0]
        start=next(i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='b')
        block=compile(ast.Module(body=loop.body[start:],type_ignores=[]),str(r.__file__),'exec')
        for failure in (True,False):
            state=dict(r.__dict__,id='observed-Od',variant='observed',opt='Od',source=Path('/source'),target=Path('/target'),directory=Path('/evidence/observed-Od'),commands={},patches={},expected={},actual=[],binaries={},objects={},native_target=Path('/native'),executable='/rust.exe',creation=123,parsed={},out=Path('/evidence'),m={'builds':[]},native={},rust={},r={},e={})
            retained=[]
            def acquire(*args):
                self.assertEqual(len(retained),1)
                self.assertEqual(retained[0]['builds'][0]['runtime_corpus']['created_ns'],123)
                self.assertNotIn('compiled_capture',retained[0]['builds'][0])
                if failure:raise ValueError('acquisition failed')
                return {'native':{},'rust':{}}
            state['compiled_evidence']=acquire;state['write_json']=lambda path,value:retained.append(copy.deepcopy(value))
            with patch.object(Path,'read_bytes',return_value=b'compiled image'),patch.object(r.c,'source_inventory',return_value={}):
                if failure:
                    with self.assertRaisesRegex(ValueError,'acquisition failed'):exec(block,state)
                    self.assertEqual(len(retained),1)
                    self.assertEqual(state['parsed'],{})
                else:
                    exec(block,state)
                    self.assertEqual(len(retained),2)
                    self.assertEqual(retained[1]['builds'][0]['compiled_capture'],{'native':{},'rust':{}})

    def test_37_leaf_candidate_and_signed_import_thunk(self):
        raw,mapping,rows,_=code_fixture();changed=bytearray(raw)
        struct.pack_into('<II',changed,288,0,0)
        mapping+=b' 0001:00000008 next_leaf 0000000140001008 f object.obj\n'
        witness=r.required_code_ranges(bytes(changed),rows,mapping)
        self.assertEqual(witness['requests'][0]['extent_kind'],'NextDistinctExecutableSymbolCandidateOnly')
        self.assertEqual(witness['ranges'][0]['end_rva'],0x1008)
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
        many=dict(view,ranges=view['ranges']*128,sections=[])
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
        candidate=copy.deepcopy(edge);self.assertTrue(r.formatting_exclusion(candidate,view,view['ranges'][0]))
        self.assertEqual(candidate['classification'],'CandidateRequiringIndependentSemanticReview')
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

    def test_zz_real_effects_rejected_before_effects(self):
        target=Path('/Users/geekjapan/.codex/orchestrate/mikudance-rust-20261027/renderer-operation-boundary/effect-probe')
        self.assertFalse(target.exists());r.readonly()
        probes=[lambda:target.write_bytes(b'forbidden'),lambda:target.mkdir(),lambda:subprocess.run([sys.executable,'-c','raise SystemExit(99)'],check=True),lambda:socket.socket()]
        for probe in probes:
            with self.assertRaises(ValueError):probe()
        self.assertFalse(target.exists())


if __name__=='__main__':unittest.main(verbosity=2)
