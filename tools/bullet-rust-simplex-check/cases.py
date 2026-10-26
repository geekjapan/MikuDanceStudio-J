"""Deterministic operation streams, with region and exceptional-value cases."""
import itertools
import json
import math
import random
import struct


def bits(f):
    return struct.unpack('<I', struct.pack('<f', f))[0]


def value(i):
    return struct.unpack('<f', struct.pack('<I', i))[0]


def corpus(nonfinite=False):
    lines, labels = [], []

    def emit(op, *vectors):
        lines.append(' '.join([op] + [f'{bits(f):x}' for v in vectors for f in v]))

    def case(name, points, witnesses=True, first='C'):
        start = len(lines)
        emit('R')
        for i, w in enumerate(points):
            q = (i + .25, -i - .5, i * .125)
            p = tuple(x + y for x, y in zip(w, q)) if witnesses else (i + 9., -i - 3., i + 2.)
            emit('A', w, p, q)
            emit('I', w)
        emit(first)
        emit('C')
        emit('P')
        emit('B')
        for w in points:
            emit('I', w)
        emit('I', (1e18,)*3)
        labels.append({'name': name, 'start': start, 'end': len(lines), 'size': len(points)})

    tetra=[(1.,0.,0.), (0.,1.,0.), (0.,0.,1.), (-1.,-1.,-1.)]
    emit('R')
    case('seed-defined-witnesses', [(1., 2., 3.)], False)
    if nonfinite:
        for f,name in [(math.inf,'inf'),(-math.inf,'negative-inf'),(math.nan,'nan')]:
            for n in [1,2,3,4]:
                case(f'{name}-{n}', [(f,1.,0.)]+tetra[:n-1], False)
        return ('\n'.join(lines)+'\n').encode(), labels
    case('empty-retains-cache', [])
    case('singleton-stored-w-is-independent', [(-3., 2., 1.)], False, 'P')
    for name, ps in [
        ('segment-A', [(1., 0., 0.), (2., 0., 0.)]),
        ('segment-B', [(2., 0., 0.), (1., 0., 0.)]),
        ('segment-AB', [(-1., 2., 0.), (1., 2., 0.)]),
        ('coincident', [(1., 2., 3.)]*2),
        ('signed-zero', [(-0., 0., -0.), (0., -0., 0.)]),
    ]:
        case(name, ps)
    tri=[(0., 0., 1.), (2., 0., 1.), (0., 2., 1.)]
    for name, point in [('A',(-1.,-1.,0.)), ('B',(3.,-1.,0.)), ('AB',(1.,-1.,0.)), ('C',(-1.,3.,0.)), ('AC',(-1.,1.,0.)), ('BC',(2.,2.,0.)), ('face',(.5,.5,0.)), ('tie-A',(0.,0.,0.)), ('tie-BC',(1.,1.,0.))]:
        translated=[tuple(a-b for a,b in zip(v,point)) for v in tri]
        for j, permutation in enumerate(itertools.permutations(translated)):
            case(f'triangle-{name}-permutation-{j}', permutation, j % 2 == 0, 'P' if j % 2 else 'C')
    tetra=[(1.,0.,0.), (0.,1.,0.), (0.,0.,1.), (-1.,-1.,-1.)]
    offsets=[('interior',(0.,0.,0.)), ('ABC',(2.,2.,2.)), ('ACD',(-2.,1.,-2.)), ('ADB',(1.,-2.,-2.)), ('BDC',(-2.,-2.,1.)), ('vertex',(3.,0.,0.)), ('edge',(2.,2.,0.)), ('face-tie',(1.,1.,1.))]
    for name, offset in offsets:
        ps=[tuple(a-b for a,b in zip(v,offset)) for v in tetra]
        for j, perm in enumerate(itertools.permutations(ps)):
            case(f'tetra-{name}-permutation-{j}', perm, j % 2 == 0)
    for n in [2,3,4]:
        case(f'duplicate-{n}', [(1.,2.,3.)]*n)
        case(f'collinear-{n}', [(float(i), 0., 0.) for i in range(n)])
    case('coplanar', [(1.,0.,1.), (0.,1.,1.), (-1.,0.,1.), (0.,-1.,1.)])
    threshold=bits(1e-4)
    for delta in [-1,0,1]:
        h=value(threshold+delta)
        case(f'degeneracy-threshold-{delta}', [(0.,0.,1.),(1.,0.,1.),(0.,1.,1.),(0.,0.,1.+h)])
        case(f'degeneracy-exact-signd-{delta}', [(0.,0.,0.),(1.,0.,0.),(0.,1.,0.),(0.,0.,h)])
    for scale,name in [(value(1),'subnormal'),(value(0x800000),'small-normal'),(1e-12,'tiny'),(1e10,'large'),(1e30,'overflow')]:
        for n in [2,3,4]:
            case(f'{name}-{n}', [tuple(x*scale for x in v) for v in tetra[:n]])
    for delta in [-1,0,1]:
        x=value(bits(1.)+delta)
        case(f'ulp-{delta}', [(x,1.,-1.),(-1.,-1.,1.),(2.,-1.,-1.)])
    case('cancellation', [(16777216.,1.,-16777216.),(-16777216.,-1.,16777216.),(1.,2.,3.)], False)
    rng=random.Random(275)
    for i in range(2000):
        n=i%5
        points=[tuple(rng.randint(-10000,10000)/128 for _ in range(3)) for _ in range(n)]
        case(f'random-{i}', points, i%3!=0, 'P' if i%2 else 'C')
    # Growth after reduction exercises lastW retention and invalidation on add.
    for i in range(64):
        emit('R')
        for w in [(1.,2.,3.),(2.,3.,4.),(-2.,-3.,-4.),(0.,1.,-2.)]:
            emit('A', w, w, (0.,0.,0.))
            emit('C')
            emit('I', w)
            emit('B')
    return ('\n'.join(lines)+'\n').encode(), labels


if __name__=='__main__':
    import sys
    sys.stdout.buffer.write(corpus()[0])
