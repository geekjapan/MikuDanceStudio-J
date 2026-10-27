#!/usr/bin/env python3
"""Capture real persistent dispatcher traces. Unknown numeric results fail closed."""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from cases import corpus
from trace import validate
from observe import copy_rust, simplex_events

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = 'fa418493a170aca71021301f171d45d5ce48e9ef'


def native_sources(root=ROOT):
    src = root / 'recipes/bullet275/bullet-src/src'
    return sorted(p for folder in ['LinearMath', 'BulletCollision', 'BulletDynamics'] for p in (src / folder).rglob('*.cpp'))


def source_paths(root=ROOT):
    src = root / 'recipes/bullet275/bullet-src/src'
    return sorted(set([
        *native_sources(root), *src.rglob('*.h'), *src.rglob('*.inl'),
        *(root / 'rust/crates/mds-bullet-sys/shim').rglob('*.h'),
        *(root / 'rust/crates/mds-bullet/src/core').rglob('*.rs'),
        *(root / 'rust/crates/mds-crtmath/src').rglob('*.rs'),
        *(p for p in (root / 'rust/crates/mds-bullet/tests').rglob('*') if p.is_file()),
        *(root / 'tools/bullet-rust-dispatcher-check').glob('*.*'),
        root / '.github/workflows/bullet-dispatcher.yml',
    ]))


