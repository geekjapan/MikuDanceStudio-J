"""Finite actual member-name state experiment. Default operation is read-only replay."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import sys
import stat
import zipfile
import member_name_lowering as P

sys.dont_write_bytecode = True
need, sha, loads = P.need, P.sha, P.loads
BASE = '8edbf1314a289ba0757b406f89276ca27da84c50'
REMOVED = ('RUSTC_BOOTSTRAP', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'VKD3D_DEBUG', 'VKD3D_SHADER_DEBUG')
MUTANTS = ('tail_plus_one', 'exchange_ids', 'missing_word', 'duplicate_word', 'missing_padding', 'stop_after_failure')
POISON = 0xa5a5a5a5


def cases():
    rows = [dict(kind=0, tail=r['tail'], count=0, capacity=0, script=0, bits=4) for r in P.cases() if r['domain'] == 'normal']
    for tail in (0, 10, 100000, P.MASK):
        for capacity in range(9):
            for count in range(capacity + 1):
                for script in range(16):
                    rows.append(dict(kind=0, tail=tail, count=count, capacity=capacity, script=script, bits=4))
    need(len(rows) == 3000, 'exact finite core corpus')
    for kind, script, bits in ((1, 0, 4), (1, 1, 4), (2, 1, 5), (2, 31, 5), (3, 0, 4)):
        rows.append(dict(kind=kind, tail=0, count=0, capacity=0, script=script, bits=bits))
    return rows


def expected(row, mutant=None):
    count, capacity = row['count'], row['capacity']
    words = [POISON] * capacity
    for i in range(count):
        words[i] = 0x11000000 + i
    token, next_token, consumed, events, diagnostics = int(capacity != 0), int(capacity != 0), 0, [], []
    def allocate(size, kind):
        nonlocal consumed, token, next_token, capacity, words
        old = token
        failed = consumed < row['bits'] and bool(row['script'] & (1 << consumed))
        consumed += 1
        if not failed:
            next_token += 1
            token = next_token
            new_capacity = size // 4
            words = ([0] * new_capacity if kind == 'calloc' else words + [POISON] * (new_capacity - capacity))
            capacity = new_capacity
        events.append([kind, size, int(not failed), old, token])
        if failed:
            diagnostics.append(('vkd3d_calloc', 'Out of memory.') if kind == 'calloc' else ('vkd3d_realloc', f'Out of memory, size {size}.'))
        return not failed
    if row['kind'] in (1, 2):
        allocate(1024, 'calloc')
    tail = (row['tail'] + (mutant == 'tail_plus_one')) & P.MASK
    text = ('cb' + str(tail)).encode()
    q = (len(text) + 4) // 4
    operations = [[((3 + q) << 16) | 6], [17], [29]]
    if mutant == 'exchange_ids':
        operations[1:3] = [[29], [17]]
    if mutant == 'missing_word':
        operations.pop(2)
    if mutant == 'duplicate_word':
        operations.insert(3, [29])
    operations.append(text)
    if row['kind'] in (0, 2):
        for op in operations:
            size = q if isinstance(op, bytes) else 1
            if count + size > capacity:
                new_capacity = max(capacity, 4)
                while new_capacity < count + size:
                    new_capacity *= 2
                if not allocate(new_capacity * 4, 'realloc'):
                    if mutant == 'stop_after_failure':
                        break
                    continue
            if isinstance(op, bytes):
                data = bytearray().join(w.to_bytes(4, 'little') for w in words[count:count+q])
                if mutant != 'missing_padding':
                    data[-4:] = bytes(4)
                data[:len(text)] = text
                words[count:count+q] = [int.from_bytes(data[i:i+4], 'little') for i in range(0, 4*q, 4)]
            else:
                words[count] = op[0]
            count += size
    need(consumed <= 4 + int(mutant == 'duplicate_word') + int(row['kind'] == 2), 'finite allocation bound')
    final = dict(count=count, capacity=capacity, words=words[:count], token=token, consumed=consumed,
                 unused=row['script'] >> min(consumed, row['bits']), events=events,
                 free_token=token, post_count=0, list_empty=1, overflow=int(row['kind'] == 3))
    return final, diagnostics


def case_input(rows):
    return ''.join(' '.join(str(r[k]) for k in ('kind','tail','count','capacity','script','bits'))+'\n' for r in rows).encode()


def rust_item(source, name, kind):
    pattern = r'^(?:pub )?' + kind + r' ' + re.escape(name) + r'\b'
    matches = list(re.finditer(pattern, source, re.M))
    need(len(matches) == 1, 'unique Rust item '+name)
    start = matches[0].start()
    if kind == 'struct':
        while source[:start].endswith('\n') and source[:start].splitlines()[-1].startswith('#['):
            start = source.rfind('\n', 0, start-1)+1
    cursor = matches[0].end()
    stack = []
    quote = None
    i = cursor
    while i < len(source):
        c = source[i]
        if quote:
            if c == '\\':
                i += 2
                continue
            if c == quote:
                quote = None
        elif c == '"':
            quote = c
        elif c in '([{':
            stack.append(c)
        elif c in ')]}':
            need(bool(stack) and stack.pop() == {')':'(',']':'[','}':'{'}[c], 'balanced Rust item '+name)
            if c == '}' and not stack:
                end = i+1
                if source[end:end+1] == ';':
                    end += 1
                return start, end, source[start:end]
        elif c == ';' and not stack:
            return start, i+1, source[start:i+1]
        i += 1
    raise ValueError('unterminated Rust item '+name)


def closure(z, src):
    c, r = z.read(P.C_PATH).decode(), z.read(P.R_PATH).decode()
    bindings = []
    def bind(path, original, text, label):
        need(original.count(text) == 1, 'unique closure span '+label)
        start = original.index(text)
        need(original[:start] + text + original[start+len(text):] == original, 'closure inverse')
        bindings.append(dict(path=path, label=label, start=start, end=start+len(text), sha256=sha(text.encode()),
                             dependencies=sorted(set(re.findall(r'\b[A-Za-z_]\w*\b', text)))))
        return text
    cparts = []
    for name in ('vkd3d_spirv_stream', 'vkd3d_spirv_chunk', 'vkd3d_spirv_builder'):
        text = P.extract_function(c, 'struct '+name+'\n')+';'
        cparts.append(bind(P.C_PATH,c,text,name))
    funcs = ('vkd3d_spirv_stream_init','vkd3d_spirv_stream_clear','vkd3d_spirv_stream_free',
             'vkd3d_spirv_opcode_word','vkd3d_spirv_build_word','vkd3d_spirv_string_word_count','vkd3d_spirv_build_string')
    for name in funcs:
        anchor = next(line for line in c.splitlines() if line.startswith('static ') and ' '+name+'(' in line)
        cparts.append(bind(P.C_PATH,c,P.extract_function(c,anchor),name))
    cparts.append(src['original.c'])
    needed_types = ('size_t','uint8_t','uint32_t','uint64_t','vkd3d_spirv_builder','vkd3d_spirv_stream',
                    'vkd3d_spirv_chunk','list','rb_tree','rb_entry','rb_compare_func','SpvExecutionModel',
                    'SpvExecutionModel_','SpvCapability','SpvCapability_','SpvOp','SpvOp_',
                    'vkd3d_debug_class','vkd3d_debug_channel')
    rparts = []
    for name in needed_types:
        kind = 'struct' if re.search(r'^pub struct '+name+r'\b',r,re.M) else 'type'
        _, _, text = rust_item(r,name,kind)
        rparts.append(bind(P.R_PATH,r,text,name))
        if kind == 'struct' and re.search(r'^impl '+name+r' \{',r,re.M):
            _, _, text = rust_item(r,name,'impl')
            rparts.append(bind(P.R_PATH,r,text,'impl '+name))
    for name in ('SpvOpCodeMask','SpvWordCountShift','VKD3D_DEBUG_ENV_NAME','r#true','r#false'):
        _, _, text = rust_item(r,name,'static mut' if name.startswith('Spv') else 'const')
        rparts.append(bind(P.R_PATH,r,text,name))
    for name in ('vkd3d_debug_channel_default','vkd3d_debug_channel__vkd3d'):
        _, _, text = rust_item(r,name,'static mut')
        rparts.append(bind(P.R_PATH,r,text,name))
    for name in funcs + ('list_init','align','vkd3d_calloc','vkd3d_free'):
        text = P.extract_function(r,'unsafe extern "C" fn '+name+'(')
        if r[:r.index(text)].endswith('#[inline]\n'):
            text = '#[inline]\n' + text
        rparts.append(bind(P.R_PATH,r,text,name))
    external = []
    for name in ('snprintf','strlen','memcpy','calloc','free','vkd3d_array_reserve','vkd3d_debug_channel_printf'):
        matches = re.findall(r'    unsafe fn '+name+r'\([\s\S]*?;',r)
        need(len(matches) == 1, 'unique genuine external '+name)
        text = bind(P.R_PATH,r,matches[0],'extern '+name)
        if name in ('calloc','free'):
            text = '#[link_name = "probe_'+name+'"]\n'+text
        external.append(text)
    memory = z.read('result/rust-raw/src/vkd3d_common/memory.rs').decode()
    need(memory.count('    unsafe fn realloc(') == 1, 'memory allocator binding')
    memory_bound = memory.replace('    unsafe fn realloc(', '    #[link_name = "probe_realloc"]\n    unsafe fn realloc(',1)
    need(memory_bound.replace('    #[link_name = "probe_realloc"]\n','',1) == memory, 'allocator inverse')
    bind('result/rust-raw/src/vkd3d_common/memory.rs',memory,memory,'memory module')
    rust = 'mod memory {\n'+memory_bound+'\n}\nmod spirv {\nunsafe extern "C" {\n'+'\n'.join(external)+'\n}\n'+'\n'.join(rparts)+'\n'+src['lowered.rs']+'\n@RUN@\n}\nfn main() { unsafe { probe_main(); } }\nunsafe extern "C" { fn probe_main(); }\n'
    native = c[:c.index('#define VKD3D_SPIRV_VERSION_1_0')]+'\n'+'\n'.join(cparts)+'\n@RUN@\n'
    files = {}
    for name in z.namelist():
        if name.startswith('result/source/') and not name.endswith('/'):
            files['native/'+name[len('result/source/'):]] = z.read(name)
    receipt = loads(z.read('cursor-witness/receipt.json'))
    pair = next(p for p in receipt['pairs'] if p['unit'].endswith('/vkd3d-shader/spirv.c'))
    witness = loads(z.read(pair['witness'].split('/vkd3d-probe/evidence/',1)[1]))
    for record in witness['native_inputs']['buffers']:
        path = record['physical_path']
        for marker in ('/spv/include/','/hdr/include/'):
            if path and marker in path:
                files['external/'+path.split(marker,1)[1]] = bytes.fromhex(record['bytes_hex'])
    need('external/spirv/unified1/spirv.h' in files, 'genuine SPIR-V header closure')
    return native, rust, bindings, files, witness['native_inputs']['adjusted_driver_argv']


HARNESS = r'''
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <assert.h>
_Static_assert(sizeof(unsigned)==4 && sizeof(size_t)==8 && sizeof(void *)==8,"Linux x64 scalar ABI");
static unsigned script, bits, used, token, next_token, nlog;
static size_t old_bytes;
struct event { unsigned kind; size_t size; unsigned ok, old, now; };
static struct event logbuf[8];
extern void run_case(unsigned, unsigned, size_t, size_t, unsigned, unsigned);
static void record(unsigned kind, size_t size, unsigned ok, unsigned old, unsigned now) {
    assert(nlog < 8); logbuf[nlog++] = (struct event){kind,size,ok,old,now};
}
static int fail(void) { unsigned n=used++; return n<bits && (script & (1u<<n)); }
void *probe_realloc(void *p, size_t size) {
    unsigned old=token; size_t previous=old_bytes;
    if (fail()) { record(0,size,0,old,old); return NULL; }
    assert(size <= 4096); void *q=realloc(p,size); assert(q);
    memset((unsigned char *)q+previous,0xa5,size-previous);
    token=++next_token; old_bytes=size; record(0,size,1,old,token); return q;
}
void *probe_calloc(size_t n, size_t s) {
    unsigned old=token; assert(n==256 && s==4);
    if (fail()) { record(1,n*s,0,old,old); return NULL; }
    void *q=calloc(n,s); assert(q); token=++next_token; old_bytes=n*s;
    record(1,n*s,1,old,token); return q;
}
void probe_free(void *p) { unsigned old=token; free(p); token=0; old_bytes=0; (void)old; }
void *probe_start(size_t capacity, unsigned input_script, unsigned input_bits) {
    script=input_script; bits=input_bits; used=0; token=0; next_token=0; nlog=0; old_bytes=capacity*4;
    if (!capacity) return NULL;
    void *p=malloc(old_bytes); assert(p); memset(p,0xa5,old_bytes); token=++next_token; return p;
}
void probe_finish(const uint32_t *words, size_t count, size_t capacity, unsigned overflow) {
    assert(count<=capacity && count<=32);
    printf("{\"count\":%zu,\"capacity\":%zu,\"words\":[",count,capacity);
    for(size_t i=0;i<count;i++) printf("%s%u",i?",":"",words[i]);
    printf("],\"token\":%u,\"consumed\":%u,\"unused\":%u,\"events\":[",token,used,script>>(used<bits?used:bits));
    for(unsigned i=0;i<nlog;i++) {
        struct event *e=&logbuf[i];
        printf("%s[\"%s\",%zu,%u,%u,%u]",i?",":"",e->kind?"calloc":"realloc",e->size,e->ok,e->old,e->now);
    }
    printf("],\"free_token\":%u,\"overflow\":%u",token,overflow);
}
void probe_end(size_t count, unsigned empty) {
    assert(token==0); printf(",\"post_count\":%zu,\"list_empty\":%u}\n",count,empty);
}
void probe_layout(const char *type, size_t size, size_t alignment, const size_t *offsets, size_t n) {
    printf("{\"layout\":\"%s\",\"size\":%zu,\"alignment\":%zu,\"offsets\":[",type,size,alignment);
    for(size_t i=0;i<n;i++) printf("%s%zu",i?",":"",offsets[i]);
    printf("]}\n");
}
extern void layouts(void);
void probe_main(void) {
    unsigned kind,tail,s,b; size_t count,capacity; unsigned id=0;
    printf("{\"tid\":%u}\n",(unsigned)gettid()); layouts();
    while(scanf("%u %u %zu %zu %u %u",&kind,&tail,&count,&capacity,&s,&b)==6) {
        fprintf(stderr,"CASE %u BEGIN\n",id);
        run_case(kind,tail,count,capacity,s,b);
        fprintf(stderr,"CASE %u END\n",id++);
    }
    assert(feof(stdin));
}
'''
C_RUN = r'''
void *probe_start(size_t,unsigned,unsigned);
void probe_finish(const uint32_t *,size_t,size_t,unsigned);
void probe_end(size_t,unsigned);
void probe_layout(const char *,size_t,size_t,const size_t *,size_t);
void layouts(void) {
@C_LAYOUTS@
}

void run_case(unsigned kind,unsigned tail,size_t count,size_t capacity,unsigned script,unsigned bits) {
    struct vkd3d_spirv_builder builder={0};
    struct vkd3d_spirv_stream *s=&builder.debug_stream;
    s->words=probe_start(capacity,script,bits); s->capacity=capacity; s->word_count=count;
    list_init(&s->inserted_chunks);
    for(size_t i=0;i<count;i++) s->words[i]=0x11000000u+i;
    if(kind==1 || kind==2) vkd3d_spirv_stream_init(s);
    if(kind==0 || kind==2) vkd3d_spirv_build_op_member_name(&builder,17,29,"cb%u",tail);
    unsigned overflow=0;
    if(kind==3) overflow=!vkd3d_array_reserve((void **)&s->words,&s->capacity,SIZE_MAX/4+1,4);
    probe_finish(s->words,s->word_count,s->capacity,overflow);
    vkd3d_spirv_stream_free(s);
    probe_end(s->word_count,s->inserted_chunks.next==&s->inserted_chunks && s->inserted_chunks.prev==&s->inserted_chunks);
}
int main(void) { extern void probe_main(void); probe_main(); return 0; }
'''
R_RUN = r'''
unsafe extern "C" {
    fn probe_start(capacity:usize,script:u32,bits:u32)->*mut ::core::ffi::c_void;
    fn probe_finish(words:*const u32,count:usize,capacity:usize,overflow:u32);
    fn probe_end(count:usize,empty:u32);
    fn probe_layout(name:*const ::core::ffi::c_char,size:usize,alignment:usize,offsets:*const usize,n:usize);
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn layouts() {
@R_LAYOUTS@
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn run_case(kind:u32,tail:u32,count:usize,capacity:usize,script:u32,bits:u32) {
    let mut storage=::core::mem::MaybeUninit::<vkd3d_spirv_builder>::zeroed();
    let builder=storage.as_mut_ptr();
    let s=&raw mut (*builder).debug_stream;
    (*s).words=probe_start(capacity,script,bits).cast(); (*s).capacity=capacity; (*s).word_count=count;
    list_init(&raw mut (*s).inserted_chunks);
    for i in 0..count { *(*s).words.add(i)=0x11000000+i as u32; }
    if kind==1 || kind==2 { vkd3d_spirv_stream_init(s); }
    if kind==0 || kind==2 { vkd3d_spirv_build_op_member_name(builder,17,29,b"cb%u\0".as_ptr().cast(),tail); }
    let mut overflow=0;
    if kind==3 { overflow=(!vkd3d_array_reserve((&raw mut (*s).words).cast(),&raw mut (*s).capacity,usize::MAX/4+1,4)) as u32; }
    probe_finish((*s).words,(*s).word_count,(*s).capacity,overflow);
    vkd3d_spirv_stream_free(s);
    let head=&raw mut (*s).inserted_chunks;
    probe_end((*s).word_count,((*head).next==head && (*head).prev==head) as u32);
}
'''


def programs(native, rust):
    clayouts,rlayouts=[],[]
    for name in ('vkd3d_spirv_builder','vkd3d_spirv_stream','vkd3d_spirv_chunk','list','rb_tree','rb_entry'):
        _,_,declaration=rust_item(rust,name,'struct')
        fields=re.findall(r'    pub (\w+):',declaration)
        need(fields,'complete genuine layout fields '+name)
        offsets=','.join('offsetof(struct '+name+','+f+')' for f in fields)
        clayouts.append('probe_layout("'+name+'",sizeof(struct '+name+'),_Alignof(struct '+name+'),(const size_t[]){'+offsets+'},'+str(len(fields))+');')
        offsets=','.join('::core::mem::offset_of!('+name+','+f+')' for f in fields)
        rlayouts.append('probe_layout(b"'+name+'\\0".as_ptr().cast(),::core::mem::size_of::<'+name+'>(),::core::mem::align_of::<'+name+'>(),['+offsets+'].as_ptr(),'+str(len(fields))+');')
    out = {'oracle.c':native.replace('@RUN@',C_RUN.replace('@C_LAYOUTS@','\n'.join(clayouts))), 'stable.rs':rust.replace('@RUN@',R_RUN.replace('@R_LAYOUTS@','\n'.join(rlayouts))), 'harness.c':HARNESS}
    changes = {
        'tail_plus_one':('        tail,\n','        tail.wrapping_add(1),\n'),
        'exchange_ids':('vkd3d_spirv_build_word(stream, type_id);\n    vkd3d_spirv_build_word(stream, member);','vkd3d_spirv_build_word(stream, member);\n    vkd3d_spirv_build_word(stream, type_id);'),
        'missing_word':('    vkd3d_spirv_build_word(stream, member);\n',''),
        'duplicate_word':('    vkd3d_spirv_build_word(stream, member);\n','    vkd3d_spirv_build_word(stream, member);\n    vkd3d_spirv_build_word(stream, member);\n'),
        'missing_padding':('    *ptr.offset(word_count.wrapping_sub(1 as ::core::ffi::c_uint) as isize) = 0\n        as uint32_t;',''),
    }
    for name,(old,new) in changes.items():
        need(out['stable.rs'].count(old)==1,'unique semantic mutant '+name)
        out[name+'.rs']=out['stable.rs'].replace(old,new,1)
    value=out['stable.rs']
    anchor='    vkd3d_spirv_build_word(stream, type_id);'
    need(value.count(anchor)==1,'stop mutant target anchor')
    value=value.replace(anchor,'    if (*stream).word_count == start_count { return; }\n'+anchor,1)
    value=value.replace('    vkd3d_spirv_build_word(stream, member);','    if (*stream).word_count == start_count + 1 { return; }\n    vkd3d_spirv_build_word(stream, member);',1)
    anchor='    vkd3d_spirv_build_string(\n'
    need(value.count(anchor)==1,'stop mutant string anchor')
    value=value.replace(anchor,'    if (*stream).word_count == start_count + 2 { return; }\n'+anchor,1)
    anchor='    name_size = vkd3d_spirv_string_word_count('
    need(value.count(anchor)==1,'stop mutant count anchor')
    value=value.replace(anchor,'    let start_count = (*stream).word_count;\n'+anchor,1)
    out['stop_after_failure.rs']=value
    return out


def tooling_sources():
    out=P.tooling_sources()
    folder=Path(__file__).resolve().parent
    for name in ('member_name_state.py','test_member_name_state.py'):
        out['tooling/'+name]=(folder/name).read_bytes()
    out['tooling/member-name-real-state.yml']=(folder.parent.parent/'.github/workflows/member-name-real-state.yml').read_bytes()
    return out


def prepare(paths):
    proof, src=P.admission(paths)
    with zipfile.ZipFile(paths['all24']) as z:
        native,rust,bindings,files,macros=closure(z,src)
    generated=programs(native,rust)
    files.update({k:v.encode() for k,v in {**src,**generated}.items()})
    files.update(tooling_sources())
    files['closure.json']=(json.dumps(dict(bindings=bindings,admitted_driver=macros),sort_keys=True,indent=2)+'\n').encode()
    files['admission.json']=(json.dumps(proof,sort_keys=True,indent=2)+'\n').encode()
    rows=cases()
    files['cases.json']=(json.dumps(rows,sort_keys=True,indent=2)+'\n').encode()
    files['input.txt']=case_input(rows)
    return proof,files,generated,rows


def command_plan(generated):
    includes=['-Inative','-Inative/include','-Inative/include/private','-Inative/libs/vkd3d-shader','-Iexternal']
    common=['cc','-std=c11','-D_GNU_SOURCE','-DHAVE_CONFIG_H','-D_WIN32_WINNT=0x0600','-D_FORTIFY_SOURCE=0','-DC2RUST=1']+includes
    plan=[('rustc-identity',['rustc','+1.95.0','-vV'],None),('cc-identity',['cc','--version'],None),('pinned-rustc-path',['rustup','which','--toolchain','1.95.0','rustc'],None)]
    for mode,opt in (('normal','-O0'),('optimized','-O2')):
        for name,source,extra in (
            ('debug','native/libs/vkd3d-common/debug.c',[]),
            ('harness','harness.c',[]),
            ('memory','native/libs/vkd3d-common/memory.c',['-Drealloc=probe_realloc'])):
            plan.append((name+'-'+mode+'-object',common+[opt]+extra+['-c',source,'-o',name+'-'+mode+'.o'],None))
        for name in generated:
            if name=='harness.c':
                continue
            key=name+'-'+mode
            objects=['debug-'+mode+'.o','harness-'+mode+'.o']
            if name.endswith('.c'):
                argv=common+[opt,'-DLIBVKD3D_SHADER_SOURCE','-DVKD3D_DEBUG_ENV=VKD3D_SHADER_DEBUG','-Dcalloc=probe_calloc','-Dfree=probe_free',name,'memory-'+mode+'.o']+objects+['-pthread','-o',key+'.bin']
            else:
                argv=['rustc','+1.95.0','--edition=2024','--crate-name','member_name_state','-C','opt-level=3' if mode=='optimized' else 'opt-level=0',name]
                for obj in objects:
                    argv+=['-C','link-arg='+obj]
                argv+=['-C','link-arg=-pthread','-o',key+'.bin']
            plan.append((key+'-compile',argv,None))
            plan.append((key+'-run',['./'+key+'.bin'],'input.txt'))
    return plan


def verify_commands(root,plan):
    aggregate=loads((root/'commands.json').read_bytes())
    need(set(aggregate)=={stem for stem,_,_ in plan},'complete command inventory')
    need({p.name for p in root.glob('*.command.json')}=={s+'.command.json' for s,_,_ in plan},'individual command receipt coverage')
    for stem,argv,stdin in plan:
        receipt=loads((root/(stem+'.command.json')).read_bytes())
        need(set(receipt)=={'status','command','failure','stdout_sha256','stderr_sha256'},'command receipt fields')
        command=receipt['command']
        need(command==aggregate[stem],'aggregate/individual receipt differs')
        need(set(command)=={'argv','cwd','start','end','exit_code','stdout','stderr','environment','removed_environment','input_sha256'},'command fields')
        need(command['argv']==argv and command['cwd']==loads((root/'host.json').read_bytes())['cwd'],'exact argv/cwd')
        need(receipt['status']=='succeeded' and receipt['failure'] is None and type(command['exit_code']) is int and command['exit_code']==0,'successful actual command required')
        need(command['removed_environment']==list(REMOVED),'clean environment contract')
        env=command['environment']
        need(set(env)=={'GITHUB_ACTIONS','GITHUB_SHA','RUNNER_OS','RUNNER_ARCH','PATH','LC_ALL'} and env['GITHUB_ACTIONS']=='true' and env['RUNNER_OS']=='Linux' and env['RUNNER_ARCH']=='X64' and env['LC_ALL']=='C','host environment')
        need(re.fullmatch('[0-9a-f]{40}',env['GITHUB_SHA']) and env['PATH'] and env['GITHUB_SHA']==loads((root/'host.json').read_bytes())['source_head'],'source/runtime identity')
        for field in ('start','end'):
            need(datetime.datetime.fromisoformat(command[field]).utcoffset()==datetime.timedelta(0),'UTC command time')
        need(command['start']<=command['end'],'command time order')
        need(command['input_sha256']==(sha((root/stdin).read_bytes()) if stdin else None),'stdin identity')
        for field in ('stdout','stderr'):
            need(command[field]==stem+'.'+field,'raw output path')
            need(receipt[field+'_sha256']==sha((root/command[field]).read_bytes()),'raw output hash')
    version=(root/'rustc-identity.stdout').read_text()
    need('release: 1.95.0\n' in version and 'host: x86_64-unknown-linux-gnu\n' in version and 'nightly' not in version,'pinned stable compiler')
    compilers=loads((root/'compilers.json').read_bytes())
    need(set(compilers)=={'cc','rustc'},'compiler file identities')
    for row in compilers.values():
        need(set(row)=={'path','sha256'} and Path(row['path']).is_absolute() and re.fullmatch('[0-9a-f]{64}',row['sha256']),'compiler byte identity')


def verify_output(root,key,rows,mutant):
    stdout=(root/(key+'-run.stdout')).read_bytes()
    lines=stdout.splitlines()
    need(len(lines)==len(rows)+7,'complete output rows/layouts')
    tid=loads(lines[0])
    need(set(tid)=={'tid'} and type(tid['tid']) is int and tid['tid']>0,'real single thread TID')
    layouts=[loads(s) for s in lines[1:7]]
    need([r['layout'] for r in layouts]==['vkd3d_spirv_builder','vkd3d_spirv_stream','vkd3d_spirv_chunk','list','rb_tree','rb_entry'],'genuine layout coverage')
    for row in layouts:
        need(set(row)=={'layout','size','alignment','offsets'} and type(row['size']) is int and row['size']>0 and row['alignment'] in (4,8) and len(row['offsets'])=={'vkd3d_spirv_builder':28,'vkd3d_spirv_stream':4,'vkd3d_spirv_chunk':4,'list':2,'rb_tree':2,'rb_entry':4}[row['layout']] and all(type(v) is int and 0<=v<=row['size'] for v in row['offsets']),'compiled layout receipt')
    errors=[]
    mismatches=0
    for i,row in enumerate(rows):
        want,diagnostics=expected(row,mutant)
        need(json.dumps(loads(lines[i+7]),sort_keys=True)==json.dumps(want,sort_keys=True),'complete expected state '+key+' case '+str(i))
        mismatches+=want!=expected(row)[0]
        errors.append(f'CASE {i} BEGIN\n')
        for function,message in diagnostics:
            errors.append(f'vkd3d:{tid["tid"]}:err:vkd3d:{function} {message}\n')
        errors.append(f'CASE {i} END\n')
    need((root/(key+'-run.stderr')).read_bytes()==''.join(errors).encode(),'exact real diagnostic TID/framing/text '+key)
    need(mutant is None or mismatches>0,'semantic mutant must differ after complete expected match')
    return layouts,mismatches


def packet_manifest(root):
    need(root.is_dir() and not root.is_symlink(),'real packet directory')
    out={}
    total=0
    for path in sorted(root.rglob('*')):
        need(not path.is_symlink(),'packet symlink')
        if path.is_dir():
            continue
        need(stat.S_ISREG(path.stat().st_mode),'packet regular file')
        name=str(path.relative_to(root))
        need(P.safe_name(name),'packet safe path')
        if name=='seal.json':
            continue
        total+=path.stat().st_size
        need(len(out)<1500 and total<=650_000_000,'bounded packet')
        out[name]=sha(path.read_bytes())
    return out


def replay(root,paths):
    need(root is not None,'complete sealed packet required for default replay')
    before=packet_manifest(root)
    need(loads((root/'seal.json').read_bytes())==before,'complete exact packet seal')
    proof,files,generated,rows=prepare(paths)
    for name,data in files.items():
        need((root/name).read_bytes()==data,'retained source/input differs '+name)
    plan=command_plan(generated)
    verify_commands(root,plan)
    binaries=loads((root/'binaries.json').read_bytes())
    expected_names={s[:-8]+'.bin' for s,_,_ in plan if s.endswith('-compile')}
    object_names={argv[-1] for stem,argv,_ in plan if stem.endswith('-object')}
    need(set(binaries)==expected_names|object_names,'binary/object inventory')
    inventory=set(files)|{'host.json','commands.json','compilers.json','binaries.json'}|set(binaries)
    inventory|={stem+suffix for stem,_,_ in plan for suffix in ('.command.json','.stdout','.stderr')}
    need(set(before)==inventory,'exact packet membership')
    for name,digest in binaries.items():
        data=(root/name).read_bytes()
        need(sha(data)==digest and data[:6]==b'\x7fELF\x02\x01' and data[18:20]==b'\x3e\x00','Linux x64 ELF source-bound binary/object')
    result={}
    reference=None
    for name in generated:
        if name=='harness.c':
            continue
        mutant=name[:-3] if name[:-3] in MUTANTS else None
        for mode in ('normal','optimized'):
            key=name+'-'+mode
            layouts,mismatches=verify_output(root,key,rows,mutant)
            if reference is None:
                reference=layouts
            need(layouts==reference,'C/Rust genuine compiled layout equality')
            result[key]=mismatches
    need(packet_manifest(root)==before,'read-only replay changed evidence')
    return dict(scope='finite_actual_member_name_final_state_and_allocation_history',cases=len(rows),core_cases=3000,
                actual_compiled='PASS retained Linux x64 normal/optimized',mutant_mismatches=result,admission=proof,
                authentic_job_proof=False,stable_lowering='not_authorized',native_debug='diagnostic dependency only')


def run_hosted(root,paths):
    import platform
    import shutil
    import subprocess
    need(sys.platform=='linux' and platform.machine()=='x86_64' and os.environ.get('GITHUB_ACTIONS')=='true','hosted Linux x64 only')
    need(not root.exists(),'fresh output required')
    root.mkdir(parents=True)
    env=dict(os.environ)
    for key in REMOVED:
        env.pop(key,None)
    env['LC_ALL']='C'
    required={k:env[k] for k in ('GITHUB_ACTIONS','GITHUB_SHA','RUNNER_OS','RUNNER_ARCH','PATH','LC_ALL')}
    aggregate={}
    def write(name,value):
        p=root/name
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(value if isinstance(value,bytes) else (json.dumps(value,sort_keys=True,indent=2)+'\n').encode())
    write('host.json',dict(cwd=str(root.resolve()),base=BASE,source_head=required['GITHUB_SHA'],scope='finite actual final initialized state and allocation history',poison=POISON,poison_intervention='starting capacity and newly grown bytes only; genuine calloc remains zero',lifetime='new token on every successful realloc; free token captured before actual free; no freed pointer observation',limitations=['no arbitrary transient equivalence','native debug is diagnostic dependency only','no whole translator or product adoption','other 32 variadics unchanged','Linux x64 only'],local_compiled_acceptance=False))
    def run(stem,argv,stdin):
        start=datetime.datetime.now(datetime.timezone.utc).isoformat()
        output,errors,code,failure=b'',b'',None,None
        caught=None
        try:
            p=subprocess.run(argv,cwd=root,env=env,input=(root/stdin).read_bytes() if stdin else None,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
            output,errors,code=p.stdout,p.stderr,p.returncode
            status='succeeded' if code==0 else 'failed'
            if code!=0:
                failure=dict(kind='nonzero_exit',message=str(code))
        except (OSError,subprocess.TimeoutExpired) as error:
            caught=error
            status='timeout' if isinstance(error,subprocess.TimeoutExpired) else 'launch_error'
            failure=dict(kind=status,message=str(error))
            if isinstance(error,subprocess.TimeoutExpired):
                output,errors=error.stdout or b'',error.stderr or b''
        command=dict(argv=argv,cwd=str(root.resolve()),start=start,end=datetime.datetime.now(datetime.timezone.utc).isoformat(),exit_code=code,
                     stdout=stem+'.stdout',stderr=stem+'.stderr',environment=required,removed_environment=list(REMOVED),
                     input_sha256=sha((root/stdin).read_bytes()) if stdin else None)
        write(command['stdout'],output); write(command['stderr'],errors)
        write(stem+'.command.json',dict(status=status,command=command,failure=failure,stdout_sha256=sha(output),stderr_sha256=sha(errors)))
        aggregate[stem]=command
        write('commands.json',aggregate)
        if caught:
            raise caught
        need(code==0,'actual command failed '+stem)
    proof,files,generated,rows=prepare(paths)
    for name,data in files.items():
        write(name,data)
    plan=command_plan(generated)
    for stem,argv,stdin in plan:
        run(stem,argv,stdin)
        if stem=='pinned-rustc-path':
            pinned=Path((root/'pinned-rustc-path.stdout').read_text().strip())
            need(pinned.is_absolute() and pinned.is_file(),'pinned compiler executable')
            write('compilers.json',{name:dict(path=str(path),sha256=sha(path.read_bytes())) for name,path in [('rustc',pinned.resolve()),('cc',Path(shutil.which('cc')).resolve())]})
    names={s[:-8]+'.bin' for s,_,_ in plan if s.endswith('-compile')}|{argv[-1] for s,argv,_ in plan if s.endswith('-object')}
    write('binaries.json',{name:sha((root/name).read_bytes()) for name in names})
    write('seal.json',packet_manifest(root))
    return replay(root,paths)


def guard(event,args):
    if event=='open':
        mode=args[1] or ''
        flags=args[2] or 0
        need(not any(c in mode for c in 'wax+') and not flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND),'read-only replay filesystem write')
    need(event not in ('os.mkdir','os.remove','os.rename','os.rmdir','os.chmod','os.link','os.symlink','os.truncate','os.utime','os.system','os.posix_spawn') and not event.startswith(('subprocess.','socket.')),'read-only replay forbidden effect '+event)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts',type=Path)
    for key in P.ARTIFACTS:
        parser.add_argument('--'+key,type=Path)
    parser.add_argument('--replay',type=Path)
    parser.add_argument('--run-hosted',type=Path)
    parser.add_argument('--acquire',type=Path)
    args=parser.parse_args()
    need(sum(x is not None for x in (args.replay,args.run_hosted,args.acquire))<=1,'exclusive operation')
    if args.acquire:
        P.acquire(args.acquire)
        return
    paths={k:getattr(args,k) or (args.artifacts/(k+'.zip') if args.artifacts else None) for k in P.ARTIFACTS}
    need(all(paths.values()),'all three admitted artifacts required')
    if args.run_hosted:
        result=run_hosted(args.run_hosted,paths)
    else:
        sys.addaudithook(guard)
        result=replay(args.replay,paths)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()
