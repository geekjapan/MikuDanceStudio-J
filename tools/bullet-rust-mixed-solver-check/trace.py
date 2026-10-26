"""Version 1 trace schema parser and schedule validation. All floats remain raw words."""
from collections import Counter
import struct
import re


def positive(word):
    return struct.unpack('!f', bytes.fromhex(word))[0] > 0


def records(path):
    with path.open() as stream:
        for number, line in enumerate(stream, 1):
            fields = line.rstrip('\n').split('\t')
            if len(fields) < 10:
                raise ValueError(f'{number}: incomplete header')
            case, step, kind, iteration, index = map(int, fields[:5])
            if re.fullmatch(r'(?:[0-9a-f]{8}\t)*[0-9a-f]{8}', '\t'.join(fields[5:])) is None:
                raise ValueError(f'{number}: invalid raw word')
            cursor = 5
            def count():
                nonlocal cursor
                n = int(fields[cursor], 16); cursor += 1
                return n
            def take(n):
                nonlocal cursor
                result = fields[cursor:cursor+n]; cursor += n
                if len(result) != n:
                    raise ValueError(f'{number}: truncated state')
                return result
            pool = [take(19) for _ in range(count())]
            groups = []
            for size in [29, 29, 29]:
                rows = [take(size) for _ in range(count())]
                for row in rows:
                    if any(int(w, 16) >= len(pool) for w in row[:2]):
                        raise ValueError(f'{number}: invalid solver body ID')
                groups.append(rows)
            bodies = [take(71) for _ in range(count())]
            originals = [int(b[0], 16) for b in pool if b[0] != 'ffffffff']
            if len(originals) != len(set(originals)) or any(i >= len(bodies) for i in originals):
                raise ValueError(f'{number}: duplicate or invalid original body')
            for i, b in enumerate(bodies):
                companion = int(b[0], 16)
                if companion != 0xffffffff and (companion >= len(pool) or int(pool[companion][0], 16) != i):
                    raise ValueError(f'{number}: companion mapping differs')
            points = [[take(29) for _ in range(count())] for _ in range(count())]
            for row in groups[1]:
                mi, pi = map(lambda w:int(w,16), row[23:25])
                if mi >= len(points) or pi >= len(points[mi]):
                    raise ValueError(f'{number}: invalid point mapping')
            if any(int(row[23],16) >= len(groups[1]) for row in groups[2]):
                raise ValueError(f'{number}: invalid friction mapping')
            if cursor != len(fields):
                raise ValueError(f'{number}: trailing words')
            yield (case, step, kind, iteration, index), pool, groups, bodies, points


def validate(path, cases=96):
    stream = iter(records(path)); counters = Counter(); events = 0
    def consume(expected):
        nonlocal events
        record = next(stream, None)
        if record is None or record[0] != expected:
            raise ValueError(f'event {events}: expected {expected}, got {None if record is None else record[0]}')
        events += 1; counters[f'event_{expected[2]}'] += 1
        return record
    for case in range(cases):
        for step in range(2):
            setup = consume((case, step, 0, -1, -1))
            _, pool, groups, bodies, points = setup
            nj, nn, nf = map(len, groups)
            # The corpus serializes one joint between adjacent non-ground bodies,
            # plus a free joint in the lazy-registration variants.
            variant = case % 48
            joints = 0 if variant == 0 else 1 if variant == 1 else len(bodies) - 2 + int(variant % 9 == 1)
            counters['empty_group'] += int(not pool)
            counters['normal_warmstart'] += sum(int(int(r[22],16) & 0x7fffffff != 0) for r in groups[1])
            counters['joint_impulse_reset'] += sum(r[22] == '00000000' for r in groups[0])
            for iteration in range(10):
                for index in range(nj):
                    consume((case, step, 1, iteration, index)); consume((case, step, 2, iteration, index))
                for index in range(joints):
                    before = consume((case, step, 7, iteration, index));after = consume((case, step, 8, iteration, index))
                    counters['lazy_callback_addition'] += int(len(after[1]) > len(before[1]))
                for index in range(nn):
                    consume((case, step, 3, iteration, index));consume((case, step, 4, iteration, index))
                for index in range(nf):
                    first = next(stream, None)
                    if first is None:
                        raise ValueError('truncated friction event')
                    header, _, state, _, _ = first
                    normal = state[1][int(state[2][index][23],16)]
                    kind = 5 if positive(normal[22]) else 9
                    if header != (case, step, kind, iteration, index):
                        raise ValueError(f'incorrect friction eligibility/order {header}')
                    events += 1; counters[f'event_{kind}'] += 1
                    if kind == 5:
                        friction = state[2][index]
                        counters['negative_friction'] += int(int(normal[25],16) >> 31 != 0)
                        counters['zero_friction'] += int(int(normal[25],16) & 0x7fffffff == 0)
                        counters['reversed_friction_bounds'] += int(positive(friction[20]))
                        consume((case, step, 6, iteration, index))
            for index in range(len(after[1]) if joints else len(pool)):
                consume((case, step, 11, -1, index))
                consume((case, step, 12, -1, index))
            final = consume((case, step, 10, -1, -1))
            counters['generated_nan_rows'] += sum(int(int(word,16)&0x7f800000 == 0x7f800000 and int(word,16)&0x7fffff != 0) for rows in final[2] for row in rows for word in row[:23])
            counters['fixed_nonzero_delta'] += int(bool(final[1]) and any(int(w,16)&0x7fffffff for w in final[1][0][7:13]))
            for initial_points, final_points in zip(points, final[4]):
                for initial, written in zip(initial_points, final_points):
                    # Solver may change only normal impulse and setup directions/flag.
                    if initial[:18] != written[:18] or initial[19:23] != written[19:23]:
                        raise ValueError('solver changed contact metadata or lateral impulses/lifetime')
    if next(stream,None) is not None:
        raise ValueError('trailing cases/events')
    counters['events'] = events
    required = ['empty_group','normal_warmstart','joint_impulse_reset','lazy_callback_addition','negative_friction','zero_friction','reversed_friction_bounds','fixed_nonzero_delta','event_9']
    missing = [name for name in required if not counters[name]]
    if missing:
        raise ValueError(f'corpus branch gaps: {missing}')
    return dict(counters)


def compare(left, right):
    with left.open('rb') as a, right.open('rb') as b:
        for number, (x, y) in enumerate(__import__('itertools').zip_longest(a,b),1):
            if x != y:
                if x is None or y is None:
                    return {'line':number,'reason':'missing line'}
                xx, yy = x.decode().strip().split('\t'), y.decode().strip().split('\t')
                for index,(u,v) in enumerate(__import__('itertools').zip_longest(xx,yy)):
                    if u != v:
                        return {'line':number,'event':xx[:5],'word':index,'left':u,'right':v}
    return None
