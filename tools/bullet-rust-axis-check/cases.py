#!/usr/bin/env python3
"""Finite ordered AABBs, live handles, deterministic allocation and mixed streams."""
import random
import struct

live = []
freed = []
next_id = 1
capacity = 16


def bits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def floats(values):
    return [bits(v) for v in values]


def emit(op, *args):
    global next_id
    print(op, *args)
    if op == 'z' and not live:
        freed.clear()
        next_id = 1


def remove(key):
    emit('r', key)
    live.remove(key)
    freed.append(key)


def new(cap=16, lo=-10000, hi=10000):
    global next_id, capacity
    for key in list(live):
        remove(key)
    capacity = cap
    live.clear()
    freed.clear()
    next_id = 1
    emit('n', cap, *floats([lo]*3), *floats([hi]*3))


def add(lo, hi=None, group=1, mask=-1):
    global next_id
    assert len(live) < capacity
    key = freed.pop() if freed else next_id
    if key == next_id:
        next_id += 1
    live.append(key)
    emit('a', key*17, group, mask, key*31, *floats(lo), *floats(lo if hi is None else hi))
    return key


def update(key, lo, hi=None):
    assert key in live
    emit('u', key, *floats(lo), *floats(lo if hi is None else hi))


new(1500000)
emit('p')
emit('z')
new(3)
for _ in range(3):
    add([0]*3)
emit('q', 1, 3)
emit('t', 0, 701, 12345)
emit('t', 1, 702, 0)
emit('t', 2, 703, 999)
emit('p')
emit('z')
remove(2)
remove(1)
add([0]*3)
add([0]*3)
for key in list(live):
    remove(key)
emit('z')
add([1]*3)
new(2)
add([-1]*3, [1]*3)
add([1]*3, [2]*3)
emit('q', 1, 2)
update(2, [1.000001]*3, [2]*3)
emit('q', 1, 2)
update(2, [1]*3, [2]*3)
emit('t', 0, 800, 444)
emit('c', 0)
emit('c', 0)
emit('t', 0, 801, 445)
update(2, [9]*3, [10]*3)
new()
add([-1]*3, [1]*3)
add([-1]*3, [1]*3)
for axis in range(3):
    lo, hi = [-1]*3, [1]*3
    lo[axis], hi[axis] = 3, 4
    update(2, lo, hi)
    emit('q', 1, 2)
    lo[axis], hi[axis] = -3, 4
    update(2, lo, hi)
    lo[axis], hi[axis] = -4, -3
    update(2, lo, hi)
    update(2, [-1]*3, [1]*3)
update(1, [-8,-7,-6], [-5,-4,-3])
update(1, [5,4,3], [8,7,6])
update(1, [-1]*3, [1]*3)
for _ in range(4):
    update(1, [-1]*3, [1]*3)
new()
for group, mask in ((1,-1),(0,-1),(2,2),(-32768,-32768),(-32768,1),(1,-32768)):
    add([0]*3, group=group, mask=mask)
for a in live:
    for b in live:
        emit('q', a, b)
new()
values = [-3.4e38,-20000,-10000.0009765625,-10000,-9999.9990234375,-0.000001,0,0.000001,9999.9990234375,10000,10000.0009765625,20000,3.4e38]
for v in values:
    add([v]*3)
for key in live:
    update(key, [0]*3)
for key, v in zip(live, reversed(values)):
    update(key, [v]*3)
new(4, -1, 1)
add([-1]*3, [1]*3)
add([-1.0000001192092896]*3, [1.0000001192092896]*3)
add([-0.9999999403953552]*3, [0.9999999403953552]*3)
add([-3.4e38]*3, [3.4e38]*3)
for seed in range(32):
    new(12)
    rng = random.Random(seed)
    for step in range(128):
        op = rng.choice(['a','a','u','u','r','q','p','z'])
        coords = [rng.choice([-20000,-10000,-10,-1,0,0,1,10,10000,20000]) for _ in range(3)]
        hi = [v+rng.choice([0,0,1,2,20000]) for v in coords]
        if op == 'a' and len(live) < capacity:
            add(coords, hi, group=rng.choice([1,2,0,-32768,-1]), mask=rng.choice([-1,1,2,-32768]))
        elif op == 'u' and live:
            update(rng.choice(live), coords, hi)
        elif op == 'r' and live:
            remove(rng.choice(live))
        elif op == 'q' and live:
            emit('q', rng.choice(live), rng.choice(live))
        elif op == 'z':
            emit('z')
        else:
            emit('p')
        if step % 13 == 0:
            emit('b', 100000 + seed*128*128 + step*128)
for key in list(live):
    remove(key)
emit('z')
