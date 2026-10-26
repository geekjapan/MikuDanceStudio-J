#!/usr/bin/env python3
"""Complete outer-query and persistent mixed-pair scenarios, compact prefix."""
import math
from pathlib import Path
import importlib.util
spec=importlib.util.spec_from_file_location('kernel_cases',Path(__file__).resolve().parent.parent/'bullet-rust-gjk-epa-check/cases.py')
kernel=importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)
kernel_cases,word,I,rotation=kernel.cases,kernel.word,kernel.I,kernel.rotation
COMPACT = 1800

def cases():
    # Seeded solver's very first support exits before adding a vertex.
    yield 0,1,1,[.75,0,0,.8,.6,1.1]+I+[0,0,0]+I+[0,-1e10,0]+[0,.5,.7,.2,.3]
    for ka,kb,v in kernel_cases():
        if ka!=kb and any(not math.isfinite(x) for x in v):
            yield ka,kb,1,v[:30]+[1e18,.5,.7,.2,.3]
    dims=[[.75,0,0],[.8,.6,1.1],[.45,1.4,0]]
    for ka,kb in [(0,1),(1,0),(0,2),(2,0),(1,2),(2,1)]:
        for common in [0,10000]:
            for i,d in enumerate([1,.999,.998,.999,1.02,1.03,4,6,4,1,.99,.995]):
                yield ka,kb,int(i==0),dims[ka]+dims[kb]+rotation(i*.003)+[common]*3+rotation(-i*.002)+[common+d,common+.13,common]+[0 if i%2 else 1e18,.5+i*.01,.7,.2,.3+i*.01]
    import struct
    def adjacent(value, delta):
        bits=struct.unpack('<I',struct.pack('<f',value))[0]
        return struct.unpack('<f',struct.pack('<I',bits+delta))[0]
    def f(value): return struct.unpack('<f',struct.pack('<f',value))[0]
    def threshold(extents):
        d=[f(2*x) for x in extents]
        return f(f(f(math.sqrt(f(f(d[0]*d[0]+d[1]*d[1])+d[2]*d[2])))*.5)*f(.02))
    found=0
    for i in range(10,100000):
        radius=f(i/10000)
        t=threshold([radius]*3)
        if struct.unpack('<I',struct.pack('<f',t))[0]&255:continue
        for delta in range(-3,4):
            for reverse in [False,True]:
                a,b=[radius,0,0],[2,2,2]
                if reverse:a,b=b,a
                yield int(reverse),int(not reverse),1,a+b+I+[0,0,0]+I+[adjacent(radius+2+t,delta),0,0]+[1e18,.5,.7,.2,.3]
        found+=1
        if found==20:break
    # Threshold rounding changes a first-support early exit against shared witnesses.
    margins=[f(.75),f(.04),f(.45)]
    thresholds=[threshold([.75]*3),threshold([.8,.6,1.1]),threshold([.45,1.15,.45])]
    for ka,kb in [(0,1),(1,0),(0,2),(2,0),(1,2),(2,1)]:
        t=min(thresholds[ka],thresholds[kb])
        total=margins[kb]+(t+margins[ka])
        native=f(total*total)
        total_float=f(margins[kb]+f(t+margins[ka]));changed=f(total_float*total_float)
        for bound in [native,changed]:
            limit=f(math.sqrt(f(f(1e18)*bound)))
            for delta in range(-3,4):
                yield ka,kb,1,dims[ka]+dims[kb]+I+[0,0,0]+I+[0,-adjacent(limit,delta),0]+[0,.5,.7,.2,.3]
    for ka,kb,v in kernel_cases():
        if ka==kb or any(not math.isfinite(x) for x in v): continue
        yield ka,kb,1,v[:30]+[1e18,.5,.7,.2,.3]
if __name__=='__main__':
    for i,(a,b,new,v) in enumerate(cases()): print(i,a,b,new,*map(word,v),sep='\t')
