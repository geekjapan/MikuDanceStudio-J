#!/usr/bin/env python3
"""Hosted friction visibility diagnostic; never an admission or parity seal."""
import argparse
import copy
import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORKFLOW = '.github/workflows/mmd-friction-definedness.yml'
BRANCH = 'w6-mmd-friction-definedness'
ROLES = ('ordinary', 'ascending', 'descending', 'alternating')
VARIANTS = ('native-original', 'native-observed', 'rust-original', 'rust-observed')
MAX_TRACE = 64 * 1024 * 1024


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def workflow_identity(env, head, workflow):
    """Closed text identity joined to the actual checked-out workflow bytes."""
    require(env.get('GITHUB_ACTIONS') == 'true', 'hosted-only diagnostic')
    require(re.fullmatch('[0-9a-f]{40}', head) is not None, 'canonical checked-out HEAD')
    require(env.get('GITHUB_SHA') == head, 'workflow exact checked-out HEAD')
    require(env.get('GITHUB_EVENT_NAME') == 'push', 'experimental push only')
    require(env.get('GITHUB_REF') == 'refs/heads/' + BRANCH, 'experimental branch only')
    require(env.get('GITHUB_JOB') == 'diagnostic', 'single diagnostic job identity')
    repository = env.get('GITHUB_REPOSITORY', '')
    require(re.fullmatch('[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) is not None,
            'canonical workflow repository')
    require(env.get('GITHUB_WORKFLOW_REF') == repository + '/' + WORKFLOW + '@refs/heads/' + BRANCH,
            'actual workflow source identity')
    require(env.get('GITHUB_WORKFLOW_SHA') == head, 'same-HEAD workflow source')
    values = []
    for name in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
        value = env.get(name, '')
        require(re.fullmatch('[1-9][0-9]{0,19}', value) is not None, 'canonical workflow run/attempt')
        values.append(value)
    require(type(workflow) is bytes and 0 < len(workflow) <= 65536, 'bounded workflow bytes')
    return ('MMD_FRICTION_WORKFLOW 1\n'
            f'head {head}\nrepository {repository}\nbranch {BRANCH}\n'
            f'run {values[0]}\nattempt {values[1]}\njob diagnostic\n'
            f'source {len(workflow)} {sha(workflow)} {WORKFLOW}\n').encode('ascii')


def validate_corpus(inputs, cases):
    require(type(inputs) is str and inputs.isascii() and inputs.endswith('\n')
            and '\r' not in inputs and '\0' not in inputs, 'complete ASCII LF corpus')
    rows = inputs.splitlines()
    require(type(cases) is list and len(cases) == 30, 'actual frozen 30-case corpus')
    cursor, names = 0, set()
    for case in cases:
        require(type(case) is dict and set(case) == {'name', 'family', 'start', 'end', 'operations'},
                'complete case definition')
        start, end, name = case['start'], case['end'], case['name']
        require(type(start) is int and type(end) is int and start == cursor and start < end < len(rows),
                'contiguous complete case boundaries')
        require(type(name) is str and name not in names and rows[start].split()[:2] == ['H', name]
                and rows[end] == 'X', 'actual case header and terminal command')
        names.add(name)
        require(type(case['operations']) is list and len(case['operations']) == end - start + 1,
                'every case operation accounted')
        for at, operation in enumerate(case['operations'], start):
            require(type(operation) is dict and set(operation) == {'row', 'scope'}
                    and type(operation['row']) is int and operation['row'] == at
                    and operation['scope'] in ('genuine-mmd-operations', 'fixture-injection'),
                    'ordered case operation and source scope')
        require(all(row.split()[0] not in ('H', 'X') for row in rows[start + 1:end]), 'no nested or dropped case')
        cursor = end + 1
    require(cursor == len(rows) and len(rows) <= 2147483647, 'whole corpus case coverage')
    return inputs.encode('ascii')


class Schedule:
    """Exact ordered planned commands retained before execution as closed text."""
    def __init__(self, recorder, out):
        self.recorder, self.out = recorder, out
        self.planned = []

    def run(self, label, argv, *, cwd, data=None, inputs=(), outputs=()):
        argv = [self.recorder.bind_tool(argv[0])['path'], *map(str, argv[1:])]
        inputs, outputs = tuple(map(Path, inputs)), tuple(map(Path, outputs))
        row = (label, tuple(argv), str(cwd), None if data is None else sha(data),
               tuple(map(str, inputs)), tuple(map(str, outputs)))
        self.planned.append(row)
        lines = ['MMD_FRICTION_SCHEDULE 1\n']
        for ordinal, (name, args, directory, stdin, ins, outs) in enumerate(self.planned, 1):
            fields = [str(ordinal), name, directory, stdin or '-', str(len(args)), *args,
                      str(len(ins)), *ins, str(len(outs)), *outs]
            lines.append('S ' + ' '.join(value.encode().hex() for value in fields) + '\n')
        self.recorder.write(self.out / 'schedule.txt', ''.join(lines).encode('ascii'))
        return self.recorder.run(label, argv, cwd=cwd, data=data, inputs=inputs, outputs=outputs)

    def check(self):
        require(len(self.planned) == len(self.recorder.commands), 'complete command schedule length')
        for expected, actual in zip(self.planned, self.recorder.commands):
            label, argv, cwd, stdin, inputs, outputs = expected
            require((actual['label'], tuple(actual['argv']), actual['cwd'], actual['stdin_sha256'])
                    == (label, argv, cwd, stdin), 'exact command/source/stdin schedule ' + label)
            require(set(actual['inputs_before']) == set(inputs) and set(actual['outputs']) == set(outputs),
                    'complete command input/output schedule ' + label)
            require(type(actual['pid']) is int and actual['pid'] > 0 and actual['waited'] is True
                    and actual['streams_closed'] is True and type(actual['returncode']) is int
                    and actual['returncode'] == 0, 'normally exited closed command ' + label)


def _resequence(rows):
    sequence = 0
    output = []
    for source in rows:
        row = list(source)
        if row[0].startswith('F') and row[0] not in ('FH', 'FZ'):
            sequence += 1
            row[2] = str(sequence)
        elif row[0] == 'FZ':
            row[1] = str(sequence)
        output.append(' '.join(row))
    return ('\n'.join(output) + '\n').encode('ascii')


def runtime_controls(raw, captures, inputs, role):
    """Safe text/defined-value peers, each with a precise rejection witness."""
    from friction_trace import parse, compare_defined, compare_physical
    from friction_compare import common_fields
    lines = ['MMD_FRICTION_RUNTIME_CONTROLS 1\n']
    native, rust_original, rust_observed = captures[1:]
    tokens = [line.split() for line in raw.decode('ascii').splitlines()]
    selected = {}
    for index, row in enumerate(tokens):
        if row[0].startswith('F') and row[0] not in ('FH', 'FZ'):
            selected.setdefault((row[0], row[3]), index)
    require(selected, 'actual observed control sites')
    for (tag, site), index in selected.items():
        for kind in ('missing', 'duplicate'):
            peer = tokens[:index] + (tokens[index:index + 1] if kind == 'duplicate' else []) + tokens[index + (kind == 'missing'):]
            try:
                parse(_resequence(peer), inputs, variant='native-observed', role=role, corpus_sha=sha(inputs.encode('ascii')))
            except ValueError as error:
                lines.append(f'S {kind} {tag} {site} {tokens[index][1]} {str(error).encode().hex()}\n')
            else:
                raise ValueError(f'actual structural peer accepted: {kind} {tag} {site}')
    for tag in ('S', 'J', 'R', 'K', 'Y', 'V'):
        index = next((i for i, row in enumerate(rust_original.base) if row[0] == tag), None)
        require(index is not None, 'actual initialized Rust common control row ' + tag)
        row = rust_original.base[index]
        for field_index in range(2, len(row)):
            changed = list(row)
            changed[field_index] = '1' if row[field_index] == '0' else '0'
            peer = copy.copy(rust_original)
            peer.base = list(rust_original.base)
            peer.base[index] = tuple(changed)
            try:
                common_fields(peer, rust_observed)
            except ValueError as error:
                lines.append(f'C {tag} {row[1]} {field_index} {str(error).encode().hex()}\n')
            else:
                raise ValueError('actual initialized Rust common field peer accepted: ' + tag)
    numerical = 0
    for key, (state, words) in native.directions.items():
        if state != 'D':
            continue
        for index in range(3):
            changed_words = list(words)
            changed_words[index] = f'{int(changed_words[index], 16) ^ 1:08x}'
            peer = copy.copy(native)
            peer.directions = dict(native.directions)
            peer.directions[key] = ('D', tuple(changed_words))
            try:
                compare_defined(peer, rust_observed)
            except ValueError as error:
                require('DEFINED numerical difference' in str(error), 'exact defined-value witness classification')
                lines.append('N ' + ' '.join(map(str, (*key, index))) + '\n')
                numerical += 1
            else:
                raise ValueError('defined-word peer accepted')
    require(numerical > 0, 'nonempty actual defined numerical controls')
    unwritten = next((key for key, (state, _) in native.directions.items() if state == 'U'), None)
    require(unwritten is not None and unwritten in rust_original.physical, 'actual native U / original Rust physical witness')
    peer = copy.copy(rust_original)
    peer.physical = dict(rust_original.physical)
    words = list(peer.physical[unwritten])
    words[0] = f'{int(words[0], 16) ^ 1:08x}'
    peer.physical[unwritten] = tuple(words)
    try:
        compare_physical(peer, rust_observed)
    except ValueError as error:
        require('physical numerical difference' in str(error), 'exact original Rust physical witness classification')
        lines.append('P ' + ' '.join(map(str, unwritten)) + '\n')
    else:
        raise ValueError('original Rust physical peer accepted on native U')
    return ''.join(lines).encode('ascii')


def capture(out, authority_path):
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'full helpers and compilers are GHA-only')
    require((platform.system(), platform.machine()) == ('Linux', 'x86_64'), 'frozen Linux x64 host')
    # Heavy project imports are confined to the hosted entry point.
    import check as legacy
    import evidence as ev
    import hooks
    import friction_native as native
    import friction_rust as rust
    from cases import dynamics_corpus
    from friction_trace import parse
    from friction_compare import four_variants

    require(not out.exists(), 'fresh diagnostic output')
    require(out != ROOT and ROOT not in out.parents and out not in ROOT.parents, 'disjoint diagnostic root')
    require(authority_path != out and out not in authority_path.parents and not authority_path.exists(),
            'fresh detached authority outside diagnostic root')
    require(all(os.environ.get(name) is None for name in ('BULLET_ALLOC_LOG', 'OPENMMD_DUMP_SPRING')),
            'no native environment log injection')
    require(all(not os.environ.get(name) for name in ('CL', '_CL_', 'CFLAGS', 'CXXFLAGS', 'CPPFLAGS',
                                                    'LDFLAGS', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS')),
            'no ambient compiler flag injection')
    source_paths = sorted(set(legacy.source_paths()) | {ROOT / WORKFLOW})
    require(all(path.is_file() and not path.is_symlink() for path in source_paths), 'regular diagnostic source closure')
    def snapshot():
        return {p.relative_to(ROOT).as_posix(): sha(p.read_bytes()) for p in source_paths}
    out.mkdir(parents=True)
    recorder = ev.Recorder(out, snapshot)
    schedule = Schedule(recorder, out)
    cwd = ROOT / 'rust'
    outcome = 'INCOMPLETE'
    try:
        for path in source_paths:
            dst = out / 'source' / path.relative_to(ROOT)
            dst.parent.mkdir(parents=True, exist_ok=True)
            recorder.write(dst, path.read_bytes())
        head = schedule.run('git-head', ['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
        require(not schedule.run('git-status', ['git', 'status', '--porcelain=v1'], cwd=ROOT).strip(),
                'clean diagnostic source')
        tree = schedule.run('git-tree', ['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT).decode().strip()
        require(re.fullmatch('[0-9a-f]{40}', tree) is not None, 'canonical source tree')
        workflow = schedule.run('git-workflow', ['git', 'show', 'HEAD:' + WORKFLOW], cwd=ROOT)
        require(workflow == recorder.read(out / 'source' / WORKFLOW), 'actual tracked workflow bytes')
        recorder.write(out / 'workflow.txt', workflow_identity(os.environ, head, workflow))
        inputs, cases = dynamics_corpus()
        corpus = validate_corpus(inputs, cases)
        recorder.write(out / 'inputs.txt', corpus)
        recorder.save(out / 'cases.json', cases)
        command_count = len(inputs.splitlines())
        corpus_sha = sha(corpus)
        roots, custody = {}, {}
        for variant in VARIANTS:
            root = out / 'generated' / variant
            legacy.copy_sources(root)
            shutil.copyfile(ROOT / WORKFLOW, root / WORKFLOW)
            roots[variant] = root
            if variant.startswith('native-'):
                edits, originals, census = native.generate(root, observed=variant.endswith('-observed'), corpus=corpus)
                census_raw = ''.join('C ' + str(line) + ' ' + path + ' ' + text.encode().hex() + '\n'
                                     for path, line, text in census).encode('ascii')
                recorder.write(out / (variant + '-census.txt'), census_raw)
            else:
                recorder.write(out / (variant + '-source-binding.txt'),
                               (rust.preflight(root) + rust.source_binding()).encode('utf-8'))
                paths = set(hooks.observation_paths(True)) | set(rust.SOURCE_PATHS) | {rust.RUNNER}
                originals = {name: (root / name).read_bytes() for name in paths}
                edits = (hooks.instrument(root, HERE, dynamics=True) + rust.instrument(root, HERE)
                         if variant.endswith('-observed') else rust.original_fixtures(root, HERE))
                edits += rust.consumer(root, variant.endswith('-observed'))
            changed = {edit['path'] for edit in edits}
            originals = {name: raw for name, raw in originals.items() if name in changed}
            hooks.inverse(root, edits, originals)
            recorder.save(out / (variant + '-edits.json'), edits)
            custody[variant] = (edits, originals)
        recorder.generated_roots = list(roots.values())
        compiler = recorder.bind_tool(os.environ.get('CXX', 'clang++'))['path']
        linker = schedule.run('native-linker-path', [compiler, '-print-prog-name=ld'], cwd=cwd).decode().strip()
        linker = recorder.bind_tool(linker)['path']
        archiver = recorder.bind_tool('ar')['path']
        schedule.run('native-compiler-version', [compiler, '--version'], cwd=cwd)
        schedule.run('native-linker-version', [linker, '--version'], cwd=cwd)
        schedule.run('archiver-version', [archiver, '--version'], cwd=cwd)
        rustc = schedule.run('rustc-path', ['rustup', 'which', '--toolchain', '1.95.0', 'rustc'], cwd=cwd).decode().strip()
        version = schedule.run('rust-version', [rustc, '-Vv'], cwd=cwd)
        require(b'release: 1.95.0\n' in version, 'actual pinned Rust compiler')
        rust_linker = recorder.bind_tool('cc')['path']
        schedule.run('rust-linker-version', [rust_linker, '--version'], cwd=cwd)
        rust_args = [rustc, '--edition=2021', '-O', '-C', 'linker=' + rust_linker]
        from test_friction_rust import RUNTIME_CONTROL
        control_root = out / 'rust-ledger-control'
        control_root.mkdir()
        control_source, control_runtime = control_root / 'main.rs', control_root / 'friction_rust.rs'
        recorder.write(control_source, RUNTIME_CONTROL.encode('utf-8'))
        recorder.write(control_runtime, (HERE / 'friction_rust.rs').read_bytes())
        recorder.generated_roots.append(control_root)
        recorder.save(out / 'generated-start.json', recorder.generated_snapshot())
        control_exe = out / 'rust-ledger-control-probe'
        schedule.run('rust-ledger-control-build', [*rust_args, control_source, '-o', control_exe], cwd=cwd,
                     inputs=[control_source, control_runtime], outputs=[control_exe])
        control_rows = [line.split() for line in schedule.run('rust-ledger-control-run', [control_exe], cwd=cwd,
                                                             inputs=[control_exe]).decode('ascii').splitlines()]
        require(control_rows[0] == ['FH', '3', 'rust-observed', 'ordinary', '0' * 64, '3'], 'control exact header')
        require([row[3] for row in control_rows if row[0] == 'FW'] == ['PLANE_BOTH', 'VELOCITY_DIR1', 'FIXTURE_W'],
                'control actual branch writers and retention')
        require(len([row for row in control_rows if row[0] == 'FP']) == 4
                and [row[8] for row in control_rows if row[0] == 'FD'] == ['3', '3', '0', '0'],
                'control physical words and replacement reset')
        require(control_rows[-1][0] == 'FZ' and int(control_rows[-1][1]) == len(control_rows) - 2
                and control_rows[-1][-1] == '6' and any(row[0] == 'FV' for row in control_rows),
                'control move and complete generation closure')
        crt_source = ROOT / 'rust/crates/mds-crtmath/src/lib.rs'
        crt, rlib = out / 'libmds_crtmath.a', out / 'libmds_crtmath.rlib'
        schedule.run('crt-build', [*rust_args, '--crate-name', 'mds_crtmath', '--crate-type', 'rlib,staticlib',
                                  crt_source, '--out-dir', out], cwd=cwd, inputs=[crt_source], outputs=[crt, rlib])
        includes, aliases, objects, archives, executables = {}, {}, {}, {}, {}
        def acquire(occurrences):
            bindings = []
            for occurrence in occurrences:
                spelling = Path(occurrence['raw'])
                target = (spelling if spelling.is_absolute() else cwd / spelling).resolve(strict=True)
                require(target.is_file(), 'regular measured native include')
                raw = target.read_bytes()
                retained = out / 'include-bytes' / sha(raw)
                retained.parent.mkdir(exist_ok=True)
                if not retained.exists():
                    recorder.write(retained, raw)
                bindings.append({**occurrence, 'target': str(target), 'sha256': sha(raw)})
            return bindings
        def compile_object(source, obj, label, root, extra):
            flags = legacy.native_flags(root, dynamics=True)
            discovery = obj.with_name('discovery-' + obj.name)
            raw = schedule.run(label + '-discovery', [compiler, *flags, *extra, '-c', source, '-o', discovery],
                               cwd=cwd, inputs=[source], outputs=[discovery])
            occurrences = ev.include_occurrences(raw, recorder.read(out / (label + '-discovery.stderr')), 'Linux')
            pre = acquire(occurrences)
            pre_manifest, pre_aliases = ev.include_projection(pre, occurrences, 'Linux')
            dependencies = sorted({Path(binding['target']) for binding in pre})
            raw = schedule.run(label, [compiler, *flags, *extra, '-c', source, '-o', obj], cwd=cwd,
                               inputs=[source, *dependencies], outputs=[obj])
            occurrences = ev.include_occurrences(raw, recorder.read(out / (label + '.stderr')), 'Linux')
            post = acquire(occurrences)
            manifest, post_aliases = ev.include_projection(post, occurrences, 'Linux')
            require((pre_manifest, pre_aliases) == (manifest, post_aliases), 'measured include discovery/use equality')
            recorder.save(out / (label + '-include-bindings.json'),
                          {'schema': 1, 'label': label, 'cwd': str(cwd), 'pre': pre, 'post': post})
            recorder.save(out / (label + '-includes.json'), manifest)
            for spelling, binding in post_aliases.items():
                require(spelling not in aliases or aliases[spelling] == binding, 'fixed include alias across builds')
                aliases[spelling] = binding
            includes[label] = dependencies
            return dependencies
        for variant in VARIANTS[:2]:
            root = roots[variant]
            objdir = out / ('objects-' + variant)
            objdir.mkdir()
            observed = variant.endswith('-observed')
            objs, includers = native.rebuild_all(root, objdir, compile_object=compile_object, observed=observed)
            objects[variant] = objs
            recorder.write(out / (variant + '-includers.txt'),
                           ''.join('I ' + header + ' ' + source + '\n' for header in sorted(includers)
                                   for source in includers[header]).encode('ascii'))
            archive = out / ('lib-' + variant + '.a')
            archives[variant] = archive
            schedule.run(variant + '-archive', [archiver, 'rcs', archive, *objs], cwd=cwd, inputs=objs, outputs=[archive])
            listing = schedule.run(variant + '-archive-list', [archiver, 't', archive], cwd=cwd, inputs=[archive]).decode().splitlines()
            sources = native.native_sources(root)
            require(len(sources) == len(objs), 'complete archive source/object count')
            bindings = [{'source': source.relative_to(root).as_posix(), 'source_sha256': sha(source.read_bytes()),
                         'object': obj.name, 'object_sha256': sha(recorder.read(obj))} for source, obj in zip(sources, objs)]
            parsed = ev.verify_archive(recorder.read(archive), listing, 'Linux', bindings,
                                       {obj.name: recorder.read(obj) for obj in objs},
                                       {source.relative_to(root).as_posix(): source.read_bytes() for source in sources})
            require(len(parsed.payloads) == len(objs), 'complete actual archive payload closure')
            recorder.save(out / (variant + '-archive-bindings.json'), bindings)
        for variant in VARIANTS[:2]:
            root, archive = roots[variant], archives[variant]
            source = root / 'tools/bullet-rust-mmd-collision-check/oracle.cpp'
            obj, exe, linkmap = (out / (variant + suffix) for suffix in ('.o', '', '.map'))
            extra = ['-include', root / native.HEADER, '-include', root / 'tools/bullet-rust-mmd-collision-check/observer.h',
                     '-DDW_OBSERVED=1'] if variant.endswith('-observed') else []
            compile_object(source, obj, variant + '-consumer', root, extra)
            schedule.run(variant + '-link', [compiler, obj, archive, crt, '-ldl', '-lpthread', '-lm',
                                            '-fuse-ld=' + linker, '-Wl,-Map,' + str(linkmap), '-o', exe],
                         cwd=cwd, inputs=[obj, archive, crt], outputs=[exe, linkmap])
            selected = native.selected_link_objects(recorder.read(linkmap), objects[variant], archive=archive,
                                                   selected_members=ev.selected_members,
                                                   forbidden_archives=[path for name, path in archives.items() if name != variant])
            recorder.save(out / (variant + '-link-selection.json'), sorted(selected))
            executables[variant] = exe
        for variant in VARIANTS[2:]:
            entry = roots[variant] / 'tools/bullet-rust-mmd-collision-check/runner.rs'
            exe = out / variant
            schedule.run(variant + '-build', [*rust_args, '--extern', 'mds_crtmath=' + str(rlib),
                                             '--cfg', 'test', '--cfg', 'mmd_dynamics', entry, '-o', exe],
                         cwd=cwd, inputs=[entry, rlib], outputs=[exe])
            executables[variant] = exe
        runtime_env = recorder.bind_tool('env')['path']
        captures, observed_streams = {}, {}
        for role in ROLES:
            role_rows = []
            observed_raw = None
            for variant in VARIANTS:
                label = variant + '-run-' + role
                raw = schedule.run(label, [executables[variant], role] if variant.startswith('native-')
                                   else [runtime_env, 'MMD_FRICTION_ROLE=' + role,
                                         'MMD_FRICTION_CORPUS_SHA=' + corpus_sha,
                                         'MMD_FRICTION_COMMANDS=' + str(command_count), executables[variant]],
                                   cwd=cwd, data=corpus, inputs=[executables[variant]])
                require(len(raw) <= MAX_TRACE, 'combined base/sidecar output cap')
                rows = parse(raw, inputs, variant=variant, role=role, corpus_sha=corpus_sha)
                if variant == 'native-observed':
                    observed_raw = raw
                role_rows.append(rows)
                counts = ' '.join(f'{key} {value}' for key, value in sorted(rows.maxima.items()))
                recorder.write(out / (label + '-capacity.txt'),
                               (f'MMD_FRICTION_CAPACITY 1\nvariant {variant}\nrole {role}\n'
                                f'bytes {len(raw)}\nclosed {rows.closed}\nmaxima {counts}\n').encode('ascii'))
            captures[role], observed_streams[role] = role_rows, observed_raw
        for role in ROLES:
            four_variants(*captures[role])
            recorder.write(out / ('runtime-controls-' + role + '.txt'),
                           runtime_controls(observed_streams[role], captures[role], inputs, role))
        # Hosted suites use initialized metadata; no write is removed behind a hook.
        suites = ('test_friction_parser.py', 'test_friction_stream.py', 'test_friction_comparison.py',
                  'test_friction_native.py', 'test_friction_check.py')
        python = recorder.bind_tool(sys.executable)['path']
        for suite in suites:
            schedule.run('controls-' + suite.removeprefix('test_').removesuffix('.py').replace('_', '-'),
                         [python, '-B', HERE / suite, '-v'], cwd=ROOT, inputs=[HERE / suite])
        schedule.run('controls-friction-rust-generation',
                     [python, '-B', '-m', 'unittest', '-v', 'test_friction_rust.Local',
                      'test_friction_rust.Hosted.test_real_generation_and_complete_inverse'], cwd=HERE,
                     inputs=[HERE / 'test_friction_rust.py'])
        for variant, (edits, originals) in custody.items():
            hooks.inverse(roots[variant], edits, originals)
        endings = []
        for spelling, binding in sorted(aliases.items()):
            acquired = acquire([{'stream': 'stderr', 'ordinal': 0, 'raw': spelling}])[0]
            require((acquired['target'], acquired['sha256']) == binding, 'end-preserved effective include alias')
            endings.append({'cwd': str(cwd), 'raw': spelling, 'target': acquired['target'], 'sha256': acquired['sha256']})
        recorder.save(out / 'native-include-bindings-end.json', {'schema': 1, 'bindings': endings})
        recorder.save(out / 'generated-end.json', recorder.generated_snapshot())
        require(recorder.read(out / 'generated-start.json') == recorder.read(out / 'generated-end.json'),
                'every generated source unchanged throughout execution')
        schedule.check()
        outcome = 'COMPARED'
    except Exception as error:
        recorder.write(out / 'failure.txt', (type(error).__name__ + ' ' + str(error) + '\n').encode('utf-8'))
        raise
    finally:
        recorder.write(out / 'result.txt',
                       (f'MMD_FRICTION_DIAGNOSTIC 1\nresult DIAGNOSTIC_ONLY\noutcome {outcome}\n'
                        'original_conditional_dir2_noninterference OPEN\nfinal_parity BLOCK\n'
                        'admission BLOCK\nseal BLOCK\n').encode('ascii'))
        try:
            recorder.close()
        finally:
            recorder.manifest()
    # Byte/command closure only. Never call normal admission/replay.
    authority = recorder.authority()
    receipt = authority.receipt()
    authority_path.write_bytes(receipt)
    expected = ev.read_authority(authority_path, size=len(receipt), sha256=sha(receipt))
    packet = ev.Capture.open(out, expected=expected)
    records = ev.command_records(lambda name: packet[name], expected)
    require(len(records) == len(schedule.planned), 'externally anchored complete command inventory')
    for record in records:
        ev.closed_command(record, expected.members)
    with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='ascii') as stream:
        stream.write(f'authority_size={len(receipt)}\nauthority_sha256={sha(receipt)}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', required=True, type=Path)
    parser.add_argument('--authority', required=True, type=Path)
    args = parser.parse_args()
    capture(args.out_dir.resolve(), args.authority.resolve())


if __name__ == '__main__':
    main()
