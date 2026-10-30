#!/usr/bin/env python3
"""Fixed-source hosted sample readback diagnostic; offline verification never runs binaries."""
import argparse
import ast
import difflib
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import time
import zlib

ROOT = Path(__file__).resolve().parents[2]
BASE = "3cf0711d38f94e6be5c5d06129257d1c963f973a"
PREFIX = "tools/renderer-sample-readback/"
ALLOWLIST = {PREFIX + p for p in ("run.py", "observer.rs", "replay.rs", "test_run.py")} | {".github/workflows/renderer-sample-readback.yml"}
RENDERER = "rust/crates/mds-render/src/renderer.rs"
COMMON = "rust/crates/mds-render/tests/common/mod.rs"
LIB = "rust/crates/mds-render/src/lib.rs"
GOLDEN = "rust/crates/mds-render/tests/golden2.rs"
MODULE = "rust/crates/mds-render/src/renderer/sample_readback_observer.rs"
FROZEN = {
    RENDERER: "5c31f91eff8ebd2e96f1d32107a0975793fe75246cc40be3a9997f69f095f3f5",
    COMMON: "de07dd797c5615bc6422fe43c5c6b209d9fb70079d4499b44daad580c40312f1",
    LIB: "a114ac3d90985d9ba484c92bb7bd9a0fae4acb90a0c1ede034f72343627c0c14",
    GOLDEN: "b6b462bcd156f498a9a50829670e25d5447fb68ec9f56c990f9a49dc0d9e2612",
}
POINTS = {"selfshadow_30": [(193,192),(455,199),(456,199),(288,296)],
          "skin_0": [(334,229),(332,232),(327,237)],
          "skin_30": [(361,149),(342,187),(360,148)]}
FAILURES = {"selfshadow_30", "skin_0", "skin_30"}
EXPECTED_ADAPTER = "llvmpipe (LLVM 20.1.2, 256 bits)|Vulkan"
BUILD = ["cargo", "+1.95.0", "test", "-p", "mds-render", "--test", "golden2", "--no-run", "--locked", "--message-format=json", "-vv"]
FLAGS = ["--include-ignored", "--nocapture", "--test-threads=1"]
RELOCATION = None

def require(ok, message):
    if not ok:
        raise ValueError(message)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def load_json(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'duplicate JSON key: ' + k)
            result[k] = v
        return result
    def finite_number(value):
        number = float(value)
        require(math.isfinite(number), 'nonfinite JSON: ' + value)
        return number
    return json.loads(raw, object_pairs_hook=pairs, parse_float=finite_number,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError('nonfinite JSON: ' + v)))

def read_png(path, dimensions=(640, 360)):
    data = Path(path).read_bytes()
    require(data[:8] == b'\x89PNG\r\n\x1a\n', 'PNG signature')
    pos, chunks, idat, ended = 8, [], bytearray(), False
    while pos < len(data):
        require(pos + 12 <= len(data), 'truncated PNG chunk')
        n, kind = struct.unpack('>I4s', data[pos:pos+8])
        require(n <= len(data) - pos - 12, 'truncated PNG body')
        body = data[pos+8:pos+8+n]
        crc = struct.unpack('>I', data[pos+8+n:pos+12+n])[0]
        require(zlib.crc32(kind + body) == crc, 'PNG CRC')
        require(not ended, 'PNG trailing data')
        if kind == b'IHDR':
            require(not chunks and n == 13, 'PNG IHDR order/length')
            header = struct.unpack('>IIBBBBB', body)
            require(header == (*dimensions, 8, 6, 0, 0, 0), 'PNG format/dimensions')
        elif kind == b'IDAT':
            require(chunks and chunks[0] == b'IHDR', 'PNG IDAT before IHDR')
            require(not idat or chunks[-1] == b'IDAT', 'PNG split IDAT')
            idat.extend(body)
        elif kind == b'IEND':
            require(n == 0 and idat, 'PNG IEND')
            ended = True
        else:
            require(kind[0] & 32, 'unsupported critical PNG chunk')
        chunks.append(kind)
        pos += n + 12
    require(ended, 'missing PNG IEND')
    width, height = dimensions
    stride = width * 4
    decoder = zlib.decompressobj()
    raw = decoder.decompress(idat, height * (stride + 1) + 1)
    require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail, 'PNG zlib stream')
    require(len(raw) == height * (stride + 1), 'PNG decoded length')
    result, previous = bytearray(), bytearray(stride)
    for y in range(height):
        kind = raw[y*(stride+1)]
        require(kind <= 4, 'PNG filter')
        line = bytearray(raw[y*(stride+1)+1:(y+1)*(stride+1)])
        for i in range(stride):
            a = line[i-4] if i >= 4 else 0
            b, c = previous[i], previous[i-4] if i >= 4 else 0
            p = a + b - c
            pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
            prediction = (0, a, b, (a+b)//2, a if pa <= pb and pa <= pc else b if pb <= pc else c)[kind]
            line[i] = (line[i] + prediction) & 255
        result.extend(line)
        previous = line
    return [tuple(result[i:i+4]) for i in range(0, len(result), 4)]

def safe_name(name):
    p = PurePosixPath(name)
    require(isinstance(name, str) and name and '\\' not in name and not p.is_absolute() and
            all(x not in ('', '.', '..') for x in name.split('/')), 'unsafe relative path')
    return name


def snapshot(root):
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'source symlink prohibited')
        if path.is_file():
            result[safe_name(path.relative_to(root).as_posix())] = digest(path.read_bytes())
    return result


def frozen(root):
    for name, sha in FROZEN.items():
        require(digest((root/name).read_bytes()) == sha, 'fixed input drift: ' + name)


