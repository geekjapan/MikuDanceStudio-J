#!/usr/bin/env python3
"""Every mutation must compile and fail the frozen complete-scenario prefix."""
import argparse
import json
import os
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--crt-rlib',type=Path,required=True)
    args=parser.parse_args()
    output=args.out_dir.resolve();output.mkdir(parents=True,exist_ok=True)
    source=(ROOT/'rust/crates/mds-bullet/src/core/gjk_epa.rs').read_text()
    adapter=source.index('pub fn calc_pen_depth(')
    mutations={
        'delete-penetration': source[:adapter]+source[adapter:].replace('if let QueryResult::Success(solution) = penetration(shapes, transforms, guess, true)', 'if let QueryResult::Success(solution) = QueryResult::Failure(Status::Separated)'),
        'delete-distance-fallback': source[:adapter]+source[adapter:].replace('distance(shapes, transforms, guess)', 'QueryResult::Failure(Status::GjkFailed)'),
        'nonvalid-is-failure':source.replace('== EpaStatus::Failed {','!= EpaStatus::Valid {'),
        'face-tie-selection':source.replace('sqd < mind','sqd <= mind'),
        'margin-removal':source.replace('Minkowski::new(shapes, transforms, use_margins)', 'Minkowski::new(shapes, transforms, false)'),
        'epa-accuracy':source.replace('if wdist > 0.0001','if wdist > 0.001'),
        'nonnative-double-length':source.replace('let d = d.scale(1.0 / d.length());','let d = d.scale(1.0 / (d.0.into_iter().map(|v| f64::from(v)*f64::from(v)).sum::<f64>().sqrt() as f32));'),
        'world-normal':source.replace('normal: epa.normal.negate(),','normal: transforms[0].basis.apply(epa.normal.negate()),'),
        'gjk-reduction':source.replace('if mask & (1 << i) != 0','if weight > 0.0'),
    }
    results={}
    environment={k:v for k,v in os.environ.items() if not k.startswith('MDS_GJK_EPA_')}
    for name,changed in mutations.items():
        assert changed!=source,name
        directory=output/name;directory.mkdir(exist_ok=True)
        kernel=directory/'gjk_epa.rs';kernel.write_text(changed)
        math=ROOT/'rust/crates/mds-bullet/src/core/math.rs';shape=math.with_name('shape.rs');test=ROOT/'rust/crates/mds-bullet/tests/pure_bullet/gjk_epa.rs'
        harness=directory/'harness.rs';harness.write_text(f'#![allow(dead_code,unused_variables)]\nmod core {{ #[path="{math}"] pub mod math; #[path="{shape}"] pub mod shape; #[path="{kernel}"] pub mod gjk_epa; }}\n#[path="{test}"] mod gjk_epa;\n')
        binary=directory/'test';command=['rustup','run','1.95.0','rustc','--edition=2021','--test','-O',str(harness),'--extern',f'mds_crtmath={args.crt_rlib.resolve()}','-o',str(binary)]
        subprocess.run(command,cwd=ROOT/'rust',check=True,env=environment)
        result=subprocess.run([binary],capture_output=True,text=True,env=environment)
        (directory/'test.log').write_text(result.stdout+result.stderr)
        results[name]='rejected' if result.returncode else 'SURVIVED';print(name,results[name],flush=True)
    (output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    if 'SURVIVED' in results.values():raise SystemExit('A GJK/EPA mutation survived')
if __name__=='__main__':main()
