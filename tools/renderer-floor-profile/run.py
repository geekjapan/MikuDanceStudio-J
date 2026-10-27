#!/usr/bin/env python3
"""Same-host importer/math diagnostic. Without --run, replay only reads evidence."""
import argparse
import importlib.util
import json
import math
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
SCHEMA = 'mds-floor-profile-v1'
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
# These are the actual four ordered floor positions; the fifth is direct-only.
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
    row=previous.record(out,label,argv,cwd,env,timeout)
    if 'RUSTFLAGS' in env:
        row['env']['RUSTFLAGS']=env['RUSTFLAGS']
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
        # Insert before the complete merge call without changing its expression.
        anchor=b'        return Err(Error::NoMesh);\n    }\n'
        add(MESH,anchor,b'    #[cfg(mds_floor_profile)] floor_profile::premerge(&containers);\n')
        add(MESH,b'    if single {\n        mesh.attribute_table = attribute_table(&mesh.indices, &mesh.face_material);\n    }\n',b'    #[cfg(mds_floor_profile)] floor_profile::merged(&mesh);\n')
    observer=(HERE/'observer.rs').read_text()
    observer=observer.replace('@CASES@',','.join('('+json.dumps(id)+',include_bytes!('+json.dumps(str(input_root/(id+'.x')))+'))' for id,_,_ in CASES))
    observer=observer.replace('@MATRICES@',repr(MATRICES)).replace('@POINTS@',repr(POINTS))
    # Hooks and sink remain compiled in integration-test libraries; only the entry is a test.
    add(MESH,read(MESH)[-40:],b'\n#[cfg(mds_floor_profile)]\nmod floor_profile {\n'+observer.encode()+b'\n}\n')
    cpp=(HERE/'native.cpp.in').read_text()
    cpp=cpp.replace('@IDS@',','.join(json.dumps(id) for id,_,_ in CASES))
    cpp=cpp.replace('@FILES@',','.join('L'+json.dumps(str(input_root/(id+'.x'))) for id,_,_ in CASES))
    for key,value in [('@MATRICES@',MATRICES),('@POINTS@',POINTS)]:
        cpp=cpp.replace(key,repr(value).replace('[','{').replace(']','}'))
    result['native.cpp']=cpp.encode();result['native_observer.hpp']=(HERE/'native_observer.hpp').read_bytes()
    return result,patches


def material(rows):
    require(type(rows) is list and 0<len(rows)<=10000,'material count')
    for row in rows: require(len(finite(row))==17,'material words')


