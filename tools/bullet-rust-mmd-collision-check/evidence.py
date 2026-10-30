"""Diagnostic command custody. This module does not admit native captures."""
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

    def run(self, label, argv, *, cwd, data=None, inputs=(), outputs=()):
        require(label and all(c in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in label), 'command label')
        require(not any(record['label'] == label for record in self.commands), 'unique command label')
        require(self.snapshot() == self.sources, 'fixed sources before ' + label)
        require({key: os.environ.get(key) for key in ENVIRONMENT} == self.environment, 'named settings preserved before command')
        binding = identity(argv[0])
        if not Path(binding['path']).is_relative_to(self.out):
            require(binding['path'] not in self.tools or self.tools[binding['path']] == binding, 'fixed external tool identity')
            self.tools[binding['path']] = binding
            retained = self.out / 'tool-bytes' / binding['sha256']
            retained.parent.mkdir(exist_ok=True)
            if not retained.exists():
                retained.write_bytes(Path(binding['target']).read_bytes())
            save(self.out / 'tools-start.json', self.tools)
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


def admit_capture(*args, **kwargs):
    raise ValueError('MMD strict actual-capture admission is not implemented; diagnostic captures are UNADMITTED')


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
    """Only the unfinished strict admit_capture boundary may construct this value."""
    head: str
    inputs: str
    cases: tuple
    observed_trace: bytes
    report_sha256: str
