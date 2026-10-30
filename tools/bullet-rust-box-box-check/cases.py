#!/usr/bin/env python3
"""Deterministic box pairs and persistent collision traces."""
import math
import random
import struct


def words(values):
    return ' '.join(f'{struct.unpack("<I", struct.pack("<f", v))[0]:08x}' for v in values)


def pose(origin=(0, 0, 0), angles=(0, 0, 0)):
    x, y, z = angles
    a, b, c = math.cos(x), math.cos(y), math.cos(z)
    d, e, f = math.sin(x), math.sin(y), math.sin(z)
    return [*origin, b*c, d*e*c-a*f, a*e*c+d*f,
            b*f, d*e*f+a*c, a*e*f-d*c, -e, d*b, a*b]


def new(a, b, borrowed=0):
    print('N', borrowed, words([*a, *b]))


def step(a, b):
    print('T', words([*a, .7, .3, *b, .6, .4]))


def main():
    rng = random.Random(275)
    for borrowed in (0, 1):
        for scale in (.001, .02, .04, 1, 1000):
            new([scale]*3, [scale]*3, borrowed)
            for x in (3, 2, 1.99, 1.9, 1.9, 2.001, 2.1, 3, 1.9):
                step(pose(), pose((x*scale, 0, 0)))
                if x == 1.99:
                    print('J')
            print('R')
        new((1, 1, 1), (1, 1, 1), borrowed)
        for i in range(80):
            step(pose(), pose((i*.001, 1.8 if i < 60 else 3, 0), (0, i*.013, 0)))
            if i in (0, 30):
                print('J')
    for borrowed in (0, 1):
        for rotation in (0, 1e-7, .7853981633974483):
            for swapped in (False, True):
                new((1, 1, 1), (1, 1, 1), borrowed)
                for x in (1.8, 1.8, 2, 2.01, 2.034, 2.035, 2.05, 1.8):
                    pa, pb = pose(), pose((x, 0, 0), (rotation, 0, 0))
                    step(pb if swapped else pa, pa if swapped else pb)
                    if x == 1.8:
                        print('J')
                print('R')
        for thickness in (1e-6, .001, .039999999, .04):
            new((2, thickness, .1), (2, thickness, .1), borrowed)
            for angle in (0, 1e-7, .1, 1.5):
                step(pose(), pose((.01, thickness, 0), (0, angle, .001)))
    for index in range(4000):
        scale = rng.choice((.001, .03, .04, .1, 1, 10, 1000))
        a = [scale*rng.uniform(.05, 2) for _ in range(3)]
        b = [scale*rng.uniform(.05, 2) for _ in range(3)]
        pa = pose([scale*rng.uniform(-1, 1) for _ in range(3)], [rng.uniform(-3, 3) for _ in range(3)])
        pb = pose([scale*rng.uniform(-2, 2) for _ in range(3)], [rng.uniform(-3, 3) for _ in range(3)])
        if index % 10 == 0:
            pb = pose([scale*rng.uniform(-1, 1) for _ in range(3)], (0, 1e-6, 0))
            pa = pose()
        new(a, b)
        step(pa, pb)
        if index % 5 == 0:
            print('J')
            step(pa, pb)
        if index % 8 == 0:
            new(b, a)
            step(pb, pa)


if __name__ == '__main__':
    main()
