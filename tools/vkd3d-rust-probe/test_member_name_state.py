"""Compiler-free checks. Synthetic packets never establish compiled acceptance."""
import copy
import json
import subprocess
import sys
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
import member_name_state as S


class ModelTests(unittest.TestCase):
    def test_exact_core_domain(self):
        rows=S.cases()
        self.assertEqual(len(rows),3005)
        self.assertEqual(len({r['tail'] for r in rows[:120]}),120)
        self.assertEqual({(r['count'],r['capacity']) for r in rows[120:3000]}, {(c,k) for k in range(9) for c in range(k+1)})
        self.assertEqual({r['script'] for r in rows[120:3000]},set(range(16)))
        self.assertEqual({(len('cb'+str(r['tail']))+4)//4 for r in rows[120:3000]}, {1,2,3,4})

    def test_empty_success_exact_words_and_growth(self):
        value,diagnostics=S.expected(S.cases()[0])
        self.assertEqual(value['words'],[0x40006,17,29,0x306263])
        self.assertEqual(value['events'],[['realloc',16,1,0,1]])
        self.assertEqual((value['count'],value['capacity'],value['consumed'],value['unused']),(4,4,1,0))
        self.assertEqual(diagnostics,[])

    def test_failed_reserves_continue(self):
        row=dict(kind=0,tail=0,count=0,capacity=0,script=7,bits=4)
        value,diagnostics=S.expected(row)
        self.assertEqual(value['words'],[0x306263])
        self.assertEqual(value['events'],[['realloc',16,0,0,0]]*3+[['realloc',16,1,0,1]])
        self.assertEqual(len(diagnostics),3)
        stop,_=S.expected(row,'stop_after_failure')
        self.assertEqual(stop['words'],[])
        self.assertEqual(stop['consumed'],1)

    def test_prefix_and_unused_suffix(self):
        row=dict(kind=0,tail=0,count=2,capacity=8,script=15,bits=4)
        value,_=S.expected(row)
        self.assertEqual(value['words'][:2],[0x11000000,0x11000001])
        self.assertEqual((value['consumed'],value['unused']),(0,15))

    def test_defined_script_suffix(self):
        row=dict(kind=0,tail=0,count=0,capacity=0,script=15,bits=4)
        value,_=S.expected(row,'duplicate_word')
        self.assertEqual(value['consumed'],5)
        self.assertEqual(value['events'][-1],['realloc',16,1,0,1])
        self.assertEqual(value['unused'],0)

    def test_distinct_init_and_overflow(self):
        success,failed,continued,all_failed,overflow=[S.expected(r)[0] for r in S.cases()[3000:]]
        self.assertEqual(success['events'],[['calloc',1024,1,0,1]])
        self.assertEqual(success['capacity'],256)
        self.assertEqual(failed['capacity'],0)
        self.assertEqual(continued['count'],4)
        self.assertEqual(all_failed['count'],0)
        self.assertEqual(all_failed['consumed'],5)
        self.assertEqual(overflow['events'],[])
        self.assertEqual(overflow['overflow'],1)

    def test_all_finite_mutant_bounds_and_lifetimes(self):
        rows=S.cases()
        for mutant in (None,)+S.MUTANTS:
            differences=0
            for row in rows:
                value,diagnostics=S.expected(row,mutant)
                self.assertLessEqual(value['consumed'],4+int(mutant=='duplicate_word')+int(row['kind']==2))
                self.assertEqual(len(diagnostics),sum(not e[2] for e in value['events']))
                self.assertEqual(len(value['words']),value['count'])
                self.assertLessEqual(value['count'],value['capacity'])
                token=int(row['capacity']!=0)
                for _,size,ok,old,new in value['events']:
                    self.assertEqual(old,token)
                    self.assertLessEqual(size,1024)
                    if ok:
                        self.assertEqual(new,token+1)
                    else:
                        self.assertEqual(new,token)
                    token=new
                self.assertEqual(value['free_token'],token)
                differences+=value!=S.expected(row)[0]
            self.assertEqual(bool(differences),mutant is not None)

    def test_poison_makes_padding_control_defined(self):
        row=S.cases()[0]
        value,_=S.expected(row,'missing_padding')
        self.assertEqual(value['words'][-1],0xa5306263)

    def test_default_requires_packet(self):
        with self.assertRaisesRegex(ValueError,'complete sealed packet'):
            S.replay(None,{})

    def test_guard_rejects_effects(self):
        for event,args in [('open',('/tmp/state-proof','w',os.O_CREAT)),('os.mkdir',('/tmp/state-proof',)),('subprocess.Popen',('true',)),('socket.getaddrinfo',('localhost',))]:
            with self.assertRaisesRegex(ValueError,'read-only replay'):
                S.guard(event,args)
        S.guard('open',('/tmp/state-proof','r',os.O_RDONLY))

    def test_actual_guard_blocks_write_process_and_network(self):
        folder=str(Path(S.__file__).parent)
        for action in ("open('/tmp/member-state-must-not-exist','w')", "os.mkdir('/tmp/member-state-must-not-exist')", "subprocess.run(['unreachable-member-state'])", "socket.getaddrinfo('localhost',80)"):
            code="import sys,os,subprocess,socket;sys.path.insert(0,"+repr(folder)+");import member_name_state as S;sys.addaudithook(S.guard);"+action
            result=subprocess.run([sys.executable,'-B','-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertNotEqual(result.returncode,0)
            self.assertIn(b'read-only replay',result.stderr)

    def test_output_packet_corruptions_are_rejected(self):
        rows=[dict(kind=0,tail=0,count=0,capacity=0,script=15,bits=4)]
        layouts=[dict(layout=n,size=32,alignment=8,offsets=[0]*{'vkd3d_spirv_builder':28,'vkd3d_spirv_stream':4,'vkd3d_spirv_chunk':4,'list':2,'rb_tree':2,'rb_entry':4}[n]) for n in ('vkd3d_spirv_builder','vkd3d_spirv_stream','vkd3d_spirv_chunk','list','rb_tree','rb_entry')]
        wanted,diagnostics=S.expected(rows[0])
        output=[dict(tid=123)]+layouts+[wanted]
        errors='CASE 0 BEGIN\n'+''.join('vkd3d:123:err:vkd3d:'+f+' '+m+'\n' for f,m in diagnostics)+'CASE 0 END\n'
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            def write(value,stderr=errors):
                (root/'test-run.stdout').write_text(''.join(json.dumps(r)+'\n' for r in value))
                (root/'test-run.stderr').write_text(stderr)
            write(output)
            S.verify_output(root,'test',rows,None)
            for field,value in [('count',True),('token',1),('events',[]),('words',[99]),('free_token',1),('unused',15)]:
                broken=copy.deepcopy(output)
                broken[-1][field]=value
                write(broken)
                with self.assertRaises(ValueError):
                    S.verify_output(root,'test',rows,None)
            write(output[:-1])
            with self.assertRaisesRegex(ValueError,'complete output'):
                S.verify_output(root,'test',rows,None)
            write(output,errors.replace('vkd3d:123:', 'vkd3d:124:',1))
            with self.assertRaisesRegex(ValueError,'diagnostic TID'):
                S.verify_output(root,'test',rows,None)

    def test_manifest_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'data').write_bytes(b'bound')
            (root/'alias').symlink_to(root/'data')
            with self.assertRaisesRegex(ValueError,'packet symlink'):
                S.packet_manifest(root)

    def test_duplicate_json_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate JSON'):
            S.loads('{"a":1,"a":2}')


class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=os.environ.get('MEMBER_NAME_ALL24')
        S.need(path,'MEMBER_NAME_ALL24 must identify fixed admitted archive')
        with zipfile.ZipFile(path) as z:
            src=S.P.sources(z)
            cls.native,cls.rust,cls.bindings,cls.files,cls.macros=S.closure(z,src)
            cls.generated=S.programs(cls.native,cls.rust)
            cls.originals={p:z.read(p).decode() for p in {b['path'] for b in cls.bindings}}

    def test_exact_spans_dependencies_and_inverse(self):
        for b in self.bindings:
            original=self.originals[b['path']]
            text=original[b['start']:b['end']]
            self.assertEqual(S.sha(text.encode()),b['sha256'])
            self.assertEqual(original[:b['start']]+text+original[b['end']:],original)
            self.assertTrue(b['dependencies'])
        self.assertEqual(len(self.bindings),59)
        self.assertIn('-DVKD3D_DEBUG_ENV=VKD3D_SHADER_DEBUG',self.macros)

    def test_genuine_closure_and_separate_namespaces(self):
        self.assertIn('mod memory {',self.rust)
        self.assertIn('mod spirv {',self.rust)
        self.assertEqual(self.rust.count('static mut vkd3d_debug_channel_default:'),2)
        self.assertIn('VKD3D_SHADER_DEBUG',self.rust)
        self.assertIn('VKD3D_DEBUG\\0',self.rust)
        self.assertIn('#[repr(C)]\npub struct vkd3d_spirv_builder',self.rust)
        self.assertIn('pub numeric_type_ids: [[uint32_t; 4]; 18]',self.rust)
        self.assertIn('pub type rb_compare_func = Option<',self.rust)
        self.assertIn('external/spirv/unified1/spirv.h',self.files)
        self.assertIn('native/libs/vkd3d-common/debug.c',self.files)
        self.assertNotIn('VaList',self.rust)
        self.assertNotIn('c2rust_args',self.rust)
        self.assertNotIn('#![feature',self.rust)

    def test_mutants_have_exact_permitted_sources(self):
        self.assertEqual(set(self.generated), {'oracle.c','stable.rs','harness.c'}|{m+'.rs' for m in S.MUTANTS})
        for mutant in S.MUTANTS:
            self.assertNotEqual(self.generated[mutant+'.rs'],self.generated['stable.rs'])
        self.assertIn('MaybeUninit::<vkd3d_spirv_builder>::zeroed()',S.R_RUN)
        self.assertNotIn('assume_init',S.R_RUN)
        self.assertNotIn('realloc(p,size); assert(p',S.HARNESS)

    def test_complete_command_plan_and_object_bindings(self):
        plan=S.command_plan(self.generated)
        self.assertEqual(len(plan),41)
        self.assertEqual(len({s for s,_,_ in plan}),41)
        objects=[(stem,argv) for stem,argv,_ in plan if stem.endswith('-object')]
        self.assertEqual(len(objects),6)
        for stem,argv in objects:
            self.assertEqual('-Drealloc=probe_realloc' in argv,stem.startswith('memory'))
        for stem,argv,stdin in plan:
            if stem.endswith('-run'):
                self.assertEqual(stdin,'input.txt')
            if stem.endswith('-compile'):
                self.assertIn('debug-'+('optimized' if 'optimized' in stem else 'normal')+'.o',' '.join(argv))

    def test_missing_wrong_duplicate_extra_receipts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'commands.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'complete command inventory'):
                S.verify_commands(root,S.command_plan(self.generated))
            (root/'commands.json').write_text('{"wrong":{}}')
            with self.assertRaisesRegex(ValueError,'complete command inventory'):
                S.verify_commands(root,[])
            (root/'commands.json').write_text('{"x":{},"x":{}}')
            with self.assertRaisesRegex(ValueError,'duplicate JSON'):
                S.verify_commands(root,[])
            (root/'commands.json').write_text('{}')
            (root/'extra.command.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'individual command receipt coverage'):
                S.verify_commands(root,[])

    def test_individual_receipt_identity_and_status_controls(self):
        import datetime
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            stem='rustc-identity'
            argv=['rustc','+1.95.0','-vV']
            now=datetime.datetime.now(datetime.timezone.utc).isoformat()
            env=dict(GITHUB_ACTIONS='true',GITHUB_SHA='a'*40,RUNNER_OS='Linux',RUNNER_ARCH='X64',PATH='/synthetic',LC_ALL='C')
            command=dict(argv=argv,cwd='/synthetic',start=now,end=now,exit_code=0,stdout=stem+'.stdout',stderr=stem+'.stderr',environment=env,removed_environment=list(S.REMOVED),input_sha256=None)
            output=b'release: 1.95.0\nhost: x86_64-unknown-linux-gnu\n'
            receipt=dict(status='succeeded',command=command,failure=None,stdout_sha256=S.sha(output),stderr_sha256=S.sha(b''))
            (root/'host.json').write_text(json.dumps(dict(cwd='/synthetic',source_head='a'*40)))
            (root/'compilers.json').write_text(json.dumps({k:dict(path='/synthetic/'+k,sha256='b'*64) for k in ('cc','rustc')}))
            (root/(stem+'.stdout')).write_bytes(output)
            (root/(stem+'.stderr')).write_bytes(b'')
            def write(value):
                (root/'commands.json').write_text(json.dumps({stem:command}))
                (root/(stem+'.command.json')).write_text(json.dumps(value))
            write(receipt)
            S.verify_commands(root,[(stem,argv,None)])
            for key,value in [('status','failed'),('failure',dict(kind='timeout')),('stdout_sha256','0'*64),('stderr_sha256','0'*64)]:
                broken=copy.deepcopy(receipt);broken[key]=value;write(broken)
                with self.assertRaises(ValueError):
                    S.verify_commands(root,[(stem,argv,None)])
            for key,value in [('argv',['wrong']),('cwd','/wrong'),('exit_code',False),('removed_environment',[]),('input_sha256','wrong')]:
                broken=copy.deepcopy(receipt);broken['command'][key]=value;write(broken)
                with self.assertRaises(ValueError):
                    S.verify_commands(root,[(stem,argv,None)])
            write(receipt)
            (root/(stem+'.stdout')).write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError,'raw output hash'):
                S.verify_commands(root,[(stem,argv,None)])

    def test_bad_source_and_extraction_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'unique Rust item'):
            S.rust_item('pub type size_t=usize;\npub type size_t=usize;','size_t','type')
        with self.assertRaisesRegex(ValueError,'unique semantic mutant'):
            S.programs(self.native,self.rust.replace('        tail,\n','        other,\n'))


if __name__=='__main__':
    unittest.main()
