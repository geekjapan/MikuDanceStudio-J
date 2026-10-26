#!/usr/bin/env python3
"""Deterministic operation streams; live proxy UIDs remain stable and unique."""
import random

pairs = []
states = [[i + 1, 1, -1] for i in range(48)]

def emit(op, *args):
    print(op, *args)
    if op == 's':
        a, uid, group, mask = args
        assert all(a not in p for p in pairs)
        states[a] = [uid, group, mask]
    if op in ('a', 'r'):
        a, b = args
        p = tuple(sorted((a, b), key=lambda k: states[k][0]))
        if op == 'a':
            if states[a][1] & states[b][2] and states[b][1] & states[a][2] and p not in pairs:
                pairs.append(p)
        elif p in pairs:
            i = pairs.index(p)
            pairs[i] = pairs[-1]
            pairs.pop()
    if op in ('p', 'v'):
        i = 0
        while i < len(pairs):
            if (args[0] in pairs[i] if op == 'p' else sum(pairs[i]) % args[0] == 0):
                pairs[i] = pairs[-1]
                pairs.pop()
            else:
                i += 1

emit('f', 0, 1)
emit('r', 0, 1)
emit('v', 1)
emit('a', 1, 0)
emit('t', 0, 11, 0)
emit('a', 0, 1)
# Update filters while the pair lives: add filters first; find/remove do not.
print('s', 0, 1, 0, 0)
old = states[0]
states[0] = [1, 0, 0]
emit('a', 1, 0)
emit('f', 1, 0)
emit('r', 1, 0)
emit('s', 0, *old)
# Force collisions and multiple doublings, then remove head/middle/tail slots.
for a in range(12):
    for b in range(a + 1, 12):
        emit('a', a, b)
        if (a + b) % 4 == 0:
            emit('t', len(pairs)-1, 100 + a*12+b, a*12+b)
for index in (0, 7, -1, 3, 10):
    emit('r', *pairs[index])
emit('v', 3)
emit('x', 4)
emit('p', 4)
emit('v', 1)
# Signed hash shifts, UID high bits, and short sign extension.
uids = [-2147483648, -1, 0, 32767, 32768, 65535, 65536, 2147483647]
for i, uid in enumerate(uids):
    emit('s', i, uid, -32768 if i % 2 else -1, -1)
for a in range(8):
    for b in range(a+1,8):
        emit('a', b, a)
        emit('f', a, b)
emit('t', 0, 777, 123456)
emit('c', 0)
emit('c', 0)
emit('x', 3)
emit('p', 7)
emit('v', 2)
emit('v', 1)
# Both directions must match, including bit 15 in the signed mask.
emit('s', 10, 510, -32768, -32768)
emit('s', 11, 511, -32768, -32768)
emit('s', 12, 512, 1, -32768)
emit('s', 13, 513, -32768, 1)
emit('a', 10, 11)
emit('a', 10, 12)
emit('a', 12, 13)
emit('a', 11, 13)
emit('v', 1)
# Recycle a UID at a different proxy identity only after removal.
emit('s', 0, 900, 1, -1)
emit('s', 1, 901, 1, -1)
emit('a', 0, 1)
emit('r', 0, 1)
emit('s', 0, 902, 1, -1)
emit('s', 2, 900, 1, -1)
emit('a', 2, 1)
emit('p', 0)
emit('p', 2)
# Direct constructor tie retains the native strict-less-than rule.
emit('s', 20, 1234, 1, -1)
emit('s', 21, 1234, 1, -1)
emit('q', 20, 21)
emit('q', 21, 20)
for i in range(48):
    emit('s', i, i+1, 1, -1)
for seed in range(32):
    emit('v', 1)
    rng = random.Random(seed)
    for step in range(64):
        a, b = rng.sample(range(16), 2)
        op = rng.choice(('a','a','a','f','r','p','v','x','t','c'))
        if op in ('a','f','r'):
            emit(op,a,b)
        elif op in ('p','x'):
            emit(op,a)
        elif op == 'v':
            emit(op,rng.randrange(2,7))
        elif pairs:
            index = rng.randrange(len(pairs))
            emit(op,index,1000+seed*64+step, rng.randrange(100000)) if op == 't' else emit(op,index)
        else:
            emit('f',a,b)
emit('v',1)