def mesh(row,native=False):
    require(type(row['positions']) is list and 0<len(row['positions'])<=1000000,'position count')
    for position in row['positions']: require(len(finite(position))==3,'position words')
    indices=words(row['indices']);attrs=words(row['attributes'])
    require(indices and len(indices)%3==0 and len(attrs)*3==len(indices) and all(i<len(row['positions']) for i in indices),'index/count/bounds')
    if 'materials' in row:
        material(row['materials']);require(all(i<len(row['materials']) for i in attrs),'material bounds')
    if 'table' in row:
        require(type(row['table']) is list,'attribute table')
        covered=[]
        for t in row['table']:
            require(len(words(t))==5,'attribute range words');id,start,count,vs,vc=t
            require(count>0 and start+count<=len(attrs) and vs+vc<=len(row['positions']),'attribute range bounds')
            require(attrs[start:start+count]==[id]*count and all(vs<=i<vs+vc for i in indices[start*3:(start+count)*3]),'attribute range binding')
            covered.extend(range(start,start+count))
        # Empty is legitimate for the multi-mesh frames fixture.
        require(not row['table'] or sorted(covered)==list(range(len(attrs))),'attribute table coverage')
    if native:
        n,f,stride,offset,vb,ib,width=words(row['bounds'])
        require(n==len(row['positions']) and f*3==len(indices) and 0<stride<=256 and offset+12<=stride and vb==n*stride and width in (2,4) and ib==f*3*width,'actual declaration/lock buffer bounds')
        require(row['initialized']==['position'] and row['unknown']==['uv','padding','other-declaration-channels'],'unknown initialization channel')
    return {k:row[k] for k in ('positions','indices','attributes','table') if k in row}


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
        row=take('fp');require(row['point']==point and type(row['mxcsr']) is int and 0<=row['mxcsr']<=0xffff,'same-thread FP state');return row['mxcsr']
    def hr(name):
        row=take('hr');require(row['operation']==name and type(row['value']) is int and 0<=row['value']<0x80000000,'missing/failed HRESULT '+name)
    def native_mesh(stage):
        for name in ('GetDeclaration','GetVertexBuffer','VertexBufferGetDesc','GetIndexBuffer','IndexBufferGetDesc','LockVertexBuffer','UnlockVertexBuffer','LockIndexBuffer','UnlockIndexBuffer','LockAttributeBuffer','UnlockAttributeBuffer','GetAttributeTableSize'):hr(name)
        if rows[at].get('stage')=='hr':hr('GetAttributeTable')
        row=take(stage);mesh(row,True)
        require((row['table']!=[])==(rows[at-2].get('operation')=='GetAttributeTable'),'attribute table HRESULT binding')
        return row
    result={'cases':{},'direct':[],'fp':[]}
    if language=='native':
        cpu=take('cpu');require(len(words(cpu['vendor']))==3 and len(words(cpu['brand']))==12 and len(words(cpu['features']))==3 and len(words([cpu['identity']]))==1,'closed CPU facts')
        result['cpu']=cpu;result['fp'].append(fp('device-before'));hr('CreateDevice');result['fp'].append(fp('device-after'))
        dll=take('dll');require(re.fullmatch('[0-9a-f]{64}',dll['sha256']) and type(dll['size']) is int and dll['size']>0 and len(words(dll['rvas']))==3 and type(dll['base']) is int and dll['base']>0 and dll['import_target']==dll['base']+dll['rvas'][0],'DLL/import/direct binding');result['dll']=dll
    for id,_,_ in CASES:
        case=take('case');require(case['id']==id,'case identity/order');item={}
        if language=='native':
            item['fp']=[fp('independent-before')];hr('D3DXLoadMeshFromXW');item['fp'].append(fp('independent-after'))
            item['raw']=native_mesh('independent-raw')
            mats=take('independent-material-raw');material(mats['words']);item['raw_materials']=mats['words']
            item['fp'].append(fp('loader-before'))
            if observed:
                item['fp'].append(fp('production-raw-before'));item['production_raw']=native_mesh('production-raw');item['fp'].append(fp('production-raw-after'))
            item['fp'].append(fp('loader-after'));require(take('loader')=={'stage':'loader','success':True},'production loader succeeded')
            item['before']=native_mesh('before-observation')
            if observed:item['observation']=native_mesh('observation')
            item['final']=native_mesh('final-adjusted');mats=take('final-material-adjusted');material(mats['words']);item['final_materials']=mats['words']
            require(mesh(item['before'])==mesh(item['final']) and (not observed or mesh(item['observation'])==mesh(item['final'])),'native extra observation interference')
        else:
            require(type(case['mxcsr']) is int and 0<=case['mxcsr']<=0xffff,'Rust FP state');item['fp']=[case['mxcsr']]
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
            item['final']=take('final-adjusted');mesh(item['final']);item['final_materials']=item['final']['materials'];item['fp'].append(item['final']['mxcsr'])
        result['cases'][id]=item
    for mi in range(3):
        for pi in range(5):
            for operation in (('TransformCoord','Transform') if language=='native' else ('TransformCoord',)):
                row=take('direct');require(row['operation']==operation and row['matrix']==mi and row['point']==pi,'direct operation/input/matrix identity')
                require(len(finite(row['words']))==(4 if operation=='Transform' else 3),'direct operation output width')
                require(all(type(row[k]) is int and 0<=row[k]<=0xffff for k in ('before','after')),'direct FP state');result['direct'].append(row)
    require(at==len(rows)-1,'extra/unknown records')
    if language=='native':
        q,t=result['direct'][-2:];require(q['words']!=t['words'][:3] and t['words'][3]==word(3.),'nonunit-w distinguishes operations')
    return result


def semantic(a,b):
    return {'classification':'Equal' if a==b else 'SemanticDifference','before':a,'after':b}


