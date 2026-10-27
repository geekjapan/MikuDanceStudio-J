#!/usr/bin/env python3
"""Conditional floor geometry diagnostic; default replay only reads retained files."""
import argparse
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = '2c40c2878d726926c30bf5fa6220fd754032daf1'
PREFIX = 'tools/renderer-floor-geometry/'
WORKFLOW = '.github/workflows/renderer-floor-geometry.yml'

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

old = module('floor_projection', 'tools/renderer-shadow-eligibility/run.py')
c = module('floor_common', 'tools/renderer-shadow-eligibility/capture.py')
h = c.h
require, digest, load_json = old.require, old.digest, old.load_json
ORIGINS = {'native_geometry':'ActualProductionLoaderOnHostedHAL',
           'placement':'OriginalSourceBodyWithProjectedFixtureState',
           'rust':'ActualCanonicalFrame30CpuUploadNotGpuReadback',
           'native_pmm_timeline_shadow_draw':'NotExecuted',
           'native_projected_upload':'DiagnosticD3DXTransformOfLoadedVerticesNotDrawOrNativeUpload',
           'internal_loader_CloneMeshFVF_ComputeNormals_HRESULTs':'Unobserved',
           'noninterference':'CommonSnapshotConsoleNotFullApplication'}

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def record(out, label, argv, cwd, env, timeout=1200):
    row = {'argv':list(map(str,argv)), 'cwd':str(cwd), 'env':{k:v for k,v in env.items() if k in ('PATH','HOME','CARGO_HOME','RUSTUP_HOME','TMPDIR','LD_LIBRARY_PATH','WGPU_BACKEND','VK_ICD_FILENAMES','XDG_RUNTIME_DIR','CARGO_TERM_COLOR','CARGO_INCREMENTAL','CARGO_TARGET_DIR','CXX','MDS_RENDER_PNG_DIR','INCLUDE','LIB','LIBPATH','VCToolsInstallDir','WindowsSdkDir','WindowsSDKVersion')}, 'start_utc':utc(), 'start_ns':time.time_ns(), 'status':None, 'terminal':'launch_failure'}
    require(not (out/(label+'.json')).exists(), 'fresh command')
    try:
        with (out/(label+'.stdout')).open('xb') as stdout, (out/(label+'.stderr')).open('xb') as stderr:
            try:
                p = subprocess.run(row['argv'],cwd=cwd,env=env,stdout=stdout,stderr=stderr,timeout=timeout)
                row.update(status=p.returncode,terminal='exit')
            except subprocess.TimeoutExpired:
                row['terminal'] = 'timeout'
            except OSError as e:
                row['launch_error'] = str(e)
    finally:
        row.update(end_utc=utc(),end_ns=time.time_ns())
        for suffix in ('stdout','stderr'):
            raw=(out/(label+'.'+suffix)).read_bytes()
            row[suffix]={'name':label+'.'+suffix,'sha256':digest(raw),'size':len(raw)}
        (out/(label+'.json')).write_text(json.dumps(row,indent=2)+'\n')
    return row

def checked(out,label,status=0):
    row,a,b=c.receipt(out,label,status)
    require(row['terminal']=='exit' and row['start_utc'] and row['end_utc'], 'normal terminal receipt')
    return row,a,b

def projection(base):
    blobs=old.fixed(base)
    prior=old.fixture_projection(blobs)['accessories'][0]
    raw=blobs[old.PMM]
    fields={}
    for name,offset,fmt in [('parentModel',3147,'i'),('parentBone',3151,'i'),('rotation[0]',3155,'I'),('rotation[1]',3159,'I'),('rotation[2]',3163,'I'),('scale',3167,'I'),('position[0]',3171,'I'),('position[1]',3175,'I'),('position[2]',3179,'I')]:
        text='        Rd(fd, &accessory.'+name+', 4);'
        fields[name]={'offset':offset,'size':4,'raw_hex':raw[offset:offset+4].hex(),'value':struct.unpack_from('<'+fmt,raw,offset)[0],'assignment':old.assignment(blobs,'src/io/pmm_load_v2.cpp',text)}
    require(fields['parentModel']['value']==-1, 'fixed floor parent')
    return {'source':BASE,'fixture':old.FIXTURES[old.PMM],'asset':old.FIXTURES[old.FLOOR],'slot':prior['slot'],'frame':30,'prior':prior,'fields':fields}

def wire(p):
    f=p['fields']; a=p['prior']['fields']
    values=[f['parentModel']['value'],f['parentBone']['value']]+[a[n]['value'] for n in ('visible','shadowEnabled','additiveBlend')]+[f[n]['value'] for n in ('rotation[0]','rotation[1]','rotation[2]','scale','position[0]','position[1]','position[2]')]
    return ' '.join(map(str,values))+'\n'

