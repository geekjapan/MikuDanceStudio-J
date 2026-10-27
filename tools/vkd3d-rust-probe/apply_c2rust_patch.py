"""Apply and retain every destination of the pinned official C2Rust patch."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess

REVISION = 'ac687698b6c13491dfec45c6a9ad9e8b4da35227'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_destinations(patch):
    destinations = []
    for section in patch.read_text().split('diff --git ')[1:]:
        header = section.splitlines()[0]
        match = re.fullmatch(r'a/([^\s]+) b/([^\s]+)', header)
        if not match or match[1] != match[2]:
            raise ValueError('unsafe or unsupported patch destination header')
        name = match[2]
        parts = PurePosixPath(name).parts
        if (not parts or name != '/'.join(parts) or any(p in ('.', '..') for p in parts)
                or name.startswith('/') or ':' in name or '\\' in name or '.git' in parts):
            raise ValueError('unsafe patch destination ' + name)
        if re.findall(r'^\+\+\+ (.+)$', section, re.M) != ['b/' + name]:
            raise ValueError('missing or inconsistent patch destination ' + name)
        if re.search(r'^(?:new file|old|new) mode (?!100644$|100755$)', section, re.M):
            raise ValueError('unsafe patch destination mode ' + name)
        if name in destinations:
            raise ValueError('duplicate patch destination ' + name)
        destinations.append(name)
    if not destinations:
        raise ValueError('missing patch destinations')
    return sorted(destinations)


def source_file(root, name, required=True):
    path = root
    if path.is_symlink():
        raise ValueError('symlink patch destination root')
    for part in PurePosixPath(name).parts:
        path /= part
        if path.is_symlink():
            raise ValueError('symlink patch destination ' + name)
    if required and not path.is_file():
        raise ValueError('missing patch destination ' + name)
    return path


def verify_evidence(artifacts, source=None):
    record = json.loads((artifacts / 'c2rust-patch.json').read_text())
    saved_patch = artifacts / 'c2rust-source.patch'
    names = patch_destinations(saved_patch)
    if (record['original_revision'] != REVISION or digest(saved_patch) != record['patch_sha256']
            or record['applied_diff_sha256'] != record['patch_sha256']
            or set(record['modified_source_sha256']) != set(names)):
        raise ValueError('incomplete or inconsistent applied source evidence')
    for name in names:
        expected = record['modified_source_sha256'][name]
        if digest(source_file(artifacts / 'c2rust-applied-source', name)) != expected:
            raise ValueError('applied source evidence hash differs for ' + name)
        if source is not None and digest(source_file(source, name)) != expected:
            raise ValueError('compiler source differs from applied evidence for ' + name)
    return record


def bind_tool(source, artifacts, tool):
    record = verify_evidence(artifacts, source)
    retained = tool / 'source-evidence'
    retained.mkdir()
    for name in ('c2rust-source.patch', 'c2rust-patch.json'):
        shutil.copy2(artifacts / name, retained / name)
    shutil.copytree(artifacts / 'c2rust-applied-source', retained / 'c2rust-applied-source')
    receipt = {'source_receipt_sha256': digest(retained / 'c2rust-patch.json'),
               'patch_sha256': record['patch_sha256'],
               'binary_sha256': {name: digest(tool / 'bin' / name)
                                 for name in ('c2rust', 'c2rust-transpile')}}
    (tool / 'source-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    verify_tool(tool)


def verify_tool(tool):
    record = verify_evidence(tool / 'source-evidence')
    receipt = json.loads((tool / 'source-receipt.json').read_text())
    if (receipt['source_receipt_sha256'] != digest(tool / 'source-evidence/c2rust-patch.json')
            or receipt['patch_sha256'] != record['patch_sha256']
            or receipt['binary_sha256'] != {name: digest(tool / 'bin' / name)
                                           for name in ('c2rust', 'c2rust-transpile')}):
        raise ValueError('tool binary or applied source receipt differs')


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
    files = patch_destinations(patch)
    for name in files:
        source_file(source, name, required=False)
    git('apply', '--check', str(patch))
    git('apply', str(patch))
    shutil.copy2(patch, artifacts / 'c2rust-source.patch')
    for name in files:
        destination = artifacts / 'c2rust-applied-source' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file(source, name), destination)
    record = {'official_repository': 'https://github.com/immunant/c2rust.git',
              'original_revision': REVISION, 'patch_sha256': digest(patch),
              'applied_diff_sha256': digest(artifacts / 'c2rust-source.patch'),
              'modified_source_sha256': {name: digest(source_file(source, name)) for name in files}}
    (artifacts / 'c2rust-patch.json').write_text(json.dumps(record, indent=2) + '\n')
    verify_evidence(artifacts, source)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--artifacts', required=True, type=Path)
    parser.add_argument('--tool', type=Path, help='bind built binaries to complete retained source evidence')
    args = parser.parse_args()
    if args.tool:
        bind_tool(args.source, args.artifacts, args.tool)
    else:
        apply(args.source, args.artifacts)
