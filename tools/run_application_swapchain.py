"""Run real-PMM application Reset/controller comparison; never count a skip as pass."""
import argparse
import json
import os
from pathlib import Path
import subprocess

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui',required=True,type=Path)
    parser.add_argument('--application',required=True,type=Path)
    parser.add_argument('--evidence',required=True,type=Path)
    parser.add_argument('--single-sample',action='store_true')
    args=parser.parse_args()
    root=args.evidence.resolve()
    root.mkdir(parents=True,exist_ok=True)
    for name in ('request.txt','request.next','results.txt','reset.log'):
        (root/name).unlink(missing_ok=True)
    env=dict(os.environ,MDS_RHI_GUI_MODE='swapchain',MDS_RHI_SWAPCHAIN_CONTROLLER='1',
             MDS_RHI_SWAPCHAIN_LOG=str(root/'reset.log'),MDS_RHI_SWAPCHAIN_TEST_DIR=str(root),
             MIKUDANCESTUDIO_AB_FREEZE_PHYSICS='1',MDS_RHI_SPRITE_ADAPTER='1')
    # Independent lifecycle test, not material/replay precision acceptance.
    for key in list(env):
        if key.startswith(('MDS_RHI_HISTORY','MDS_RHI_MODEL','MDS_RHI_LIVE','MDS_RHI_SHADER','MDS_RHI_TEXTURE')):
            env.pop(key)
    env.pop('MDS_RHI_REPLAY_SINGLE_SAMPLE_CONTROL',None)
    if args.single_sample:
        env['MDS_RHI_REPLAY_SINGLE_SAMPLE_CONTROL']='1'
    try:
        result=subprocess.run([str(args.gui.resolve()),str(args.application.resolve())],env=env,
                              timeout=240,capture_output=True,text=True,errors='replace')
        (root/'gui.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        code=result.returncode
        records=(root/'results.txt').read_text().splitlines() if (root/'results.txt').exists() else []
        logs=(root/'reset.log').read_text() if (root/'reset.log').exists() else ''
        exact=len(records)==6 and all('status=PASS' in r and 'differences=0 ' in r for r in records)
        for sequence in range(1,7):
            old=root/f'{sequence}.legacy.bgra'; new=root/f'{sequence}.controller.bgra'
            exact=exact and old.exists() and new.exists() and old.read_bytes()==new.read_bytes() and old.stat().st_size>0
        exact=exact and logs.count('phase=restored')>=24 and 'controller=1' in logs and logs.count('phase=native_failed')==1 and 'failureRecovery=1' in records[0]
        callbackOrder=True
        pendingFailure=False
        for line in logs.splitlines():
            if line.startswith('phase=native_failed '): pendingFailure=True
            elif line.startswith('phase=native_success '): pendingFailure=False
            elif line.startswith(('phase=mme_reset ','phase=restored ')) and pendingFailure: callbackOrder=False
        exact=exact and callbackOrder
        status='PASS' if code==0 and exact else 'UNAVAILABLE' if code==77 else 'FAIL'
        report={'status':status,'guiExit':code,'pairs':len(records),'sameFramePixelEquality':exact,'resetCallbackOrder':callbackOrder,
                'nativeDriverLoss':'NOT_FORCED','applicationRenderer':'legacy DX9','defaultControllerEnabled':False,'singleSampleControl':args.single_sample}
    except subprocess.TimeoutExpired:
        code=1; report={'status':'FAIL','reason':'GUI test timeout'}
    (root/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['status']=='PASS' else 77 if code==77 else 1
if __name__=='__main__':
    raise SystemExit(main())
