import copy
import json
from pathlib import Path
import unittest

from cases import corpus
from hooks import CORE, NATIVE, OWNER, SHIM, MUTANTS, instrument, inverse, mutate
from trace import bind_inputs, comparison, validate, validate_allocator, validate_physical, decode_json
import check


class MemoryPath:
    def __init__(self, files, name=''):
        self.files, self.name = files, name
    def __truediv__(self, name):
        return MemoryPath(self.files, self.name + ('/' if self.name else '') + str(name))
    def read_bytes(self):
        return self.files[self.name]
    def read_text(self):
        return self.read_bytes().decode().replace('\r\n','\n')
    def write_bytes(self, value):
        self.files[self.name] = value


def synthetic(native=False):
    commands = 'H synthetic injected\nC\nC\nD\nX\n'
    lines = ['O 0 H 0 0 0 1']
    zero = ' '.join(['00000000']*48)
    def body(row, i):
        return f'B {row} {i} 0 1 {i+1} 1 -1 {i} {zero}'
    for row, count in [(1,1),(2,2)]:
        lines.append(f'O {row} C {count} 0 0 1')
        lines.extend(body(row,i) for i in range(count))
    lines.extend(['E 3 A+ 1','E 3 M+ 1 0 1','O 3 D 2 1 1 1',body(3,0),body(3,1),
                  'P 3 0 0 1 1','M 3 0 1 1 0 1 00000000 00000000 0',
                  'E 4 U 1','E 4 M- 1','E 4 A- 1','E 4 U 0','O 4 X 0 0 0 1','Z 5'])
    if native:
        target=[]
        counts={0:0,1:1,2:2,3:2}
        for i,line in enumerate(lines):
            target.append(line)
            row=int(line.split()[1])
            if row in counts and line.split()[0]!='E' and (i+1==len(lines) or int(lines[i+1].split()[1])!=row):
                count=counts[row]
                nodes=[]
                if count==2:nodes.append('-1 128 '+ ' '.join(['00000000']*6))
                nodes.extend(f'{j} {256+j*128} '+ ' '.join(['00000000']*6) for j in range(count))
                target.append(f'T {row} 0 {len(nodes)} '+ ' '.join(nodes)+(' ' if nodes else '')+'0')
                target.append(f'T {row} 1 0 0')
        lines=target
    return commands, ('\n'.join(lines)+'\n').encode()


