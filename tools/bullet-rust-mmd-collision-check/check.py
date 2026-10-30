#!/usr/bin/env python3
"""Hosted genuine MMD collision capture, strict admission, and Rust replay."""
import argparse
import os
from pathlib import Path
import platform
import re
import shutil
import sys

from cases import corpus, dynamics_corpus
from evidence import (Recorder, admit_capture, digest, include_occurrences, include_projection,
                      require, save, selected_members, selected_overrides, verify_archive, validate_native_lifetimes,
                      macro_source, policy, command_schedule, read_authority, encode_json, Capture, candidate_capture, actual_peer_controls, admit_replay, _admit_replay)
from hooks import CORE, MUTANTS, NATIVE_OBSERVATIONS, OBSERVATION_PATHS, instrument, inverse, mutate, mutants, observation_paths, native_observations
from trace import common, frames, semantic_projection, validate_lifetimes

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = 'f6ab4feef335e76d590c3f8a9c5f532dec73ba70'
BASE_TREE = '005ae1183e9972df56689796cf87589117418e7d'
DYNAMICS_BASE = '93e5ec6151e8bd3b4d86720b50cc0f2a321e4fcc'
DYNAMICS_BASE_TREE = '7c8f9eaa46d5f05ca46bf180a0a139e547fe3489'
FOLDERS = ['recipes/bullet275/bullet-src/src', 'rust/crates/mds-bullet/src/core',
           'rust/crates/mds-bullet/tests', 'rust/crates/mds-bullet-sys/shim',
           'rust/crates/mds-crtmath/src', 'tools/bullet-rust-mmd-collision-check']
EXTRA = ['.github/workflows/bullet-mmd-collision-world.yml', 'rust/crates/mds-bullet-sys/build.rs',
         'rust/crates/mds-bullet/Cargo.toml', 'rust/Cargo.lock', '.gitattributes', 'rust/.gitattributes',
         'tools/bullet-rust-dbvt-check/fixtures.rs',
         'tools/bullet-rust-dbvt-check/native-topdown-nontermination.tsv']
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


def native_flags(root, dynamics=False):
    src, shim = root / 'recipes/bullet275/bullet-src/src', root / 'rust/crates/mds-bullet-sys/shim'
    if os.name == 'nt':
        return (['/DDW_DYNAMICS=1'] if dynamics else []) + ['/nologo', '/std:c++17', '/O2', '/MD', '/EHsc', '/fp:precise', '/DBT_NO_PROFILE=1',
                '/DWIN32', '/showIncludes', '/I' + str(src), '/I' + str(shim), '/FI' + str(shim / 'det_math.h')]
    return (['-DDW_DYNAMICS=1'] if dynamics else []) + ['-std=c++17', '-O2', '-ffp-contract=off', '-fno-fast-math', '-fdeclspec', '-DBT_NO_PROFILE=1',
            '-H', '-I', shim / 'sse_emu', '-I', src, '-I', shim, '-include', shim / 'det_math.h']


def compiled_controls(recorder, out, shadow, rargs, suffix, inputs, expected, dynamics=False):
    controls = {}
    for name, (_, _, _, field) in mutants(dynamics).items():
        target = out / 'mutants' / name
        shutil.copytree(shadow, target)
        recorder.generated_roots = [shadow, target]
        entry = target / 'tools/bullet-rust-mmd-collision-check/runner.rs'
        baseline = out / ('baseline-' + name + suffix)
        recorder.run('baseline-build-' + name, [*rargs, '--cfg', 'test', entry, '-o', baseline],
                     cwd=ROOT / 'rust', inputs=[entry, out / 'libmds_crtmath.rlib'], outputs=[baseline])
        clean = frames(recorder.run('baseline-run-' + name, [baseline], cwd=ROOT / 'rust', data=inputs.encode()), inputs, dynamics=dynamics)
        validate_lifetimes(clean)
        require(clean == expected, 'same-host full clean baseline ' + name)
        changed = mutate(target, name, dynamics)
        recorder.save(out / ('mutation-' + name + '.json'), changed)
        executable = out / ('mutant-' + name + suffix)
        recorder.run('mutant-build-' + name, [*rargs, '--cfg', 'test', entry, '-o', executable],
                     cwd=ROOT / 'rust', inputs=[entry, out / 'libmds_crtmath.rlib'], outputs=[executable])
        rows = frames(recorder.run('mutant-run-' + name, [executable], cwd=ROOT / 'rust', data=inputs.encode()), inputs, dynamics=dynamics)
        validate_lifetimes(rows)
        differences = [i for i, (a, b) in enumerate(zip(clean, rows)) if a != b]
        directed = [i for i, (a, b) in enumerate(zip(clean, rows))
                    if semantic_projection(a, field) != semantic_projection(b, field)]
        require(differences and directed, 'normally exiting full trace with intended semantic difference ' + name)
        controls[name] = {'field': field, 'different_rows': differences, 'semantic_rows': directed,
                          'baseline_binary_sha256': digest(recorder.read(baseline)),
                          'mutant_binary_sha256': digest(recorder.read(executable)),
                          'normal_exit': True, 'full_trace': True}
    recorder.save(out / 'semantic-controls.json', controls)
    recorder.generated_roots = [shadow]
    return controls


