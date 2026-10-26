"""Observe copies of the native outer detector and owned manifold algorithm."""
from collections import Counter
import difflib
import json
from pathlib import Path
import subprocess

def observe(src, command, executable, inputs, output, environment):
    replacements={}
    paths=['BulletCollision/NarrowPhaseCollision/btGjkPairDetector.cpp','BulletCollision/CollisionDispatch/btConvexConvexAlgorithm.cpp','BulletCollision/CollisionDispatch/btManifoldResult.cpp']
    labels={
        'max-distance': 'checkSimplex=true;',
        'duplicate': 'm_degenerateSimplex = 1;',
        'relative-error': 'm_degenerateSimplex = 11;',
        'closest-failed': 'm_degenerateSimplex = 3;',
        'near-origin': 'm_degenerateSimplex = 6;',
        'distance-increase': 'm_degenerateSimplex = 7;',
        'progress': 'm_degenerateSimplex = 12;',
        'small-axis': 'm_degenerateSimplex = 5;',
        'penetration-adapter': 'm_cachedSeparatingAxis.setZero();',
        'penetration-replaced': 'm_lastUsedMethod = 3;',
        'penetration-retained': 'm_lastUsedMethod = 8;',
        'penetration-zero-normal': 'm_lastUsedMethod = 9;',
        'distance-fallback': 'm_lastUsedMethod = 6;',
        'distance-retained': 'm_lastUsedMethod = 5;',
        'tail': 'm_lastUsedMethod = 1;',
        'emitted': 'm_cachedSeparatingDistance = distance;',
    }
    for relative in paths:
        source=src/relative;original=source.read_text();changed='#include <cstdio>\n'+original
        if source.stem=='btGjkPairDetector':
            for label,needle in labels.items():
                assert changed.count(needle)==1,(label,needle)
                changed=changed.replace(needle,needle+f' std::fprintf(stderr,"outer-{label}\\n");')
            needle='if (m_curIter++ > gGjkMaxIter)\n\t\t\t\t  {'
            assert needle in changed
            changed=changed.replace(needle,needle+' std::fprintf(stderr,"outer-iteration-limit\\n");')
            changed=changed.replace('m_simplexSolver->backup_closest(m_cachedSeparatingAxis);\n\t\t\t\t\tbreak;', 'std::fprintf(stderr,"outer-full-simplex\\n"); m_simplexSolver->backup_closest(m_cachedSeparatingAxis);\n\t\t\t\t\tbreak;')
        elif source.stem=='btConvexConvexAlgorithm':
            needle='resultOut->refreshContactPoints();';assert needle in changed
            changed=changed.replace(needle,'std::fprintf(stderr,"manifold-refresh\\n"); '+needle)
        else:
            needle='if (depth > m_manifoldPtr->getContactBreakingThreshold())';assert needle in changed
            changed=changed.replace(needle, 'std::fprintf(stderr,"manifold-depth %d\\n",int(depth > m_manifoldPtr->getContactBreakingThreshold()));\n'+needle)
        copied=output/(source.stem+'-observed.cpp');copied.write_text(changed)
        (output/(source.stem+'-observed.patch')).write_text(''.join(difflib.unified_diff(original.splitlines(True),changed.splitlines(True),fromfile=str(source),tofile=str(copied))))
        replacements[str(source)]=str(copied)
    observed=output/'native-observed'
    cmd=[replacements.get(str(x),str(observed) if x==executable else str(x)) for x in command]
    cmd+=['-I',str(src/'BulletCollision/NarrowPhaseCollision'),'-I',str(src/'BulletCollision/CollisionDispatch')]
    subprocess.run(cmd,check=True,env=environment)
    with (output/'coverage.log').open('wb') as log:
        result=subprocess.check_output([observed],input=inputs,stderr=log,env=environment)
    (output/'observed.tsv').write_bytes(result)
    assert result==(output/'native.tsv').read_bytes(),'Observer changed output'
    counts=Counter((output/'coverage.log').read_text().splitlines())
    (output/'coverage.json').write_text(json.dumps({'counts':dict(counts),'unobserved':[label for label in [*labels,'full-simplex','iteration-limit'] if not counts['outer-'+label]],'original-observed-stdout-identical':True},indent=2)+'\n')
    for label in ['max-distance','duplicate','near-origin','penetration-adapter','penetration-replaced','distance-fallback','tail','emitted']:
        assert counts['outer-'+label],label
    assert counts['manifold-depth 0'] and counts['manifold-depth 1'] and counts['manifold-refresh']
    return list(map(Path,replacements.values()))
