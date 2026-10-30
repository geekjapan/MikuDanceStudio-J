"""Closed native capture and Rust replay custody and admission."""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import ntpath
import math
import re
import stat
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import subprocess
import time

ENVIRONMENT = ['CL', '_CL_', 'INCLUDE', 'LIB', 'LIBPATH', 'CXX', 'CC', 'LD', 'AR', 'SDKROOT',
               'MACOSX_DEPLOYMENT_TARGET', 'CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'RUSTFLAGS',
               'CARGO_ENCODED_RUSTFLAGS', 'RUSTUP_TOOLCHAIN', 'BULLET_ALLOC_LOG', 'OPENMMD_DUMP_SPRING']

def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    temporary = path.with_name(path.name + '.pending')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(path)


def identity(executable):
    found = shutil.which(str(executable))
    require(found is not None, 'resolved executable ' + str(executable))
    path = Path(found).absolute()
    target = path.resolve(strict=True)
    require(target.is_file(), 'regular executable')
    return {'path': str(path), 'target': str(target), 'sha256': digest(target.read_bytes())}


class Recorder:
    def __init__(self, out, snapshot):
        self.out, self.snapshot = out, snapshot
        self.sources = snapshot()
        self.commands = []
        self.generated_roots = []
        self.tools = {}
        self.environment = {key: os.environ.get(key) for key in ENVIRONMENT}
        save(out / 'source-start.json', self.sources)
        save(out / 'environment-start.json', self.environment)

    def generated_snapshot(self):
        return {p.relative_to(self.out).as_posix(): digest(p.read_bytes())
                for root in self.generated_roots for p in sorted(root.rglob('*'))
                if p.is_file() and '__pycache__' not in p.parts}

    def bind_tool(self, executable):
        binding = identity(executable)
        if not Path(binding['path']).is_relative_to(self.out):
            require(binding['path'] not in self.tools or self.tools[binding['path']] == binding, 'fixed external tool identity')
            self.tools[binding['path']] = binding
            retained = self.out / 'tool-bytes' / binding['sha256']
            retained.parent.mkdir(exist_ok=True)
            if not retained.exists():
                retained.write_bytes(Path(binding['target']).read_bytes())
            save(self.out / 'tools-start.json', self.tools)
        return binding

    def run(self, label, argv, *, cwd, data=None, inputs=(), outputs=()):
        require(label and all(c in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in label), 'command label')
        require(not any(record['label'] == label for record in self.commands), 'unique command label')
        require(self.snapshot() == self.sources, 'fixed sources before ' + label)
        require({key: os.environ.get(key) for key in ENVIRONMENT} == self.environment, 'named settings preserved before command')
        binding = self.bind_tool(argv[0])
        outputs = list(outputs)
        if os.name == 'nt' and (label in {'dedicated-build', 'pure-build', 'rust-observed-build'}
                                or label.startswith(('baseline-build-', 'mutant-build-'))):
            require(len(outputs) == 1 and Path(outputs[0]).suffix == '.exe', 'one Windows Rust executable')
            outputs.append(Path(outputs[0]).with_suffix('.pdb'))
        argv = [binding['path'], *map(str, argv[1:])]
        record = {'label': label, 'argv': argv, 'cwd': str(cwd), 'executable': binding,
                  'stdin_sha256': None if data is None else digest(data),
                  'inputs_before': {str(p): digest(Path(p).read_bytes()) for p in inputs},
                  'generated_before': self.generated_snapshot(),
                  'outputs': {}, 'pid': None, 'start_utc': utc(), 'end_utc': None,
                  'waited': False, 'streams_closed': False, 'returncode': None}
        self.commands.append(record)
        save(self.out / 'commands.json', self.commands)
        start = time.monotonic()
        stdout_path, stderr_path = (self.out / (label + suffix) for suffix in ('.stdout', '.stderr'))
        with stdout_path.open('xb') as stdout, stderr_path.open('xb') as stderr:
            process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, env={**os.environ, 'VSLANG': '1033'})
            record['pid'] = process.pid
            save(self.out / 'commands.json', self.commands)
            try:
                process.communicate(data, timeout=600)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                record['timeout'] = True
            record.update(returncode=process.returncode, waited=True)
        record.update(end_utc=utc(), seconds=time.monotonic() - start, streams_closed=True,
                      stdout_sha256=digest(stdout_path.read_bytes()), stderr_sha256=digest(stderr_path.read_bytes()))
        record['outputs'] = {str(p): digest(Path(p).read_bytes()) for p in outputs if Path(p).is_file()}
        record['inputs_end'] = {str(p): digest(Path(p).read_bytes()) for p in inputs}
        record['executable_end'] = identity(binding['path'])
        record['generated_end'] = self.generated_snapshot()
        save(self.out / 'commands.json', self.commands)
        require(record['inputs_end'] == record['inputs_before'], 'input preservation ' + label)
        require(record['executable_end'] == binding, 'executable preservation ' + label)
        require(record['generated_end'] == record['generated_before'], 'generated source preservation ' + label)
        require(self.snapshot() == self.sources, 'fixed sources after ' + label)
        require(record['returncode'] == 0 and not record.get('timeout'), 'normally exiting command ' + label)
        require(len(record['outputs']) == len(outputs), 'all declared command outputs ' + label)
        return stdout_path.read_bytes()

    def close(self):
        end = self.snapshot()
        save(self.out / 'source-end.json', end)
        environment = {key: os.environ.get(key) for key in ENVIRONMENT}
        save(self.out / 'environment-end.json', environment)
        require(environment == self.environment, 'named setting start/end preservation')
        tools = {name: identity(name) for name in self.tools}
        save(self.out / 'tools-end.json', tools)
        require(tools == self.tools, 'external tool start/end identity preservation')
        require(end == self.sources, 'source before/end preservation')
        require(all(record['waited'] and record['streams_closed'] for record in self.commands), 'all commands waited and closed')


MAX_FILES, MAX_FILE, MAX_TOTAL, MAX_PATH = 24000, 512 * 1024**2, 4 * 1024**3, 1024


def fields(value, names, message):
    require(type(value) is dict and set(value) == set(names), message + ' fields')
    return value


def sha_identity(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None, 'digest framing')
    return value


def include_occurrences(stdout, stderr, system):
    found = []
    for stream, raw in [('stdout',stdout),('stderr',stderr)]:
        ordinal = 0
        for line in raw.decode().splitlines():
            match = re.match(r'^Note: including file:\s+(.+)$',line) if system == 'Windows' else re.match(r'^\.+ (.+)$',line)
            if match:
                found.append({'stream':stream,'ordinal':ordinal,'raw':match[1]})
                ordinal += 1
    return found


def include_projection(bindings, occurrences, system):
    require(type(bindings) is list and len(bindings)==len(occurrences) and bindings, 'complete include occurrences')
    path = PureWindowsPath if system=='Windows' else PurePosixPath
    manifest, aliases = {}, {}
    for binding, occurrence in zip(bindings,occurrences):
        fields(binding,['stream','ordinal','raw','target','sha256'],'include binding')
        require(type(binding['ordinal']) is int and {key:binding[key] for key in occurrence}==occurrence, 'exact include stream/ordinal/raw ownership')
        target = binding['target']; raw = binding['raw']; value = sha_identity(binding['sha256'])
        require(type(raw) is str and 0<len(raw)<=MAX_PATH and '\x00' not in raw, 'include raw spelling')
        require(type(target) is str and path(target).is_absolute() and '..' not in path(target).parts and len(target)<=MAX_PATH, 'resolved include absolute target')
        require(target==(ntpath.normcase(str(path(target))) if system=='Windows' else str(path(target))), 'canonical resolved include target')
        require(target not in manifest or manifest[target]==value, 'consistent include target bytes')
        require(raw not in aliases or aliases[raw]==(target,value), 'consistent include alias binding')
        manifest[target]=value; aliases[raw]=(target,value)
    return manifest, aliases


@dataclass(frozen=True)
class _Archive:
    payloads: dict
    specials: tuple
    bsd_indexes: dict[str, bytes]


