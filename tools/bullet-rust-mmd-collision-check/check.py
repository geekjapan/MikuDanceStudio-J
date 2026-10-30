#!/usr/bin/env python3
"""Genuine MMD collision diagnostic scaffold. Captures remain UNADMITTED."""
import argparse
import os
from pathlib import Path
import platform
import shutil
import sys

from cases import corpus
from evidence import Recorder, admit_capture, digest, require, save
from hooks import CORE, MUTANTS, NATIVE_OBSERVATIONS, OBSERVATION_PATHS, instrument, inverse, mutate
from trace import common, frames

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = 'f6ab4feef335e76d590c3f8a9c5f532dec73ba70'
BASE_TREE = '005ae1183e9972df56689796cf87589117418e7d'
FOLDERS = ['recipes/bullet275/bullet-src/src', 'rust/crates/mds-bullet/src/core',
           'rust/crates/mds-bullet/tests', 'rust/crates/mds-bullet-sys/shim',
           'rust/crates/mds-crtmath/src', 'tools/bullet-rust-mmd-collision-check']
EXTRA = ['.github/workflows/bullet-mmd-collision-world.yml', 'rust/crates/mds-bullet-sys/build.rs',
         'rust/crates/mds-bullet/Cargo.toml', 'rust/Cargo.lock', '.gitattributes', 'rust/.gitattributes']
PENDING = ['strict closed actual-capture admission and legal actual-capture malformed peers',
           'discovery/pre-use/end include occurrence and archive-member binding',
           'native accelerator allocation chronology admission',
           'full normally exiting compiled mutant corpus and directed field admission',
           'same-HEAD Windows producer admission and four-destination replay']


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


