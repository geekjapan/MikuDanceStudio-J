#!/usr/bin/env python3
"""Deterministic geometry and direct manifold traces, encoded as binary32 words."""
import math
import random
import struct


def word(x):
    return f'{struct.unpack("<I", struct.pack("<f", x))[0]:08x}'


def emit(op, values=(), tail=()):
    print(op, *(word(x) for x in values), *tail, sep='\t')


def shape(kind, dims):
    return '\t'.join([str(kind), *(word(x) for x in (list(dims) + [0]*4)[:4])])


def new(a, b):
    print('N', shape(*a), shape(*b), sep='\t')


def transform(origin=(0, 0, 0), rotation=(0, 0, 0, 1)):
    return [*origin, *rotation]


def body(origin=(0, 0, 0), rotation=(0, 0, 0, 1), friction=.5, restitution=.25):
    return [*transform(origin, rotation), friction, restitution]


def point(a, depth=-.1, impulse=0, lifetime=0):
    # World positions are initialized for direct cache operations too.
    emit('I', [*a, *a, *a, *a, 0, 1, 0, depth, .25, .125, impulse, impulse+1, impulse+2], [lifetime])


def main():
    rng = random.Random(275)
    sphere=(0,[.5]); plane=(3,[0,1,0,0]); box=(1,[.5,.7,.3]); capsule=(2,[.3,.8])
    for k,d in [sphere,box,capsule,(2,[.03,0]),(1,[.001,-.01,.02]),(0,[-.1]),(0,[0]),(2,[.2,-.3])]:
        for direction in [(0,0,0),(-0.,0.,-0.),(1,0,0),(0,-1,0),(1e-9,-1e-9,0),(.01,.01,0),(.3,-.4,.7)]:
            print('S',shape(k,d),*(word(x) for x in direction),sep='\t')
    for radius in [.5, .001, 0., -.01]:
        new((0,[radius]),sphere)
        for distance in [0.,1e-8,2**-23,2**-22,radius+.5,radius+.5+1e-7,radius+.5-1e-7,.2,.201,.205,2.,.2]:
            emit('T',body((distance,0,0),friction=30)+body(friction=-.5))
    new((0,[.7]),(0,[.3]))
    for xyz in [(0,0,0),(.1,.2,.3),(-.1,-.2,-.3),(1e-8,2e-8,-3e-8),(.31,.52,-.17),(2,0,0)]:
        emit('T',body(xyz,(.1,.2,.3,math.sqrt(.86)),friction=30,restitution=.8)+body(rotation=(.3,-.1,0,math.sqrt(.9)),friction=.7,restitution=.4))
    for convex in [sphere,box,capsule,(2,[.03,0]),(2,[0,0]),(1,[.001,-.01,.02]),(0,[-.01])]:
        for swapped in [False,True]:
            for p in [plane,(3,[.3,.7,.8,.13]),(3,[0,0,1,-.2])]:
                new(p if swapped else convex,convex if swapped else p)
                for i,y in enumerate([2.,.7,.5,.49,.48,.4,.399,.405,1.5,.1,-.1]):
                    angle=i*.033
                    cb=body((.003*i,y,-.002*i),(0,0,math.sin(angle),math.cos(angle)),friction=-30,restitution=-.5)
                    pb=body((.001*i,.002*i,0),(math.sin(angle*.2),0,0,math.cos(angle*.2)),friction=.7,restitution=.8)
                    emit('T',pb+cb if swapped else cb+pb)
    # Threshold equality, stale contacts and perturbation at a box corner.
    for swapped in [False,True]:
        new(plane if swapped else box,box if swapped else plane)
        threshold=math.sqrt(1+1.4**2+.6**2)*.5*.02
        for y in [.7+threshold, .7+threshold-1e-7, .7+threshold+1e-7,.69,.69,2.,.69]:
            cb=body((0,y,0));pb=body()
            emit('T',pb+cb if swapped else cb+pb)
    # Negative raw radius makes the perturbation alone cross the contact threshold.
    for swapped in [False, True]:
        convex = (0, [-.01])
        new(plane if swapped else convex, convex if swapped else plane)
        cb = body((0, -.0095, 0)); pb = body()
        emit('T', pb+cb if swapped else cb+pb)
    # Random finite rotations, dimensions and moving tilted planes.
    for _ in range(60):
        convex=rng.choice([sphere,box,capsule])
        swapped=rng.choice([False,True]);new(plane if swapped else convex,convex if swapped else plane)
        for frame in range(6):
            axis=[rng.uniform(-1,1) for _ in range(3)];norm=math.sqrt(sum(x*x for x in axis));ang=rng.uniform(-.5,.5)
            q=[x/norm*math.sin(ang) for x in axis]+[math.cos(ang)]
            cb=body((rng.uniform(-.02,.02),rng.uniform(-.5,.8),rng.uniform(-.02,.02)),q)
            pb=body((0,.001*frame,0),(.03,0,0,math.sqrt(1-.03**2)))
            emit('T',pb+cb if swapped else cb+pb)
    # Exhaust replacement candidates, including nonzero impulses and lifetimes.
    for _ in range(160):
        emit('C',[.02])
        for i in range(5):
            point([rng.randint(-6,6)*.1 for _ in range(3)],rng.choice([-.1,-.2,-.3]),i*.25,i+7)
        emit('D',tail=[1])
        emit('R',transform()+transform())
    # Earliest equal area, nearest ties, strict distance, and replacement retention.
    emit('C',[.25])
    for i,x in enumerate([0.,1.,2.,3.,4.]):point((x,0,0),-.1,i+1,i+20)
    emit('C',[.25])
    for i,x in enumerate([0.,.5,.25,.24999999,0.]):point((x,0,0),-.1,i+1,i+20)
    emit('D',tail=[0]);emit('R',transform()+transform((.251,0,0)))
    # Reverse refresh removal and tangential equality.
    for drift in [.02,.020000001,.019999999]:
        emit('C',[.02])
        for i in range(4):point((i*.2,0,0),-.1,i,i+1)
        emit('R',transform()+transform((drift,0,0)))


if __name__ == '__main__':
    main()
