import json
from pathlib import Path
import tempfile
import unittest
from observation import captures,differences,identity,verify


class ObservationTests(unittest.TestCase):
    def test_only_exact_frozen_streams_and_enumerated_arithmetic_words_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);profiles=out/'profiles';profiles.mkdir()
            for name in ['compiler.txt','rust-target.txt','effective-profile.txt']:(out/name).write_text('frozen '+name)
            for name in ['inputs.tsv','original.tsv','native.tsv','rust.tsv']:(out/name).write_text('frozen '+name)
            (out/'source-sha256.json').write_text('{}')
            words=['00000001','ffffffff']+['00000000']*18+['00000000']*5
            # Pool body delta-linear x is word 13 in the complete event.
            native='0\t0\t0\t-1\t-1\t'+'\t'.join(words)+'\n'
            native_words=native.rstrip().split('\t');native_words[13]='7fc00000';native='\t'.join(native_words)+'\n'
            rust_words=native_words[:];rust_words[13]='ffc00000';rust='\t'.join(rust_words)+'\n'
            (out/'native.trace').write_text(native);(out/'rust.trace').write_text(rust)
            inventory=differences(out/'native.trace',out/'rust.trace')
            profile={'name':'bounded-test','identity':identity(out),'captures':captures(out),'producer_sources':{},'differences':inventory,'limit':'exact synthetic test only'}
            profile_path=profiles/'test.json';profile_path.write_text(json.dumps(profile))
            self.assertFalse(verify(out,profiles)['raw_bit_equality'])
            altered=json.loads(json.dumps(profile));altered['legacy_prefix']={'native.trace':{'lines':1,'sha256':'wrong'}}
            profile_path.write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError,'legacy capture prefix differs'):verify(out,profiles)
            profile_path.write_text(json.dumps(profile))
            # Finite, signed-zero, infinity, unrecorded NaN, copy, location and count changes all fail.
            for index,value in [(7,'3f800000'),(7,'80000000'),(7,'7f800000'),(8,'ffc00000'),(13,'7fc00000'),(14,'ffc00000')]:
                changed=rust_words[:];changed[index]=value;(out/'rust.trace').write_text('\t'.join(changed)+'\n')
                with self.assertRaises(ValueError):verify(out,profiles)
            (out/'rust.trace').write_text(rust+rust)
            with self.assertRaises(ValueError):verify(out,profiles)
            (out/'rust.trace').write_text(rust)
            (out/'compiler.txt').write_text('unseen host/compiler')
            with self.assertRaises(ValueError):verify(out,profiles)
            (out/'compiler.txt').write_text('frozen compiler.txt')
            for field,value in [('word',14),('native','ffc00000'),('field','pool[0].delta_angular[0]')]:
                altered=json.loads(json.dumps(profile));altered['differences'][0][field]=value;profile_path.write_text(json.dumps(altered))
                with self.assertRaises(ValueError):verify(out,profiles)

if __name__=='__main__':unittest.main()
