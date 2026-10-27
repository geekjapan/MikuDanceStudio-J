#!/usr/bin/env python3
"""Same-host importer/math diagnostic. Without --run, replay only reads evidence."""
import argparse
import importlib.util
import json
import math
import ntpath
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import struct
import sys
import tarfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = '77b3e431bc1ac2ab5610692f2e12c903a7629090'
BASE_TREE = '778782dc8ad6352585a9b7eeb135c04150d1f2e4'
SCHEMA = 'mds-floor-profile-v2'
PARENT = 'd512df053e6025f958d2a8a106307d89237a63e1'
FP_CONTRACT = {'snapshot':'HardwareMxcsr', 'identity':'SourceSiteOnly',
               'rust_operation_ordering':'Unproved', 'exception_attribution':'Unsupported',
               'operation_environment':'Unproved'}
PATHS = ['.github/workflows/renderer-floor-profile.yml'] + [
    'tools/renderer-floor-profile/'+n for n in
    ('run.py','native.cpp.in','native_observer.hpp','observer.rs','test_run.py')]
MESH = 'rust/crates/mds-accessory/src/mesh.rs'
ACCESSORY = 'src/render/accessory.cpp'
FLOOR = 'tests/fixtures/rust/golden2/shadow_floor.x'
FLOOR_SHA = 'adfd3e6fb4b552f6c38eb9b94bc8b75061270e7d24a4933694c73df02e58122c'
IDENTITY = [1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.]
AFFINE = [2.,0.,0.,0.,0.,3.,0.,0.,0.,0.,4.,0.,.5,2.,-.25,1.]
PROJECTIVE = IDENTITY[:-1]+[3.]
MATRICES = [IDENTITY,AFFINE,PROJECTIVE]
POINTS = [[-1.,0.,-1.],[-1.,0.,1.],[1.,0.,1.],[1.,0.,-1.],[1.,1.,-1.]]
CASES = [('floor-top',FLOOR,None),('floor-identity',FLOOR,0),
         ('floor-affine',FLOOR,1),('cube','tests/fixtures/rust/accessory/cube.x',None),
         ('frames','tests/fixtures/rust/accessory/frames.x',None)]

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

previous = module('profile_prior', 'tools/renderer-floor-geometry/run.py')
c = previous.c
h = c.h
require, digest, load_json = previous.require, previous.digest, previous.load_json
checked, readonly = previous.checked, previous.readonly

def record(out,label,argv,cwd,env,timeout=1200):
    binary=Path(argv[0]).read_bytes() if label in ('native','rust') else None
    row=previous.record(out,label,argv,cwd,env,timeout)
    if 'RUSTFLAGS' in env:
        for key in ('RUSTFLAGS','CL','_CL_'):row['env'][key]=env[key]
    if binary is not None:
        require(Path(argv[0]).read_bytes()==binary,'executed retained binary changed')
        row['executed_binary']={'path':str(argv[0]),'sha256':digest(binary),'size':len(binary)}
    write_json(out/(label+'.json'),row)
    return row


