"""Output-copy observations of the actual simplex argument, without pointer values."""
import difflib
from pathlib import Path
import re
import shutil


def instrument_rust(source):
    pattern = re.compile(r'(            self\.manifolds\[index\]\.manifold\.process\(\n                objects\[a\]\.contact,\n                objects\[b\]\.contact,\n)                ([^\n]+),\n            \);')
    matches = list(pattern.finditer(source))
    assert len(matches) == 1, 'dispatcher process observer anchor differs'
    match = matches[0]
    argument = match[2]
    hook = '''            let configured_simplex = &self.simplex as *const VoronoiSimplexSolver;
            let used_simplex = ARGUMENT;
            if matches!(self.manifolds[index].manifold.kind(), super::contact::PairKind::ConvexConvex | super::contact::PairKind::CapsuleCapsule) {
                eprintln!("SIMPLEX {}", usize::from(std::ptr::eq(configured_simplex, used_simplex as *const VoronoiSimplexSolver)));
            }
'''.replace('ARGUMENT', argument)
    return source[:match.start()] + hook + match[1] + '                used_simplex,\n            );' + source[match.end():]


def copy_rust(root, destination):
    core = destination / 'rust/crates/mds-bullet/src/core'
    shutil.copytree(root / 'rust/crates/mds-bullet/src/core', core, dirs_exist_ok=True)
    runner = destination / 'tools/bullet-rust-dispatcher-check/runner.rs'
    runner.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / 'tools/bullet-rust-dispatcher-check/runner.rs', runner)
    source = core / 'dispatcher.rs'
    original = source.read_text();observed = instrument_rust(original);source.write_text(observed)
    (destination / 'observer.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True), observed.splitlines(True))))
    return runner


def simplex_events(raw):
    result = []
    for line in raw.decode('ascii').splitlines():
        if line.startswith('SIMPLEX'):
            assert line in ['SIMPLEX 0', 'SIMPLEX 1'], 'malformed simplex observation'
            result.append(line)
    return result