def snapshot(root=ROOT):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths(root) if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--mutation', action='append')
    parser.add_argument('--skip-mutations', action='store_true', help='Focused local capture only; does not qualify for acceptance')
    args = parser.parse_args()
    out = args.out_dir.resolve();out.mkdir(parents=True, exist_ok=True)
    before = snapshot()
    status = {'schema': 'dispatcher-v1', 'status': 'FAIL', 'base': BASE,
              'parent_current_source_acceptance': 'PENDING', 'world_integration': 'NOT_CONNECTED', 'four_host_acceptance': 'PENDING'}
    def save(name, value): (out / name).write_text(json.dumps(value, indent=2) + '\n')
    save('source-start.json', before)
    producer = {name: digest for name, digest in before.items() if name.endswith(('.rs', '.cpp', '.h', '.inl'))}
    save('producer-start.json', producer)
    save('verification-start.json', {name: digest for name, digest in before.items() if name not in producer})
    def protected_snapshot():
        folders = [ROOT / 'rust/crates/mds-bullet/tests', ROOT / 'recipes/bullet275/bullet-src/src', ROOT / 'rust/crates/mds-bullet-sys/shim', ROOT / 'rust/crates/mds-crtmath/src', *[folder for folder in ROOT.glob('tools/bullet-rust-*-check') if folder != HERE]]
        paths = sorted(set(p for folder in folders for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts))
        return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    protected = protected_snapshot()
    save('protected-start.json', protected)
    generated = {}
    commands = []
    env = {k: v for k, v in os.environ.items() if not k.startswith('OPENMMD_DUMP_')}
    def run(command, label, inputs=None):
        command = list(map(str, command));commands.append({'label': label, 'argv': command})
        save('commands.json', commands)
        result = subprocess.run(command, cwd=ROOT / 'rust', env=env, input=inputs, capture_output=True, timeout=240)
        (out / (label + '.stdout')).write_bytes(result.stdout);(out / (label + '.stderr')).write_bytes(result.stderr)
        if result.returncode: raise RuntimeError(f'{label} returned {result.returncode}: {result.stderr.decode(errors="replace")[-3000:]}')
        return result.stdout
    try:
        assert before == snapshot(), 'source membership or bytes changed before build'
        machine = platform.machine().lower()
        assert machine in ['arm64', 'aarch64', 'amd64', 'x86_64'], machine
        if platform.system() == 'Darwin': assert machine == 'arm64', 'Intel macOS is unsupported'
        status['host'] = {'system': platform.platform(), 'architecture': machine,
                          'runner_image': os.environ.get('ImageOS'), 'runner_image_version': os.environ.get('ImageVersion')}
        run(['rustup', 'run', '1.95.0', 'rustc', '-Vv'], 'rust-version')
        run(['git', '-C', ROOT, 'ls-files', '--eol'], 'git-transport')
        run(['git', '-C', ROOT, 'check-attr', '--stdin', 'text', 'eol'], 'source-attributes', ('\n'.join(before) + '\n').encode())
        compiler = os.environ.get('CXX', 'cl' if os.name == 'nt' else 'clang++')
        run([compiler, '/?'] if os.name == 'nt' else [compiler, '--version'], 'compiler-version')
        run([sys.executable, '-m', 'unittest', 'discover', '-s', HERE, '-p', 'test_*.py'], 'checker-tests')
        crt = out / ('mds_crtmath.lib' if os.name == 'nt' else 'libmds_crtmath.a')
        run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-name', 'mds_crtmath', '--crate-type', 'rlib,staticlib', '--print', 'native-static-libs', '-O', ROOT / 'rust/crates/mds-crtmath/src/lib.rs', '--out-dir', out], 'crt')
        src = ROOT / 'recipes/bullet275/bullet-src/src';shim = ROOT / 'rust/crates/mds-bullet-sys/shim'
        dispatcher = src / 'BulletCollision/CollisionDispatch/btCollisionDispatcher.cpp'
        original = dispatcher.read_text()
        replacements = [
            ('\tm_manifoldsPtr.push_back(manifold);', '\tm_manifoldsPtr.push_back(manifold);\n\tfprintf(stderr,"ALLOC %d\\n",manifold->m_index1a);'),
            ('\treturn algo;', '\tfprintf(stderr,"ALGORITHM %d %d\\n",*static_cast<int*>(body0->getUserPointer()),*static_cast<int*>(body1->getUserPointer()));\n\treturn algo;'),
            ('\tclearManifold(manifold);', '\tfprintf(stderr,"RELEASE %d\\n",manifold->m_index1a);\n\tclearManifold(manifold);'),
        ]
        observed = original
        for anchor, replacement in replacements:
            assert observed.count(anchor) == 1, anchor
            observed = observed.replace(anchor, replacement)
        observed = '#include <cstdio>\n' + observed
        altered = out / dispatcher.name;altered.write_text(observed)
        convex = src / 'BulletCollision/CollisionDispatch/btConvexConvexAlgorithm.cpp'
        convex_original = convex.read_text()
        convex_anchor = 'void btConvexConvexAlgorithm ::processCollision (btCollisionObject* body0,btCollisionObject* body1,const btDispatcherInfo& dispatchInfo,btManifoldResult* resultOut)\n{'
        assert convex_original.count(convex_anchor) == 1
        convex_observed = '#include <cstdio>\n' + convex_original.replace(convex_anchor, convex_anchor + '\n    static const btSimplexSolverInterface* configured = m_simplexSolver;\n    fprintf(stderr,"SIMPLEX %d\\n",configured==m_simplexSolver?1:0);')
        altered_convex = out / convex.name;altered_convex.write_text(convex_observed)
        (out / 'simplex-observer.diff').write_text(''.join(difflib.unified_diff(convex_original.splitlines(True), convex_observed.splitlines(True))))
        (out / 'observer.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True), observed.splitlines(True))))
        save('observer-operations.json', replacements)
        if os.name == 'nt':
            flags = ['/nologo', '/std:c++17', '/O2', '/MD', '/EHsc', '/fp:precise', '/W0', '/DBT_NO_PROFILE=1', f'/I{src}', f'/I{shim}', f'/I{dispatcher.parent}', f'/FI{shim / "det_math.h"}']
        else:
            flags = ['-std=c++17', '-O2', '-ffp-contract=off', '-fno-fast-math', '-fdeclspec', '-w', '-DBT_NO_PROFILE=1', '-I', shim / 'sse_emu', '-I', src, '-I', shim, '-I', dispatcher.parent, '-include', shim / 'det_math.h']
        save('compiler-flags.json', list(map(str, flags)))
        profile = out / 'macros.cpp'
        profile_code = '#include "LinearMath/btScalar.h"\n#include <cstdio>\n#define S_(x) #x\n#define S(x) S_(x)\nint main(){\n'
        for macro in ['BT_USE_SSE', 'BT_USE_DOUBLE_PRECISION', 'BT_NO_PROFILE', 'WIN32', '_WIN32', '_WIN64', '_MSC_VER', '_M_X64', '__x86_64__', '__aarch64__', '_M_ARM64']:
            profile_code += f'#ifdef {macro}\nputs("{macro}=" S({macro}));\n#else\nputs("{macro}=<undefined>");\n#endif\n'
        profile.write_text(profile_code + 'printf("pointer_bits=%zu\\n",sizeof(void*)*8);\n}\n')
        profile_exe = out / ('macros.exe' if os.name == 'nt' else 'macros')
        run([compiler, *flags, profile, f'/Fe:{profile_exe}', f'/Fo:{out / "macros.obj"}'] if os.name == 'nt' else [compiler, *flags, profile, '-o', profile_exe], 'macro-build')
        run([profile_exe], 'effective-macros')
        generated = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in [profile, altered, altered_convex]}
        save('generated-producers.json', generated)
        sources = [HERE / 'oracle.cpp', *[p for p in native_sources() if p not in [dispatcher, convex]]]
        save('compiled-cpp.json', [p.relative_to(ROOT).as_posix() for p in [*sources, dispatcher, convex]])
        objects = []
        # Compile serially so command and compiler output order remains deterministic.
        for i, path in enumerate(sources):
            obj = out / (f'base-{i}.obj' if os.name == 'nt' else f'base-{i}.o')
            run([compiler, *flags, '/c', path, f'/Fo{obj}'] if os.name == 'nt' else [compiler, *flags, '-c', path, '-o', obj], f'compile-{i}')
            objects.append(obj)
        binaries = []
        for label, paths in [('original', [dispatcher, convex]), ('observed', [altered, altered_convex])]:
            exe = out / (label + ('.exe' if os.name == 'nt' else ''))
            if os.name == 'nt':
                libs = (out / 'crt.stderr').read_text().split('native-static-libs:')[-1].splitlines()[0].split()
                command = [compiler, *flags, *paths, *objects, crt, f'/Fe:{exe}', f'/Fo:{out}\\', '/link', '/OPT:REF', *libs]
            else:
                command = [compiler, *flags, *paths, *objects, crt, '-o', exe]
                command += ['-Wl,-dead_strip'] if platform.system() == 'Darwin' else ['-Wl,--gc-sections', '-ldl', '-lpthread', '-lm']
            run(command, 'link-' + label);binaries.append(exe)
        rust = out / ('rust-dispatcher.exe' if os.name == 'nt' else 'rust-dispatcher')
        rust_args = ['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '-O', '--extern', f'mds_crtmath={out / "libmds_crtmath.rlib"}']
        run([*rust_args, HERE / 'runner.rs', '-o', rust], 'rust-build')
        shadow = out / 'observed-rust-source'
        observed_runner = copy_rust(ROOT, shadow)
        generated.update({str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in shadow.rglob('*.rs')})
        save('generated-producers.json', generated)
        observed_rust = out / ('rust-observed.exe' if os.name == 'nt' else 'rust-observed')
        run([*rust_args, observed_runner, '-o', observed_rust], 'rust-observer-build')
        tests = out / ('rust-tests.exe' if os.name == 'nt' else 'rust-tests')
        run([*rust_args, '--test', HERE / 'harness.rs', '-o', tests], 'test-build')
        run([tests, 'core::dispatcher::tests'], 'focused-tests')
        inputs = corpus();(out / 'inputs.tsv').write_bytes(inputs)
        expected = run([binaries[0]], 'native', inputs)
        actual_observer = run([binaries[1]], 'observed', inputs)
        assert expected == actual_observer, 'observer changed original native stdout'
        observer_events = (out / 'observed.stderr').read_text().splitlines()
        assert sum(line.startswith('ALLOC ') for line in observer_events) == sum(line.startswith('RELEASE ') for line in observer_events), 'native manifold teardown was not exactly once'
        actual = run([rust], 'rust', inputs)
        rust_observer = run([observed_rust], 'rust-observed', inputs)
        assert actual == rust_observer, 'Rust argument observer changed stdout'
        native_simplex = simplex_events((out / 'observed.stderr').read_bytes())
        rust_simplex = simplex_events((out / 'rust-observed.stderr').read_bytes())
        assert native_simplex and native_simplex == rust_simplex, 'actual configuration simplex argument identity differs'
        save('simplex-comparison.json', {'status': 'PASS', 'events': len(native_simplex), 'native': native_simplex, 'rust': rust_simplex})
        for stream in [expected, actual_observer, actual]: validate(stream, inputs)
        difference = ''.join(difflib.unified_diff(expected.decode().splitlines(True), actual.decode().splitlines(True), fromfile='native', tofile='rust'))
        (out / 'native-rust.diff').write_text(difference)
        save('trace-sha256.json', {name: hashlib.sha256((out / name).read_bytes()).hexdigest() for name in ['inputs.tsv', 'native.stdout', 'observed.stdout', 'observed.stderr', 'rust.stdout']})
        assert expected == actual, 'raw native/Rust mismatch; complete streams retained; numeric profile approval is pending'
        status['raw_comparison'] = 'BIT_EXACT'
        status['commands'] = len(inputs.splitlines())
        status['trace_lines'] = len(actual.splitlines())
        assert before == snapshot(), 'source closure changed after capture'
        if not args.skip_mutations:
            run([sys.executable, HERE / 'mutations.py', '--out-dir', out / 'mutations', '--capture-dir', out, *[x for name in (args.mutation or []) for x in ['--only', name]]], 'mutations')
        save('source-end.json', snapshot())
        save('protected-end.json', protected_snapshot())
        status['mutation_coverage'] = 'NOT_RUN' if args.skip_mutations else 'SELECTED_ONLY' if args.mutation else 'ALL_NAMED'
        status['status'] = 'PASS_FOCUSED_ONLY' if args.skip_mutations else 'PASS_SELECTED_MUTATIONS_ONLY' if args.mutation else 'PASS_SAME_HOST_RAW_AND_MUTATIONS'
    except BaseException as error:
        status['error'] = str(error)
        raise
    finally:
        after = snapshot();save('source-finally.json', after)
        protected_after = protected_snapshot();save('protected-finally.json', protected_after)
        generated_after = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() if Path(name).is_file() else None for name in generated}
        save('generated-producers-finally.json', generated_after)
        status['integrity'] = 'PASS' if before == after and protected == protected_after and generated == generated_after else 'FAIL'
        save('status.json', status)
        assert before == after and protected == protected_after and generated == generated_after, 'source membership or protected raw bytes changed during check'
    print(json.dumps(status, indent=2))


if __name__ == '__main__': main()
