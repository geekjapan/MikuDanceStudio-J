"""Deterministic dispatcher command corpus. Float transport is raw binary32."""
import struct


def word(value):
    return struct.pack('>f', value).hex()


def corpus():
    lines = []
    def add(*parts): lines.append(' '.join(map(str, parts)))
    def body(i, shape, xyz=(0, 0, 0), state=1, flags=0, threshold=1e18):
        add('N', i, shape, *map(word, xyz), state, flags, word(threshold))
    for a in range(4):
        for b in range(4):
            add('F')
            body(0, a)
            body(1, b, (0.25, 0.5, 0.125))
            add('P', 0, 1)
            add('D')
            add('D')
            add('T', 1, *map(word, (10, 10, 10)))
            add('D')
            add('T', 1, *map(word, (0.25, 0.5, 0.125)))
            add('D')
    for state0 in range(6):
        for state1 in range(6):
            add('F');body(0, 0);body(1, 0, (1, 0, 0))
            add('P', 0, 1);add('D');add('W', 0)
            add('A', 0, state0);add('A', 1, state1);add('D')
    for flags0 in range(8):
        for flags1 in range(8):
            add('F');body(0, 0, flags=flags0);body(1, 0, (1, 0, 0), flags=flags1)
            add('P', 0, 1);add('D')
    add('F');body(0, 3);body(1, 0, (0, .5, 0))
    add('E', 1, 0, 1);add('P', 0, 1);add('D');add('E', 1, 0, 0);add('D');add('C', 0);add('D')
    add('E', 0, 1, 1);add('D');add('E', 0, 1, 0);add('D')
    add('F')
    for i in range(5): body(i, 0, (i * 10, 0, 0), threshold=5-i)
    for i in range(1, 5): add('P', 0, i)
    add('D');add('C', 2);add('C', 2);add('X', 2);add('R', 0, 4);add('P', 0, 2);add('D');add('X', 0)
    add('F')
    for i, shape in enumerate([0, 1, 2, 1]): body(i, shape, (i * .2, .1, .3))
    for pair in [(0, 1), (2, 3)]: add('P', *pair)
    add('D');add('D');add('R', 0, 1);add('P', 0, 1);add('D')
    for reversed_order in [False, True]:
        add('F')
        body(int(reversed_order), 0, (0, .5, 0));body(int(not reversed_order), 3, flags=1)
        add('P', 0, 1);add('D');add('S');add('D');add('S');add('D')
    add('F')
    return ('\n'.join(lines) + '\n').encode()


if __name__ == '__main__':
    import sys
    sys.stdout.buffer.write(corpus())
