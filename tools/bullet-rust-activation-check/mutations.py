#!/usr/bin/env python3
"""Compile isolated activation mutations and require compact replay to reject them."""
import argparse
import json
import os
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
    source = (ROOT / 'rust/crates/mds-bullet/src/core/activation.rs').read_text()
    mutations = {
        'sticky-state4': ('ActivationState::DisableDeactivation | ActivationState::DisableSimulation', 'ActivationState::DisableSimulation'),
        'sticky-state5': ('ActivationState::DisableDeactivation | ActivationState::DisableSimulation', 'ActivationState::DisableDeactivation'),
        'sleep-time-inclusive': ('self.deactivation_time > settings.time', 'self.deactivation_time >= settings.time'),
        'linear-speed-inclusive': ('linear.length2() < self.linear_sleeping_threshold', 'linear.length2() <= self.linear_sleeping_threshold'),
        'angular-speed-inclusive': ('angular.length2() < self.angular_sleeping_threshold', 'angular.length2() <= self.angular_sleeping_threshold'),
        'activate-static': ('if force || classification == CollisionClassification::Dynamic', 'if force || classification != CollisionClassification::Kinematic'),
        'activate-kinematic': ('if force || classification == CollisionClassification::Dynamic', 'if force || classification != CollisionClassification::Static'),
        'activate-both-flags': ('if force || classification == CollisionClassification::Dynamic', 'if force || classification == CollisionClassification::Dynamic || classification == CollisionClassification::StaticAndKinematic'),
        'sleep-no-zeroing': ('*angular = Vec3::ZERO;\n                    *linear = Vec3::ZERO;', 'let _ = (angular, linear);'),
        'sleep-zeroing-order': ('if self.state == ActivationState::IslandSleeping {\n                    *angular', 'if self.state == ActivationState::WantsDeactivation {\n                    *angular'),
        'world-query-before-update': ('self.update_deactivation(time_step, *linear, *angular);', 'let _ = time_step;'),
        'state-zero-inactive': ('ActivationState::IslandSleeping | ActivationState::DisableSimulation', 'ActivationState::Moving | ActivationState::IslandSleeping | ActivationState::DisableSimulation'),
    }
    results = {}
    environment = {k: v for k, v in os.environ.items() if not k.startswith('MDS_ACTIVATION_')}
    for name, (old, new) in mutations.items():
        assert old in source, name
        changed = source.replace(old, new, 1)
        directory = output / name
        directory.mkdir(exist_ok=True)
        kernel = directory / 'activation.rs'
        kernel.write_text(changed)
        math = ROOT / 'rust/crates/mds-bullet/src/core/math.rs'
        test = ROOT / 'rust/crates/mds-bullet/tests/pure_bullet/activation.rs'
        harness = directory / 'harness.rs'
        harness.write_text(f'#![allow(dead_code)]\nmod core {{ #[path="{math}"] pub mod math; #[path="{kernel}"] pub mod activation; }}\n#[path="{test}"] mod tests;\n')
        binary = directory / 'test'
        subprocess.run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--test', '-O', str(harness), '--extern', f'mds_crtmath={args.crt_rlib.resolve()}', '-o', str(binary)], cwd=ROOT / 'rust', env=environment, check=True)
        result = subprocess.run([binary], capture_output=True, text=True, env=environment, cwd=ROOT / 'rust')
        (directory / 'test.log').write_text(result.stdout + result.stderr)
        results[name] = 'rejected' if result.returncode else 'SURVIVED'
        print(name, results[name], flush=True)
    (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    assert 'SURVIVED' not in results.values(), 'An activation mutation survived'


if __name__ == '__main__':
    main()
