#!/usr/bin/env python3
import copy
import importlib.util
from pathlib import Path
import struct
import unittest

spec=importlib.util.spec_from_file_location('floor',Path(__file__).with_name('run.py'))
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

def packet():
    pack=lambda values:struct.pack('<'+'I'*len(values),*values).hex()
    vertices=[[0,0,0],[1065353216,0,0],[0,0,1065353216]]
    mesh={'vertices':3,'faces':1,'stride':12,'options':544,'fvf':2,'index_width':2,'decl':[[0,2,0,0]],'vb':pack(sum(vertices,[])),'ib':struct.pack('<3H',0,1,2).hex(),'attributes':pack([0]),'materials':1,'material_bits':[[0]*17],'table':[[0,0,1,0,3]],'vb_size':36,'ib_size':[6,102]}
    return mesh

def native_text(observed=False):
    mesh=packet();mesh.update(stride=32,fvf=274,vb_size=96,decl=[[0,2,0,0],[12,2,3,0],[24,1,5,0]])
    mesh['vb']=struct.pack('<24I',*([0]*24)).hex()
    hrs=['GetDeclaration','GetVertexBuffer','VertexBufferGetDesc','GetIndexBuffer','IndexBufferGetDesc','LockVertexBuffer','UnlockVertexBuffer','LockIndexBuffer','LockAttributeBuffer','UnlockAttributeBuffer','UnlockIndexBuffer','GetAttributeTableSize','GetAttributeTable']
    def section(name):
        lines=[f"{name} fvf 274 options 544 vertices 3 faces 1 stride 32"]
        lines += ['hr '+v+' 00000000' for v in hrs]
        lines += ['vb_size 96','ib_size 6 102','vb '+mesh['vb'],'ib '+mesh['ib'],'attributes '+mesh['attributes']]
        for off,typ,usage,ui in mesh['decl']:
            lines += [f'decl {off} {typ} {usage} {ui}','decl_bytes '+struct.pack('<HHBBBB',0,off,typ,0,usage,ui).hex()]
        lines += ['v '+str(i)+' 0 0 0 0 0 0 0 0' for i in range(3)]
        lines += ['f 0 0 1 2 0','table 1','t 0 0 1 0 3','materials 1']
        if name=='raw':lines += ['material '+'00'*68]
        else:
            lines += ['material_bits '+'00'*68,'texture_types 00','texture_paths '+'00'*2048,'name '+'00'*100,'directory '+'00'*512,'source_path '+'00'*512,'record_metadata 0 -1 0','world '+struct.pack('<16f',1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1).hex(),'position '+'00'*12,'rotation '+'00'*12,'scale 0000803f','opacity 0000803f','state 1 1 0 -1 0']
            lines += ['projected_upload '+'00'*32 for _ in range(3)]
            for i in range(5):lines += ['hr GetRenderState 00000000',f'device {i} 0']
        return lines
    lines=['MDS_FLOOR_V1','hr CreateDevice 00000000','hr D3DXLoadMeshFromXW 00000000']+section('raw')+['loader 1']
    if observed:lines += ['snapshot observation']+section('record')
    lines += ['snapshot final']+section('record')+['end 0']
    return '\n'.join(lines)+'\n'

def rust_text():
    p=r.projection(r.ROOT);w=r.wire(p).split()
    identity=struct.unpack('<16I',struct.pack('<16f',1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1))
    lines=['FG_STEP']*30+['FG_BIND 0 0 30 .\\shadow_floor.x 16','FG_STATE 0 '+' '.join(w[:5])+' 1065353216 '+' '.join(w[5:])+' 16','FG_LOCAL 0 3 3 1']
    lines += ['FG_V 0 '+str(i)+' '+' '.join(['0']*8) for i in range(3)]
    lines += ['FG_I 0 0 1 2','FG_A 0 0','FG_T 0 0 0 1 0 3','FG_M 0 0 '+' '.join(['0']*17),'FG_WORLD 0 '+' '.join(map(str,identity)),'FG_UPLOAD 0 '+'00'*96,'FG_PREP '+struct.pack('<3I',0,1,2).hex(),'FG_RANGE 0 0 3']
    return '\n'.join(lines)+'\n'

