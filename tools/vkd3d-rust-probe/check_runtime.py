"""Check the prepared C2Rust tool against the hosted LLVM/Rust runtime."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from apply_c2rust_patch import verify_tool


def output(command):
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=True)
    print('$ ' + ' '.join(map(str, command)), flush=True)
    print(result.stdout, end='', flush=True)
    return result.stdout


def check(tool, record=False):
    verify_tool(tool)
    versions = {
        'clang': output(['/usr/bin/clang-18', '--version']).splitlines()[0],
        'llvm': output(['/usr/bin/llvm-config-18', '--version']).strip(),
        'rust': output(['rustc', '+1.95.0', '--version']).strip(),
        'ldd': output(['ldd', '--version']).splitlines()[0],
        'packages': output(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\n',
                           'clang-18', 'llvm-18', 'libclang-cpp18', 'libllvm18']),
    }
    if (not re.search(r'\bclang version 18\.', versions['clang'])
            or not versions['llvm'].startswith('18.')
            or not versions['rust'].startswith('rustc 1.95.0 ')):
        raise RuntimeError('expected Clang/LLVM 18 and Rust 1.95.0')
    for name in ('c2rust', 'c2rust-transpile'):
        dependencies = output(['ldd', str(tool / 'bin' / name)])
        if re.search(r'\bnot found\b', dependencies):
            raise RuntimeError('unresolved runtime dependency for ' + name)
        output([str(tool / 'bin' / name), '--version'])
    manifest = tool / 'runtime.json'
    if record:
        manifest.write_text(json.dumps(versions, indent=2) + '\n')
    elif versions != json.loads(manifest.read_text()):
        raise RuntimeError('runtime versions differ from the prepared tool')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool', required=True, type=Path)
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    check(args.tool.resolve(), args.record)


if __name__ == '__main__':
    main()
