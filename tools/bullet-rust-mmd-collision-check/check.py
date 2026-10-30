#!/usr/bin/env python3
"""Genuine MMD collision diagnostic scaffold. Captures remain UNADMITTED."""
import argparse
import os
from pathlib import Path
import platform
import re
import shutil
import sys

from cases import corpus
from evidence import (Recorder, admit_capture, digest, include_occurrences, include_projection,
                      require, save, selected_members, selected_overrides, verify_archive, validate_native_lifetimes,
                      macro_source, policy, command_schedule, Capture, candidate_capture, actual_peer_controls, admit_replay, _admit_replay)
from hooks import CORE, MUTANTS, NATIVE_OBSERVATIONS, OBSERVATION_PATHS, instrument, inverse, mutate
from trace import common, frames, semantic_projection, validate_lifetimes

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = 'f6ab4feef335e76d590c3f8a9c5f532dec73ba70'
BASE_TREE = '005ae1183e9972df56689796cf87589117418e7d'
FOLDERS = ['recipes/bullet275/bullet-src/src', 'rust/crates/mds-bullet/src/core',
           'rust/crates/mds-bullet/tests', 'rust/crates/mds-bullet-sys/shim',
           'rust/crates/mds-crtmath/src', 'tools/bullet-rust-mmd-collision-check']
EXTRA = ['.github/workflows/bullet-mmd-collision-world.yml', 'rust/crates/mds-bullet-sys/build.rs',
         'rust/crates/mds-bullet/Cargo.toml', 'rust/Cargo.lock', '.gitattributes', 'rust/.gitattributes']
PENDING = ['same-HEAD hosted native and Windows replay execution after independent source review']


def source_paths():
    paths = {p for folder in FOLDERS for p in (ROOT / folder).rglob('*')
             if p.is_file() and '__pycache__' not in p.parts}
    paths.update(ROOT / path for path in EXTRA)
    require(all(not p.is_symlink() for p in paths), 'regular source closure')
    return sorted(paths)


def snapshot():
    return {p.relative_to(ROOT).as_posix(): digest(p.read_bytes()) for p in source_paths()}


def copy_sources(target):
    for folder in FOLDERS:
        shutil.copytree(ROOT / folder, target / folder, ignore=shutil.ignore_patterns('__pycache__'))
    for name in EXTRA:
        dst = target / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dst)


def native_flags(root):
    src, shim = root / 'recipes/bullet275/bullet-src/src', root / 'rust/crates/mds-bullet-sys/shim'
    if os.name == 'nt':
        return ['/nologo', '/std:c++17', '/O2', '/MD', '/EHsc', '/fp:precise', '/DBT_NO_PROFILE=1',
                '/DWIN32', '/showIncludes', '/I' + str(src), '/I' + str(shim), '/FI' + str(shim / 'det_math.h')]
    return ['-std=c++17', '-O2', '-ffp-contract=off', '-fno-fast-math', '-fdeclspec', '-DBT_NO_PROFILE=1',
            '-H', '-I', shim / 'sse_emu', '-I', src, '-I', shim, '-include', shim / 'det_math.h']


