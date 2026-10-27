#!/usr/bin/env python3
"""Recapture actual native islands APIs and replay every operation in pure Rust."""
import argparse
import hashlib
from collections import Counter
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from cases import corpus
from observe import prepare
from wake import validate_wake, focused_inputs, negative_controls

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = {k: v for k, v in os.environ.items() if not k.startswith('MDS_ISLANDS_')}
    temporary = output / 'tmp'
    temporary.mkdir(exist_ok=True)
    environment['TMPDIR'] = str(temporary)

    def run(command, **kwargs):
        subprocess.run(list(map(str, command)), check=True, cwd=ROOT / 'rust', env=environment, **kwargs)

    src = ROOT / 'recipes/bullet275/bullet-src/src'
    shim = ROOT / 'rust/crates/mds-bullet-sys/shim'
    crt = ROOT / 'rust/crates/mds-crtmath/src/lib.rs'
    rustc = ['rustup', 'run', '1.95.0', 'rustc']
    run([*rustc, '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'rlib,staticlib', '-O', crt, '--out-dir', output])
    native_sources = sorted(p for folder in ['LinearMath', 'BulletCollision', 'BulletDynamics'] for p in (src / folder).rglob('*.cpp'))
    executable = output / 'native-islands'
    command = [os.environ.get('CXX', 'clang++'), '-std=c++17', '-O2', '-ffp-contract=off', '-fno-fast-math',
               '-fdeclspec', '-w', '-DBT_NO_PROFILE=1', '-I', shim / 'sse_emu', '-I', src, '-I', shim,
               '-include', shim / 'det_math.h', HERE / 'oracle.cpp', *native_sources,
               output / 'libmds_crtmath.a', '-o', executable]
    command += ['-Wl,-dead_strip'] if platform.system() == 'Darwin' else ['-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', '-ldl', '-lpthread', '-lm']
    (output / 'native-command.json').write_text(json.dumps(list(map(str, command)), indent=2) + '\n')
    run(command)
    macros = subprocess.check_output([*command[:command.index(HERE / 'oracle.cpp')], '-dM', '-E', HERE / 'oracle.cpp'], env=environment)
    (output / 'macros.txt').write_bytes(macros)
    inputs, compact_rows, scenarios = corpus()
    captured = subprocess.check_output([executable], input=inputs, env=environment, stderr=subprocess.DEVNULL)
    assert captured
    observed_src = output / 'observed-src'
    prepare(src, observed_src)
    observed_command = [str(x).replace(str(src),str(observed_src)) for x in command]
    observed_command[observed_command.index('-o')+1] = str(output / 'native-observed')
    run(observed_command)
    with (output / 'observer.tsv').open('wb') as trace:
        observed = subprocess.check_output([output / 'native-observed'], input=inputs, env=environment, stderr=trace)
    assert observed == captured, 'observer changed native stdout'
    trace_text = (output / 'observer.tsv').read_text()
    wake_coverage = validate_wake(inputs, trace_text)
    focused = focused_inputs()
    focused_native = subprocess.check_output([executable], input=focused, env=environment, stderr=subprocess.DEVNULL)
    with (output / 'wake-focused-observer.tsv').open('wb') as trace:
        focused_observed = subprocess.check_output([output / 'native-observed'], input=focused, env=environment, stderr=trace)
    assert focused_observed == focused_native, 'observer changed focused native stdout'
    (output / 'wake-focused-inputs.tsv').write_bytes(focused)
    (output / 'wake-focused-native.tsv').write_bytes(focused_native)
    focused_trace = (output / 'wake-focused-observer.tsv').read_text()
    (output / 'wake-coverage.json').write_text(json.dumps(wake_coverage, indent=2) + '\n')
    (output / 'wake-focused-coverage.json').write_text(json.dumps(validate_wake(focused, focused_trace), indent=2) + '\n')
    (output / 'wake-negative-controls.json').write_text(json.dumps(negative_controls(focused, focused_trace), indent=2) + '\n')
    (output / 'inputs.tsv').write_bytes(inputs)
    (output / 'native.tsv').write_bytes(captured)
    fixture = ROOT / 'rust/crates/mds-bullet/tests/islands_data'
    for name, data in [('inputs.tsv', inputs), ('native.tsv', captured)]:
        prefix = b''.join(data.splitlines(keepends=True)[:compact_rows]) if name == 'inputs.tsv' else b''.join(line for line in data.splitlines(keepends=True) if int(line.split()[0]) < compact_rows)
        if args.record:
            (fixture / name).write_bytes(prefix)
        assert (fixture / name).read_bytes() == prefix, name + ' differs from complete frozen prefix'
    binary = output / 'rust-islands'
    common = ['--edition=2021', '--test', '-D', 'warnings', '-O', HERE / 'harness.rs', '--extern', f'mds_crtmath={output / "libmds_crtmath.rlib"}']
    run([*rustc, *common, '-o', binary])
    run(['rustup', 'run', '1.95.0', 'clippy-driver', *common, '-o', output / 'clippy-islands'])
    run([binary])
    environment['MDS_ISLANDS_INPUTS'] = str(output / 'inputs.tsv')
    environment['MDS_ISLANDS_NATIVE'] = str(output / 'native.tsv')
    run([binary])
    environment.pop('MDS_ISLANDS_INPUTS')
    environment.pop('MDS_ISLANDS_NATIVE')
    run([sys.executable, HERE / 'mutations.py', '--out-dir', output / 'mutations', '--crt-rlib', output / 'libmds_crtmath.rlib'])
    files = [*HERE.glob('*.*'), *fixture.glob('*.tsv'), *src.rglob('*.h'), *native_sources,
             *shim.rglob('*.h'), *crt.parent.rglob('*.rs'),
             ROOT / 'rust/crates/mds-bullet/src/core/islands.rs', ROOT / 'rust/crates/mds-bullet/src/core/activation.rs', ROOT / 'rust/crates/mds-bullet/src/core/math.rs',
             ROOT / 'rust/crates/mds-bullet/tests/pure_bullet/islands.rs',
             ROOT / 'rust/crates/mds-bullet/tests/pure_bullet.rs', ROOT / 'rust/crates/mds-bullet/src/core/mod.rs',
             ROOT / '.github/workflows/bullet-primitives.yml', output / 'inputs.tsv', output / 'native.tsv']
    (output / 'sha256.json').write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, indent=2) + '\n')
    provenance = [platform.platform(), subprocess.check_output([os.environ.get('CXX', 'clang++'), '--version'], text=True),
                  subprocess.check_output(['rustup', 'run', '1.95.0', 'rustc', '-Vv'], text=True)]
    (output / 'provenance.txt').write_text('\n'.join(provenance))
    branches = Counter()
    with (output / 'observer.tsv').open() as trace:
        for line in trace:
            fields = line.split()
            if fields[0] == 'I':
                assert len(fields) == 2
                continue
            assert fields[0] in ('UF','O','Q'), fields[0]
            count_index, width = {'UF': (4,2), 'O': (5,6), 'Q': (1,1)}[fields[0]]
            assert len(fields) == count_index + 1 + int(fields[count_index]) * width, 'malformed observer row'
            label = fields[0] if fields[0] == 'Q' else ':'.join(fields[:2])
            branches[label] += 1
            if fields[:2] == ['O', 'scan']:
                branches['scan_skipped' if int(fields[3]) else 'scan_active'] += 1
            if fields[:2] == ['O', 'sleep']:
                branches['all_sleeping' if int(fields[3]) else 'group_awake'] += 1
    assert all(branches[k] for k in ('UF:reset','UF:find','UF:unite','UF:sort','O:sleep','O:wake_A_before','O:wake_A_after','O:wake_B_before','O:wake_B_after','O:scan','O:cursor','Q','scan_skipped','scan_active','all_sleeping','group_awake'))
    (output / 'branches.json').write_text(json.dumps(branches, indent=2)+'\n')
    schema = {
        'schema': 'bullet275-islands-v1', 'status': 'complete',
        'input_sha256': hashlib.sha256(inputs).hexdigest(),
        'native_sha256': hashlib.sha256(captured).hexdigest(),
        'compact_input_sha256': hashlib.sha256((fixture / 'inputs.tsv').read_bytes()).hexdigest(),
        'compact_native_sha256': hashlib.sha256((fixture / 'native.tsv').read_bytes()).hexdigest(),
        'source_hashes': {str(p.relative_to(src)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [src / 'BulletCollision/CollisionDispatch/btUnionFind.h', src / 'BulletCollision/CollisionDispatch/btUnionFind.cpp', src / 'BulletCollision/CollisionDispatch/btSimulationIslandManager.cpp', src / 'BulletDynamics/Dynamics/btDiscreteDynamicsWorld.cpp', src / 'LinearMath/btAlignedObjectArray.h']},
        'observer_stdout_identical': True, 'observer_sources': json.loads((output / 'observer-sources.json').read_text()), 'allocator_history': 'input scenario order; fresh native world per W row',
        'float_encoding': 'all defined f32 fields are raw u32; no masks',
        'object_fields': ['registration_index','activation_state','classification_bits','contact_response','island_tag','companion_id','hit_fraction_bits','deactivation_time_bits'],
        'ignored_bytes': ['padding','absolute addresses','uninitialized manifold fields'],
        'native_command': json.loads((output / 'native-command.json').read_text()),
        'macros_sha256': hashlib.sha256(macros).hexdigest(), 'toolchain': provenance,
    }
    (output / 'schema.json').write_text(json.dumps(schema,indent=2)+'\n')
    compact_scenarios = compact_rows
    summary = {'scenarios': scenarios, 'snapshots': len(captured.splitlines()), 'compact_scenarios': compact_scenarios, 'compact_snapshots': len((fixture / 'native.tsv').read_bytes().splitlines()),
               'native_sources_modified': False, 'masked_words': 0, 'observer_stdout_identical': True, 'mutants': len(json.loads((output / 'mutations/results.json').read_text()))}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
