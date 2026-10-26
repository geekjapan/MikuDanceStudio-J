#!/usr/bin/env python3
"""Deterministic complete independent query scenarios. Compact is the fixed prefix."""
import math
import struct
import random

def f(v): return struct.unpack('<f',struct.pack('<f',v))[0]
def word(v): return f'{struct.unpack("<I",struct.pack("<f",v))[0]:08x}'
def rotation(angle):
    c,s=f(math.cos(angle)),f(math.sin(angle))
    return [c,-s,0,s,c,0,0,0,1]
I=[1,0,0,0,1,0,0,0,1]
def rotation3(rng):
    x,y,z=[rng.uniform(-3,3) for _ in range(3)]
    cx,sx,cy,sy,cz,sz=map(f,[math.cos(x),math.sin(x),math.cos(y),math.sin(y),math.cos(z),math.sin(z)])
    return list(map(f,[cz*cy,cz*sy*sx-sz*cx,cz*sy*cx+sz*sx,sz*cy,sz*sy*sx+cz*cx,sz*sy*cx-cz*sx,-sy,cy*sx,cy*cx]))
COMPACT = 1801
def cases():
    dims=[[0.75,0,0],[0.8,0.6,1.1],[0.45,1.4,0]]
    for ka,kb in [(0,1),(1,0),(0,2),(2,0),(1,2),(2,1),(0,0),(1,1),(2,2)]:
        for distance in [4,2,1.6,1.5,1.4999,1.0,0.2,0]:
            for angle in [0,0.37,1.1]:
                for guess in [[1,0,0],[0,0,0],[0.3,-0.7,1.2]]:
                    yield ka,kb,dims[ka]+dims[kb]+rotation(angle)+[0,0,0]+rotation(-angle*.7)+[distance,0.13 if angle else 0,0]+guess
    # Small, flat, contained, zero-height, negative and extreme dimensions.
    for ka,kb in [(0,1),(1,0),(0,2),(2,0),(1,2),(2,1),(1,1),(2,2)]:
        for scale in [0,1e-6,0.01,0.039999996,0.04,0.040000003,1,1000,1e10,-1]:
            for offset in [0,0.00009999999,0.0001,0.000100000005,0.039999996,0.04,0.040000003,2]:
                a=[f(x*scale)for x in dims[ka]];b=dims[kb].copy()
                if ka==2:a[1]=0
                yield ka,kb,a+b+I+[0,0,0]+rotation(.73)+[offset,offset*.37,0]+[1,0.3,-0.1]
    # Exact axis touching and adjacent float thresholds, cap ends, and slivers.
    for ka,kb in [(0,1),(1,0),(0,2),(2,0),(1,2),(2,1),(0,0),(1,1),(2,2)]:
        for axis in range(3):
            def extent(kind):
                return dims[kind][axis] if kind==1 else dims[kind][0]+(dims[kind][1]*.5 if kind==2 and axis==1 else 0)
            touching=f(extent(ka)+extent(kb))
            bits=struct.unpack('<I',struct.pack('<f',touching))[0]
            offsets=[struct.unpack('<f',struct.pack('<I',bits+d))[0] for d in [-1,0,1]]
            offsets += [touching*.1,touching*.99,touching*1.01,touching*2]
            for offset in offsets:
                for common in [0,10000]:
                    p=[common]*3;q=p.copy();q[axis]+=offset
                    yield ka,kb,dims[ka]+dims[kb]+I+p+I+q+[.3,1.1,-.7]
    for ka,kb in [(0,1),(1,0),(0,2),(2,0),(1,2),(2,1),(0,0),(1,1),(2,2)]:
        thin=[[.00001,0,0],[.00001,3,.041],[.00001,6,0]]
        for offset in [0,.00001,.0001,.04,3]:
            for angle in [0,.19,1.1]:
                yield ka,kb,thin[ka]+dims[kb]+rotation(angle)+[0,0,0]+rotation(-angle)+[offset,offset*.2,offset*.03]+[.3,.7,-1.1]
    rng=random.Random(275)
    for _ in range(5000):
        ka,kb=rng.randrange(3),rng.randrange(3)
        a=[rng.uniform(.04,3) for _ in range(3)];b=[rng.uniform(.04,3)for _ in range(3)]
        yield ka,kb,a+b+rotation3(rng)+[rng.uniform(-4,4)for _ in range(3)]+rotation3(rng)+[rng.uniform(-4,4)for _ in range(3)]+[rng.uniform(-2,2)for _ in range(3)]
    # Directed raw nonfinite dimensions on native defined paths are kept separate.
    for value in [float('inf'),-float('inf'),float('nan')]:
        for kind in range(3):
            a=dims[kind].copy();a[0]=value
            yield kind,1,a+dims[1]+I+[0,0,0]+I+[4,0,0]+[1,0,0]
if __name__=='__main__':
    for i,(a,b,v) in enumerate(cases()): print(i,a,b,*map(word,v),sep='\t')
