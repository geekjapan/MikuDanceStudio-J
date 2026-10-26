#!/usr/bin/env python3
"""Compile the unchanged native solver and compare operation-level Rust state."""
import argparse
import gzip
import hashlib
import json
import os
import platform
from pathlib import Path
import subprocess
from cases import corpus

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent
SOURCES={
    'btVoronoiSimplexSolver.cpp':'2e7ea24a8ce2d7b13c4bf679b9012c3c352e5742f0ecae1d0ba86b413363c98b',
    'btVoronoiSimplexSolver.h':'0ffe4a05d40157945e14a1baa6439b612cb6ba86bffb7c48bccec1b3bae35ba5',
}


def run(command, **kwargs):
    return subprocess.run(list(map(str,command)), cwd=ROOT/'rust', check=True, **kwargs)


def compare(expected, actual, label):
    a,b=expected.splitlines(),actual.splitlines()
    if a!=b:
        mismatch=next((i for i,(x,y) in enumerate(zip(a,b)) if x!=y),min(len(a),len(b)))
        raise AssertionError(f'{label} differs at operation {mismatch}: native={a[mismatch:mismatch+1]} rust={b[mismatch:mismatch+1]}')


def coverage(rows, labels):
    regions={n:set() for n in [2,3,4]}
    thresholds={}
    rows=rows.decode().splitlines()
    for label in labels:
        state=next(line.split() for line in rows[label['start']:label['end']] if line.startswith(('C ','P ')))
        if label['size'] in regions:
            regions[label['size']].add(''.join(state[8:12]))
        if label['name'].startswith('degeneracy-exact-signd-'):
            thresholds[label['name']]=int(state[7])
    expected={2:{'1000','0100','1100'},3:{'1000','0100','1100','0010','1010','0110','1110'},4:{format(n,'04b') for n in range(1,16)}}
    assert regions==expected, f'missing simplex regions: {regions}'
    assert thresholds=={'degeneracy-exact-signd--1':1,'degeneracy-exact-signd-0':0,'degeneracy-exact-signd-1':0}
    return {'usage_masks':{n:sorted(v) for n,v in regions.items()},'threshold_degenerate':thresholds}