def insertions(original, changes):
    spans = []
    modified = original
    for anchor, inserted in changes:
        require(original.count(anchor) == 1 and modified.count(anchor) == 1, 'missing/duplicate source anchor')
        start = modified.index(anchor) + len(anchor)
        modified = modified[:start] + inserted + modified[start:]
        spans.append({'start': len(modified[:start].encode()), 'bytes': inserted, 'anchor': anchor})
    restored = modified.encode()
    for span in reversed(spans):
        start, added = span['start'], span['bytes'].encode()
        require(restored[start:start+len(added)] == added, 'insertion span mismatch')
        restored = restored[:start] + restored[start+len(added):]
    require(restored == original.encode(), 'inverse source reconstruction')
    return modified, spans


COMMON_CHANGES = [(
    '        eprintln!("SKIP: no wgpu adapter on this host (not a pass)");\n    }\n',
    '    if let Some(ref actual) = gpu {\n'
    '        eprintln!("SAMPLE_ADAPTER {}|{}", actual.adapter,\n'
    '            std::thread::current().name().expect("libtest thread"));\n    }\n')]
RENDERER_CHANGES = [(
    'use std::sync::Arc;\n', '\nmod sample_readback_observer;\n'), (
    '        let to_linear = srgb_to_linear_table();\n        let mut sum = vec![0f32; (width * height * 4) as usize];\n',
    '        let mut capture = sample_readback_observer::Capture::begin(frame, padded_row, row_bytes, &to_linear)?;\n'), (
    '                    .map_err(|e| format!("read readback buffer: {e}"))?;\n',
    '                capture.sample(*sample, shift, &mapped)?;\n'), (
    '        finish(error_scope)?;\n', '        capture.finish(&sum)?;\n')]


def generate(base, dest, observed, observer):
    frozen(base)
    require(not dest.exists(), 'generated copy already exists')
    shutil.copytree(base, dest)
    spans = {}
    for name, changes in [(COMMON, COMMON_CHANGES)] + ([(RENDERER, RENDERER_CHANGES)] if observed else []):
        before = (base/name).read_text()
        after, spans[name] = insertions(before, changes)
        (dest/name).write_text(after)
    if observed:
        require(not (dest/MODULE).exists(), 'observer module already exists')
        (dest/MODULE).parent.mkdir(parents=True, exist_ok=True)
        (dest/MODULE).write_bytes(observer)
    validate_generated(base, dest, observed, observer)
    return spans


def validate_generated(base, dest, observed, observer):
    expected = snapshot(base)
    for name, changes in [(COMMON, COMMON_CHANGES)] + ([(RENDERER, RENDERER_CHANGES)] if observed else []):
        text, _ = insertions((base/name).read_text(), changes)
        expected[name] = digest(text.encode())
    if observed:
        expected[MODULE] = digest(observer)
    require(snapshot(dest) == expected, 'unexpected generated source path/bytes')
    for path in expected:
        executable = (dest/path).stat().st_mode & 0o111
        original = (base/path).stat().st_mode & 0o111 if path != MODULE else 0
        require(executable == original,'generated executable mode drift')