def compiled_controls(recorder, out, shadow, rargs, suffix, inputs, expected):
    controls = {}
    for name, (_, _, _, field) in MUTANTS.items():
        target = out / 'mutants' / name
        shutil.copytree(shadow, target)
        recorder.generated_roots = [shadow, target]
        entry = target / 'tools/bullet-rust-mmd-collision-check/runner.rs'
        baseline = out / ('baseline-' + name + suffix)
        recorder.run('baseline-build-' + name, [*rargs, '--cfg', 'test', entry, '-o', baseline],
                     cwd=ROOT / 'rust', inputs=[entry, out / 'libmds_crtmath.rlib'], outputs=[baseline])
        clean = frames(recorder.run('baseline-run-' + name, [baseline], cwd=ROOT / 'rust', data=inputs.encode()), inputs)
        validate_lifetimes(clean)
        require(clean == expected, 'same-host full clean baseline ' + name)
        changed = mutate(target, name)
        save(out / ('mutation-' + name + '.json'), changed)
        executable = out / ('mutant-' + name + suffix)
        recorder.run('mutant-build-' + name, [*rargs, '--cfg', 'test', entry, '-o', executable],
                     cwd=ROOT / 'rust', inputs=[entry, out / 'libmds_crtmath.rlib'], outputs=[executable])
        rows = frames(recorder.run('mutant-run-' + name, [executable], cwd=ROOT / 'rust', data=inputs.encode()), inputs)
        validate_lifetimes(rows)
        differences = [i for i, (a, b) in enumerate(zip(clean, rows)) if a != b]
        directed = [i for i, (a, b) in enumerate(zip(clean, rows))
                    if semantic_projection(a, field) != semantic_projection(b, field)]
        require(differences and directed, 'normally exiting full trace with intended semantic difference ' + name)
        controls[name] = {'field': field, 'different_rows': differences, 'semantic_rows': directed,
                          'baseline_binary_sha256': digest(baseline.read_bytes()),
                          'mutant_binary_sha256': digest(executable.read_bytes()),
                          'normal_exit': True, 'full_trace': True}
    save(out / 'semantic-controls.json', controls)
    recorder.generated_roots = [shadow]
    return controls