def classify(native,rust):
    findings=[];differences=[]
    for id,_,_ in CASES:
        n,r=native['cases'][id],rust['cases'][id]
        for stage,a,b in [('production-raw/merged-raw',mesh(n['production_raw']),mesh(r['merged'])),('final-adjusted',mesh(n['final']),mesh(r['final'])),('raw-materials',n['raw_materials'],r['merged']['materials']),('adjusted-materials',n['final_materials'],r['final_materials'])]:
            if a!=b:differences.append({'case':id,'stage':stage,**semantic(a,b)})
        parsed=[]
        for node in r['parsed']:
            if node.get('kind')=='Mesh':
                values=node['values'];require(values and values[0][0]=='int','AST Mesh vertex count')
                count=values[0][1];require(0<count<=1000000 and len(values)>=1+3*count,'AST Mesh position count')
                ps=[]
                for i in range(count):
                    ps.append([v[1] if v[0]=='float' else word(float(v[1])) for v in values[1+3*i:4+3*i]])
                parsed.extend(ps)
        pre=[p for row in r['premerge'] for p in row['positions']]
        if parsed==pre and pre!=r['merged']['positions']:findings.append({'case':id,'finding':'ChangeAfterParsingAtMerge','qualification':'ordered positions; material-driven splits can change count on other inputs'})
        if mesh(n['production_raw'])!=mesh(n['final']):findings.append({'case':id,'finding':'ProductionRawVersusFinalPostprocessingDifference'})
    ncoords=[r for r in native['direct'] if r['operation']=='TransformCoord']
    for n,r in zip(ncoords,rust['direct']):
        if n['words']!=r['words']:differences.append({'stage':'direct-TransformCoord','matrix':n['matrix'],'point':n['point'],**semantic(n['words'],r['words'])})
    for id,_,mi in CASES[:3]:
        matrix=0 if mi is None else mi
        direct=[row['words'] for row in ncoords if row['matrix']==matrix][:4]
        n=native['cases'][id];r=rust['cases'][id]
        if direct!=n['production_raw']['positions']:
            findings.append({'case':id,'finding':'DirectCoordVersusProductionRawSupportsDifferentPaths','qualification':'same DLL; FP controls and observation interference remain qualifications'})
        pre=[p for container in r['premerge'] for p in container['positions']]
        if matrix==0 and direct==n['production_raw']['positions']==pre and pre!=r['merged']['positions']:
            findings.append({'case':id,'finding':'CurrentNativeVersusFixedRustArithmeticDifference','qualification':'does not separate CPU from DLL or select universal policy'})
    if native['cases']['floor-top']['production_raw']['positions']!=native['cases']['floor-identity']['production_raw']['positions']:
        findings.append({'finding':'TopVersusIdentityFrameInputTopologyDependence','qualification':'does not isolate Frame from explicit matrix'})
    native_fp=native['fp']+[v for case in native['cases'].values() for v in case['fp']]+[v for row in native['direct'] for v in (row['before'],row['after'])]
    rust_fp=[v for case in rust['cases'].values() for v in case['fp']]+[v for row in rust['direct'] for v in (row['before'],row['after'])]
    fp_states={language:[{'mxcsr':v,'rounding':(v>>13)&3,'ftz':bool(v&0x8000),'daz':bool(v&0x40),'sticky_flags':v&63,'controls':v&0xffc0} for v in values] for language,values in [('native',native_fp),('rust',rust_fp)]}
    # These are observations, not a choice of compatibility profile or internal instruction.
    return {'state':'CompleteSameHostDiagnostic','differences':differences,'findings':findings,
            'fp_states':fp_states,'uncertainty':['CPU versus DLL cause unproved','D3DX internal instructions unobserved','one host cannot select universal arithmetic policy','FP control or optimization variation may confound localization','native draw/upload, GPU, pixel cause and full app unexecuted']}


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


