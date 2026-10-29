from collections import Counter
from dataclasses import dataclass
import hashlib
import math
import ntpath
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat

from hooks import CORE, NATIVE, OWNER, SHIM, MUTANTS, OBSERVATION_PATHS, NATIVE_OBSERVATIONS, instrument, inverse, mutate, require
from trace import validate_noninterference, bind_inputs, comparison, validate, validate_allocator, validate_physical, decode_json

BASE = 'c8dc8a387a9d37442a84dbd8a3b81c90898b6d6d'
MODES = ['ascending', 'descending', 'alternating', 'ordinary']
LIMITS = ['finite allocator/corpus order only', 'debug drawer null', 'native physical deletes separate',
          'no public backend or solver/CCD/MMD adoption', 'discovery includes acquired after discovery and before measured compilation; no compiler-read attestation',
          'resolved tools and named settings only; no full compiler/OS/environment attestation',
          'Rust linker driver and native linker identity recorded; inner subprocess chain unobserved',
          'generated node provenance is not direct original-binary type observation',
          'ordinary mode has no raw allocator callback corroboration']
ENVIRONMENT = ['CL', '_CL_', 'INCLUDE', 'LIB', 'LIBPATH', 'CXX', 'CC', 'LD', 'AR', 'SDKROOT',
               'MACOSX_DEPLOYMENT_TARGET', 'CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'RUSTFLAGS',
               'CARGO_ENCODED_RUSTFLAGS', 'RUSTUP_TOOLCHAIN']
MAX_FILES, MAX_FILE, MAX_TOTAL, MAX_PATH = 24000, 512 * 1024**2, 4 * 1024**3, 1024
TOUCHED = OBSERVATION_PATHS
MACROS = ['BT_USE_SSE','BT_USE_DOUBLE_PRECISION','BT_NO_PROFILE','WIN32','_MSC_VER','_M_X64',
          '__x86_64__','__aarch64__','MDS_BT_SYSTEM_MATH','sinf','cosf','atan2f','pointer_bits','scalar_bytes']


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fields(value, names, message):
    require(type(value) is dict and set(value) == set(names), message + ' fields')
    return value


def identity(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None, 'digest framing')
    return value


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
        if type(item) is bool: require(key in {'timeout','normal_exit','full_schema'}, 'boolean in integer receipt field')
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


class _Memory:
    def __init__(self, files, name=''):
        self.files, self.name = files, name
    def __truediv__(self, name):
        return _Memory(self.files, self.name + ('/' if self.name else '') + str(name))
    def read_bytes(self): return self.files[self.name]
    def read_text(self): return self.read_bytes().decode().replace('\r\n', '\n')
    def write_bytes(self, raw): self.files[self.name] = raw


def generated_sources(originals, fixtures):
    memory = _Memory(dict(originals))
    changes = instrument(memory, _Memory(fixtures))
    inverse(memory, changes, originals)
    return memory.files, changes


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


def native_flags(system, root):
    path = PureWindowsPath if system == 'Windows' else PurePosixPath
    src, shim = path(root)/'recipes/bullet275/bullet-src/src', path(root)/'rust/crates/mds-bullet-sys/shim'
    return list(map(str, ['/nologo','/std:c++17','/O2','/MD','/EHsc','/fp:precise','/DBT_NO_PROFILE=1','/DWIN32','/showIncludes','/I'+str(src),'/I'+str(shim),'/FI'+str(shim/'det_math.h')] if system == 'Windows' else ['-std=c++17','-O2','-ffp-contract=off','-fno-fast-math','-fdeclspec','-DBT_NO_PROFILE=1','-H','-I',shim/'sse_emu','-I',src,'-I',shim,'-include',shim/'det_math.h']))


def macro_source():
    text = '#include "LinearMath/btScalar.h"\n#include <cstdio>\n#define S_(x) #x\n#define S(x) S_(x)\nint main(){\n'
    for key in MACROS[:-2]:
        text += f'#ifdef {key}\nputs("{key}=" S({key}));\n#else\nputs("{key}=<undefined>");\n#endif\n'
    return (text+'printf("pointer_bits=%zu\\nscalar_bytes=%zu\\n",sizeof(void*)*8,sizeof(btScalar));}\n').encode()


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
        target = binding['target']; raw = binding['raw']; value = identity(binding['sha256'])
        require(type(raw) is str and 0<len(raw)<=MAX_PATH and '\x00' not in raw, 'include raw spelling')
        require(type(target) is str and path(target).is_absolute() and '..' not in path(target).parts and len(target)<=MAX_PATH, 'resolved include absolute target')
        require(target==(ntpath.normcase(str(path(target))) if system=='Windows' else str(path(target))), 'canonical resolved include target')
        require(target not in manifest or manifest[target]==value, 'consistent include target bytes')
        require(raw not in aliases or aliases[raw]==(target,value), 'consistent include alias binding')
        manifest[target]=value; aliases[raw]=(target,value)
    return manifest, aliases


