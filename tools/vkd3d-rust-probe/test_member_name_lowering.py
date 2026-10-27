import copy
from contextlib import contextmanager
import io
import os
from pathlib import Path, PosixPath
import sys
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.dont_write_bytecode = True
import member_name_lowering as M


@contextmanager
def hosted_verifier():
    import full_compiler as F
    original = Path(F.__file__).parent / 'patches/c2rust-win64-abi.patch'
    module = '/home/runner/work/MikuDanceStudio-J/MikuDanceStudio-J/tools/vkd3d-rust-probe/full_compiler.py'
    reviewed = Path(module).parent / 'patches/c2rust-win64-abi.patch'
    live = {'bytes': original.read_bytes(), 'reads': []}
    methods = {name: getattr(PosixPath, name) for name in ('read_bytes', 'resolve', 'is_file', 'is_symlink')}
    def read(path):
        live['reads'].append(str(path))
        if path == reviewed:
            return live['bytes']
        if str(path).startswith('/home/'):
            raise AssertionError('unexpected live captured read ' + str(path))
        return methods['read_bytes'](path)
    def resolve(path, *args, **kwargs):
        return path if path == reviewed else methods['resolve'](path, *args, **kwargs)
    def is_file(path):
        return methods['is_file'](original if path == reviewed else path)
    def is_symlink(path):
        return methods['is_symlink'](original if path == reviewed else path)
    with patch.object(F, '__file__', module), patch.object(PosixPath, 'read_bytes', read), \
         patch.object(PosixPath, 'resolve', resolve), patch.object(PosixPath, 'is_file', is_file), \
         patch.object(PosixPath, 'is_symlink', is_symlink):
        yield reviewed, live


class TraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.z = zipfile.ZipFile(os.environ['MEMBER_NAME_ALL24'])
        cls.src = M.sources(cls.z)

    def test_actual_hosted_transport_and_reviewed_patch(self):
        import full_compiler as F
        import apply_c2rust_patch as A
        setup = Path(os.environ.get('MEMBER_NAME_SETUP', str(Path(os.environ['MEMBER_NAME_ALL24']).with_name('setup.zip'))))
        with zipfile.ZipFile(setup) as retained:
            transport = M.Transport(self.z, retained)
        tool = next(p for p in transport.files if p.endswith('/bin/c2rust-transpile'))
        original_paths = F.Path, A.Path
        with hosted_verifier() as (reviewed, live):
            transport.files[str(reviewed)] = b'untrusted captured replacement'
            with transport.context():
                F.verify_cursor_tool(F.Path(tool))
                self.assertEqual(F.Path(reviewed).read_bytes(), live['bytes'])
                self.assertEqual(F.Path(reviewed).resolve(), reviewed)
                self.assertTrue(F.Path(reviewed).is_file())
                self.assertFalse(F.Path(reviewed).is_symlink())
                alias, target = next(iter(transport.aliases.items()))
                self.assertEqual(F.Path(alias).read_bytes(), transport.read(target))
                self.assertEqual(str(F.Path(alias).resolve()), target)
                for unknown in ('/home/unknown/captured.c', str(reviewed)+'.other', str(reviewed)+'/child', str(reviewed.parent/'neighbor.patch')):
                    before = list(live['reads'])
                    with self.subTest(path=unknown), self.assertRaises(KeyError):
                        F.Path(unknown).read_bytes()
                    self.assertEqual(live['reads'], before)
                    self.assertFalse(F.Path(unknown).is_file())
            self.assertEqual((F.Path, A.Path), original_paths)
            live['bytes'] += b'changed current reviewed patch'
            with self.assertRaisesRegex(ValueError, 'differs from reviewed patch'):
                with transport.context():
                    F.verify_cursor_tool(F.Path(tool))
            self.assertEqual((F.Path, A.Path), original_paths)
        self.assertEqual((F.Path, A.Path), original_paths)

    def test_exact_source_and_inverse(self):
        lowered = M.lower(self.src['original.rs'])
        self.assertEqual(lowered, self.src['lowered.rs'])
        self.assertIn('mut tail: ::core::ffi::c_uint', lowered)
        self.assertIn('snprintf(', lowered)
        self.assertNotIn('VaList', lowered)
        self.assertEqual(lowered[lowered.index('    name['):], self.src['original.rs'][self.src['original.rs'].index('    name['):])

    def test_edit_and_inverse_controls(self):
        for old, new in [('1024','1023'),('c2rust_args','wrong'),("'\\0'", "'x'"),('mut member: uint32_t','mut member: i32'),('mut fmt:', 'fmt:')]:
            with self.subTest(edit=old), self.assertRaises(ValueError):
                M.lower(self.src['original.rs'].replace(old,new))
        with patch.object(M, 'EDITS', (*M.EDITS, ('    name_size =', '    name_size = 0;\n    name_size ='))):
            with self.assertRaises(ValueError):
                M.lower(self.src['original.rs'])

    def test_source_caller_reference_and_formatter_controls(self):
        class Altered:
            def __init__(self, changes): self.changes = changes
            def read(self, name): return self.changes.get(name, TraceTests.z.read(name))
        c, r = self.z.read(M.C_PATH), self.z.read(M.R_PATH)
        for path, raw in [(M.C_PATH,c.replace(b'"cb%u", reg_idx', b'"cb%d", reg_idx')),
                          (M.C_PATH,c+b'\nvkd3d_spirv_build_op_member_name\n'),
                          (M.C_PATH,c.replace(b'name[1024]', b'name[1023]')),
                          (M.R_PATH,r.replace(b'unsafe fn snprintf(', b'unsafe fn removed(')),
                          (M.R_PATH,r.replace(b'                reg_idx,\n', b'                0,\n'))]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                M.sources(Altered({path:raw}))

    def test_string_aware_extraction(self):
        source = 'static void f() { const char *s="}\\\"{"; /* } */ // }\n if (1) { } }\n'
        self.assertEqual(M.extract_function(source,'static void f('),source.rstrip())
        with self.assertRaises(ValueError):
            M.extract_function(source+source,'static void f(')
        with self.assertRaises(ValueError):
            M.extract_function(source[:-3],'static void f(')

    def test_uint_domains_and_all_boundaries(self):
        rows = M.cases()
        tails = {r['tail'] for r in rows if r['domain']=='normal'}
        self.assertTrue({0,1,2**31-1,2**31,2**31+1,M.MASK} <= tails)
        self.assertEqual({r['q'] for r in rows if r['domain']=='normal'}, {1,2,3,4})
        self.assertEqual({r['builder'] for r in rows},{0,1,2})
        for base, maximum in ((2,32),(10,10)):
            for k in range(maximum+1):
                for d in (-1,0,1):
                    v=base**k+d
                    if 0<=v<=M.MASK: self.assertIn(v,tails)
        self.assertEqual(len(M.expected(rows).splitlines()),3+7*len(rows))
        self.assertIn(b'|opcode|6|2|',M.expected([dict(rows[-1],q=M.MASK)]))

    def test_case_malformed_controls(self):
        row=M.cases()[0]
        for key, value in [('tail',-1),('tail',2**32),('q',True),('w',2**32),('builder',3),('domain','unknown')]:
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                M.validate_cases([dict(row,**{key:value})])
        for rows in ([],[{}],[dict(row,extra=1)]):
            with self.assertRaises(ValueError): M.validate_cases(rows)

    def test_duplicate_json_and_cbor_controls(self):
        for raw in ('{"x":1,"x":2}', '{"x":NaN}'):
            with self.assertRaises(ValueError): M.loads(raw)
        for raw in (b'', b'\x18', b'\x80\x00', b'\x63x'):
            with self.assertRaises(ValueError): M.cbor(raw)
        self.assertEqual(M.cbor(b'\x82\x01\x02'),[1,2])

    def test_program_shapes(self):
        programs=M.programs(self.src)
        self.assertEqual(len(programs),8)
        self.assertIn(self.src['original.c'],programs['oracle.c'])
        self.assertIn(self.src['lowered.rs'],programs['stable.rs'])
        self.assertIn('tail.wrapping_add(1)',programs['tail_plus_one.rs'])
        self.assertIn('let _ignored',programs['ignore_w.rs'])
        for name, source in programs.items():
            if name.endswith('.rs'):
                self.assertNotIn('VaList',source)
                self.assertNotIn('#![feature',source)
                self.assertNotIn('c_variadic',source)

    def test_archive_path_controls(self):
        for name in ('../x','/tmp/x','a/../b','a\\b','./a','a//b',''):
            self.assertFalse(M.safe_name(name),name)
        self.assertTrue(M.safe_name('a/b'))
        with self.assertRaises(ValueError):
            M.archive(Path(os.environ['MEMBER_NAME_ALL24']),'setup')

    def test_exact_mutant_traces(self):
        rows = M.cases()
        for mutant in ('tail_plus_one','exchange_ids','missing_word','duplicate_word','ignore_q','ignore_w'):
            value = M.expected(rows,mutant)
            self.assertNotEqual(value,M.expected(rows))
            self.assertEqual(sum(b'|suppliers|' in line for line in value.splitlines()),len(rows))
            self.assertEqual(sum(b'|count|' in line for line in value.splitlines()),len(rows))
            self.assertEqual(sum(b'|opcode|' in line for line in value.splitlines()),len(rows))
        tail = M.expected([next(r for r in rows if r['tail']==M.MASK and r['domain']=='normal')],'tail_plus_one')
        self.assertIn(b'63623000',tail)

    def test_execution_controls(self):
        generated = M.programs(self.src)
        rows = M.cases()
        name, key = 'stable.rs', 'stable.rs-normal'
        binary = b'\x7fELF\x02\x01'+bytes(12)+b'\x3e\x00'+bytes(44)
        packet = {name:generated[name].encode(),key+'.bin':binary,
                  key+'.stdout':M.expected(rows),key+'.stderr':b'',
                  key+'-compile.stdout':b'',key+'-compile.stderr':b''}
        class MemoryPath:
            def __init__(self,name=''):self.name=name
            def __truediv__(self,name):return MemoryPath(name)
            def read_bytes(self):return packet[self.name]
            def is_file(self):return self.name in packet
        env = {'GITHUB_ACTIONS':'true','GITHUB_SHA':'test-fixture','RUNNER_OS':'Linux','RUNNER_ARCH':'X64','PATH':'test-fixture'}
        compile_record = {'argv':['rustc','+1.95.0','--edition=2024','--crate-name','member_name_pilot','-C','opt-level=0',name,'-o',key+'.bin'],
                          'exit_code':0,'start':'2026-01-01T00:00:00+00:00','end':'2026-01-01T00:00:01+00:00',
                          'stdout':key+'-compile.stdout','stderr':key+'-compile.stderr','environment':env,
                          'removed_environment':['RUSTC_BOOTSTRAP','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS']}
        record=dict(compile_record,argv=['./'+key+'.bin'],stdout=key+'.stdout',stderr=key+'.stderr',compile=compile_record,
                    compile_exit_code=0,binary=key+'.bin',binary_sha256=M.sha(binary),source=name,
                    source_sha256=M.sha(packet[name]),input_sha256=M.sha(M.case_input(rows)))
        self.assertEqual(M.verify_execution(MemoryPath(),key,record,rows,generated),0)
        for field,value in [('exit_code',1),('compile_exit_code',1),('binary_sha256','0'*64),('input_sha256','0'*64),('source_sha256','0'*64),('argv',['wrong']),('binary','../outside')]:
            with self.subTest(field=field),self.assertRaises(ValueError):
                M.verify_execution(MemoryPath(),key,dict(record,**{field:value}),rows,generated)
        for value in (M.expected(rows)+b'extra\n', M.expected(rows)[:-1],M.expected(rows[:-1])):
            packet[key+'.stdout']=value
            with self.assertRaises(ValueError):M.verify_execution(MemoryPath(),key,record,rows,generated)
        packet[key+'.stdout']=M.expected(rows)
        bad=copy.deepcopy(record)
        bad['compile']['argv'][1]='+nightly'
        with self.assertRaises(ValueError):M.verify_execution(MemoryPath(),key,bad,rows,generated)
        bad=copy.deepcopy(record)
        bad['environment']['RUSTC_BOOTSTRAP']='1'
        with self.assertRaises(ValueError):M.verify_execution(MemoryPath(),key,bad,rows,generated)

    def test_actual_typed_ast_bindings(self):
        prefix='cursor-witness/raw/src/vkd3d_shader/spirv'
        witness=M.loads(self.z.read(prefix+'.cursor-witness.json'))
        typed=self.z.read(prefix+'.typed-ast.txt').decode()
        result=M.typed_bindings(witness,typed)
        self.assertEqual(result['native_cursors'],7)
        self.assertEqual(result['required_types'],81)
        for old,new in [('platform_byte_size: 24,','platform_byte_size: 23,'),('"va_start"','"invented"')]:
            with self.subTest(old=old),self.assertRaises(ValueError):
                M.typed_bindings(witness,typed.replace(old,new))

    def test_hosted_writers_reject_local_use(self):
        with patch.object(sys,'platform','darwin'),patch('subprocess.run',side_effect=RuntimeError('must not execute')):
            with self.assertRaises(ValueError):M.run_hosted(Path('/unused-test-only'),{})
            with self.assertRaises(ValueError):M.acquire(Path('/unused-test-only'))

    def test_default_path_does_not_execute(self):
        with patch('subprocess.run',side_effect=RuntimeError('must not execute')), patch('urllib.request.urlopen',side_effect=RuntimeError('must not fetch')), patch.object(Path,'write_bytes',side_effect=RuntimeError('must not write')), patch.object(Path,'write_text',side_effect=RuntimeError('must not write')):
            with patch.object(M,'admission',return_value=({'proof':'test-only'},self.src)):
                result=M.replay(None,{})
                self.assertEqual(result['actual_compiled_pilot'],'UNRUN')

    @contextmanager
    def hosted_fixture(self, root, failed_stem=None, failure=None):
        compiler = root.parent/'fixture-compiler'
        compiler.write_bytes(b'fixture compiler, never executed')
        binary = b'\x7fELF\x02\x01'+bytes(12)+b'\x3e\x00'+bytes(44)
        identities = {'rustc':'rustc-identity','cc':'cc-identity','rustup':'pinned-rustc-path'}
        def process(argv, **kwargs):
            self.assertEqual(kwargs['timeout'],120)
            self.assertEqual(kwargs['cwd'],root)
            if argv[0] in identities and '-o' not in argv:
                stem = identities[argv[0]]
                output = (str(compiler)+'\n').encode() if argv[0]=='rustup' else (
                    b'release: 1.95.0\nhost: x86_64-unknown-linux-gnu\n' if argv[0]=='rustc' else b'fixture cc\n')
            elif '-o' in argv:
                stem = argv[-1].removesuffix('.bin')+'-compile'
                output = b''
            else:
                key = argv[0].removeprefix('./').removesuffix('.bin')
                stem = key+'-run'
                source = key.rsplit('-',1)[0]
                mutant = None if source in ('oracle.c','stable.rs') else source.removesuffix('.rs')
                output = M.expected(M.cases(),mutant)
            if stem == failed_stem:
                if isinstance(failure,Exception):
                    raise failure
                return subprocess.CompletedProcess(argv,failure,b'partial stdout',b'command failed')
            if '-o' in argv:
                (root/argv[-1]).write_bytes(binary)
            return subprocess.CompletedProcess(argv,0,output,b'')
        env = {'GITHUB_ACTIONS':'true','GITHUB_SHA':'fixture','RUNNER_OS':'Linux','RUNNER_ARCH':'X64',
               'PATH':'fixture path','RUSTC_BOOTSTRAP':'1','RUSTFLAGS':'bad','CARGO_ENCODED_RUSTFLAGS':'bad'}
        with patch.object(sys,'platform','linux'),patch('platform.machine',return_value='x86_64'), \
             patch.dict(os.environ,env,clear=True),patch.object(M,'admission',return_value=({'fixture':True},self.src)), \
             patch('shutil.which',return_value=str(compiler)),patch('subprocess.run',side_effect=process):
            yield

    def check_hosted_failure(self, stem, failure, status, code):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'packet'
            with self.hosted_fixture(root,stem,failure):
                with self.assertRaises(type(failure) if isinstance(failure,Exception) else ValueError):
                    M.run_hosted(root,{})
                receipt = M.loads((root/(stem+'.command.json')).read_bytes())
                self.assertEqual(receipt['status'],status)
                self.assertEqual(receipt['command']['exit_code'],code)
                self.assertIsNotNone(receipt['failure'])
                if code is None:
                    self.assertEqual(receipt['failure']['kind'],status)
                for path in root.glob('*.command.json'):
                    saved = M.loads(path.read_bytes())
                    command = saved['command']
                    self.assertTrue(command['argv'])
                    self.assertLessEqual(command['start'],command['end'])
                    self.assertTrue(command['end'].endswith('+00:00'))
                    self.assertEqual(set(command['environment']),{'GITHUB_ACTIONS','GITHUB_SHA','RUNNER_OS','RUNNER_ARCH','PATH','LC_ALL'})
                    self.assertEqual(command['environment']['LC_ALL'],'C')
                    self.assertEqual(command['removed_environment'],['RUSTC_BOOTSTRAP','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS'])
                    for field in ('stdout','stderr'):
                        self.assertEqual(saved[field+'_sha256'],M.sha((root/command[field]).read_bytes()))
                self.assertFalse((root/'executions.json').exists())
                with self.assertRaises((ValueError,FileNotFoundError)):
                    M.replay(root,{})
            return receipt

    def test_failed_identity_receipt(self):
        receipt = self.check_hosted_failure('cc-identity',7,'failed',7)
        self.assertEqual(receipt['command']['argv'],['cc','--version'])

    def test_failed_compile_receipt(self):
        receipt = self.check_hosted_failure('oracle.c-normal-compile',23,'failed',23)
        self.assertEqual(receipt['command']['argv'],['cc','-std=c11','-D_POSIX_C_SOURCE=200809L','-O0','oracle.c','-o','oracle.c-normal.bin'])

    def test_failed_execution_receipt(self):
        receipt = self.check_hosted_failure('oracle.c-normal-run',19,'failed',19)
        self.assertEqual(receipt['command']['argv'],['./oracle.c-normal.bin'])

    def test_timeout_partial_output_receipt(self):
        failure = subprocess.TimeoutExpired(['./oracle.c-normal.bin'],120,output=b'partial stdout',stderr=b'partial stderr')
        receipt = self.check_hosted_failure('oracle.c-normal-run',failure,'timeout',None)
        self.assertEqual(receipt['stdout_sha256'],M.sha(b'partial stdout'))
        self.assertEqual(receipt['stderr_sha256'],M.sha(b'partial stderr'))

    def test_launch_failure_receipt(self):
        self.check_hosted_failure('cc-identity',FileNotFoundError('fixture missing compiler'),'launch_error',None)

    def test_successful_replay_cross_checks_command_receipts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'packet'
            with self.hosted_fixture(root):
                result = M.run_hosted(root,{})
                self.assertEqual(result['actual_compiled_pilot'],'PASS retained Linux x64 normal/optimized executions')
                self.assertEqual(len(list(root.glob('*.command.json'))),35)
                path = root/'oracle.c-normal-compile.command.json'
                original = path.read_bytes()
                receipt = M.loads(original)
                changed_command = dict(receipt['command'],argv=['wrong'])
                for changes in ({'status':'failed'}, {'failure':{'kind':'timeout'}},
                                {'command':changed_command}, {'stdout_sha256':'0'*64}):
                    path.write_text(M.json.dumps(dict(receipt,**changes)))
                    (root/'seal.json').write_text(M.json.dumps(M.manifest(root)))
                    with self.subTest(changes=changes),self.assertRaises(ValueError):
                        M.replay(root,{})
                path.unlink()
                (root/'seal.json').write_text(M.json.dumps(M.manifest(root)))
                with self.assertRaises(ValueError):
                    M.replay(root,{})
                path.write_bytes(original)
                (root/'extra.command.json').write_bytes(original)
                (root/'seal.json').write_text(M.json.dumps(M.manifest(root)))
                with self.assertRaises(ValueError):
                    M.replay(root,{})


if __name__ == '__main__':
    unittest.main()