def fbits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def number(text):
    node = ast.parse(text, mode='eval').body
    def evaluate(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            return n.value
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -evaluate(n.operand)
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
            return evaluate(n.left) / evaluate(n.right)
        raise ValueError('unfamiliar sample constant')
    return evaluate(node)


def contract(root):
    frozen(root)
    text = (root/GOLDEN).read_text()
    dims = tuple(int(re.search(r'const '+c+r': usize = (\d+);', text)[1]) for c in ('W','H'))
    images_text = re.search(r'const IMAGES: .*? = \[(.*?)\];', text, re.S)[1]
    images = [(s,int(f)) for s,f in re.findall(r'\("(\w+)", (\d+)\)', images_text)]
    bodies = re.findall(r'#\[test\]\n(?:#\[ignore = "[^"\n]*"\]\n)?fn (\w+)\(\) \{\n(.*?)\n\}', text, re.S)
    calls, gates = {}, {}
    for name, body in bodies:
        gate = re.fullmatch(r'    gate\("(\w+)", (\d+)\);', body)
        if gate:
            scene, frame = gate.groups()
            require(name == scene+'_'+frame, 'gate test identity')
            gates[name] = scene+'-'+frame
            calls[name] = 1
        else:
            direct = len(re.findall(r'\b(?:render_at|render_with_display)\(', body))
            if 'for (scene, frame) in IMAGES {' in body:
                require(direct == 1, 'unfamiliar image loop body')
                direct *= len(images)
            calls[name] = direct
    require(len(calls) == 14 and len(gates) == len(images) == 11 and sum(calls.values()) == 28 and
            set(gates.values()) == {s+'-'+str(f) for s,f in images}, 'source call coverage')
    lib = (root/LIB).read_text()
    sample_text = re.search(r'pub const SAMPLES_8X: .*? = \[(.*?)\n\];', lib, re.S)[1]
    offsets = [[fbits(number(v.strip())) for v in pair.split(',')] for pair in re.findall(r'\[([^\[\]]+)\]', sample_text)]
    pixel_text = re.search(r'pub const PIXEL_OFFSET_D3D9: .*? = \[(.*?)\];', lib)[1]
    pixel = [fbits(number(v.strip())) for v in pixel_text.split(',')]
    require(len(offsets) == 8 and all(len(p) == 2 for p in offsets), 'source sample coverage')
    return {'dimensions': dims, 'calls': calls, 'gates': gates, 'offsets': offsets, 'pixel': pixel}


class Reader:
    def __init__(self, raw):
        self.raw, self.at = raw, 0
    def take(self, n):
        require(n >= 0 and self.at+n <= len(self.raw), 'truncated capture protocol')
        value = self.raw[self.at:self.at+n]
        self.at += n
        return value
    def words(self, n):
        return list(struct.unpack('<'+'I'*n, self.take(4*n)))
    def end(self):
        require(self.at == len(self.raw), 'capture trailing data')


def capture_call(directory, c, retained=True):
    r = Reader((directory/'call.bin').read_bytes())
    require(r.take(8) == b'MDSSMP01', 'capture schema')
    name = r.take(r.words(1)[0]).decode('ascii')
    ordinal,width,height,padded,row,count = r.words(6)
    require(name in c['calls'] and 0 <= ordinal < c['calls'][name] and
            directory.name == name+'-'+str(ordinal), 'call identity/ordinal')
    require((width,height) == tuple(c['dimensions']) and row == width*4 and
            padded == ((row+255)//256)*256 and count == len(c['offsets']), 'capture dimensions/stride/count')
    pixel = r.words(2)
    lut = r.words(256)
    offsets = [r.words(2) for _ in range(count)]
    r.end()
    require(pixel == c['pixel'] and offsets == c['offsets'], 'pixel/sample offsets/order')
    require(all(math.isfinite(struct.unpack('<f',struct.pack('<I',b))[0]) for b in lut), 'nonfinite LUT')
    samples = []
    for i, offset in enumerate(offsets):
        meta = Reader((directory/f'sample-{i}.bin').read_bytes())
        index, *values = meta.words(5)
        meta.end()
        shifts = [fbits(struct.unpack('<f',struct.pack('<I',p))[0]-struct.unpack('<f',struct.pack('<I',s))[0]) for p,s in zip(pixel,offset)]
        require(index == i and values[:2] == offset and values[2:] == shifts, 'sample identity/order/shift')
        raw = directory/f'sample-{i}.rgba'
        if retained:
            require(raw.is_file() and raw.stat().st_size == row*height, 'sample raw dimensions/size')
            samples.append({'index':i, 'offset':offset, 'shift':shifts, 'size':row*height, 'sha256':digest(raw.read_bytes())})
    finish = Reader((directory/'finish.bin').read_bytes())
    points = []
    point_count = finish.words(1)[0]
    for _ in range(point_count):
        x,y,*bits = finish.words(6)
        require(x < width and y < height and all(math.isfinite(struct.unpack('<f',struct.pack('<I',b))[0]) for b in bits), 'sum dimensions/nonfinite')
        points.append({'x':x, 'y':y, 'sum_bits':bits})
    require(finish.take(8) == b'COMPLETE', 'incomplete capture')
    finish.end()
    require([(p['x'],p['y']) for p in points] == POINTS.get(name,[]), 'selected point coverage/order')
    names = {'call.bin','finish.bin'} | {f'sample-{i}.bin' for i in range(count)}
    if retained:
        names |= {f'sample-{i}.rgba' for i in range(count)}
    require({p.name for p in directory.iterdir()} == names, 'unexpected/missing capture files')
    return {'test':name,'ordinal':ordinal,'width':width,'height':height,'row':row,'padded':padded,
            'pixel':pixel,'offsets':offsets,'lut':lut,'samples':samples,'points':points}


def validate_capture_records(records, c):
    expected = {name+'-'+str(i) for name,count in c['calls'].items() for i in range(count)}
    require(set(records) == expected, 'capture record call coverage')
    lut = None
    for identity,row in records.items():
        name,ordinal = identity.rsplit('-',1)
        width,height = c['dimensions']
        require(all(type(row[k]) is int for k in ('ordinal','width','height','row','padded')) and
                row['test'] == name and row['ordinal'] == int(ordinal) and
                (row['width'],row['height']) == (width,height) and row['row'] == width*4 and
                row['padded'] == ((width*4+255)//256)*256 and row['pixel'] == c['pixel'] and
                row['offsets'] == c['offsets'], 'capture record identity/dimensions/offsets')
        require(len(row['lut']) == 256 and all(type(b) is int and 0 <= b <= 0xffffffff and
                math.isfinite(struct.unpack('<f',struct.pack('<I',b))[0]) for b in row['lut']), 'LUT bit shape')
        if lut is None:
            lut = row['lut']
        require(row['lut'] == lut, 'decode LUT differs between calls')
        require(len(row['samples']) == len(c['offsets']), 'capture record sample count')
        for index,sample in enumerate(row['samples']):
            offset = c['offsets'][index]
            shift = [fbits(struct.unpack('<f',struct.pack('<I',p))[0]-struct.unpack('<f',struct.pack('<I',o))[0]) for p,o in zip(c['pixel'],offset)]
            require(type(sample['index']) is int and type(sample['size']) is int and sample['index'] == index and sample['offset'] == offset and sample['shift'] == shift and
                    sample['size'] == width*height*4 and isinstance(sample['sha256'],str) and
                    re.fullmatch('[0-9a-f]{64}',sample['sha256']), 'capture record sample identity/order/offset/size/hash')
        require([(p['x'],p['y']) for p in row['points']] == POINTS.get(name,[]) and
                all(len(p['sum_bits']) == 4 and all(type(b) is int and 0 <= b <= 0xffffffff and
                    math.isfinite(struct.unpack('<f',struct.pack('<I',b))[0]) for b in p['sum_bits']) for p in row['points']), 'actual sum point bits/coverage')
    require(sum(len(row['samples']) for row in records.values()) == 224 and
            sum(len(row['samples']) for row in records.values() if row['test'] in c['gates']) == 88, 'capture retention coverage')
    return records


def captures(root, c, stored=None):
    expected = {name+'-'+str(i) for name,count in c['calls'].items() for i in range(count)}
    require({p.name for p in root.iterdir()} == expected, 'missing/extra capture calls')
    result = {}
    for name in sorted(expected):
        directory = root/name
        keep = name.rsplit('-',1)[0] in c['gates']
        row = capture_call(directory,c, retained=stored is None or keep)
        if stored is not None:
            old = stored[name]
            if not keep:
                row['samples'] = old['samples']
                require(len(row['samples']) == len(c['offsets']) and
                        all(s['index'] == i and s['offset'] == c['offsets'][i] and s['size'] == row['row']*row['height'] and
                            re.fullmatch('[0-9a-f]{64}', s['sha256']) for i,s in enumerate(row['samples'])), 'discarded sample inventory')
            require(row == old, 'capture identity/hash/LUT/sum drift')
        result[name] = row
    return validate_capture_records(result,c)


def golden_log(raw, code, c):
    require(code == 101 and not re.search(r'SKIP|validation error|wgpu error',raw,re.I), 'canonical return code/skip')
    summaries = re.findall(r'^test result: (.*)$',raw,re.M)
    summary = re.fullmatch(r'FAILED\. 11 passed; 3 failed; 0 ignored; 0 measured; 0 filtered out; finished in ([0-9]+\.[0-9]{2})s',summaries[0]) if len(summaries) == 1 else None
    require(summary is not None and math.isfinite(float(summary[1])), 'canonical test totals')
    rows = re.findall(r'^test (\w+) \.\.\. (ok|FAILED)$',raw,re.M)
    require(len(rows) == 14 and len(dict(rows)) == 14 and set(dict(rows)) == set(c['calls']) and
            {n for n,s in rows if s == 'FAILED'} == FAILURES, 'canonical test identities/failures')
    adapters = re.findall(r'^SAMPLE_ADAPTER ([^\n]+)\|([A-Za-z0-9_]+)$',raw,re.M)
    require(len(adapters) == 14 and {name for _,name in adapters} == set(c['calls']) and
            len({name for _,name in adapters}) == 14 and all(a == EXPECTED_ADAPTER for a,_ in adapters), 'actual adapter/test identity')
    return dict(rows)


def cargo_binary(raw, source, target):
    lines = [line for line in raw.splitlines(keepends=True) if line.lstrip().startswith(b'{')]
    require(lines and all(line.endswith(b'\n') for line in lines), 'Cargo truncated object')
    rows = [load_json(line) for line in lines]
    require(all(type(r) is dict and isinstance(r.get('reason'),str) and r['reason'] for r in rows), 'Cargo object shape')
    finishes = [r for r in rows if r['reason'] == 'build-finished']
    require(len(finishes) == 1 and rows[-1] is finishes[0] and
            finishes[0] == {'reason':'build-finished','success':True} and finishes[0]['success'] is True, 'Cargo terminal success')
    selected = [r for r in rows if r['reason'] == 'compiler-artifact' and r.get('target',{}).get('name') == 'golden2']
    require(len(selected) == 1, 'Cargo golden2 artifact identity/count')
    r = selected[0]
    t = r['target']
    crate = Path(source)/'rust/crates/mds-render'
    require(r.get('manifest_path') == str(crate/'Cargo.toml') and t.get('src_path') == str(crate/'tests/golden2.rs') and
            t.get('kind') == ['test'] and t.get('crate_types') == ['bin'] and t.get('test') is True, 'Cargo target/manifest/source')
    profile = {'opt_level':'0','debuginfo':2,'debug_assertions':True,'overflow_checks':True,'test':True}
    require(r.get('profile') == profile and type(r['profile']['debuginfo']) is int and
            all(r['profile'][p] is True for p in ('debug_assertions','overflow_checks','test')), 'Cargo test profile')
    exe = r.get('executable')
    require(isinstance(exe,str) and Path(exe).parent == Path(target)/'debug/deps' and
            re.fullmatch('golden2-[0-9a-f]+',Path(exe).name) and r.get('filenames') == [exe], 'Cargo executable path')
    return exe


def relocate(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'unsafe artifact path')
    if RELOCATION:
        original,current = RELOCATION
        require(path.is_relative_to(original), 'path outside evidence root')
        return current/path.relative_to(original)
    return path


def file_id(path):
    return {'path':str(path),'size':path.stat().st_size,'sha256':digest(path.read_bytes())}


def checked_file(record):
    require(type(record['size']) is int and record['size'] >= 0 and
            isinstance(record['sha256'],str) and re.fullmatch('[0-9a-f]{64}',record['sha256']), 'file identity shape')
    path = relocate(record['path'])
    require(not path.is_symlink() and path.is_file() and path.stat().st_size == record['size'] and
            digest(path.read_bytes()) == record['sha256'], 'file identity/hash mismatch')
    return path


def command(out,label,argv,cwd,env):
    start = time.time_ns()
    stdout,stderr = out/(label+'.stdout'),out/(label+'.stderr')
    record = {'argv':list(map(str,argv)),'cwd':str(cwd),'env':env,'start_ns':start,
              'end_ns':None,'status':None,'stdout_path':str(stdout),'stderr_path':str(stderr)}
    receipt = out/(label+'.json')
    receipt.write_text(json.dumps(record,indent=2)+'\n')
    with stdout.open('xb') as out_stream, stderr.open('xb') as err_stream:
        result = subprocess.run(list(map(str,argv)),cwd=cwd,env=env,stdout=out_stream,stderr=err_stream)
    record |= {'end_ns':time.time_ns(),'status':result.returncode,
               'stdout':file_id(stdout),'stderr':file_id(stderr)}
    receipt.write_text(json.dumps(record,indent=2)+'\n')
    return record


def output(record):
    return checked_file(record['stdout']).read_text()+'\n'+checked_file(record['stderr']).read_text()


def validate_command(record,argv,cwd,env,status):
    require(record['argv'] == list(map(str,argv)) and record['cwd'] == str(cwd) and record['env'] == env and
            record['status'] == status and type(record['status']) is int and
            type(record['start_ns']) is int and type(record['end_ns']) is int and
            0 <= record['start_ns'] <= record['end_ns'], 'command identity/status/timing')
    checked_file(record['stdout'])
    checked_file(record['stderr'])


def git_hash(kind,raw):
    return hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def git_inventory(root):
    return {name: ['100755' if (root/name).stat().st_mode & 0o111 else '100644',
                   git_hash('blob',(root/name).read_bytes())] for name in snapshot(root)}


def tree_hash(entries):
    tree = {}
    for path,(mode,sha) in entries.items():
        safe_name(path)
        node = tree
        parts = path.split('/')
        for part in parts[:-1]:
            node = node.setdefault(part,{})
            require(type(node) is dict,'Git file/directory collision')
        require(parts[-1] not in node and mode in ('100644','100755') and re.fullmatch('[0-9a-f]{40}',sha), 'Git entry shape')
        node[parts[-1]] = (mode,sha)
    def build(node):
        values = []
        for name,value in node.items():
            is_dir = isinstance(value,dict)
            mode,sha = ('40000',build(value)) if is_dir else value
            values.append((name.encode()+ (b'/' if is_dir else b''), mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(sha)))
        return git_hash('tree',b''.join(body for _,body in sorted(values)))
    return build(tree)


def commit_proof(path,revision,entries):
    raw = path.read_bytes()
    require(git_hash('commit',raw) == revision and raw.startswith(('tree '+tree_hash(entries)+'\n').encode()), 'fixed Git commit/tree/source identity')


def archive_extract(archive,dest):
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        require(len({m.name for m in members}) == len(members), 'duplicate source archive path')
        for m in members:
            safe_name(m.name.rstrip('/'))
            require(m.isdir() or m.isfile(), 'archive links/special entries prohibited')
        tar.extractall(dest,filter='data')


def image_analysis(control,observed,gold_dir,c,logs,capture_dir,capture_rows,replay_dir):
    results = []
    expected_files = {name+suffix for name in c['gates'].values() for suffix in ('.png','-diff.png')}
    require({p.name for p in control.iterdir()} == {p.name for p in observed.iterdir()} == expected_files,'canonical image coverage')
    dimensions = tuple(c['dimensions'])
    width,height = dimensions
    for test,name in sorted(c['gates'].items()):
        a,b,gold = [read_png(p/(name+'.png'),dimensions) for p in (control,observed,gold_dir)]
        da,db = [read_png(p/(name+'-diff.png'),dimensions) for p in (control,observed)]
        require(a == b and da == db,'control/observer RGBA or diff/mask changed: '+name)
        mask = [p == (255,0,255,255) for p in da]
        errors = [max(abs(p[k]-g[k]) for k in range(3)) for p,g in zip(a,gold)]
        unmasked = [d for d,m in zip(errors,mask) if not m]
        require(unmasked,'empty canonical score')
        for i,(d,m) in enumerate(zip(errors,mask)):
            if not m:
                v = 255-min(255,4*d)
                require(da[i] == (v,v,v,255),'canonical diff encoding')
        score = {'pixels':len(unmasked),'close_count':sum(d <= 4 for d in unmasked),'over4':sum(d > 4 for d in unmasked),
                 'max':max(unmasked),'sum':sum(unmasked),'tolerance':4,'min_close':0.9999,'max_limit':48}
        close = score['close_count']/score['pixels']
        score['passes'] = close >= .9999 and score['max'] <= 48
        require(score['passes'] == (test not in FAILURES),'canonical score/failure set')
        for log in logs:
            rows = re.findall(re.escape(name)+r': (\d+) px \((\d+) masked\), within 4 ([0-9.]+), max (\d+), mean ([0-9.]+)',log)
            require(rows == [(str(len(unmasked)),str(sum(mask)),f'{close:.5f}',str(score['max']),f"{score['sum']/score['pixels']:.4f}")], 'canonical printed metric mismatch')
        call_name = test+'-0'
        replay = (replay_dir/(name+'.rgba')).read_bytes()
        require(len(replay) == width*height*4 and replay == bytes(v for p in b for v in p), 'independent full-image replay mismatch')
        row = capture_rows[call_name]
        samples = [(capture_dir/call_name/f'sample-{i}.rgba').read_bytes() for i in range(8)]
        points = []
        for p in row['points']:
            x,y = p['x'],p['y']
            i = y*width+x
            colors = [list(raw[4*i:4*i+4]) for raw in samples]
            minimum = [min(color[k] for color in colors) for k in range(4)]
            maximum = [max(color[k] for color in colors) for k in range(4)]
            excluded = [k for k in range(4) if gold[i][k] < minimum[k] or gold[i][k] > maximum[k]]
            points.append(p | {'masked':mask[i],'samples':colors,'golden':gold[i],'control':a[i],'observer':b[i],
                              'replay':list(replay[4*i:4*i+4]),'min':minimum,'max':maximum,'excluded_channels':excluded,
                              'classification':'excluded_by_channel_bound' if excluded else 'not_excluded'})
        maxima = None
        if test in ('skin_0','skin_30'):
            x,y = POINTS[test][-1]
            expected = 78 if test == 'skin_0' else 112
            actual = score['max']
            maxima = {'documented_point':[x,y],'documented_error':expected,'actual_point_error':errors[y*width+x],
                      'actual_max':actual,'discrepancy':errors[y*width+x] != expected or actual != expected}
        if test == 'selfshadow_30':
            documented = POINTS[test][:3]
            point_errors = [errors[y*width+x] for x,y in documented]
            maxima = {'documented_points':documented,'documented_error':56,'actual_point_errors':point_errors,
                      'actual_max':score['max'],'discrepancy':any(error != 56 for error in point_errors) or score['max'] != 56}
        results.append({'test':test,'image':name,'metrics':score,'mask_sha256':digest(bytes(mask)),
                        'points':points,'maxima':maxima,'rgba_sha256':digest(replay)})
    return results


def verify(manifest, temporary=False):
    require(manifest['schema'] == 1 and manifest['base'] == BASE,'experiment schema/base')
    out = relocate(manifest['artifact_root'])
    base = out/'sources/base'
    frozen(base)
    base_git = git_inventory(base)
    commit_proof(out/'base.commit',BASE,base_git)
    tooling = out/'tooling'
    require(set(snapshot(tooling)) == ALLOWLIST,'tooling path closure')
    head_git = base_git | git_inventory(tooling)
    require(set(head_git)-set(base_git) == ALLOWLIST,'only five new paths authorized')
    commit_proof(out/'head.commit',manifest['head'],head_git)
    require(snapshot(base) == manifest['base_sources'],'base inventory drift')
    c = contract(base)
    observer = (tooling/(PREFIX+'observer.rs')).read_bytes()
    common_env = manifest['env']
    require(common_env.get('WGPU_BACKEND') == 'vulkan' and 'MDS_RENDER_RECORD' not in common_env and
            not any(k.startswith('MDS_') for k in common_env),'common environment identity')
    host = manifest['host']
    require(len(host['commands']) >= 4,'host receipts incomplete')
    expected_host = [['rustc','+1.95.0','-vV'],['vulkaninfo','--summary'],
                     ['dpkg-query','-W','mesa-vulkan-drivers','libvulkan1'],['ldconfig','-p']]
    host_cwd = str(Path(manifest['artifact_root'])/'sources/base/rust')
    for index,record in enumerate(host['commands']):
        if index < 4:
            argv = expected_host[index]
        else:
            argv = record['argv']
            require(len(argv) == 2 and argv[0] == 'ldd' and
                    argv[1] in {r['original_path'] for r in host['libraries']}, 'host library command identity')
        validate_command(record,argv,host_cwd,common_env,0)
    require(re.search(r'^rustc 1\.95\.0 ', output(host['commands'][0]),re.M) and
            'host: x86_64-unknown-linux-gnu' in output(host['commands'][0]) and
            'llvmpipe' in output(host['commands'][1]).lower(), 'compiler/host Vulkan identity')
    require(host['icd']['original_path'] == common_env['VK_ICD_FILENAMES'],'ICD environment identity')
    checked_file(host['icd'])
    require(host['libraries'] and any('lvp' in r['original_path'] for r in host['libraries']), 'host libraries missing')
    for record in host['libraries']:
        checked_file(record)
    require(manifest['points_text'] == point_text() and (out/'points.tsv').read_text() == point_text(),'point contract drift')
    variants = manifest['variants']
    require([v['name'] for v in variants] == ['control','observed'],'variant identity/order')
    logs = []
    for v in variants:
        name = v['name']
        source = relocate(v['source'])
        require(source == out/'sources'/name,'source directory identity')
        validate_generated(base,source,name == 'observed',observer)
        require(snapshot(source) == v['before'] == v['after'],'before/end source/fixture inventories')
        require(v['fixture_before'] == v['fixture_after'] == {p:h for p,h in snapshot(base).items() if p.startswith('tests/fixtures/')}, 'fixture inventories')
        expected_spans = {COMMON:insertions((base/COMMON).read_text(),COMMON_CHANGES)[1]}
        if name == 'observed':
            expected_spans[RENDERER] = insertions((base/RENDERER).read_text(),RENDERER_CHANGES)[1]
        require(v['spans'] == expected_spans,'declared generated spans')
        for path in expected_spans:
            expected_diff = ''.join(difflib.unified_diff((base/path).read_text().splitlines(True),(source/path).read_text().splitlines(True),fromfile=path,tofile=path))
            require((out/name/(Path(path).name+'.diff')).read_text() == expected_diff,'generated diff receipt')
        require(type(v['before_ns']) is int and type(v['after_ns']) is int and
                v['before_ns'] <= v['build']['start_ns'] <= v['test']['end_ns'] <= v['after_ns'], 'source before/end timing')
        target = v['target']
        require(not Path(target).is_relative_to(Path(v['source'])),'build target inside source snapshot')
        env = common_env | {'CARGO_TARGET_DIR':target}
        validate_command(v['build'],BUILD,Path(v['source'])/'rust',env,0)
        cargo = cargo_binary(checked_file(v['build']['stdout']).read_bytes(),v['source'],target)
        require(v['original_binary']['path'] == cargo and v['original_binary']['size'] == v['binary']['size'] and
                v['original_binary']['sha256'] == v['binary']['sha256'], 'original/copied binary hash identity')
        binary = checked_file(v['binary'])
        require(binary == out/name/'golden2','retained binary path')
        validate_command(v['list'],[v['binary']['path'],'--list'],Path(v['source'])/'rust',env,0)
        listed = re.findall(r'^(\w+): test$',output(v['list']),re.M)
        require(len(listed) == 14 and set(listed) == set(c['calls']),'actual binary test list/source mapping')
        test_env = env | {'MDS_RENDER_PNG_DIR':v['images']}
        if name == 'observed':
            test_env |= {'MDS_SAMPLE_READBACK_DIR':manifest['capture_dir'],'MDS_SAMPLE_POINTS':str(Path(manifest['artifact_root'])/'points.tsv')}
        validate_command(v['test'],[v['binary']['path']]+FLAGS,Path(v['source'])/'rust',test_env,101)
        raw = output(v['test'])
        golden_log(raw,101,c)
        logs.append(raw)
        require(snapshot(relocate(v['images'])) == v['image_inventory'],'image inventory/hash drift')
    require(variants[0]['target'] != variants[1]['target'],'shared Cargo target')
    require(variants[0]['test']['end_ns'] <= variants[1]['build']['start_ns'],'nonsequential Cargo/GPU execution')
    capture_dir = relocate(manifest['capture_dir'])
    require(capture_dir == out/'captures','capture root identity')
    observed = captures(capture_dir,c,None if temporary else manifest['captures'])
    require(observed == manifest['captures'],'captured record inventory mismatch')
    replay = manifest['replay']
    source = out/'replay.rs'
    require(source.read_bytes() == (tooling/(PREFIX+'replay.rs')).read_bytes(),'independent replay source identity')
    compile_argv = ['rustc','+1.95.0','--edition=2021','-C','opt-level=0',str(Path(manifest['artifact_root'])/'replay.rs'),'-o',replay['original_binary']['path']]
    validate_command(replay['compile'],compile_argv,str(Path(manifest['artifact_root'])),common_env,0)
    binary = checked_file(replay['binary'])
    require(replay['original_binary']['size'] == replay['binary']['size'] and replay['original_binary']['sha256'] == replay['binary']['sha256'], 'replay original/copied hash')
    require(binary == out/'replay','replay retained binary path')
    validate_command(replay['self_check'],[replay['binary']['path'],'--self-check'],manifest['artifact_root'],common_env,0)
    require(output(replay['self_check']).strip() == 'REPLAY_SELF_CHECK_OK','replay self checks')
    require(set(replay['runs']) == set(c['gates']),'independent replay coverage')
    for test,record in replay['runs'].items():
        image = c['gates'][test]
        argv = [replay['binary']['path'],str(Path(manifest['capture_dir'])/(test+'-0')),str(Path(manifest['artifact_root'])/'replays'/(image+'.rgba'))]
        validate_command(record,argv,manifest['artifact_root'],common_env,0)
        require(output(record).strip() == f"REPLAY_OK {test} 0 {c['dimensions'][0]} {c['dimensions'][1]} {len(POINTS.get(test,[]))}", 'actual replay identity/sum receipt')
    images = image_analysis(*(relocate(v['images']) for v in variants),base/'tests/fixtures/rust/golden2',c,logs,capture_dir,observed,out/'replays')
    total = sum(s['size'] for row in observed.values() for s in row['samples'])
    retained = sum(s['size'] for row in observed.values() if row['test'] in c['gates'] for s in row['samples'])
    return {'diagnostic_valid':True,'golden_parity':False,'renderer_adopted':False,'base':BASE,'head':manifest['head'],
            'adapter':EXPECTED_ADAPTER,'tests':14,'passed':11,'failed':sorted(FAILURES),'calls':28,'sample_records':224,
            'retained_samples':88,'discarded_payloads':136,'replayed_gate_calls':11,'discarded_payload_replay':False,
            'sample_bytes':total,'retained_bytes':retained,'images':images,
            'mask_origin':'Immutable canonical diff magenta sentinels tied to fixed score source; grid projection is not independently rerun.',
            'limits':'Channel exclusion assumes monotone convex resolve. In-range is inconclusive. No native PMM pose, primitive, depth, hardware 8x or sample-ownership evidence. Host ICD/library/UUID receipts do not prove per-process loaded libraries or adapter UUID.'}


def point_text():
    return ''.join(f'{name} {x} {y}\n' for name,points in POINTS.items() for x,y in points)


def run(out,build_root):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true', 'execution is hosted Linux only')
    require(not out.exists() and not build_root.exists() and not out.is_relative_to(ROOT) and not build_root.is_relative_to(ROOT) and
            not out.is_relative_to(build_root) and not build_root.is_relative_to(out), 'fresh separate external evidence/build roots required')
    out.mkdir(parents=True)
    build_root.mkdir(parents=True)
    manifest = {'schema':1,'base':BASE,'artifact_root':str(out),'variants':[]}
    def checkpoint():
        (out/'partial.json').write_text(json.dumps(manifest,indent=2)+'\n')
    checkpoint()
    head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    require(not subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT),'checkout has tracked changes')
    changed = subprocess.check_output(['git','diff','--name-only',BASE,head],cwd=ROOT,text=True).splitlines()
    require(set(changed) == ALLOWLIST,'HEAD delta must be exactly five approved additions')
    for revision,label in [(BASE,'base'),(head,'head')]:
        (out/(label+'.commit')).write_bytes(subprocess.check_output(['git','cat-file','commit',revision],cwd=ROOT))
    tooling = out/'tooling'
    for name in ALLOWLIST:
        dest = tooling/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/name,dest)
    archive = out/'base-source.tar'
    with archive.open('xb') as stream:
        subprocess.run(['git','archive',BASE],cwd=ROOT,stdout=stream,check=True)
    base = out/'sources/base'
    base.mkdir(parents=True)
    archive_extract(archive,base)
    manifest |= {'head':head,'base_sources':snapshot(base),'points_text':point_text()}
    commit_proof(out/'base.commit',BASE,git_inventory(base))
    (out/'points.tsv').write_text(point_text())
    env = {k:os.environ[k] for k in ('PATH','HOME','CARGO_HOME','RUSTUP_HOME','TMPDIR','LD_LIBRARY_PATH') if k in os.environ}
    icds = list(Path('/usr/share/vulkan/icd.d').glob('lvp_icd*.json'))
    require(len(icds) == 1,'exactly one llvmpipe ICD required')
    runtime = out/'xdg-runtime'
    runtime.mkdir(mode=0o700)
    env |= {'WGPU_BACKEND':'vulkan','VK_ICD_FILENAMES':str(icds[0]),'XDG_RUNTIME_DIR':str(runtime),
            'CARGO_TERM_COLOR':'never','CARGO_INCREMENTAL':'0','CXX':'clang++'}
    manifest['env'] = env
    host_commands = []
    manifest['host'] = {'commands':host_commands,'libraries':[]}
    for label,argv in [('rust-version',['rustc','+1.95.0','-vV']),('vulkan-summary',['vulkaninfo','--summary']),
                       ('mesa-packages',['dpkg-query','-W','mesa-vulkan-drivers','libvulkan1']),('loader-libraries',['ldconfig','-p'])]:
        record = command(out,label,argv,base/'rust',env)
        host_commands.append(record)
        checkpoint()
        require(record['status'] == 0,'host receipt failed')
    library = Path(load_json(icds[0].read_text())['ICD']['library_path'])
    if not library.is_absolute():
        library = Path('/usr/lib/x86_64-linux-gnu')/library
    libraries = {library} | {Path(p) for p in re.findall(r'=> (/\S+)',output(host_commands[3])) if 'libvulkan' in p}
    for i,path in enumerate(sorted(libraries)):
        record = command(out,'library-deps-'+str(i),['ldd',str(path)],base/'rust',env)
        host_commands.append(record)
        require(record['status'] == 0,'library dependency receipt failed')
        libraries |= {Path(p) for p in re.findall(r'=> (/\S+)',output(record))}
    host_files = out/'host-files'
    host_files.mkdir()
    for i,path in enumerate(sorted(libraries)):
        dest = host_files/(str(i)+'-'+path.name)
        shutil.copy2(path,dest)
        manifest['host']['libraries'].append(file_id(dest) | {'original_path':str(path)})
    dest = host_files/icds[0].name
    shutil.copy2(icds[0],dest)
    manifest['host']['icd'] = file_id(dest) | {'original_path':str(icds[0])}
    capture_dir = out/'captures'
    capture_dir.mkdir()
    manifest['capture_dir'] = str(capture_dir)
    observer = (tooling/(PREFIX+'observer.rs')).read_bytes()
    c = contract(base)
    for name in ('control','observed'):
        directory = out/name
        directory.mkdir()
        source = out/'sources'/name
        spans = generate(base,source,name == 'observed',observer)
        for path in spans:
            diff = ''.join(difflib.unified_diff((base/path).read_text().splitlines(True),(source/path).read_text().splitlines(True),fromfile=path,tofile=path))
            (directory/(Path(path).name+'.diff')).write_text(diff)
        images = directory/'images'
        images.mkdir()
        v = {'name':name,'source':str(source),'before':snapshot(source),'spans':spans,
             'fixture_before':{p:h for p,h in manifest['base_sources'].items() if p.startswith('tests/fixtures/')},
             'target':str(build_root/name),'images':str(images),'before_ns':time.time_ns()}
        manifest['variants'].append(v)
        checkpoint()
        variant_env = env | {'CARGO_TARGET_DIR':v['target']}
        v['build'] = command(directory,'build',BUILD,source/'rust',variant_env)
        checkpoint()
        require(v['build']['status'] == 0,'Cargo build failed')
        original = Path(cargo_binary(checked_file(v['build']['stdout']).read_bytes(),source,v['target']))
        v['original_binary'] = file_id(original)
        binary = directory/'golden2'
        shutil.copy2(original,binary)
        v['binary'] = file_id(binary)
        require(v['original_binary']['sha256'] == v['binary']['sha256'],'copy binary hash mismatch')
        v['list'] = command(directory,'list',[binary,'--list'],source/'rust',variant_env)
        test_env = variant_env | {'MDS_RENDER_PNG_DIR':str(images)}
        if name == 'observed':
            test_env |= {'MDS_SAMPLE_READBACK_DIR':str(capture_dir),'MDS_SAMPLE_POINTS':str(out/'points.tsv')}
        v['test'] = command(directory,'test',[binary]+FLAGS,source/'rust',test_env)
        v['after'] = snapshot(source)
        v['after_ns'] = time.time_ns()
        v['fixture_after'] = {p:h for p,h in v['after'].items() if p.startswith('tests/fixtures/')}
        v['image_inventory'] = snapshot(images)
        checkpoint()
        golden_log(output(v['test']),v['test']['status'],c)
    manifest['captures'] = captures(capture_dir,c)
    manifest['capture_inventory_before_cleanup'] = snapshot(capture_dir)
    source = out/'replay.rs'
    shutil.copy2(tooling/(PREFIX+'replay.rs'),source)
    original = build_root/'sample-replay'
    replay = {'runs':{}}
    manifest['replay'] = replay
    replay['compile'] = command(out,'replay-compile',['rustc','+1.95.0','--edition=2021','-C','opt-level=0',source,'-o',original],out,env)
    checkpoint()
    require(replay['compile']['status'] == 0,'independent replay compile failed')
    replay['original_binary'] = file_id(original)
    binary = out/'replay'
    shutil.copy2(original,binary)
    replay['binary'] = file_id(binary)
    replay['self_check'] = command(out,'replay-self-check',[binary,'--self-check'],out,env)
    replays = out/'replays'
    replays.mkdir()
    for test,image in sorted(c['gates'].items()):
        record = command(out,'replay-'+test,[binary,capture_dir/(test+'-0'),replays/(image+'.rgba')],out,env)
        replay['runs'][test] = record
        checkpoint()
        require(record['status'] == 0,'independent f32 replay discrepancy: '+test)
    verify(manifest, temporary=True)
    for call,row in manifest['captures'].items():
        if row['test'] not in c['gates']:
            for sample in row['samples']:
                path = capture_dir/call/f"sample-{sample['index']}.rgba"
                require(digest(path.read_bytes()) == sample['sha256'],'temporary owned payload drift before deletion')
                path.unlink()
    manifest['capture_inventory_after_cleanup'] = snapshot(capture_dir)
    (out/'experiment.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def verify_cleanup(manifest):
    root = relocate(manifest['capture_dir'])
    before,after = manifest['capture_inventory_before_cleanup'],manifest['capture_inventory_after_cleanup']
    c = contract(relocate(manifest['artifact_root'])/'sources/base')
    expected_removed = {name+f"/sample-{s['index']}.rgba":s['sha256'] for name,row in manifest['captures'].items()
                        if row['test'] not in c['gates'] for s in row['samples']}
    require(len(expected_removed) == 136 and {p:h for p,h in before.items() if p not in after} == expected_removed and
            after == {p:h for p,h in before.items() if p not in expected_removed} and snapshot(root) == after,
            'temporary sample cleanup/inventory identity')


def main():
    global RELOCATION
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--build-root',type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    try:
        if args.run:
            require(args.build_root is not None,'--build-root required')
            manifest = run(out,args.build_root.resolve())
        else:
            manifest = load_json((out/'experiment.json').read_text())
            RELOCATION = (Path(manifest['artifact_root']),out)
            seal = load_json((out/'seal.json').read_text())
            require({p:h for p,h in snapshot(out).items() if p != 'seal.json'} == seal,'full evidence seal/inventory mismatch')
        verify_cleanup(manifest)
        result = verify(manifest)
        if args.run:
            (out/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
            (out/'seal.json').write_text(json.dumps(snapshot(out),indent=2)+'\n')
        print(json.dumps(result,indent=2))
        return 0
    except (ValueError,KeyError,IndexError,TypeError,OSError,subprocess.SubprocessError,tarfile.TarError,zlib.error,struct.error) as error:
        if args.run and out.exists():
            (out/'failure.json').write_text(json.dumps({'diagnostic_valid':False,'error':str(error)},indent=2)+'\n')
        print(str(error),file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
