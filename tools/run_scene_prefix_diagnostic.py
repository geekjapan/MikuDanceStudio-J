"""Capture and replay a single-sample PMM prefix without enabling an app backend."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('gui', 'application', 'parity', 'replay', 'fixture', 'output'):
        parser.add_argument('--'+arg, required=True, type=Path)
    parser.add_argument('--model', default='Dammy_Bone.pmd')
    parser.add_argument('--ground', action='store_true', help='enable ground only in the temporary PMM fixture')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(not p.is_file() for p in (args.gui,args.application,args.parity,args.replay,args.fixture)):
        report = {'status':'UNAVAILABLE','reason':'missing executable or private fixture','productionActivation':False}
        (output/'run.json').write_text(json.dumps(report,indent=2)+'\n')
        return 77
    # Each run needs a fresh directory: never accept a prior manifest following
    # a failed GUI run. Preserve earlier evidence rather than deleting it.
    if (output/'history_replay.scene_prefix.manifest').exists():
        raise ValueError('choose a fresh output directory for application capture')
    env = {k:v for k,v in os.environ.items() if not k.startswith('MDS_RHI_')}
    env.update(MDS_PMM_GUI_FIXTURE=str(args.fixture.resolve()),MDS_PMM_RELOCATE_MODEL=args.model,
               MDS_RHI_HISTORY_REPLAY='1',MDS_RHI_PORTABLE_REPLAY='1',MDS_RHI_REPLAY_SINGLE_SAMPLE_CONTROL='1',
               MDS_RHI_REAL_BATCH_CAPTURE='1',MDS_RHI_GUI_MODE='model',MDS_RHI_GUI_MATERIAL='13',
               MDS_RHI_PORTABLE_MIP_CAPTURE='1',MDS_RHI_PORTABLE_SHADOW_CAPTURE='1',
               MDS_RHI_HISTORY_TRACE='1',MDS_RHI_PORTABLE_PREFIX_EXPORT='1',MDS_RHI_EVIDENCE_DIR=str(output))
    if args.ground:
        env['MDS_RHI_GUI_GROUND']='1'
    command = [str(p.resolve()) for p in (args.gui,args.application,args.parity)]
    with (output/'gui.log').open('w',encoding='utf-8') as log:
        gui = subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
    report = {'guiExit':gui.returncode,'groundTemporaryFixture':args.ground,'productionActivation':False}
    manifest = output/'history_replay.scene_prefix.manifest'
    if not manifest.is_file():
        report.update(status='UNAVAILABLE' if gui.returncode==77 else 'FAIL',reason='no fresh prefix manifest')
        (output/'run.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))
        return gui.returncode or 1
    with (output/'replay.log').open('w',encoding='utf-8') as log:
        replay = subprocess.run([str(args.replay.resolve()),'--scene-prefix-normal',str(output),str(output/'candidate')],stdout=log,stderr=subprocess.STDOUT,timeout=180)
    report.update(replayExit=replay.returncode,status='PASS' if gui.returncode==0 and replay.returncode==0 else 'BLOCKED' if 31 in (gui.returncode,replay.returncode) else 'FAIL')
    (output/'run.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
    return replay.returncode or gui.returncode


if __name__ == '__main__':
    raise SystemExit(main())
