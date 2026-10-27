"""Every input is serialized before execution, including float words and endpoint order."""
import random
ONE = 1065353216
HALF = 1056964608
FAR = 1073741824

def corpus():
    rows = []
    def uf(n, commands):
        rows.append(f'{len(rows)} U {n} {len(commands)} ' + ' '.join(commands))
    def world(objects, pairs=(), constraints=(), manifolds=(), split=1, mode=1):
        def flat(xs): return ' '.join(str(x) for xs0 in xs for x in xs0)
        pairs=[tuple(sorted(p)) for p in pairs]
        rows.append(f'{len(rows)} W {len(objects)} {split} {mode} {flat(objects)} {len(pairs)} {flat(pairs)} {len(constraints)} {flat(constraints)} {len(manifolds)} {flat(manifolds)}')
    def obj(state=1, flags=0, response=1, time=HALF, tag=73, comp=29, hit=HALF):
        return (state,flags,response,time,tag,comp,hit)
    uf(0, ['S'])
    uf(1, ['F 0','J 0 0','S'])
    uf(9, ['J 0 1','J 1 2','J 2 3','J 3 4','J 4 5','J 5 6','J 6 7','J 7 8','F 0','F 1','F 0','S'])
    uf(8, ['J 0 1','J 1 2','J 3 4','J 2 4','J 5 6','J 6 7','J 4 7','S'])
    for n in (2,3,4,5,7,8,15,16,31):
        uf(n, [f'J {i} {n-1}' for i in range(n-1)]+['S'])
    for mode in (0,1):
        world([], mode=mode)
        for split in (0,1):
            for state in range(6):
                for flags in range(4):
                    world([obj(state,flags),obj(2)], [(0,1)], [(0,1,1,0)], [(0,1,0,0)], split,mode)
            for s in range(6):
                for t in range(6):
                    world([obj(s),obj(t)], [(0,1)], (), [(0,1,0,0)],split,mode)
                    world([obj(s),obj(t)], (), [(0,1,0,1)], [(1,0,1,FAR)],split,mode)
            for flags in (1,2,3):
                for state in range(6):
                    for response in (0,1):
                        world([obj(2),obj(state,flags,response),obj(2)], (), (), [(0,1,0,0),(1,2,0,0)],split,mode)
            # Equal-root swaps, unsorted dispatcher/constraint arrays and body0 key.
            world([obj(),obj(),obj(),obj(1,1),obj(2),obj(5)], [(2,0),(0,1)], [(1,3,1,1),(0,3,0,0),(2,3,1,0),(5,4,1,0)], [(1,3,0,0),(3,2,1,FAR),(0,3,0,0),(5,4,0,0)],split,mode)
            # Skipped group owns a manifold; a later active group must advance past it.
            world([obj(1),obj(5),obj(1),obj(1)],[(0,1),(2,3)],(),[(0,1,0,0),(2,3,0,0)],split,mode)
            # Pair merge guards independent of constraint guards.
            for side in (0,1):
                for flags in range(4):
                    for response in (0,1):
                        os=[obj(),obj()]; os[side]=obj(1,flags,response)
                        world(os,[(1,0)],(),[(0,1,0,0)],split,mode)
    for n in (127,128,129):
        for mode in (0,1):
            for split in (0,1):
                world([obj() for _ in range(n)],[(i,i+1) for i in range(n-1)],[(i,n-1,1,0) for i in range(n-1)],[(i,n-1,0,0) for i in range(n-1)],split,mode)
                world([obj() for _ in range(n*2)],[(i*2,i*2+1) for i in range(n)],(),[(i*2,i*2+1,0,0) for i in range(n)],split,mode)
    for word in (0,0x80000000,0x7fc12345,0x7f800000,0xff800000):
        world([obj(2,time=word,hit=word),obj(5,2,0,time=word,hit=word)],(),(),[(1,0,0,0)],mode=1)
    compact=len(rows)
    rng=random.Random(275)
    for _ in range(250):
        n=rng.randrange(2,40)
        objects=[obj(rng.randrange(6),rng.randrange(4),rng.randrange(2),rng.choice([0,HALF,ONE,0x80000000,0x7fc12345])) for _ in range(n)]
        pairs=[]
        for _ in range(n*2):
            a,b=rng.sample(range(n),2)
            if (a,b) not in pairs and (b,a) not in pairs: pairs.append((a,b))
        constraints=[(*rng.sample(range(n),2),rng.randrange(2),rng.randrange(2)) for _ in range(n)]
        manifolds=[(*rng.sample(range(n),2),rng.randrange(2),rng.choice([0,FAR])) for _ in range(n)]
        world(objects,pairs,constraints,manifolds,rng.randrange(2),rng.randrange(2))
    return ('\n'.join(rows)+'\n').encode(),compact,len(rows)