def include_evidence(data, raw, schedule, context, names):
    system=context['system']; win=system=='Windows'
    path=PureWindowsPath if win else PurePosixPath
    root,out=path(context['root']),path(context['out'])
    def canonical(value):
        return ntpath.normcase(str(path(value))) if win else str(path(value))
    def source(value):
        target=path(value)
        for base,prefix in [(out/'generated','generated/'),(root,'source/')]:
            if target.is_relative_to(base):return prefix+target.relative_to(base).as_posix()
        return None
    retained={canonical(name):name for name in names}
    dependencies, aliases = {}, {}
    for label,argv,cwd,input_name,produced,compile in schedule:
        if not compile:continue
        receipt=fields(data(label+'-include-bindings.json'),['schema','label','cwd','pre','post'],'include receipt')
        require(type(receipt['schema']) is int and receipt['schema']==1 and receipt['label']==label and receipt['cwd']==cwd, 'include receipt schema/label/cwd')
        projections=[]
        for stage,key,suffix in [(label+'-discovery','pre','-includes-pre.json'),(label,'post','-includes.json')]:
            occurrences=include_occurrences(raw(stage+'.stdout'),raw(stage+'.stderr'),system)
            manifest,bound=include_projection(receipt[key],occurrences,system)
            require(data(label+suffix)==manifest, 'canonical include binding projection '+stage)
            projections.append(bound)
            for binding in receipt[key]:
                target,value=binding['target'],binding['sha256']
                content=raw('include-bytes/'+value)
                require(digest(content)==value, 'retained include content '+label)
                source_name=source(target)
                if source_name is not None:
                    match=retained.get(canonical(source_name))
                    require(match is not None and raw(match)==content, 'source/generated include binding '+target)
                raw_source=source(binding['raw']) if path(binding['raw']).is_absolute() else None
                if raw_source is not None and canonical(raw_source) in retained:
                    require(canonical(binding['raw'])==target and raw(retained[canonical(raw_source)])==content, 'raw source/generated include ownership')
                require(target not in dependencies or dependencies[target]==value, 'consistent include dependency identity')
                dependencies[target]=value
            for spelling,binding in bound.items():
                alias=(cwd,spelling)
                require(alias not in aliases or aliases[alias]==binding, 'consistent temporal include alias')
                aliases[alias]=binding
        require(projections[0]==projections[1], 'discovery pre-use and measured include aliases preserved '+label)
    ending=fields(data('native-include-bindings-end.json'),['schema','bindings'],'include end receipt')
    require(type(ending['schema']) is int and ending['schema']==1 and type(ending['bindings']) is list, 'include end schema')
    actual={}
    for entry in ending['bindings']:
        fields(entry,['cwd','raw','target','sha256'],'include end binding')
        require(all(type(entry[key]) is str for key in entry), 'include end scalar fields')
        alias=(entry['cwd'],entry['raw'])
        require(alias not in actual, 'unique include end alias')
        actual[alias]=(entry['target'],identity(entry['sha256']))
    require(actual==aliases, 'complete original alias end resolution/bytes')
    require(data('native-includes-end.json')==dependencies, 'complete native include end union')


def source_attributes(name, sources):
    result={'text':'unspecified','eol':'unspecified'}
    for attribute_file in sorted((key for key in sources if key=='.gitattributes' or key.endswith('/.gitattributes')),key=lambda key:key.count('/')):
        base=attribute_file.rpartition('/')[0]
        if base and not name.startswith(base+'/'):continue
        relative=name[len(base)+1:] if base else name
        for line in sources[attribute_file].decode().splitlines():
            if not line.strip() or line.lstrip().startswith('#'):continue
            pattern,*attributes=line.split()
            subject=relative if '/' in pattern else relative.rsplit('/',1)[-1]
            expression=re.escape(pattern).replace(r'\*\*', '.*').replace(r'\*','[^/]*').replace(r'\?','[^/]')
            if not re.fullmatch(expression,subject):continue
            for attribute in attributes:
                key=attribute.lstrip('!-').split('=',1)[0]
                if key in result:
                    result[key]='unset' if attribute.startswith('-') else 'unspecified' if attribute.startswith('!') else attribute.split('=',1)[1] if '=' in attribute else 'set'
    return result


def worktree_ending(raw):
    if b'\r\n' in raw:
        return 'mixed' if b'\n' in raw.replace(b'\r\n',b'') else 'crlf'
    return 'lf' if b'\n' in raw else 'none'


@dataclass(frozen=True)
class _Archive:
    payloads: dict
    specials: tuple
    bsd_indexes: dict[str, bytes]


def decode_archive(raw):
    require(raw.startswith(b'!<arch>\n'), 'actual ar/COFF archive container')
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


class _VerifiedCapture:
    def __init__(self, modes, bound, report_sha256):
        self._modes, self._bound, self.report_sha256 = modes, bound, report_sha256
    def bound_input(self, mode): return self._bound[mode]
    def compare(self, mode, raw):
        actual = validate(raw, self._inputs)
        require(comparison(actual)==comparison(self._modes[mode]), 'exact ordered owner/manifold/numeric equality '+mode)
        return len(actual)