def capture(out, authority_path, dynamics=False):
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'compiler and actual capture are hosted-only')
    require((platform.system(), platform.machine().lower()) in {
        ('Windows', 'amd64'), ('Windows', 'x86_64'), ('Darwin', 'arm64'),
        ('Linux', 'x86_64'), ('Linux', 'aarch64'), ('Linux', 'arm64')}, 'supported actual host')
    require(not out.exists(), 'fresh unique output directory')
    require(ROOT != out and ROOT not in out.parents and out not in ROOT.parents, 'disjoint source and capture roots')
    out.mkdir(parents=True)
    recorder = Recorder(out, snapshot)
    inputs, cases = dynamics_corpus() if dynamics else corpus()
    recorder.write(out / 'inputs.txt', inputs.encode())
    recorder.save(out / 'cases.json', cases)
    status = {'schema': 1, 'status': 'UNRUN', 'base': DYNAMICS_BASE if dynamics else BASE, 'base_tree': DYNAMICS_BASE_TREE if dynamics else BASE_TREE,
              'host': {'system': platform.system(), 'machine': platform.machine()},
              'scope': 'private MMD dynamics ownership' if dynamics else 'private MMD collision ownership', 'pending': PENDING,
              'native_accelerator': 'unchanged genuine constructor; Rust query and allocation parity excluded'}
    recorder.save(out / 'report.json', status)
    try:
        python = recorder.bind_tool(sys.executable)['path']
        for path in source_paths():
            dst = out / 'source' / path.relative_to(ROOT)
            dst.parent.mkdir(parents=True, exist_ok=True)
            recorder.write(dst, path.read_bytes())
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
        if dynamics:
            rargs += ['--cfg', 'mmd_dynamics']
        suffix, extension = ('.exe', '.obj') if os.name == 'nt' else ('', '.o')
        focused = out / ('dedicated' + suffix)
        dedicated = ROOT / ('rust/crates/mds-bullet/tests/mmd_dynamics_world.rs' if dynamics else 'rust/crates/mds-bullet/tests/mmd_collision_world.rs')
        recorder.run('dedicated-build', [*rargs, '--test', '-D', 'warnings', dedicated, '-o', focused],
                     cwd=ROOT / 'rust', inputs=[dedicated, out / 'libmds_crtmath.rlib'], outputs=[focused])
        dedicated_names = recorder.run('dedicated-list', [focused, '--list', '--format', 'terse'], cwd=ROOT / 'rust').decode().splitlines()
        prefix = 'mmd_dynamics_' if dynamics else 'mmd_world_'
        expected_dedicated = [line for line in dedicated_names if line.startswith(prefix) and line.endswith(': test')]
        if dynamics:
            require(len(expected_dedicated) == 9, 'nine private dynamics behavior tests discovered')
            source_names = re.findall(r'^fn (mmd_dynamics_[a-z0-9_]+)\(', dedicated.read_text(), re.M)
            require(len(source_names) == 9 and sorted(expected_dedicated) == sorted(name + ': test' for name in source_names),
                    'expected and discovered dynamics behavior test names agree')
        require(expected_dedicated, 'nonempty real dedicated behavior test inventory')
        focused_log = recorder.run('dedicated-run', [focused, prefix, *(['--test-threads=1'] if dynamics else [])], cwd=ROOT / 'rust').decode()
        require(f'test result: ok. {len(expected_dedicated)} passed; 0 failed; 0 ignored;' in focused_log, 'all listed dedicated tests executed')
        if dynamics:
            require(all(f'test {name} ... ok' in focused_log.splitlines() for name in source_names),
                    'every expected dynamics behavior test executed successfully')
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
        originals = {path: (shadow / path).read_bytes() for path in observation_paths(dynamics)}
        edits = instrument(shadow, HERE, dynamics)
        inverse(shadow, edits, originals)
        recorder.save(out / 'observation-edits.json', edits)
        recorder.generated_roots.append(shadow)
        recorder.save(out / 'generated-start.json', recorder.generated_snapshot())
        rust_exe = out / ('rust-mmd' + suffix)
        runner = shadow / 'tools/bullet-rust-mmd-collision-check/runner.rs'
        recorder.run('rust-observed-build', [*rargs, '--cfg', 'test', runner, '-o', rust_exe],
                     cwd=ROOT / 'rust', inputs=[runner, out / 'libmds_crtmath.rlib'], outputs=[rust_exe])
        rust_rows = frames(recorder.run('rust-observed-run', [rust_exe], cwd=ROOT / 'rust', data=inputs.encode()), inputs, dynamics=dynamics)
        recorder.save(out / 'rust-lifetimes.json', validate_lifetimes(rust_rows))
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
                    recorder.write(retained, raw)
                result.append({**occurrence, 'target': str(target), 'sha256': value})
            return result
        def compile_object(source, obj, label, root=ROOT, extra=()):
            flags = native_flags(root, dynamics)
            cwd = ROOT / 'rust'
            def argv(output):
                return ([compiler, *flags, *extra, '/c', source, '/Fo' + str(output)] if os.name == 'nt'
                        else [compiler, *flags, *extra, '-c', source, '-o', output])
            discovery = obj.with_name('discovery-' + obj.name)
            raw = recorder.run(label + '-discovery', argv(discovery), cwd=cwd, inputs=[source], outputs=[discovery])
            occurrences = include_occurrences(raw, recorder.read(out / (label + '-discovery.stderr')), platform.system())
            pre = acquire(occurrences, cwd)
            pre_manifest, pre_aliases = include_projection(pre, occurrences, platform.system())
            recorder.save(out / (label + '-includes-pre.json'), pre_manifest)
            dependencies = [Path(binding['target']) for binding in pre]
            raw = recorder.run(label, argv(obj), cwd=cwd, inputs=[source, *dependencies], outputs=[obj])
            occurrences = include_occurrences(raw, recorder.read(out / (label + '.stderr')), platform.system())
            post = acquire(occurrences, cwd)
            post_manifest, post_aliases = include_projection(post, occurrences, platform.system())
            require(pre_manifest == post_manifest and pre_aliases == post_aliases, 'discovery pre-use/measured include preservation')
            recorder.save(out / (label + '-include-bindings.json'), {'schema': 1, 'label': label, 'cwd': str(cwd), 'pre': pre, 'post': post})
            recorder.save(out / (label + '-includes.json'), post_manifest)
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
                             'object': obj.name, 'object_sha256': digest(recorder.read(obj))})
            if source.stem in {'btDbvt', 'btDbvtBroadphase'}:
                flags = native_flags(ROOT, dynamics)
                expanded = recorder.run('expanded-' + source.stem.lower(),
                    [compiler, *flags, '/E', source] if os.name == 'nt' else [compiler, *flags, '-E', source],
                    cwd=ROOT / 'rust', inputs=[source])
                observed_policy = policy(expanded.decode())
                require(observed_policy['policy'] == ('mmd-win64-sse' if os.name == 'nt' else 'generic-reference'), 'actual native archive numeric policy')
                recorder.save(out / ('policy-' + source.stem + '.json'), observed_policy)
        macro = out / 'effective-macros.cpp'
        recorder.write(macro, macro_source())
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
        original_sources = {name: recorder.read(out / 'source' / name) for name in recorder.sources}
        parsed_archive = verify_archive(recorder.read(archive), [line.strip() for line in listing if line.strip()],
                                        platform.system(), bindings, {p.name: recorder.read(p) for p in objects}, original_sources)
        recorder.save(out / 'archive-bindings.json', bindings)
        extracted = out / 'archive-payloads'
        extracted.mkdir()
        for name, raw in parsed_archive.payloads.items():
            base = name.replace('\\', '/').rsplit('/', 1)[-1]
            recorder.write(extracted / base, raw)
        recorder.save(out / 'archive-payload-identities.json', {name: digest(raw) for name, raw in parsed_archive.payloads.items()})
        hook_header = HERE / 'observer.h'
        hook_flags = ['/FI' + str(hook_header), '/DDW_OBSERVED=1'] if os.name == 'nt' else ['-include', hook_header, '-DDW_OBSERVED=1']
        overrides = []
        for i, path in enumerate(native_observations(dynamics)):
            obj = out / ('observed-' + Path(path).stem + extension)
            compile_object(shadow / path, obj, f'observed-object-{i}', shadow, hook_flags)
            overrides.append(obj)
        crt = out / ('mds_crtmath.lib' if os.name == 'nt' else 'libmds_crtmath.a')
        libs = (recorder.read(out / 'crt-build.stderr').decode().split('native-static-libs:')[-1].splitlines()[0].split()
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
            link_data = recorder.read(linkmap)
            if platform.system() != 'Darwin':
                link_data += b'\n' + link_output + b'\n' + recorder.read(out / (name + '-link.stderr'))
            selected = selected_members(link_data, platform.system(), str(archive))
            require(selected and selected <= {p.name for p in objects}, 'selected actual archive payloads')
            if platform.system() == 'Darwin':
                selected_overrides(link_data, [str(p) for p in prefix])
            recorder.save(out / (name + '-link-selection.json'), sorted(selected))
            for role in (['ordinary', 'ascending', 'descending', 'alternating'] if dynamics else [None]):
                label = name + '-run' + ('-' + role if role and role != 'ordinary' else '')
                raw = recorder.run(label, [exe, role] if role else [exe], cwd=ROOT / 'rust', data=inputs.encode())
                rows = frames(raw, inputs, observed=name == 'observed', dynamics=dynamics)
                native_rows[name if role in {None, 'ordinary'} else name + '-' + role] = rows
                if name == 'observed':
                    require(rows == rust_rows, 'every allocator role matches exact Rust trace')
                    recorder.save(out / (label.replace('-run', '-trace') + '-lifetimes.json'), validate_lifetimes(rows))
                lifecycle = validate_native_lifetimes(recorder.read(out / (label + '.stderr')).replace(b'\r\n', b'\n'),
                                                      inputs, observed=name == 'observed', role=role)
                recorder.save(out / (label.replace('-run', '') + '-lifetime-summary.json'), lifecycle)
        for role in (['', '-ascending', '-descending', '-alternating'] if dynamics else ['']):
            require(common(native_rows['native' + role], dynamics=dynamics) == common(native_rows['observed' + role], dynamics=dynamics), 'common original/observed noninterference for each role')
        require(rust_rows == native_rows['observed'], 'ordered diagnostic native/Rust equality')
        controls = compiled_controls(recorder, out, shadow, rargs, suffix, inputs, rust_rows, dynamics)
        inverse(shadow, edits, originals)
        endings = []
        for (cwd, spelling), binding in include_aliases.items():
            acquired = acquire([{'stream': 'stdout', 'ordinal': 0, 'raw': spelling}], Path(cwd))[0]
            require((acquired['target'], acquired['sha256']) == binding, 'native include alias end preservation')
            endings.append({'cwd': cwd, 'raw': spelling, 'target': acquired['target'], 'sha256': acquired['sha256']})
        recorder.save(out / 'native-include-bindings-end.json', {'schema': 1, 'bindings': endings})
        recorder.save(out / 'generated-end.json', recorder.generated_snapshot())
        recorded = {record['label']: record for record in recorder.commands}
        producer = {'schema': 1, 'system': platform.system(), 'root': str(ROOT), 'out': str(out),
                    'tools': {name: recorded[label]['argv'][0] for name, label in [
                        ('git', 'git-head'), ('rustup', 'rustc-path'), ('rustc', 'rust-version'),
                        ('compiler', 'compile-000'), ('archiver', 'archive-build')]}}
        producer['tools'].update(python=python, rust_linker=rust_linker, native_linker=native_linker)
        recorder.save(out / 'producer.json', producer)
        schedule = command_schedule(producer, [p.relative_to(ROOT).as_posix() for p in sources], libs, dynamics=dynamics)
        require([(r['label'], tuple(r['argv']), r['cwd']) for r in recorder.commands] ==
                [(r.label, r.argv, r.cwd) for r in schedule], 'exact complete diagnostic command schedule')
        for expected, record in zip(schedule, recorder.commands):
            require(set(record['outputs']) == set(expected.outputs), 'exact produced artifact roles ' + expected.label)
            require(record['stdin_sha256'] == (digest(inputs.encode()) if expected.corpus else None),
                    'exact corpus stdin role ' + expected.label)
        status.update(status='DIAGNOSTIC_EQUAL_UNADMITTED', cases=len(cases), checkpoints=len(inputs.splitlines()),
                      commands=len(recorder.commands), mutant_definitions=len(mutants(dynamics)), compiled_controls=len(controls))
        recorder.save(out / 'report.json', status)
    except Exception as error:
        status.update(error=str(error))
        if status['status'] == 'UNRUN':
            status['status'] = 'DIAGNOSTIC_FAILED'
        recorder.save(out / 'report.json', status)
        raise
    finally:
        recorder.close()
        recorder.manifest()
    authority = recorder.authority()
    expected = {'authority':authority,'expected_head':head,'canonical_sources':original_sources,'inputs':inputs,'cases':cases,
                'expected_host':{(platform.system(),platform.machine().lower())}, 'dynamics': dynamics}
    status.update(status='CONTROLLED_PASS',pending=[])
    report_bytes = encode_json(status)
    candidate = candidate_capture(Capture.open(out, expected=authority),{'report.json':report_bytes})
    expected['authority'] = candidate.authority
    peers = actual_peer_controls(candidate,**expected)
    candidate = candidate_capture(candidate,{'actual-capture-controls.json':encode_json(peers)})
    expected['authority'] = candidate.authority
    admit_capture(candidate,**expected)
    for name in ['actual-capture-controls.json','report.json','artifact-manifest.json']:
        temporary = out / (name+'.pending')
        temporary.write_bytes(candidate[name])
        temporary.replace(out/name)
    admit_capture(out,**expected)
    require(authority_path != out and out not in authority_path.parents, 'detached authority outside capture')
    receipt = candidate.authority.receipt()
    authority_path.write_bytes(receipt)
    with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as stream:
        stream.write(f'authority_size={len(receipt)}\nauthority_sha256={digest(receipt)}\n')


def replay(directory, out, authority, dynamics=False):
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'compiler and actual replay are hosted-only')
    require((platform.system(), platform.machine().lower()) in {
        ('Windows', 'amd64'), ('Windows', 'x86_64'), ('Darwin', 'arm64'),
        ('Linux', 'x86_64'), ('Linux', 'aarch64'), ('Linux', 'arm64')}, 'supported actual replay host')
    require(not out.exists(), 'fresh unique replay output directory')
    require(ROOT != out and ROOT not in out.parents and out not in ROOT.parents, 'disjoint source and replay roots')
    out.mkdir(parents=True)
    recorder = Recorder(out, snapshot)
    inputs, cases = dynamics_corpus() if dynamics else corpus()
    recorder.write(out / 'inputs.txt', inputs.encode())
    recorder.save(out / 'cases.json', cases)
    status = {'schema': 1, 'status': 'REPLAY_UNADMITTED', 'pending': PENDING, 'base': DYNAMICS_BASE if dynamics else BASE, 'base_tree': DYNAMICS_BASE_TREE if dynamics else BASE_TREE,
              'host': {'system': platform.system(), 'machine': platform.machine()}}
    recorder.save(out / 'report.json', status)
    try:
        for path in source_paths():
            dst = out / 'source' / path.relative_to(ROOT)
            dst.parent.mkdir(parents=True, exist_ok=True)
            recorder.write(dst, path.read_bytes())
        head = recorder.run('git-head', ['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
        require(not recorder.run('git-status', ['git', 'status', '--porcelain=v1'], cwd=ROOT).strip(), 'clean replay source')
        producer = admit_capture(directory, authority=authority, expected_head=head,
                                 canonical_sources={name: recorder.read(out / 'source' / name) for name in recorder.sources},
                                 inputs=inputs, cases=cases,
                                 expected_host={('Windows', 'amd64'), ('Windows', 'x86_64')}, dynamics=dynamics)
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
        if dynamics:
            rargs += ['--cfg', 'mmd_dynamics']
        suffix = '.exe' if os.name == 'nt' else ''
        shadow = out / 'generated'
        copy_sources(shadow)
        originals = {path: (shadow / path).read_bytes() for path in observation_paths(dynamics)}
        edits = instrument(shadow, HERE, dynamics)
        inverse(shadow, edits, originals)
        recorder.save(out / 'observation-edits.json', edits)
        recorder.generated_roots = [shadow]
        recorder.save(out / 'generated-start.json', recorder.generated_snapshot())
        entry = shadow / 'tools/bullet-rust-mmd-collision-check/runner.rs'
        executable = out / ('rust-mmd' + suffix)
        recorder.run('rust-observed-build', [*rargs, '--cfg', 'test', entry, '-o', executable], cwd=ROOT / 'rust',
                     inputs=[entry, out / 'libmds_crtmath.rlib'], outputs=[executable])
        raw = recorder.run('rust-observed-run', [executable], cwd=ROOT / 'rust', data=inputs.encode())
        actual = frames(raw, inputs, dynamics=dynamics)
        validate_lifetimes(actual)
        require(actual == frames(producer.observed_trace, inputs, dynamics=dynamics), 'every admitted Windows checkpoint and raw word replayed')
        controls = compiled_controls(recorder, out, shadow, rargs, suffix, inputs, actual, dynamics)
        inverse(shadow, edits, originals)
        recorder.save(out / 'generated-end.json', recorder.generated_snapshot())
        status.update(cases=len(cases), checkpoints=len(inputs.splitlines()), commands=len(recorder.commands),
                      compiled_controls=len(controls))
        recorded = {record['label']:record for record in recorder.commands}
        recorder.save(out / 'replay-producer.json', {'schema':1,'system':platform.system(),'root':str(ROOT),'out':str(out),
             'tools':{'git':recorded['git-head']['argv'][0],'rustup':recorded['rustc-path']['argv'][0],
                      'rustc':recorded['rust-version']['argv'][0],'rust_linker':rust_linker}})
        recorder.save(out / 'report.json', status)
    except Exception as error:
        status.update(error=str(error))
        recorder.save(out / 'report.json', status)
        raise
    finally:
        recorder.close()
        recorder.manifest()
    current_sources = {name: recorder.read(out / 'source' / name) for name in recorder.sources}
    replay_authority = recorder.authority()
    candidate = Capture.open(out, expected=replay_authority)
    _admit_replay(candidate,producer,authority=replay_authority,expected_head=head,
                  canonical_sources=current_sources,require_pass=False,dynamics=dynamics)
    status.update(status='CONTROLLED_PASS',pending=[])
    candidate = candidate_capture(candidate, {'report.json':encode_json(status)})
    admit_replay(candidate,producer,authority=candidate.authority,expected_head=head,canonical_sources=current_sources,dynamics=dynamics)
    for name in ['report.json','artifact-manifest.json']:
        temporary = out / (name+'.pending')
        temporary.write_bytes(candidate[name])
        temporary.replace(out/name)
    admit_replay(out,producer,authority=candidate.authority,expected_head=head,canonical_sources=current_sources,dynamics=dynamics)



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--describe', action='store_true')
    parser.add_argument('--dynamics', action='store_true')
    parser.add_argument('--out-dir', type=Path)
    parser.add_argument('--replay-dir', type=Path)
    parser.add_argument('--authority', type=Path)
    parser.add_argument('--authority-size', type=int)
    parser.add_argument('--authority-sha256')
    args = parser.parse_args()
    if args.describe:
        import json
        inputs, cases = dynamics_corpus() if args.dynamics else corpus()
        print(json.dumps({'status': 'SOURCE_ONLY_UNRUN', 'cases': len(cases), 'checkpoints': len(inputs.splitlines()),
                          'mutant_definitions': len(mutants(args.dynamics)), 'pending': PENDING}, sort_keys=True))
        return
    require(args.out_dir is not None and args.authority is not None, '--out-dir and --authority required')
    if args.replay_dir is not None:
        require(args.authority_size is not None and args.authority_sha256 is not None, 'pinned remote authority size/SHA required')
        authority = read_authority(args.authority, size=args.authority_size, sha256=args.authority_sha256)
        replay(args.replay_dir.resolve(), args.out_dir.resolve(), authority, args.dynamics)
    else:
        require(args.authority_size is None and args.authority_sha256 is None, 'producer emits its own authority')
        capture(args.out_dir.resolve(), args.authority.resolve(), args.dynamics)


if __name__ == '__main__':
    main()
