"""Independent DX9 / reference DX11 / RHI DX11 single-batch acceptance."""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',required=True,type=Path)
    parser.add_argument('--capture',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    capture=args.capture or (Path(os.environ['MDS_RHI_MODEL_CAPTURE']) if os.environ.get('MDS_RHI_MODEL_CAPTURE') else None)
    if capture is None or not capture.is_file():
        print('UNAVAILABLE: set MDS_RHI_MODEL_CAPTURE to a version-5 independent batch capture')
        return 77
    header=struct.unpack('<17I',capture.read_bytes()[:68])
    width,height=header[10:12]
    if header[1]!=5 or header[14] or width>4080 or height>4080:
        raise ValueError('Requires version-5 capture without history, size <=4080')
    args.output.mkdir(parents=True,exist_ok=True)
    results=[]
    for name,w,h in [('original',width,height),('larger',width+16,height+16)]:
        directory=args.output/name
        result=subprocess.run([str(args.executable.resolve()),'--adapter','--size',str(w),str(h),str(capture.resolve()),str(directory.resolve())],capture_output=True,text=True,timeout=90)
        (args.output/(name+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
        entry={'size':[w,h],'exit':result.returncode,'status':'FAIL'}
        if result.returncode==0:
            baseline=(directory/'dx11.rgba').read_bytes()
            dx9=(directory/'dx9.rgba').read_bytes()
            exact=len(baseline)==w*h*4 and all((directory/f'adapter-{device}-{cycle}.rgba').read_bytes()==baseline for device in range(2) for cycle in range(3))
            entry.update(status='PASS' if exact else 'FAIL',baselineDifferences=0 if exact else None,
                         dx9Differences=sum(dx9[i:i+4]!=baseline[i:i+4] for i in range(0,len(baseline),4)))
        elif result.returncode==77:
            entry['status']='UNAVAILABLE'
        results.append(entry)
    status='PASS' if all(r['status']=='PASS' for r in results) else 'UNAVAILABLE' if all(r['status']=='UNAVAILABLE' for r in results) else 'FAIL'
    report={'status':status,'capture':str(capture),'runs':results,'dx9Gate':'separate','applicationRenderer':'unchanged'}
    (args.output/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    return 0 if status=='PASS' else 77 if status=='UNAVAILABLE' else 1
if __name__=='__main__':
    raise SystemExit(main())