def decode_archive(raw):
    require(type(raw) is bytes and 8 <= len(raw) <= MAX_FILE and raw.startswith(b'!<arch>\n'), 'bounded actual ar/COFF archive container')
    offset, names, result, specials = 8, b'', {}, []
    symbol_tables, member_offsets, bsd_indexes = [], set(), {}
    while offset < len(raw):
        header = raw[offset:offset+60]
        require(len(header)==60 and header[58:]==b'`\n' and re.fullmatch(rb' *[0-9]+ *', header[48:58]), 'archive header')
        size = int(header[48:58]); start = offset+60
        require(start+size <= len(raw), 'archive payload bounds')
        body = raw[start:start+size]; name = header[:16].decode('ascii').strip()
        if name in {'/', '//', '/SYM64/'}:
            specials.append(name)
            require(specials.count(name) <= (2 if name=='/' else 1), 'archive special member multiplicity')
            if name=='//': names = body
            else:symbol_tables.append((name,body))
        else:
            if name.startswith('#1/'):
                require(name[3:].isdigit(), 'BSD archive name length')
                length = int(name[3:]); require(0 < length <= len(body), 'BSD archive name bounds')
                inline = body[:length].rstrip(b'\x00')
                require(b'\x00' not in inline, 'BSD archive inline name padding')
                name = inline.decode(); body = body[length:]
            elif re.fullmatch(r'/[0-9]+', name):
                index = int(name[1:]); require(index < len(names) and (index==0 or names[index-1] in (0,10)), 'archive long name offset')
                tail = names[index:]; match = re.search(b'\x00|/\n', tail)
                require(match is not None, 'terminated archive long name'); name = tail[:match.start()].decode()
            else:
                require(not name.startswith('/'), 'known archive table/name encoding')
                name = name.rstrip('/')
            if name.startswith('__.SYMDEF'):
                require(name in {'__.SYMDEF','__.SYMDEF SORTED','__.SYMDEF_64','__.SYMDEF_64 SORTED'}, 'known archive symbol table')
                require(not bsd_indexes, 'archive special member multiplicity')
                symbol_tables.append((name,body));specials.append(name);bsd_indexes[name]=body
                if size%2:require(raw[start+size:start+size+1]==b'\n', 'archive alignment byte')
                offset = start+size+size%2; continue
            require(name and name.casefold() not in {key.casefold() for key in result}, 'unique archive payload member')
            result[name] = body;member_offsets.add(offset)
        if size%2: require(raw[start+size:start+size+1] == b'\n', 'archive alignment byte')
        offset = start+size+size%2
    require(offset==len(raw), 'complete archive container')
    for i,(name,body) in enumerate(symbol_tables):
        require(valid_symbol_table(name,body,member_offsets,second=i==1 and name=='/'), 'archive symbol table payload/offsets')
    return _Archive(result,tuple(specials),bsd_indexes)


def archive_listing(archive, listing, system):
    require(type(listing) is list and all(type(name) is str and name for name in listing), 'archive listing names')
    actual=Counter(listing); payloads=Counter(archive.payloads.keys())
    require(all(actual[name]==1 for name in payloads), 'actual archive listing payload membership')
    extra=actual-payloads
    allowed=Counter(name for name in archive.specials if system=='Darwin' and name.startswith('__.SYMDEF'))
    require(not (extra-allowed), 'actual archive listing special membership')


def valid_symbol_table(name, raw, offsets, second=False):
    def strings(data,count):
        parts=data.split(b'\0')
        return len(parts)>count and all(parts[i] for i in range(count)) and not b'\0'.join(parts[count:]).strip(b'\0\n')
    if name.startswith('__.SYMDEF'):
        width=8 if '_64' in name else 4
        for order in ['little','big']:
            if len(raw)<2*width:continue
            size=int.from_bytes(raw[:width],order);end=width+size
            if size%(2*width) or end+width>len(raw):continue
            strings_size=int.from_bytes(raw[end:end+width],order);text=raw[end+width:end+width+strings_size]
            if end+width+strings_size>len(raw) or raw[end+width+strings_size:].strip(b'\0'):continue
            valid=True
            for start in range(width,end,2*width):
                index=int.from_bytes(raw[start:start+width],order);member=int.from_bytes(raw[start+width:start+2*width],order)
                if member not in offsets or index>=len(text) or (index and text[index-1]!=0) or b'\0' not in text[index:]:valid=False;break
            if valid:return True
        return False
    width=8 if name=='/SYM64/' else 4
    if len(raw)<width:return False
    order='little' if second else 'big';count=int.from_bytes(raw[:width],order)
    end=width+count*width
    if end>len(raw):return False
    members=[int.from_bytes(raw[start:start+width],order) for start in range(width,end,width)]
    if not all(value in offsets for value in members):return False
    if not second:return strings(raw[end:],count)
    if end+4>len(raw):return False
    count=int.from_bytes(raw[end:end+4],'little');start=end+4;end=start+2*count
    if end>len(raw):return False
    if any(not 1<=int.from_bytes(raw[i:i+2],'little')<=len(members) for i in range(start,end,2)):return False
    return strings(raw[end:],count)


def darwin_object_records(raw):
    # Symbol/literal payload is opaque; only the leading object table owns link identities.
    prefix = re.match(rb'\A# Path: /[^\x00-\x1f]+\n# Arch: arm64\n# Object files:\n', raw)
    require(prefix is not None and prefix.end()<=2*MAX_PATH, 'Darwin object table prefix')
    records = []
    indices = set()
    offset = prefix.end()
    while offset<len(raw):
        end = raw.find(b'\n',offset)
        require(end>=0 and end-offset<=MAX_PATH*2, 'Darwin object table line bounds')
        line = raw[offset:end]; offset = end+1
        if line==b'# Sections:':
            require(records, 'Darwin nonempty object table')
            return tuple(records)
        match = re.fullmatch(rb'\[ *([0-9]+)\] ([^\x00-\x1f]+)',line)
        require(match is not None, 'Darwin object table record')
        index, value = int(match[1]), match[2]
        require(index not in indices and len(records)<MAX_FILES, 'Darwin unique bounded object index')
        require(value==value.strip(), 'Darwin object path framing')
        indices.add(index); records.append(value)
    raise ValueError('Darwin object table Sections boundary')


def selected_overrides(raw, paths):
    records = darwin_object_records(raw)
    for path in paths:
        require(records.count(path.encode())==1, 'actual selected override object '+path)


def selected_members(raw, system, library):
    if system=='Darwin':
        expected = library.encode(); base = expected.rsplit(b'/',1)[-1]
        selected = []
        for value in darwin_object_records(raw):
            match = re.fullmatch(rb'(.+)\(([^()]+\.o)\)',value)
            if match and match[1].rsplit(b'/',1)[-1]==base:
                require(match[1]==expected, 'Darwin exact archive library path')
                member = match[2].decode(errors='strict')
                require(member not in selected, 'Darwin unique archive member')
                selected.append(member)
            else:
                require(base not in value, 'Darwin malformed archive member')
        return set(selected)
    text = raw.decode(errors='strict').replace('\\','/')
    library = library.replace('\\','/')
    base = library.rsplit('/',1)[-1]
    if system == 'Windows':
        pattern = r'(?i)(?:'+re.escape(base)+r'|'+re.escape(base.rsplit('.',1)[0])+r')(?::|\()([^\s()]+\.obj)\)?(?=\s|$)'
        return {match.group(1).rsplit('/',1)[-1] for match in re.finditer(pattern,text)}
    pattern = r'^'+re.escape(library)+r'\(([^()]+\.o)\)(?=\s|$)'
    return {match.group(1) for match in re.finditer(pattern,text,re.MULTILINE)}


def admit_capture(directory, **expected):
    require(bool(expected), 'strict current source/head/corpus/host context is required')
    fields(expected,['expected_head','canonical_sources','inputs','cases','expected_host'],'external strict admission context')
    return _admit_capture(directory, **expected)


def verify_archive(raw, listing, system, bindings, objects, sources):
    archive = decode_archive(raw)
    archive_listing(archive, listing, system)
    expected = {name for name in sources if name.endswith('.cpp') and
                name.startswith(tuple('recipes/bullet275/bullet-src/src/' + folder + '/' for folder in
                                      ('BulletCollision', 'BulletDynamics', 'LinearMath')))}
    require(type(bindings) is list and len(bindings) == len(expected), 'complete compiled native source bindings')
    require({b['source'] for b in bindings} == expected, 'exact compiled source closure')
    actual = {}
    for name, content in archive.payloads.items():
        base = name.replace('\\', '/').rsplit('/', 1)[-1]
        require(base not in actual, 'unique archive member basename')
        actual[base] = content
    require(set(actual) == set(objects), 'complete archive payload/object membership')
    for binding in bindings:
        fields(binding, ['source', 'source_sha256', 'object', 'object_sha256'], 'archive source/object binding')
        source, obj = binding['source'], binding['object']
        require(obj == source.rsplit('/',1)[-1].rsplit('.',1)[0] + ('.obj' if system == 'Windows' else '.o'),
                'exact compiled source/object stem binding')
        require(binding['source_sha256'] == digest(sources[source]), 'compiled source identity')
        require(obj in objects and binding['object_sha256'] == digest(objects[obj]), 'compiled object identity')
        require(actual[obj] == objects[obj], 'actual archive payload bytes equal compiled object')
    return archive


