#!/usr/bin/env python3
"""Capture the real default-owned broadphase, its archive, and strict Rust replays."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

from cases import corpus
from trace import bind_inputs, differences, require, validate

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = '3a15446bb6d5ad372a0e41289a71fa47632e1d59'
MODES = ['ascending', 'descending', 'alternating', 'ordinary']
POLICIES = ['generic-reference', 'mmd-win64-sse']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def source_paths(root=ROOT):
    folders = [root / 'recipes/bullet275/bullet-src/src', root / 'rust/crates/mds-bullet/src/core',
               root / 'rust/crates/mds-bullet/tests', root / 'rust/crates/mds-crtmath/src',
               root / 'tools/bullet-rust-dbvt-check', root / 'tools/bullet-rust-dbvt-broadphase-check']
    paths = {p for folder in folders for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    paths.add(root / '.github/workflows/bullet-dbvt-broadphase.yml')
    return sorted(paths)


def snapshot(root=ROOT):
    return {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in source_paths(root)}


def fixed_inputs():
    inputs, histories = corpus()
    manifest = json.loads((HERE / 'manifest.json').read_text())
    require(manifest == {'schema': 1, 'checkpoints': len(inputs.splitlines()),
                         'sha256': digest(inputs.encode()), 'histories': histories}, 'immutable corpus manifest')
    return inputs, manifest


def expanded_function(text, name, parameters):
    pattern = name + r'\s*\(\s*const\s+btDbvtAabbMm\s*&\s*\w+\s*,\s*const\s+btDbvtAabbMm\s*&\s*\w+'
    if parameters == 3:
        pattern += r'\s*,[^)]+'
    pattern += r'\s*\)\s*\{'
    matches = list(re.finditer(pattern, text))
    require(len(matches) == 1, 'one expanded ' + name)
    start = matches[0].end() - 1
    depth = 1
    end = start + 1
    while depth and end < len(text):
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    require(depth == 0, 'complete expanded body')
    return text[start:end]


def classify(text):
    bodies = {name: expanded_function(text, name, count) for name, count in [('Intersect', 2), ('Select', 3), ('Merge', 3)]}
    if all(token in bodies[name] for name, token in [('Intersect', '_mm_cmplt_ps'), ('Select', '_mm_cmple_ss'), ('Merge', '_mm_min_ps')]):
        policy = 'mmd-win64-sse'
    elif all('_mm_' not in body for body in bodies.values()) and 'Proximity' in bodies['Select']:
        policy = 'generic-reference'
    else:
        raise ValueError('unknown or mixed actual DBVT numeric policy')
    return {'policy': policy, 'bodies': bodies}


def mutate(source, name):
    broadphase = source / 'rust/crates/mds-bullet/src/core/dbvt_broadphase.rs'
    tree = source / 'rust/crates/mds-bullet/src/core/dbvt.rs'
    bp = broadphase.read_text()
    replacements = {
        'query-side': ('for tree in sets {', 'for tree in &sets[1..] {'),
        'filter': ('group,\n            mask,', 'group: -1,\n            mask: -1,'),
        'stage': ('let old = self.proxy(key).requested;', 'if self.proxy(key).requested == requested { return; }\n        let old = self.proxy(key).requested;'),
        'migration': ('self.sets[0].remove(key);\n                self.sets[1].insert(key, self.proxy(key).requested);', 'let expanded = self.sets[0].volume(key);\n                self.sets[0].remove(key);\n                self.sets[1].insert(key, expanded);'),
        'reactivation': ('self.sets[0].insert(key, requested);\n            collide = true;', 'self.sets[0].insert(key, requested);\n            collide = false;'),
        'margin': ('Some(0.05)', 'Some(0.0)'),
        'sign': ('if delta.0[i] < 0.0', 'if delta.0[i] > 0.0'),
        'teleport': ('self.sets[0].update(key, requested);', 'let mut padded = requested; padded.min = padded.min.sub(Vec3([0.05; 3])); self.sets[0].update(key, padded);'),
        'budget': ('self.cache.pairs().len() * 10 / 100', '0'),
        'cursor': ('(self.counters.cid + count) % self.cache.pairs().len()', '0'),
        'release': ('self.cache.remove_proxy(key, &self.states, release);', 'self.cache.remove_proxy(key, &self.states, |_| {});\n        let _ = release;'),
        'live-reset': ('if self.sets.iter().all(|tree| tree.leaf_count() == 0) {', 'if self.sets.iter().any(|tree| tree.leaf_count() > 0) { self.counters.gid = 0; }\n        if self.sets.iter().all(|tree| tree.leaf_count() == 0) {'),
        'cleanup-leaf': ('self.sets[usize::from(self.proxy(key).stage == FIXED)].volume(key)', 'self.proxy(key).requested'),
    }
    path, original = broadphase, bp
    if name == 'containment':
        path, original = tree, tree.read_text()
        old, new = 'if self.node(n).volume.contains(*volume) {', 'if false && self.node(n).volume.contains(*volume) {'
    elif name == 'order':
        path, original = tree, tree.read_text()
        old, new = 'Kind::Branch(c) => stack.extend(c),', 'Kind::Branch(c) => stack.extend(c.into_iter().rev()),'
    else:
        old, new = replacements[name]
    require(original.count(old) == 1, 'one semantic control anchor: ' + name)
    changed = original.replace(old, new)
    path.write_text(changed)
    return {'path': path.relative_to(source).as_posix(), 'old': old, 'new': new,
            'before': digest(original.encode()), 'after': digest(changed.encode())}


CONTROLS = ['query-side', 'filter', 'stage', 'migration', 'reactivation', 'containment',
            'margin', 'sign', 'teleport', 'budget', 'cursor', 'release', 'live-reset', 'cleanup-leaf', 'order']


def witness(name, baseline, changed):
    fields = {'query-side': [3, 7], 'filter': [7], 'stage': [5], 'migration': [6],
              'reactivation': [3, 7], 'containment': [3, 6], 'margin': [6], 'sign': [6],
              'teleport': [6], 'budget': [3, 7], 'cursor': [3], 'release': [9, 10],
              'live-reset': [3], 'cleanup-leaf': [7], 'order': [7]}[name]
    found = []
    for i, (a, b) in enumerate(zip(baseline, changed)):
        if name == 'order' and a[2] != 'c':
            continue
        if any(a[field] != b[field] for field in fields):
            found.append(i)
    require(found, 'directed semantic witness: ' + name)
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--policy', choices=POLICIES, required=True)
    parser.add_argument('--replay-dir', type=Path)
    parser.add_argument('--rust-only', action='store_true', help='focused preparation, never native acceptance')
    args = parser.parse_args()
    require(not (args.replay_dir and args.rust_only), 'choose replay or Rust-only')
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    inputs, manifest = fixed_inputs()
    before = snapshot()
    save(out / 'source-start.json', before)
    canonical = {name: digest((ROOT / name).read_bytes().replace(b'\r\n', b'\n')) for name in before}
    save(out / 'source-canonical.json', canonical)
    (out / 'inputs.txt').write_text(inputs)
    save(out / 'manifest.json', manifest)
    for name in before:
        target = out / 'source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    commands = []
    status = {'schema': 1, 'status': 'FAIL', 'unit_base': BASE, 'policy': args.policy,
              'native': 'UNRUN', 'controlled_order': 'UNRUN', 'ordinary_raw_order': 'UNRUN',
              'public_world': 'HOLD', 'inherited_pr214_final_acceptance': 'ROOT_GATE',
              'inherited_pr214_limit': 'declared capture closure omitted directly consumed mds-crtmath/src/lib.rs'}
    save(out / 'report.json', status)
    def run(command, label, data=None, cwd=None):
        argv = list(map(str, command))
        record = {'label': label, 'argv': argv, 'cwd': str(cwd or ROOT / 'rust'),
                  'stdin_sha256': None if data is None else digest(data)}
        commands.append(record)
        save(out / 'commands.json', commands)
        started = time.monotonic()
        try:
            result = subprocess.run(argv, cwd=cwd or ROOT / 'rust', input=data, capture_output=True, timeout=300,
                                    env={**os.environ, 'VSLANG': '1033'})
        except subprocess.TimeoutExpired as error:
            record.update(timeout=True, returncode=None)
            (out / (label + '.stdout')).write_bytes(error.stdout or b'')
            (out / (label + '.stderr')).write_bytes(error.stderr or b'')
            save(out / 'commands.json', commands)
            raise
        record.update(returncode=result.returncode, timeout=False, seconds=time.monotonic()-started,
                      stdout_sha256=digest(result.stdout), stderr_sha256=digest(result.stderr))
        (out / (label + '.stdout')).write_bytes(result.stdout)
        (out / (label + '.stderr')).write_bytes(result.stderr)
        save(out / 'commands.json', commands)
        if label.startswith('compile-') or label == 'oracle-compile':
            includes = []
            for line in (result.stdout + result.stderr).decode(errors='replace').splitlines():
                match = re.match(r'^Note: including file:\s+(.+)$', line) if os.name == 'nt' else re.match(r'^\.+ (.+)$', line)
                if match:
                    path = Path(match[1]).resolve()
                    require(path.is_file(), 'actual compiler include exists')
                    includes.append({'path': str(path), 'sha256': digest(path.read_bytes())})
            require(includes, 'actual compiler include closure')
            save(out / (label + '-includes.json'), includes)
        require(result.returncode == 0, label + ' must exit normally with zero status')
        return result.stdout
    try:
        status['checkout'] = run(['git', 'rev-parse', 'HEAD'], 'checkout').decode().strip()
        status['changed_paths_from_base'] = run(['git', 'diff', '--name-only', BASE, 'HEAD'], 'unit-paths').decode().splitlines()
        status['host'] = {'system': platform.system(), 'machine': platform.machine(), 'image': os.environ.get('ImageVersion')}
        run(['rustup', 'run', '1.95.0', 'rustc', '--version', '--verbose'], 'rust-version')
        rustc = ['rustup', 'run', '1.95.0', 'rustc', '--edition=2021']
        crt = out / 'libmds_crtmath.rlib'
        run([*rustc, '--crate-name', 'mds_crtmath', '--crate-type', 'rlib', '-C', 'opt-level=2',
             'crates/mds-crtmath/src/lib.rs', '-o', crt], 'crt-build')
        exe_suffix = '.exe' if os.name == 'nt' else ''
        rust = out / ('rust-broadphase' + exe_suffix)
        def build_rust(source, executable, label):
            run([*rustc, '--cfg', 'test', source, '--extern', f'mds_crtmath={crt}', '-o', executable], label)
        build_rust(HERE / 'runner.rs', rust, 'rust-build')
        plain_raw = run([rust, args.policy], 'rust-ordinary', inputs.encode())
        plain = validate(plain_raw, inputs, False)
        focused = out / ('pure-bullet' + exe_suffix)
        run([*rustc, '--test', '-D', 'warnings', '-C', 'opt-level=2', 'crates/mds-bullet/tests/pure_bullet.rs',
             '--extern', f'mds_crtmath={crt}', '-o', focused], 'focused-build')
        run([focused, 'dbvt_broadphase'], 'focused-test')
        if args.rust_only:
            status.update(status='PREPARATION_ONLY', rust_checkpoints=len(plain), focused='PASS')
            return
        capture = args.replay_dir.resolve() if args.replay_dir else out
        if args.replay_dir:
            report = json.loads((capture / 'report.json').read_text())
            require(report['status'] == 'CONTROLLED_PASS' and report['policy'] == 'mmd-win64-sse', 'accepted Windows SSE capture')
            require(report['host']['system'] == 'Windows', 'actual Windows producer required')
            members = json.loads((capture / 'artifact-manifest.json').read_text())
            for name, expected in members.items():
                require(digest((capture / name).read_bytes()) == expected, 'capture integrity: ' + name)
            require((capture / 'inputs.txt').read_bytes() == inputs.encode(), 'exact Windows corpus')
            require(json.loads((capture / 'source-canonical.json').read_text()) == canonical, 'exact Windows producer and verification source closure')
            require(args.policy == 'mmd-win64-sse', 'production Windows replay policy')
            status['native'] = 'WINDOWS_SOURCE_REPLAY'
            status['capture_report_sha256'] = digest((capture / 'report.json').read_bytes())
        else:
            require(platform.machine().lower() in ['amd64', 'x86_64', 'arm64', 'aarch64'], 'supported native architecture')
            require(platform.system() != 'Darwin' or platform.machine().lower() == 'arm64', 'Apple Silicon macOS required')
            compiler = os.environ.get('CXX', 'cl' if os.name == 'nt' else 'clang++')
            compiler_path = shutil.which(compiler)
            require(compiler_path is not None, 'native compiler path')
            status['compiler'] = {'path': str(Path(compiler_path).resolve()), 'sha256': digest(Path(compiler_path).read_bytes())}
            src = ROOT / 'recipes/bullet275/bullet-src/src'
            sources = sorted(p for folder in ['BulletCollision', 'BulletDynamics', 'LinearMath'] for p in (src / folder).rglob('*.cpp'))
            flags = ['/nologo', '/std:c++17', '/O2', '/MD', '/EHsc', '/fp:precise', '/DWIN32', '/DBT_NO_PROFILE=1', '/showIncludes', '/I' + str(src)] if os.name == 'nt' else [
                '-std=c++17', '-O2', '-ffp-contract=off', '-fno-fast-math', '-fdeclspec', '-DBT_NO_PROFILE=1', '-H', '-I', str(src)]
            save(out / 'compiler-flags.json', flags)
            run([compiler, '/?'] if os.name == 'nt' else [compiler, '--version'], 'compiler-version')
            objects = []
            bindings = []
            for index, source in enumerate(sources):
                obj = out / (source.stem + ('.obj' if os.name == 'nt' else '.o'))
                require(obj not in objects, 'unique native member names')
                label = f'compile-{index:03d}-{source.stem}'
                command = [compiler, *flags, '/c', source, '/Fo' + str(obj)] if os.name == 'nt' else [compiler, *flags, '-c', source, '-o', obj]
                raw = run(command, label)
                objects.append(obj)
                bindings.append({'source': source.relative_to(ROOT).as_posix(), 'source_sha256': digest(source.read_bytes()),
                                 'object': obj.name, 'sha256': digest(obj.read_bytes()), 'command': label})
                if source.stem in ['btDbvt', 'btDbvtBroadphase']:
                    pre = run([compiler, *flags, '/E', source] if os.name == 'nt' else [compiler, *flags, '-E', source], 'expanded-' + source.stem)
                    observed = classify(pre.decode(errors='strict'))
                    require(observed['policy'] == args.policy, 'actual archive TU policy')
                    save(out / ('profile-' + source.stem + '.json'), observed)
            library = out / ('BulletBroadphase.lib' if os.name == 'nt' else 'libBulletBroadphase.a')
            run(['lib', '/NOLOGO', '/OUT:' + str(library), *objects] if os.name == 'nt' else ['ar', 'rcs', library, *objects], 'archive-build')
            listing = run(['lib', '/NOLOGO', '/LIST', library] if os.name == 'nt' else ['ar', 't', library], 'archive-members')
            listed = [line.strip() for line in listing.decode(errors='strict').splitlines() if line.strip()]
            actual_members = {}
            for obj in objects:
                selected = [line for line in listed if line.replace('\\', '/').split('/')[-1].lower() == obj.name.lower()]
                require(len(selected) == 1, 'one observed archive member: ' + obj.name)
                actual_members[obj.name] = selected[0]
            save(out / 'actual-archive-members.json', actual_members)
            extracted = out / 'extracted'
            extracted.mkdir()
            if os.name == 'nt':
                for obj in objects:
                    target = extracted / obj.name
                    run(['lib', '/NOLOGO', '/EXTRACT:' + actual_members[obj.name], '/OUT:' + str(target), library], 'member-' + obj.stem)
                    require(target.read_bytes() == obj.read_bytes(), 'actual archive object bytes')
            else:
                run(['ar', 'x', library], 'archive-extract', cwd=extracted)
                for obj in objects:
                    require((extracted / obj.name).read_bytes() == obj.read_bytes(), 'actual archive object bytes')
            save(out / 'archive-bindings.json', {'members': bindings, 'archive_sha256': digest(library.read_bytes())})
            native = out / ('native-broadphase' + exe_suffix)
            link_map = out / 'native.map'
            oracle_obj = out / ('oracle.obj' if os.name == 'nt' else 'oracle.o')
            run([compiler, *flags, '/Bv', '/c', HERE / 'oracle.cpp', '/Fo' + str(oracle_obj)] if os.name == 'nt' else [compiler, *flags, '-c', HERE / 'oracle.cpp', '-o', oracle_obj], 'oracle-compile')
            expanded = run([compiler, *flags, '/E', HERE / 'oracle.cpp'] if os.name == 'nt' else [compiler, *flags, '-E', HERE / 'oracle.cpp'], 'expanded-oracle')
            observed = classify(expanded.decode(errors='strict'))
            require(observed['policy'] == args.policy, 'actual new consumer policy')
            save(out / 'profile-oracle.json', observed)
            if os.name == 'nt':
                link = [compiler, '/nologo', '/MD', '/EHsc', oracle_obj, library, '/Fe' + str(native), '/link', '/MAP:' + str(link_map), '/VERBOSE:LIB']
            elif platform.system() == 'Darwin':
                link = [compiler, oracle_obj, library, '-Wl,-map,' + str(link_map), '-o', native]
            else:
                link = [compiler, oracle_obj, library, '-Wl,-Map,' + str(link_map), '-o', native]
            link_output = run(link, 'oracle-link')
            actual_map = link_map.read_bytes()
            selected_members = {}
            link_lines = (actual_map + link_output).decode(errors='replace').splitlines()
            for member in ['btDbvt', 'btDbvtBroadphase']:
                extension = '.obj' if os.name == 'nt' else '.o'
                matching = [line for line in link_lines if member + extension in line and library.stem in line]
                require(matching, 'actual selected archive member binding: ' + member)
                selected_members[member] = matching
            save(out / 'actual-link-members.json', selected_members)
            actual_profile = json.loads(run([native, 'profile'], 'actual-macros'))
            require(actual_profile['pointer_bits'] == 64, 'actual 64-bit consumer')
            require(actual_profile['prevent_false_update'] == 0 and actual_profile['accurate_sleeping'] == 0,
                    'actual required broadphase compile policy')
            require(actual_profile['margin_bits'] == 1028443341, 'actual native margin 0.05 bits')
            require(actual_profile['bt_use_sse'] == (args.policy == 'mmd-win64-sse'), 'actual consumer SSE macro')
            save(out / 'actual-macros.json', actual_profile)
            status['native'] = 'ACTUAL_UNMODIFIED_ARCHIVE'
            status['native_binary_sha256'] = digest(native.read_bytes())
            for mode in MODES:
                raw = run([native, mode], 'native-' + mode, inputs.encode())
                validate(raw, inputs, True)
        controlled = {}
        for mode in MODES:
            raw = (capture / ('native-' + mode + '.stdout')).read_bytes()
            native_rows = validate(raw, inputs, True)
            if mode == 'ordinary':
                mismatch = differences(native_rows, plain)
                status['ordinary_raw_order'] = 'EQUAL' if not mismatch else 'DIVERGED'
                save(out / 'ordinary-differences.json', {'indices': mismatch, 'native_rows': len(native_rows), 'sorting': False})
                continue
            bound = bind_inputs(inputs, native_rows)
            (out / ('bound-' + mode + '.txt')).write_text(bound)
            rust_raw = run([rust, args.policy], 'rust-' + mode, bound.encode())
            rust_rows = validate(rust_raw, inputs, False)
            mismatch = differences(native_rows, rust_rows)
            save(out / ('difference-' + mode + '.json'), mismatch)
            require(not mismatch, 'strict native ordered checkpoint equality: ' + mode)
            controlled[mode] = len(rust_rows)
        status['controlled_order'] = controlled
        controls = {}
        for name in CONTROLS:
            shadow = out / 'mutants' / name
            for folder in ['rust/crates/mds-bullet/src/core', 'rust/crates/mds-bullet/tests', 'tools/bullet-rust-dbvt-check', 'tools/bullet-rust-dbvt-broadphase-check']:
                shutil.copytree(ROOT / folder, shadow / folder, ignore=shutil.ignore_patterns('__pycache__'))
            change = mutate(shadow, name)
            save(out / ('mutation-' + name + '.json'), change)
            executable = out / ('mutant-' + name + exe_suffix)
            build_rust(shadow / 'tools/bullet-rust-dbvt-broadphase-check/runner.rs', executable, 'mutant-build-' + name)
            raw = run([executable, args.policy], 'mutant-run-' + name, inputs.encode())
            rows = validate(raw, inputs, False)
            mismatch = differences(plain, rows)
            require(mismatch, 'compiled semantic control must change full valid rows: ' + name)
            controls[name] = {'normal_exit': True, 'full_schema': True, 'different_checkpoints': mismatch,
                              'executable_sha256': digest(executable.read_bytes()),
                              'semantic_witness': witness(name, plain, rows)}
        save(out / 'semantic-controls.json', controls)
        status.update(status='CONTROLLED_PASS', semantic_controls=len(controls), checkpoints=manifest['checkpoints'])
    except Exception as error:
        status['error'] = str(error)
        raise
    finally:
        final = snapshot()
        save(out / 'source-final.json', final)
        if final != before:
            status.update(status='FAIL', error='protected source closure changed during verification')
        save(out / 'report.json', status)
        members = {p.relative_to(out).as_posix(): digest(p.read_bytes()) for p in sorted(out.rglob('*'))
                   if p.is_file() and p.name != 'artifact-manifest.json'}
        save(out / 'artifact-manifest.json', members)
        require(final == before, 'protected source closure unchanged')
        print(json.dumps(status, sort_keys=True))


if __name__ == '__main__':
    main()
