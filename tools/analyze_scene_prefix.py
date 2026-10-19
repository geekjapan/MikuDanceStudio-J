"""Audit complete native/diagnostic prefix evidence, retaining every image failure."""
import argparse
import csv
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
from analyze_accessory_isolation import tags,fnv,f32


def difference(a,b):
    if len(a)!=len(b) or len(a)%4:
        raise ValueError('image dimensions differ')
    mismatches=maximum=0
    first=None
    for n,(x,y) in enumerate(zip(memoryview(a).cast('I'),memoryview(b).cast('I'))):
        if x!=y:
            mismatches+=1
            delta=max(abs(a[n*4+k]-b[n*4+k]) for k in range(4))
            maximum=max(maximum,delta)
            if first is None:first=n
    return mismatches,maximum,first


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    parser.add_argument('--evidence',type=Path,help='Independent diagnostic output; defaults to archive/candidate')
    args=parser.parse_args()
    root=args.archive
    directory=args.evidence or root/'candidate'
    lines=(root/'history_replay.scene_prefix.manifest').read_text().splitlines()
    manifest=tags(lines[0])
    native_log=(root/'history_replay.dx9').read_text().splitlines()
    if manifest['schema']!='1':raise ValueError('unsupported export schema')
    if manifest['status']!='READY':
        blocks=[tags(line) for line in native_log if line.startswith(('PORTABLE_BLOCK ','PORTABLE_GATE '))]
        ground=[]
        for line in lines[1:]:
            fields=tags(line)
            if fields.get('name')=='ground':
                state=(root/f"history_replay.scene_prefix.draw{fields['draw']}.state").read_text().splitlines()
                ground.append(tags(state[0]))
        result={'status':'BLOCKED','manifest':manifest,'nativeBlockingProof':blocks,'groundCommands':ground,'productionActivation':False,'fullSceneAcceptance':False}
        (directory/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result))
        return 31
    count=int(manifest['draws'])
    if manifest['nativeExact']!='1' or len(lines)!=count+1:raise ValueError('incomplete native capture')
    passes={int(tags(line)['draw']):tags(line)['name'] for line in lines[1:]}
    if set(passes)!=set(range(1,count+1)):raise ValueError('broken pass membership')
    region=tags(next(line for line in native_log if line.startswith('PORTABLE_REGION ')))
    x,y,w,h=[int(region[k]) for k in ('x','y','width','height')]
    size=w*h*4
    begin=tags(next(line for line in native_log if line.startswith('BEGIN ')))
    if begin['samples']!='0' or begin['quality']!='0':raise ValueError('this gate requires single sample')
    gate=tags(next(line for line in native_log if line.startswith('PORTABLE_GATE ')))
    if gate['status']!='VALIDATED' or int(gate['draws'])!=count:raise ValueError('portable application gate failed')
    prefix=tags(next(line for line in native_log if line.startswith('PREFIX ')))
    if prefix['status']!='PASS' or prefix['beforeDifferentPixels']!='0':raise ValueError('native prefix reconstruction failed')
    traces=[tags(line) for line in native_log if line.startswith('TRACE ')]
    if len(traces)!=count or any(int(t['beforeSequence'])!=n+1 or t['differentPixels']!='0' for n,t in enumerate(traces)):
        raise ValueError('incomplete native per-draw reconstruction')
    proof=[]
    for draw in range(1,count+1):
        stem=root/f'history_replay.scene_prefix.draw{draw}'
        state=Path(str(stem)+'.state').read_text().splitlines()
        recorded=tags(next(line for line in native_log if line.startswith(f'DRAW sequence={draw} ')))
        descriptor=tags(state[0])
        if recorded['pass']!=passes[draw]:raise ValueError('draw pass changed')
        for key in ('sequence','type','fvf','indexed','base','minimum','vertices','start','count'):
            if descriptor[key]!=recorded[key]:raise ValueError('draw descriptor changed')
        vertex=Path(str(stem)+'.vertices').read_bytes();index=Path(str(stem)+'.indices').read_bytes()
        if descriptor['indexed']=='1' and not index:raise ValueError('indexed draw has no index snapshot')
        if fnv(vertex)!=int(recorded['vbVersion']) or fnv(index)!=int(recorded['ibVersion']):raise ValueError('geometry version changed')
        effective=tags(next(line for line in native_log if line.startswith(f'STATE sequence={draw} ')))
        state_count=mip_count=0
        for line in state[1:]:
            kind=line.split()[0];fields=tags(line)
            if kind in ('RS','TSS','SAMPLER'):
                key=f"rs.{fields['key']}" if kind=='RS' else f"{'tss' if kind=='TSS' else 'sampler'}.{fields['stage']}.{fields['key']}"
                if fields['value']!=effective[key]:raise ValueError('pipeline/sampler state changed')
                state_count+=1
            if kind in ('WORLD','VIEW','PROJECTION'):
                transform={'WORLD':256,'VIEW':2,'PROJECTION':3}[kind]
                captured=tags(next(line for line in native_log if line.startswith(f'MATRIX sequence={draw} transform={transform} ')))
                if any(f32(fields[f'f{k}'])!=f32(captured[f'm{k}']) for k in range(16)):raise ValueError('matrix changed')
            if kind=='TEXTURE' and fields['present']=='1':
                texture=Path(str(stem)+f".texture{fields['stage']}").read_bytes()
                if fnv(texture)!=int(recorded[f"texture{fields['stage']}Version"]):raise ValueError('texture version changed')
            if kind=='PREPARED_MIP':
                data=Path(str(stem)+f".prepared{fields['stage']}.{fields['level']}.rgba").read_bytes()
                if len(data)!=int(fields['width'])*int(fields['height'])*4 or fnv(data)!=int(fields['hash']):raise ValueError('prepared mip changed')
                mip_count+=1
        proof.append({'draw':draw,'pass':passes[draw],'states':state_count,'preparedMips':mip_count,
                      'indexed':descriptor['indexed']=='1','nativeTopology':int(descriptor['type']),
                      'primitiveCount':int(descriptor['count']),'start':int(descriptor['start']),
                      'vertexSha256':hashlib.sha256(vertex).hexdigest(),'indexSha256':hashlib.sha256(index).hexdigest()})
    with (directory/'trace.csv').open(newline='') as file:rows=list(csv.DictReader(file))
    if len(rows)!=count+1 or [int(r['afterDraw']) for r in rows]!=list(range(count+1)):raise ValueError('incomplete replay boundaries')
    first=None
    for boundary,row in enumerate(rows):
        actual=(root/(f'history_replay.scene_prefix.draw{boundary+1}.before.bgra' if boundary<count else 'history_replay.scene_prefix.final.bgra')).read_bytes()
        candidate=(directory/f'after{boundary}.bgra').read_bytes()
        if len(actual)!=size or len(candidate)!=size:raise ValueError('invalid boundary image extent')
        changed,maximum,pixel=difference(actual,candidate)
        if int(row['candidateDifferentPixels'])!=changed or int(row['maxDelta'])!=maximum or int(row['nativeHash'])!=fnv(actual) or int(row['candidateHash'])!=fnv(candidate):
            raise ValueError('image contradicts captured trace')
        if row['pass']!=('clear' if not boundary else passes[boundary]):raise ValueError('trace pass differs')
        if pixel is not None and (int(row['firstX'])!=x+pixel%w or int(row['firstY'])!=y+pixel//w):raise ValueError('first difference coordinate changed')
        if first is None and changed:first={'afterDraw':boundary,'pass':row['pass'],'differentPixels':changed,'maxDelta':maximum,'first':[x+pixel%w,y+pixel//w]}
    with (directory/'isolated.csv').open(newline='') as file:isolated=list(csv.DictReader(file))
    if len(isolated)!=count or [int(r['draw']) for r in isolated]!=list(range(1,count+1)):raise ValueError('incomplete draw-alone controls')
    groups={}
    for r in isolated:
        if r['pass']!=passes[int(r['draw'])]:raise ValueError('isolated pass changed')
        failed=int(r['differentPixels'])>0
        if not failed and r['nativeHash']!=r['candidateHash']:raise ValueError('zero delta hash mismatch')
        if failed:
            actual=(directory/f"isolated{r['draw']}.native.bgra").read_bytes();candidate=(directory/f"isolated{r['draw']}.candidate.bgra").read_bytes()
            changed,maximum,_=difference(actual,candidate)
            if changed!=int(r['differentPixels']) or maximum!=int(r['maxDelta']) or fnv(actual)!=int(r['nativeHash']) or fnv(candidate)!=int(r['candidateHash']):raise ValueError('isolated control image mismatch')
        group=groups.setdefault(r['pass'],{'draws':0,'exact':0,'differingDraws':[]});group['draws']+=1;group['exact']+=not failed
        if failed:group['differingDraws'].append({'draw':int(r['draw']),'differentPixels':int(r['differentPixels']),'maxDelta':int(r['maxDelta'])})
    result={'status':'PASS' if first is None and all(r['nativeDifferentPixels']=='0' for r in rows) else 'FAIL',
            'draws':count,'boundaries':count+1,'passes':dict(Counter(passes.values())),
            'nativeFailingBoundaries':sum(int(r['nativeDifferentPixels'])>0 for r in rows),
            'candidateFailingBoundaries':sum(int(r['candidateDifferentPixels'])>0 for r in rows),
            'firstDifference':first,'finalDifferentPixels':int(rows[-1]['candidateDifferentPixels']),
            'isolatedControls':groups,'archiveProof':proof,'outsideRegionUnspecified':True,
            'productionActivation':False,'fullSceneAcceptance':False}
    control_file=root/'first-controls'/'controls.csv'
    if control_file.exists():
        with control_file.open(newline='') as file:controls=list(csv.DictReader(file))
        names={'original','repeat','selected_only','no_depth','no_stencil','no_specular','no_normalize','no_lighting','selected_only_no_depth','selected_only_no_stencil','before_selected','small_viewport','small_viewport_no_depth'}
        if len(controls)!=13 or {r['mode'] for r in controls}!=names:raise ValueError('incomplete first-draw controls')
        result['firstDrawControls']={}
        for row in controls:
            a=(control_file.parent/(row['mode']+'.native.bgra')).read_bytes();b=(control_file.parent/(row['mode']+'.candidate.bgra')).read_bytes()
            changed,maximum,pixel=difference(a,b)
            expected_size=670*503*4 if row['mode'].startswith('small_viewport') else size
            if len(a)!=expected_size or changed!=int(row['differentPixels']) or maximum!=int(row['maxDelta']) or fnv(a)!=int(row['nativeHash']) or fnv(b)!=int(row['candidateHash']):raise ValueError('control image mismatch')
            result['firstDrawControls'][row['mode']]={'differentPixels':changed,'maxDelta':maximum}
    summary=tags((directory/'summary.txt').read_text())
    if int(summary['candidateFailingBoundaries'])!=result['candidateFailingBoundaries'] or summary['finalRepeatExact']!='1':raise ValueError('summary contradicts boundaries')
    center_file=directory/'center_mode.txt'
    xy_file=directory/'xy_policy.txt'
    if xy_file.exists():
        policy=tags(xy_file.read_text())
        if policy.get('fusedXY')!='1' or policy.get('geometryUnchanged')!='1' or policy.get('nativeVertexCapture')!='0' or policy.get('productionActivation')!='0' or not center_file.exists():raise ValueError('invalid fused XY diagnostic policy')
        result['fusedXYDiagnostic']=policy
    if center_file.exists():
        center=tags(center_file.read_text())
        if center!={'center':'viewport','shaderShift':'0','viewportShiftX':'0.5','viewportShiftY':'0.5','geometryUnchanged':'1','CPUClipping':'0','productionActivation':'0'}:raise ValueError('unsupported center-stage mode')
        if summary.get('finalRepeats')!='3':raise ValueError('missing three fresh final center-stage images')
        final=(directory/f'after{count}.bgra').read_bytes()
        if any((directory/f'repeat{n}.bgra').read_bytes()!=final for n in range(1,4)):raise ValueError('center-stage final image repetition changed')
        result.update(centerMode=center,finalRepeats=3)
    (directory/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='archiveProof'}))
    return 0 if result['status']=='PASS' else 32


if __name__=='__main__':
    raise SystemExit(main())
