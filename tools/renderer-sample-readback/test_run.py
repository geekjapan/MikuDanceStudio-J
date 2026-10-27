#!/usr/bin/env python3
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import tarfile
import tempfile
import unittest
import zlib

SPEC = importlib.util.spec_from_file_location('sample_run',Path(__file__).with_name('run.py'))
r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r)


def words(values):
    return struct.pack('<'+'I'*len(values),*values)


def png(path,pixels,width=2,height=1):
    def chunk(kind,data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
    raw = b''.join(b'\0'+bytes(v for p in pixels[y*width:(y+1)*width] for v in p) for y in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+
                     chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))


class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = r.contract(r.ROOT)

    def reject(self,fn,*args):
        with self.assertRaises((ValueError,KeyError,IndexError,TypeError,OSError,UnicodeError)):
            fn(*args)

    def test_source_contract(self):
        self.assertEqual(sum(self.c['calls'].values()),28)
        self.assertEqual(self.c['calls']['grid_lines'],11)
        self.assertEqual(self.c['calls']['selfshadow_0_map_4096'],2)
        self.assertEqual(self.c['calls']['shadow_map_display_draws_the_map_in_gray'],4)
        self.assertEqual(len(self.c['gates']),11)
        self.assertEqual(len(self.c['offsets']),8)

    def test_generated_sources_and_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root/'base'
            for name in r.FROZEN:
                dest = base/name
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(r.ROOT/name,dest)
            observer = Path(__file__).with_name('observer.rs').read_bytes()
            for observed in (False,True):
                dest = root/str(observed)
                spans = r.generate(base,dest,observed,observer)
                self.assertEqual(set(spans),{r.COMMON,r.RENDERER} if observed else {r.COMMON})
                r.validate_generated(base,dest,observed,observer)
                (dest/'unexpected').write_bytes(b'extra')
                self.reject(r.validate_generated,base,dest,observed,observer)
                (dest/'unexpected').unlink()
                (dest/r.GOLDEN).write_bytes(b'changed')
                self.reject(r.validate_generated,base,dest,observed,observer)
            (base/r.COMMON).write_bytes(b'drift')
            self.reject(r.generate,base,root/'drift',False,observer)
        self.reject(r.insertions,'missing',[('anchor','added')])
        self.reject(r.insertions,'anchor anchor',[('anchor','added')])
        before = 'prefix anchor suffix'
        after,spans = r.insertions(before,[('anchor','addition')])
        self.assertEqual(after[:spans[0]['start']]+after[spans[0]['start']+len('addition'):],before)

    def test_json_and_paths(self):
        for raw in ('{"a":1,"a":2}','{"x":NaN}','{"x":Infinity}','{"x":-Infinity}','{"x":1e999}','{"x":-1e999}','{"x":1'):
            with self.subTest(raw=raw):
                self.reject(r.load_json,raw)
        for name in ('../a','/a','a/../b','a//b','a\\b','a/./b',''):
            self.reject(r.safe_name,name)
        self.assertEqual(r.safe_name('a/b'),'a/b')

    def cargo(self):
        source,target = '/source','/target'
        crate = source+'/rust/crates/mds-render'
        exe = target+'/debug/deps/golden2-abcdef0123'
        row = {'reason':'compiler-artifact','manifest_path':crate+'/Cargo.toml',
               'target':{'name':'golden2','src_path':crate+'/tests/golden2.rs','kind':['test'],'crate_types':['bin'],'test':True},
               'profile':{'opt_level':'0','debuginfo':2,'debug_assertions':True,'overflow_checks':True,'test':True},
               'executable':exe,'filenames':[exe]}
        return row,{'reason':'build-finished','success':True},source,target

    def test_cargo_mixed_stream_and_controls(self):
        artifact,finish,source,target = self.cargo()
        def stream(a=artifact,f=finish):
            return b'native compiler output\n'+json.dumps(a).encode()+b'\nmore native output\n'+json.dumps(f).encode()+b'\n'
        self.assertEqual(r.cargo_binary(stream(),source,target),artifact['executable'])
        mutations = [('manifest_path','/other/Cargo.toml'),('executable','/wrong/golden2-abc'),('filenames',[])]
        for key,value in mutations:
            row = copy.deepcopy(artifact)
            row[key] = value
            self.reject(r.cargo_binary,stream(row),source,target)
        for key,value in [('name','other'),('src_path','/other/golden2.rs'),('kind',['bin']),('test',False)]:
            row = copy.deepcopy(artifact)
            row['target'][key] = value
            self.reject(r.cargo_binary,stream(row),source,target)
        for key,value in [('opt_level','1'),('debuginfo',True),('test',1)]:
            row = copy.deepcopy(artifact)
            row['profile'][key] = value
            self.reject(r.cargo_binary,stream(row),source,target)
        for raw in (stream()+json.dumps(artifact).encode()+b'\n',stream()+json.dumps(finish).encode()+b'\n',
                    stream(f={'reason':'build-finished','success':False}),stream()[:-1],
                    stream()+b'{truncated',stream()+b'{"x":1,"x":2}\n',stream()+b'{"reason":"note","v":1e999}\n',
                    json.dumps(artifact).encode()+b'\n'):
            self.reject(r.cargo_binary,raw,source,target)

    def log(self):
        text = '\n'.join(f'test {name} ... '+('FAILED' if name in r.FAILURES else 'ok') for name in self.c['calls'])
        text += '\n'+'\n'.join('SAMPLE_ADAPTER '+r.EXPECTED_ADAPTER+'|'+name for name in self.c['calls'])
        return text+'\ntest result: FAILED. 11 passed; 3 failed; 0 ignored; 0 measured; 0 filtered out; finished in 8.49s\n'

    def test_canonical_suite_adapter_controls(self):
        raw = self.log()
        self.assertEqual(len(r.golden_log(raw,101,self.c)),14)
        summary = raw.splitlines()[-1]
        for suffix in ('', ' finished in NaNs', ' finished in infs', ' finished in -1.00s',
                       ' finished in 1e999s', ' finished in 8.49s trailing', ' finished in 8.49s; 1 passed',
                       ' finished in '+ '9'*400 + '.00s'):
            self.reject(r.golden_log,raw.replace(' finished in 8.49s',suffix),101,self.c)
        self.reject(r.golden_log,raw+summary+'\n',101,self.c)
        for before,after in [('FAILED.','ok.'),('3 failed','2 failed'),('0 measured','1 measured'),
                             ('0 filtered out','1 filtered out'),('8.49s','8s'),('8.49s','8.4s')]:
            self.reject(r.golden_log,raw.replace(before,after),101,self.c)
        for changed,code in [(raw,0),(raw+'SKIP',101),(raw.replace('11 passed','10 passed'),101),
                             (raw.replace('0 ignored','1 ignored'),101),(raw.replace('SAMPLE_ADAPTER','OTHER',1),101),
                             (raw.replace(r.EXPECTED_ADAPTER,'different|Vulkan',1),101),
                             (raw.replace('|accessory_0','|accessory_30',1),101),
                             (raw.replace('test skin_0 ... FAILED','test skin_0 ... ok'),101),
                             (raw+'test accessory_0 ... ok\n',101),
                             (raw.replace('test accessory_0 ... ok\n',''),101)]:
            self.reject(r.golden_log,changed,code,self.c)

    def call_fixture(self,root):
        c = copy.deepcopy(self.c)
        c['dimensions'] = (2,1)
        directory = root/'accessory_0-0'
        directory.mkdir()
        name = b'accessory_0'
        raw = b'MDSSMP01'+words([len(name)])+name+words([0,2,1,256,8,8])+words(c['pixel'])+words([0]*256)+words(sum(c['offsets'],[]))
        (directory/'call.bin').write_bytes(raw)
        for i,offset in enumerate(c['offsets']):
            pixel = [struct.unpack('<f',struct.pack('<I',p))[0] for p in c['pixel']]
            sample = [struct.unpack('<f',struct.pack('<I',p))[0] for p in offset]
            shift = [r.fbits(p-s) for p,s in zip(pixel,sample)]
            (directory/f'sample-{i}.bin').write_bytes(words([i]+offset+shift))
            (directory/f'sample-{i}.rgba').write_bytes(bytes([i,0,0,255])*2)
        (directory/'finish.bin').write_bytes(words([0])+b'COMPLETE')
        return directory,c

    def test_capture_identity_stride_offsets_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory,c = self.call_fixture(Path(tmp))
            row = r.capture_call(directory,c)
            self.assertEqual(len(row['samples']),8)
            self.reject(r.captures,Path(tmp),c)
            header = (directory/'call.bin').read_bytes()
            fixed = 8+4+len('accessory_0')
            for offset,value in [(fixed,1),(fixed+4,3),(fixed+8,2),(fixed+12,8),(fixed+16,12),(fixed+20,7),
                                 (fixed+24,r.fbits(0)),(len(header)-4,r.fbits(0))]:
                raw = bytearray(header)
                raw[offset:offset+4] = words([value])
                (directory/'call.bin').write_bytes(raw)
                self.reject(r.capture_call,directory,c)
            (directory/'call.bin').write_bytes(header)
            sample_path = directory/'sample-0.bin'
            sample = sample_path.read_bytes()
            for offset,value in [(0,1),(4,r.fbits(.2)),(12,r.fbits(.4))]:
                raw = bytearray(sample)
                raw[offset:offset+4] = words([value])
                sample_path.write_bytes(raw)
                self.reject(r.capture_call,directory,c)
            sample_path.write_bytes(sample)
            (directory/'sample-7.rgba').write_bytes(b'bad')
            self.reject(r.capture_call,directory,c)
            (directory/'sample-7.rgba').write_bytes(bytes([7,0,0,255])*2)
            (directory/'finish.bin').write_bytes(words([0])+b'INCOMPLE')
            self.reject(r.capture_call,directory,c)
            (directory/'finish.bin').write_bytes(words([0])+b'COMPLETE')
            (directory/'extra').write_bytes(b'x')
            self.reject(r.capture_call,directory,c)

    def test_all_capture_payloads_retention_hash_lut_and_actual_sum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            captures = root/'captures'
            captures.mkdir()
            seed = root/'seed'
            seed.write_bytes(bytes([0,0,0,255])*(640*360))
            c = self.c
            for name,count in c['calls'].items():
                for ordinal in range(count):
                    directory = captures/(name+'-'+str(ordinal))
                    directory.mkdir()
                    encoded = name.encode()
                    header = b'MDSSMP01'+words([len(encoded)])+encoded+words([ordinal,640,360,2560,2560,8])
                    (directory/'call.bin').write_bytes(header+words(c['pixel'])+words([0]*256)+words(sum(c['offsets'],[])))
                    for index,offset in enumerate(c['offsets']):
                        shifts = [r.fbits(struct.unpack('<f',struct.pack('<I',p))[0]-struct.unpack('<f',struct.pack('<I',o))[0]) for p,o in zip(c['pixel'],offset)]
                        (directory/f'sample-{index}.bin').write_bytes(words([index]+offset+shifts))
                        os.link(seed,directory/f'sample-{index}.rgba')
                    points = r.POINTS.get(name,[])
                    (directory/'finish.bin').write_bytes(words([len(points)])+b''.join(words([x,y]+[0]*4) for x,y in points)+b'COMPLETE')
            stored = r.captures(captures,c)
            self.assertEqual(sum(len(row['samples']) for row in stored.values()),224)
            for identity,row in stored.items():
                if row['test'] not in c['gates']:
                    for sample in row['samples']:
                        (captures/identity/f"sample-{sample['index']}.rgba").unlink()
            self.assertEqual(sum(len(list(p.glob('*.rgba'))) for p in captures.iterdir()),88)
            self.assertEqual(r.captures(captures,c,stored),stored)
            raw_path = captures/'accessory_0-0/sample-0.rgba'
            original = raw_path.read_bytes()
            raw_path.unlink()
            raw_path.write_bytes(bytes([1])+original[1:])
            self.reject(r.captures,captures,c,stored)
            raw_path.write_bytes(original)
            header_path = captures/'accessory_0-0/call.bin'
            original = header_path.read_bytes()
            at = 8+4+len('accessory_0')+6*4+2*4
            changed = bytearray(original)
            changed[at:at+4] = words([r.fbits(.5)])
            header_path.write_bytes(changed)
            self.reject(r.captures,captures,c,stored)
            header_path.write_bytes(original)
            finish_path = captures/'skin_0-0/finish.bin'
            original = finish_path.read_bytes()
            changed = bytearray(original)
            changed[12:16] = words([r.fbits(1.0)])
            finish_path.write_bytes(changed)
            self.reject(r.captures,captures,c,stored)
            finish_path.write_bytes(original)
            changed = copy.deepcopy(stored)
            changed['grid_lines-0']['samples'][0]['shift'] = [0,0]
            self.reject(r.captures,captures,c,changed)

    def test_complete_capture_record_ledger_and_permutations(self):
        c = self.c
        records = {}
        for test,count in c['calls'].items():
            for ordinal in range(count):
                row = {'test':test,'ordinal':ordinal,'width':640,'height':360,'row':2560,'padded':2560,
                       'pixel':c['pixel'],'offsets':c['offsets'],'lut':[0]*256,'samples':[],
                       'points':[{'x':x,'y':y,'sum_bits':[0]*4} for x,y in r.POINTS.get(test,[])]}
                for index,offset in enumerate(c['offsets']):
                    shift = [r.fbits(struct.unpack('<f',struct.pack('<I',p))[0]-struct.unpack('<f',struct.pack('<I',o))[0]) for p,o in zip(c['pixel'],offset)]
                    row['samples'].append({'index':index,'offset':offset,'shift':shift,'size':640*360*4,'sha256':'0'*64})
                records[test+'-'+str(ordinal)] = row
        r.validate_capture_records(records,c)
        def bad(change):
            candidate = copy.deepcopy(records)
            change(candidate)
            self.reject(r.validate_capture_records,candidate,c)
        name = 'accessory_0-0'
        bad(lambda rows: rows.pop(name))
        bad(lambda rows: rows.update({'extra-0':rows[name]}))
        bad(lambda rows: rows[name].update({'test':'accessory_30'}))
        bad(lambda rows: rows[name].update({'ordinal':1}))
        bad(lambda rows: rows[name].update({'padded':2816}))
        bad(lambda rows: rows[name]['lut'].__setitem__(0,1))
        bad(lambda rows: rows[name]['samples'].reverse())
        bad(lambda rows: rows[name]['samples'].__setitem__(0,rows[name]['samples'][1]))
        bad(lambda rows: rows[name]['samples'].pop())
        bad(lambda rows: rows[name]['samples'][0].update({'shift':[0,0]}))
        bad(lambda rows: rows[name]['samples'][0].update({'sha256':'bad'}))
        bad(lambda rows: rows[name]['samples'][0].update({'size':0}))
        bad(lambda rows: rows['skin_0-0']['points'][0].update({'x':0}))
        bad(lambda rows: rows['skin_0-0']['points'][0].update({'sum_bits':[0x7f800000]*4}))
        bad(lambda rows: rows['skin_0-0']['points'].pop())
        bad(lambda rows: rows.update({'accessory_0-0':rows['accessory_30-0'],'accessory_30-0':rows['accessory_0-0']}))

    def test_file_binary_hash_and_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root/'binary'
            path.write_bytes(b'original')
            identity = r.file_id(path)
            r.checked_file(identity)
            path.write_bytes(b'changed!')
            self.reject(r.checked_file,identity)
            path.write_bytes(b'original')
            record = {'argv':['binary'],'cwd':'/cwd','env':{},'status':101,'start_ns':1,'end_ns':2,
                      'stdout':identity,'stderr':identity}
            r.validate_command(record,['binary'],'/cwd',{},101)
            for key,value in [('status',0),('argv',['other']),('cwd','/other'),('env',{'OTHER':'1'}),('end_ns',0)]:
                changed = copy.deepcopy(record)
                changed[key] = value
                self.reject(r.validate_command,changed,['binary'],'/cwd',{},101)
            r.RELOCATION = (root,root)
            self.reject(r.relocate,'/outside')
            self.reject(r.relocate,str(root/'..'/'outside'))
            r.RELOCATION = None

    def test_png_metrics_masks_and_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a,b,gold,cap,replay = [root/name for name in ('a','b','gold','cap','replay')]
            for path in (a,b,gold,cap,replay): path.mkdir()
            pixels = [(0,0,0,255),(255,255,255,255)]
            for directory in (a,b,gold): png(directory/'accessory-0.png',pixels)
            for directory in (a,b): png(directory/'accessory-0-diff.png',[(255,255,255,255)]*2)
            (replay/'accessory-0.rgba').write_bytes(bytes(v for p in pixels for v in p))
            call = cap/'accessory_0-0'
            call.mkdir()
            for i in range(8): (call/f'sample-{i}.rgba').write_bytes(bytes(v for p in pixels for v in p))
            c = {'dimensions':(2,1),'gates':{'accessory_0':'accessory-0'}}
            rows = {'accessory_0-0':{'points':[]}}
            logs = ['accessory-0: 2 px (0 masked), within 4 1.00000, max 0, mean 0.0000']*2
            result = r.image_analysis(a,b,gold,c,logs,cap,rows,replay)
            self.assertTrue(result[0]['metrics']['passes'])
            self.reject(r.image_analysis,a,b,gold,c,[logs[0].replace('max 0','max 1')]*2,cap,rows,replay)
            (replay/'accessory-0.rgba').write_bytes(b'x'*8)
            self.reject(r.image_analysis,a,b,gold,c,logs,cap,rows,replay)
            (replay/'accessory-0.rgba').write_bytes(bytes(v for p in pixels for v in p))
            png(b/'accessory-0.png',[(1,0,0,255),pixels[1]])
            self.reject(r.image_analysis,a,b,gold,c,logs,cap,rows,replay)
            png(b/'accessory-0.png',pixels)
            png(b/'accessory-0-diff.png',[(255,0,255,255),(255,255,255,255)])
            self.reject(r.image_analysis,a,b,gold,c,logs,cap,rows,replay)
            for directory in (a,b): png(directory/'accessory-0-diff.png',[(254,254,254,255)]*2)
            self.reject(r.image_analysis,a,b,gold,c,logs,cap,rows,replay)

    def test_fixed_maxima_discrepancies_keep_the_selected_points(self):
        original_points = r.POINTS
        try:
            r.POINTS = {name:[(0,0),(1,0),(0,1)] for name in ('selfshadow_30','skin_0','skin_30')}
            r.POINTS['selfshadow_30'].append((1,1))
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for test,error in [('selfshadow_30',56),('skin_0',78),('skin_30',112)]:
                    name = test.replace('_','-')
                    a,b,gold,cap,replay = [root/test/key for key in ('a','b','gold','cap','replay')]
                    for path in (a,b,gold,cap,replay): path.mkdir(parents=True)
                    rendered = [(0,0,0,255)]*4
                    for path in (a,b): png(path/(name+'.png'),rendered,2,2)
                    (replay/(name+'.rgba')).write_bytes(bytes(v for p in rendered for v in p))
                    call = cap/(test+'-0')
                    call.mkdir()
                    for index in range(8): (call/f'sample-{index}.rgba').write_bytes(bytes(v for p in rendered for v in p))
                    for change in ('none','masked','point','unmasked'):
                        with self.subTest(test=test,change=change):
                            errors = [error,error,error,255]
                            if change == 'point': errors[0 if test == 'selfshadow_30' else 2] -= 1
                            if change == 'unmasked': errors[1] += 1
                            masked = change != 'none'
                            if not masked: errors[3] = 0
                            png(gold/(name+'.png'),[(value,0,0,255) for value in errors],2,2)
                            diffs = [(255-min(255,4*value),)*3+(255,) for value in errors]
                            if masked: diffs[3] = (255,0,255,255)
                            for path in (a,b): png(path/(name+'-diff.png'),diffs,2,2)
                            scored = errors[:3] if masked else errors
                            log = f'{name}: {len(scored)} px ({int(masked)} masked), within 4 {sum(v <= 4 for v in scored)/len(scored):.5f}, max {max(scored)}, mean {sum(scored)/len(scored):.4f}'
                            rows = r.image_analysis(a,b,gold,{'dimensions':(2,2),'gates':{test:name}},[log]*2,cap,{test+'-0':{'points':[]}},replay)
                            self.assertEqual(rows[0]['maxima']['discrepancy'],change in ('point','unmasked'))
                            maxima = rows[0]['maxima']
                            self.assertEqual(maxima['actual_max'],max(scored))
                            self.assertEqual(maxima.get('documented_points',maxima.get('documented_point')),[(0,0),(1,0),(0,1)] if test == 'selfshadow_30' else [0,1])
        finally:
            r.POINTS = original_points

    def test_evidence_tar_preserves_git_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'evidence'
            source.mkdir()
            executable = source/'executable'
            executable.write_bytes(b'retained bytes')
            executable.chmod(0o755)
            (source/'.hidden').write_bytes(b'hidden receipt')
            before = r.git_inventory(source)
            archive = root/'evidence.tar'
            with tarfile.open(archive,'w') as tar:
                tar.add(source,arcname=source.name)
            executable.chmod(0o644)
            self.assertNotEqual(r.tree_hash(r.git_inventory(source)),r.tree_hash(before))
            restored = root/'restored'
            restored.mkdir()
            r.archive_extract(archive,restored)
            self.assertEqual(r.git_inventory(restored/source.name),before)

    def test_git_object_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'a').write_bytes(b'content')
            entries = r.git_inventory(root)
            commit = ('tree '+r.tree_hash(entries)+'\nparent '+r.BASE+'\n\nmessage\n').encode()
            revision = r.git_hash('commit',commit)
            path = root/'commit'
            path.write_bytes(commit)
            r.commit_proof(path,revision,entries)
            changed = copy.deepcopy(entries)
            changed['a'][1] = '0'*40
            self.reject(r.commit_proof,path,revision,changed)
            self.reject(r.commit_proof,path,'0'*40,entries)


if __name__ == '__main__':
    unittest.main()