def validate_native_lifetimes(raw, inputs, *, observed):
    require(type(raw) is bytes and len(raw) <= 64 * 1024**2, 'bounded native lifetime chronology')
    commands = inputs.splitlines()
    live_allocations, registered, joints = {}, {}, {}
    last_sequence, last_row = 0, 0
    current_world = None
    closed = set()
    for line in raw.decode('ascii').splitlines():
        words = line.split(' ')
        require(all(words) and words[0] in {'ALLOC', 'BODY_REGISTER', 'JOINT_CREATE', 'PHYSICAL'}, 'known native lifetime event')
        require(len(words) >= 2 and words[1].isdigit(), 'native lifetime checkpoint')
        row = int(words[1])
        require(last_row <= row < len(commands), 'ordered native lifetime checkpoints')
        for index in range(last_row, row):
            if commands[index] == 'X':
                if not observed:
                    registered.clear()
                    joints.clear()
                require(not registered and not joints and (not observed or not live_allocations), 'closed native world ownership')
                closed.add(index)
        last_row = row
        op = commands[row].split()[0]
        if words[0] == 'ALLOC':
            require(observed and len(words) == 7 and all(x.isdigit() for x in words[2:]), 'native allocation event framing')
            sequence, alloc, pointer, size, alignment = map(int, words[2:])
            require(sequence == last_sequence + 1 and alloc in {0, 1}, 'exact allocation chronology')
            last_sequence = sequence
            if alloc:
                require(pointer > 0 and pointer not in live_allocations and size > 0 and alignment > 0
                        and alignment & (alignment - 1) == 0 and pointer % alignment == 0, 'live aligned native allocation')
                live_allocations[pointer] = (sequence, size, alignment)
            else:
                require(pointer in live_allocations and size == alignment == 0, 'release existing native allocation')
                del live_allocations[pointer]
        elif words[0] == 'BODY_REGISTER':
            require(len(words) == 4 and op in {'H', 'C'} and all(x.isdigit() for x in words[2:]), 'body registration event')
            owner, pointer = map(int, words[2:])
            if op == 'H':
                require(owner == 0 and not registered and not joints, 'ground first genuine registration')
                current_world = row
            require(current_world is not None and owner == len(registered) and pointer > 0
                    and pointer not in registered.values(), 'ordered unique body registration')
            registered[owner] = pointer
        elif words[0] == 'JOINT_CREATE':
            require(len(words) == 5 and op == 'J' and words[2].isdigit() and words[3].isdigit(), 'joint registration event')
            index, pointer, uid = map(int, words[2:])
            require(index == len(joints) and pointer > 0 and pointer not in joints.values(), 'ordered unique joint registration')
            require(uid == int(commands[row].split()[3]), 'genuine signed joint UID')
            joints[index] = pointer
        else:
            require(observed and len(words) == 5 and op == 'X', 'physical destruction event')
            kind, pointer, owner = words[2], int(words[3]), int(words[4])
            if kind == 'joint':
                require(joints and owner == -1 and pointer == joints[max(joints)], 'reverse physical joint destruction')
                del joints[max(joints)]
            else:
                require(kind == 'body' and not joints and registered and owner == max(registered)
                        and registered[owner] == pointer, 'reverse physical body destruction')
                del registered[owner]
    if observed:
        require(not registered and not joints and not live_allocations, 'complete native ownership and allocation closure')
    require(last_sequence > 0 if observed else last_sequence == 0, 'native allocator observation domain')
    return {'allocation_events': last_sequence, 'physical_closure': observed}


def policy(text):
    functions = {}
    for name, count in [('Intersect',2),('Select',3),('Merge',3)]:
        pattern = name + r'\s*\(\s*const\s+btDbvtAabbMm\s*&\s*\w+\s*,\s*const\s+btDbvtAabbMm\s*&\s*\w+'
        pattern += (r'\s*,[^)]+' if count == 3 else '') + r'\s*\)\s*\{'
        matches = list(re.finditer(pattern,text)); require(len(matches)==1,'one expanded DBVT '+name)
        start = matches[0].end()-1; end = start+1; depth = 1
        while depth and end<len(text):
            depth += (text[end]=='{')-(text[end]=='}'); end += 1
        require(depth==0,'complete expanded DBVT body'); functions[name]=text[start:end]
    if all(token in functions[name] for name,token in [('Intersect','_mm_cmplt_ps'),('Select','_mm_cmple_ss'),('Merge','_mm_min_ps')]):
        name = 'mmd-win64-sse'
    else:
        require(all('_mm_' not in body for body in functions.values()) and 'Proximity' in functions['Select'], 'known unmixed DBVT numeric policy')
        name = 'generic-reference'
    return {'policy':name,'functions':functions}




MACROS = ['BT_USE_SSE','BT_USE_DOUBLE_PRECISION','BT_NO_PROFILE','WIN32','_MSC_VER','_M_X64',
          '__x86_64__','__aarch64__','MDS_BT_SYSTEM_MATH','sinf','cosf','atan2f','pointer_bits','scalar_bytes']


def macro_source():
    text = '#include "LinearMath/btScalar.h"\n#include <cstdio>\n#define S_(x) #x\n#define S(x) S_(x)\nint main(){\n'
    for key in MACROS[:-2]:
        text += f'#ifdef {key}\nputs("{key}=" S({key}));\n#else\nputs("{key}=<undefined>");\n#endif\n'
    return (text+'printf("pointer_bits=%zu\\nscalar_bytes=%zu\\n",sizeof(void*)*8,sizeof(btScalar));}\n').encode()


def decode_json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'duplicate JSON key')
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON constant')))


