"""Hosted x86_64 C/Rust ABI smoke using actual translated definitions."""
import argparse
import json
from pathlib import Path
import shutil
import sys

from full_compiler import stable_env
from probe import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2rust', required=True, type=Path)
    parser.add_argument('--artifacts', required=True, type=Path)
    parser.add_argument('--clang', default='/usr/bin/clang-18')
    parser.add_argument('--rust-toolchain', default='1.95.0')
    args = parser.parse_args()
    root = args.artifacts.resolve()
    root.mkdir(parents=True, exist_ok=True)
    fixture = Path(__file__).resolve().parent / 'abi-fixtures'
    for path in fixture.glob('*.c'):
        shutil.copy2(path, root / path.name)
    source = root / 'translated.c'
    database = root / 'compile_commands.json'
    database.write_text(json.dumps([{'directory': str(root), 'file': str(source),
                                    'arguments': [args.clang, '-std=c99', '-c', str(source)]}], indent=2))
    result = {'status': 'incomplete', 'stages': {}}
    env = stable_env(root / 'target')

    def stage(name, command, timeout=60):
        record = run(command, root / (name + '.log'), cwd=root, env=env, timeout=timeout)
        result['stages'][name] = record
        (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        if record['exit_code'] != 0:
            raise RuntimeError(name + ' failed')

    try:
        stage('clang-ast', [args.clang, '-std=c99', '-Xclang', '-ast-dump-all', '-fsyntax-only', str(source)])
        stage('transpile', [str(args.c2rust.resolve().with_name('c2rust-transpile')),
                           '--fail-on-error', '--disable-rustfmt', '--edition', '2024',
                           '--output-dir', str(root / 'rust'), str(database)])
        generated = root / 'rust/translated.rs'
        text = generated.read_text()
        if 'extern "win64" fn' not in text or 'extern "C" fn' not in text:
            raise RuntimeError('actual generated ABI definitions missing')
        stage('rust-build', ['rustc', '+' + args.rust_toolchain, '--edition', '2024',
                             '--crate-type', 'staticlib', str(generated), '-o', str(root / 'libtranslated.a')])
        stage('c-link', [args.clang, '-std=c99', str(root / 'caller.c'), str(root / 'libtranslated.a'),
                         '-ldl', '-lpthread', '-lm', '-o', str(root / 'abi-check')])
        stage('abi-run', [str(root / 'abi-check')], 10)
        expected = 'C to Rust Win64 direct/vtable 204; Rust to C Win64 callback 120; C ABI 86\n'
        if (root / 'abi-run.log').read_text() != expected:
            raise RuntimeError('missing or unexpected ABI runtime result')
        result['status'] = 'success'
    except (RuntimeError, OSError) as error:
        result['status'] = 'failure'
        result['error'] = str(error)
    finally:
        (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return 0 if result['status'] == 'success' else 1


if __name__ == '__main__':
    sys.exit(main())