def command_schedule(context, sources, policy_name, crt_libraries, *, replay=False, archive_indexes=()):
    system, root, out = context['system'], context['root'], context['out']
    path = PureWindowsPath if system=='Windows' else PurePosixPath
    root, out = path(root), path(out)
    here = root/'tools/bullet-rust-discrete-world-check'
    tools = context['tools']; win = system=='Windows'; suffix = '.exe' if win else ''; ext = '.obj' if win else '.o'
    rust = [tools['rustup'],'run','1.95.0','rustc','--edition=2021','-O']
    if not replay:rust += ['-C','linker='+tools['rust_linker']]
    rargs = [*rust,'--extern','mds_crtmath='+str(out/'libmds_crtmath.rlib')]
    flags = native_flags(system,str(root)); compiler = tools.get('compiler'); shadow = out/'generated'
    file_context={**context,'archive_objects':tuple(path(source).stem+ext for source in sources)}
    result = []
    def add(label, argv, data=None, cwd=None, compile=False):
        argv = list(map(str,argv)); cwd = str(cwd or root/'rust')
        if compile: add(label+'-discovery',argv,data,cwd)
        roles=command_files(label,argv,file_context,archive_indexes=archive_indexes)
        result.append((label,argv,cwd,data,tuple(str(out/value.retained) for value in roles.outputs),compile))
    add('helpers-normal',[tools['python'],'-B',here/'test_check.py','-v'])
    add('helpers-optimized',[tools['python'],'-B','-O',here/'test_check.py','-v'])
    add('git-head',[tools['git'],'rev-parse','HEAD'])
    add('git-status',[tools['git'],'status','--porcelain=v1'])
    add('git-transport',[tools['git'],'ls-files','--eol'],cwd=root)
    add('git-attributes',[tools['git'],'check-attr','--stdin','text','eol'],'attributes',cwd=root)
    add('rust-compiler-path',[tools['rustup'],'which','--toolchain','1.95.0','rustc'])
    add('rust-version',[tools['rustup'],'run','1.95.0','rustc','-Vv'])
    crt = out/('mds_crtmath.lib' if win else 'libmds_crtmath.a')
    add('crt-build',[*rust,'--crate-name','mds_crtmath','--crate-type','rlib,staticlib','--print','native-static-libs',root/'rust/crates/mds-crtmath/src/lib.rs','--out-dir',out])
    for name,source,extra in [('dedicated','discrete_collision_world.rs',['discrete_world_']),('pure','pure_bullet.rs',[])]:
        exe = out/(name+suffix)
        add(name+'-build',[*rargs,'--test','-D','warnings',root/'rust/crates/mds-bullet/tests'/source,'-o',exe])
        add(name+'-run',[exe,*extra])
    rust_exe = out/('rust-world'+suffix)
    add('rust-observed-build',[*rargs,'--cfg','test',shadow/'tools/bullet-rust-discrete-world-check/runner.rs','-o',rust_exe])
    add('rust-ordinary',[rust_exe,policy_name],'inputs')
    if not replay:
        add('compiler-version',[compiler,'/?'] if win else [compiler,'--version'])
        if not win: add('native-linker-path',[compiler,'-print-prog-name=ld'])
        macro = out/'effective-macros.cpp'; macro_exe = out/('effective-macros'+suffix)
        add('macro-build',[compiler,*flags,macro,'/Fe'+str(macro_exe),'/Fo'+str(out)+'/'] if win else [compiler,*flags,macro,'-o',macro_exe],compile=True)
        add('actual-macros',[macro_exe])
        def object_command(source,obj,label,extra=()):
            add(label,[compiler,*flags,*extra,'/c',source,'/Fo'+str(obj)] if win else [compiler,*flags,*extra,'-c',source,'-o',obj],compile=True)
        objects = []
        for i,source in enumerate(sources):
            obj = out/(path(source).stem+ext); objects.append(obj)
            object_command(root/source,obj,f'compile-{i:03d}')
            if path(source).stem in {'btDbvt','btDbvtBroadphase'}:
                add('expanded-'+path(source).stem,[compiler,*flags,'/E' if win else '-E',root/source])
        library = out/('BulletWorld.lib' if win else 'libBulletWorld.a')
        add('archive-build',[tools['archiver'],'/NOLOGO','/OUT:'+str(library),*objects] if win else [tools['archiver'],'rcs',library,*objects])
        add('archive-list',[tools['archiver'],'/NOLOGO','/LIST',library] if win else [tools['archiver'],'t',library])
        if win:
            for obj in objects:
                add('extract-'+obj.stem,[tools['archiver'],'/NOLOGO','/EXTRACT:'+context['archive_names'][obj.name],'/OUT:'+str(out/'extracted'/obj.name),library])
        else: add('archive-extract',[tools['archiver'],'x',library],cwd=out/'extracted')
        hook = ['/FI'+str(here/'observer.h'),'/DDW_OBSERVED=1'] if win else ['-include',here/'observer.h','-DDW_OBSERVED=1']
        overrides = []
        for name,source_path in NATIVE_OBSERVATIONS:
            obj = out/('observed-'+name+ext); overrides.append(obj)
            object_command(shadow/source_path,obj,'observed-'+name,hook)
        for name,source,extra,prefix in [('native',here/'oracle.cpp',[],[]),('observed',shadow/'tools/bullet-rust-discrete-world-check/oracle.cpp',hook,overrides)]:
            obj = out/(name+'-consumer'+ext); exe = out/(name+suffix); linkmap = out/(name+'.map')
            object_command(source,obj,name+'-consumer-build',extra)
            add(name+'-consumer-expanded',[compiler,*flags,*extra,'/E' if win else '-E',source])
            link = [compiler,'/nologo','/MD','/EHsc',obj,*prefix,library,crt,'/Fe'+str(exe),'/link','/MAP:'+str(linkmap),'/VERBOSE:LIB',*crt_libraries] if win else [compiler,obj,*prefix,library,crt,*crt_libraries,'-fuse-ld='+tools['native_linker'],('-Wl,-map,' if system=='Darwin' else '-Wl,-Map,')+str(linkmap),'-o',exe]
            add(name+'-link',link)
            for mode in MODES: add(name+'-'+mode,[exe,mode,out/(name+'-allocator-'+mode+'.jsonl')],'inputs')
    for mode in MODES: add('rust-bound-'+mode,[rust_exe,policy_name],'bound-'+mode)
    for name in MUTANTS:
        for prefix in ['baseline','mutant']:
            exe = out/(prefix+'-'+name+suffix)
            add(prefix+'-build-'+name,[*rargs,'--cfg','test',out/'mutants'/name/'tools/bullet-rust-discrete-world-check/runner.rs','-o',exe])
            add(prefix+'-run-'+name,[exe,policy_name],'inputs')
    return result