def safe_name(name):
    require(type(name) is str and 0 < len(name) <= MAX_PATH and ':' not in name and '\\' not in name
            and not name.startswith('/') and all(part not in {'', '.', '..'} for part in name.split('/'))
            and not re.search(r'[\x00-\x1f<>"|?*]',name)
            and all(not part.endswith((' ', '.')) and not re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',part) for part in name.split('/')), 'safe capture path')
    return name


def inventory(expected, actual):
    require(type(expected) is dict and set(expected) == set(actual), 'exact capture inventory')
    require(len({safe_name(name).casefold() for name in expected}) == len(expected), 'capture case collision')
    for name, value in expected.items():
        require(identity(value) == actual[name], 'capture identity ' + name)


def json_value(raw):
    value = decode_json(raw)
    def finite(item, key=None):
        if type(item) is bool: require(key in {'timeout','normal_exit','full_schema','waited','streams_closed','full_trace','physical_closure'}, 'boolean in integer receipt field')
        elif isinstance(item, float): require(math.isfinite(item), 'finite JSON number')
        elif isinstance(item, dict):
            for name,child in item.items(): finite(child,name)
        elif isinstance(item, list):
            for child in item: finite(child,key)
    finite(value)
    return value


class Capture:
    def __init__(self, directory, overrides=None):
        self.directory, self.overrides = Path(directory), overrides or {}
        require(not self.directory.is_symlink(), 'capture root symlink forbidden')
        self.sizes = {}
        total = 0
        directory_count = 0
        for root, directories, files in os.walk(self.directory, followlinks=False):
            for name in directories:
                directory_count += 1
                require(directory_count<=MAX_FILES, 'capture directory bounds')
                safe_name((Path(root)/name).relative_to(self.directory).as_posix())
                require(stat.S_ISDIR((Path(root)/name).lstat().st_mode), 'capture directory symlink forbidden')
            for name in files:
                path = Path(root)/name
                info = path.lstat()
                require(stat.S_ISREG(info.st_mode), 'capture regular files only')
                relative = safe_name(path.relative_to(self.directory).as_posix())
                self.sizes[relative] = info.st_size
                total += info.st_size
                require(len(self.sizes) <= MAX_FILES and info.st_size <= MAX_FILE and total <= MAX_TOTAL, 'capture resource bounds')
        for name, raw in self.overrides.items():
            safe_name(name)
            require(type(raw) is bytes and len(raw) <= MAX_FILE, 'candidate byte bounds')
            total += len(raw) - self.sizes.get(name, 0)
            self.sizes[name] = len(raw)
        require(len(self.sizes) <= MAX_FILES and total <= MAX_TOTAL, 'candidate resource bounds')
        require(len({name.casefold() for name in self.sizes}) == len(self.sizes), 'capture case collision')

    def __iter__(self):
        return iter(self.sizes)

    def __getitem__(self, name):
        require(name in self.sizes, 'required capture file ' + name)
        if name in self.overrides: return self.overrides[name]
        path = self.directory/name
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_size == self.sizes[name], 'fixed regular capture file')
        with path.open('rb') as stream:
            raw = stream.read(self.sizes[name]+1)
        require(len(raw) == self.sizes[name], 'fixed bounded capture read')
        return raw


@dataclass(frozen=True)
class VerifiedCapture:
    """Carries the checked producer input and ordered output."""
    head: str
    inputs: str
    cases: tuple
    observed_trace: bytes
    report_sha256: str


@dataclass(frozen=True)
class CommandSpec:
    label: str
    argv: tuple
    cwd: str
    inputs: tuple
    outputs: tuple
    compile: bool = False
    corpus: bool = False
    generation: str = 'none'


def command_schedule(context, sources, libraries):
    """Exact current diagnostic command recipe. This is not capture admission."""
    from hooks import MUTANTS, NATIVE_OBSERVATIONS
    fields(context, ['schema', 'system', 'root', 'out', 'tools'], 'command recipe context')
    require(type(context['schema']) is int and context['schema'] == 1, 'command recipe schema')
    system = context['system']
    require(system in {'Windows', 'Darwin', 'Linux'}, 'command recipe supported system')
    path = PureWindowsPath if system == 'Windows' else PurePosixPath
    require(all(type(context[key]) is str and len(context[key]) <= MAX_PATH and path(context[key]).is_absolute()
                and '..' not in path(context[key]).parts for key in ['root', 'out']), 'command recipe absolute roots')
    root, out = path(context['root']), path(context['out'])
    require(root != out and root not in out.parents and out not in root.parents, 'command recipe disjoint roots')
    tools = context['tools']
    fields(tools, ['python', 'git', 'rustup', 'rustc', 'rust_linker', 'compiler', 'archiver', 'native_linker'], 'command recipe tools')
    require(all(type(value) is str and path(value).is_absolute() and len(value) <= MAX_PATH for value in tools.values()),
            'command recipe absolute tool invocations')
    require(type(sources) in {list, tuple} and len(sources) <= MAX_FILES and len(set(sources)) == len(sources), 'finite unique source recipe')
    require(all(safe_name(name).startswith('recipes/bullet275/bullet-src/src/') and name.endswith('.cpp') for name in sources),
            'native source recipe membership')
    require(type(libraries) in {list, tuple} and len(libraries) <= 64 and all(type(value) is str and 0 < len(value) <= MAX_PATH
            and '\x00' not in value for value in libraries), 'bounded native link libraries')
    win = system == 'Windows'
    suffix, extension = ('.exe', '.obj') if win else ('', '.o')
    result = []
    generation = 'none'
    def add(label, argv, inputs=(), outputs=(), compile=False, corpus=False, cwd=None):
        outputs = list(outputs)
        if win and (label in {'dedicated-build', 'pure-build', 'rust-observed-build'}
                    or label.startswith(('baseline-build-', 'mutant-build-'))):
            require(len(outputs) == 1 and path(outputs[0]).suffix == '.exe', 'one Windows Rust executable recipe')
            outputs.append(path(outputs[0]).with_suffix('.pdb'))
        result.append(CommandSpec(label, tuple(map(str, argv)), str(cwd or root / 'rust'),
                                  tuple(map(str, inputs)), tuple(map(str, outputs)), compile, corpus, generation))
    def flags(base):
        src, shim = base / 'recipes/bullet275/bullet-src/src', base / 'rust/crates/mds-bullet-sys/shim'
        return (['/nologo','/std:c++17','/O2','/MD','/EHsc','/fp:precise','/DBT_NO_PROFILE=1','/DWIN32','/showIncludes',
                 '/I'+str(src),'/I'+str(shim),'/FI'+str(shim/'det_math.h')] if win else
                ['-std=c++17','-O2','-ffp-contract=off','-fno-fast-math','-fdeclspec','-DBT_NO_PROFILE=1','-H',
                 '-I',shim/'sse_emu','-I',src,'-I',shim,'-include',shim/'det_math.h'])
    def compile_object(source, obj, label, base=root, extra=()):
        for name, output in [(label+'-discovery',obj.with_name('discovery-'+obj.name)),(label,obj)]:
            argv = ([tools['compiler'],*flags(base),*extra,'/c',source,'/Fo'+str(output)] if win else
                    [tools['compiler'],*flags(base),*extra,'-c',source,'-o',output])
            add(name,argv,[source],[output],compile=True)
    add('git-head',[tools['git'],'rev-parse','HEAD'],cwd=root)
    add('git-status',[tools['git'],'status','--porcelain=v1'],cwd=root)
    add('rustc-path',[tools['rustup'],'which','--toolchain','1.95.0','rustc'])
    add('rust-version',[tools['rustc'],'-Vv'])
    if not win:
        add('native-linker-path',[tools['compiler'],'-print-prog-name=ld'])
    rust = [tools['rustc'],'--edition=2021','-O','-C','linker='+tools['rust_linker']]
    crt_source = root / 'rust/crates/mds-crtmath/src/lib.rs'
    rlib = out / 'libmds_crtmath.rlib'
    crt = out / ('mds_crtmath.lib' if win else 'libmds_crtmath.a')
    add('crt-build',[*rust,'--crate-name','mds_crtmath','--crate-type','rlib,staticlib','--print','native-static-libs',crt_source,'--out-dir',out],[crt_source],[rlib,crt])
    rargs = [*rust,'--extern','mds_crtmath='+str(rlib)]
    dedicated = root / 'rust/crates/mds-bullet/tests/mmd_collision_world.rs'
    focused = out / ('dedicated'+suffix)
    add('dedicated-build',[*rargs,'--test','-D','warnings',dedicated,'-o',focused],[dedicated,rlib],[focused])
    add('dedicated-list',[focused,'--list','--format','terse'])
    add('dedicated-run',[focused,'mmd_world_'])
    pure_source, pure = root / 'rust/crates/mds-bullet/tests/pure_bullet.rs', out / ('pure'+suffix)
    add('pure-build',[*rargs,'--test','-D','warnings',pure_source,'-o',pure],[pure_source,rlib],[pure])
    add('pure-list',[pure,'--list','--format','terse'])
    add('pure-run',[pure])
    generation = 'shadow'
    shadow = out / 'generated'
    runner = shadow / 'tools/bullet-rust-mmd-collision-check/runner.rs'
    rust_exe = out / ('rust-mmd'+suffix)
    add('rust-observed-build',[*rargs,'--cfg','test',runner,'-o',rust_exe],[runner,rlib],[rust_exe])
    add('rust-observed-run',[rust_exe],corpus=True)
    objects = []
    for i, name in enumerate(sources):
        source = root / name
        obj = out / (source.stem+extension)
        compile_object(source,obj,f'compile-{i:03d}')
        objects.append(obj)
        if source.stem in {'btDbvt','btDbvtBroadphase'}:
            add('expanded-'+source.stem,[tools['compiler'],*flags(root),'/E' if win else '-E',source],[source])
    macro, macro_obj, macro_exe = out / 'effective-macros.cpp', out / ('effective-macros'+extension), out / ('effective-macros'+suffix)
    compile_object(macro,macro_obj,'macro-build')
    add('macro-link',[tools['compiler'],'/nologo','/MD',macro_obj,'/Fe'+str(macro_exe)] if win else
                    [tools['compiler'],macro_obj,'-fuse-ld='+tools['native_linker'],'-o',macro_exe],[macro_obj],[macro_exe])
    add('actual-macros',[macro_exe])
    archive = out / ('BulletMmd.lib' if win else 'libBulletMmd.a')
    add('archive-build',[tools['archiver'],'/NOLOGO','/OUT:'+str(archive),*objects] if win else
                        [tools['archiver'],'rcs',archive,*objects],objects,[archive])
    add('archive-list',[tools['archiver'],'/NOLOGO','/LIST',archive] if win else [tools['archiver'],'t',archive],[archive])
    header = root / 'tools/bullet-rust-mmd-collision-check/observer.h'
    hook_flags = ['/FI'+str(header),'/DDW_OBSERVED=1'] if win else ['-include',header,'-DDW_OBSERVED=1']
    overrides = []
    for i, name in enumerate(NATIVE_OBSERVATIONS):
        obj = out / ('observed-'+path(name).stem+extension)
        compile_object(shadow/name,obj,f'observed-object-{i}',shadow,hook_flags)
        overrides.append(obj)
    for name, base, extra, prefix in [('native',root,[],[]),('observed',shadow,hook_flags,overrides)]:
        source = base / 'tools/bullet-rust-mmd-collision-check/oracle.cpp'
        obj, exe, linkmap = out / (name+'-consumer'+extension), out / (name+suffix), out / (name+'.map')
        compile_object(source,obj,name+'-consumer-build',base,extra)
        argv = ([tools['compiler'],'/nologo','/MD','/EHsc',obj,*prefix,archive,crt,'/Fe'+str(exe),'/link','/MAP:'+str(linkmap),'/VERBOSE:LIB',*libraries] if win else
                [tools['compiler'],obj,*prefix,archive,crt,*libraries,'-fuse-ld='+tools['native_linker'],('-Wl,-map,' if system=='Darwin' else '-Wl,-Map,')+str(linkmap),'-o',exe])
        add(name+'-link',argv,[obj,*prefix,archive,crt],[exe,linkmap])
        add(name+'-run',[exe],corpus=True)
    for name in MUTANTS:
        target = out / 'mutants' / name
        entry = target / 'tools/bullet-rust-mmd-collision-check/runner.rs'
        baseline, mutant = out / ('baseline-'+name+suffix), out / ('mutant-'+name+suffix)
        generation = 'baseline-'+name
        add('baseline-build-'+name,[*rargs,'--cfg','test',entry,'-o',baseline],[entry,rlib],[baseline])
        add('baseline-run-'+name,[baseline],corpus=True)
        generation = 'mutant-'+name
        add('mutant-build-'+name,[*rargs,'--cfg','test',entry,'-o',mutant],[entry,rlib],[mutant])
        add('mutant-run-'+name,[mutant],corpus=True)
    require(len({entry.label for entry in result}) == len(result), 'unique complete command recipe')
    return tuple(result)


class _Memory:
    def __init__(self, files, name=''):
        self.files, self.name = files, name
    def __truediv__(self, name):
        return _Memory(self.files, self.name + ('/' if self.name else '') + str(name))
    def read_bytes(self):
        return self.files[self.name]
    def read_text(self):
        return self.read_bytes().decode().replace('\r\n', '\n')
    def write_bytes(self, raw):
        self.files[self.name] = raw


ACTUAL_PEERS = ['wrong-head','unclosed-command','boolean-pid','open-source','bad-executed-binary']


def _admit_capture(directory, *, expected_head, canonical_sources, inputs, cases, expected_host, require_actual_controls=True):
    from hooks import (MUTANTS, OWNER, OBSERVATION_PATHS, NATIVE_OBSERVATIONS, instrument, inverse, mutate)
    from trace import frames, common, validate_lifetimes, semantic_projection
    require(type(expected_head) is str and re.fullmatch('[0-9a-f]{40}', expected_head), 'external current HEAD')
    require(type(canonical_sources) is dict and canonical_sources and type(inputs) is str and type(cases) is list,
            'external current source and corpus context')
    capture = directory if isinstance(directory, Capture) else Capture(directory)
    names, used = set(capture), set()
    folded = {name.casefold(): name for name in names}
    def raw(name):
        safe_name(name)
        require(name.casefold() in folded, 'required capture member ' + name)
        name = folded[name.casefold()]
        used.add(name)
        return capture[name]
    def data(name):
        return json_value(raw(name))
    manifest = data('artifact-manifest.json')
    fields(manifest, names - {'artifact-manifest.json'}, 'closed artifact inventory')
    for name, value in manifest.items():
        require(sha_identity(value) == digest(raw(name)), 'closed artifact identity ' + name)
    # Inventory hashing does not make an unknown file a protocol member.
    used = {'artifact-manifest.json'}
    report = fields(data('report.json'), ['schema','status','base','base_tree','host','scope','pending','native_accelerator',
                    'head','cases','checkpoints','commands','mutant_definitions','compiled_controls'], 'native report')
    require(type(report['schema']) is int and report['schema'] == 1 and report['status'] in
            {'DIAGNOSTIC_EQUAL_UNADMITTED','CONTROLLED_PASS'}, 'completed native report schema')
    require(report['base'] == 'f6ab4feef335e76d590c3f8a9c5f532dec73ba70' and
            report['base_tree'] == '005ae1183e9972df56689796cf87589117418e7d' and report['head'] == expected_head,
            'fixed MMD base and current producer HEAD')
    host = fields(report['host'], ['system','machine'], 'actual native host')
    require(all(type(value) is str for value in host.values()) and
            (host['system'], host['machine'].lower()) in expected_host and
            (host['system'], host['machine'].lower()) in {('Windows','amd64'),('Windows','x86_64'),('Darwin','arm64'),
             ('Linux','x86_64'),('Linux','aarch64'),('Linux','arm64')}, 'allowed actual native host')
    require(type(report['pending']) is list and all(type(item) is str for item in report['pending']), 'typed pending gates')
    if require_actual_controls:
        require(report['status'] == 'CONTROLLED_PASS' and report['pending'] == [], 'final native admission state')
    require(report['scope'] == 'private MMD collision ownership' and
            report['native_accelerator'] == 'unchanged genuine constructor; Rust query and allocation parity excluded',
            'fixed collision-only boundary')
    for key, value in [('cases',len(cases)),('checkpoints',len(inputs.splitlines())),
                       ('mutant_definitions',len(MUTANTS)),('compiled_controls',len(MUTANTS))]:
        require(type(report[key]) is int and report[key] == value, 'derived complete native count ' + key)
    require(data('cases.json') == cases and raw('inputs.txt') == inputs.encode(), 'exact current finite corpus')
    start = data('source-start.json')
    fields(start, canonical_sources, 'exact current physical source closure')
    require(data('source-end.json') == start, 'source-before/end preservation')
    original = {}
    for name, value in start.items():
        content = raw('source/' + name)
        require(sha_identity(value) == digest(content) and content.replace(b'\r\n',b'\n') ==
                canonical_sources[name].replace(b'\r\n',b'\n'), 'current canonical source identity ' + name)
        if '/tests/' in name:
            require(content == canonical_sources[name], 'binary test checkout transport')
        original[name] = content
    memory = _Memory(dict(original))
    edits = instrument(memory, _Memory(original, 'tools/bullet-rust-mmd-collision-check'))
    inverse(memory, edits, {name: original[name] for name in OBSERVATION_PATHS})
    require(data('observation-edits.json') == edits, 'exact generated observation recipe and inverse')
    generated = memory.files
    generation = {'generated/' + name: digest(value) for name, value in generated.items()}
    require(data('generated-start.json') == generation and data('generated-end.json') == generation,
            'complete generated source-before/end closure')
    for name, value in generated.items():
        require(raw('generated/' + name) == value, 'exact generated source bytes ' + name)
    context = fields(data('producer.json'), ['schema','system','root','out','tools'], 'producer context')
    require(context['system'] == host['system'], 'producer/native host agreement')
    path = PureWindowsPath if host['system'] == 'Windows' else PurePosixPath
    root, out = path(context['root']), path(context['out'])
    settings = fields(data('environment-start.json'), ENVIRONMENT, 'named compiler settings')
    require(all(value is None or type(value) is str for value in settings.values()) and
            data('environment-end.json') == settings and not settings['CL'] and not settings['_CL_'] and
            settings['BULLET_ALLOC_LOG'] is None and settings['OPENMMD_DUMP_SPRING'] is None, 'preserved named compiler policy')
    tools = data('tools-start.json')
    require(type(tools) is dict and set(tools) == set(context['tools'].values()) and data('tools-end.json') == tools,
            'complete resolved tool start/end closure')
    for name, binding in tools.items():
        fields(binding, ['path','target','sha256'], 'resolved tool')
        require(name == binding['path'] and path(name).is_absolute() and path(binding['target']).is_absolute() and
                digest(raw('tool-bytes/' + sha_identity(binding['sha256']))) == binding['sha256'], 'retained resolved executable bytes')
    sources = sorted((name for name in start if name.endswith('.cpp') and name.startswith(tuple(
        'recipes/bullet275/bullet-src/src/' + folder + '/' for folder in ['BulletCollision','BulletDynamics','LinearMath']))), key=path)
    require(sources and len({path(name).stem.casefold() for name in sources}) == len(sources), 'complete unique current archive source recipe')
    win = host['system'] == 'Windows'
    extension, suffix = ('.obj','.exe') if win else ('.o','')
    libraries = (raw('crt-build.stderr').decode().split('native-static-libs:')[-1].splitlines()[0].split() if win else
                 [] if host['system'] == 'Darwin' else ['-ldl','-lpthread','-lm'])
    schedule = command_schedule(context, sources, libraries)
    commands = data('commands.json')
    require(type(commands) is list and len(commands) == len(schedule) and type(report['commands']) is int and
            report['commands'] == len(commands), 'complete exact command schedule')
    expected_mutants = {}
    for name in MUTANTS:
        changed = _Memory(dict(generated))
        mutation = mutate(changed, name)
        require(data('mutation-' + name + '.json') == mutation, 'exact compiled semantic mutation ' + name)
        expected_mutants[name] = changed.files
        for source, value in changed.files.items():
            require(raw('mutants/' + name + '/' + source) == value, 'exact compiled mutant source closure')
    def artifact(value, expected):
        target = path(value)
        require(target.is_absolute() and '..' not in target.parts, 'absolute direct command input')
        if target.is_relative_to(out):
            content = raw(target.relative_to(out).as_posix())
        elif target.is_relative_to(root):
            content = raw('source/' + target.relative_to(root).as_posix())
        else:
            content = raw('include-bytes/' + sha_identity(expected))
        require(digest(content) == expected, 'produced/pre-use/end input identity ' + value)
        return content
    include_aliases = {}
    for spec, command in zip(schedule, commands):
        fields(command, ['label','argv','cwd','executable','stdin_sha256','inputs_before','generated_before','outputs','pid',
                        'start_utc','end_utc','waited','streams_closed','returncode','seconds','stdout_sha256','stderr_sha256',
                        'inputs_end','executable_end','generated_end'], 'closed command receipt')
        require(command['label'] == spec.label and type(command['argv']) is list and tuple(command['argv']) == spec.argv and
                command['cwd'] == spec.cwd, 'exact command ownership/order/arguments')
        require(type(command['pid']) is int and command['pid'] > 0 and command['waited'] is True and command['streams_closed'] is True
                and type(command['returncode']) is int and command['returncode'] == 0, 'actual waited normally exiting command')
        require(type(command['seconds']) in {int,float} and math.isfinite(command['seconds']) and command['seconds'] >= 0,
                'finite command duration')
        begin, end = datetime.fromisoformat(command['start_utc']), datetime.fromisoformat(command['end_utc'])
        require(begin.utcoffset() == end.utcoffset() == timezone.utc.utcoffset(begin) and begin <= end, 'actual UTC command boundaries')
        require(command['stdin_sha256'] == (digest(inputs.encode()) if spec.corpus else None), 'exact command corpus input')
        for stream in ['stdout','stderr']:
            require(command[stream + '_sha256'] == digest(raw(spec.label + '.' + stream)), 'closed command stream identity')
        binding = fields(command['executable'], ['path','target','sha256'], 'executed tool binding')
        require(binding == command['executable_end'] and binding['path'] == spec.argv[0], 'executed executable before/end identity')
        if path(binding['path']).is_relative_to(out):
            require(binding['target'] == binding['path'], 'produced executable has no unrecorded indirection')
            artifact(binding['path'], binding['sha256'])
        else:
            require(binding == tools[binding['path']], 'executed resolved external tool')
        expected_generation = dict(generation) if spec.generation != 'none' else {}
        if spec.generation.startswith(('baseline-','mutant-')):
            prefix, name = spec.generation.split('-',1)
            source_map = generated if prefix == 'baseline' else expected_mutants[name]
            expected_generation.update({'mutants/' + name + '/' + source: digest(value) for source, value in source_map.items()})
        require(command['generated_before'] == command['generated_end'] == expected_generation, 'compiled generated-source pre-use/end identity')
        declared = list(spec.inputs)
        if spec.compile:
            receipt = fields(data(spec.label.removesuffix('-discovery') + '-include-bindings.json'),
                             ['schema','label','cwd','pre','post'], 'include binding receipt')
            base = spec.label.removesuffix('-discovery')
            require(type(receipt['schema']) is int and receipt['schema'] == 1 and receipt['label'] == base and receipt['cwd'] == spec.cwd,
                    'include receipt command ownership')
            pre, post = [], []
            for stage, key in [(base+'-discovery','pre'),(base,'post')]:
                occurrences = include_occurrences(raw(stage+'.stdout'),raw(stage+'.stderr'),host['system'])
                projection, aliases = include_projection(receipt[key],occurrences,host['system'])
                require(data(base+('-includes-pre.json' if key=='pre' else '-includes.json')) == projection, 'exact include projection')
                (pre if key == 'pre' else post).append(aliases)
                for item in receipt[key]:
                    content = artifact(item['target'],item['sha256'])
                    require(raw('include-bytes/'+item['sha256']) == content, 'retained actual include bytes')
                    alias = (spec.cwd,item['raw'])
                    pair = (item['target'],item['sha256'])
                    require(alias not in include_aliases or include_aliases[alias] == pair, 'temporal include alias preservation')
                    include_aliases[alias] = pair
            require(pre == post, 'discovery pre-use/measured include aliases preserved')
            if not spec.label.endswith('-discovery'):
                declared += [item['target'] for item in receipt['pre']]
        require(type(command['inputs_before']) is dict and set(command['inputs_before']) == set(declared) and
                command['inputs_end'] == command['inputs_before'], 'exact direct input roles and preservation')
        for value, identity_value in command['inputs_before'].items():
            artifact(value,sha_identity(identity_value))
        require(type(command['outputs']) is dict and set(command['outputs']) == set(spec.outputs), 'exact produced artifact roles')
        for value, identity_value in command['outputs'].items():
            artifact(value,sha_identity(identity_value))
    require(raw('git-head.stdout').decode().strip() == expected_head and not raw('git-status.stdout').strip(), 'actual clean producer HEAD')
    require(raw('rustc-path.stdout').decode().strip() == context['tools']['rustc'] and
            b'release: 1.95.0\n' in raw('rust-version.stdout').replace(b'\r\n',b'\n'), 'actual pinned compiler binding')
    endings = fields(data('native-include-bindings-end.json'), ['schema','bindings'], 'include end receipt')
    require(type(endings['schema']) is int and endings['schema'] == 1 and type(endings['bindings']) is list, 'include end framing')
    aliases = {}
    for item in endings['bindings']:
        fields(item, ['cwd','raw','target','sha256'], 'include end alias')
        key = (item['cwd'],item['raw'])
        require(key not in aliases, 'unique end include alias')
        aliases[key] = (item['target'],sha_identity(item['sha256']))
    require(aliases == include_aliases, 'closed complete include end resolution')
    require(raw('effective-macros.cpp') == macro_source(), 'exact native macro source')
    macro_lines = raw('actual-macros.stdout').decode().splitlines()
    require(len(macro_lines) == len(MACROS) and [line.split('=',1)[0] for line in macro_lines] == MACROS, 'complete exact ABI macro keys')
    macros = dict(line.split('=',1) for line in macro_lines)
    require(all(macros[key] == value for key,value in {'pointer_bits':'64','scalar_bytes':'4','MDS_BT_SYSTEM_MATH':'<undefined>',
                'sinf':'mds_crt_sinf','cosf':'mds_crt_cosf','atan2f':'mds_crt_atan2f','BT_NO_PROFILE':'1',
                'BT_USE_DOUBLE_PRECISION':'<undefined>'}.items()), 'actual deterministic native ABI policy')
    require(macros['BT_USE_SSE'] == '' and (macros['WIN32'] != '<undefined>') == win and
            (macros['_MSC_VER'] != '<undefined>') == win, 'actual platform macro policy')
    if win:
        require(macros['WIN32'] == '1' and macros['_M_X64'] == '100' and macros['__aarch64__'] == '<undefined>', 'actual MSVC x64 ABI')
    else:
        architecture = '__x86_64__' if host['machine'].lower() == 'x86_64' else '__aarch64__'
        require(macros[architecture] == '1' and macros['_M_X64'] == '<undefined>', 'actual generic architecture ABI')
        require(path(raw('native-linker-path.stdout').decode().strip()).name == path(context['tools']['native_linker']).name,
                'actual compiler-selected native linker binding')
    for stem in ['btDbvt','btDbvtBroadphase']:
        observed = policy(raw('expanded-'+stem+'.stdout').decode())
        require(data('policy-'+stem+'.json') == observed and observed['policy'] == ('mmd-win64-sse' if win else 'generic-reference'),
                'actual compiled native archive policy')
    archive_name = 'BulletMmd.lib' if win else 'libBulletMmd.a'
    objects = {path(name).stem+extension:raw(path(name).stem+extension) for name in sources}
    archive = verify_archive(raw(archive_name),raw('archive-list.stdout').decode().splitlines(),host['system'],
                             data('archive-bindings.json'),objects,original)
    require(data('archive-payload-identities.json') == {name:digest(value) for name,value in archive.payloads.items()}, 'archive payload inventory')
    for name,value in archive.payloads.items():
        require(raw('archive-payloads/'+name.replace('\\','/').rsplit('/',1)[-1]) == value, 'actual archive member bytes')
    for label in ['native','observed']:
        link = raw(label+'.map')
        if host['system'] != 'Darwin':
            link += b'\n'+raw(label+'-link.stdout')+b'\n'+raw(label+'-link.stderr')
        selected = selected_members(link,host['system'],str(out/archive_name))
        require(selected and selected <= set(objects) and data(label+'-link-selection.json') == sorted(selected), 'actual linked native archive membership')
        if label == 'observed' and host['system'] == 'Darwin':
            selected_overrides(link,[str(out/('observed-'+path(name).stem+extension)) for name in NATIVE_OBSERVATIONS])
        summary = validate_native_lifetimes(raw(label+'-run.stderr').replace(b'\r\n',b'\n'),inputs,observed=label=='observed')
        require(data(label+'-lifetime-summary.json') == summary, 'complete native allocator/physical lifetime facts')
    native = frames(raw('native-run.stdout'),inputs,observed=False)
    observed = frames(raw('observed-run.stdout'),inputs)
    rust = frames(raw('rust-observed-run.stdout'),inputs)
    require(common(native) == common(observed) and observed == rust, 'genuine noninterference and ordered complete Rust/native equality')
    require(data('rust-lifetimes.json') == validate_lifetimes(rust) and
            data('observed-trace-lifetimes.json') == validate_lifetimes(observed), 'independent algorithm/manifold lifetime closure')
    controls = fields(data('semantic-controls.json'), MUTANTS, 'complete compiled controls')
    for name, (_,_,_,field) in MUTANTS.items():
        clean = frames(raw('baseline-run-'+name+'.stdout'),inputs)
        mutated = frames(raw('mutant-run-'+name+'.stdout'),inputs)
        validate_lifetimes(clean); validate_lifetimes(mutated)
        require(clean == rust, 'complete same-host clean baseline')
        different = [i for i,(a,b) in enumerate(zip(clean,mutated)) if a != b]
        directed = [i for i,(a,b) in enumerate(zip(clean,mutated)) if semantic_projection(a,field) != semantic_projection(b,field)]
        require(different and directed, 'normally exiting full-trace directed semantic rejection')
        expected = {'field':field,'different_rows':different,'semantic_rows':directed,
                    'baseline_binary_sha256':digest(raw('baseline-'+name+suffix)),
                    'mutant_binary_sha256':digest(raw('mutant-'+name+suffix)),'normal_exit':True,'full_trace':True}
        require(controls[name] == expected and controls[name]['normal_exit'] is True and controls[name]['full_trace'] is True,
                'actual compiled directed control receipt')
    for label,prefix in [('dedicated','mmd_world_'),('pure','')]:
        listed = raw(label+'-list.stdout').decode().splitlines()
        count = sum(line.endswith(': test') and line.startswith(prefix) for line in listed)
        log = raw(label+'-run.stdout').decode()
        require(count > 0 and f'test result: ok. {count} passed; 0 failed; 0 ignored;' in log, 'complete listed real Rust behavior suite')
    if require_actual_controls or 'actual-capture-controls.json' in names:
        controls = fields(data('actual-capture-controls.json'), ['schema','domain','legal_actual_report_sha256','rejected'], 'actual malformed-peer controls')
        require(type(controls['schema']) is int and controls['schema'] == 1 and controls['domain'] == 'actual-capture-malformed-peers'
                and controls['legal_actual_report_sha256'] == digest(raw('report.json')) and controls['rejected'] == ACTUAL_PEERS,
                'legal actual capture precedes complete malformed-peer refusals')
    require(used == names, 'closed capture protocol membership: '+str(sorted(names-used)[:5]))
    return VerifiedCapture(expected_head,inputs,tuple(cases),raw('observed-run.stdout'),digest(raw('report.json')))


def candidate_capture(capture, overrides):
    require(isinstance(capture, Capture) and type(overrides) is dict, 'bounded current actual capture candidate')
    changes = {**capture.overrides, **overrides}
    view = Capture(capture.directory, changes)
    inventory = {name:digest(view[name]) for name in view if name != 'artifact-manifest.json'}
    changes['artifact-manifest.json'] = (json.dumps(inventory,indent=2,sort_keys=True)+'\n').encode()
    return Capture(capture.directory, changes)


def actual_peer_controls(capture, **expected):
    # The positive uses actual compiled capture bytes, never a synthetic PID/binary fixture.
    proof = _admit_capture(capture, **expected, require_actual_controls=False)
    rejected = []
    for name in ACTUAL_PEERS:
        overrides = {}
        if name == 'wrong-head':
            value = json_value(capture['report.json']); value['head'] = '0'*40
            overrides['report.json'] = (json.dumps(value,sort_keys=True)+'\n').encode()
        elif name in {'unclosed-command','boolean-pid'}:
            value = json_value(capture['commands.json'])
            value[0]['streams_closed' if name == 'unclosed-command' else 'pid'] = False if name == 'unclosed-command' else True
            overrides['commands.json'] = (json.dumps(value,sort_keys=True)+'\n').encode()
        elif name == 'open-source':
            value = json_value(capture['source-end.json']); value[next(iter(value))] = '0'*64
            overrides['source-end.json'] = (json.dumps(value,sort_keys=True)+'\n').encode()
        else:
            report = json_value(capture['report.json'])
            executable = 'rust-mmd.exe' if report['host']['system'] == 'Windows' else 'rust-mmd'
            raw = capture[executable]
            require(raw, 'nonempty actual executable')
            overrides[executable] = bytes([raw[0]^1])+raw[1:]
        peer = candidate_capture(capture,overrides)
        try:
            _admit_capture(peer, **expected, require_actual_controls=False)
        except ValueError:
            rejected.append(name)
        else:
            raise ValueError('malformed actual peer admitted: '+name)
    require(rejected == ACTUAL_PEERS, 'complete observed actual-peer rejection list')
    return {'schema':1,'domain':'actual-capture-malformed-peers','legal_actual_report_sha256':proof.report_sha256,'rejected':rejected}


def _admit_replay(directory, producer, *, expected_head, canonical_sources, require_pass=True):
    from hooks import MUTANTS, OBSERVATION_PATHS, instrument, inverse, mutate
    from trace import frames, validate_lifetimes, semantic_projection
    require(isinstance(producer, VerifiedCapture) and producer.head == expected_head, 'admitted same-HEAD Windows producer')
    capture = Capture(directory)
    names, used = set(capture), set()
    def raw(name):
        safe_name(name); require(name in names, 'required replay member '+name)
        used.add(name); return capture[name]
    def data(name): return json_value(raw(name))
    manifest = fields(data('artifact-manifest.json'),names-{'artifact-manifest.json'},'closed replay inventory')
    for name,value in manifest.items(): require(sha_identity(value) == digest(raw(name)), 'replay artifact identity')
    used = {'artifact-manifest.json'}
    report = fields(data('report.json'),['schema','status','pending','base','base_tree','host','head','producer_report_sha256',
                    'cases','checkpoints','commands','compiled_controls'],'replay report')
    require(type(report['schema']) is int and report['schema'] == 1 and report['status'] in {'REPLAY_UNADMITTED','CONTROLLED_PASS'}
            and report['base'] == 'f6ab4feef335e76d590c3f8a9c5f532dec73ba70' and
            report['base_tree'] == '005ae1183e9972df56689796cf87589117418e7d' and report['head'] == expected_head
            and report['producer_report_sha256'] == producer.report_sha256, 'bound complete current replay')
    require(type(report['pending']) is list and all(type(item) is str for item in report['pending']), 'typed replay pending gates')
    if require_pass:
        require(report['status'] == 'CONTROLLED_PASS' and report['pending'] == [], 'final replay admission state')
    host = fields(report['host'],['system','machine'],'replay host')
    require((host['system'],host['machine'].lower()) in {('Windows','amd64'),('Windows','x86_64'),('Darwin','arm64'),
            ('Linux','x86_64'),('Linux','aarch64'),('Linux','arm64')},'supported replay host')
    inputs,cases = producer.inputs,list(producer.cases)
    require(raw('inputs.txt') == inputs.encode() and data('cases.json') == cases,'same admitted finite Windows corpus')
    for key,value in [('cases',len(cases)),('checkpoints',len(inputs.splitlines())),('compiled_controls',len(MUTANTS))]:
        require(type(report[key]) is int and report[key] == value,'derived full replay count')
    start = fields(data('source-start.json'),canonical_sources,'replay source closure')
    require(data('source-end.json') == start,'replay source-before/end preservation')
    original = {}
    for name,value in start.items():
        content = raw('source/'+name)
        require(digest(content) == sha_identity(value) and content.replace(b'\r\n',b'\n') ==
                canonical_sources[name].replace(b'\r\n',b'\n'),'current replay canonical source')
        if '/tests/' in name: require(content == canonical_sources[name],'binary replay test transport')
        original[name] = content
    memory = _Memory(dict(original)); edits = instrument(memory,_Memory(original,'tools/bullet-rust-mmd-collision-check'))
    inverse(memory,edits,{name:original[name] for name in OBSERVATION_PATHS})
    require(data('observation-edits.json') == edits,'exact replay observation inverse')
    generated = memory.files
    generation = {'generated/'+name:digest(value) for name,value in generated.items()}
    require(data('generated-start.json') == data('generated-end.json') == generation,'replay generated source closure')
    for name,value in generated.items(): require(raw('generated/'+name) == value,'actual replay generated bytes')
    context = fields(data('replay-producer.json'),['schema','system','root','out','tools'],'replay context')
    require(type(context['schema']) is int and context['schema'] == 1 and context['system'] == host['system'],'replay context host')
    path = PureWindowsPath if host['system'] == 'Windows' else PurePosixPath
    root,out = path(context['root']),path(context['out'])
    require(root.is_absolute() and out.is_absolute() and root != out and root not in out.parents and out not in root.parents,'disjoint replay roots')
    fields(context['tools'],['git','rustup','rustc','rust_linker'],'replay tools')
    tools = data('tools-start.json')
    require(type(tools) is dict and set(tools) == set(context['tools'].values()) and data('tools-end.json') == tools,'replay resolved tool closure')
    for name,binding in tools.items():
        fields(binding,['path','target','sha256'],'replay resolved tool')
        require(name == binding['path'] and path(name).is_absolute() and path(binding['target']).is_absolute()
                and digest(raw('tool-bytes/'+sha_identity(binding['sha256']))) == binding['sha256'],'retained replay tool bytes')
    settings = fields(data('environment-start.json'),ENVIRONMENT,'replay named settings')
    require(data('environment-end.json') == settings and all(value is None or type(value) is str for value in settings.values()),'replay setting preservation')
    suffix = '.exe' if host['system'] == 'Windows' else ''
    rust = [context['tools']['rustc'],'--edition=2021','-O','-C','linker='+context['tools']['rust_linker']]
    rlib,source = out/'libmds_crtmath.rlib',root/'rust/crates/mds-crtmath/src/lib.rs'
    rargs = [*rust,'--extern','mds_crtmath='+str(rlib)]
    recipe = []
    def add(label,argv,declared=(),outputs=(),generation='none',corpus=False,cwd=None):
        outputs = list(outputs)
        if suffix and (label == 'rust-observed-build' or label.startswith(('baseline-build-','mutant-build-'))):
            outputs.append(path(outputs[0]).with_suffix('.pdb'))
        recipe.append((label,list(map(str,argv)),str(cwd or root/'rust'),list(map(str,declared)),list(map(str,outputs)),generation,corpus))
    add('git-head',[context['tools']['git'],'rev-parse','HEAD'],cwd=root)
    add('git-status',[context['tools']['git'],'status','--porcelain=v1'],cwd=root)
    add('rustc-path',[context['tools']['rustup'],'which','--toolchain','1.95.0','rustc'])
    add('rust-version',[context['tools']['rustc'],'-Vv'])
    add('crt-build',[*rust,'--crate-name','mds_crtmath','--crate-type','rlib',source,'--out-dir',out],[source],[rlib])
    entry = out/'generated/tools/bullet-rust-mmd-collision-check/runner.rs'; executable = out/('rust-mmd'+suffix)
    add('rust-observed-build',[*rargs,'--cfg','test',entry,'-o',executable],[entry,rlib],[executable],'shadow')
    add('rust-observed-run',[executable],generation='shadow',corpus=True)
    mutated_sources = {}
    for name in MUTANTS:
        memory = _Memory(dict(generated)); mutation = mutate(memory,name); mutated_sources[name] = memory.files
        require(data('mutation-'+name+'.json') == mutation,'exact replay compiled mutation')
        for file,value in memory.files.items(): require(raw('mutants/'+name+'/'+file) == value,'actual replay mutant source')
        entry = out/'mutants'/name/'tools/bullet-rust-mmd-collision-check/runner.rs'
        for prefix in ['baseline','mutant']:
            exe = out/(prefix+'-'+name+suffix); gen = prefix+'-'+name
            add(prefix+'-build-'+name,[*rargs,'--cfg','test',entry,'-o',exe],[entry,rlib],[exe],gen)
            add(prefix+'-run-'+name,[exe],generation=gen,corpus=True)
    commands = data('commands.json')
    require(type(commands) is list and len(commands) == len(recipe) and type(report['commands']) is int and report['commands'] == len(recipe),'complete replay command schedule')
    def artifact(value,identity_value):
        target = path(value)
        require(target.is_absolute() and '..' not in target.parts,'absolute replay artifact input')
        relative = target.relative_to(out).as_posix() if target.is_relative_to(out) else 'source/'+target.relative_to(root).as_posix()
        require(digest(raw(relative)) == sha_identity(identity_value),'replay produced/pre-use/end identity')
    for (label,argv,cwd,declared,outputs,gen,corpus),command in zip(recipe,commands):
        fields(command,['label','argv','cwd','executable','stdin_sha256','inputs_before','generated_before','outputs','pid','start_utc','end_utc',
                        'waited','streams_closed','returncode','seconds','stdout_sha256','stderr_sha256','inputs_end','executable_end','generated_end'],'closed replay command')
        require(command['label'] == label and command['argv'] == argv and command['cwd'] == cwd,'exact replay command ownership')
        require(type(command['pid']) is int and command['pid'] > 0 and command['waited'] is True and command['streams_closed'] is True
                and type(command['returncode']) is int and command['returncode'] == 0,'actual normally exiting closed replay command')
        begin,end = datetime.fromisoformat(command['start_utc']),datetime.fromisoformat(command['end_utc'])
        require(begin.utcoffset() == end.utcoffset() == timezone.utc.utcoffset(begin) and begin <= end and
                type(command['seconds']) in {int,float} and math.isfinite(command['seconds']) and command['seconds'] >= 0,'finite UTC replay boundaries')
        require(command['stdin_sha256'] == (digest(inputs.encode()) if corpus else None),'exact replay corpus stdin')
        for stream in ['stdout','stderr']: require(command[stream+'_sha256'] == digest(raw(label+'.'+stream)),'closed replay stream identity')
        binding = fields(command['executable'],['path','target','sha256'],'replay executed binary')
        require(binding['path'] == argv[0] and command['executable_end'] == binding,'replay executed binary start/end')
        if path(binding['path']).is_relative_to(out):
            require(binding['path'] == binding['target'],'replay binary indirection'); artifact(binding['path'],binding['sha256'])
        else: require(binding == tools[binding['path']],'replay external executable binding')
        expected = dict(generation) if gen != 'none' else {}
        if gen.startswith(('baseline-','mutant-')):
            prefix,name = gen.split('-',1); values = generated if prefix == 'baseline' else mutated_sources[name]
            expected.update({'mutants/'+name+'/'+file:digest(value) for file,value in values.items()})
        require(command['generated_before'] == command['generated_end'] == expected,'replay generated pre-use/end source')
        require(type(command['inputs_before']) is dict and set(command['inputs_before']) == set(declared) and command['inputs_end'] == command['inputs_before'],'replay direct input closure')
        for value,identity_value in command['inputs_before'].items(): artifact(value,identity_value)
        require(type(command['outputs']) is dict and set(command['outputs']) == set(outputs),'replay produced artifact roles')
        for value,identity_value in command['outputs'].items(): artifact(value,identity_value)
    require(raw('git-head.stdout').decode().strip() == expected_head and not raw('git-status.stdout').strip(),'actual clean replay HEAD')
    require(raw('rustc-path.stdout').decode().strip() == context['tools']['rustc'] and b'release: 1.95.0\n' in raw('rust-version.stdout').replace(b'\r\n',b'\n'),'actual pinned replay compiler')
    actual = frames(raw('rust-observed-run.stdout'),inputs); validate_lifetimes(actual)
    require(actual == frames(producer.observed_trace,inputs),'every actual Windows-source checkpoint and raw word replayed')
    controls = fields(data('semantic-controls.json'),MUTANTS,'complete replay semantic controls')
    for name,(_,_,_,field) in MUTANTS.items():
        clean,changed = frames(raw('baseline-run-'+name+'.stdout'),inputs),frames(raw('mutant-run-'+name+'.stdout'),inputs)
        validate_lifetimes(clean); validate_lifetimes(changed)
        require(clean == actual,'complete same-host clean replay control')
        differences = [i for i,(a,b) in enumerate(zip(clean,changed)) if a != b]
        directed = [i for i,(a,b) in enumerate(zip(clean,changed)) if semantic_projection(a,field) != semantic_projection(b,field)]
        require(differences and directed,'normally exiting directed replay semantic control')
        require(controls[name] == {'field':field,'different_rows':differences,'semantic_rows':directed,
                'baseline_binary_sha256':digest(raw('baseline-'+name+suffix)),
                'mutant_binary_sha256':digest(raw('mutant-'+name+suffix)),'normal_exit':True,'full_trace':True},'actual replay control receipt')
        require(controls[name]['normal_exit'] is True and controls[name]['full_trace'] is True,'typed replay control flags')
    require(used == names,'closed complete replay protocol membership: '+str(sorted(names-used)[:5]))
    return {'head':expected_head,'producer_report_sha256':producer.report_sha256,'checkpoints':len(actual),'compiled_controls':len(controls)}


def admit_replay(directory, producer, *, expected_head, canonical_sources):
    return _admit_replay(directory,producer,expected_head=expected_head,canonical_sources=canonical_sources)