class SourceControls(unittest.TestCase):
    def test_complete_synthetic_lifetimes_and_no_manifold_algorithm(self):
        commands, raw = synthetic()
        rows=validate(raw,commands)
        self.assertEqual(rows[3]['pairs'],[[0,1,1]])
        changed=raw.replace(b'E 3 M+ 1 0 1\n',b'').replace(b' D 2 1 1 1',b' D 2 1 0 1').replace(b'M 3 0 1 1 0 1 00000000 00000000 0\n',b'').replace(b'E 4 M- 1\n',b'')
        self.assertEqual(len(validate(changed,commands)[3]['manifolds']),0)

    def test_missing_extra_corrupt_operation_and_lifetime_reject(self):
        commands,raw=synthetic()
        controls=[raw.replace(b'O 1 C 1 0 0 1\n',b''),raw+b'\n',raw.replace(b'O 2 C',b'O 2 D'),
                  raw.replace(b'E 4 M- 1\n',b''),raw.replace(b'E 4 U 1',b'E 4 U 0'),
                  raw.replace(b'P 3 0 0 1 1',b'P 3 0 0 1 2'),raw.replace(b'00000000',b'0000000g',1),
                  raw.replace(b'Z 5',b'Z 4'),raw.replace(b'B 2 1 ',b'B 2 0 '),raw.replace(b'E 3 A+ 1',b'E 3 A+ 2')]
        for changed in controls:
            with self.subTest(changed=changed[-30:]),self.assertRaises(ValueError): validate(changed,commands)

    def test_native_leaf_owner_and_cached_free_rank_binding(self):
        commands,raw=synthetic(True)
        rows=validate(raw,commands,native=True)
        bound=bind_inputs(commands,rows)
        self.assertEqual(bound.count('BIND'),4)
        for old,new in [(b'-1 128',b'-1 256'),(b'1 384',b'0 384')]:
            with self.assertRaises(ValueError):validate(raw.replace(old,new),commands,native=True)
        self.assertEqual(comparison(rows),comparison(validate(synthetic()[1],commands)))

    def test_allocator_rejects_orphan_free_and_false_mode(self):
        rows=validate(b'O 0 H 0 0 0 1\nO 1 X 0 0 0 1\nZ 2\n','H x public\nX\n')
        header={'schema':1,'mode':'ascending','arena_base':4096,'slots':65536,'stride':128,'node_bytes':56,'raw_node_bytes':79,'node_type_alignment':8}
        records=[header,*[{'kind':kind,'counters':[0,0,0,0],'events':[]} for kind in [0,1,'final']]]
        raw=lambda:('\n'.join(json.dumps(r) for r in records)+'\n').encode()
        validate_allocator(raw(),rows,'ascending')
        records[1]['events']=[{'op':'free','route':'raw','pointer':4096,'ordinal':1}]
        with self.assertRaises(ValueError):validate_allocator(raw(),rows,'ascending')
        records[1]['events']=[]
        with self.assertRaises(ValueError):validate_allocator(raw(),rows,'descending')

    def test_allocator_live_node_prefix_and_full_free_are_required(self):
        rows=[{'trees':[[[[0,4112,*(['00000000']*6)]],0],[[],0]]},{'trees':[]}]
        records=[{'schema':1,'mode':'ascending','arena_base':4096,'slots':65536,'stride':128,'node_bytes':56,'raw_node_bytes':79,'node_type_alignment':8},
                 {'kind':0,'counters':[1,0,0,0],'events':[{'op':'alloc','route':'raw','ordinal':1,'pointer':4096,'size':79,'alignment':0}]},
                 {'kind':1,'counters':[1,1,0,0],'events':[{'op':'free','route':'raw','ordinal':1,'pointer':4096}]},
                 {'kind':'final','counters':[1,1,0,0],'events':[]}]
        raw=lambda value:('\n'.join(json.dumps(v) for v in value)+'\n').encode()
        validate_allocator(raw(records),rows,'ascending')
        for field,value in [('ordinal',2),('pointer',4224),('size',80),('alignment',16)]:
            changed=copy.deepcopy(records);changed[1]['events'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate_allocator(raw(changed),rows,'ascending')
        changed=copy.deepcopy(records);changed[2]['events']=[]
        with self.assertRaises(ValueError):validate_allocator(raw(changed),rows,'ascending')

    def test_policy_classifier_rejects_unknown_mixed_and_incomplete_bodies(self):
        parameters='const btDbvtAabbMm& a, const btDbvtAabbMm& b'
        generic='Intersect('+parameters+'){return 1;} Select('+parameters+', int c){return Proximity();} Merge('+parameters+', int c){return 2;}'
        sse=generic.replace('return 1;', 'return _mm_cmplt_ps();').replace('return Proximity();','return _mm_cmple_ss();').replace('return 2;','return _mm_min_ps();')
        self.assertEqual(check.policy(generic)['policy'],'generic-reference')
        self.assertEqual(check.policy(sse)['policy'],'mmd-win64-sse')
        for changed in [generic+generic,generic[:-1],generic.replace('Proximity','Other'),sse.replace('_mm_min_ps','Other')]:
            with self.assertRaises(ValueError):check.policy(changed)

    def test_capture_inventory_rejects_missing_extra_corrupt_and_unsafe_paths(self):
        good={'source/a.cpp':'a'*64,'native.stdout':'b'*64}
        check.inventory(good,dict(good))
        with self.assertRaisesRegex(ValueError,'duplicate'):
            decode_json('{"status":"FAIL","status":"CONTROLLED_PASS"}')
        for expected,actual in [(good,{'source/a.cpp':'a'*64}),(good,{**good,'extra':'c'*64}),(good,{**good,'native.stdout':'c'*64}),({'../escape':'a'*64},{'../escape':'a'*64}),({'a':'INVALID'},{'a':'INVALID'})]:
            with self.assertRaises(ValueError):check.inventory(expected,actual)

    def test_native_physical_timing_is_separate_and_reverse_ordered(self):
        commands='H x public\nC\nC\nJ\nX\n'
        raw=b'JOINT_CREATE 3 0 123\nPHYSICAL 4 joint 123 -1\nPHYSICAL 4 body 456 1\nPHYSICAL 4 body 789 0\n'
        validate_physical(raw,commands)
        for changed in [raw.replace(b'joint 123',b'joint 999'),raw.replace(b'456 1',b'456 0'),raw.splitlines(keepends=True)[0]+b''.join(raw.splitlines(keepends=True)[2:])]:
            with self.assertRaises(ValueError):validate_physical(changed,commands)

    def test_actual_source_hook_inverse_lf_and_windows_transport(self):
        touched=[OWNER,CORE+'dispatcher.rs',CORE+'world_objects.rs',NATIVE+'btCollisionDispatcher.cpp',NATIVE+'btCollisionWorld.cpp',SHIM]
        for windows in [False,True]:
            originals={path:(check.ROOT/path).read_bytes().replace(b'\r\n',b'\n') for path in touched}
            if windows:originals={path:raw.replace(b'\n',b'\r\n') for path,raw in originals.items()}
            memory=MemoryPath(copy.deepcopy(originals))
            changes=instrument(memory,check.HERE)
            inverse(memory,changes,originals)
            for name in MUTANTS:
                mutant=MemoryPath(copy.deepcopy(memory.files));edits=mutate(mutant,name)
                self.assertEqual(len(edits),1)
                self.assertNotEqual(mutant.files[OWNER],memory.files[OWNER])
            memory.files[OWNER]+=b'corrupt'
            with self.assertRaises(ValueError):inverse(memory,changes,originals)

    def test_corpus_reaches_boundaries_and_preserves_public_fixture_separation(self):
        inputs,cases=corpus()
        names={c['name'] for c in cases}
        self.assertTrue({f'shapes-{a}-{b}' for a in range(4) for b in range(4)}<=names)
        self.assertTrue({f'force-{f}-activation-{a}' for f in (0,1) for a in range(6)}<=names)
        commands=inputs.splitlines()
        for case in cases:
            self.assertEqual(commands[case['start']].split()[0],'H')
            self.assertEqual(commands[case['end']],'X')
            if case['scope']=='public':self.assertFalse(any(line.split()[0] in {'A','I','V'} for line in commands[case['start']:case['end']]))
        import struct
        f32=lambda f:struct.unpack('<f',struct.pack('<f',f))[0]
        squared=[]
        for extent in [499999.9375,499999.96875,500000.0]:
            diagonal=f32(2*f32(extent+f32(.02)))
            squared.append(f32(f32(diagonal*diagonal)+f32(2.04*2.04*2)))
        self.assertLess(squared[0],f32(1e12));self.assertEqual(squared[1],f32(1e12));self.assertGreater(squared[2],f32(1e12))


def load_tests(loader, tests, pattern):
    from test_evidence import AdmissionControls
    tests.addTests(loader.loadTestsFromTestCase(AdmissionControls))
    return tests


if __name__=='__main__':
    unittest.main()
