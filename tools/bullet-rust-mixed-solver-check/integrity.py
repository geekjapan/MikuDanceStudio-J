"""Hash the standalone compilation closure without newline or path normalization."""
import hashlib
import json
import os
import stat
from pathlib import Path
import re


def regular_path(root, path):
    for entry in [path, *path.parents]:
        if entry == root:break
        if entry.is_symlink():raise ValueError('symlink source entry: ' + str(entry))
    try:mode=path.stat().st_mode
    except OSError as error:raise ValueError('missing source entry: ' + str(path)) from error
    if not stat.S_ISREG(mode):raise ValueError('nonregular source entry: ' + str(path))
    return path


def input_files(folder, pattern, excluded=()):
    if folder.is_symlink():raise ValueError('symlink source directory: ' + str(folder))
    def failed(error):raise error
    for current, dirs, files in os.walk(folder, followlinks=False, onerror=failed):
        current=Path(current)
        dirs[:]=[name for name in dirs if current/name not in excluded and name != '__pycache__']
        for name in dirs:
            if (current/name).is_symlink():raise ValueError('symlink source directory: ' + str(current/name))
            if (current/name).match(pattern):raise ValueError('nonregular source entry: ' + str(current/name))
        for name in files:
            path=current/name
            if path not in excluded and path.match(pattern):yield path


def verifier_paths(root, out=None):
    here=root/'tools/bullet-rust-mixed-solver-check'
    excluded=() if out is None else (out,)
    return sorted({*input_files(here, '*.json', excluded),
                   *(p for p in input_files(here, '*.py', excluded) if p.parent == here)})


def source_paths(root, out=None):
    return sorted(set(producer_paths(root)) | set(verifier_paths(root, out)))


def producer_paths(root, read_source=None):
    from check import SOURCES
    here = root / 'tools/bullet-rust-mixed-solver-check'
    src = root / 'recipes/bullet275/bullet-src/src'
    shim = root / 'rust/crates/mds-bullet-sys/shim'
    paths = {*input_files(src, '*.h'), *(src / (name + '.cpp') for name in SOURCES),
             *input_files(shim, '*.h'), *input_files(root / 'rust/crates/mds-crtmath/src', '*.rs'),
             here / 'cases.py', here / 'oracle.cpp', here / 'runner.rs',
             root / 'tools/bullet-rust-contact-solver-check/support.rs'}
    read_source = read_source or (lambda path: path.read_text())
    for source in [here / 'runner.rs', root / 'tools/bullet-rust-contact-solver-check/support.rs']:
        paths.update(Path(os.path.abspath(source.parent / relative)) for relative in re.findall(r'#\[path = "([^"]+)"\]', read_source(regular_path(root, source))))
    return sorted(paths)


def snapshot(root, paths):
    return {p.relative_to(root).as_posix(): hashlib.sha256(regular_path(root, p).read_bytes()).hexdigest() for p in sorted(set(paths))}


def check_integrity(root, out, sources, fixtures):
    failures=[]
    try:
        current={p.relative_to(root).as_posix() for p in source_paths(root, out)}
        failures.extend(sorted(current ^ set(sources)))
        for entries in [sources, fixtures]:
            for name, expected in entries.items():
                if hashlib.sha256(regular_path(root, root/name).read_bytes()).hexdigest() != expected:
                    failures.append(name)
    except (OSError, ValueError) as error:
        failures.append(str(error))
    result = {'status': 'FAIL' if failures else 'PASS', 'sources': len(sources), 'fixtures': len(fixtures), 'changed': failures}
    (out / 'integrity.json').write_text(json.dumps(result, indent=2) + '\n')
    if failures:
        raise ValueError('source or frozen fixture integrity differs: ' + ', '.join(failures))
