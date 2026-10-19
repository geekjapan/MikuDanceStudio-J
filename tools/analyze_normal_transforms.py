"""Compare independently generated transforms without fitting native outputs.

General rotation axis probes observe the combined normal/light response;
only exact-axis views permit direct coefficient recovery.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import struct
from generate_sensitive_depth_matrices import multiply, dot


def bits(value):
    return struct.unpack('<I', struct.pack('<f', float(value)))[0]


def fl(value):
    return struct.unpack('<f', struct.pack('<f', float(value)))[0]


def read(path, keys, coordinates):
    with path.open(newline='') as file:
        rows = list(csv.DictReader(file))
    indexed = {tuple(int(r[k]) for k in keys): r for r in rows}
    if len(rows) != len(coordinates) or set(indexed) != set(coordinates):
        raise ValueError(f'incomplete/duplicate observation: {path}')
    for r in rows:
        if not math.isfinite(float(r['value'])) or bits(r['value']) != int(r['bits']):
            raise ValueError('invalid float observation')
        if int(r['holdout']) != (int(r['transform']) >= 6):
            raise ValueError('holdout transform membership changed')
    return indexed


def normal_matrix(world, view):
    m = [[sum(float(world[i*4+k])*float(view[k*4+j]) for k in range(3)) for j in range(3)] for i in range(3)]
    det = m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])-m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])+m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0])
    out = [0.]*16
    out[15] = 1.
    for i in range(3):
        for j in range(3):
            a, b, c, d = (i+1)%3, (i+2)%3, (j+1)%3, (j+2)%3
            out[i*4+j] = fl((m[a][c]*m[b][d]-m[a][d]*m[b][c])/det)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    root = args.directory
    manifest = json.loads((root/'manifest.json').read_text())
    if manifest != {'transforms': 12, 'holdoutTransforms': 6, 'normals': 6, 'exactAxisTransforms': 8, 'samples': 1, 'nativeRepeats': 3, 'gpuRepeats': 2, 'productionActivation': False}:
        raise ValueError('unexpected experiment manifest')
    matrices = read(root/'matrices.csv', ('transform', 'kind', 'k'), [(t,p,k) for t in range(12) for p in range(4) for k in range(16)])
    axis_coordinates = [(t,n,0,a,s,0) for t in range(12) for n in range(6,9) for a in range(3) for s in range(2)]
    axis_coordinates += [(t,n,z,a,s,p) for t in range(12) for n in range(6) for z in range(2) for a in range(3) for s in range(2) for p in range(2)]
    axes = read(root/'axes.csv', ('transform','normal','normalize','axis','sign','path'), axis_coordinates)
    value_coordinates = [(t,n,p,s,k) for t in range(12) for n in range(6) for p in range(2) for s in range(6) for k in range(4)]
    value_coordinates += [(t,n,2,s,k) for t in range(12) for n in range(6) for s in range(4) for k in range(4)]
    value_coordinates += [(t,n,3,s,k) for t in range(12) for n in range(6) for s in (5,6) for k in range(4)]
    value_coordinates += [(t,n,1,6,k) for t in range(12) for n in range(6) for k in range(4)]
    values = read(root/'values.csv', ('transform','normal','path','stage','k'), value_coordinates)
    normals = [[.13,.37,-.91],[-.83,.11,-.47],[.007,-.015,.019],[.25,1.75,-2.5],[-1.33,-.27,.51],[.61,.73,-.89]]
    normals = [[fl(v) for v in n] for n in normals]
    identity = [1. if k in (0,5,10,15) else 0. for k in range(16)]
    failures = []
    results = []

    def compare(native, candidate, context):
        same = bits(native) == bits(candidate) or float(native) == float(candidate) == 0
        if not same:
            failures.append({**context, 'native': float(native), 'candidate': float(candidate), 'nativeBits': bits(native), 'candidateBits': bits(candidate)})
        return int(same)

    for t in range(12):
        transforms = [[float(matrices[t,p,k]['value']) for k in range(16)] for p in range(4)]
        world, view, original, candidate = transforms
        expected = normal_matrix(multiply(world, view, 'sequential'), identity)
        for k in range(16):
            if candidate[k] != expected[k] or original[k] != normal_matrix(world,view)[k]:
                raise ValueError('candidate matrix differs from declared arithmetic')
        exact_axes = t < 8
        if any(int(matrices[t,p,k]['exactAxes']) != exact_axes for p in range(4) for k in range(16)):
            raise ValueError('exact-axis classification changed')
        r = {'transform':t,'name':matrices[t,0,0]['name'],'holdout':t>=6,'exactAxes':exact_axes,
             'matrixExact':0,'rawNativeProgrammableExact':0,'normalizedNativeProgrammableExact':0,
             'lengthNativeProgrammableExact':0,'reciprocalNativeProgrammableExact':0,
             'signedFacingExact':0,'facingExact':0,'colorExact':0,
             'axisRawComponentsExact':0,'axisNormalizedComponentsExact':0,
             'baselineMatrixExact':0,'baselineFacingExact':0,
             'baselineAxisRawComponentsExact':0,'baselineAxisNormalizedComponentsExact':0}
        if exact_axes:
            for row in range(3):
                for col in range(3):
                    observed = fl(float(axes[t,row+6,0,col,0,0]['value'])-float(axes[t,row+6,0,col,1,0]['value']))
                    r['matrixExact'] += compare(observed, candidate[row*4+col], {'transform':t,'boundary':'matrix','row':row,'column':col})
                    r['baselineMatrixExact'] += observed == original[row*4+col]
        for n in range(6):
            for k in range(3):
                expected_raw = dot((*normals[n],0.), candidate[k::4], 'fused')
                if bits(expected_raw) != int(values[t,n,1,0,k]['bits']):
                    raise ValueError('actual GPU raw dot differs from CPU fused rule')
            for native_stage,candidate_stage,label,channels in ((0,0,'raw',3),(1,2,'length',1),(2,3,'reciprocal',1),(3,1,'normalized',3)):
                field = {'raw':'rawNativeProgrammableExact','length':'lengthNativeProgrammableExact','reciprocal':'reciprocalNativeProgrammableExact','normalized':'normalizedNativeProgrammableExact'}[label]
                for k in range(channels):
                    r[field] += compare(values[t,n,2,native_stage,k]['value'],values[t,n,1,candidate_stage,k]['value'],{'transform':t,'normal':n,'boundary':label,'k':k})
            r['facingExact'] += compare(values[t,n,3,5,0]['value'],values[t,n,1,5,0]['value'],{'transform':t,'normal':n,'boundary':'facing'})
            r['baselineFacingExact'] += bits(values[t,n,3,5,0]['value']) == int(values[t,n,0,5,0]['bits'])
            for k in range(3):
                r['colorExact'] += compare(values[t,n,3,6,k]['value'],min(1.,max(0.,float(values[t,n,1,6,k]['value']))),{'transform':t,'normal':n,'boundary':'color','k':k})
            for z in range(2):
                for a in range(3):
                    for sign in range(2):
                        r['signedFacingExact'] += compare(axes[t,n,z,a,sign,0]['value'],axes[t,n,z,a,sign,1]['value'],{'transform':t,'normal':n,'boundary':'axisFacing','normalize':z,'axis':a,'sign':sign})
                    if exact_axes:
                        raw = fl(float(axes[t,n,z,a,0,0]['value'])-float(axes[t,n,z,a,1,0]['value']))
                        field = 'axisNormalizedComponentsExact' if z else 'axisRawComponentsExact'
                        r[field] += compare(raw,values[t,n,1,z,a]['value'],{'transform':t,'normal':n,'boundary':'axisNormalized' if z else 'axisRaw','axis':a})
                        baseline_field = 'baselineAxisNormalizedComponentsExact' if z else 'baselineAxisRawComponentsExact'
                        r[baseline_field] += bits(raw) == int(values[t,n,0,z,a]['bits']) or raw == float(values[t,n,0,z,a]['value']) == 0
        results.append(r)
    aggregate = {field:sum(r[field] for r in results) for field in results[0] if field.endswith('Exact')}
    result = {'transforms':results,'aggregate':aggregate,'failures':failures,'signedZeroCoefficientsEquivalent':True,
              'cpuFusedRawExact':216,'generalAxisResponsesAreEffectiveLightingOnly':True,
              'independentTransformAcceptance':not failures,'productionActivation':False,'fullSceneAcceptance':False}
    (root/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(aggregate))
    print(f'failures={len(failures)} holdoutFailures={sum(f["transform"]>=6 for f in failures)} independentTransformAcceptance={not failures} productionActivation=0')
    for r in results:
        print(f'{r["transform"]}: {r["name"]} matrix={r["matrixExact"]}/{9 if r["exactAxes"] else 0} facing={r["facingExact"]}/6 color={r["colorExact"]}/18 signedFacing={r["signedFacingExact"]}/72')
    return 0 if not failures else 32


if __name__ == '__main__':
    raise SystemExit(main())