def replay_report(report, head, inputs, cases):
    fields(report,['schema','status','base','policy','native','compiled_controls','public_world','scope','host','head','checkpoints','cases','controlled','ordinary_unbound','limits','producer_report_sha256'],'replay report')
    require(type(report['schema']) is int and report['schema']==7 and report['status']=='CONTROLLED_PASS' and report['base']==BASE and report['head']==head, 'completed distinct replay schema')
    require(report['policy']=='mmd-win64-sse' and report['native']=='WINDOWS_SOURCE_REPLAY' and identity(report['producer_report_sha256']), 'admitted native Windows producer digest')
    require(type(report['compiled_controls']) is int and report['compiled_controls']==len(MUTANTS) and type(report['cases']) is int and report['cases']==len(cases) and type(report['checkpoints']) is int and report['checkpoints']==len(inputs.splitlines()), 'complete current-Rust replay corpus and controls')
    require(type(report['controlled']) is dict and report['controlled']=={mode:len(inputs.splitlines()) for mode in MODES} and all(type(value) is int for value in report['controlled'].values()), 'complete current-Rust replay modes')
    require(report['public_world']=='UNCHANGED_NATIVE_BACKEND' and report['scope']=='private default-DBVT discrete collision owner' and report['ordinary_unbound']=='WINDOWS_SOURCE_REPLAY' and report['limits']==LIMITS+['replay Rust inner linker chain unobserved'], 'qualified replay boundary')
    host = fields(report['host'],['system','machine','image'],'replay host')
    require(type(host['system']) is str and type(host['machine']) is str and (host['image'] is None or type(host['image']) is str), 'replay host field types')
    return report


@dataclass(frozen=True)
class _Output:
    physical: str
    retained: str


@dataclass(frozen=True)
class _CommandFiles:
    inputs: tuple[str, ...]
    outputs: tuple[_Output, ...]


def command_files(label, argv, context, *, archive_indexes=()):
    path = PureWindowsPath if context['system']=='Windows' else PurePosixPath
    out = path(context['out'])
    physical = []
    for i, value in enumerate(argv):
        if value=='-o': physical.append(path(argv[i+1]))
        elif value.startswith(('/Fo','/Fe','/OUT:')):
            name=value[5:] if value.startswith('/OUT:') else value[3:]
            if name and not name.endswith(('/', '\\')): physical.append(path(name))
    base=label.removesuffix('-discovery')
    if base=='archive-build' and context['system']!='Windows': physical.append(path(argv[2]))
    if base=='crt-build': physical=[out/('mds_crtmath.lib' if context['system']=='Windows' else 'libmds_crtmath.a'),out/'libmds_crtmath.rlib']
    if base=='archive-extract': physical=[out/'extracted'/name for name in context['archive_objects']]
    if context['system']=='Darwin' and label=='archive-extract': physical += [out/'extracted'/name for name in archive_indexes]
    if base.endswith('-link'): physical.append(out/(base[:-5]+'.map'))
    if base in [name+'-'+mode for name in ['native','observed'] for mode in MODES]: physical.append(path(argv[-1]))
    if context['system']=='Windows' and base=='macro-build': physical.append(out/'effective-macros.obj')
    rust_executables = {'dedicated-build':'dedicated', 'pure-build':'pure', 'rust-observed-build':'rust-world',
                        **{prefix+'-build-'+name:prefix+'-'+name for prefix in ['baseline','mutant'] for name in MUTANTS}}
    if context['system']=='Windows' and label in rust_executables:
        require(physical==[out/(rust_executables[label]+'.exe')], 'exact Windows Rust executable output '+label)
        physical.append(physical[0].with_suffix('.pdb'))
    outputs=tuple(_Output(str(value), ('discovery/'+base+'/' if label.endswith('-discovery') else '')+value.relative_to(out).as_posix()) for value in physical)
    result=[]
    forced=False
    for value in argv[1:]:
        if value=='-include': forced=True;continue
        is_forced=forced or value.startswith('/FI');forced=False
        if value.startswith('/FI'): value=value[3:]
        if value.startswith('mds_crtmath='): value=value.split('=',1)[1]
        candidate=path(value)
        if candidate.is_absolute() and (is_forced or candidate.suffix.lower() in {'.rs','.cpp','.o','.obj','.a','.lib','.rlib'}) and candidate not in physical:
            if str(candidate) not in result: result.append(str(candidate))
    return _CommandFiles(tuple(result),outputs)