def capture(out):
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'compiler and actual capture are hosted-only')
    require((platform.system(), platform.machine().lower()) in {
        ('Windows', 'amd64'), ('Windows', 'x86_64'), ('Darwin', 'arm64'),
        ('Linux', 'x86_64'), ('Linux', 'aarch64'), ('Linux', 'arm64')}, 'supported actual host')
    require(not out.exists(), 'fresh unique output directory')
    out.mkdir(parents=True)
    inputs, cases = corpus()
    (out / 'inputs.txt').write_bytes(inputs.encode())
    save(out / 'cases.json', cases)
    status = {'schema': 1, 'status': 'UNRUN', 'base': BASE, 'base_tree': BASE_TREE,
              'scope': 'private MMD collision ownership', 'pending': PENDING,
              'native_accelerator': 'unchanged genuine constructor; Rust query and allocation parity excluded'}
    save(out / 'report.json', status)
    recorder = Recorder(out, snapshot)
    try:
        for path in source_paths():
            dst = out / 'source' / path.relative_to(ROOT)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(path.read_bytes())
        head = recorder.run('git-head', ['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
        require(not recorder.run('git-status', ['git', 'status', '--porcelain=v1'], cwd=ROOT).strip(), 'clean producer source')
        status['head'] = head
        compiler = os.environ.get('CXX', 'cl' if os.name == 'nt' else 'clang++')
        rustup = 'rustup'
        rustc = recorder.run('rustc-path', [rustup, 'which', '--toolchain', '1.95.0', 'rustc'], cwd=ROOT / 'rust').decode().strip()
        recorder.run('rust-version', [rustc, '-Vv'], cwd=ROOT / 'rust')
        rust = [rustc, '--edition=2021', '-O']
        recorder.run('crt-build', [*rust, '--crate-name', 'mds_crtmath', '--crate-type', 'rlib,staticlib',
                     '--print', 'native-static-libs', ROOT / 'rust/crates/mds-crtmath/src/lib.rs', '--out-dir', out],
                     cwd=ROOT / 'rust', inputs=[ROOT / 'rust/crates/mds-crtmath/src/lib.rs'])
        rargs = [*rust, '--extern', 'mds_crtmath=' + str(out / 'libmds_crtmath.rlib')]
        suffix, extension = ('.exe', '.obj') if os.name == 'nt' else ('', '.o')
        focused = out / ('dedicated' + suffix)
        dedicated = ROOT / 'rust/crates/mds-bullet/tests/mmd_collision_world.rs'
        recorder.run('dedicated-build', [*rargs, '--test', '-D', 'warnings', dedicated, '-o', focused],
                     cwd=ROOT / 'rust', inputs=[dedicated], outputs=[focused])
        recorder.run('dedicated-run', [focused, 'mmd_world_'], cwd=ROOT / 'rust')
        pure = out / ('pure' + suffix)
        recorder.run('pure-build', [*rargs, '--test', '-D', 'warnings', ROOT / 'rust/crates/mds-bullet/tests/pure_bullet.rs', '-o', pure],
                     cwd=ROOT / 'rust', outputs=[pure])
        recorder.run('pure-run', [pure], cwd=ROOT / 'rust')
        shadow = out / 'generated'
        copy_sources(shadow)
        originals = {path: (shadow / path).read_bytes() for path in OBSERVATION_PATHS}
        edits = instrument(shadow, HERE)
        inverse(shadow, edits, originals)
        save(out / 'observation-edits.json', edits)
        rust_exe = out / ('rust-mmd' + suffix)
        runner = shadow / 'tools/bullet-rust-mmd-collision-check/runner.rs'
        recorder.run('rust-observed-build', [*rargs, '--cfg', 'test', runner, '-o', rust_exe],
                     cwd=ROOT / 'rust', inputs=[runner], outputs=[rust_exe])
        rust_rows = frames(recorder.run('rust-observed-run', [rust_exe], cwd=ROOT / 'rust', data=inputs.encode()), inputs)
        src = ROOT / 'recipes/bullet275/bullet-src/src'
        sources = sorted(p for folder in ['BulletCollision', 'BulletDynamics', 'LinearMath'] for p in (src / folder).rglob('*.cpp'))
        objects, bindings = [], []
        def compile_object(source, obj, label, root=ROOT, extra=()):
            flags = native_flags(root)
            argv = [compiler, *flags, *extra, '/c', source, '/Fo' + str(obj)] if os.name == 'nt' else [compiler, *flags, *extra, '-c', source, '-o', obj]
            recorder.run(label, argv, cwd=ROOT / 'rust', inputs=[source], outputs=[obj])
        for i, source in enumerate(sources):
            obj = out / (source.stem + extension)
            require(obj not in objects, 'unique archive member name')
            compile_object(source, obj, f'compile-{i:03d}')
            objects.append(obj)
            bindings.append({'source': source.relative_to(ROOT).as_posix(), 'source_sha256': digest(source.read_bytes()),
                             'object': obj.name, 'object_sha256': digest(obj.read_bytes())})
        archive = out / ('BulletMmd.lib' if os.name == 'nt' else 'libBulletMmd.a')
        recorder.run('archive-build', ['lib', '/NOLOGO', '/OUT:' + str(archive), *objects] if os.name == 'nt'
                     else ['ar', 'rcs', archive, *objects], cwd=ROOT / 'rust', inputs=objects, outputs=[archive])
        recorder.run('archive-list', ['lib', '/NOLOGO', '/LIST', archive] if os.name == 'nt' else ['ar', 't', archive], cwd=ROOT / 'rust', inputs=[archive])
        save(out / 'archive-bindings.json', bindings)
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
            args = [compiler, '/nologo', '/MD', '/EHsc', obj, *prefix, archive, crt, '/Fe' + str(exe), '/link', *libs] if os.name == 'nt' else [compiler, obj, *prefix, archive, crt, *libs, '-o', exe]
            recorder.run(name + '-link', args, cwd=ROOT / 'rust', inputs=[obj, *prefix, archive, crt], outputs=[exe])
            raw = recorder.run(name + '-run', [exe], cwd=ROOT / 'rust', data=inputs.encode())
            native_rows[name] = frames(raw, inputs, observed=name == 'observed')
        require(common(native_rows['native']) == common(native_rows['observed']), 'common original/observed noninterference')
        require(rust_rows == native_rows['observed'], 'ordered diagnostic native/Rust equality')
        inverse(shadow, edits, originals)
        status.update(status='DIAGNOSTIC_EQUAL_UNADMITTED', cases=len(cases), checkpoints=len(inputs.splitlines()),
                      commands=len(recorder.commands), mutant_definitions=len(MUTANTS), compiled_controls='UNRUN')
        save(out / 'report.json', status)
        admit_capture(out)
    except Exception as error:
        status.update(error=str(error))
        if status['status'] == 'UNRUN':
            status['status'] = 'DIAGNOSTIC_FAILED'
        save(out / 'report.json', status)
        raise
    finally:
        recorder.close()
        save(out / 'artifact-manifest.json', {p.relative_to(out).as_posix(): digest(p.read_bytes()) for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'artifact-manifest.json'})


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
        admit_capture(args.replay_dir)
    capture(args.out_dir.resolve())


if __name__ == '__main__':
    main()
