#!/usr/bin/env python3
"""Deterministic raw IEEE inputs. Directed cases precede the seeded tail."""
import struct
import random

def bits(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]

def generate():
    directions = [(0, 0, 0), (0x80000000,)*3]
    for axis in range(3):
        for w in [bits(1), bits(-1), bits(.01)-1, bits(.01), bits(.01)+1,
                  bits(2**-23)-1, bits(2**-23), bits(2**-23)+1, 1,
                  bits(1e19), bits(1e30), 0x7f800000, 0xff800000, 0x7fc00001]:
            d=[0,0,0];d[axis]=w;directions.append(tuple(d))
    for x in [-1,1]:
        for y in [-1,1]:
            for z in [-1,1]: directions.append(tuple(map(bits,(x,y,z))))
    directions += [tuple(map(bits,d)) for d in [(1,2,3),(1e-4, .01,1e-8),(1e10,1,3),(.003,.004,.008660254)]]
    directions += [(0x33dd090e, 0x2f9c55ca, 0x338125ad)]
    directions += [
        (0x3bc5888e, 0x3bd73d17, 0x3b946a46),
        (0x3bc58890, 0x3bd73d17, 0x3b946a46),
        (0x3bf1c179, 0x3b8b7641, 0x3babb194),
        (0x3352bac2, 0x33a3036b, 0x33a6ea78),
        (0x3352bac4, 0x33a3036b, 0x33a6ea78),
        (0x339ccb23, 0x339fa4f5, 0x3378b872),
    ]
    dimensions=[(1,2,3),(0,0,0),(-1,-2,-3),(.04,.08,.04),(1e-30,1e-30,1e-30),(1e20,1e20,1e20),(-1e20,-1e20,-1e20)]
    # The first 1600 cases retain all directed inputs and a seeded prefix.
    for dim in dimensions[:3]:
        for kind in range(3):
            for d in directions: yield kind,tuple(map(bits,dim))+d
    for dim in dimensions[3:]:
        for kind in range(3):
            for d in directions: yield kind,tuple(map(bits,dim))+d
    for kind in range(3):
        for axis in range(3):
            for w in [0x7fc00001,0x7f800000,0xff800000,0x80000000]:
                dim=list(map(bits,(1,2,3)));dim[axis]=w
                yield kind,tuple(dim)+tuple(map(bits,(1,2,3)))
    for kind in range(3):
        for delta in [-1, 1]:
            for axis in range(3):
                d=[0,0,0]; d[axis]=bits(1)
                yield kind,(bits(.04)+delta,)*3+tuple(d)
    rng=random.Random(275)
    for _ in range(2000):
        yield rng.randrange(3),tuple(bits(rng.uniform(-5,5)) for _ in range(6))

if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(newline='\n')
    for i,(kind,words) in enumerate(generate()):
        print(i,kind,*(f'{w:08x}' for w in words),sep='\t')
