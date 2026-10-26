#!/usr/bin/env python3
"""Require each compiled semantic mutation to fail the real native comparison."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--crt-rlib',type=Path,required=True)
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--native',type=Path,required=True)
    args=parser.parse_args();output=args.out_dir.resolve();output.mkdir(parents=True,exist_ok=True)
    core=ROOT/'rust/crates/mds-bullet/src/core'
    pair=(core/'gjk_pair.rs').read_text();contact=(core/'contact.rs').read_text();kernel=(core/'gjk_epa.rs').read_text()
    mutations={
        'delete-penetration':('gjk_epa',kernel.replace('if let QueryResult::Success(solution) = penetration(shapes, transforms, guess, true)','if let QueryResult::Success(solution) = QueryResult::Failure(Status::Separated)')),
        'delete-distance-fallback':('gjk_epa',kernel.replace('} else if let QueryResult::Success(solution) = distance(shapes, transforms, guess)', '} else if let QueryResult::Success(solution) = QueryResult::Failure(Status::GjkFailed)')),
        'nonvalid-is-failure':('gjk_epa',kernel.replace('== EpaStatus::Failed {','!= EpaStatus::Valid {')),
        'face-tie':('gjk_epa',kernel.replace('sqd < mind','sqd <= mind')),
        'stock-final-distance-gate':('gjk_pair',pair.replace('if let Some(mut point) = contact {','if let Some(mut point) = contact.filter(|p| p.distance < 0.0 || p.distance * p.distance < maximum_distance_squared) {')),
        'rotate-fallback-normal':('gjk_pair',pair.replace('PenDepth::Separated(solution) => {\n                query.cached_axis = solution.normal;', 'PenDepth::Separated(solution) => {\n                query.cached_axis = transforms[0].basis.apply(solution.normal);')),
        'normalize-fallback-normal':('gjk_pair',pair.replace('PenDepth::Separated(solution) => {\n                query.cached_axis = solution.normal;', 'PenDepth::Separated(solution) => {\n                query.cached_axis = solution.normal.scale(1.0 / solution.normal.length());')),
        'remove-midpoint':('gjk_pair',pair.replace('let offset = transforms[0].origin.add(transforms[1].origin).scale(0.5);','let offset = Vec3::ZERO;')),
        'fresh-simplex':('gjk_pair',pair.replace('    simplex.reset();','    let mut fresh = VoronoiSimplexSolver::default();\n    let simplex = &mut fresh;\n    simplex.reset();')),
        'erase-cache':('gjk_pair',pair.replace('    simplex.reset();','    simplex.reset();\n    simplex.cached_p1 = Vec3::ZERO;\n    simplex.cached_p2 = Vec3::ZERO;\n    simplex.cached_v = Vec3::ZERO;')),
        'clear-manifold':('contact',contact.replace('            PairKind::ConvexConvex => {','            PairKind::ConvexConvex => {\n                self.count = 0;')),
        'strict-manifold-threshold':('contact',contact.replace('if distance > self.threshold {','if distance >= self.threshold {')),
        'float-threshold-sum':('contact',contact.replace('let sum = self.shapes[1].margin() as f64','let sum = self.shapes[1].margin()').replace('(self.threshold as f64 + self.shapes[0].margin() as f64)','(self.threshold + self.shapes[0].margin())')),
    }
    results={};env=os.environ.copy();env['MDS_GJK_PAIR_INPUTS']=str(args.inputs.resolve());env['MDS_GJK_PAIR_NATIVE']=str(args.native.resolve())
    for name,(module,changed) in mutations.items():
        assert changed!=(core/(module+'.rs')).read_text(),name
        directory=output/name;directory.mkdir(exist_ok=True)
        # The copied contact module's existing private tests still use their original paths.
        changed=re.sub(r'#\[path = "(../../tests/[^\"]+)"\]',lambda m:'#[path = "'+str((core/m[1]).resolve())+'"]',changed)
        source=directory/(module+'.rs');source.write_text(changed)
        harness=(ROOT/'tools/bullet-rust-gjk-pair-check/harness.rs').read_text()
        harness=re.sub(r'#\[path = "([^\"]+)"\]',lambda m:'#[path = "'+str((ROOT/'tools/bullet-rust-gjk-pair-check'/m[1]).resolve())+'"]',harness)
        harness=harness.replace(str(core/(module+'.rs')),str(source)).replace('#![allow(dead_code)]','#![allow(dead_code,unused_variables)]')
        test=directory/'harness.rs';test.write_text(harness);binary=directory/'test'
        subprocess.run(['rustup','run','1.95.0','rustc','--edition=2021','--test','-O',test,'--extern',f'mds_crtmath={args.crt_rlib.resolve()}','-o',binary],check=True,cwd=ROOT/'rust',env=env)
        result=subprocess.run([binary,'outer_and_persistent'],capture_output=True,text=True,cwd=ROOT/'rust',env=env)
        (directory/'test.log').write_text(result.stdout+result.stderr)
        results[name]='rejected' if result.returncode else 'SURVIVED'
        print(name,results[name],flush=True)
    (output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    if 'SURVIVED' in results.values():raise SystemExit('A semantic mutation survived')
if __name__=='__main__':main()