def source_expected(base,observed,input_root,opt):
    changes,patches=generated(lambda p:(base/p).read_bytes(),observed,input_root)
    raw=changes['CMakeLists.txt'];replacement=raw.replace(b'@OPT@',opt.encode())
    # Optimization substitution is separately reversible, including both occurrences.
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
    require(('parent '+BASE) in (out/'head.commit').read_text().splitlines(),'frozen parent identity')
    require(input_manifest(inputs(lambda p:(base/p).read_bytes()))==m['inputs'],'closed input manifest')
    for row in inputs(lambda p:(base/p).read_bytes()):require((out/'inputs'/(row['id']+'.x')).read_bytes()==row['bytes'],'retained exact input bytes')
    for build in m['builds']:
        variant,opt=build['variant'],build['optimization']
        changes,patches,expected=source_expected(base,variant=='observed',PureWindowsPath(m['input_root']),'/'+opt)
        require(build['patches']==patches and build['before']==expected==build['after'],'insertion/inverse/source-end binding')
        source=out/'sources'/build['id']
        # Replay portable modes from the authenticated source inventories on Windows.
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
    require(m['schema']==SCHEMA and m['base']==BASE and m['paths']==PATHS and re.fullmatch('[0-9a-f]{40}',m['head']),'diagnostic generation/head')
    verify_sources(out,m)
    require([b['id'] for b in m['builds']]==[v+'-'+opt for opt in ('Od','O2') for v in ('control','observed')],'actual build matrix')
    parsed={}
    for b in m['builds']:
        directory=out/b['id'];opt='/'+b['optimization'];source=b['source'];target=b['target']
        for label in ('configure','native-build','rust-build','mesh_dump','x_files','native','rust'):
            receipt,stdout,stderr=checked(directory,label)
            require(receipt['argv']==b['commands'][label] and receipt['cwd']==(str(PureWindowsPath(source)/'rust') if label.startswith('rust') or label in ('mesh_dump','x_files') else source),'exact command/cwd binding')
            require(receipt['env'].get('CARGO_TARGET_DIR')==target and receipt['env'].get('CARGO_INCREMENTAL')=='0' and receipt['env'].get('RUSTFLAGS')=='--cfg mds_floor_profile --check-cfg=cfg(mds_floor_profile)','closed Cargo environment')
        native_command=(directory/'native-build.stdout').read_text(errors='replace')+(directory/'native-build.stderr').read_text(errors='replace')
        # /v:diag retains actual MSBuild CL and Link task command lines for core and console.
        commands=[line.strip() for line in native_command.splitlines() if re.search(r'(?i)(?:cl|link)\.exe(?:"|\s)',line)]
        require(commands and any(opt in line and ('accessory.cpp' in line or 'accessory.obj' in line) for line in commands) and any(opt in line and 'native.cpp' in line for line in commands) and any('floor_profile.exe' in line and 'link.exe' in line.lower() for line in commands),'actual core/console compile and link commands')
        require(commands==b['actual_native_commands'],'retained parsed compile/link commands')
        require(b['objects'] and any(path.endswith('/accessory.obj') for path in b['objects']) and any(path.endswith('/native.obj') for path in b['objects']),'core/console object closure')
        for path,row in b['objects'].items():
            h.safe_name(path);raw=(directory/'objects'/path).read_bytes();require(len(raw)==row['size'] and digest(raw)==row['sha256'],'compiled object bytes')
        require(b['original_native_binary']['sha256']==b['binaries']['floor_profile.exe']['sha256'] and b['original_rust_binary']['sha256']==b['binaries']['rust-profile.exe']['sha256'],'original build output/executed binary identity')
        for name,row in b['binaries'].items():
            raw=(directory/name).read_bytes();require(digest(raw)==row['sha256'] and len(raw)==row['size'],'binary/source binding');pe_exports(raw) if name=='d3dx9_43.dll' else require(raw[:2]==b'MZ','actual executable PE')
        require(b['commands']['native']==[str(PureWindowsPath(b['evidence'])/'floor_profile.exe'),'fixed',b['variant']],'native exact argv')
        mode=['--release'] if b['optimization']=='O2' else []
        require(b['commands']['rust-build']==['cargo','+1.95.0','test','-p','mds-accessory','--lib','--no-run','--message-format=json']+mode,'pinned Rust build')
        for test in ('mesh_dump','x_files'):
            require(b['commands'][test]==['cargo','+1.95.0','test','-p','mds-accessory','--test',test]+mode+['--','--test-threads=1'],'unchanged integration fixture commands')
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
            for id,_,_ in CASES:
                a,b=control[language]['cases'][id],observed[language]['cases'][id]
                require(mesh(a['final'])==mesh(b['final']) and a['final_materials']==b['final_materials'],'control/observed bitwise initialized final state')
            a,b=[p[language]['cases'] for p in (control,observed)]
            require(mesh(a['floor-top']['final'])!=mesh(a['floor-affine']['final']) and mesh(b['floor-top']['final'])!=mesh(b['floor-affine']['final']),'genuine normal-exit affine sensitivity')
        results[opt]=classify(*observed)
    result={'schema':SCHEMA,'head':m['head'],'results':results,'hosted':'ExecutedWindowsOnly','profile_adoption':'NotAuthorized'}
    require(load_json((out/'result.json').read_bytes())==result,'rederived diagnostic result')
    return result