class Controls(unittest.TestCase):
    def test_extraction_inverse_and_all_original_inputs(self):
        r.old.fixed(r.ROOT)
        source,m=r.extract(r.ROOT)
        self.assertIn('const int modelSlot',source)
        self.assertNotIn('RunMeshDump(',source)
        self.assertEqual(m['inverse_sha256'],m['spans']['src/tools/mesh_dump.cpp']['sha256'])
        self.assertIn('GetAttributeTableSize',source)
    def test_projection_source_and_raw_fields(self):
        p=r.projection(r.ROOT)
        self.assertEqual(p['slot'],0)
        self.assertEqual(len(r.wire(p).split()),12)
        self.assertEqual(p['fields']['scale']['raw_hex'],'cdcccc3e')
    def test_rejects_changed_original_input(self):
        blobs=r.old.fixed(r.ROOT);blobs[r.old.FLOOR]+=b'changed'
        with self.assertRaises(ValueError):r.old.validate_blobs(blobs)
    def test_generated_inverse(self):
        for observed in (False,True):
            patches=r.generated(r.ROOT,observed)
            self.assertEqual(len(patches),3 if observed else 1)
            for name,(text,spans) in patches.items():
                restored=text.encode()
                for span in reversed(spans):
                    at=span['start'];raw=span['bytes'].encode()
                    self.assertEqual(restored[at:at+len(raw)],raw)
                    restored=restored[:at]+restored[at+len(raw):]
                self.assertEqual(restored,(r.ROOT/name).read_bytes())
    def test_valid_different_representation_and_counts(self):
        m=packet();a=r.validate_mesh(m)
        self.assertEqual(a['indices'],[0,1,2])
        m['vertices']=4;m['vb']+='00'*12;m['vb_size']+=12
        self.assertEqual(len(r.validate_mesh(m)['vertices']),4)
    def test_malformed_meshes(self):
        for key,value in [('vb','00'),('ib','00'),('attributes',''),('materials',0),('vb_size',12),('ib_size',[6,101]),('decl',[[12,2,0,0]]),('table',[[1,0,1,0,3]])]:
            with self.subTest(key=key):
                m=packet();m[key]=value
                with self.assertRaises((ValueError,KeyError)):r.validate_mesh(m)
        m=packet();m['ib']=struct.pack('<3H',0,1,3).hex()
        with self.assertRaises(ValueError):r.validate_mesh(m)
    def test_invalid_native_is_not_difference(self):
        for text,status in [('MDS_FLOOR_V1\nend 0\n',0),('MDS_FLOOR_V1\nhr test 80004005\nend 0\n',0),('MDS_FLOOR_V1\nend 0\n',77),('SKIP',0),('',0)]:
            with self.assertRaises((ValueError,IndexError)):r.native_parse(text,status)
    def test_missing_duplicate_unknown_rust(self):
        p=r.projection(r.ROOT)
        for text in ('','FG_STEP\n'*30,'FG_UNKNOWN 0\n','FG_STEP\n'*31):
            with self.assertRaises(ValueError):r.rust_parse(text,p)
    def test_complete_native_packet_and_rejections(self):
        text=native_text(True);result=r.native_parse(text,0)
        self.assertEqual(r.semantic_snapshot(result['observation']),r.semantic_snapshot(result['final']))
        for malformed in [text.replace('hr GetDeclaration 00000000\n','',1),text.replace('materials 1','materials 0',1),text.replace('loader 1','loader 0'),text.replace('end 0','end 77'),text.replace('vb_size 96','vb_size 95',1),text.replace('snapshot final','snapshot observation'),text.replace('hr GetDeclaration 00000000','hr GetDeclaration 80004005',1),text.replace('ib 000001000200','ib 000001000300',1)]:
            with self.subTest(packet=malformed[:100]):
                with self.assertRaises((ValueError,KeyError)):r.native_parse(malformed,0)
    def test_comparison_retains_valid_differences(self):
        native=r.native_parse(native_text(),0)
        rust={'vertices':[[0]*8 for _ in range(3)],'indices':[0,1,2],'attributes':[0],'materials':[[0]*17],'world':r.ints(bytes.fromhex(native['final']['world'])),'upload':[0]*24,'prepared':[0,1,2],'ranges':[[0,0,3]],'table':[[0,0,1,0,3]]}
        self.assertEqual(r.comparison(native,rust)['result'],'ConditionalGeometryAgreement')
        rust['vertices'].append([0]*8);rust['upload'].extend([0]*8)
        result=r.comparison(native,rust)
        self.assertEqual(result['result'],'ConditionalGeometryDifference')
        self.assertIn('loaded.vertices',result['differences'])

    def test_unknown_clone_channels_are_explicit_and_raw_retained(self):
        native=r.native_parse(native_text(),0)
        # Source-declared raw UVs are absent; the loaded clone still declares their space.
        raw=native['raw'];raw['decl']=[v for v in raw['decl'] if v[2]!=5]
        native['final']['mesh']['initialized_usage']=[0,3]
        loaded=native['final']['mesh'];data=bytearray.fromhex(loaded['vb']);data[24:28]=struct.pack('<I',0x7fc00000);loaded['vb']=data.hex()
        decoded=r.validate_mesh(loaded)
        self.assertEqual(decoded['representation']['unproved_initialization_usage'],[5])
        self.assertNotIn('5',decoded['vertices'][0])
        self.assertEqual(bytes.fromhex(loaded['vb'])[24:28],struct.pack('<I',0x7fc00000))

    def test_actual_rust_wire_source_binding_and_rejections(self):
        p=r.projection(r.ROOT);text=rust_text();result=r.rust_parse(text,p)
        self.assertEqual(result['prepared'],[0,1,2])
        for malformed in [text.replace('FG_BIND 0 0','FG_BIND 0 2'),text.replace('FG_BIND 0 0 30','FG_BIND 0 0 29'),text.replace('FG_I 0 0 1 2','FG_I 0 0 1 3'),text.replace('FG_A 0 0','FG_A 0 1'),text.replace('FG_RANGE 0 0 3','FG_RANGE 0 1 3'),text.replace('FG_LOCAL 0 3 3 1','FG_LOCAL 0 4 3 1'),text+'FG_I 0 0 1 2\n']:
            with self.assertRaises(ValueError):r.rust_parse(malformed,p)
        wrong=copy.deepcopy(p);wrong['fields']['scale']['value']+=1
        with self.assertRaises(ValueError):r.rust_parse(text,wrong)

    def test_strict_json_and_numbers(self):
        for raw in ('{"x":1,"x":2}','{"x":NaN}'):
            with self.assertRaises(ValueError):r.load_json(raw)
        for text in ('-1','4294967296','01'):
            with self.assertRaises(ValueError):r.words(text)

if __name__=='__main__':unittest.main()
