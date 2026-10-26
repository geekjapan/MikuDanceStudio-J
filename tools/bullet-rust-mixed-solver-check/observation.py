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
        labels.append(label);value=int(fields[cursor],16);cursor+=1;return value
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
    return {name:(out/name).read_text() for name in ['compiler.txt','rust-target.txt','effective-profile.txt']}


def captures(out):
    return {name:digest(out/name) for name in ['inputs.tsv','original.tsv','native.tsv','rust.tsv','native.trace','rust.trace']}


def verify(out,profiles):
    observed_identity=identity(out)
    candidates=[json.loads(p.read_text()) for p in profiles.glob('*.json')]
    candidates=[p for p in candidates if p['identity']==observed_identity]
    if len(candidates)!=1:raise ValueError('unknown or ambiguous arithmetic observation host/toolchain profile')
    expected=candidates[0]
    actual_differences=differences(out/'native.trace',out/'rust.trace')
    if actual_differences != expected['differences']:raise ValueError('unknown arithmetic observation field/value/location/count')
    if captures(out)!=expected['captures']:raise ValueError('paired capture differs from its exact frozen stream')
    source_manifest=json.loads((out/'source-sha256.json').read_text())
    if any(source_manifest.get(name)!=value for name,value in expected['producer_sources'].items()):raise ValueError('arithmetic observation source profile differs')
    return {'status':'SOURCE_DEFINED_ARITHMETIC_OBSERVATION','profile':expected['name'],'raw_bit_equality':False,'difference_words':len(actual_differences),'first_difference':actual_differences[0],'limit':expected['limit']}
