import json
from itertools import product
from pathlib import Path
import tempfile
import unittest
from observation import captures,differences,identity,verify,digest,select_profile


class ObservationTests(unittest.TestCase):
    def test_only_exact_frozen_streams_and_enumerated_arithmetic_words_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);profiles=out/'profiles';profiles.mkdir()
            for name in ['compiler.txt','rust-target.txt','effective-profile.txt']:(out/name).write_text('frozen '+name)
            for name in ['inputs.tsv','original.tsv','native.tsv','rust.tsv']:(out/name).write_text('frozen '+name)
            (out/'source-sha256.json').write_text(json.dumps({'source.rs':'frozen'}))
            words=['00000001','ffffffff']+['00000000']*18+['00000000']*5
            # Pool body delta-linear x is word 13 in the complete event.
            native='0\t0\t0\t-1\t-1\t'+'\t'.join(words)+'\n'
            native_words=native.rstrip().split('\t');native_words[13]='7fc00000';native='\t'.join(native_words)+'\n'
            rust_words=native_words[:];rust_words[13]='ffc00000';rust='\t'.join(rust_words)+'\n'
            (out/'native.trace').write_text(native);(out/'rust.trace').write_text(rust)
            inventory=differences(out/'native.trace',out/'rust.trace')
            profile={'name':'bounded-test','identity':identity(out),'captures':captures(out),'producer_sources':{'source.rs':'frozen'},'differences':inventory,'limit':'exact synthetic test only'}
            profile_path=profiles/'test.json';profile_path.write_text(json.dumps(profile))
            self.assertFalse(verify(out,profiles)['raw_bit_equality'])
            (out/'compiler-banner.txt').write_bytes(b'Microsoft compiler 19.44.35229 for x64\r\n')
            windows=json.loads(json.dumps(profile));windows['identity']=identity(out)
            windows['identity_raw']={'compiler-banner.txt':digest(out/'compiler-banner.txt')}
            profile_path.write_text(json.dumps(windows))
            self.assertFalse(verify(out,profiles)['raw_bit_equality'])
            (out/'compiler-banner.txt').write_bytes(b'Microsoft compiler 19.44.35230 for x64\r\n')
            with self.assertRaisesRegex(ValueError,'unknown or ambiguous'):verify(out,profiles)
            (out/'compiler-banner.txt').write_bytes(b'Microsoft compiler 19.44.35229 for x64\n')
            with self.assertRaisesRegex(ValueError,'raw compiler identity'):verify(out,profiles)
            (out/'compiler-banner.txt').unlink();profile_path.write_text(json.dumps(profile))

            (out/'source-sha256.json').write_text(json.dumps({'source.rs':'changed'}))
            with self.assertRaisesRegex(ValueError,'source profile differs'):verify(out,profiles)
            (out/'source-sha256.json').write_text(json.dumps({'source.rs':'frozen'}))
            other=json.loads(json.dumps(profile));other['name']='other-source'
            other['producer_sources']={'source.rs':'other'}
            (profiles/'other.json').write_text(json.dumps(other))
            self.assertEqual(select_profile(out,profiles)['name'],'bounded-test')
            (out/'source-sha256.json').write_text(json.dumps({'source.rs':'other'}))
            self.assertEqual(select_profile(out,profiles)['name'],'other-source')
            other['producer_sources']={'source.rs':'frozen'}
            (profiles/'other.json').write_text(json.dumps(other))
            (out/'source-sha256.json').write_text(json.dumps({'source.rs':'frozen'}))
            with self.assertRaisesRegex(ValueError,'unknown or ambiguous'):select_profile(out,profiles)
            (profiles/'other.json').unlink()
            (out/'source-sha256.json').write_text(json.dumps({'source.rs':'frozen'}))
            altered=json.loads(json.dumps(profile));altered['legacy_prefix']={'native.trace':{'lines':1,'sha256':'wrong'}}
            profile_path.write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError,'legacy capture prefix differs'):verify(out,profiles)
            profile_path.write_text(json.dumps(profile))
            # Finite, signed-zero, infinity, unrecorded NaN, copy, location and count changes all fail.
            for index,value in [(7,'3f800000'),(7,'80000000'),(7,'7f800000'),(8,'ffc00000'),(13,'7fc00000'),(13,'ffc00001'),(14,'ffc00000')]:
                changed=rust_words[:];changed[index]=value;(out/'rust.trace').write_text('\t'.join(changed)+'\n')
                with self.assertRaises(ValueError):verify(out,profiles)
            (out/'native.trace').write_text(rust);(out/'rust.trace').write_text(native)
            with self.assertRaisesRegex(ValueError,'field/value/location/count'):verify(out,profiles)
            (out/'native.trace').write_text(native);(out/'rust.trace').write_text(rust)
            for name in profile['captures']:
                raw=(out/name).read_bytes();(out/name).write_bytes(raw+b'\n')
                with self.assertRaises(ValueError):verify(out,profiles)
                (out/name).write_bytes(raw)
            for name in ['native.trace','rust.trace']:
                raw=(out/name).read_bytes()
                (out/name).write_bytes(raw.replace(b'\r\n',b'\n') if b'\r\n' in raw else raw.replace(b'\n',b'\r\n'))
            with self.assertRaisesRegex(ValueError,'exact frozen stream'):verify(out,profiles)
            (out/'native.trace').write_text(native);(out/'rust.trace').write_text(rust)
            (out/'rust.trace').write_text(rust+rust)
            with self.assertRaises(ValueError):verify(out,profiles)
            (out/'rust.trace').write_text(rust)
            (out/'compiler.txt').write_text('unseen host/compiler')
            with self.assertRaises(ValueError):verify(out,profiles)
            (out/'compiler.txt').write_text('frozen compiler.txt')
            for field,value in [('word',14),('native','ffc00000'),('field','pool[0].delta_angular[0]')]:
                altered=json.loads(json.dumps(profile));altered['differences'][0][field]=value;profile_path.write_text(json.dumps(altered))
                with self.assertRaises(ValueError):verify(out,profiles)

    def test_historical_records_select_exact_recorded_sources_and_reject_unknown_closure(self):
        from check import hooks, SOLVER, ROOT, HERE
        from integrity import verifier_paths, snapshot
        import hashlib
        import subprocess
        import io
        import tarfile
        from unittest.mock import patch
        for (host,count),autocrlf in product([('macarm',1948),('linuxarm',1948),('linuxx64',696),('windows',954)],['false','true']):
            with self.subTest(host=host,autocrlf=autocrlf),tempfile.TemporaryDirectory() as directory:
                out=Path(directory)
                profile=json.loads((HERE/'profiles'/f'{host}-run40426173732-current219.json').read_text())
                measured=profile['measurement']
                archived=measured['all_233_raw_sources']
                verifier_prefix='tools/bullet-rust-mixed-solver-check/'
                archived_verifiers={n for n in archived if n.startswith(verifier_prefix) and Path(n).suffix in {'.py','.json'} and n!=verifier_prefix+'cases.py'}
                producers=set(archived)-archived_verifiers
                source=sorted(producers)[0]
                self.assertEqual(profile['producer_sources'],{n:archived[n] for n in producers})
                self.assertEqual(len(profile['producer_sources']),len(archived)-len(archived_verifiers))
                self.assertEqual(len(archived_verifiers),14)
                self.assertTrue(profile['strict_producer_closure'])
                self.assertEqual(measured['actual_run'],40426173732)
                self.assertEqual(measured['actual_artifact']['host'],host)
                self.assertEqual(measured['difference_words'],count)
                self.assertEqual(len(measured['all_233_raw_sources']),233)
                self.assertEqual(len(profile['captures']),6)
                self.assertEqual(len(profile['differences']),count)
                self.assertEqual(hashlib.sha256(json.dumps(profile['differences'],separators=(',',':')).encode()).hexdigest(),measured['differences_canonical_sha256'])
                old=json.loads((HERE/'profiles'/f'{host}-run40411448747.json').read_text())
                self.assertEqual(profile['captures'],old['captures'])
                self.assertEqual(profile['differences'],old['differences'])
                self.assertEqual(measured['historical_profile'],old['name'])
                self.assertTrue(measured['historical_difference_inventory_and_captures_identical'])
                for name,raw in measured['identity_raw_text'].items():(out/name).write_bytes(raw.encode())
                with patch.dict('os.environ',{'GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'core.autocrlf','GIT_CONFIG_VALUE_0':autocrlf}):
                    archive=subprocess.check_output(['git','-c','core.autocrlf=false','archive',measured['head'],*sorted(producers)],cwd=ROOT)
                with tarfile.open(fileobj=io.BytesIO(archive)) as pinned:
                    for name in sorted(producers):
                        raw=pinned.extractfile(name).read()
                        if host=='windows':raw=raw.replace(b'\n',b'\r\n')
                        self.assertEqual(hashlib.sha256(raw).hexdigest(),profile['producer_sources'][name],name)
                    solver_source=pinned.extractfile(SOLVER.relative_to(ROOT).as_posix()).read().decode()
                observed=hooks(solver_source).encode()
                if host=='windows':observed=observed.replace(b'\n',b'\r\n')
                (out/SOLVER.name).write_bytes(observed)
                sources={**snapshot(ROOT,verifier_paths(ROOT)),**profile['producer_sources']}
                manifest=out/'source-sha256.json'
                manifest.write_text(json.dumps(sources))
                aliases=dict(sources);aliases[source.replace('/','\\')]=sources[source]
                manifest.write_text(json.dumps(aliases))
                with self.assertRaisesRegex(ValueError,'ambiguous source manifest'):select_profile(out,HERE/'profiles')
                manifest.write_text(json.dumps(sources))
                with patch('integrity.producer_paths',return_value=[ROOT/n for n in producers]):
                    self.assertEqual(select_profile(out,HERE/'profiles')['name'],profile['name'])
                verifier=sorted(set(sources)-producers)[0]
                independent=dict(sources,**{verifier:'changed verifier hash'})
                manifest.write_text(json.dumps(independent))
                with patch('integrity.producer_paths',return_value=[ROOT/n for n in producers]):
                    self.assertEqual(select_profile(out,HERE/'profiles')['name'],profile['name'])
                manifest.write_text(json.dumps(sources))
                for closure in [producers|{'unknown.rs'},producers-{source}]:
                    with patch('integrity.producer_paths',return_value=[ROOT/n for n in closure]):
                        with self.assertRaisesRegex(ValueError,'producer closure differs'):select_profile(out,HERE/'profiles')
                for changed in [dict(sources,**{source:'unknown'}),{n:h for n,h in sources.items() if n!=source},dict(sources,**{'unknown.rs':'unknown'})]:
                    manifest.write_text(json.dumps(changed))
                    with self.assertRaisesRegex(ValueError,'source profile differs|producer closure differs'):select_profile(out,HERE/'profiles')
                manifest.write_text(json.dumps(sources))
                (out/SOLVER.name).write_bytes(observed+b'\n')
                with patch('integrity.producer_paths',return_value=[ROOT/n for n in producers]):
                    with self.assertRaisesRegex(ValueError,'observer source differs'):select_profile(out,HERE/'profiles')
                (out/SOLVER.name).write_bytes(observed)
                compiler=out/'compiler.txt';raw=compiler.read_bytes()
                compiler.write_bytes(raw.replace(b'\r\n',b'\n') if b'\r\n' in raw else raw.replace(b'\n',b'\r\n'))
                with patch('integrity.producer_paths',return_value=[ROOT/n for n in producers]):
                    with self.assertRaisesRegex(ValueError,'raw compiler identity differs'):select_profile(out,HERE/'profiles')
                compiler.write_bytes(raw+b'unseen compiler')
                with self.assertRaisesRegex(ValueError,'unknown or ambiguous'):select_profile(out,HERE/'profiles')

    def test_actual_current_source_snapshot_requires_a_matching_profile(self):
        from check import ROOT, HERE
        from integrity import producer_paths, source_paths, snapshot
        producers=snapshot(ROOT,producer_paths(ROOT))
        for host in ['macarm','linuxarm','linuxx64','windows']:
            with self.subTest(host=host),tempfile.TemporaryDirectory() as directory:
                out=Path(directory)
                profile=json.loads((HERE/'profiles'/f'{host}-run40426173732-current219.json').read_text())
                for name,raw in profile['measurement']['identity_raw_text'].items():(out/name).write_bytes(raw.encode())
                manifest=snapshot(ROOT,source_paths(ROOT,out))
                self.assertEqual({n:manifest[n] for n in producers},producers)
                (out/'source-sha256.json').write_text(json.dumps(manifest))
                if producers!=profile['producer_sources']:
                    # The real final gate must reject before reading any numeric capture.
                    with self.assertRaisesRegex(ValueError,'source profile differs|producer closure differs'):
                        verify(out,HERE/'profiles')
                else:
                    from check import SOLVER, hooks
                    (out/SOLVER.name).write_text(hooks(SOLVER.read_text()))
                    self.assertEqual(select_profile(out,HERE/'profiles')['name'],profile['name'])

    def test_actual_msvc_banner_is_required_and_raw_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            for name in ['compiler.txt','rust-target.txt','effective-profile.txt']:(out/name).write_text('same help and target')
            first=identity(out)
            (out/'compiler-banner.txt').write_bytes(b'Microsoft compiler 19.44.35229 for x64\r\n')
            second=identity(out)
            self.assertNotEqual(first,second)
            (out/'compiler-banner.txt').write_bytes(b'Microsoft compiler 19.44.35230 for x64\r\n')
            self.assertNotEqual(second,identity(out))

if __name__=='__main__':unittest.main()