def extract(base):
    manifest={}
    def span(path,begin,end):
        raw=(base/path).read_bytes(); b,e=begin.encode(),end.encode()
        require(raw.count(b)==1 and raw.count(e)==1,'unique source span')
        first,last=raw.index(b),raw.index(e)
        require(first<last,'span order')
        manifest[path]={'source_sha256':digest(raw),'start':first,'end':last,'sha256':digest(raw[first:last]),'text':raw[first:last].decode()}
        return raw[first:last].decode()
    reader=span('src/tools/mesh_dump.cpp','void Add(std::string& out,','bool AddRaw(')
    placement=span(old.ACCESSORY,'void AccessoryPlacement(','// Faithful transcription of sub_4C4A10')
    edits=[]
    def replace(before,after):
        nonlocal reader
        require(reader.count(before)==1,'reader patch unique '+before)
        edits.append({'before':before,'after':after});reader=reader.replace(before,after)
    replace('FAILED(mesh->GetDeclaration(decl))','!Checked(out,"GetDeclaration",mesh->GetDeclaration(decl))')
    replace('FAILED(mesh->LockVertexBuffer(D3DLOCK_READONLY, &locked))','!Checked(out,"LockVertexBuffer",mesh->LockVertexBuffer(D3DLOCK_READONLY, &locked))')
    replace('FAILED(mesh->LockIndexBuffer(D3DLOCK_READONLY, &ib))','!Checked(out,"LockIndexBuffer",mesh->LockIndexBuffer(D3DLOCK_READONLY, &ib))')
    replace('FAILED(mesh->LockAttributeBuffer(D3DLOCK_READONLY, &attributes))','!Checked(out,"LockAttributeBuffer",mesh->LockAttributeBuffer(D3DLOCK_READONLY, &attributes))')
    replace('        elements.push_back(e);','        if(e.Stream != 0 || e.Offset + ElementBytes(e.Type) > stride) return false;\n        if(e.Method != 0) return false;\n        Raw(out,"decl_bytes",&e,sizeof e);\n        elements.push_back(e);')
    replace('    const auto* vb = static_cast<const unsigned char*>(locked);','    Raw(out,"vb",locked,static_cast<size_t>(vertices)*stride);\n    const auto* vb = static_cast<const unsigned char*>(locked);')
    replace('    mesh->UnlockVertexBuffer();','    if(!Checked(out,"UnlockVertexBuffer",mesh->UnlockVertexBuffer()))return false;')
    replace('        mesh->UnlockIndexBuffer();','        Checked(out,"UnlockIndexBufferFailure",mesh->UnlockIndexBuffer());')
    replace('    const bool wide = (options & 1) != 0;', '    Raw(out,"ib",ib,static_cast<size_t>(faces)*3*((options&1)?4:2));\n    Raw(out,"attributes",attributes,static_cast<size_t>(faces)*4);\n    const bool wide = (options & 1) != 0;')
    replace('    mesh->UnlockAttributeBuffer();','    if(!Checked(out,"UnlockAttributeBuffer",mesh->UnlockAttributeBuffer()))return false;')
    replace('    mesh->UnlockIndexBuffer();','    if(!Checked(out,"UnlockIndexBuffer",mesh->UnlockIndexBuffer()))return false;')
    replace('    mesh->GetAttributeTable(nullptr, &tableSize);','    if(!Checked(out,"GetAttributeTableSize",mesh->GetAttributeTable(nullptr, &tableSize)))return false;')
    replace('FAILED(mesh->GetAttributeTable(table.data(), &tableSize))','!Checked(out,"GetAttributeTable",mesh->GetAttributeTable(table.data(), &tableSize))')
    replace('    void* locked = nullptr;', '    IDirect3DVertexBuffer9* vertexBuffer=nullptr;\n    if(!Checked(out,"GetVertexBuffer",mesh->GetVertexBuffer(&vertexBuffer)))return false;\n    D3DVERTEXBUFFER_DESC vd{};const HRESULT vh=vertexBuffer->GetDesc(&vd);vertexBuffer->Release();\n    if(!Checked(out,"VertexBufferGetDesc",vh) || vd.Size != vertices*stride)return false;\n    Add(out,"vb_size %u\\n",vd.Size);\n    IDirect3DIndexBuffer9* indexBuffer=nullptr;\n    if(!Checked(out,"GetIndexBuffer",mesh->GetIndexBuffer(&indexBuffer)))return false;\n    D3DINDEXBUFFER_DESC id{};const HRESULT ih=indexBuffer->GetDesc(&id);indexBuffer->Release();\n    if(!Checked(out,"IndexBufferGetDesc",ih) || id.Size != faces*3*((options&1)?4:2))return false;\n    Add(out,"ib_size %u %u\\n",id.Size,unsigned(id.Format));\n    void* locked = nullptr;')
    replace('        Add(out, "v %lu", i);', '        if(projectedWorld && std::strcmp(section,"record")==0) {\n            if(mesh->GetFVF()!=274 || stride!=32) {Checked(out,"RejectedVertexUnlock",mesh->UnlockVertexBuffer());return false;}\n            D3DXVECTOR3 p,n;std::memcpy(&p,vertex,12);std::memcpy(&n,vertex+12,12);\n            D3DXVECTOR4 q;D3DXVec3Transform(&q,&p,reinterpret_cast<const D3DXMATRIX*>(projectedWorld));\n            D3DXVec3TransformNormal(&n,&n,reinterpret_cast<const D3DXMATRIX*>(projectedWorld));D3DXVec3Normalize(&n,&n);\n            float upload[8]={q.x,q.y,q.z,n.x,n.y,n.z};std::memcpy(upload+6,vertex+24,8);Raw(out,"projected_upload",upload,32);\n        }\n        Add(out, "v %lu", i);')
    inverse=reader
    for edit in reversed(edits):
        require(inverse.count(edit['after'])==1,'inverse patch uniqueness')
        inverse=inverse.replace(edit['after'],edit['before'])
    require(inverse==manifest['src/tools/mesh_dump.cpp']['text'],'reader inverse proof')
    source=(HERE/'native.cpp.in').read_text().replace('@READER@',reader).replace('@PLACEMENT@',placement)
    return source,{'spans':manifest,'reader_edits':edits,'inverse_sha256':digest(inverse.encode()),'generated_sha256':digest(source.encode())}

