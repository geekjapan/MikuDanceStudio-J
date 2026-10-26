#!/usr/bin/env python3
"""Compile isolated source mutations and require the compact fixture to reject each."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--crt-rlib', type=Path, required=True)
    args = parser.parse_args()
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = (ROOT / 'rust/crates/mds-bullet/src/core/shape.rs').read_text()
    start = source.index('    /// Nonvirtual convex support')
    end = source.index('    pub fn margin(self)', start)
    prefix, body, suffix = source[:start], source[start:end], source[end:]
    with_margin = body.index('    pub fn supporting_vertex_nonvirtual')
    mutations = {
        'virtual-substitute': body[:with_margin] + '    pub fn supporting_vertex_nonvirtual(self, direction: Vec3) -> Option<Vec3> { self.supporting_vertex(direction) }\n',
        'sphere-radius-without-margin': body.replace('Self::Sphere { .. } => Vec3::ZERO', 'Self::Sphere { radius } => direction.normalize().scale(radius)'),
        'capsule-margin-removal': body.replace('.sub(v.scale(CONVEX_MARGIN))', ''),
        'cap-greater-equal': body.replace('dot > maximum', 'dot >= maximum'),
        'capsule-threshold-equal': body.replace('length2 < 0.0001', 'length2 <= 0.0001'),
        'capsule-length-association': body.replace('(z * z + y * y) + x * x', '(x * x + y * y) + z * z'),
        'capsule-radius-association': body.replace('.scale(radius))\n                        .sub(v.scale(CONVEX_MARGIN))', '.scale(radius - CONVEX_MARGIN))'),
        'margin-length-association': body.replace('(y * y + z * z) + x * x', '(x * x + y * y) + z * z'),
    }
    outcomes = {}
    for name, mutated in mutations.items():
        assert mutated != body, name
        directory = output / name
        directory.mkdir(exist_ok=True)
        shape = directory / 'shape.rs'
        shape.write_text(prefix + mutated + suffix)
        harness = directory / 'test.rs'
        math = ROOT / 'rust/crates/mds-bullet/src/core/math.rs'
        test = ROOT / 'rust/crates/mds-bullet/tests/pure_bullet/support.rs'
        harness.write_text(f'#![allow(dead_code)]\nmod core {{ #[path = "{math}"] pub mod math; #[path = "{shape}"] pub mod shape; }}\n#[path = "{test}"] mod support;\n')
        executable = directory / 'test'
        command = ['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--test', '-O', str(harness), '--extern', f'mds_crtmath={args.crt_rlib.resolve()}', '-o', str(executable)]
        subprocess.run(command, cwd=ROOT / 'rust', check=True)
        result = subprocess.run([executable], capture_output=True, text=True)
        (directory / 'test.log').write_text(result.stdout + result.stderr)
        outcomes[name] = 'rejected' if result.returncode else 'SURVIVED'
        print(name, outcomes[name], flush=True)
    (output / 'results.json').write_text(json.dumps(outcomes, indent=2) + '\n')
    if 'SURVIVED' in outcomes.values():
        raise SystemExit('A support mutation survived the compact corpus')

if __name__ == '__main__':
    main()