def run(out,build_root,toolchain):
    require(sys.platform=='win32' and os.environ.get('GITHUB_ACTIONS')=='true','explicit hosted Windows execution only')
    require(build_root and toolchain and toolchain.is_file() and not out.exists() and not build_root.exists() and not out.is_relative_to(ROOT) and not build_root.is_relative_to(ROOT) and not out.is_relative_to(build_root) and not build_root.is_relative_to(out),'fresh external evidence/build roots')
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
    input_root=out/'inputs';input_root.mkdir();rows=inputs(lambda p:(base/p).read_bytes())
    for row in rows:(input_root/(row['id']+'.x')).write_bytes(row['bytes'])
    m={'schema':SCHEMA,'base':BASE,'head':head,'paths':PATHS,'input_root':str(input_root),'inputs':input_manifest(rows),'base_inventory':c.source_inventory(base),'builds':[],
       'configuration_differences':'Native Release in both modes, appended /Od or /O2 on core and console; Rust dev versus release defaults, opt-level/debug assertions/overflow/debuginfo differ. Observed copies add private sink calls only.'}
    parsed={}
    for opt in ('Od','O2'):
        for variant in ('control','observed'):
            id=variant+'-'+opt;directory=out/id;directory.mkdir();source=out/'sources'/id;shutil.copytree(base,source)
            changes,patches,expected=source_expected(base,variant=='observed',input_root,'/'+opt)
            for path,raw in changes.items():(source/path).write_bytes(raw)
            for path,row in expected.items():c.TRANSPORT_MODES[str((source/path).resolve())]=row['mode']
            require(c.source_inventory(source)==expected,'generated source initial closure')
            native_target=build_root/id/'native';target=build_root/id/'rust'
            e=env|{'CARGO_TARGET_DIR':str(target),'CARGO_INCREMENTAL':'0','CARGO_TERM_COLOR':'never','RUSTFLAGS':'--cfg mds_floor_profile --check-cfg=cfg(mds_floor_profile)'}
            commands={
                'configure':['cmake','-S',str(source),'-B',str(native_target),'-G','Visual Studio 17 2022','-A','x64','-DCMAKE_TOOLCHAIN_FILE='+str(toolchain),'-DBUILD_TESTING=OFF','-DMIKUDANCESTUDIO_DIAG=OFF'],
                'native-build':['cmake','--build',str(native_target),'--config','Release','--target','floor_profile','--parallel','4','--','/v:diag'],
                'native':[str(directory/'floor_profile.exe'),'fixed',variant],
                'rust-build':['cargo','+1.95.0','test','-p','mds-accessory','--lib','--no-run','--message-format=json']+(['--release'] if opt=='O2' else []),
            }
            for label in ('configure','native-build'):
                require(record(directory,label,commands[label],source,e,2400)['status']==0,'native '+label+' failure is not SemanticDifference')
            shutil.copyfile(native_target/'Release/floor_profile.exe',directory/'floor_profile.exe')
            raw=(directory/'native-build.stdout').read_text(errors='replace')+(directory/'native-build.stderr').read_text(errors='replace')
            actual=[line.strip() for line in raw.splitlines() if re.search(r'(?i)(?:cl|link)\.exe(?:"|\s)',line)]
            require(record(directory,'native',commands['native'],source,e,300)['status']==0,'native normal exit required')
            native=parse((directory/'native.stdout').read_bytes(),'native',variant=='observed')
            shutil.copyfile(native['dll']['path'],directory/'d3dx9_43.dll')
            require(record(directory,'rust-build',commands['rust-build'],source/'rust',e)['status']==0,'Rust build')
            cargo=[load_json(line) for line in (directory/'rust-build.stdout').read_bytes().splitlines() if line.startswith(b'{')]
            require(cargo and cargo[-1]=={'reason':'build-finished','success':True},'Cargo build terminal')
            executables=[row['executable'] for row in cargo if row.get('reason')=='compiler-artifact' and row.get('target',{}).get('name')=='mds_accessory' and row.get('executable')]
            require(len(executables)==1,'actual Rust unit binary');shutil.copyfile(executables[0],directory/'rust-profile.exe')
            commands['rust']=[str(directory/'rust-profile.exe'),'mesh::floor_profile::diagnostic','--exact','--nocapture','--test-threads=1']
            require(record(directory,'rust',commands['rust'],source/'rust',e,300)['status']==0,'Rust probe normal exit')
            rust=parse((directory/'rust.stdout').read_bytes(),'rust',variant=='observed')
            for test in ('mesh_dump','x_files'):
                commands[test]=['cargo','+1.95.0','test','-p','mds-accessory','--test',test]+(['--release'] if opt=='O2' else [])+['--','--test-threads=1']
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
            b={'id':id,'variant':variant,'optimization':opt,'source':str(source),'target':str(target),'evidence':str(directory),'commands':commands,'patches':patches,'before':expected,'after':c.source_inventory(source),'actual_native_commands':actual,'binaries':binaries,'objects':objects,'original_native_binary':{'path':str(native_target/'Release/floor_profile.exe'),'sha256':digest((native_target/'Release/floor_profile.exe').read_bytes())},'original_rust_binary':{'path':executables[0],'sha256':digest(Path(executables[0]).read_bytes())}}
            m['builds'].append(b);write_json(out/'manifest.json',m);parsed[id]=(native,rust)
    result={'schema':SCHEMA,'head':head,'results':{opt:classify(*parsed['observed-'+opt]) for opt in ('Od','O2')},'hosted':'ExecutedWindowsOnly','profile_adoption':'NotAuthorized'}
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
