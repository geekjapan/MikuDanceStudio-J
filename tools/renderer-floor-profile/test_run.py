#!/usr/bin/env python3
"""Compiler-free controls. Synthetic streams never count as hosted execution."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
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
    return {'stage':stage,'positions':[[0,0,0],[r.word(1.),0,0],[0,r.word(1.),0]],'indices':[0,1,2],'attributes':[0],'table':[], 'materials':[[0]*17]}


def packet(language,observed=True):
    rows=[{'stage':'begin','language':language}]
    def fp(point):rows.append({'stage':'fp','point':point,'mxcsr':8064})
    def hr(name):rows.append({'stage':'hr','operation':name,'value':0})
    def mesh(stage):
        for name in HR:hr(name)
        row=geometry(stage);row.pop('materials');row.update(bounds=[3,1,12,0,36,6,2],initialized=['position'],unknown=['uv','padding','other-declaration-channels']);rows.append(row)
    if language=='native':
        rows.append({'stage':'cpu','vendor':[0]*3,'identity':0,'brand':[0]*12,'features':[0]*3})
        fp('device-before');hr('CreateDevice');fp('device-after')
        rows.append({'stage':'dll','path':'C:\\diagnostic.dll','size':1,'sha256':'0'*64,'base':4096,'rvas':[1,2,3],'import_target':4097})
    for id,_,_ in r.CASES:
        rows.append({'stage':'case','id':id,'mxcsr':8064})
        if language=='native':
            fp('independent-before');hr('D3DXLoadMeshFromXW');fp('independent-after');mesh('independent-raw')
            rows.append({'stage':'independent-material-raw','words':[[0]*17]});fp('loader-before')
            if observed:fp('production-raw-before');mesh('production-raw');fp('production-raw-after')
            fp('loader-after');rows.append({'stage':'loader','success':True});mesh('before-observation')
            if observed:mesh('observation')
            mesh('final-adjusted');rows.append({'stage':'final-material-adjusted','words':[[0]*17]})
        else:
            if observed:
                rows.extend([{'stage':'parsed','kind':'Mesh','name':'Synthetic','path':[0],'values':[['int',3]]+[['float',v] for p in geometry('')['positions'] for v in p]}, {'stage':'parsed-end'}])
                row=geometry('premerge');row.pop('materials');row.pop('table');row.update(ordinal=0,matrix=list(map(r.word,r.IDENTITY)));rows.extend([row,{'stage':'premerge-end'},geometry('merged-raw')])
            row=geometry('final-adjusted');row.update(mxcsr=8064);rows.append(row)
    for m in range(3):
        for p in range(5):
            for op in (('TransformCoord','Transform') if language=='native' else ('TransformCoord',)):
                rows.append({'stage':'direct','operation':op,'matrix':m,'point':p,'words':[r.word(1.)]*3+([r.word(3. if m==2 else 1.)] if op=='Transform' else []),'before':8064,'after':8064})
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
        row['materials']=[]
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
    def test_zz_real_effects_rejected_before_effects(self):
        target=Path('/Users/geekjapan/.codex/orchestrate/mikudance-rust-20261027/renderer-floor-profile/effect-probe')
        self.assertFalse(target.exists());r.readonly()
        probes=[lambda:target.write_bytes(b'forbidden'),lambda:target.mkdir(),lambda:subprocess.run([sys.executable,'-c','raise SystemExit(99)'],check=True),lambda:socket.socket()]
        for probe in probes:
            with self.assertRaises(ValueError):probe()
        self.assertFalse(target.exists())


if __name__=='__main__':unittest.main(verbosity=2)