def write_json(path, value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8')


def word(x):
    return struct.unpack('<I',struct.pack('<f',x))[0]


def words(values):
    require(type(values) is list and all(type(v) is int and 0 <= v <= 0xffffffff for v in values),'u32 words')
    return values


def finite(values):
    words(values)
    require(all(math.isfinite(struct.unpack('<f',struct.pack('<I',v))[0]) for v in values),'finite initialized float')
    return values


def inputs(read):
    floor=read(FLOOR)
    require(len(floor)==451 and digest(floor)==FLOOR_SHA,'fixed floor bytes')
    result=[]
    for id,path,matrix in CASES:
        original=read(path); raw=original;prefix=b'';suffix=b''
        if matrix is not None:
            text=','.join(str(v) for v in MATRICES[matrix])
            prefix=('\nFrame Diagnostic {\nFrameTransformMatrix {\n'+text+';;\n}\n').encode()
            suffix=b'\n}\n'
            raw=original[:16]+prefix+original[16:]+suffix
            require(raw[:16]+raw[16+len(prefix):-len(suffix)]==original,'wrapper inverse')
        result.append({'id':id,'source':path,'matrix':matrix,'sha256':digest(raw),'size':len(raw),
                       'original_sha256':digest(original),'prefix':prefix.hex(),'suffix':suffix.hex(),'bytes':raw})
    return result


def input_manifest(rows):
    return [{k:v for k,v in row.items() if k!='bytes'} for row in rows]


def insert(raw,anchor,addition):
    require(raw.count(anchor)==1,'unique insertion anchor '+repr(anchor))
    offset=raw.index(anchor)+len(anchor)
    generated=raw[:offset]+addition+raw[offset:]
    patch={'offset':offset,'anchor_hex':anchor.hex(),'original_sha256':digest(raw),
           'generated_sha256':digest(generated),'inserted_hex':addition.hex(),'original_hex':raw.hex()}
    require(inverse(generated,patch)==raw,'complete insertion inverse')
    return generated,patch


def inverse(raw,patch):
    require(digest(raw)==patch['generated_sha256'],'generated inverse binding')
    offset=patch['offset']; addition=bytes.fromhex(patch['inserted_hex'])
    require(raw[offset:offset+len(addition)]==addition,'inverse bytes')
    result=raw[:offset]+raw[offset+len(addition):]
    require(result.hex()==patch['original_hex'] and digest(result)==patch['original_sha256'],'original inverse identity')
    return result


def generated(read,observed,input_root):
    input_root=PureWindowsPath(str(input_root))
    patches={};result={}
    def add(path,anchor,text):
        raw=result.get(path,read(path))
        raw,patch=insert(raw,anchor,text)
        original=read(path)
        require(original.count(anchor)==1,'unique original physical anchor')
        patch.update(original_offset=original.index(anchor)+len(anchor),base_sha256=digest(original))
        result[path]=raw;patches.setdefault(path,[]).append(patch)
    add('CMakeLists.txt',read('CMakeLists.txt'),b'''
add_executable(floor_profile native.cpp)
target_include_directories(floor_profile PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(floor_profile PRIVATE mikudancestudio_core MMEffect dsound bcrypt)
target_compile_options(mikudancestudio_core PRIVATE @OPT@)
target_compile_options(floor_profile PRIVATE @OPT@)
''')
    if observed:
        add(ACCESSORY,b'#include "mikudancestudio/ported_funcs.hpp"',b'\n#include "../../native_observer.hpp"')
        add(ACCESSORY,b'    TraceAccessoryLoadStage("mesh-loaded", mesh);',b'\n    ::FloorProfileRaw(mesh);')
        add(MESH,b'    let nodes = xfile::parse(data)?;',b'\n    #[cfg(mds_floor_profile)] floor_profile::parsed(&nodes);')
        anchor=b'        return Err(Error::NoMesh);\n    }\n'
        add(MESH,anchor,b'    #[cfg(mds_floor_profile)] floor_profile::premerge(&containers);\n')
        add(MESH,b'    if single {\n        mesh.attribute_table = attribute_table(&mesh.indices, &mesh.face_material);\n    }\n',b'    #[cfg(mds_floor_profile)] floor_profile::merged(&mesh);\n')
    observer=(HERE/'observer.rs').read_text()
    observer=observer.replace('@CASES@',','.join('('+json.dumps(id)+',include_bytes!('+json.dumps(str(input_root/(id+'.x')))+'))' for id,_,_ in CASES))
    observer=observer.replace('@MATRICES@',repr(MATRICES)).replace('@POINTS@',repr(POINTS))
    add(MESH,read(MESH)[-40:],b'\n#[cfg(mds_floor_profile)]\nmod floor_profile {\n'+observer.encode()+b'\n}\n')
    cpp=(HERE/'native.cpp.in').read_text()
    cpp=cpp.replace('@IDS@',','.join(json.dumps(id) for id,_,_ in CASES))
    cpp=cpp.replace('@FILES@',','.join('L'+json.dumps(str(input_root/(id+'.x'))) for id,_,_ in CASES))
    for key,value in [('@MATRICES@',MATRICES),('@POINTS@',POINTS)]:
        cpp=cpp.replace(key,repr(value).replace('[','{').replace(']','}'))
    result['native.cpp']=cpp.encode();result['native_observer.hpp']=(HERE/'native_observer.hpp').read_bytes()
    return result,patches


def material_count(value,empty=False):
    require(type(value) is int and (0 if empty else 1) <= value <= 10000,'material count')
    return value


def snapshot(raw, language, stage, case=None, operation=None, matrix=None, point=None):
    require(type(raw) is int and 0 <= raw <= 0xffff,'strict MXCSR sample')
    return {'site':{'language':language,'stage':stage,'case':case,'operation':operation,'matrix':matrix,'point':point},
            'raw':raw,'controls':raw & 0xffc0,'sticky_flags':raw & 63}


def qualify_fp(left,right):
    a=[v['controls'] for v in left];b=[v['controls'] for v in right]
    status=('ObservedControlMismatch' if a!=b else
            'SampledDefaultControlsAgree' if all(v==0x1f80 for v in a+b) else 'ObservedNondefaultControls')
    return {'sampled_controls':status,'left':left,'right':right,'operation_environment':'Unproved'}


def mesh(row,native=False,domain=True):
    require(not domain or 'material_count' in row,'required geometry material domain')
    require(type(row['positions']) is list and 0<len(row['positions'])<=1000000,'position count')
    for position in row['positions']: require(len(finite(position))==3,'position words')
    indices=words(row['indices']);attrs=words(row['attributes'])
    require(indices and len(indices)%3==0 and len(attrs)*3==len(indices) and all(i<len(row['positions']) for i in indices),'index/count/bounds')
    if 'material_count' in row:
        count=material_count(row['material_count'],row.get('stage')=='premerge');require(all(i<max(count,1) for i in attrs),'material bounds')
    if 'table' in row:
        require(type(row['table']) is list,'attribute table')
        covered=[]
        for t in row['table']:
            require(len(words(t))==5,'attribute range words');id,start,count,vs,vc=t
            require('material_count' not in row or id<row['material_count'],'attribute table material domain')
            require(count>0 and start+count<=len(attrs) and vs+vc<=len(row['positions']),'attribute range bounds')
            require(attrs[start:start+count]==[id]*count and all(vs<=i<vs+vc for i in indices[start*3:(start+count)*3]),'attribute range binding')
            covered.extend(range(start,start+count))
        require(not row['table'] or sorted(covered)==list(range(len(attrs))),'attribute table coverage')
    if native:
        n,f,stride,offset,vb,ib,width=words(row['bounds'])
        require(n==len(row['positions']) and f*3==len(indices) and 0<stride<=256 and offset+12<=stride and vb==n*stride and width in (2,4) and ib==f*3*width,'actual declaration/lock buffer bounds')
        require(row['initialized']==['position'] and row['unknown']==['uv','padding','other-declaration-channels'],'unknown initialization channel')
    return {k:row[k] for k in ('positions','indices','attributes','table','material_count') if k in row}


def parse(raw,language,observed):
    text=raw.decode('utf-8');require('SKIP' not in text,'unsupported is not execution')
    lines=[line[3:] for line in text.splitlines() if line.startswith('FP ')]
    rows=[load_json(line) for line in lines]
    require(rows and rows[0]=={'stage':'begin','language':language} and rows[-1]=={'stage':'end','status':0},'normal complete stream terminal')
    at=1
    def take(stage):
        nonlocal at
        require(at<len(rows)-1 and rows[at].get('stage')==stage,'ordered/missing stage '+stage)
        row=rows[at];at+=1;return row
    def fp(point):
        row=take('fp');require(row['point']==point and row['case']==current_case,'FP source site');return snapshot(row['mxcsr'],language,point,current_case)
    def hr(name):
        row=take('hr');require(row['operation']==name and type(row['value']) is int and 0<=row['value']<0x80000000,'missing/failed HRESULT '+name)
    def native_mesh(stage):
        for name in ('GetDeclaration','GetVertexBuffer','VertexBufferGetDesc','GetIndexBuffer','IndexBufferGetDesc','LockVertexBuffer','UnlockVertexBuffer','LockIndexBuffer','UnlockIndexBuffer','LockAttributeBuffer','UnlockAttributeBuffer','GetAttributeTableSize'):hr(name)
        if rows[at].get('stage')=='hr':hr('GetAttributeTable')
        row=take(stage);mesh(row,True,False)
        require((row['table']!=[])==(rows[at-2].get('operation')=='GetAttributeTable'),'attribute table HRESULT binding')
        return row
    result={'cases':{},'direct':[],'fp':[]}
    current_case=None
    if language=='native':
        cpu=take('cpu');require(len(words(cpu['vendor']))==3 and len(words(cpu['brand']))==12 and len(words(cpu['features']))==3 and len(words([cpu['identity']]))==1,'closed CPU facts')
        result['cpu']=cpu;result['fp'].append(fp('device-before'));hr('CreateDevice');result['fp'].append(fp('device-after'))
        dll=take('dll');require(re.fullmatch('[0-9a-f]{64}',dll['sha256']) and type(dll['size']) is int and dll['size']>0 and len(words(dll['rvas']))==3 and type(dll['base']) is int and dll['base']>0 and dll['import_target']==dll['base']+dll['rvas'][0],'DLL/import/direct binding');result['dll']=dll
    for id,_,_ in CASES:
        case=take('case');require(case['id']==id,'case identity/order');item={};current_case=id
        if language=='native':
            item['fp']=[fp('independent-before')];hr('D3DXLoadMeshFromXW');item['fp'].append(fp('independent-after'))
            item['raw']=native_mesh('independent-raw')
            mats=take('independent-material-raw');item['raw']['material_count']=material_count(mats['material_count']);mesh(item['raw'])
            item['fp'].append(fp('loader-before'))
            if observed:
                item['fp'].append(fp('production-raw-before'));item['production_raw']=native_mesh('production-raw');item['fp'].append(fp('production-raw-after'))
            item['fp'].append(fp('loader-after'));require(take('loader')=={'stage':'loader','success':True},'production loader succeeded')
            item['before']=native_mesh('before-observation')
            if observed:item['observation']=native_mesh('observation')
            item['final']=native_mesh('final-adjusted');mats=take('final-material-adjusted');count=material_count(mats['material_count'])
            for stage in ('before','observation','final','production_raw'):
                if stage in item:item[stage]['material_count']=count;mesh(item[stage])
            require(mesh(item['before'])==mesh(item['final']) and (not observed or mesh(item['observation'])==mesh(item['final'])),'native extra observation interference')
        else:
            item['fp']=[snapshot(case['mxcsr'],language,'case',id)]
            if observed:
                ast=[]
                while rows[at].get('stage') in ('parsed','reference'):
                    node=rows[at];at+=1
                    require(type(node['path']) is list and node['path'] and all(type(v) is int and v>=0 for v in node['path']),'ordered AST path')
                    require(node['path'] not in [n['path'] for n in ast],'duplicate AST path')
                    if node['stage']=='parsed':
                        require(type(node['kind']) is str and type(node['values']) is list,'actual AST node')
                        for value in node['values']:
                            require(type(value) is list and len(value)==2 and value[0] in ('int','float','bytes'),'AST scalar tag')
                            if value[0]=='float':finite([value[1]])
                            elif value[0]=='int':require(type(value[1]) is int,'AST integer')
                            else:require(type(value[1]) is list and all(type(v) is int and 0<=v<=255 for v in value[1]),'AST bytes')
                    ast.append(node)
                require(ast and any(n.get('kind')=='Mesh' for n in ast) and [n['path'] for n in ast]==sorted(n['path'] for n in ast),'parsed Mesh coverage/order');take('parsed-end');item['parsed']=ast
                containers=[]
                while rows[at].get('stage')=='premerge':
                    row=take('premerge');require(row['ordinal']==len(containers) and len(finite(row['matrix']))==16,'ordered applied matrices');mesh(row);containers.append(row)
                require(containers,'container coverage');take('premerge-end');item['premerge']=containers
                merged=take('merged-raw');mesh(merged);item['merged']=merged
            item['final']=take('final-adjusted');require(item['final']['id']==id,'final FP case site');mesh(item['final']);item['fp'].append(snapshot(item['final']['mxcsr'],language,'final-adjusted',id))
        result['cases'][id]=item
    for mi in range(3):
        for pi in range(5):
            for operation in (('TransformCoord','Transform') if language=='native' else ('TransformCoord',)):
                row=take('direct');require(row['operation']==operation and type(row['matrix']) is int and row['matrix']==mi and type(row['point']) is int and row['point']==pi,'direct operation/input/matrix identity')
                require(len(finite(row['words']))==(4 if operation=='Transform' else 3),'direct operation output width')
                row['fp']=[snapshot(row[k],language,k,operation=operation,matrix=mi,point=pi) for k in ('sample_a','sample_b')];result['direct'].append(row)
    require(at==len(rows)-1,'extra/unknown records')
    if language=='native':
        q,t=result['direct'][-2:];require(q['words']!=t['words'][:3] and t['words'][3]==word(3.),'nonunit-w distinguishes operations')
    return result


def semantic(a,b):
    return {'classification':'Equal' if a==b else 'SemanticDifference','before':a,'after':b}


def classify(native,rust):
    findings=[];differences=[];relations=[];qualifications=[]
    def held(id,name,qualification):
        findings.append({'case':id,'finding':name,'cause_status':'Held',
                         'reason':'OperationEnvironmentUnproved','fp_qualification':qualification})
    for id,_,_ in CASES:
        n,r=native['cases'][id],rust['cases'][id]
        qualification=qualify_fp([v for v in n['fp'] if v['site']['stage'] in ('loader-before','loader-after')],r['fp'])
        qualifications.append({'case':id,**qualification})
        for stage,a,b in [('production-raw/merged-raw',mesh(n['production_raw']),mesh(r['merged'])),('final-adjusted',mesh(n['final']),mesh(r['final']))]:
            if a!=b:differences.append({'case':id,'stage':stage,**semantic(a,b)})
        parsed=[]
        for node in r['parsed']:
            if node.get('kind')=='Mesh':
                values=node['values'];require(values and values[0][0]=='int','AST Mesh vertex count')
                count=values[0][1];require(0<count<=1000000 and len(values)>=1+3*count,'AST Mesh position count')
                for i in range(count):
                    parsed.append([v[1] if v[0]=='float' else word(float(v[1])) for v in values[1+3*i:4+3*i]])
        pre=[p for row in r['premerge'] for p in row['positions']]
        if parsed==pre and pre!=r['merged']['positions']:findings.append({'case':id,'finding':'ChangeAfterParsingAtMerge','qualification':'ordered positions; material-driven splits can change count on other inputs'})
        if mesh(n['production_raw'])!=mesh(n['final']):findings.append({'case':id,'finding':'ProductionRawVersusFinalPostprocessingDifference'})
        containers=r['premerge']
        reason='OrderedPremergePointsOrMatricesDoNotMatchDirectInputs'
        if len(containers)==1 and containers[0]['positions']==[list(map(word,p)) for p in POINTS[:4]]:
            matches=[mi for mi,m in enumerate(MATRICES) if containers[0]['matrix']==list(map(word,m))]
            if len(matches)==1 and len(r['merged']['positions'])==4:
                direct=[row['words'] for row in rust['direct'] if row['matrix']==matches[0] and row['point']<4]
                relations.append({'case':id,'relation':'RustDirectVersusMerged','matrix':matches[0],**semantic(direct,r['merged']['positions'])})
                continue
            reason='AppliedMatrixHasNoUniqueDirectCorrespondenceOrMergedCountDiffers'
        relations.append({'case':id,'relation':'RustDirectVersusMerged','classification':'NotComparable','reason':reason})
    ncoords=[r for r in native['direct'] if r['operation']=='TransformCoord']
    for n,r in zip(ncoords,rust['direct']):
        qualification=qualify_fp(n['fp'],r['fp'])
        qualifications.append({'matrix':n['matrix'],'point':n['point'],'operation':'TransformCoord',**qualification})
        if n['words']!=r['words']:differences.append({'stage':'direct-TransformCoord','matrix':n['matrix'],'point':n['point'],**semantic(n['words'],r['words'])})
    for id,_,mi in CASES[:3]:
        matrix=0 if mi is None else mi
        direct_rows=[row for row in ncoords if row['matrix']==matrix and row['point']<4]
        direct=[row['words'] for row in direct_rows]
        n=native['cases'][id];r=rust['cases'][id]
        q=qualify_fp([v for row in direct_rows for v in row['fp']], [v for v in n['fp'] if v['site']['stage'] in ('loader-before','loader-after')]*len(direct_rows))
        if direct!=n['production_raw']['positions']:
            held(id,'DirectCoordVersusProductionRawSupportsDifferentPaths',q)
        pre=[p for container in r['premerge'] for p in container['positions']]
        if matrix==0 and direct==n['production_raw']['positions']==pre and pre!=r['merged']['positions']:
            held(id,'CurrentNativeVersusFixedRustArithmeticDifference',qualify_fp([v for v in n['fp'] if v['site']['stage'] in ('loader-before','loader-after')],r['fp']))
    if native['cases']['floor-top']['production_raw']['positions']!=native['cases']['floor-identity']['production_raw']['positions']:
        findings.append({'finding':'TopVersusIdentityFrameInputTopologyDependence','qualification':'does not isolate Frame from explicit matrix'})
    return {'state':'CompleteSameHostDiagnostic','differences':differences,'findings':findings,
            'output_relations':relations,'causal_qualification':qualifications,
            'fp_states':{'native':native['fp']+[v for case in native['cases'].values() for v in case['fp']]+[v for row in native['direct'] for v in row['fp']],
                         'rust':[v for case in rust['cases'].values() for v in case['fp']]+[v for row in rust['direct'] for v in row['fp']]},
            'uncertainty':['OperationEnvironmentUnproved','Rust direct compiled output may be constant-folded',
                           'CPU versus DLL cause unproved','D3DX internal instructions unobserved',
                           'one host cannot select universal arithmetic policy','material-value difference unresolved',
                           'native draw/upload, GPU, pixel cause and full app unexecuted']}


def pe_exports(raw):
    require(raw[:2]==b'MZ' and len(raw)>64,'PE image')
    pe=struct.unpack_from('<I',raw,0x3c)[0]
    require(raw[pe:pe+6]==b'PE\0\0d\x86','AMD64 PE')
    count=struct.unpack_from('<H',raw,pe+6)[0];optional=pe+24
    require(struct.unpack_from('<H',raw,optional)[0]==0x20b,'PE32+')
    section=optional+struct.unpack_from('<H',raw,pe+20)[0]
    sections=[struct.unpack_from('<IIII',raw,section+i*40+8) for i in range(count)]
    def offset(rva):
        matches=[ptr+rva-va for size,va,rawsize,ptr in sections if va<=rva<va+rawsize]
        require(len(matches)==1 and matches[0]<len(raw),'PE RVA bounds');return matches[0]
    export=offset(struct.unpack_from('<I',raw,optional+112)[0])
    funcs,names=struct.unpack_from('<II',raw,export+20)
    fr,nr,orr=struct.unpack_from('<III',raw,export+28)
    fo,no,oo=offset(fr),offset(nr),offset(orr);result={}
    for i in range(names):
        nameoffset=offset(struct.unpack_from('<I',raw,no+4*i)[0]);end=raw.index(b'\0',nameoffset)
        name=raw[nameoffset:end].decode('ascii');ordinal=struct.unpack_from('<H',raw,oo+2*i)[0]
        require(ordinal<funcs,'PE export ordinal');result[name]=struct.unpack_from('<I',raw,fo+4*ordinal)[0]
    return result


def recipe(runner_temp,variant,opt):
    root=PureWindowsPath(runner_temp)
    require(root.is_absolute() and '..' not in root.parts and variant in ('control','observed') and opt in ('Od','O2'),'closed recipe inputs')
    out=root/'floor-profile-evidence';build=root/'floor-profile-build'
    id=variant+'-'+opt;source=out/'sources'/id;directory=out/id
    native=build/id/'native';target=build/id/'rust'
    mode=['--release'] if opt=='O2' else []
    commands={
        'configure':['cmake','-S',str(source),'-B',str(native),'-G','Visual Studio 17 2022','-A','x64','-DCMAKE_TOOLCHAIN_FILE='+str(root/'floor-profile-deps/build/generators/conan_toolchain.cmake'),'-DBUILD_TESTING=OFF','-DMIKUDANCESTUDIO_DIAG=OFF'],
        'native-build':['cmake','--build',str(native),'--config','Release','--target','floor_profile','--parallel','4','--','/v:diag'],
        'native':[str(directory/'floor_profile.exe'),'fixed',variant],
        'rust-build':['cargo','+1.95.0','test','-p','mds-accessory','--lib','--no-run','--message-format=json']+mode,
        'rust':[str(directory/'rust-profile.exe'),'mesh::floor_profile::diagnostic','--exact','--nocapture','--test-threads=1'],
    }
    for test in ('mesh_dump','x_files'):
        commands[test]=['cargo','+1.95.0','test','-p','mds-accessory','--test',test]+mode+['--','--test-threads=1']
    return {'id':id,'source':str(source),'target':str(target),'evidence':str(directory),
            'native_target':str(native),'input_root':str(out/'inputs'),'commands':commands,
            'cwd':{label:str(source/'rust') if label.startswith('rust') or label in ('mesh_dump','x_files') else str(source) for label in commands}}


def admit_recipe(m,b):
    r=recipe(m['runner_temp'],b['variant'],b['optimization'])
    require(m['input_root']==r['input_root'],'closed input root')
    require(all(b[key]==r[key] for key in ('id','source','target','evidence','commands')),'closed command/source/target/evidence recipe')
    return r


def admit_command(receipt,r,label):
    require(receipt['argv']==r['commands'][label] and receipt['cwd']==r['cwd'][label],'exact command/cwd binding')
    expected={'CARGO_TARGET_DIR':r['target'],'CARGO_INCREMENTAL':'0',
              'RUSTFLAGS':'--cfg mds_floor_profile --check-cfg=cfg(mds_floor_profile)','CL':'','_CL_':''}
    require(all(receipt['env'].get(k)==v for k,v in expected.items()),'closed compiler environment')


def admit_manifest(m):
    require(m['fp_observation_contract']==FP_CONTRACT,'fixed FP observation contract')
    require(m['schema']==SCHEMA and m['base']==BASE and m['paths']==PATHS and re.fullmatch('[0-9a-f]{40}',m['head']),'diagnostic generation/head')


def cargo_binary(raw,r,opt):
    lines=[line for line in raw.splitlines(keepends=True) if line.lstrip().startswith(b'{')]
    require(lines and all(line.endswith(b'\n') for line in lines),'complete Cargo JSON')
    rows=[load_json(line) for line in lines]
    require(all(type(row) is dict and type(row.get('reason')) is str for row in rows),'Cargo object')
    require([row for row in rows if row['reason']=='build-finished']==[{'reason':'build-finished','success':True}] and rows[-1]=={'reason':'build-finished','success':True},'Cargo terminal')
    artifacts=[row for row in rows if row['reason']=='compiler-artifact' and row.get('target',{}).get('name')=='mds_accessory']
    require(len(artifacts)==1,'exact Cargo package target')
    row=artifacts[0];source=PureWindowsPath(r['source'])/'rust/crates/mds-accessory';t=row['target']
    package=row.get('package_id');require(type(package) is str and package.startswith('path+file:///') and package.endswith('#mds-accessory@0.1.0'),'Cargo package identity')
    from urllib.parse import unquote
    package_path=unquote(package[len('path+file:///'):].split('#')[0])
    require(PureWindowsPath(package_path)==source,'Cargo package source')
    require(PureWindowsPath(row['manifest_path'])==source/'Cargo.toml' and PureWindowsPath(t['src_path'])==source/'src/lib.rs' and t['kind']==['lib'] and t['crate_types']==['lib'] and t['test'] is True,'Cargo target source/kind')
    profile={'opt_level':'3' if opt=='O2' else '0','debuginfo':0 if opt=='O2' else 2,'debug_assertions':opt=='Od','overflow_checks':opt=='Od','test':True}
    require(row['profile']==profile and type(row['profile']['debuginfo']) is int and all(type(row['profile'][key]) is bool for key in ('debug_assertions','overflow_checks','test')),'actual Cargo profile')
    exe=row['executable'];path=PureWindowsPath(exe)
    require(path.parent==PureWindowsPath(r['target'])/('release' if opt=='O2' else 'debug')/'deps' and re.fullmatch('mds_accessory-[0-9a-f]+[.]exe',path.name) and exe in row['filenames'],'Cargo executable membership')
    return exe


def command_words(line):
    result=[];token='';quoted=False;at=0;started=False
    while at<len(line):
        char=line[at]
        if char=='\\':
            end=at
            while end<len(line) and line[end]=='\\':end+=1
            count=end-at
            if end<len(line) and line[end]=='"':
                token+='\\'*(count//2)
                if count%2:token+='"'
                else:quoted=not quoted
                at=end+1
            else:token+='\\'*count;at=end
            started=True;continue
        if char=='"':quoted=not quoted;started=True
        elif char.isspace() and not quoted:
            if started:result.append(token);token='';started=False
        else:token+=char;started=True
        at+=1
    require(not quoted,'unterminated Windows command quote')
    if started:result.append(token)
    require(result and not any(v.startswith('@') for v in result),'unexpanded response file')
    return result


def native_commands(raw):
    result=[]
    for line in raw.decode(errors='replace').splitlines():
        match=re.search(r'(?i)(?:"[^"\r\n]*[\\/]|[A-Za-z]:[^"\r\n]*[\\/])(?:cl|link|lib)[.]exe"?(?=\s)',line)
        if match:
            command=[line[match.start():match.end()].strip('"')]+command_words(line[match.end():].strip())
            if command not in result:result.append(command)
    return result


def winpath(path,cwd):
    return PureWindowsPath(ntpath.normpath(str(PureWindowsPath(cwd)/path)))


def option(args,name):
    values=[]
    for i,arg in enumerate(args):
        if arg.lower().startswith(name.lower()):
            value=arg[len(name):]
            if value.startswith(':'):value=value[1:]
            if not value:
                require(i+1<len(args),'option value');value=args[i+1]
            values.append(value)
    require(values,'missing option '+name)
    return values[-1]


def archive_members(raw):
    require(raw.startswith(b'!<arch>\n'),'COFF archive signature')
    at=8;result=[]
    while at<len(raw):
        require(at+60<=len(raw) and raw[at+58:at+60]==b'`\n','COFF archive header')
        size=int(raw[at+48:at+58].strip());start=at+60;end=start+size
        require(size>=0 and end<=len(raw),'COFF archive member bounds')
        name=raw[at:at+16].strip()
        if name not in (b'/',b'//'):result.append(raw[start:end])
        at=end+(size%2)
    require(at==len(raw),'COFF archive end')
    return result


def native_provenance(commands,r,opt,objects,archive):
    cwd=r['native_target'];source=PureWindowsPath(r['source']);root=PureWindowsPath(cwd)
    def tool(row):return PureWindowsPath(row[0]).name.lower()
    def compile(path):
        matches=[row for row in commands if tool(row)=='cl.exe' and any(winpath(v,cwd)==source/path for v in row[1:] if v.lower().endswith('.cpp'))]
        require(len(matches)==1,'exact source compilation '+path)
        args=matches[0][1:];require('/c' in [v.lower() for v in args],'compile-only command')
        options=[v.lower() for v in args if re.fullmatch(r'(?i)[/-]O(?:d|[012x])',v)]
        require(options and options[-1][1:]==opt.lower(),'effective ordered optimization')
        obj=option(args,'/Fo');obj=winpath(obj,cwd)
        if not obj.suffix:obj=obj/(PureWindowsPath(path).stem+'.obj')
        expected=root/('mikudancestudio_core.dir' if path==ACCESSORY else 'floor_profile.dir')/'Release'/(PureWindowsPath(path).stem+'.obj')
        require(obj==expected,'exact CMake target object')
        relative=obj.relative_to(root).as_posix()
        require(relative in objects,'exact compiled retained object')
        return obj,objects[relative]
    accessory,accessory_bytes=compile(ACCESSORY);native,native_bytes=compile('native.cpp')
    lib=root/'Release/mikudancestudio_core.lib'
    libraries=[row for row in commands if tool(row)=='lib.exe' and winpath(option(row[1:],'/OUT'),cwd)==lib]
    require(len(libraries)==1 and accessory in [winpath(v,cwd) for v in libraries[0][1:] if v.lower().endswith('.obj')],'core archive object membership')
    require(any(member==accessory_bytes for member in archive_members(archive)),'compiled accessory object bytes in core archive')
    exe=root/'Release/floor_profile.exe'
    links=[row for row in commands if tool(row)=='link.exe' and winpath(option(row[1:],'/OUT'),cwd)==exe]
    require(len(links)==1,'exact final executable link')
    args=links[0][1:]
    require(native in [winpath(v,cwd) for v in args if v.lower().endswith('.obj')] and lib in [winpath(v,cwd) for v in args if v.lower().endswith('.lib')],'final link exact harness object and core archive')
    return str(exe)


def source_expected(base,observed,input_root,opt):
    changes,patches=generated(lambda p:(base/p).read_bytes(),observed,input_root)
    raw=changes['CMakeLists.txt'];replacement=raw.replace(b'@OPT@',opt.encode())
    patches['CMakeLists.txt'].append({'kind':'optimization','original_hex':raw.hex(),'original_sha256':digest(raw),'generated_sha256':digest(replacement),'option':opt})
    changes['CMakeLists.txt']=replacement
    expected=c.source_inventory(base)
    for path,raw in changes.items():expected[path]={'sha256':digest(raw),'mode':expected.get(path,{}).get('mode',0o644)}
    return changes,patches,expected


def verify_sources(out,m):
    base=out/'sources/base';base_inv=c.source_inventory(base)
    require(base_inv==m['base_inventory'],'complete base source closure')
    entries={name:['100755' if row['mode']&0o111 else '100644',h.git_hash('blob',(base/name).read_bytes())] for name,row in base_inv.items()}
    h.commit_proof(out/'base.commit',BASE,entries)
    commit=(out/'base.commit').read_text();require(commit.splitlines()[0]=='tree '+BASE_TREE,'base tree identity')
    for path in PATHS:
        raw=(out/'tooling'/path).read_bytes();require(raw==(ROOT/path).read_bytes() and path not in entries,'six new tooling paths')
        entries[path]=['100644',h.git_hash('blob',raw)]
    h.commit_proof(out/'head.commit',m['head'],entries)
    require(('parent '+PARENT) in (out/'head.commit').read_text().splitlines(),'frozen parent identity')
    require(input_manifest(inputs(lambda p:(base/p).read_bytes()))==m['inputs'],'closed input manifest')
    for row in inputs(lambda p:(base/p).read_bytes()):require((out/'inputs'/(row['id']+'.x')).read_bytes()==row['bytes'],'retained exact input bytes')
    for build in m['builds']:
        variant,opt=build['variant'],build['optimization']
        changes,patches,expected=source_expected(base,variant=='observed',PureWindowsPath(m['input_root']),'/'+opt)
        require(build['patches']==patches and build['before']==expected==build['after'],'insertion/inverse/source-end binding')
        source=out/'sources'/build['id']
        if sys.platform=='win32':
            for path,row in expected.items():c.TRANSPORT_MODES[str((source/path).resolve())]=row['mode']
        require(c.source_inventory(source)==expected,'generated source drift')
        for path,rows in patches.items():
            raw=(source/path).read_bytes()
            for patch in reversed(rows):
                if patch.get('kind')=='optimization':
                    require(digest(raw)==patch['generated_sha256'],'optimization generated hash');raw=bytes.fromhex(patch['original_hex']);require(digest(raw)==patch['original_sha256'],'optimization inverse hash')
                else:raw=inverse(raw,patch)
            require(raw==(base/path).read_bytes(),'full file inverse')


def replay(out,archive=None):
    if archive:
        inventory=c.transport(archive,out)
        require(set(inventory)==set(previous.evidence_inventory(out))|{'seal.json'},'exact completed archive membership')
    seal=load_json((out/'seal.json').read_bytes())
    require(seal['schema']==SCHEMA and seal['files']==previous.evidence_inventory(out),'complete generation seal')
    m=load_json((out/'manifest.json').read_bytes())
    admit_manifest(m)
    verify_sources(out,m)
    require([b['id'] for b in m['builds']]==[v+'-'+opt for opt in ('Od','O2') for v in ('control','observed')],'actual build matrix')
    parsed={}
    for b in m['builds']:
        r=admit_recipe(m,b)
        directory=out/b['id'];opt=b['optimization'];source=r['source'];target=r['target']
        for label in ('configure','native-build','rust-build','mesh_dump','x_files','native','rust'):
            receipt,stdout,stderr=checked(directory,label)
            admit_command(receipt,r,label)
            if label in ('native','rust'):
                binary=(directory/('floor_profile.exe' if label=='native' else 'rust-profile.exe')).read_bytes()
                require(receipt['executed_binary']=={'path':r['commands'][label][0],'sha256':digest(binary),'size':len(binary)},'executed retained binary receipt')
        _,build_stdout,build_stderr=checked(directory,'native-build')
        commands=native_commands(build_stdout+b'\n'+build_stderr)
        require(commands==b['actual_native_commands'],'retained parsed compile/archive/link commands')
        objects={}
        for path,row in b['objects'].items():
            h.safe_name(path);raw=(directory/'objects'/path).read_bytes();require(len(raw)==row['size'] and digest(raw)==row['sha256'],'compiled object bytes');objects[path]=raw
        original=native_provenance(commands,r,opt,objects,(directory/'mikudancestudio_core.lib').read_bytes())
        _,cargo_stdout,_=checked(directory,'rust-build')
        executable=cargo_binary(cargo_stdout,r,opt)
        require(b['original_native_binary']=={'path':original,'sha256':b['binaries']['floor_profile.exe']['sha256']} and b['original_rust_binary']=={'path':executable,'sha256':b['binaries']['rust-profile.exe']['sha256']},'derived produced/executed binary identity')
        require(set(b['binaries'])=={'floor_profile.exe','rust-profile.exe','d3dx9_43.dll'},'exact retained runtime binaries')
        for name,row in b['binaries'].items():
            raw=(directory/name).read_bytes();require(digest(raw)==row['sha256'] and len(raw)==row['size'],'binary/source binding');pe_exports(raw) if name=='d3dx9_43.dll' else require(raw[:2]==b'MZ','actual executable PE')
        for test in ('mesh_dump','x_files'):
            log=(directory/(test+'.stdout')).read_text()+(directory/(test+'.stderr')).read_text()
            require('test result: ok.' in log and re.search(r'0 failed; 0 ignored;',log) and 'SKIP' not in log and 'FP ' not in log,'fixture tests executed with inactive sink')
        _,nout,nerr=checked(directory,'native');require(not nerr,'native stderr');native=parse(nout,'native',b['variant']=='observed')
        _,rout,_=checked(directory,'rust');require(b'test result: ok. 1 passed; 0 failed; 0 ignored;' in rout,'one actual Rust unit probe with no ignored tests');rust=parse(rout,'rust',b['variant']=='observed')
        dll=native['dll'];raw=(directory/'d3dx9_43.dll').read_bytes();exports=pe_exports(raw)
        require(digest(raw)==dll['sha256'] and len(raw)==dll['size'] and dll['rvas']==[exports[n] for n in ('D3DXLoadMeshFromXW','D3DXVec3TransformCoord','D3DXVec3Transform')],'actual loaded DLL bytes/exports')
        parsed[b['id']]=(native,rust)
    results={}
    for opt in ('Od','O2'):
        control,observed=[parsed[v+'-'+opt] for v in ('control','observed')]
        for language in range(2):
            require([{k:row[k] for k in ('operation','matrix','point','words')} for row in control[language]['direct']]==[{k:row[k] for k in ('operation','matrix','point','words')} for row in observed[language]['direct']],'control/observed direct output invariance')
            for id,_,_ in CASES:
                a,b=control[language]['cases'][id],observed[language]['cases'][id]
                require(mesh(a['final'])==mesh(b['final']) ,'control/observed bitwise initialized final state')
            a,b=[p[language]['cases'] for p in (control,observed)]
            require(mesh(a['floor-top']['final'])!=mesh(a['floor-affine']['final']) and mesh(b['floor-top']['final'])!=mesh(b['floor-affine']['final']),'genuine normal-exit affine sensitivity')
        results[opt]=classify(*observed)
    result={'schema':SCHEMA,'fp_observation_contract':FP_CONTRACT,'head':m['head'],'results':results,'hosted':'ExecutedWindowsOnly','profile_adoption':'NotAuthorized'}
    require(load_json((out/'result.json').read_bytes())==result,'rederived diagnostic result')
    return result


def run(out,build_root,toolchain):
    require(sys.platform=='win32' and os.environ.get('GITHUB_ACTIONS')=='true','explicit hosted Windows execution only')
    require(build_root and toolchain and toolchain.is_file() and not out.exists() and not build_root.exists() and not out.is_relative_to(ROOT) and not build_root.is_relative_to(ROOT) and not out.is_relative_to(build_root) and not build_root.is_relative_to(out),'fresh external evidence/build roots')
    runner_temp=os.environ['RUNNER_TEMP']
    r=recipe(runner_temp,'control','Od')
    require(PureWindowsPath(str(out))==PureWindowsPath(r['evidence']).parent and PureWindowsPath(str(build_root))==PureWindowsPath(runner_temp)/'floor-profile-build' and PureWindowsPath(str(toolchain))==PureWindowsPath(runner_temp)/'floor-profile-deps/build/generators/conan_toolchain.cmake','fixed hosted roots/toolchain')
    out.mkdir(parents=True);build_root.mkdir(parents=True);env=os.environ.copy()
    for label,argv in [('git-head',['git','rev-parse','HEAD']),('git-status',['git','status','--porcelain']),('git-paths',['git','diff','--name-only',BASE,'HEAD']),('source-archive',['git','-c','tar.umask=0022','archive',BASE]),('base-commit',['git','cat-file','commit',BASE]),('head-commit',['git','cat-file','commit','HEAD'])]:
        require(record(out,label,argv,ROOT,env)['status']==0,'source identity command')
    head=(out/'git-head.stdout').read_text().strip()
    require(head==os.environ.get('GITHUB_SHA') and not (out/'git-status.stdout').read_bytes(),'clean exact workflow HEAD')
    require(set((out/'git-paths.stdout').read_text().splitlines())==set(PATHS),'exact six paths')
    shutil.copyfile(out/'source-archive.stdout',out/'base-source.tar');base=out/'sources/base'
    base_modes=c.safe_tar(out/'base-source.tar',base)
    for path,row in base_modes.items():c.TRANSPORT_MODES[str((base/path).resolve())]=row['mode']
    for name in ('base','head'):shutil.copyfile(out/(name+'-commit.stdout'),out/(name+'.commit'))
    for path in PATHS:
        dest=out/'tooling'/path;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/path,dest)
    input_root=Path(r['input_root']);input_root.mkdir();rows=inputs(lambda p:(base/p).read_bytes())
    for row in rows:(input_root/(row['id']+'.x')).write_bytes(row['bytes'])
    m={'schema':SCHEMA,'fp_observation_contract':FP_CONTRACT,'runner_temp':runner_temp,'base':BASE,'head':head,'paths':PATHS,'input_root':str(input_root),'inputs':input_manifest(rows),'base_inventory':c.source_inventory(base),'builds':[],
       'configuration_differences':'Native Release in both modes, appended /Od or /O2 on core and console; Rust dev versus release defaults, opt-level/debug assertions/overflow/debuginfo differ. Observed copies add private sink calls. Both copies include coarse private MXCSR snapshots with operation ordering unproved.'}
    parsed={}
    for opt in ('Od','O2'):
        for variant in ('control','observed'):
            r=recipe(runner_temp,variant,opt);commands=r['commands']
            id=r['id'];directory=Path(r['evidence']);directory.mkdir();source=Path(r['source']);shutil.copytree(base,source)
            changes,patches,expected=source_expected(base,variant=='observed',input_root,'/'+opt)
            for path,raw in changes.items():(source/path).write_bytes(raw)
            for path,row in expected.items():c.TRANSPORT_MODES[str((source/path).resolve())]=row['mode']
            require(c.source_inventory(source)==expected,'generated source initial closure')
            native_target=Path(r['native_target']);target=Path(r['target'])
            e=env|{'CARGO_TARGET_DIR':str(target),'CARGO_INCREMENTAL':'0','CARGO_TERM_COLOR':'never','RUSTFLAGS':'--cfg mds_floor_profile --check-cfg=cfg(mds_floor_profile)','CL':'','_CL_':''}
            for label in ('configure','native-build'):
                require(record(directory,label,commands[label],source,e,2400)['status']==0,'native '+label+' failure is not SemanticDifference')
            shutil.copyfile(native_target/'Release/floor_profile.exe',directory/'floor_profile.exe')
            actual=native_commands((directory/'native-build.stdout').read_bytes()+b'\n'+(directory/'native-build.stderr').read_bytes())
            shutil.copyfile(native_target/'Release/mikudancestudio_core.lib',directory/'mikudancestudio_core.lib')
            require(record(directory,'native',commands['native'],source,e,300)['status']==0,'native normal exit required')
            native=parse((directory/'native.stdout').read_bytes(),'native',variant=='observed')
            shutil.copyfile(native['dll']['path'],directory/'d3dx9_43.dll')
            require(record(directory,'rust-build',commands['rust-build'],source/'rust',e)['status']==0,'Rust build')
            executable=cargo_binary((directory/'rust-build.stdout').read_bytes(),r,opt)
            shutil.copyfile(executable,directory/'rust-profile.exe')
            require(record(directory,'rust',commands['rust'],source/'rust',e,300)['status']==0,'Rust probe normal exit')
            rust=parse((directory/'rust.stdout').read_bytes(),'rust',variant=='observed')
            for test in ('mesh_dump','x_files'):
                require(record(directory,test,commands[test],source/'rust',e)['status']==0,'unchanged fixture contract '+test)
            require(c.source_inventory(source)==expected,'source end drift')
            objects={}
            for object_path in sorted(native_target.rglob('*.obj')):
                relative=object_path.relative_to(native_target).as_posix()
                retained=directory/'objects'/relative;retained.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(object_path,retained)
                raw=retained.read_bytes();objects[relative]={'sha256':digest(raw),'size':len(raw)}
            require(any(path.endswith('/accessory.obj') for path in objects) and any(path.endswith('/native.obj') for path in objects),'actual core and console object files')
            binaries={}
            for name in ('floor_profile.exe','rust-profile.exe','d3dx9_43.dll'):
                raw=(directory/name).read_bytes();binaries[name]={'sha256':digest(raw),'size':len(raw)}
            b={'id':id,'variant':variant,'optimization':opt,'source':str(source),'target':str(target),'evidence':str(directory),'commands':commands,'patches':patches,'before':expected,'after':c.source_inventory(source),'actual_native_commands':actual,'binaries':binaries,'objects':objects,'original_native_binary':{'path':str(native_target/'Release/floor_profile.exe'),'sha256':digest((native_target/'Release/floor_profile.exe').read_bytes())},'original_rust_binary':{'path':executable,'sha256':digest(Path(executable).read_bytes())}}
            m['builds'].append(b);write_json(out/'manifest.json',m);parsed[id]=(native,rust)
    result={'schema':SCHEMA,'fp_observation_contract':FP_CONTRACT,'head':head,'results':{opt:classify(*parsed['observed-'+opt]) for opt in ('Od','O2')},'hosted':'ExecutedWindowsOnly','profile_adoption':'NotAuthorized'}
    write_json(out/'result.json',result);write_json(out/'seal.json',{'schema':SCHEMA,'files':previous.evidence_inventory(out)})
    return replay(out)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--build-root',type=Path)
    parser.add_argument('--toolchain',type=Path)
    parser.add_argument('--bundle',type=Path)
    args=parser.parse_args();out=args.out.resolve()
    if args.run:
        require(args.archive is None,'hosted run creates its own complete generation')
        result=run(out,args.build_root.resolve() if args.build_root else None,args.toolchain)
        if args.bundle:result=result|{'bundle':c.bundle(out,args.bundle.resolve())}
    else:
        require(not any((args.build_root,args.toolchain,args.bundle)),'default replay cannot request effects')
        readonly();result=replay(out,args.archive)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,IndexError,OSError,struct.error,tarfile.TarError) as error:
        print(json.dumps({'result':'InvalidEvidence','error':str(error)}),file=sys.stderr);sys.exit(1)
