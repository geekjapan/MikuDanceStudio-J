#!/usr/bin/env python3
"""Finite directed capsule pairs and lifecycle traces; all values become f32 bits."""
import importlib.util
from pathlib import Path
import math
import random
import struct
spec = importlib.util.spec_from_file_location('boxes', Path(__file__).parents[1] / 'bullet-rust-box-box-check/cases.py')
boxes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boxes)
pose, words = boxes.pose, boxes.words

def new(a, b):
    print('N 0', words([*a, *b]))

def step(a, b):
    print('T', words([*a, .7, .3, *b, .6, .4]))

def main():
    for a, b in [((1,2),(1,2)), ((.3,0),(.8,0)), ((.25,6),(.9,.5))]:
        for angle in [(0,0,0),(3.141592653589793,0,0),(.7,.3,.5),(1.5707963267948966,0,0)]:
            for reverse in (False, True):
                new(b if reverse else a, a if reverse else b)
                for xyz in [(0,0,0),(.1,0,0),(0,4,0),(.1,-5,.1),(0,0,0),(3,0,0),(.1,.02,0),(.1,.02,0)]:
                    pa,pb=pose(),pose(xyz,angle)
                    step(pb if reverse else pa, pa if reverse else pb)
                    if xyz==(.1,0,0): print('J')
                print('R')
    # Exact tangent branches use orthonormal signed permutation bases.
    z_axis=[0,0,0, 1,0,0, 0,0,-1, 0,1,0]
    antiparallel=[0,0,0, 1,0,0, 0,-1,0, 0,0,-1]
    new((.5,2),(.7,3));step(pose(),antiparallel)
    for p in [pose(),z_axis]:
        new((.5,2),(.7,3));step(p,p);print('J');step(p,p)
    for translation in [(10000,20000,-30000),(-1e5,1e5,1e5)]:
        new((1,4),(.5,2))
        for delta in [(1,0,0),(1,.1,.1),(4,0,0),(1,0,0)]:
            step(pose(translation),pose([a+b for a,b in zip(translation,delta)]))
    f32=lambda v: struct.unpack('<f',struct.pack('<f',v))[0]
    h=f32(50+f32(.04));r=f32(.04)
    threshold=f32(f32(math.sqrt(f32(f32(r*r+h*h)+r*r)))*f32(.02))
    center=struct.unpack('<I',struct.pack('<f',threshold))[0]
    for bits in [center-1,center,center+1]:
        new((0,100),(0,100));step(pose(),pose((struct.unpack('<f',struct.pack('<I',bits))[0],0,0)))
    rng=random.Random(275)
    for i in range(400):
        a=(rng.uniform(.1,1),rng.uniform(0,5));b=(rng.uniform(.1,1),rng.uniform(0,5))
        pa=pose([rng.uniform(-1,1) for _ in range(3)],[rng.uniform(-3,3) for _ in range(3)])
        pb=pose([rng.uniform(-2,2) for _ in range(3)],[rng.uniform(-3,3) for _ in range(3)])
        new(a,b);step(pa,pb)
        if i%5==0: print('J');step(pa,pb)

if __name__=='__main__': main()
