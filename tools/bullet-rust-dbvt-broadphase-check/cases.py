"""Immutable operation histories for the default-owned broadphase."""
import struct


def bits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def box(lo, hi):
    return ' '.join(str(bits(x)) for x in [lo] * 3 + [hi] * 3)


def corpus():
    histories = []
    def history(name, commands):
        histories.append((name, ['H ' + str(len(histories)), *commands]))
    def create(i, lo=0, hi=1, group=1, mask=1):
        return f'c {i} {group} {mask} ' + box(lo, hi)
    def move(i, lo, hi):
        return f's {i} ' + box(lo, hi)
    history('empty-live-reset-uid-reuse', ['r', 'v ' + str(bits(2)), create(0), 'p', 'r', 'd 0', create(0), 'd 0', 'r', create(0), 'd 0'])
    history('touch-filter-duplicate-attempt', [create(0), create(1, 1, 2), create(2, .5, 1.5, 2, 2), move(1, .75, 2), 'n', 'p', move(0, 10, 11), 'p', 'd 2', 'd 1', 'd 0'])
    history('unchanged-stage-refresh', [create(0, 0, 2), create(1, 0, 2), 'p', move(0, 0, 2), move(1, .5, 1.5), 'p', 'p', 'p', 'd 0', 'd 1'])
    for prediction in [0, 1, 2, -1]:
        history(f'prediction-{prediction}', ['v ' + str(bits(prediction)), create(0, 0, 2), move(0, -.25, 1.75), move(0, -.5, 2.5), 'p', move(0, 20, 21), 'p', 'p', move(0, 20, 21), 'p', 'd 0'])
    history('fixed-reactivation-query-sides', [create(0), create(1, 4, 5), 'p', 'p', create(2, 8, 9), move(2, 4, 5), move(0, 4, 5), 'n', 'd 1', 'p', 'd 0', 'd 2'])
    history('margin-versus-requested-cleanup', [create(0), create(1, .5, 1.5), move(0, .75, 1.75), move(1, .5, .74), 'n', 'p', 'p', 'n', 'd 0', 'd 1'])
    history('teleport-cleanup-release', [create(0), create(1), 'n', move(1, 100, 101), 'p', 'd 0', create(0), 'n', 'd 1', 'd 0', 'r'])
    history('swap-remove-budget', [*[create(i) for i in range(6)], 'n', 'p', 'p', *[move(i, 100 + 3*i, 101 + 3*i) for i in range(6)], create(6, 0, 200, 2, 2), 'p', 'p', *[f'd {i}' for i in range(7)]])
    history('cursor-and-destroy-order', [*[create(i) for i in range(8)], 'p', move(0, .1, 1.1), 'n', 'p', move(1, 100, 101), 'p', 'd 3', 'p', *[f'd {i}' for i in [0, 1, 2, 4, 5, 6, 7]]])
    for leaves in [99, 100, 101, 200]:
        history(f'fixed-optimization-{leaves}', [*[create(i, i*3, i*3+1) for i in range(leaves)], 'p', 'p', 'p', 'p', *[f'd {i}' for i in range(leaves)], 'r'])
    manifest = [{'history': name, 'checkpoints': len(commands)} for name, commands in histories]
    return '\n'.join(command for _, commands in histories for command in commands) + '\n', manifest


if __name__ == '__main__':
    print(corpus()[0], end='')