SCENE='''    if std::thread::current().name() == Some("selfshadow_30") {
        for (ordinal, (a, (state, world))) in pmm.accessories.iter().zip(&states).enumerate() {
            eprintln!("FG_BIND {} {} {} {} {}",ordinal,a.slot,frame,a.path.text,world.len());
            eprintln!("FG_STATE {} {} {} {} {} {} {} {} {}",ordinal,state.parent_model,state.parent_bone,u8::from(state.visible),u8::from(state.shadow_enabled),u8::from(state.additive_blend),state.opacity.to_bits(),state.rotation.iter().chain(std::iter::once(&state.scale)).chain(&state.position).map(|v|v.to_bits().to_string()).collect::<Vec<_>>().join(" "),world.len());
        }
    }
'''
PREP='''        let floor_ranges: &Vec<(u32,u32)> = &ranges;
        if std::thread::current().name() == Some("selfshadow_30") {
            eprintln!("FG_PREP {}",index_data.iter().map(|b|format!("{b:02x}")).collect::<String>());
            for (i,(start,count)) in floor_ranges.iter().enumerate() { eprintln!("FG_RANGE {} {} {}",i,start,count); }
        }
'''
def generated(base, observed):
    changes={h.COMMON:h.COMMON_CHANGES}
    if observed:
        text=(base/h.GOLDEN).read_text(); begin=text.index('    let states: Vec<_> = pmm\n'); end=text.index('    let draws: Vec<AccessoryDraw>',begin)
        changes[h.GOLDEN]=[('        physics.step().unwrap();\n','        if std::thread::current().name() == Some("selfshadow_30") { eprintln!("FG_STEP"); }\n'),(text[begin:end],SCENE)]
        r=(base/h.RENDERER).read_text(); start=r.index('        let accessory_keys = Self::accessory_keys(stage);'); end=r.index('    /// The keys of the accessories',start)
        scope=r[start:end]; anchor=scope[:scope.index('            self.queue.write_buffer(&p.vertices, 0, &bytes(&body));')]
        prep_start=r.index('    fn prepare_accessory('); prep_end=r.index('        let mut uploaded = HashMap::new();',prep_start)
        prep=r[prep_start:prep_end]
        changes[h.RENDERER]=[(anchor,(HERE/'observer.rs').read_text()),(prep,PREP)]
    return {name:h.insertions((base/name).read_text(),rows) for name,rows in changes.items()}

def validate_source(base,dest,observed):
    expected=c.source_inventory(base)
    for name,(text,_) in generated(base,observed).items(): expected[name]=expected[name]|{'sha256':digest(text.encode())}
    require(c.source_inventory(dest)==expected,'generated source/inverse identity')
    return expected

def words(values,count=None):
    v=values.split();require(count is None or len(v)==count,'word count')
    require(all(re.fullmatch('0|[1-9][0-9]*',x) and int(x)<=0xffffffff for x in v),'u32 words')
    return list(map(int,v))

def floats(values):
    require(all(math.isfinite(struct.unpack('<f',struct.pack('<I',v))[0]) for v in values),'finite initialized floats')
    return values

def hexbytes(text):
    require(bool(re.fullmatch('(?:[0-9a-f]{2})+',text)),'raw byte wire')
    return bytes.fromhex(text)

