#!/usr/bin/env python3
"""Replay an existing complete host capture through the current product joint API."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    native = args.capture.resolve()
    counts = probe.counts(native)
    out = args.out_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    joint = out / 'joint_solver.rs'
    probe.save_adapter(probe.JOINT.read_text(),probe.joint_adapter(probe.JOINT.read_text(),native),joint)
    harness = out / 'harness.rs'
    source = (probe.CHECK.parent / 'harness.rs').read_text()
    for relative in re.findall(r'#\[path = "([^"]+)"\]',source):
        path = joint if relative.endswith('/joint_solver.rs') else (probe.CHECK.parent / relative).resolve()
        source = probe.replace_once(source,json.dumps(relative),json.dumps(path.as_posix()))
    harness.write_text(source)
    def run(command, **kwargs):
        subprocess.run(list(map(str,command)),cwd=probe.ROOT / 'rust',check=True,**kwargs)
    crt = probe.ROOT / 'rust/crates/mds-crtmath/src/lib.rs'
    run(['rustup','run','1.95.0','rustc','--edition=2021','--crate-name','mds_crtmath','--crate-type','rlib','-O',crt,'-o',out / 'libmds_crtmath.rlib'])
    run(['rustup','run','1.95.0','rustc','--edition=2021','--crate-name','bullet_core_support','--crate-type','rlib','-O',probe.CHECK.parent / 'support.rs','--extern',f'mds_crtmath={out / "libmds_crtmath.rlib"}','-o',out / 'libbullet_core_support.rlib'])
    exe = out / ('replay.exe' if os.name == 'nt' else 'replay')
    run(['rustup','run','1.95.0','rustc','--edition=2021','--test','-D','warnings','-O',harness,'-L',f'dependency={out}','--extern',f'bullet_core_support={out / "libbullet_core_support.rlib"}','--extern',f'mds_crtmath={out / "libmds_crtmath.rlib"}','-o',exe])
    actual = out / 'rust.tsv'
    if actual.exists():actual.unlink()
    env = dict(os.environ,MDS_JOINT_ACTUAL=str(actual),MDS_JOINT_EXPECTED_EVENTS=str(counts['simd_events']))
    run([exe,'joint_solver::native_joint_solver_matches_every_setup_iteration_and_writeback_bit','--exact','--nocapture'],env=env)
    actual_counts=probe.counts(actual)
    assert actual_counts == counts
    assert probe.input_fingerprint(actual) == probe.input_fingerprint(native)
    (out / 'status.json').write_text(json.dumps({'status':'PASS','native':str(native),'native_counts':counts,'rust_counts':actual_counts,'inputs':probe.input_fingerprint(native),'scope':'complete current joint replay, no cross-host output-bit equivalence claim'},indent=2)+'\n')

if __name__ == '__main__':main()
