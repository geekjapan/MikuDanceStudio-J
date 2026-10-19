"""Audit line/history controls against saved images without accepting scene parity."""
import argparse
import csv
import hashlib
import json
import re
import struct
from pathlib import Path
from analyze_scene_prefix import difference
from analyze_accessory_isolation import fnv, tags


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind',choices=('lines','history','reduction'))
    parser.add_argument('archive',type=Path)
    parser.add_argument('evidence',type=Path)
    parser.add_argument('--selected',type=int,default=6)
    args=parser.parse_args()
    source=args.archive;root=args.evidence
    state=(source/'history_replay.scene_prefix.draw1.state').read_text().splitlines()
    desc=tags(state[0]);region=tags(next(s for s in state if s.startswith('VIEWPORT ')))
    x,y,w,h=[int(region[k]) for k in ('x','y','width','height')]
    size=w*h*4
    with (root/'controls.csv').open(newline='') as f:rows=list(csv.DictReader(f))
    data={r['mode']:r for r in rows}
    if len(data)!=len(rows):raise ValueError('duplicate controls')
    segments=int(desc['count']);selected=1 if args.kind=='lines' else args.selected
    common={'original','repeat1','repeat2','repeat3'}
    if args.kind=='lines':
        expected=common|{'no_depth','no_stencil','no_alpha_test','no_blend','unlit_uniform','reverse_all','no_depth_write'}
        expected|={f'{prefix}{n}' for prefix in ('segment','reverse') for n in range(1,segments+1)}
        failed=[n for n in range(1,segments+1) if int(data[f'segment{n}']['differentPixels'])]
        expected|={f'{prefix}{n}' for prefix in ('compact_segment','compact_reverse','compact_uniform') for n in failed}
        with (root/'segments.csv').open(newline='') as f:endpoints=list(csv.DictReader(f))
        if len(endpoints)!=segments*2:raise ValueError('missing endpoint geometry')
        # Check original indexed endpoints byte-for-byte, not only their labels.
        vertex=(source/'history_replay.scene_prefix.draw1.vertices').read_bytes()
        index=(source/'history_replay.scene_prefix.draw1.indices').read_bytes()
        from analyze_accessory_isolation import f32
        native_log=(source/'history_replay.dx9').read_text().splitlines()
        ib=tags(next(line for line in native_log if line.startswith('BUFFER sequence=1 kind=index ')))
        step=2 if int(ib['format'])==101 else 4
        for n,row in enumerate(endpoints):
            segment,endpoint=divmod(n,2);at=int(desc['start'])+n
            index_value=int.from_bytes(index[at*step:(at+1)*step],'little')
            position=struct.unpack_from('<3fI',vertex,index_value*int(desc['stride']))
            if int(row['segment'])!=segment+1 or int(row['endpoint'])!=endpoint or int(row['index'])!=index_value or int(row['color'])!=position[3]:raise ValueError('endpoint identity changed')
            if any(f32(row[key])!=struct.pack('<f',position[k]) for k,key in enumerate(('x','y','z'))):raise ValueError('endpoint position changed')
        for n in failed:
            original_indices=[int(row['index']) for row in endpoints[(n-1)*2:n*2]]
            compact=b''.join(vertex[i*16:(i+1)*16] for i in original_indices)
            if (root/f'compact_segment{n}.vertices').read_bytes()!=compact or (root/f'compact_segment{n}.indices').read_bytes()!=bytes((0,0,1,0)):raise ValueError('compact line differs from source endpoints')
    elif args.kind=='history':
        expected=common|{f'prior_mask{m}' for m in range(1<<(selected-1))}
        expected|={'ground_no_depth_write','grid_no_depth_write','plane_no_depth_write','all_no_stencil','ground_no_stencil_write',
                   'ground_depth_only','ground_color_only','selected_no_depth','selected_always','selected_less','selected_equal',
                   'selected_no_depth_write','selected_no_stencil','selected_no_blend'}
    else:
        expected=common|{'pair','plane_triangle0','plane_triangle1','minimal_pair','minimal_plane_alone','minimal_accessory_alone',
                         'minimal_plane_no_depth_write','minimal_no_stencil','minimal_plane_depth_only','minimal_less','minimal_equal','minimal_always','minimal_no_depth'}
        reduction=tags((root/'reduction.txt').read_text())
        if int(reduction['compact']):expected.add('compact_pair')
        expected|={n for n in data if re.fullmatch(r'reduce_step\d+_half[01]',n)}
    if set(data)!=expected:raise ValueError('incomplete controls')
    run=tags((root/'summary.txt').read_text())
    if int(run['comparisons'])!=len(data) or run['baselineNativeExact']!='1' or run['repeatedBaselineExact']!='1' or run['productionActivation']!='0' or run['imageAcceptance']!='0':raise ValueError('invalid diagnostic completion summary')
    images={}
    for name in data:
        images[name]=tuple((root/(name+suffix)).read_bytes() for suffix in ('.native.bgra','.candidate.bgra'))
        if any(len(b)!=size for b in images[name]):raise ValueError('image extent mismatch')
    native,candidate=images['original']
    saved=(source/f'history_replay.scene_prefix.draw{selected+1}.before.bgra').read_bytes()
    if saved!=native:raise ValueError('baseline no longer matches original application')
    if (source/'candidate'/f'after{selected}.bgra').read_bytes()!=candidate:raise ValueError('baseline candidate no longer matches previous evidence')
    for n in range(1,4):
        if images[f'repeat{n}']!=images['original']:raise ValueError('baseline repetition unstable')
    summary={}
    diff_pixels={}
    for name,(a,b) in images.items():
        changed,maximum,first=difference(a,b);row=data[name]
        changed_n,_,_=difference(native,a);changed_r,_,_=difference(candidate,b)
        if any(int(row[key])!=value for key,value in (('differentPixels',changed),('maxDelta',maximum),('nativeHash',fnv(a)),('candidateHash',fnv(b)),('nativeChangedFromBaseline',changed_n),('candidateChangedFromBaseline',changed_r))):raise ValueError(f'{name} contradicts image metrics')
        if first is not None and (int(row['firstX']),int(row['firstY']))!=(x+first%w,y+first//w):raise ValueError('first coordinate changed')
        diff_pixels[name]=[(x+p%w,y+p//w,tuple(a[p*4:p*4+4]),tuple(b[p*4:p*4+4])) for p,(u,v) in enumerate(zip(memoryview(a).cast('I'),memoryview(b).cast('I'))) if u!=v]
        summary[name]={'differentPixels':changed,'maxDelta':maximum,'first':None if first is None else [x+first%w,y+first//w]}
    with (root/'pixels.csv').open(newline='') as f:pixel_rows=list(csv.DictReader(f))
    actual_pixels=[]
    for row in pixel_rows:
        actual_pixels.append((row['mode'],int(row['x']),int(row['y']),tuple(int(row['native'+k]) for k in ('B','G','R','A')),tuple(int(row['candidate'+k]) for k in ('B','G','R','A'))))
    wanted=[(name,*p) for name in data for p in diff_pixels[name]]
    if actual_pixels!=wanted:raise ValueError('per-pixel log contradicts saved images')
    proof=[]
    for draw in range(1,selected+1):
        files=sorted(source.glob(f'history_replay.scene_prefix.draw{draw}.*'))
        proof.append({'draw':draw,'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files if not p.name.endswith('.bgra')}})
    result={'kind':args.kind,'controls':len(data),'nativeApplicationBaselineExact':True,'repeatedBaselineExact':True,
            'region':[x,y,w,h],'baseline':summary['original'],'controlMetrics':summary,'archiveProof':proof,
            'productionActivation':False,'imageAcceptance':False}
    if args.kind=='lines':
        failed=[n for n in range(1,segments+1) if summary[f'segment{n}']['differentPixels']]
        result['differingSegments']=failed
        result['segmentPixels']={str(n):diff_pixels[f'segment{n}'] for n in failed}
        result['reversedSegmentPixels']={str(n):diff_pixels[f'reverse{n}'] for n in failed}
    elif args.kind=='history':
        focus=[p[:2] for p in diff_pixels['original']]
        result['focusControls']={name:[{'xy':[px,py],'nativeBGRA':list(a[((py-y)*w+px-x)*4:((py-y)*w+px-x)*4+4]),
                                      'candidateBGRA':list(b[((py-y)*w+px-x)*4:((py-y)*w+px-x)*4+4])} for px,py in focus] for name,(a,b) in images.items()}
        masks=[m for m in range(1<<(selected-1)) if any(tuple(p[:2]) in {tuple(f) for f in focus} for p in diff_pixels[f'prior_mask{m}'])]
        minimal=[m for m in masks if not any(other!=m and other&m==other for other in masks)]
        result['minimalFocusHistoryMasks']=[{'mask':m,'draws':[n+1 for n in range(selected-1) if m&(1<<n)]+[selected]} for m in minimal]
    else:
        fx,fy=int(reduction['focusX']),int(reduction['focusY']);at=((fy-y)*w+fx-x)*4
        if not(x<=fx<x+w and y<=fy<y+h) or native[at:at+4]==candidate[at:at+4]:raise ValueError('invalid reduction focus')
        def mismatch(name):
            a,b=images[name];return a[at:at+4]!=b[at:at+4]
        if not mismatch('pair'):raise ValueError('ground/accessory pair lost the focus')
        plane_candidates=[n for n in range(2) if mismatch(f'plane_triangle{n}')]
        if not plane_candidates or plane_candidates[0]!=int(reduction['planeTriangle']):raise ValueError('plane triangle selection contradicts controls')
        original_draw=tags((source/f'history_replay.scene_prefix.draw{selected}.state').read_text().splitlines()[0])
        first=step=0;count=int(original_draw['count']);visited=set()
        while count>1:
            left=count//2;retained=False
            for half in range(2):
                name=f'reduce_step{step}_half{half}';visited.add(name)
                if name not in images:raise ValueError('missing binary reduction branch')
                if mismatch(name):
                    first+=left if half else 0;count=count-left if half else left;retained=True;break
            if not retained:break
            step+=1
        if visited!={n for n in data if re.fullmatch(r'reduce_step\d+_half[01]',n)}:raise ValueError('unexpected binary reduction branch')
        if first!=int(reduction['accessoryFirstTriangle']) or count!=int(reduction['accessoryTriangles']):raise ValueError('reduction range contradicts comparisons')
        if not mismatch('minimal_pair') or (int(reduction['compact']) and not mismatch('compact_pair')):raise ValueError('minimal geometry did not preserve focus')
        if count==1:
            for label,draw,triangle in (('plane',2,int(reduction['planeTriangle'])),('accessory',selected,first)):
                stem=source/f'history_replay.scene_prefix.draw{draw}'
                descriptor=tags(Path(str(stem)+'.state').read_text().splitlines()[0])
                vertices=Path(str(stem)+'.vertices').read_bytes();indices=Path(str(stem)+'.indices').read_bytes()
                stride=int(descriptor['stride']);start=int(descriptor['start'])+triangle*3
                # Captured reduction uses UInt16; prove this with recorder metadata.
                if descriptor['indexed']=='1':
                    log=(source/'history_replay.dx9').read_text().splitlines()
                    ib=tags(next(line for line in log if line.startswith(f'BUFFER sequence={draw} kind=index ')))
                    index_step=2 if int(ib['format'])==101 else 4
                    original_indices=[int.from_bytes(indices[(start+n)*index_step:(start+n+1)*index_step],'little') for n in range(3)]
                else:original_indices=list(range(start,start+3))
                compact=b''.join(vertices[n*stride:(n+1)*stride] for n in original_indices)
                if (root/f'minimal_{label}.vertices').read_bytes()!=compact:raise ValueError('compact vertices differ from source range')
                expected_indices=bytes((0,0,1,0,2,0)) if descriptor['indexed']=='1' else b''
                if (root/f'minimal_{label}.indices').read_bytes()!=expected_indices:raise ValueError('compact index remap differs')
                result[label+'Geometry']={'sourceDraw':draw,'sourceTriangleZeroBased':triangle,'sourceVertexIndices':original_indices,
                    'positions':[list(struct.unpack_from('<3f',compact,n*stride)) for n in range(3)],'sha256':hashlib.sha256(compact).hexdigest()}
        result['reduction']={k:int(v) for k,v in reduction.items()}
        result['focusControls']={name:{'nativeBGRA':list(a[at:at+4]),'candidateBGRA':list(b[at:at+4])} for name,(a,b) in images.items()}
    (root/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('archiveProof','focusControls','controlMetrics')}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
