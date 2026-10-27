#!/usr/bin/env python3
"""Deterministic complete activation traces, directed prefix then seeded sequences."""
import random
import struct


def word(value):
    return struct.pack('>f', value).hex()


def corpus():
    scenarios = []
    host_specific = []

    def add(*ops, host_specific_arithmetic=False):
        target = host_specific if host_specific_arithmetic else scenarios
        target.append(['reset', *ops])

    def velocities(linear=0.0, angular=0.0):
        return 'velocities ' + ' '.join(map(word, [linear, -0.0, 0.0, angular, 0.0, -0.0]))

    for state in range(6):
        for target in range(6):
            add(f'force {state}', 'time 40400000', f'set {target}', f'force {target}')
        for flags in [0, 1, 2, 3, 4, 7]:
            for force in [0, 1]:
                add(f'force {state}', f'flags {flags}', 'time 80000000', f'activate {force}')
        for linear, angular in [(0, 0), (0.8, 0), (0, 1), (0.8000000715255737, 0),
                                (0.7999999523162842, 0), (0, 0.9999999403953552),
                                (-0.8, 0), (0, -1), (float('inf'), 0), (float('nan'), 0),
                                (0, float('nan')), (1e-30, -1e-30)]:
            for op in ['update', 'world']:
                add(f'force {state}', 'time 40000000', velocities(linear, angular),
                    op + ' 3e800000', 'query', 'activate 0', 'world 00000000')
        for time in ['00000000', '80000000', '3fffffff', '40000000', '40000001',
                     'bf800000', '7f800000', 'ff800000', '7fc12345']:
            for dt in ['00000000', '80000000', '3e800000', 'bf800000', '7f800000', '7fc12345']:
                add(f'force {state}', f'time {time}', f'update {dt}', 'query', 'world 00000000',
                    host_specific_arithmetic=time == 'ff800000' and dt == '7f800000')
        for flags in [0, 1, 2, 3]:
            for setting in ['40000000 0', '00000000 0', '80000000 0', '40000000 1',
                            'bf800000 0', '7f800000 0', '7fc12345 0']:
                add(f'force {state}', f'flags {flags}', 'settings ' + setting, 'time 40400000',
                    velocities(0.1, 0.2), 'world 00000000', 'world 3e800000')
        for threshold in [0.0, -0.8, float('inf'), float('nan'), 1e-30]:
            add(f'force {state}', 'thresholds ' + word(threshold) + ' ' + word(threshold),
                velocities(0.1, 0.1), 'time 40400000', 'update 3e800000', 'world 00000000')
    add('velocities 80000000 00000000 80000000 00000000 80000000 00000000',
        'world 40000000', 'world 00000000', 'world 34000000', 'force 2',
        velocities(3, 4), 'world 3e800000', 'activate 0', 'world 3e800000')
    for state in range(6):
        for value in ['7fc12345', 'ffc54321', '7f812345', 'ff854321', '7f7fffff', 'ff7fffff']:
            add(f'force {state}', 'time ' + value, 'update 00000000', 'update ' + value,
                'thresholds ' + value + ' ' + value,
                'velocities ' + ' '.join([value] * 6), 'world 3e800000')
        for vector in ['3ecccccd 3ecccccd 3ecccccd', '00000000 3f4ccccd 00000000',
                       '00000000 00000000 3f4ccccd', '3ef5c28f 3f23d70a 00000000']:
            add(f'force {state}', 'time 40400000',
                'velocities ' + vector + ' 00000000 00000000 00000000', 'update 3e800000')
    compact_rows = sum(map(len, scenarios))
    scenarios.extend(host_specific)
    rng = random.Random(27520261027)
    floats = [word(x) for x in [0.0, -0.0, 0.1, -1, 0.8, 1, 2, 3, 1e-30,
                               float('inf'), float('-inf'), float('nan')]]
    for _ in range(400):
        ops = []
        for _ in range(40):
            op = rng.randrange(10)
            if op < 2:
                ops.append(('force ' if op == 0 else 'set ') + str(rng.randrange(6)))
            elif op == 2: ops.append('flags ' + str(rng.randrange(8)))
            elif op == 3: ops.append('activate ' + str(rng.randrange(2)))
            elif op == 4: ops.append('velocities ' + ' '.join(rng.choices(floats, k=6)))
            elif op == 5: ops.append('thresholds ' + ' '.join(rng.choices(floats, k=2)))
            elif op == 6: ops.append('time ' + rng.choice(floats))
            elif op == 7: ops.append('settings ' + rng.choice(floats) + ' ' + str(rng.randrange(2)))
            else: ops.append(('update ' if op == 8 else 'world ') + rng.choice(floats))
        add(*ops)
    lines = [f'{i}.{j}\t{op}\n' for i, scenario in enumerate(scenarios) for j, op in enumerate(scenario)]
    return ''.join(lines).encode(), compact_rows, len(scenarios)


if __name__ == '__main__':
    import sys
    sys.stdout.buffer.write(corpus()[0])