def selected_fixture(inputs, captured, labels, name):
    # Keep the contiguous structured prefix so retained caches remain native-derived.
    selected = labels if name == 'nonfinite' else [label for label in labels if not label['name'].startswith('random-')]
    end = selected[-1]['end']
    selected_input = b''.join(inputs.splitlines(keepends=True)[:end])
    selected_native = b''.join(captured.splitlines(keepends=True)[:end])
    provenance = {
        'selection': 'complete contiguous structured prefix; singleton seeded',
        'scenarios': len(selected), 'operations': end,
        'labels': [label['name'] for label in selected],
        'input_sha256': hashlib.sha256(selected_input).hexdigest(),
        'native_sha256': hashlib.sha256(selected_native).hexdigest(),
        'full_input_sha256': hashlib.sha256(inputs).hexdigest(),
        'full_native_sha256': hashlib.sha256(captured).hexdigest(),
    }
    if name == 'finite':
        provenance['coverage'] = coverage(selected_native, selected)
    return selected_input, selected_native, provenance


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--record',action='store_true')
    args=parser.parse_args()
    out=args.out_dir.resolve()
    out.mkdir(parents=True,exist_ok=True)
    src=ROOT/'recipes/bullet275/bullet-src/src'
    narrow=src/'BulletCollision/NarrowPhaseCollision'
    for name,sha in SOURCES.items():
        assert hashlib.sha256((narrow/name).read_bytes()).hexdigest()==sha, f'{name} changed'
    shim=ROOT/'rust/crates/mds-bullet-sys/shim'
    crt=ROOT/'rust/crates/mds-crtmath/src/lib.rs'
    rustc=['rustup','run','1.95.0','rustc','--edition=2021','-O']
    for kind,filename in [('staticlib','libmds_crtmath.a'),('rlib','libmds_crtmath.rlib')]:
        run([*rustc,'--crate-name','mds_crtmath','--crate-type',kind,crt,'-o',out/filename])
    command=[os.environ.get('CXX','clang++'),'-std=c++17','-O2','-ffp-contract=off','-fno-fast-math','-fdeclspec','-w','-DBT_NO_PROFILE=1','-I',shim/'sse_emu','-I',src,'-I',shim,'-include',shim/'det_math.h',HERE/'oracle.cpp',narrow/'btVoronoiSimplexSolver.cpp',src/'LinearMath/btAlignedAllocator.cpp',out/'libmds_crtmath.a','-o',out/'native-simplex']
    (out/'native-command.txt').write_text(' '.join(map(str,command))+'\n')
    run(command)
    external=['--extern',f'mds_crtmath={out / "libmds_crtmath.rlib"}']
    run([*rustc,'-D','warnings',HERE/'harness.rs',*external,'-o',out/'rust-simplex'])
    run([*rustc,'--test','-D','warnings',HERE/'harness.rs',*external,'-o',out/'rust-simplex-tests'])
    run([out/'rust-simplex-tests'])
    fixture_hashes={}
    selected_provenance={}
    summary={ 'source_sha256':SOURCES, 'host':platform.platform(),
        'rustc':subprocess.check_output(['rustup','run','1.95.0','rustc','--version'],text=True).strip(),
        'cxx':subprocess.check_output([os.environ.get('CXX','clang++'),'--version'],text=True).splitlines()[0], 'nan_comparison':'classification only; every non-NaN f32 uses raw bits', 'cases':{} }
    for name,exceptional in [('finite',False),('nonfinite',True)]:
        inputs,labels=corpus(exceptional)
        (out/f'{name}-inputs.tsv').write_bytes(inputs)
        captured=subprocess.check_output([out/'native-simplex'],input=inputs)
        (out/f'{name}-native.tsv').write_bytes(captured)
        actual=subprocess.check_output([out/'rust-simplex',out/f'{name}-inputs.tsv'])
        (out/f'{name}-rust.tsv').write_bytes(actual)
        compare(captured,actual,name)
        fixture=HERE/'fixtures'/f'{name}.tsv.gz'
        if args.record: fixture.write_bytes(gzip.compress(captured,mtime=0))
        assert gzip.decompress(fixture.read_bytes())==captured, f'{name} native fixture changed'
        (out/f'{name}-labels.json').write_text(json.dumps(labels,indent=2)+'\n')
        selected_input, selected_native, selected_provenance[name] = selected_fixture(inputs, captured, labels, name)
        selected_dir = ROOT/'rust/crates/mds-bullet/tests/simplex_data'
        for suffix, data in [('inputs', selected_input), ('native', selected_native)]:
            selected_path = selected_dir/f'{name}-{suffix}.tsv'
            if args.record: selected_path.write_bytes(data)
            assert selected_path.read_bytes() == data, f'{name} selected {suffix} differs from native capture'
        run([out/'rust-simplex', selected_dir/f'{name}-inputs.tsv', selected_dir/f'{name}-native.tsv'])
        fixture_hashes[name]={'input_sha256':hashlib.sha256(inputs).hexdigest(),'decoded_sha256':hashlib.sha256(captured).hexdigest(),'gzip_sha256':hashlib.sha256(fixture.read_bytes()).hexdigest()}
        summary['cases'][name]={'scenarios':len(labels),'operations':len(captured.splitlines())}
        if name=='finite': summary['coverage']=coverage(captured,labels)
    manifest=HERE/'fixtures'/'sha256.json'
    if args.record: manifest.write_text(json.dumps(fixture_hashes,indent=2)+'\n')
    assert json.loads(manifest.read_text())==fixture_hashes, 'fixture provenance differs'
    summary['fixture_sha256']=fixture_hashes
    selected_manifest = ROOT/'rust/crates/mds-bullet/tests/simplex_data/provenance.json'
    if args.record: selected_manifest.write_text(json.dumps(selected_provenance, indent=2)+'\n')
    assert json.loads(selected_manifest.read_text()) == json.loads(json.dumps(selected_provenance)), 'selected native provenance differs'
    summary['selected'] = selected_provenance
    original=(ROOT/'rust/crates/mds-bullet/src/core/simplex.rs').read_text()
    mutation=original.replace('self.cached_v = self.cached_p1.sub(self.cached_p2);','self.cached_v = self.vertices[0].w;',1)
    assert mutation!=original
    (out/'mutant.rs').write_text(mutation)
    harness=(HERE/'harness.rs').read_text().replace('../../rust/crates/mds-bullet/src/core/math.rs',str(ROOT/'rust/crates/mds-bullet/src/core/math.rs')).replace('../../rust/crates/mds-bullet/src/core/simplex.rs',str(out/'mutant.rs'))
    harness=harness.replace('../../rust/crates/mds-bullet/tests/pure_bullet/simplex.rs',str(ROOT/'rust/crates/mds-bullet/tests/pure_bullet/simplex.rs'))
    (out/'mutant-harness.rs').write_text(harness)
    run([*rustc,'--crate-name','simplex_mutant',out/'mutant-harness.rs',*external,'-o',out/'rust-mutant'])
    mutant=subprocess.check_output([out/'rust-mutant',out/'finite-inputs.tsv'])
    assert mutant!=(out/'finite-native.tsv').read_bytes(), 'singleton-w mutation survived'
    summary['mutation']='singleton closest uses stored w instead of p-q: detected'
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
