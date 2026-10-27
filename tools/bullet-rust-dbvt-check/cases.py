#!/usr/bin/env python3
import random


def bounds(r):
    a=[r.randrange(-20,21)/4 for _ in range(3)]
    return ' '.join(map(str,a+[x+r.randrange(1,13)/4 for x in a]))


for key in range(1,25):
    print('i',key,key,0,0,key+1,1,1)
print('t 2')
print('t 4')
print('t 8')
for key in range(1,25): print('r',key)
print('c')

for seed in range(12):
    r=random.Random(seed)
    live=[]
    for key in range(1,25):
        print('i',key,bounds(r))
        live.append(key)
    print('v -10 -10 -10 10 10 10')
    print('s')
    print('x')
    print('q -10 0 0 1 1e30 1e30 20 0 0 0 0 0 0')
    for step in range(64):
        key=r.choice(live)
        kind=r.randrange(9)
        if kind==0: print('u',key,bounds(r))
        elif kind==1: print('p',key,bounds(r),'1 -2 0 0.25')
        elif kind==2: print('e',key,r.choice([-1,0,1,3]))
        elif kind==3: print('n',r.choice([-1,0,1,3,40]))
        elif kind==4: print('t',128)
        elif kind==5: print('b')
        elif kind==6: print('v',bounds(r))
        elif kind==7: print('s')
        else:
            print('r',key)
            print('i',key,bounds(r))
        print('l',r.choice([-1,0,1,4]))
    for key in live: print('r',key)
    print('n -1')
    print('c')
print('i 1 0 0 0 1 1 1')
print('p 1 0 0 0 1 1 1 100 -100 0 2')
print('q -1 0 0 1 1e30 1e30 1 0 0 0 0 0 0')
print('q 1 0 0 1 1e30 1e30 2 0 0 0 0 0 0')
print('c')

print('h')
for key in range(1, 5): print('i', key, key - 1, 0, 0, key + 1, 2, 2)
print('h')
for key in range(1, 5): print('f', key)
print('g 1 0 0 3 2 2')
print('u 2 -4 -4 -4 4 4 4')
print('h')
print('f 2')
print('g -4 -4 -4 4 4 4')
print('b')
print('f 2')
print('t 2')
print('f 1')
print('r 2')
print('h')
print('f 3')
print('c')
print('h')
print('i 1 0 0 0 1 1 1')
print('f 1')
print('h')
print('c')
print('h')
