"""Verify saved endpoint observations and depth threshold probes independently."""
import argparse
import csv
import hashlib
import json
import struct
from pathlib import Path
from analyze_accessory_isolation import tags, fnv
from analyze_scene_prefix import difference


def rows(path):
    with path.open(newline='') as f:return list(csv.DictReader(f))


def f32(x):return struct.pack('<f',float(x))
def value(bits):return struct.unpack('<f',struct.pack('<I',bits))[0]
def clips(path):
    b=path.read_bytes()
    if len(b)%16:raise ValueError('invalid float4 capture')
    return list(struct.iter_unpack('<4f',b))


def baseline(archive,root,after):
    original_n=(root/'original.native.bgra').read_bytes()
    original_r=(root/'original.candidate.bgra').read_bytes()
    if original_n!=(archive/f'history_replay.scene_prefix.draw{after+1}.before.bgra').read_bytes():raise ValueError('native baseline differs from application')
    if original_r!=(archive/'candidate'/f'after{after}.bgra').read_bytes():raise ValueError('candidate baseline differs from earlier image')
    controls=rows(root/'controls.csv')
    for row in controls:
        name=row['mode'];n=(root/(name+'.native.bgra')).read_bytes();r=(root/(name+'.candidate.bgra')).read_bytes()
        changed,maximum,_=difference(n,r)
        if any(int(row[key])!=val for key,val in (('differentPixels',changed),('maxDelta',maximum),('nativeHash',fnv(n)),('candidateHash',fnv(r)))):raise ValueError('image contradicts controls')
    return controls


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('kind',choices=('endpoints','depth'));p.add_argument('archive',type=Path);p.add_argument('evidence',type=Path)
    args=p.parse_args();source=args.archive;root=args.evidence
    state=(source/'history_replay.scene_prefix.draw1.state').read_text().splitlines()
    v=tags(next(s for s in state if s.startswith('VIEWPORT ')));region=[int(v[k]) for k in ('x','y','width','height')]
    result={'kind':args.kind,'region':region,'nativeApplicationBaselineExact':True,'productionActivation':False,
            'imageAcceptance':False,'rawD24Readback':False,'actualDX9FixedFunctionVertexCapture':False}
    if args.kind=='endpoints':
        controls=baseline(source,root,1)
        if {r['mode'] for r in controls}!={'original','compact','uniform'}:raise ValueError('incomplete line baselines')
        raw=clips(root/'candidate.raw_clip.bin');final=clips(root/'candidate.final_clip.bin')
        if len(raw)!=2 or len(final)!=2:raise ValueError('endpoint count mismatch')
        desc=tags(state[0]);vertex=(source/'history_replay.scene_prefix.draw1.vertices').read_bytes();index=(source/'history_replay.scene_prefix.draw1.indices').read_bytes()
        log=(source/'history_replay.dx9').read_text().splitlines();ib=tags(next(s for s in log if s.startswith('BUFFER sequence=1 kind=index ')))
        step=2 if int(ib['format'])==101 else 4;start=int(desc['start'])+17*2
        indices=[int.from_bytes(index[(start+n)*step:(start+n+1)*step],'little') for n in range(2)]
        if (root/'source.vertices').read_bytes()!=b''.join(vertex[n*16:(n+1)*16] for n in indices):raise ValueError('line source bytes differ')
        observations=rows(root/'endpoints.csv');seen=set()
        for row in observations:
            name=row['source'];n=int(row['endpoint']);key=(name,n)
            if n not in (0,1) or key in seen:raise ValueError('invalid endpoint row')
            seen.add(key)
            values=[float(row[k]) for k in ('x','y','z','w')];bits=[int(row[k]) for k in ('bitsX','bitsY','bitsZ','bitsW')]
            if any(f32(f)!=struct.pack('<I',u) for f,u in zip(values,bits)):raise ValueError('endpoint float/bits disagree')
            if name in ('candidate_raw_clip','candidate_final_clip'):
                expected=(raw if name=='candidate_raw_clip' else final)[n]
                if any(f32(a)!=f32(b) for a,b in zip(values,expected)):raise ValueError('endpoint CSV differs from GPU capture')
            if name.startswith('process_'):
                expected=clips(root/(name+'.screen.bin'))[n]
                if any(f32(a)!=f32(b) for a,b in zip(values,expected)):raise ValueError('ProcessVertices observation differs from bytes')
        required={('candidate_'+stage,n) for stage in ('raw_clip','final_clip','screen') for n in range(2)}
        required|={(f'cpu_rule{rule}_{stage}',n) for rule in range(4) for stage in ('clip','screen') for n in range(2)}
        process=(root/'process_vertices.txt').read_text().splitlines();statuses={}
        for line in process[:2]:
            name=line.split()[0];info=tags(line);exit_code=int(info['childExit']);statuses[name]={'exit':exit_code,'actualDrawCapture':False}
            if exit_code==0:
                required|={(name,n) for n in range(2)}
                hr=tags((root/(name+'.status')).read_text())
                if int(hr['HRESULT'],16)!=0:raise ValueError('child success conflicts with HRESULT')
        if seen!=required:raise ValueError('missing endpoint observations')
        common=tags(process[2]);n=(root/'common_clip.native.bgra').read_bytes();r=(root/'common_clip.candidate.bgra').read_bytes()
        if len(n)!=region[2]*region[3]*4:raise ValueError('common clip region differs')
        changed,maximum,first=difference(n,r)
        if changed!=int(common['commonClipDifferentPixels']) or common['commonClipRepeatExact']!='1':raise ValueError('common clip metrics disagree')
        dn,_,_=difference(n,(root/'uniform.native.bgra').read_bytes());dr,_,_=difference(r,(root/'uniform.candidate.bgra').read_bytes())
        if dn!=int(common['nativeChangedFromUniform']) or dr!=int(common['candidateChangedFromUniform']):raise ValueError('uniform/common geometry metrics disagree')
        result.update(candidateRawClip=raw,candidateFinalClip=final,processVertices=statuses,
                      commonClip={'differentPixels':changed,'maxDelta':maximum,'nativeChangedFromUniform':dn,'candidateChangedFromUniform':dr,'first':None if first is None else [region[0]+first%region[2],region[1]+first//region[2]]})
        by_key={(r['source'],int(r['endpoint'])):r for r in observations}
        if statuses['process_software']['exit']==0:
            result['softwareMinusCandidateScreen']=[[float(by_key[('process_software',n)][k])-float(by_key[('candidate_screen',n)][k]) for k in ('x','y','z','w')] for n in range(2)]
    else:
        controls=baseline(source,root,6)
        if {r['mode'] for r in controls}!={'original','compact_pair'}:raise ValueError('incomplete depth baseline')
        threshold=rows(root/'thresholds.csv');queries=rows(root/'queries.csv');calibration=rows(root/'calibration.csv')
        summary=tags((root/'measurement_summary.txt').read_text())
        if len(threshold)!=12 or int(summary['measurements'])!=len(threshold) or int(summary['queries'])!=len(queries) or len(calibration)!=15 or summary['repeatExact']!='1' or summary['rawD24Readback']!='0':raise ValueError('incomplete threshold measurements')
        expected={(path,t,pt) for path in ('original_transform','shared_clip') for t in range(2) for pt in range(3)}
        actual={(r['path'],int(r['triangle']),int(r['point'])) for r in threshold}
        if expected!=actual or len(actual)!=len(threshold):raise ValueError('missing path/triangle/point')
        measurement={};result['thresholds']=[]
        for row in threshold:
            key=(row['path'],int(row['triangle']),int(row['point']));measurement[key]=row
            relevant=[q for q in queries if (q['path'],int(q['triangle']),int(q['point']))==key]
            cache={};fresh_counts={}
            for q in relevant:
                bits=int(q['bits']);cmp=q['comparison'];answer=(q['dx9'],q['dx11'])
                if q['x']!=row['x'] or q['y']!=row['y'] or cmp not in ('Less','Equal') or any(a not in ('G','R') for a in answer):raise ValueError('invalid ruler observation')
                query=(bits,cmp)
                if query in cache and cache[query]!=answer:raise ValueError('repeat/cached observation changed')
                cache[query]=answer
                if q['fresh']=='1':
                    fresh_counts[query]=fresh_counts.get(query,0)+1
                    stem=f"{key[0]}_t{key[1]}_p{key[2]}_b{bits}_{cmp.lower()}"
                    for side,color in zip(('native','candidate'),answer):
                        image=(root/(stem+'.'+side+'.bgra')).read_bytes()
                        if len(image)!=100:raise ValueError('threshold ROI extent differs')
                        expected_color=bytes((0,0,255,255)) if color=='R' else bytes((0,255,0,255))
                        if image[48:52]!=expected_color:raise ValueError('threshold ROI contradicts relation')
            for backend,name in enumerate(('dx9ThresholdBits','dx11ThresholdBits')):
                b=int(row[name])
                if cache.get((b,'Less'),('',''))[backend]!='R' or cache.get((b-1,'Less'),('',''))[backend]!='G' or cache.get((b,'Equal'),('',''))[backend]!='G':raise ValueError('threshold edge unproven')
                if any(fresh_counts.get(q,0)<3 for q in ((b,'Less'),(b-1,'Less'),(b,'Equal'))):raise ValueError('missing fresh edge repetitions')
                for (bits,cmp),answer in cache.items():
                    if cmp=='Less' and answer[backend]!=('G' if bits<b else 'R'):raise ValueError('nonmonotonic measured threshold')
            expected_fresh={}
            for b in {int(row['dx9ThresholdBits']),int(row['dx11ThresholdBits'])}:
                for q in ((b,'Less'),(b-1,'Less'),(b,'Equal')):expected_fresh[q]=expected_fresh.get(q,0)+3
            if fresh_counts!=expected_fresh:raise ValueError('unexpected fresh measurement multiplicity')
            result['thresholds'].append({**{k:int(row[k]) for k in ('triangle','point','x','y','dx9ThresholdBits','dx11ThresholdBits')},
                'path':key[0],'dx9ReferenceDepth':value(int(row['dx9ThresholdBits'])),'dx11ReferenceDepth':value(int(row['dx11ThresholdBits']))})
        for row in calibration:
            offset=int(row['offset']);cmp=row['comparison'];expect='G' if (offset<0 if cmp=='Less' else offset==0 if cmp=='Equal' else offset<=0) else 'R'
            if row['dx9']!=expect or row['dx11']!=expect or row['expected']!=expect:raise ValueError('ruler calibration failed')
        result['sharedClipThresholdsMatchOriginal']=all(measurement[('original_transform',t,p)][key]==measurement[('shared_clip',t,p)][key] for t in range(2) for p in range(3) for key in ('dx9ThresholdBits','dx11ThresholdBits'))
        for t,(draw,tri) in enumerate(((2,1),(6,1141))):
            stem=source/f'history_replay.scene_prefix.draw{draw}';desc=tags(Path(str(stem)+'.state').read_text().splitlines()[0]);start=int(desc['start'])+tri*3
            vertices=Path(str(stem)+'.vertices').read_bytes();indices=Path(str(stem)+'.indices').read_bytes();stride=int(desc['stride'])
            if int(desc['indexed']):
                log=(source/'history_replay.dx9').read_text().splitlines();ib=tags(next(s for s in log if s.startswith(f'BUFFER sequence={draw} kind=index ')));step=2 if int(ib['format'])==101 else 4
                referenced=[int.from_bytes(indices[(start+n)*step:(start+n+1)*step],'little') for n in range(3)]
            else:referenced=list(range(start,start+3))
            if (root/f'triangle{t}.vertices').read_bytes()!=b''.join(vertices[n*stride:(n+1)*stride] for n in referenced):raise ValueError('triangle compact source bytes differ')
            if len(clips(root/f'triangle{t}.raw_clip.bin'))!=3 or len(clips(root/f'triangle{t}.final_clip.bin'))!=3:raise ValueError('triangle stream-output count differs')
        result.update(calibration=15,thresholdMeasurements=len(threshold),rulerQueries=len(queries),edgeRepeats=3)
    result['evidenceHashes']={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(root.iterdir()) if f.is_file() and f.name!='analysis.json'}
    (root/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('evidenceHashes','candidateRawClip','candidateFinalClip')}))
    return 0


if __name__=='__main__':raise SystemExit(main())