def capture(out):
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'compiler and actual capture are hosted-only')
    require((platform.system(), platform.machine().lower()) in {
        ('Windows', 'amd64'), ('Windows', 'x86_64'), ('Darwin', 'arm64'),
        ('Linux', 'x86_64'), ('Linux', 'aarch64'), ('Linux', 'arm64')}, 'supported actual host')
    require(not out.exists(), 'fresh unique output directory')
    require(ROOT != out and ROOT not in out.parents and out not in ROOT.parents, 'disjoint source and capture roots')
    out.mkdir(parents=True)
    inputs, cases = corpus()
    (out / 'inputs.txt').write_bytes(inputs.encode())
    save(out / 'cases.json', cases)
    status = {'schema': 1, 'status': 'UNRUN', 'base': BASE, 'base_tree': BASE_TREE,
              'host': {'system': platform.system(), 'machine': platform.machine()},
              'scope': 'private MMD collision ownership', 'pending': PENDING,
              'native_accelerator': 'unchanged genuine constructor; Rust query and allocation parity excluded'}
    save(out / 'report.json', status)
    recorder = Recorder(out, snapshot)
    try:
        python = recorder.bind_tool(sys.executable)['path']
        for path in source_paths():
            dst = out / 'source' / path.relative_to(ROOT)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(path.read_bytes())
        head = recorder.run('git-head', ['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
        require(not recorder.run('git-status', ['git', 'status', '--porcelain=v1'], cwd=ROOT).strip(), 'clean producer source')
        status['head'] = head
        compiler = recorder.bind_tool(os.environ.get('CXX', 'cl' if os.name == 'nt' else 'clang++'))['path']
        rustup = 'rustup'
        rustc = recorder.run('rustc-path', [rustup, 'which', '--toolchain', '1.95.0', 'rustc'], cwd=ROOT / 'rust').decode().strip()
        version = recorder.run('rust-version', [rustc, '-Vv'], cwd=ROOT / 'rust')
        require(b'release: 1.95.0\n' in version.replace(b'\r\n', b'\n'), 'actual pinned Rust compiler')
        require(os.environ.get('BULLET_ALLOC_LOG') is None and os.environ.get('OPENMMD_DUMP_SPRING') is None,
                'native environment logging disabled')
        require(not os.environ.get('CL') and not os.environ.get('_CL_'), 'no ambient MSVC flag injection')
        rust_linker = recorder.bind_tool('link.exe' if os.name == 'nt' else 'cc')['path']
        native_linker = (rust_linker if os.name == 'nt' else recorder.bind_tool(
            recorder.run('native-linker-path', [compiler, '-print-prog-name=ld'], cwd=ROOT / 'rust').decode().strip())['path'])
        rust = [rustc, '--edition=2021', '-O', '-C', 'linker=' + rust_linker]
        recorder.run('crt-build', [*rust, '--crate-name', 'mds_crtmath', '--crate-type', 'rlib,staticlib',
                     '--print', 'native-static-libs', ROOT / 'rust/crates/mds-crtmath/src/lib.rs', '--out-dir', out],
                     cwd=ROOT / 'rust', inputs=[ROOT / 'rust/crates/mds-crtmath/src/lib.rs'],
                     outputs=[out / 'libmds_crtmath.rlib', out / ('mds_crtmath.lib' if os.name == 'nt' else 'libmds_crtmath.a')])
        rargs = [*rust, '--extern', 'mds_crtmath=' + str(out / 'libmds_crtmath.rlib')]
        suffix, extension = ('.exe', '.obj') if os.name == 'nt' else ('', '.o')
        focused = out / ('dedicated' + suffix)
        dedicated = ROOT / 'rust/crates/mds-bullet/tests/mmd_collision_world.rs'
        recorder.run('dedicated-build', [*rargs, '--test', '-D', 'warnings', dedicated, '-o', focused],
                     cwd=ROOT / 'rust', inputs=[dedicated, out / 'libmds_crtmath.rlib'], outputs=[focused])
        dedicated_names = recorder.run('dedicated-list', [focused, '--list', '--format', 'terse'], cwd=ROOT / 'rust').decode().splitlines()
        expected_dedicated = [line for line in dedicated_names if line.startswith('mmd_world_') and line.endswith(': test')]
        require(expected_dedicated, 'nonempty real dedicated behavior test inventory')
        focused_log = recorder.run('dedicated-run', [focused, 'mmd_world_'], cwd=ROOT / 'rust').decode()
        require(f'test result: ok. {len(expected_dedicated)} passed; 0 failed; 0 ignored;' in focused_log, 'all listed dedicated tests executed')
        pure = out / ('pure' + suffix)
        recorder.run('pure-build', [*rargs, '--test', '-D', 'warnings', ROOT / 'rust/crates/mds-bullet/tests/pure_bullet.rs', '-o', pure],
                     cwd=ROOT / 'rust', inputs=[ROOT / 'rust/crates/mds-bullet/tests/pure_bullet.rs', out / 'libmds_crtmath.rlib'], outputs=[pure])
        pure_names = recorder.run('pure-list', [pure, '--list', '--format', 'terse'], cwd=ROOT / 'rust').decode().splitlines()
        expected_pure = [line for line in pure_names if line.endswith(': test')]
        require(expected_pure, 'nonempty real pure suite inventory')
        pure_log = recorder.run('pure-run', [pure], cwd=ROOT / 'rust').decode()
        require(f'test result: ok. {len(expected_pure)} passed; 0 failed; 0 ignored; 0 measured; 0 filtered out' in pure_log,
                'complete listed pure suite executed')
        shadow = out / 'generated'
        copy_sources(shadow)
        originals = {path: (shadow / path).read_bytes() for path in OBSERVATION_PATHS}
        edits = instrument(shadow, HERE)
        inverse(shadow, edits, originals)
        save(out / 'observation-edits.json', edits)
        recorder.generated_roots.append(shadow)
        save(out / 'generated-start.json', recorder.generated_snapshot())
        rust_exe = out / ('rust-mmd' + suffix)
        runner = shadow / 'tools/bullet-rust-mmd-collision-check/runner.rs'
        recorder.run('rust-observed-build', [*rargs, '--cfg', 'test', runner, '-o', rust_exe],
                     cwd=ROOT / 'rust', inputs=[runner, out / 'libmds_crtmath.rlib'], outputs=[rust_exe])
        rust_rows = frames(recorder.run('rust-observed-run', [rust_exe], cwd=ROOT / 'rust', data=inputs.encode()), inputs)
        save(out / 'rust-lifetimes.json', validate_lifetimes(rust_rows))
        src = ROOT / 'recipes/bullet275/bullet-src/src'
        sources = sorted(p for folder in ['BulletCollision', 'BulletDynamics', 'LinearMath'] for p in (src / folder).rglob('*.cpp'))
        objects, bindings, include_aliases = [], [], {}
        def acquire(occurrences, cwd):
            result = []
            for occurrence in occurrences:
                path = Path(occurrence['raw'])
                if not path.is_absolute():
                    path = cwd / path
                target = path.resolve(strict=True)
                require(target.is_file(), 'resolved include regular file')
                raw = target.read_bytes()
                value = digest(raw)
                retained = out / 'include-bytes' / value
                retained.parent.mkdir(exist_ok=True)
                if not retained.exists():
                    retained.write_bytes(raw)
                result.append({**occurrence, 'target': os.path.normcase(str(target)), 'sha256': value})
            return result
        def compile_object(source, obj, label, root=ROOT, extra=()):
            flags = native_flags(root)
            cwd = ROOT / 'rust'
            def argv(output):
                return ([compiler, *flags, *extra, '/c', source, '/Fo' + str(output)] if os.name == 'nt'
                        else [compiler, *flags, *extra, '-c', source, '-o', output])
            discovery = obj.with_name('discovery-' + obj.name)
            raw = recorder.run(label + '-discovery', argv(discovery), cwd=cwd, inputs=[source], outputs=[discovery])
            occurrences = include_occurrences(raw, (out / (label + '-discovery.stderr')).read_bytes(), platform.system())
            pre = acquire(occurrences, cwd)
            pre_manifest, pre_aliases = include_projection(pre, occurrences, platform.system())
            save(out / (label + '-includes-pre.json'), pre_manifest)
            dependencies = [Path(binding['target']) for binding in pre]
            raw = recorder.run(label, argv(obj), cwd=cwd, inputs=[source, *dependencies], outputs=[obj])
            occurrences = include_occurrences(raw, (out / (label + '.stderr')).read_bytes(), platform.system())
            post = acquire(occurrences, cwd)
            post_manifest, post_aliases = include_projection(post, occurrences, platform.system())
            require(pre_manifest == post_manifest and pre_aliases == post_aliases, 'discovery pre-use/measured include preservation')
            save(out / (label + '-include-bindings.json'), {'schema': 1, 'label': label, 'cwd': str(cwd), 'pre': pre, 'post': post})
            save(out / (label + '-includes.json'), post_manifest)
            for spelling, binding in post_aliases.items():
                key = (str(cwd), spelling)
                require(key not in include_aliases or include_aliases[key] == binding, 'consistent include alias across commands')
                include_aliases[key] = binding
        for i, source in enumerate(sources):
            obj = out / (source.stem + extension)
            require(obj not in objects, 'unique archive member name')
            compile_object(source, obj, f'compile-{i:03d}')
            objects.append(obj)
            bindings.append({'source': source.relative_to(ROOT).as_posix(), 'source_sha256': digest(source.read_bytes()),
                             'object': obj.name, 'object_sha256': digest(obj.read_bytes())})
            if source.stem in {'btDbvt', 'btDbvtBroadphase'}:
                flags = native_flags(ROOT)
                expanded = recorder.run('expanded-' + source.stem,
                    [compiler, *flags, '/E', source] if os.name == 'nt' else [compiler, *flags, '-E', source],
                    cwd=ROOT / 'rust', inputs=[source])
                observed_policy = policy(expanded.decode())
                require(observed_policy['policy'] == ('mmd-win64-sse' if os.name == 'nt' else 'generic-reference'), 'actual native archive numeric policy')
                save(out / ('policy-' + source.stem + '.json'), observed_policy)
        macro = out / 'effective-macros.cpp'
        macro.write_bytes(macro_source())
        macro_obj, macro_exe = out / ('effective-macros' + extension), out / ('effective-macros' + suffix)
        compile_object(macro, macro_obj, 'macro-build')
        recorder.run('macro-link', [compiler, '/nologo', '/MD', macro_obj, '/Fe' + str(macro_exe)] if os.name == 'nt'
                     else [compiler, macro_obj, '-fuse-ld=' + native_linker, '-o', macro_exe], cwd=ROOT / 'rust', inputs=[macro_obj], outputs=[macro_exe])
        macros = recorder.run('actual-macros', [macro_exe], cwd=ROOT / 'rust')
        require(all(value in macros for value in [b'pointer_bits=64', b'scalar_bytes=4', b'MDS_BT_SYSTEM_MATH=<undefined>',
                                                b'sinf=mds_crt_sinf', b'BT_NO_PROFILE=1']), 'actual supported ABI and deterministic math policy')
        archive = out / ('BulletMmd.lib' if os.name == 'nt' else 'libBulletMmd.a')
        recorder.run('archive-build', ['lib', '/NOLOGO', '/OUT:' + str(archive), *objects] if os.name == 'nt'
                     else ['ar', 'rcs', archive, *objects], cwd=ROOT / 'rust', inputs=objects, outputs=[archive])
        listing = recorder.run('archive-list', ['lib', '/NOLOGO', '/LIST', archive] if os.name == 'nt' else ['ar', 't', archive], cwd=ROOT / 'rust', inputs=[archive]).decode().splitlines()
        original_sources = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in source_paths()}
        parsed_archive = verify_archive(archive.read_bytes(), [line.strip() for line in listing if line.strip()],
                                        platform.system(), bindings, {p.name: p.read_bytes() for p in objects}, original_sources)
        save(out / 'archive-bindings.json', bindings)
        extracted = out / 'archive-payloads'
        extracted.mkdir()
        for name, raw in parsed_archive.payloads.items():
            base = name.replace('\\', '/').rsplit('/', 1)[-1]
            (extracted / base).write_bytes(raw)
        save(out / 'archive-payload-identities.json', {name: digest(raw) for name, raw in parsed_archive.payloads.items()})
        hook_header = HERE / 'observer.h'
        hook_flags = ['/FI' + str(hook_header), '/DDW_OBSERVED=1'] if os.name == 'nt' else ['-include', hook_header, '-DDW_OBSERVED=1']
        overrides = []
        for i, path in enumerate(NATIVE_OBSERVATIONS):
            obj = out / ('observed-' + Path(path).stem + extension)
            compile_object(shadow / path, obj, f'observed-object-{i}', shadow, hook_flags)
            overrides.append(obj)
        crt = out / ('mds_crtmath.lib' if os.name == 'nt' else 'libmds_crtmath.a')
        libs = ((out / 'crt-build.stderr').read_text().split('native-static-libs:')[-1].splitlines()[0].split()
                if os.name == 'nt' else ([] if platform.system() == 'Darwin' else ['-ldl', '-lpthread', '-lm']))
        native_rows = {}
        for name, root, extra, prefix in [('native', ROOT, [], []), ('observed', shadow, hook_flags, overrides)]:
            source = root / 'tools/bullet-rust-mmd-collision-check/oracle.cpp'
            obj, exe = out / (name + '-consumer' + extension), out / (name + suffix)
            compile_object(source, obj, name + '-consumer-build', root, extra)
            linkmap = out / (name + '.map')
            args = ([compiler, '/nologo', '/MD', '/EHsc', obj, *prefix, archive, crt, '/Fe' + str(exe), '/link', '/MAP:' + str(linkmap), '/VERBOSE:LIB', *libs]
                    if os.name == 'nt' else [compiler, obj, *prefix, archive, crt, *libs, '-fuse-ld=' + native_linker,
                    ('-Wl,-map,' if platform.system() == 'Darwin' else '-Wl,-Map,') + str(linkmap), '-o', exe])
            link_output = recorder.run(name + '-link', args, cwd=ROOT / 'rust', inputs=[obj, *prefix, archive, crt], outputs=[exe, linkmap])
            link_data = linkmap.read_bytes()
            if platform.system() != 'Darwin':
                link_data += b'\n' + link_output + b'\n' + (out / (name + '-link.stderr')).read_bytes()
            selected = selected_members(link_data, platform.system(), str(archive))
            require(selected and selected <= {p.name for p in objects}, 'selected actual archive payloads')
            if platform.system() == 'Darwin':
                selected_overrides(link_data, [str(p) for p in prefix])
            save(out / (name + '-link-selection.json'), sorted(selected))
            raw = recorder.run(name + '-run', [exe], cwd=ROOT / 'rust', data=inputs.encode())
            native_rows[name] = frames(raw, inputs, observed=name == 'observed')
            if name == 'observed':
                save(out / 'observed-trace-lifetimes.json', validate_lifetimes(native_rows[name]))
            lifecycle = validate_native_lifetimes((out / (name + '-run.stderr')).read_bytes().replace(b'\r\n', b'\n'),
                                                  inputs, observed=name == 'observed')
            save(out / (name + '-lifetime-summary.json'), lifecycle)
        require(common(native_rows['native']) == common(native_rows['observed']), 'common original/observed noninterference')
        require(rust_rows == native_rows['observed'], 'ordered diagnostic native/Rust equality')
        controls = compiled_controls(recorder, out, shadow, rargs, suffix, inputs, rust_rows)
        inverse(shadow, edits, originals)
        endings = []
        for (cwd, spelling), binding in include_aliases.items():
            acquired = acquire([{'stream': 'stdout', 'ordinal': 0, 'raw': spelling}], Path(cwd))[0]
            require((acquired['target'], acquired['sha256']) == binding, 'native include alias end preservation')
            endings.append({'cwd': cwd, 'raw': spelling, 'target': acquired['target'], 'sha256': acquired['sha256']})
        save(out / 'native-include-bindings-end.json', {'schema': 1, 'bindings': endings})
        save(out / 'generated-end.json', recorder.generated_snapshot())
        recorded = {record['label']: record for record in recorder.commands}
        producer = {'schema': 1, 'system': platform.system(), 'root': str(ROOT), 'out': str(out),
                    'tools': {name: recorded[label]['argv'][0] for name, label in [
                        ('git', 'git-head'), ('rustup', 'rustc-path'), ('rustc', 'rust-version'),
                        ('compiler', 'compile-000'), ('archiver', 'archive-build')]}}
        producer['tools'].update(python=python, rust_linker=rust_linker, native_linker=native_linker)
        save(out / 'producer.json', producer)
        schedule = command_schedule(producer, [p.relative_to(ROOT).as_posix() for p in sources], libs)
        require([(r['label'], tuple(r['argv']), r['cwd']) for r in recorder.commands] ==
                [(r.label, r.argv, r.cwd) for r in schedule], 'exact complete diagnostic command schedule')
        for expected, record in zip(schedule, recorder.commands):
            require(set(record['outputs']) == set(expected.outputs), 'exact produced artifact roles ' + expected.label)
            require(record['stdin_sha256'] == (digest(inputs.encode()) if expected.corpus else None),
                    'exact corpus stdin role ' + expected.label)
        status.update(status='DIAGNOSTIC_EQUAL_UNADMITTED', cases=len(cases), checkpoints=len(inputs.splitlines()),
                      commands=len(recorder.commands), mutant_definitions=len(MUTANTS), compiled_controls=len(controls))
        save(out / 'report.json', status)
    except Exception as error:
        status.update(error=str(error))
        if status['status'] == 'UNRUN':
            status['status'] = 'DIAGNOSTIC_FAILED'
        save(out / 'report.json', status)
        raise
    finally:
        recorder.close()
        save(out / 'artifact-manifest.json', {p.relative_to(out).as_posix(): digest(p.read_bytes()) for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'artifact-manifest.json'})
    expected = {'expected_head':head,'canonical_sources':original_sources,'inputs':inputs,'cases':cases,
                'expected_host':{(platform.system(),platform.machine().lower())}}
    status.update(status='CONTROLLED_PASS',pending=[])
    import json
    report_bytes = (json.dumps(status,indent=2,sort_keys=True)+'\n').encode()
    candidate = candidate_capture(Capture(out),{'report.json':report_bytes})
    peers = actual_peer_controls(candidate,**expected)
    candidate = candidate_capture(candidate,{'actual-capture-controls.json':(json.dumps(peers,indent=2,sort_keys=True)+'\n').encode()})
    admit_capture(candidate,**expected)
    for name in ['actual-capture-controls.json','report.json','artifact-manifest.json']:
        temporary = out / (name+'.pending')
        temporary.write_bytes(candidate[name])
        temporary.replace(out/name)
    admit_capture(out,**expected)


def replay(directory, out):
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'compiler and actual replay are hosted-only')
    require((platform.system(), platform.machine().lower()) in {
        ('Windows', 'amd64'), ('Windows', 'x86_64'), ('Darwin', 'arm64'),
        ('Linux', 'x86_64'), ('Linux', 'aarch64'), ('Linux', 'arm64')}, 'supported actual replay host')
    require(not out.exists(), 'fresh unique replay output directory')
    require(ROOT != out and ROOT not in out.parents and out not in ROOT.parents, 'disjoint source and replay roots')
    out.mkdir(parents=True)
    inputs, cases = corpus()
    (out / 'inputs.txt').write_bytes(inputs.encode())
    save(out / 'cases.json', cases)
    status = {'schema': 1, 'status': 'REPLAY_UNADMITTED', 'pending': PENDING, 'base': BASE, 'base_tree': BASE_TREE,
              'host': {'system': platform.system(), 'machine': platform.machine()}}
    save(out / 'report.json', status)
    recorder = Recorder(out, snapshot)
    try:
        for path in source_paths():
            dst = out / 'source' / path.relative_to(ROOT)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(path.read_bytes())
        head = recorder.run('git-head', ['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
        require(not recorder.run('git-status', ['git', 'status', '--porcelain=v1'], cwd=ROOT).strip(), 'clean replay source')
        producer = admit_capture(directory, expected_head=head,
                                 canonical_sources={p: (ROOT / p).read_bytes() for p in snapshot()},
                                 inputs=inputs, cases=cases,
                                 expected_host={('Windows', 'amd64'), ('Windows', 'x86_64')})
        require(producer.head == head and producer.inputs == inputs and producer.cases == tuple(cases), 'same-HEAD admitted Windows producer')
        status['head'] = head
        status['producer_report_sha256'] = producer.report_sha256
        rustc = recorder.run('rustc-path', ['rustup', 'which', '--toolchain', '1.95.0', 'rustc'], cwd=ROOT / 'rust').decode().strip()
        version = recorder.run('rust-version', [rustc, '-Vv'], cwd=ROOT / 'rust')
        require(b'release: 1.95.0\n' in version.replace(b'\r\n', b'\n'), 'actual pinned replay Rust compiler')
        rust_linker = recorder.bind_tool('link.exe' if os.name == 'nt' else 'cc')['path']
        rust = [rustc, '--edition=2021', '-O', '-C', 'linker=' + rust_linker]
        recorder.run('crt-build', [*rust, '--crate-name', 'mds_crtmath', '--crate-type', 'rlib',
                     ROOT / 'rust/crates/mds-crtmath/src/lib.rs', '--out-dir', out], cwd=ROOT / 'rust',
                     inputs=[ROOT / 'rust/crates/mds-crtmath/src/lib.rs'], outputs=[out / 'libmds_crtmath.rlib'])
        rargs = [*rust, '--extern', 'mds_crtmath=' + str(out / 'libmds_crtmath.rlib')]
        suffix = '.exe' if os.name == 'nt' else ''
        shadow = out / 'generated'
        copy_sources(shadow)
        originals = {path: (shadow / path).read_bytes() for path in OBSERVATION_PATHS}
        edits = instrument(shadow, HERE)
        inverse(shadow, edits, originals)
        save(out / 'observation-edits.json', edits)
        recorder.generated_roots = [shadow]
        save(out / 'generated-start.json', recorder.generated_snapshot())
        entry = shadow / 'tools/bullet-rust-mmd-collision-check/runner.rs'
        executable = out / ('rust-mmd' + suffix)
        recorder.run('rust-observed-build', [*rargs, '--cfg', 'test', entry, '-o', executable], cwd=ROOT / 'rust',
                     inputs=[entry, out / 'libmds_crtmath.rlib'], outputs=[executable])
        raw = recorder.run('rust-observed-run', [executable], cwd=ROOT / 'rust', data=inputs.encode())
        actual = frames(raw, inputs)
        validate_lifetimes(actual)
        require(actual == frames(producer.observed_trace, inputs), 'every admitted Windows checkpoint and raw word replayed')
        controls = compiled_controls(recorder, out, shadow, rargs, suffix, inputs, actual)
        inverse(shadow, edits, originals)
        save(out / 'generated-end.json', recorder.generated_snapshot())
        status.update(cases=len(cases), checkpoints=len(inputs.splitlines()), commands=len(recorder.commands),
                      compiled_controls=len(controls))
        recorded = {record['label']:record for record in recorder.commands}
        save(out / 'replay-producer.json', {'schema':1,'system':platform.system(),'root':str(ROOT),'out':str(out),
             'tools':{'git':recorded['git-head']['argv'][0],'rustup':recorded['rustc-path']['argv'][0],
                      'rustc':recorded['rust-version']['argv'][0],'rust_linker':rust_linker}})
        save(out / 'report.json', status)
    except Exception as error:
        status.update(error=str(error))
        save(out / 'report.json', status)
        raise
    finally:
        recorder.close()
        save(out / 'artifact-manifest.json', {p.relative_to(out).as_posix(): digest(p.read_bytes()) for p in sorted(out.rglob('*'))
                                             if p.is_file() and p.name != 'artifact-manifest.json'})
    current_sources = {p:(ROOT/p).read_bytes() for p in snapshot()}
    _admit_replay(out,producer,expected_head=head,canonical_sources=current_sources,require_pass=False)
    status.update(status='CONTROLLED_PASS',pending=[])
    save(out/'report.json',status)
    save(out/'artifact-manifest.json',{p.relative_to(out).as_posix():digest(p.read_bytes()) for p in sorted(out.rglob('*'))
                                      if p.is_file() and p.name != 'artifact-manifest.json'})
    admit_replay(out,producer,expected_head=head,canonical_sources=current_sources)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--describe', action='store_true')
    parser.add_argument('--out-dir', type=Path)
    parser.add_argument('--replay-dir', type=Path)
    args = parser.parse_args()
    if args.describe:
        import json
        inputs, cases = corpus()
        print(json.dumps({'status': 'SOURCE_ONLY_UNRUN', 'cases': len(cases), 'checkpoints': len(inputs.splitlines()),
                          'mutant_definitions': len(MUTANTS), 'pending': PENDING}, sort_keys=True))
        return
    require(args.out_dir is not None, '--out-dir required')
    if args.replay_dir is not None:
        replay(args.replay_dir.resolve(), args.out_dir.resolve())
    else:
        capture(args.out_dir.resolve())


if __name__ == '__main__':
    main()
