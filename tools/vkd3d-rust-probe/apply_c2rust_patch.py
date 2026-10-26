"""Apply the local ABI patch only to the pinned, clean official C2Rust source."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

REVISION = 'ac687698b6c13491dfec45c6a9ad9e8b4da35227'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply(source, artifacts):
    source = source.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    patch = Path(__file__).resolve().parent / 'patches/c2rust-win64-abi.patch'

    def git(*arguments):
        return subprocess.check_output(['git', '-C', str(source), *arguments], text=True)

    if git('rev-parse', 'HEAD').strip() != REVISION:
        raise ValueError('C2Rust revision differs from pinned official source')
    if git('status', '--porcelain').strip():
        raise ValueError('C2Rust source must be clean before patching')
    git('apply', '--check', str(patch))
    git('apply', str(patch))
    diff = git('diff', '--binary')
    (artifacts / 'c2rust-source.patch').write_text(diff)
    files = git('diff', '--name-only').splitlines()
    record = {'official_repository': 'https://github.com/immunant/c2rust.git',
              'original_revision': REVISION, 'patch_sha256': digest(patch),
              'applied_diff_sha256': digest(artifacts / 'c2rust-source.patch'),
              'modified_source_sha256': {name: digest(source / name) for name in files}}
    (artifacts / 'c2rust-patch.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--artifacts', required=True, type=Path)
    args = parser.parse_args()
    apply(args.source, args.artifacts)
