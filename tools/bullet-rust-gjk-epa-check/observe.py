"""Instrument copies only. The unmodified executable remains the output oracle."""
from collections import Counter
import difflib
import json
from pathlib import Path
import subprocess


def observe(src, command, executable, inputs, output, environment):
    narrow = src / 'BulletCollision/NarrowPhaseCollision'
    replacements = {}
    for name in ['btGjkEpa2', 'btGjkEpaPenetrationDepthSolver']:
        source = narrow / (name + '.cpp')
        original = source.read_text()
        changed = '#include <cstdio>\n' + original
        if name == 'btGjkEpa2':
            for rank in [2, 3, 4]:
                old = f'case\t{rank}:\tsqdist=projectorigin('
                assert old in changed
                changed = changed.replace(old, f'case\t{rank}: std::fprintf(stderr,"gjk-project {rank}\\n"); sqdist=projectorigin(')
            changed = changed.replace('if(mask==15)', 'std::fprintf(stderr,"gjk-mask %u\\n",mask); if(mask==15)')
            changed = changed.replace('switch(m_simplex->rank)', 'std::fprintf(stderr,"enclose-rank %u\\n",m_simplex->rank); switch(m_simplex->rank)')
            start = changed.index('// EPA\n')
            before, epa = changed[:start], changed[start:]
            before = before.replace('return(m_status);', 'std::fprintf(stderr,"gjk-result %d\\n",int(m_status)); return(m_status);')
            before = before.replace('if(found)', 'std::fprintf(stderr,"gjk-duplicate %d\\n",int(found)); if(found)')
            before = before.replace('if(sqdist>=0)', 'std::fprintf(stderr,"gjk-projection-valid %d\\n",int(sqdist>=0)); if(sqdist>=0)')
            epa = epa.replace('const btScalar\tsqd=f->d*f->d;', 'const btScalar\tsqd=f->d*f->d; if(f->p==maxp && sqd==mind) std::fprintf(stderr,"epa-best-tie\\n");')
            epa = epa.replace('return(m_status);', 'std::fprintf(stderr,"epa-result %d\\n",int(m_status)); return(m_status);')
            for label, value in [('nonconvex', 'NonConvex'), ('degenerated', 'Degenerated'), ('invalid-hull', 'InvalidHull'), ('vertices', 'OutOfVertices'), ('accuracy', 'AccuraryReached')]:
                old = f'm_status=eStatus::{value};'
                if old in epa:
                    epa = epa.replace(old, old + f' std::fprintf(stderr,"epa-{label}\\n");')
            epa = epa.replace('m_status=m_stock.root?eStatus::OutOfVertices:eStatus::OutOfFaces;', 'm_status=m_stock.root?eStatus::OutOfVertices:eStatus::OutOfFaces; std::fprintf(stderr,"epa-stock-empty\\n");')
            changed = before + epa
        else:
            old = 'if(btGjkEpaSolver2::Distance('
            assert old in changed
            changed = changed.replace('v = results.normal;\n\t\t\treturn false;', 'v = results.normal;\n\t\t\tstd::fprintf(stderr,"adapter-distance-success\\n"); return false;')
            changed = changed.replace('\n\treturn false;', '\n\tstd::fprintf(stderr,"adapter-untouched\\n"); return false;')
            changed = changed.replace(old, 'std::fprintf(stderr,"adapter-distance-fallback\\n"); '+old)
        observed = output / (name + '-observed.cpp')
        observed.write_text(changed)
        (output / (name + '-observed.patch')).write_text(''.join(difflib.unified_diff(original.splitlines(True), changed.splitlines(True), fromfile=str(source), tofile=str(observed))))
        replacements[str(source)] = str(observed)
    observed_exe = output / 'native-gjk-epa-observed'
    cmd = [replacements.get(str(x), str(observed_exe) if x == executable else str(x)) for x in command]
    cmd += ['-I', str(narrow)]
    subprocess.run(cmd, check=True, env=environment)
    with (output / 'coverage.log').open('wb') as log:
        result = subprocess.check_output([observed_exe], input=inputs, stderr=log, env=environment)
    (output / 'observed.tsv').write_bytes(result)
    assert result == (output / 'native.tsv').read_bytes(), 'Observation changed stdout'
    counts = Counter((output / 'coverage.log').read_text().splitlines())
    gaps = [label for label in ['gjk-project 2','gjk-project 3','gjk-project 4','enclose-rank 1','enclose-rank 2','enclose-rank 3','enclose-rank 4','epa-result 0','epa-result 4','epa-result 5','epa-result 6','epa-result 7','epa-result 8','adapter-distance-fallback','adapter-distance-success','adapter-untouched','gjk-result 2','epa-best-tie'] if not counts[label]]
    (output / 'coverage.json').write_text(json.dumps({'counts': dict(counts), 'unobserved': gaps, 'original-observed-stdout-identical': True}, indent=2)+'\n')
    required = ['gjk-project 2', 'gjk-project 3', 'gjk-project 4', 'gjk-projection-valid 0', 'gjk-projection-valid 1', 'gjk-mask 15', 'enclose-rank 2', 'enclose-rank 3', 'enclose-rank 4', 'epa-result 4', 'epa-result 7', 'epa-result 8', 'epa-stock-empty', 'epa-best-tie', 'adapter-distance-success', 'adapter-untouched']
    assert all(counts[label] for label in required), {label: counts[label] for label in required}
    return [Path(p) for p in replacements.values()]
