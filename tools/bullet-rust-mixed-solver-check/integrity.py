"""Hash the standalone compilation closure without newline or path normalization."""
import hashlib
import json
from pathlib import Path
import re


def producer_paths(root, read_source=None):
    from check import SOURCES
    here = root / 'tools/bullet-rust-mixed-solver-check'
    src = root / 'recipes/bullet275/bullet-src/src'
    shim = root / 'rust/crates/mds-bullet-sys/shim'
    paths = {*src.rglob('*.h'), *(src / (name + '.cpp') for name in SOURCES),
             *shim.rglob('*.h'), * (root / 'rust/crates/mds-crtmath/src').glob('*.rs'),
             here / 'cases.py', here / 'oracle.cpp', here / 'runner.rs',
             root / 'tools/bullet-rust-contact-solver-check/support.rs'}
    read_source = read_source or (lambda path: path.read_text())
    for source in [here / 'runner.rs', root / 'tools/bullet-rust-contact-solver-check/support.rs']:
        paths.update((source.parent / relative).resolve() for relative in re.findall(r'#\[path = "([^"]+)"\]', read_source(source)))
    return sorted(paths)


def snapshot(root, paths):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}


def check_integrity(root, out, sources, fixtures):
    failures = [name for entries in [sources, fixtures] for name, expected in entries.items()
                if not (root / name).is_file() or hashlib.sha256((root / name).read_bytes()).hexdigest() != expected]
    result = {'status': 'FAIL' if failures else 'PASS', 'sources': len(sources), 'fixtures': len(fixtures), 'changed': failures}
    (out / 'integrity.json').write_text(json.dumps(result, indent=2) + '\n')
    if failures:
        raise ValueError('source or frozen fixture integrity differs: ' + ', '.join(failures))
