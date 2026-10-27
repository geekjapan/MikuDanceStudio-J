"""Exact paired observations for measured arithmetic NaN choices, without normalization."""
import hashlib
import itertools
import json
from pathlib import Path


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def schema_fields(fields):
    labels=['case','step','kind','iteration','index'];cursor=5
    def count(label):
        nonlocal cursor
        labels.append(label);value=int(fields[cursor],16);cursor+=1
        if value > len(fields):raise ValueError('schema count exceeds capture width')
        return value
    def add(names):
        nonlocal cursor
        labels.extend(names);cursor+=len(names)
    vectors=['inverse_mass','angular_factor','delta_linear','delta_angular','push_velocity','turn_velocity']
    for i in range(count('pool.count')):
        add([f'pool[{i}].original']+[f'pool[{i}].{name}[{axis}]' for name in vectors for axis in range(3)])
    for group in ['joint','normal','friction']:
        for i in range(count(group+'.count')):
            names=['body_a','body_b']+[f'{name}[{axis}]' for name in ['normal','angular_a','angular_b','component_a','component_b'] for axis in range(3)]+['diagonal_inverse','rhs','cfm','lower','upper','applied']
            names += {'joint':['push','friction','penetration_rhs','consecutive','friction_index','null_point'],'normal':['manifold','point','friction','push','penetration_rhs','friction_index'],'friction':['normal_index','push','friction','penetration_rhs','consecutive','null_point']}[group]
            add([f'{group}[{i}].{name}' for name in names])
    for i in range(count('body.count')):add([f'body[{i}].word[{n}]' for n in range(71)])
    for mi in range(count('manifold.count')):
        for pi in range(count(f'manifold[{mi}].count')):add([f'manifold[{mi}].point[{pi}].word[{n}]' for n in range(29)])
    if cursor != len(fields):raise ValueError('schema length differs')
    return labels


def differences(native,rust):
    result=[]
    with native.open() as a,rust.open() as b:
        for line,(x,y) in enumerate(itertools.zip_longest(a,b),1):
            if x==y:continue
            if x is None or y is None:raise ValueError('capture event count differs')
            xx,yy=x.rstrip('\n').split('\t'),y.rstrip('\n').split('\t')
            if xx[:5]!=yy[:5] or len(xx)!=len(yy):raise ValueError('capture event shape differs')
            labels=schema_fields(xx)
            for word,(u,v) in enumerate(zip(xx,yy)):
                if u!=v:result.append({'line':line,'event':list(map(int,xx[:5])),'word':word,'field':labels[word],'native':u,'rust':v})
    return result


def identity(out):
    names = ['compiler.txt','rust-target.txt','effective-profile.txt']
    if (out/'compiler-banner.txt').is_file():names.append('compiler-banner.txt')
    return {name:(out/name).read_text() for name in names}


def captures(out):
    return {name:digest(out/name) for name in ['inputs.tsv','original.tsv','native.tsv','rust.tsv','native.trace','rust.trace']}


def select_profile(out,profiles):
    observed_identity=identity(out)
    from integrity import regular_path
    here=Path(__file__).resolve().parent;root=here.parents[1]
    candidates=[json.loads(regular_path(profiles.parent,p).read_text()) for p in profiles.glob('*.json')]
    candidates=[p for p in candidates if p['identity']==observed_identity]
    if not candidates:raise ValueError('unknown or ambiguous arithmetic observation host/toolchain profile')
    source_manifest=json.loads((out/'source-sha256.json').read_text())
    normalized={name.replace('\\','/'):value for name,value in source_manifest.items()}
    if len(normalized)!=len(source_manifest):raise ValueError('ambiguous source manifest paths')
    candidates=[p for p in candidates if all(normalized.get(name)==value for name,value in p['producer_sources'].items())]
    if not candidates:raise ValueError('arithmetic observation source profile differs')
    if len(candidates)!=1:raise ValueError('unknown or ambiguous arithmetic observation host/toolchain profile')
    expected=candidates[0]
    if expected.get('strict_producer_closure'):
        from integrity import producer_paths, verifier_paths
        producers={p.relative_to(root).as_posix() for p in producer_paths(root)}
        verifiers={regular_path(root,p).relative_to(root).as_posix() for p in verifier_paths(root,out)}
        if set(expected['producer_sources'])!=producers or set(normalized)!=producers|verifiers:
            raise ValueError('arithmetic observation producer closure differs')
        for name in producers:regular_path(root,root/name)
    if any(digest(out/name)!=value for name,value in expected.get('identity_raw',{}).items()):raise ValueError('raw compiler identity differs')
    if any(digest(out/name)!=value for name,value in expected.get('observer_sources',{}).items()):raise ValueError('instrumented observer source differs')
    return expected


def verify(out,profiles):
    expected=select_profile(out,profiles)
    actual_differences=differences(out/'native.trace',out/'rust.trace')
    if actual_differences != expected['differences']:raise ValueError('unknown arithmetic observation field/value/location/count')
    if captures(out)!=expected['captures']:raise ValueError('paired capture differs from its exact frozen stream')
    for name, prefix in expected.get('legacy_prefix', {}).items():
        value=hashlib.sha256()
        with (out/name).open('rb') as stream:
            for _ in range(prefix['lines']):
                line=stream.readline()
                if not line:raise ValueError('truncated legacy capture prefix')
                value.update(line)
        if value.hexdigest()!=prefix['sha256']:raise ValueError('legacy capture prefix differs')
    return {'status':'SOURCE_DEFINED_ARITHMETIC_OBSERVATION','profile':expected['name'],'raw_bit_equality':False,'difference_words':len(actual_differences),'first_difference':actual_differences[0],'limit':expected['limit']}
