"""Finite source-derived MMD collision corpus. Float payloads retain raw words."""
import struct


def word(value):
    return f'{struct.unpack("<I", struct.pack("<f", value))[0]:08x}'


def floats(values):
    return ' '.join(map(word, values))


def corpus():
    lines, cases = [], []

    def start(name, family, injected=False):
        cases.append({'name': name, 'family': family, 'start': len(lines),
                      'scope': 'fixture-injection' if injected else 'genuine-mmd-operations'})
        lines.append(f'H {name} {cases[-1]["scope"]}')

    def end():
        lines.append('X')
        cases[-1]['end'] = len(lines) - 1

    def body(kind=0, x=0.0, y=3.0, mode=1, group=1, mask=-1, params=None):
        params = params or [[.75, 0, 0, 0], [.75, .5, .625, 0], [.4, 1, 0, 0]][kind]
        lines.append(f'C {kind} {word(2.0)} {mode} {group} {mask} ' +
                     floats(params + [x, y, 0, 0, 0, 0, 1]))

    def pose(op, i, x, y=3.0):
        lines.append(f'{op} {i} ' + floats([x, y, 0, 0, 0, 0, 1]))

    start('constructor', 'constructor')
    lines.extend(['U', 'D'])
    end()
    for a in range(3):
        for b in range(3):
            start(f'ordered-shapes-{a}-{b}', 'ordered-shapes', True)
            body(a)
            body(b, x=.25)
            lines.extend(['D', 'W', 'D'])
            pose('R', 1, 50)
            lines.extend(['S 1', 'D'])
            pose('R', 1, 0)
            lines.extend(['D', 'D'])
            end()
    for shape in range(3):
        for on in (0, 1):
            start(f'floor-{shape}-{on}', 'floor')
            lines.append(f'F {on}')
            body(shape, y=0)
            lines.extend(['D', 'F 0', 'D', 'F 1', 'D'])
            end()
    filters = [(1, -1, 1, -1), (-32768, -1, 1, -32768), (-1, -1, -32768, -1),
               (1, 0, 1, -1), (0, -1, 1, -1), (2, 1, 1, 2), (2, 2, 1, -1), (1, -1, 2, 2)]
    for i, (ag, am, bg, bm) in enumerate(filters):
        start(f'signed-filter-{i}', 'signed-filter')
        body(group=ag, mask=am)
        body(1, x=.25, group=bg, mask=bm)
        lines.extend(['D', 'D'])
        end()
    for a in range(3):
        for b in range(3):
            start(f'mode-{a}-{b}', 'mode')
            body(mode=a)
            body(1, x=.25, mode=b)
            lines.extend(['D', 'K 1 1', 'D', 'K 1 0', 'D', 'K 2 1', 'D', 'K 2 0', 'D'])
            end()
    for shape in range(3):
        start(f'motion-reseat-stop-{shape}', 'motion', True)
        body(shape)
        body(0, x=.25)
        lines.extend(['D', 'V 1 ' + floats([1, 2, 3, 4, 5, 6])])
        pose('M', 1, 100)
        lines.append('D')
        pose('R', 1, 50)
        lines.append('D')
        lines.append('O 1 ' + floats([0, 3, 0]))
        lines.append('D')
        end()
    for uid in (-2147483648, 0, 2147483647):
        for spring in (0, 1):
            start(f'joint-{uid}-{spring}', 'joint')
            body()
            body(1, x=.25)
            lines.extend([f'J 1 2 {uid} {spring}', 'D', 'D'])
            end()
    for boundary, extent in [('below', 499999.9375), ('equal', 499999.96875), ('above', 500000.0)]:
        for flags in (0, 1, 2, 3):
            start(f'huge-{boundary}-{flags}', 'huge-aabb', True)
            body(1, x=extent, mode=0 if flags & 1 else 1, params=[extent, 1, 1, 0])
            lines.append(f'K 1 {int(bool(flags & 2))}')
            body(0, x=.25)
            # Active and both protected states witness setActivationState's guard.
            for state in (1, 4, 5):
                lines.extend([f'A 1 {state}', 'S 1', 'D'])
            end()
    start('multiway-lifecycle', 'multiway', True)
    for i in range(7):
        body(i % 3, x=i * .2)
    lines.extend(['D', 'W', 'D', 'D'])
    for i in (1, 4, 7):
        pose('R', i, 20 + i)
    lines.extend(['D', 'D'])
    for i in (1, 4, 7):
        pose('R', i, (i - 1) * .2)
    lines.extend(['D', 'D'])
    end()
    return '\n'.join(lines) + '\n', cases
