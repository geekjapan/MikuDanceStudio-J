#!/usr/bin/env python3
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
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
    rows.append({'stage':'end','status':0})
    return rows


def wire(rows):return ('\n'.join('FP '+json.dumps(row) for row in rows)+'\n').encode()


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
            self.assertIn(transform,generated[r.MESH])
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
                     'env':{'CARGO_TARGET_DIR':recipe['target'],'CARGO_INCREMENTAL':'0','RUSTFLAGS':'--cfg mds_floor_profile --check-cfg=cfg(mds_floor_profile)','CL':'','_CL_':''}}
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
                  ['C:\\VS\\link.exe','/OUT:'+str(exe),str(native),str(library)]]
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
            receipt={'argv':recipe['commands']['native-build'],'cwd':recipe['cwd']['native-build'],'env':{'CARGO_TARGET_DIR':recipe['target'],'CARGO_INCREMENTAL':'0','RUSTFLAGS':'--cfg mds_floor_profile --check-cfg=cfg(mds_floor_profile)','CL':'','_CL_':''},'status':0,'terminal':'exit','start_ns':1,'end_ns':2,'start_utc':'start','end_utc':'end'}
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
                         original_native_binary={'path':str(r.PureWindowsPath(recipe['native_target'])/'Release/floor_profile.exe'),'sha256':r.digest(b'MZ')},
                         original_rust_binary={'path':'synthetic-cargo-executable','sha256':r.digest(b'MZ')})
                builds.append(b)
                for name in binaries:files[directory/name]=b'MZ'
                files[directory/'mikudancestudio_core.lib']=b'synthetic-archive'
                for label in recipe['commands']:
                    stdout=(wire(n) if label=='native' else wire(p)+b'test result: ok. 1 passed; 0 failed; 0 ignored;\n' if label=='rust' else b'test result: ok. 1 passed; 0 failed; 0 ignored;\n' if label in ('mesh_dump','x_files') else b'')
                    receipt={'argv':copy.deepcopy(recipe['commands'][label]),'cwd':recipe['cwd'][label],
                             'env':{'CARGO_TARGET_DIR':recipe['target'],'CARGO_INCREMENTAL':'0','RUSTFLAGS':'--cfg mds_floor_profile --check-cfg=cfg(mds_floor_profile)','CL':'','_CL_':''}}
                    if label in ('native','rust'):receipt['executed_binary']={'path':recipe['commands'][label][0],'sha256':r.digest(b'MZ'),'size':2}
                    if label=='native-build':stdout=native_log(b'',recipe)
                    receipts[(id,label)]=(receipt,stdout,b'');files[directory/(label+'.stdout')]=stdout;files[directory/(label+'.stderr')]=b''
        manifest={'schema':r.SCHEMA,'fp_observation_contract':r.FP_CONTRACT,'base':r.BASE,'head':'1'*40,'paths':r.PATHS,'runner_temp':'C:/runner/temp','input_root':r.recipe('C:/runner/temp','control','Od')['input_root'],'builds':builds}
        result={'schema':r.SCHEMA,'fp_observation_contract':r.FP_CONTRACT,'head':'1'*40,'results':{opt:r.classify(*parsed['observed-'+opt]) for opt in ('Od','O2')},'hosted':'ExecutedWindowsOnly','profile_adoption':'NotAuthorized'}
        def encode(value):return json.dumps(value).encode()
        def inventory(_):return {str(path.relative_to(out)):{'sha256':r.digest(raw),'size':len(raw)} for path,raw in files.items() if path!=out/'seal.json'}
        def seal():
            files[out/'manifest.json']=encode(manifest);files[out/'result.json']=encode(result)
            files[out/'seal.json']=encode({'schema':r.SCHEMA,'files':inventory(out)})
        seal()
        with patch.object(Path,'read_bytes',lambda path:files[path]),patch.object(Path,'read_text',lambda path,**kwargs:files[path].decode()),patch.object(r.previous,'evidence_inventory',inventory),patch.object(r,'verify_sources'),patch.object(r,'checked',lambda directory,label:receipts[(directory.name,label)]),patch.object(r,'native_provenance',lambda commands,recipe,*args:str(r.PureWindowsPath(recipe['native_target'])/'Release/floor_profile.exe')),patch.object(r,'cargo_binary',return_value='synthetic-cargo-executable'),patch.object(r,'pe_exports',return_value=exports):
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
                             'CARGO_INCREMENTAL':'0','RUSTFLAGS':'--cfg mds_floor_profile --check-cfg=cfg(mds_floor_profile)',
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

    def test_zz_real_effects_rejected_before_effects(self):
        target=Path('/Users/geekjapan/.codex/orchestrate/mikudance-rust-20261027/renderer-floor-profile-boundary-fix/effect-probe')
        self.assertFalse(target.exists());r.readonly()
        probes=[lambda:target.write_bytes(b'forbidden'),lambda:target.mkdir(),lambda:subprocess.run([sys.executable,'-c','raise SystemExit(99)'],check=True),lambda:socket.socket()]
        for probe in probes:
            with self.assertRaises(ValueError):probe()
        self.assertFalse(target.exists())


if __name__=='__main__':unittest.main(verbosity=2)