def ints(raw,width=4):
    require(len(raw)%width==0,'truncated index buffer')
    return list(struct.unpack('<'+('I' if width==4 else 'H')*(len(raw)//width),raw))

def validate_mesh(m):
    n,f,s=m['vertices'],m['faces'],m['stride'];require(0<n<=1000000 and 0<f<=1000000 and 0<s<=256,'bounded mesh size')
    vb,ib,attributes=[hexbytes(m[k]) for k in ('vb','ib','attributes')]
    require(m['vb_size']==n*s and m['ib_size']==[f*3*m['index_width'],101 if m['index_width']==2 else 102],'actual buffer declaration sizes/format')
    require(len(vb)==n*s and len(ib)==f*3*m['index_width'] and len(attributes)==f*4,'buffer sizes')
    index=ints(ib,m['index_width']);attrs=ints(attributes)
    require(all(i<n for i in index) and all(i<m['materials'] for i in attrs),'index/material bounds')
    decl=m['decl'];require(decl and len(set(map(tuple,decl)))==len(decl),'unique declaration')
    used=set();semantic=[]
    for off,typ,usage,ui in decl:
        require(0<=typ<=3 and ui==0 and usage in (0,3,5),'supported initialized floor declaration')
        size=4*(typ+1);require(off+size<=s and not used.intersection(range(off,off+size)),'declaration overlap/bounds');used.update(range(off,off+size))
    for i in range(n):
        row={}
        for off,typ,usage,ui in decl:
            if usage in m.get('initialized_usage',[d[2] for d in decl]):row[str(usage)]=floats(ints(vb[i*s+off:i*s+off+4*(typ+1)]))
        require('0' in row and len(row['0'])==3,'position declaration');semantic.append(row)
    require(len(m['table'])>0,'attribute table')
    covered=[]
    for material,start,count,vs,vc in m['table']:
        require(material<m['materials'] and start+count<=f and vs+vc<=n and count>0,'attribute table bounds')
        require(attrs[start:start+count]==[material]*count and all(vs<=i<vs+vc for i in index[start*3:(start+count)*3]),'attribute table face/index binding')
        covered.extend(range(start,start+count))
    require(sorted(covered)==list(range(f)),'complete nonoverlapping attribute table')
    return {'vertices':semantic,'indices':index,'attributes':attrs,'table':m['table'],'materials':m['material_bits'],'representation':{k:m[k] for k in ('fvf','options','stride','index_width','decl')}|{'unproved_initialization_usage':[d[2] for d in decl if d[2] not in m.get('initialized_usage',[v[2] for v in decl])]}}

def native_parse(text,status):
    require(status==0 and 'SKIP' not in text,'native normal execution')
    lines=text.splitlines();require(lines[0]=='MDS_FLOOR_V1' and lines[-1]=='end 0','native framing')
    result={'raw':None,'observation':None,'final':None}; current=None; snapshot=None; loader=0; hrs=[]
    for line in lines[1:-1]:
        a=line.split();require(a,'empty wire')
        if a[0]=='hr':
            require(len(a)==3 and re.fullmatch('[0-9a-f]{8}',a[2]) and int(a[2],16)<0x80000000,'failed capture HRESULT');hrs.append(a[1]);continue
        if a[0]=='loader': require(a==['loader','1'] and loader==0,'production loader result');loader=1;continue
        if a[0]=='snapshot':
            require(len(a)==2 and a[1] in ('observation','final') and result[a[1]] is None,'snapshot identity')
            snapshot={};result[a[1]]=snapshot;continue
        if a[0] in ('raw','record'):
            require(len(a)==11 and a[1::2]==['fvf','options','vertices','faces','stride'],'mesh header')
            current=dict(zip(('fvf','options','vertices','faces','stride'),map(int,a[2::2])))
            current.update(index_width=4 if current['options']&1 else 2,decl=[],decl_bytes=[],table=[],material_bits=[],decoded_vertices=[],decoded_faces=[],projected_upload=[])
            if a[0]=='raw':
                require(result['raw'] is None and snapshot is None,'raw uniqueness');result['raw']=current
            else:
                require(snapshot is not None and 'mesh' not in snapshot,'record snapshot');snapshot['mesh']=current
            continue
        require(current is not None,'mesh required')
        tag=a[0]
        if tag=='decl_bytes': current['decl_bytes'].append(a[1])
        elif tag=='decl': current['decl'].append(words(' '.join(a[1:]),4))
        elif tag=='vb_size':
            require('vb_size' not in current,'duplicate VB size');current['vb_size']=int(a[1])
        elif tag=='ib_size':
            require('ib_size' not in current,'duplicate IB size');current['ib_size']=list(map(int,a[1:]))
        elif tag=='projected_upload': current['projected_upload'].extend(ints(hexbytes(a[1])))
        elif tag=='v': current['decoded_vertices'].append(a[1:])
        elif tag=='f': current['decoded_faces'].append(words(' '.join(a[1:]),5))
        elif tag=='t': current['table'].append(words(' '.join(a[1:]),5))
        elif tag=='material': current['material_bits'].append(floats(ints(hexbytes(a[1]))))
        elif tag=='material_bits':
            require(not current['material_bits'],'duplicate materials')
            data=ints(hexbytes(a[1]));require(len(data)%17==0,'material byte size')
            current['material_bits']=[floats(data[i:i+17]) for i in range(0,len(data),17)]
        elif tag in ('vb','ib','attributes','materials','table'):
            key='table_count' if tag=='table' else tag
            require(key not in current,'duplicate mesh field')
            current[key]=int(a[1]) if tag in ('materials','table') else a[1]
        elif tag in ('texture_types','texture_paths','name','directory','source_path','record_metadata','world','position','rotation','scale','state','opacity'):
            require(snapshot is not None and tag not in snapshot,'duplicate/missing snapshot field')
            snapshot[tag]=a[1:] if tag in ('state','record_metadata') else a[1]
        elif tag=='device':
            require(snapshot is not None,'device snapshot')
            d=snapshot.setdefault('device',{});require(a[1] not in d,'duplicate device state');d[a[1]]=int(a[2])
        else: raise ValueError('unknown native record '+tag)
    require(loader==1 and result['raw'] and result['final'],'complete native packet')
    mesh_count=2+int(result['observation'] is not None)
    expected_hrs={'CreateDevice':1,'D3DXLoadMeshFromXW':1,'GetRenderState':5*(mesh_count-1)}
    for name in ('GetDeclaration','GetVertexBuffer','VertexBufferGetDesc','GetIndexBuffer','IndexBufferGetDesc','LockVertexBuffer','UnlockVertexBuffer','LockIndexBuffer','LockAttributeBuffer','UnlockAttributeBuffer','UnlockIndexBuffer','GetAttributeTableSize','GetAttributeTable'):expected_hrs[name]=mesh_count
    if 'InterventionLock' in hrs:expected_hrs.update(InterventionLock=1,InterventionUnlock=1)
    require({name:hrs.count(name) for name in set(hrs)}==expected_hrs,'missing/duplicate/unknown capture HRESULT')
    for m in [result['raw']]+[v['mesh'] for v in (result['observation'],result['final']) if v]:
        m['initialized_usage']=[d[2] for d in result['raw']['decl']]
        require(len(m['material_bits'])==m['materials'] and all(len(v)==17 for v in m['material_bits']),'complete material records')
        require(len(m['decoded_vertices'])==m['vertices'] and [int(v[0]) for v in m['decoded_vertices']]==list(range(m['vertices'])),'decoded vertex coverage')
        require(len(m['decoded_faces'])==m['faces'] and [v[0] for v in m['decoded_faces']]==list(range(m['faces'])),'decoded face coverage')
        require(m['table_count']==len(m['table']),'table coverage')
        require(len(m['decl_bytes'])==len(m['decl']),'complete declaration bytes')
        for raw_decl,semantic in zip(m['decl_bytes'],m['decl']):
            raw_decl=hexbytes(raw_decl);require(len(raw_decl)==8,'declaration byte size')
            stream,offset,typ,method,usage,ui=struct.unpack('<HHBBBB',raw_decl)
            require(stream==method==0 and [offset,typ,usage,ui]==semantic,'raw/initialized declaration binding')
        decoded=validate_mesh(m)
        require([v[1:] for v in m['decoded_faces']]==[decoded['indices'][3*i:3*i+3]+[decoded['attributes'][i]] for i in range(m['faces'])],'decoded face/raw buffer agreement')
    for v in (result['observation'],result['final']):
        if v:
            require(set(v)=={'mesh','texture_types','texture_paths','name','directory','source_path','record_metadata','world','position','rotation','scale','state','opacity','device'},'snapshot coverage')
            require(len(ints(hexbytes(v['world'])))==16 and len(v['device'])==5,'world/device coverage')
            floats(ints(hexbytes(v['world'])))
            require(len(hexbytes(v['name']))==100 and len(hexbytes(v['directory']))==len(hexbytes(v['source_path']))==512 and len(hexbytes(v['texture_paths']))==2048*v['mesh']['materials'] and len(hexbytes(v['texture_types']))==v['mesh']['materials'],'initialized record metadata sizes')
            require(len(v['record_metadata'])==3 and len(v['state'])==5,'record scalar coverage')
    return result

def rust_parse(text,p):
    lines=[line.split() for line in text.splitlines() if line.startswith('FG_')]
    require(sum(a==['FG_STEP'] for a in lines)==30,'actual step count')
    def one(tag):
        rows=[a[1:] for a in lines if a[0]==tag];require(len(rows)==1,'missing/duplicate '+tag);return rows[0]
    require(set(a[0] for a in lines)=={'FG_STEP','FG_BIND','FG_STATE','FG_PREP','FG_RANGE','FG_UPLOAD','FG_WORLD','FG_LOCAL','FG_V','FG_I','FG_A','FG_M','FG_T'},'Rust record domain')
    require(one('FG_BIND')==['0',str(p['slot']),'30','.\\shadow_floor.x','16'],'stable fixture slot/frame/path')
    state=one('FG_STATE');require(state[0]=='0' and list(map(int,state[1:3]))==[-1,0] and state[-1]=='16','floor state identity')
    expected=wire(p).split();require(state[1:6]==expected[:5] and state[6]=='1065353216' and state[7:-1]==expected[5:],'actual frame state/projected fixture mismatch')
    local=one('FG_LOCAL');require(local[0]=='0','floor local slot');n,ni,nm=map(int,local[1:]);require(n>0 and ni>0 and ni%3==0 and nm>0,'Rust mesh sizes')
    vertex=[a[1:] for a in lines if a[0]=='FG_V'];require(len(vertex)==n and [v[:2] for v in vertex]==[['0',str(i)] for i in range(n)],'ordered vertex coverage')
    vertices=[floats(words(' '.join(v[2:]),8)) for v in vertex]
    ii=one('FG_I');aa=one('FG_A');require(ii[0]==aa[0]=='0','index/attribute identity')
    index=words(' '.join(ii[1:]),ni);attrs=words(' '.join(aa[1:]),ni//3)
    require(all(i<n for i in index) and all(a<nm for a in attrs),'Rust index/material bounds')
    mm=[a[1:] for a in lines if a[0]=='FG_M'];require(len(mm)==nm and [v[:2] for v in mm]==[['0',str(i)] for i in range(nm)],'material coverage')
    materials=[floats(words(' '.join(v[2:]),17)) for v in mm]
    tables=[words(' '.join(a[1:]),6) for a in lines if a[0]=='FG_T'];require(tables and all(t[0]==0 for t in tables),'Rust local attribute table identity')
    covered=[]
    for _,material,start,count,vs,vc in tables:
        require(material<nm and start+count<=ni//3 and vs+vc<=n and attrs[start:start+count]==[material]*count and all(vs<=v<vs+vc for v in index[start*3:(start+count)*3]),'Rust local attribute table bounds')
        covered.extend(range(start,start+count))
    require(sorted(covered)==list(range(ni//3)),'Rust attribute table coverage')
    world=one('FG_WORLD');upload=one('FG_UPLOAD');require(world[0]==upload[0]=='0','upload identity')
    world=floats(words(' '.join(world[1:]),16));body=hexbytes(upload[1]);require(len(body)==n*32,'upload size');floats(ints(body))
    prepared=ints(hexbytes(one('FG_PREP')[0]));require(len(prepared)==ni and all(i<n for i in prepared),'prepared indices')
    ranges=[words(' '.join(a[1:]),3) for a in lines if a[0]=='FG_RANGE'];require([v[0] for v in ranges]==list(range(nm)),'prepared material domain')
    ordered=[]
    for material,start,count in ranges:
        require(start==len(ordered) and count%3==0,'prepared range continuity')
        subset=[i for f,a in enumerate(attrs) if a==material for i in index[3*f:3*f+3]]
        require(len(subset)==count,'prepared range count');ordered.extend(subset)
    require(ordered==prepared,'actual prepared upload/subsets')
    return {'vertices':vertices,'indices':index,'attributes':attrs,'materials':materials,'world':world,'upload':ints(body),'prepared':prepared,'ranges':ranges,'state':state,'table':[t[1:] for t in tables]}

def semantic_snapshot(s):
    return {k:v for k,v in s.items() if k!='mesh'}|{'mesh':validate_mesh(s['mesh'])}

def comparison(native,rust):
    differences={};representation={}
    loaded=validate_mesh(native['final']['mesh']);raw=validate_mesh(native['raw'])
    for name,m in [('raw',raw),('loaded',loaded)]:
        v=m['vertices'];local=[dict([('0',x[:3]),('3',x[3:6]),('5',x[6:8])]) for x in rust['vertices']]
        # Raw declarations can omit generated normal/UV channels. Compare only declared initialized channels.
        native_channels=set.intersection(*(set(x) for x in v))
        rv=[{k:x[k] for k in native_channels} for x in local]
        for field,a,b in [('vertices',v,rv),('indices',m['indices'],rust['indices']),('attributes',m['attributes'],rust['attributes']),('table',m['table'],rust['table']),('materials',m['materials'],rust['materials'])]:
            if a!=b:differences[name+'.'+field]={'native':a,'rust':b}
        representation[name]=m['representation']
    upload=native['final']['mesh']['projected_upload']
    require(len(upload)==native['final']['mesh']['vertices']*8,'complete native projected upload')
    initialized=native['final']['mesh']['initialized_usage']
    channels=[i for i in range(8) if (0 if i<3 else 3 if i<6 else 5) in initialized]
    observed_upload=[v for i,v in enumerate(upload) if i%8 in channels]
    rust_upload=[v for i,v in enumerate(rust['upload']) if i%8 in channels]
    floats(observed_upload)
    if observed_upload!=rust_upload:differences['projected_upload']={'native':observed_upload,'rust':rust_upload}
    world=ints(hexbytes(native['final']['world']))
    if world!=rust['world']:differences['world']={'native':world,'rust':rust['world']}
    native_prepared=[];ranges=[]
    for material in range(len(loaded['materials'])):
        start=len(native_prepared)
        for f,a in enumerate(loaded['attributes']):
            if a==material:native_prepared.extend(loaded['indices'][3*f:3*f+3])
        ranges.append([material,start,len(native_prepared)-start])
    for field,a,b in [('prepared',native_prepared,rust['prepared']),('ranges',ranges,rust['ranges'])]:
        if a!=b:differences[field]={'native':a,'rust':b}
    scope={'initialized_usage':native['final']['mesh']['initialized_usage'],'unknown_initialization_usage':loaded['representation']['unproved_initialization_usage'],'origin':{'source':old.ACCESSORY,'operation':'production CloneMeshFVF to FVF274','raw_declaration':raw['representation']['decl'],'loaded_declaration':loaded['representation']['decl']},'reason':'Clone-added declaration channels have no established initialization guarantee; raw bytes retained, those channels are not compared','agreement_excludes':'Unknown-initialization channels and arbitrary padding; not full vertex-buffer or UV equality'}
    return {'initialization_scope':scope,'result':'ConditionalGeometryDifference' if differences else 'ConditionalGeometryAgreement','differences':differences,'representation':representation,'origins':ORIGINS}


def write_json(path,value):path.write_text(json.dumps(value,indent=2)+'\n')

def source_identity(out):
    base=out/'sources/base';inventory=c.source_inventory(base)
    require(inventory==c.safe_tar(out/'base-source.tar'),'base archive inventory')
    entries={name:['100755' if row['mode']&0o111 else '100644',h.git_hash('blob',(base/name).read_bytes())] for name,row in inventory.items()}
    h.commit_proof(out/'base.commit',BASE,entries)
    manifest=load_json((out/'capture.json').read_bytes());require(manifest['schema']=='mds-floor-v1' and manifest['base']==BASE and manifest['origins']==ORIGINS,'source identity/origins')
    tooling=c.source_inventory(out/'tooling')
    require(set(tooling)==set(manifest['paths']) and all(p.startswith(PREFIX) or p==WORKFLOW for p in tooling),'exact tooling scope')
    for name,row in tooling.items():
        require((out/'tooling'/name).read_bytes()==(ROOT/name).read_bytes(),'tool source identity')
        entries[name]=['100755' if row['mode']&0o111 else '100644',h.git_hash('blob',(out/'tooling'/name).read_bytes())]
    h.commit_proof(out/'head.commit',manifest['head'],entries)
    p=projection(base);source,spans=extract(base)
    require(load_json((out/'projection.json').read_bytes())==p and (out/'native.cpp').read_bytes()==source.encode() and load_json((out/'extraction.json').read_bytes())==spans and (out/'input.txt').read_text()==wire(p),'source/extraction/input binding')
    return manifest,p

def verify_capture(out):
    m,p=source_identity(out);base=out/'sources/base';contract=h.contract(base);logs=[]
    require([v['name'] for v in m['variants']]==['control','observed'],'variant domain')
    for v in m['variants']:
        name=v['name'];source=out/'sources'/name;directory=out/name
        require(validate_source(base,source,name=='observed')==v['before']==v['after'],'source before/after inverse')
        require(v['patches']=={p:spans for p,(_,spans) in generated(base,name=='observed').items()},'source span manifest')
        build,stdout,_=checked(directory,'build')
        require(build['argv']==h.BUILD and build['cwd']==v['source']+'/rust' and build['env']['CARGO_TARGET_DIR']==v['target'],'build invocation')
        require(c.portable_cargo(stdout,v['source'],v['target'])==v['original_binary']['path'],'Cargo executable identity')
        binary=directory/'golden2';require(digest(binary.read_bytes())==v['binary']==v['original_binary']['sha256'],'binary hash')
        run,stdout,stderr=checked(directory,'test',101)
        require(run['argv']==[m['artifact_root']+'/'+name+'/golden2']+h.FLAGS and run['cwd']==v['source']+'/rust','test invocation')
        log=(stdout+b'\n'+stderr).decode();h.golden_log(log,101,contract);logs.append(log)
    require(not any(line.startswith('FG_') for line in logs[0].splitlines()),'control observations')
    rust=rust_parse(logs[1],p);metrics=c.images(out,contract,logs)
    return {'rust':rust,'metrics':metrics,'adapter':h.EXPECTED_ADAPTER,'suites':{'each':14,'passed':11,'failed':sorted(h.FAILURES)},'state':'RustCaptureValidNativeUnrun'}

def capture(out,build_root):
    require(sys.platform=='linux' and os.environ.get('GITHUB_ACTIONS')=='true','hosted Linux only')
    require(build_root and not out.exists() and not build_root.exists() and not out.is_relative_to(ROOT) and not build_root.is_relative_to(ROOT) and not out.is_relative_to(build_root) and not build_root.is_relative_to(out),'fresh external paths')
    out.mkdir(parents=True);build_root.mkdir(parents=True)
    env=os.environ.copy()
    row=record(out,'git-head',['git','rev-parse','HEAD'],ROOT,env);require(row['status']==0,'git head')
    head=(out/'git-head.stdout').read_text().strip()
    row=record(out,'git-status',['git','status','--porcelain'],ROOT,env);require(row['status']==0 and not (out/'git-status.stdout').read_bytes(),'clean source')
    row=record(out,'git-paths',['git','diff','--name-only',BASE,head],ROOT,env);require(row['status']==0,'path manifest')
    paths=(out/'git-paths.stdout').read_text().splitlines();require(paths and all(p.startswith(PREFIX) or p==WORKFLOW for p in paths),'allowlisted delta')
    row=record(out,'source-archive',['git','-c','tar.umask=0022','archive',BASE],ROOT,env);require(row['status']==0,'source archive')
    shutil.copyfile(out/'source-archive.stdout',out/'base-source.tar');base=out/'sources/base';c.safe_tar(out/'base-source.tar',base)
    for name,revision in [('base',BASE),('head',head)]:
        row=record(out,name+'-commit',['git','cat-file','commit',revision],ROOT,env);require(row['status']==0,'commit object');shutil.copyfile(out/(name+'-commit.stdout'),out/(name+'.commit'))
    for path in paths:
        dest=out/'tooling'/path;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/path,dest)
    p=projection(base);source,spans=extract(base)
    write_json(out/'projection.json',p);write_json(out/'extraction.json',spans);(out/'native.cpp').write_text(source);(out/'input.txt').write_text(wire(p))
    m={'schema':'mds-floor-v1','base':BASE,'head':head,'origins':ORIGINS,'paths':paths,'artifact_root':str(out),'variants':[]}
    icds=list(Path('/usr/share/vulkan/icd.d').glob('lvp_icd*.json'));require(len(icds)==1,'llvmpipe ICD')
    runtime=out/'runtime';runtime.mkdir(mode=0o700)
    env={k:os.environ[k] for k in ('PATH','HOME','CARGO_HOME','RUSTUP_HOME','TMPDIR','LD_LIBRARY_PATH') if k in os.environ}|{'WGPU_BACKEND':'vulkan','VK_ICD_FILENAMES':str(icds[0]),'XDG_RUNTIME_DIR':str(runtime),'CARGO_TERM_COLOR':'never','CARGO_INCREMENTAL':'0','CXX':'clang++'}
    for name in ('control','observed'):
        directory=out/name;directory.mkdir();source=out/'sources'/name;shutil.copytree(base,source)
        patches=generated(base,name=='observed')
        for path,(text,_) in patches.items():(source/path).write_text(text)
        before=validate_source(base,source,name=='observed');png=directory/'images';png.mkdir()
        e=env|{'CARGO_TARGET_DIR':str(build_root/name)}
        row=record(directory,'build',h.BUILD,source/'rust',e);require(row['status']==0,'Rust build failed')
        original=Path(h.cargo_binary((directory/'build.stdout').read_bytes(),source,build_root/name));binary=directory/'golden2';shutil.copy2(original,binary)
        row=record(directory,'test',[binary]+h.FLAGS,source/'rust',e|{'MDS_RENDER_PNG_DIR':str(png)})
        after=validate_source(base,source,name=='observed')
        m['variants'].append({'name':name,'source':str(source),'target':str(build_root/name),'before':before,'after':after,'patches':{p:s for p,(_,s) in patches.items()},'binary':digest(binary.read_bytes()),'original_binary':{'path':str(original),'sha256':digest(original.read_bytes())}})
        write_json(out/'capture.json',m)
        require(row['status']==101,'canonical suite terminal')
    result=verify_capture(out);write_json(out/'capture-result.json',result);seal(out);return result

def verify(out):
    result=verify_capture(out)
    native_dir=out/'native'
    if not native_dir.exists():return result
    manifest=load_json((native_dir/'manifest.json').read_bytes())
    source,spans=extract(out/'sources/base')
    require((native_dir/'source/native.cpp').read_bytes()==source.encode() and manifest['source_sha256']==digest(source.encode()),'native source identity')
    base_inv=c.source_inventory(out/'sources/base');expected=dict(base_inv)
    expected['native.cpp']={'sha256':digest(source.encode()),'mode':0o644}
    cmake=(out/'sources/base/CMakeLists.txt').read_text(encoding='utf-8')+native_cmake()
    require(manifest['cases']==['canonical','winding','scale'] and manifest['floor_relative']==old.FLOOR,'native case/asset binding')
    from pathlib import PureWindowsPath
    cwd=PureWindowsPath(manifest['cwd'])
    require(PureWindowsPath(manifest['floor_path'])==cwd/old.FLOOR and PureWindowsPath(manifest['binary_path'])==cwd.parent/'floor_geometry.exe' and PureWindowsPath(manifest['input_path'])==cwd.parent.parent/'input.txt','fixed native absolute paths')
    expected['CMakeLists.txt']=expected['CMakeLists.txt']|{'sha256':digest(cmake.encode())}
    if sys.platform=='win32':
        for name,row in expected.items():c.TRANSPORT_MODES[str((native_dir/'source'/name).resolve())]=row['mode']
    require(c.source_inventory(native_dir/'source')==expected,'native source inverse/full tree')
    binary=native_dir/'floor_geometry.exe';raw=binary.read_bytes()
    require(digest(raw)==manifest['binary_sha256']==manifest['original_binary_sha256']==digest((native_dir/'original-floor_geometry.exe').read_bytes()),'native executable identity')
    require(raw[:2]==b'MZ','native PE');offset=struct.unpack_from('<I',raw,0x3c)[0]
    require(raw[offset:offset+6]==b'PE\0\0d\x86','native AMD64')
    checked(native_dir,'configure');checked(native_dir,'build')
    cases={}
    for case in ('canonical','winding','scale'):
        for mode in ('control','observed'):
            label=case+'-'+mode;row,stdout,stderr=checked(native_dir,label)
            require(row['argv']==[manifest['binary_path'],manifest['floor_path'],manifest['input_path'],case,mode] and row['cwd']==manifest['cwd'],'native invocation/case binding')
            require(not stderr,'native stderr');parsed=native_parse(stdout.decode(),row['status'])
            require((parsed['observation'] is not None)==(mode=='observed'),'observation mode')
            if parsed['observation']:require(semantic_snapshot(parsed['observation'])==semantic_snapshot(parsed['final']),'observation/final noninterference')
            cases[label]=parsed
        require(validate_mesh(cases[case+'-control']['raw'])==validate_mesh(cases[case+'-observed']['raw']),'control/observed raw initialized geometry')
        require(semantic_snapshot(cases[case+'-control']['final'])==semantic_snapshot(cases[case+'-observed']['final']),'control/observed initialized final snapshot')
    canonical=cases['canonical-observed'];winding=cases['winding-observed'];scale=cases['scale-observed']
    original_indices=validate_mesh(canonical['final']['mesh'])['indices']
    expected_indices=original_indices.copy();expected_indices[0],expected_indices[1]=expected_indices[1],expected_indices[0]
    require(expected_indices!=original_indices and validate_mesh(winding['final']['mesh'])['indices']==expected_indices,'normal-exit winding exact intervention')
    scale_bits=ints(hexbytes(canonical['final']['scale']))[0]
    scale_value=struct.unpack('<f',struct.pack('<I',scale_bits))[0]
    expected_scale=struct.pack('<f',scale_value*2).hex()
    require(scale['final']['scale']==expected_scale,'named source-bound doubled-scale intervention')
    canonical_upload=[v for i,v in enumerate(canonical['final']['mesh']['projected_upload']) if i%8<6]
    scale_upload=[v for i,v in enumerate(scale['final']['mesh']['projected_upload']) if i%8<6]
    require(canonical['final']['world']!=scale['final']['world'] and canonical_upload!=scale_upload,'normal-exit scale initialized upload sensitivity')
    for mode in ('control','observed'):
        s=cases['canonical-'+mode]['final'];p=projection(out/'sources/base');f=p['fields']
        require(s['state']==['1','1','0','-1','0'] and ints(hexbytes(s['opacity']))==[1065353216],'canonical projected scalar state')
        require(ints(hexbytes(s['rotation']))==[f['rotation['+str(i)+']']['value'] for i in range(3)] and ints(hexbytes(s['scale']))==[f['scale']['value']] and ints(hexbytes(s['position']))==[f['position['+str(i)+']']['value'] for i in range(3)],'canonical projected input exact')
    return result|comparison(canonical,result['rust'])|{'state':'CompleteConditionalDiagnostic','sensitivity':{'winding':{'status':0,'schema':'MDS_FLOOR_V1','expected_changed_fields':['loaded.indices'],'before':original_indices,'after':expected_indices},'scale':{'status':0,'schema':'MDS_FLOOR_V1','expected_changed_fields':['world','initialized_projected_upload'],'before_world':canonical['final']['world'],'after_world':scale['final']['world'],'before_upload':canonical_upload,'after_upload':scale_upload}},'intervention_derivation':{'source_sha256':manifest['source_sha256'],'winding':'Swap loaded first triangle indices 0 and 1, retaining bounds','scale':'Double projected scale before complete original placement; distinct from canonical'}}

def native_cmake():
    return '\nadd_executable(floor_geometry native.cpp)\ntarget_link_libraries(floor_geometry PRIVATE mikudancestudio_core MMEffect dsound)\n'

def native(out,archive,build_root,toolchain):
    require(sys.platform=='win32' and os.environ.get('GITHUB_ACTIONS')=='true','hosted Windows only')
    require(archive and build_root and toolchain and toolchain.is_file() and not out.exists() and not build_root.exists() and not out.is_relative_to(ROOT) and not build_root.is_relative_to(ROOT) and not out.is_relative_to(build_root) and not build_root.is_relative_to(out),'fresh native output/build')
    c.transport(archive,out,True);verify_seal(out);verify_capture(out)
    require(load_json((out/'capture.json').read_bytes())['head']==os.environ.get('GITHUB_SHA'),'workflow/archive HEAD binding')
    directory=out/'native';directory.mkdir();source=directory/'source';shutil.copytree(out/'sources/base',source)
    cpp,_=extract(out/'sources/base');(source/'native.cpp').write_bytes(cpp.encode('utf-8'))
    (source/'CMakeLists.txt').write_bytes(((source/'CMakeLists.txt').read_text(encoding='utf-8')+native_cmake()).encode('utf-8'))
    env=os.environ.copy();build_root.mkdir(parents=True)
    configure=['cmake','-S',str(source),'-B',str(build_root),'-G','Visual Studio 17 2022','-A','x64','-DCMAKE_TOOLCHAIN_FILE='+str(toolchain),'-DBUILD_TESTING=OFF','-DMIKUDANCESTUDIO_DIAG=OFF']
    require(record(directory,'configure',configure,source,env)['status']==0,'native configure')
    require(record(directory,'build',['cmake','--build',str(build_root),'--config','Release','--target','floor_geometry','--parallel','4','--verbose'],source,env)['status']==0,'native build')
    original=build_root/'Release/floor_geometry.exe';binary=directory/'floor_geometry.exe';shutil.copy2(original,binary);shutil.copy2(original,directory/'original-floor_geometry.exe')
    floor=source/old.FLOOR;input_path=out/'input.txt'
    manifest={'source_sha256':digest(cpp.encode()),'binary_sha256':digest(binary.read_bytes()),'original_binary_sha256':digest(original.read_bytes()),'binary_path':str(binary),'floor_path':str(floor),'input_path':str(input_path),'cwd':str(source),'floor_relative':old.FLOOR,'cases':['canonical','winding','scale']}
    write_json(directory/'manifest.json',manifest)
    for case in manifest['cases']:
        for mode in ('control','observed'):
            row=record(directory,case+'-'+mode,[binary,floor,input_path,case,mode],source,env,120)
            require(row['status']==0,'native case failed; not a geometry difference')
    result=verify(out);write_json(out/'result.json',result);seal(out);return result

def evidence_inventory(out):
    result={}
    for p in sorted(out.rglob('*')):
        require(not p.is_symlink(),'evidence symlink')
        if p.is_file() and p != out/'seal.json':
            raw=p.read_bytes();mode=c.TRANSPORT_MODES.get(str(p.resolve()),0o755 if p.suffix=='.exe' or p.stat().st_mode&0o111 else 0o644)
            result[p.relative_to(out).as_posix()]={'sha256':digest(raw),'size':len(raw),'mode':mode}
    return result

def seal(out):
    write_json(out/'seal.json',{'schema':'mds-floor-seal-v1','files':evidence_inventory(out)})

def verify_seal(out):
    value=load_json((out/'seal.json').read_bytes())
    actual=evidence_inventory(out)
    if sys.platform=='win32':
        for name,row in actual.items():
            expected=value['files'].get(name,{})
            require(expected.get('mode') in (0o644,0o755),'retained portable mode')
            if str((out/name).resolve()) not in c.TRANSPORT_MODES:row['mode']=expected['mode']
    require(value['schema']=='mds-floor-seal-v1' and value['files']==actual,'complete evidence seal')


def readonly():
    def audit(event,args):
        if event=='open':
            mode=args[1];flags=args[2]
            require(not (isinstance(mode,str) and any(v in mode for v in 'wax+')) and not (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)),'read-only replay write')
        require(not event.startswith(('subprocess.','socket.')) and event not in ('os.system','os.posix_spawn','os.remove','os.rename','os.mkdir','os.rmdir','os.chmod','os.link','os.symlink','os.truncate'),'read-only replay effect')
    sys.addaudithook(audit)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',choices=['rust-capture','native'])
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--build-root',type=Path)
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--toolchain',type=Path)
    parser.add_argument('--bundle',type=Path)
    args=parser.parse_args();out=args.out.resolve();build=args.build_root.resolve() if args.build_root else None
    if args.run=='rust-capture':result=capture(out,build)
    elif args.run=='native':result=native(out,args.archive,build,args.toolchain)
    else:
        require(args.bundle is None,'default replay cannot write bundles')
        readonly()
        if args.archive:c.transport(args.archive,out)
        verify_seal(out)
        result=verify(out)
    if args.bundle:
        require(args.run is not None,'bundle requires explicit hosted capture')
        result=result|{'bundle':c.bundle(out,args.bundle)}
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,IndexError,OSError,struct.error) as e:
        print(json.dumps({'result':'InvalidEvidence','error':str(e)}),file=sys.stderr);sys.exit(1)