def captured_path(value, context):
    path = PureWindowsPath if context['system']=='Windows' else PurePosixPath
    target=path(value)
    for base,prefix in [(path(context['out']),''),(path(context['root']),'source/')]:
        if target.is_relative_to(base):return prefix+target.relative_to(base).as_posix()
    raise ValueError('foreign direct command input')


def semantic_fields(name):
    return ['events','pairs','manifolds'] if name in {'omit-pair-calculation','omit-dispatch','recreate-dispatcher','reverse-owner-order','reverse-dispatch-order','omit-linear-preclean'} else ['header'] if name=='default-force' else ['bodies']


def admit_capture(files, *, expected_head, canonical_sources, inputs, cases, expected_host, expected_policy):
    names = set(files)
    require(len(names) <= MAX_FILES, 'capture count bound')
    require(len({safe_name(name).casefold() for name in names})==len(names), 'capture case collision')
    if not isinstance(files,Capture):
        sizes=[len(files[name]) for name in names]
        require(all(size<=MAX_FILE for size in sizes) and sum(sizes)<=MAX_TOTAL, 'capture resource bounds before parsing')
    used = {'artifact-manifest.json'}
    manifest=None
    def raw(name):
        require(name in names, 'required capture file '+name)
        used.add(name)
        value = files[name]
        require(type(value) is bytes and len(value)<=MAX_FILE, 'capture byte bound')
        if manifest is not None:require(name in manifest and digest(value)==manifest[name], 'admitted capture byte preservation '+name)
        return value
    def data(name): return json_value(raw(name))
    manifest = data('artifact-manifest.json')
    inventory(manifest,{name:digest(files[name]) for name in names-{'artifact-manifest.json'}})
    report = fields(data('report.json'), ['schema','status','base','policy','native','compiled_controls','public_world','scope','host','head','compiler','checkpoints','cases','controlled','ordinary_unbound','limits'], 'native report')
    require(type(report['schema']) is int and report['schema']==6 and report['status']=='CONTROLLED_PASS' and report['base']==BASE, 'completed native schema')
    require(report['head']==expected_head and re.fullmatch('[0-9a-f]{40}',expected_head), 'current producer HEAD')
    host = fields(report['host'],['system','machine','image'],'host')
    require(type(host['system']) is str and type(host['machine']) is str and (host['image'] is None or type(host['image']) is str), 'host field types')
    require((host['system'],host['machine'].lower()) in expected_host, 'allowed actual producer host')
    require(report['policy']==expected_policy and report['native']=='ACTUAL_ORIGINAL_PUBLIC_SHIM_WITH_UNMODIFIED_ARCHIVE_CONTROL'
            and type(report['compiled_controls']) is int and report['compiled_controls']==len(MUTANTS), 'complete genuine native controls')
    require(report['public_world']=='UNCHANGED_NATIVE_BACKEND' and report['scope']=='private default-DBVT discrete collision owner' and report['limits']==LIMITS, 'fixed private boundary and limitations')
    require(type(report['cases']) is int and report['cases']==len(cases) and type(report['checkpoints']) is int and report['checkpoints']==len(inputs.splitlines()), 'derived corpus counts')
    require(data('cases.json')==cases and raw('inputs.txt')==inputs.encode(), 'exact current native corpus')
    require(data('source-canonical.json')=={path:digest(value.replace(b'\r\n',b'\n')) for path,value in canonical_sources.items()}, 'current canonical source closure')
    start = data('source-start.json'); require(type(start) is dict and set(start)==set(canonical_sources), 'exact physical source membership')
    require(data('source-end.json')==start, 'source-start equals source-end')
    original = {}
    for path, value in start.items():
        value = identity(value); content = raw('source/'+safe_name(path))
        require(digest(content)==value and content.replace(b'\r\n',b'\n')==canonical_sources[path].replace(b'\r\n',b'\n'), 'physical canonical source '+path)
        if path in TOUCHED: original[path] = content
    fixtures = {name:raw('source/tools/bullet-rust-discrete-world-check/'+name) for name in ['fixture.rs','world_objects_fixture.rs']}
    generated, edits = generated_sources(original,fixtures)
    require(data('observation-edits.json')==edits, 'actual current hook recipes and full inverse')
    generation = {path:digest(generated[path]) if path in generated else value for path,value in start.items()}
    require(data('generated-start.json')==generation and data('generated-end.json')==generation, 'generated start/end exact source closure')
    for path,value in generation.items(): require(digest(raw('generated/'+path))==value, 'generated physical source '+path)
    context = fields(data('producer.json'),['schema','system','root','out','tools','archive_names'],'producer')
    require(type(context['schema']) is int and context['schema']==3 and context['system']==host['system'], 'producer schema and host')
    system = context['system']; win = system=='Windows'; path_type = PureWindowsPath if win else PurePosixPath
    for value in [context['root'],context['out']]:
        require(type(value) is str and path_type(value).is_absolute() and len(value)<=MAX_PATH and '..' not in path_type(value).parts, 'producer absolute root')
    root, out = path_type(context['root']), path_type(context['out'])
    require(root!=out and root not in out.parents and out not in root.parents, 'disjoint producer roots')
    fields(context['tools'],['python','git','rustup','rustc','rust_linker','compiler','archiver','native_linker'],'tool paths')
    tools = data('tools-start.json'); require(type(tools) is dict and set(tools)==set(context['tools']), 'resolved tool membership')
    require(data('tools-end.json')==tools, 'tool start/end preservation')
    for name,tool in tools.items():
        fields(tool,['path','target','sha256'],'tool')
        require(tool['path']==context['tools'][name] and path_type(tool['path']).is_absolute() and path_type(tool['target']).is_absolute(), 'resolved actual tool path')
        require(digest(raw('tool-bytes/'+identity(tool['sha256'])))==tool['sha256'], 'retained resolved tool bytes')
    settings = fields(data('environment-start.json'),ENVIRONMENT,'named compiler/linker settings')
    require(all(value is None or type(value) is str for value in settings.values()) and data('environment-end.json')==settings, 'named settings preservation')
    require(not settings['CL'] and not settings['_CL_'], 'no ambient CL flag injection')
    compiler = fields(report['compiler'],['path','target','sha256'],'compiler')
    require(compiler==tools['compiler'], 'actual native compiler binding')
    require(data('compiler-flags.json')==native_flags(system,str(root)), 'exact effective native flags')
    require(raw('effective-macros.cpp')==macro_source(), 'actual macro probe recipe')
    macro_lines = raw('actual-macros.stdout').decode().splitlines()
    require(len(macro_lines)==len(MACROS) and all('=' in line for line in macro_lines), 'complete ABI macro output')
    macros = dict(line.split('=',1) for line in macro_lines)
    require(list(macros)==MACROS and len(macros)==len(macro_lines), 'exact fourteen macro keys')
    require(all(macros[key]==value for key,value in {'pointer_bits':'64','scalar_bytes':'4','MDS_BT_SYSTEM_MATH':'<undefined>','sinf':'mds_crt_sinf','cosf':'mds_crt_cosf','atan2f':'mds_crt_atan2f','BT_NO_PROFILE':'1','BT_USE_DOUBLE_PRECISION':'<undefined>'}.items()), 'actual ABI deterministic math policy')
    require((macros['WIN32']!='<undefined>')==win and (macros['_MSC_VER']!='<undefined>')==win and macros['BT_USE_SSE']=='', 'host-specific macro policy')
    if win:
        require(macros['WIN32']=='1' and re.fullmatch('[1-9][0-9]*',macros['_MSC_VER']) and int(macros['_MSC_VER'])>=1400 and macros['_M_X64']=='100' and macros['__aarch64__']=='<undefined>', 'actual MSVC x64 ABI macros')
    else:
        architecture='__x86_64__' if host['machine'].lower()=='x86_64' else '__aarch64__'
        require(macros[architecture]=='1' and macros['_M_X64']=='<undefined>', 'actual generic host architecture macros')
    sources = sorted((name for name in start if name.startswith('recipes/bullet275/bullet-src/src/') and name.endswith('.cpp') and name.split('/')[4] in {'BulletCollision','BulletDynamics','LinearMath'}), key=path_type)
    require(len(sources)==114 and len({path_type(name).stem.casefold() for name in sources})==114, 'complete current 114 unique archive sources')
    ext, suffix = ('.obj','.exe') if win else ('.o','')
    archive = 'BulletWorld.lib' if win else 'libBulletWorld.a'
    bindings = fields(data('archive-bindings.json'),['members','archive_sha256','actual_names'],'archive bindings')
    require(type(bindings['members']) is list and len(bindings['members'])==len(sources), 'complete archive source bindings')
    parsed_archive = decode_archive(raw(archive)); members = parsed_archive.payloads; require(bindings['archive_sha256']==digest(raw(archive)), 'raw archive identity')
    require(type(context['archive_names']) is dict and context['archive_names']==bindings['actual_names'], 'actual member names binding')
    objects = [path_type(source).stem+ext for source in sources]
    require(set(context['archive_names'])==set(objects) and set(members)==set(context['archive_names'].values()), 'exact archive payload member membership')
    listing = raw('archive-list.stdout').decode().splitlines()
    actual_listing=[line.strip() for line in listing if line.strip()]
    archive_listing(parsed_archive,actual_listing,system)
    for obj,member in context['archive_names'].items():
        require(type(member) is str and (member==obj or win and path_type(member)==out/obj), 'archive member producer path identity')
    for source,obj,entry in zip(sources,objects,bindings['members']):
        fields(entry,['source','source_sha256','object','sha256'],'archive member')
        content = raw(obj)
        require(entry=={'source':source,'source_sha256':start[source],'object':obj,'sha256':digest(content)}, 'source/object binding '+obj)
        require(raw('extracted/'+obj)==content==members[context['archive_names'][obj]], 'actual archive payload/extracted/object equality '+obj)
    crt_libraries = raw('crt-build.stderr').decode().split('native-static-libs:')[-1].splitlines()[0].split() if win else ([] if system=='Darwin' else ['-ldl','-lpthread','-lm'])
    archive_indexes = parsed_archive.bsd_indexes if system=='Darwin' else {}
    for name,body in archive_indexes.items():
        require(raw('extracted/'+name)==body, 'actual archive index/extracted equality '+name)
    schedule = command_schedule(context,sources,expected_policy,crt_libraries,archive_indexes=archive_indexes)
    commands = data('commands.json'); require(type(commands) is list and len(commands)==len(schedule), 'complete actual command schedule')
    command_map = {}
    inputs_by_name = {'inputs':inputs.encode(),'attributes':('\n'.join(sorted(start))+'\n').encode()}
    outputs = {}
    for mode in MODES:
        observed = validate(raw('observed-'+mode+'.stdout'),inputs,native=True)
        baseline = validate(raw('native-'+mode+'.stdout'),inputs,native=True,observed=False)
        validate_physical(raw('observed-'+mode+'.stderr'),inputs)
        for name,rows in [('native',baseline),('observed',observed)]:
            allocator = raw(name+'-allocator-'+mode+'.jsonl')
            for line in allocator.splitlines():json_value(line)
            validate_allocator(allocator,rows,mode,domain='unmodified-control' if name=='native' else 'generated-dbvt-node-sites')
        validate_noninterference(raw('native-allocator-'+mode+'.jsonl'),baseline,raw('observed-allocator-'+mode+'.jsonl'),observed,mode)
        bound = bind_inputs(inputs,observed).encode()
        require(raw('bound-'+mode+'.txt')==bound, 'native tree rank bound bytes '+mode)
        inputs_by_name['bound-'+mode] = bound; outputs[mode] = observed
    for record,(label,argv,cwd,input_name,produced,compile) in zip(commands,schedule):
        fields(record,['label','argv','cwd','stdin_sha256','tool','tool_target','tool_sha256','executable_sha256','returncode','timeout','seconds','stdout_sha256','stderr_sha256','outputs','inputs','generated_inputs'],'command')
        require(record['label']==label and label not in command_map, 'ordered unique command '+label)
        require(record['argv']==argv and record['cwd']==cwd, 'exact effective command argv/cwd '+label)
        expected_stdin = None if input_name is None else digest(inputs_by_name[input_name])
        require(record['stdin_sha256']==expected_stdin, 'exact command stdin '+label)
        require(type(record['returncode']) is int and record['returncode']==0 and record['timeout'] is False and type(record['seconds']) in {int,float} and math.isfinite(record['seconds']) and record['seconds']>=0, 'normal successful command '+label)
        for stream in ['stdout','stderr']: require(record[stream+'_sha256']==digest(raw(label+'.'+stream)), 'retained command output '+label)
        expected_inputs={value:digest(raw(captured_path(value,context))) for value in command_files(label,argv,{**context,'archive_objects':objects},archive_indexes=archive_indexes).inputs}
        require(record['inputs']==expected_inputs, 'actual pre-use direct source/object/archive/CRT inputs '+label)
        expected_generation=None
        if label=='rust-observed-build' or label.startswith('baseline-build-'):expected_generation=generation
        elif label.startswith('mutant-build-'):
            mutant_name=label[len('mutant-build-'):]
            memory=_Memory(dict(generated));mutate(memory,mutant_name)
            expected_generation={**generation,OWNER:digest(memory.files[OWNER])}
        require(record['generated_inputs']==expected_generation, 'actual generated source pre-use '+label)
        relative_outputs = [path_type(value).relative_to(out).as_posix() for value in produced]
        require(type(record['outputs']) is dict and set(record['outputs'])==set(relative_outputs), 'produced artifact membership '+label)
        for name in relative_outputs: require(record['outputs'][name]==digest(raw(name)), 'produced/use/end artifact identity '+label+' '+name)
        executable = argv[0]
        if path_type(executable).is_relative_to(out):
            expected_executable = digest(raw(path_type(executable).relative_to(out).as_posix()))
            require(record['tool']==executable and record['tool_target']==executable and record['tool_sha256']==expected_executable, 'actual executed produced binary '+label)
        else:
            candidates = [tool for tool in tools.values() if tool['path']==executable]
            require(candidates and record['tool']==executable and record['tool_target']==candidates[0]['target'] and record['tool_sha256']==candidates[0]['sha256'], 'resolved command tool '+label)
            expected_executable = candidates[0]['sha256']
        require(record['executable_sha256']==expected_executable, 'executed binary identity '+label)
        command_map[label] = record
    require(raw('git-head.stdout').decode().strip()==expected_head and not raw('git-status.stdout').strip(), 'current clean Git producer')
    require(raw('rust-compiler-path.stdout').decode().strip()==tools['rustc']['path'] and b'release: 1.95.0\n' in raw('rust-version.stdout').replace(b'\r\n',b'\n'), 'actual pinned compiler distinct from rustup')
    if not win:
        linker_output = raw('native-linker-path.stdout').decode().strip()
        require(path_type(linker_output).name==path_type(tools['native_linker']['path']).name, 'resolved compiler native linker selection')
    require(b'6 passed; 0 failed; 0 ignored' in raw('dedicated-run.stdout') and b'97 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out' in raw('pure-run.stdout'), 'six dedicated and unchanged native-free97 gates')
    attributes = raw('git-attributes.stdout').decode().splitlines()
    expected_attributes = {name+': '+key+': '+value for name in start for key,value in source_attributes(name,canonical_sources).items()}
    require(len(attributes)==len(expected_attributes) and set(attributes)==expected_attributes, 'exact trusted Git attributes')
    transport = raw('git-transport.stdout').decode().splitlines()
    tracked={}
    for line in transport:
        require('\t' in line, 'actual Git checkout transport')
        metadata,name=line.split('\t',1)
        require(name not in tracked, 'unique Git transport path')
        tracked[name]=metadata.split()
    for name in start:
        require(name in tracked and len(tracked[name])>=3, 'complete current Git transport membership')
        physical=raw('source/'+name)
        require(tracked[name][1]=='w/'+worktree_ending(physical), 'physical source/Git transport binding '+name)
        attributes_for_source=source_attributes(name,canonical_sources)
        if attributes_for_source['eol']=='lf' or attributes_for_source['text']=='unset':
            require(physical==canonical_sources[name], 'explicit source attribute physical transport '+name)
    include_evidence(data,raw,schedule,context,names)
    for label,receipt in [('expanded-btDbvt','policy-btDbvt.json'),('expanded-btDbvtBroadphase','policy-btDbvtBroadphase.json'),('native-consumer-expanded','native-consumer-policy.json'),('observed-consumer-expanded','observed-consumer-policy.json')]:
        observed_policy = policy(raw(label+'.stdout').decode())
        require(data(receipt)==observed_policy and observed_policy['policy']==expected_policy, 'actual expanded policy '+label)
    for name in ['native','observed']:
        link_data = raw(name+'.map')
        if system!='Darwin':link_data += b'\n'+raw(name+'-link.stdout')+b'\n'+raw(name+'-link.stderr')
        selected = selected_members(link_data,system,str(out/archive))
        required = {member+ext for member in ['btDbvtBroadphase','btDiscreteDynamicsWorld',*([member for member,_ in NATIVE_OBSERVATIONS] if name=='native' else [])]}
        require(required<=selected and selected<=set(objects), 'actual archive link member selection '+name)
        if name=='observed':
            require(not {member+ext for member,_ in NATIVE_OBSERVATIONS}&selected, 'observed overrides exclude original dispatcher/world archive payloads')
            override_members = ['observed-'+member+ext for member,_ in NATIVE_OBSERVATIONS]
            if system=='Darwin':selected_overrides(link_data,[str(out/member) for member in override_members])
            else:
                for member in override_members:
                    require(re.search(r'(?<![\w-])'+re.escape(member)+r'(?=[\s):]|$)',link_data.decode()), 'actual selected override object '+member)
        selection = data(name+'-link-selection.json')
        require(type(selection) is list and selection==sorted(selected), 'derived selected archive members '+name)
        receipt = fields(data(name+'-binary.json'),['produced_sha256','consumer_object_sha256','observed_override_objects'],'binary')
        require(receipt=={'produced_sha256':digest(raw(name+suffix)),'consumer_object_sha256':digest(raw(name+'-consumer'+ext)),
                         'observed_override_objects':{member+ext:digest(raw(member+ext)) for member in (['observed-'+member for member,_ in NATIVE_OBSERVATIONS] if name=='observed' else [])}}, 'genuine consumer/overrides/produced/executed/end binary '+name)
    plain = validate(raw('rust-ordinary.stdout'),inputs)
    controlled = {}
    for mode in MODES:
        actual = validate(raw('rust-bound-'+mode+'.stdout'),inputs)
        require(comparison(actual)==comparison(outputs[mode]), 'exact ordered bound Rust comparison '+mode)
        controlled[mode] = len(actual)
    require(type(report['controlled']) is dict and all(type(value) is int for value in report['controlled'].values()) and report['controlled']==controlled, 'derived complete four-mode counts')
    require(report['ordinary_unbound']==('EQUAL' if comparison(plain)==comparison(outputs['ordinary']) else 'DIVERGED_FINITE_ALLOCATOR_ORDER'), 'derived finite ordinary allocator result')
    controls = data('semantic-controls.json')
    require(type(controls) is dict and set(controls)==set(MUTANTS), 'complete seventeen semantic controls')
    for name in MUTANTS:
        control = fields(controls[name],['normal_exit','full_schema','different_rows','binary_sha256','semantic_fields','semantic_rows','baseline_binary_sha256','source_before','source_after'],'semantic control')
        clean = validate(raw('baseline-run-'+name+'.stdout'),inputs)
        mutant = validate(raw('mutant-run-'+name+'.stdout'),inputs)
        require(comparison(clean)==comparison(plain), 'clean same-host complete semantic baseline '+name)
        differences = [i for i,(a,b) in enumerate(zip(comparison(clean),comparison(mutant))) if a!=b]
        directed = [i for i,(a,b) in enumerate(zip(clean,mutant)) if any(a[field]!=b[field] for field in semantic_fields(name))]
        require(differences and directed, 'intended normally exiting semantic rejection '+name)
        mutation = _Memory(dict(generated)); mutation_edits = mutate(mutation,name)
        require(data('mutation-'+name+'.json')==mutation_edits, 'exact current mutation recipe '+name)
        changed = {**generation,OWNER:digest(mutation.files[OWNER])}
        for source,value in changed.items(): require(digest(raw('mutants/'+name+'/'+source))==value, 'mutant physical source '+name+' '+source)
        expected = {'normal_exit':True,'full_schema':True,'different_rows':differences,'binary_sha256':digest(raw('mutant-'+name+suffix)),
                    'semantic_fields':semantic_fields(name),'semantic_rows':directed,'baseline_binary_sha256':digest(raw('baseline-'+name+suffix)),
                    'source_before':generation,'source_after':changed}
        require(control['normal_exit'] is True and control['full_schema'] is True and control==expected and all(type(i) is int for i in control['different_rows']+control['semantic_rows']), 'derived valid directed semantic witness '+name)
    require(used==names, 'closed complete capture file membership: '+str(sorted(names-used)[:5]))
    verified = _VerifiedCapture(outputs,{mode:inputs_by_name['bound-'+mode] for mode in MODES},digest(raw('report.json')))
    verified._inputs = inputs
    return verified
