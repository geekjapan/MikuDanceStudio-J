"""Finite source-derived MMD collision corpus. Float payloads retain raw words."""
import struct
import itertools


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
        lines.append('V 1 ' + floats([-1, -2, -3, -4, -5, -6]))
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
    for boundary, extent in [('below', 499999.96875), ('equal', 500000.0), ('above', 500000.03125)]:
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


def dynamics_corpus():
    lines, cases = [], []

    def emit(command, scope='genuine-mmd-operations'):
        cases[-1]['operations'].append({'row': len(lines), 'scope': scope})
        lines.append(command)

    def start(name, family):
        cases.append({'name': name, 'family': family, 'start': len(lines), 'operations': []})
        emit(f'H {name} mixed-explicit-operations')

    def end():
        emit('X')
        cases[-1]['end'] = len(lines) - 1

    def body(kind=0, x=0, y=10, mode=1, mask=-1):
        params = [[.75, 0, 0, 0], [.75, .5, .625, 0], [.4, 1, 0, 0]][kind]
        emit(f'C {kind} {word(2)} {mode} 1 {mask} ' + floats(params + [x, y, 0, 0, 0, 0, 1]))

    def pose(op, i, x, y=10):
        emit(f'{op} {i} ' + floats([x, y, 0, 0, 0, 0, 1]))

    def step(dt=.03125, maximum=0, fixed=.03125):
        emit(f'N {word(dt)} {maximum} {word(fixed)}')

    start('mmd-clock', 'clock')
    step(0, 1, 1 / 60)
    step(0, 1, 1 / 60)
    step(0)
    step(.125)
    step(.25, 2)
    end()
    start('mmd-gravity-force-clear', 'gravity-force-clear')
    body()
    body(x=1.52)
    body(x=3.04)
    emit('G ' + floats([0, -8, 0]))
    emit('L 1 ' + floats([2, 3, 4, .2, .3, .4]), 'fixture-injection')
    emit('FRC 1 ' + floats([4, -3, 2, .5, .75, 1]), 'fixture-injection')
    step(0)
    step(.25, 4)
    step(.125)
    pose('M', 1, 5)
    step(0, 1, 1)
    step(0, 1, 1)
    end()
    for kind, uid in enumerate((-2147483648, 0, 2147483647)):
        start(f'mmd-motion-floor-uid-{kind}', 'motion-floor-uid')
        body(kind, y=1)
        body(x=4, y=1)
        emit(f'J 1 2 {uid} 1')
        pose('M', 1, 1, 2)
        step(0)
        pose('R', 1, 0, .5)
        emit('O 1 ' + floats([0, .5, 0]))
        for on in (0, 1):
            emit(f'F {on}')
            step()
        step(0, 1, 1)
        end()
    start('mmd-fixture-seeded-warmstart', 'warmstart')
    body(y=.6)
    emit('D')
    emit('W', 'fixture-injection')
    for _ in range(4):
        step()
    end()
    for mode in (1, 2):
        for edge in ('contact', 'joint'):
            for order in itertools.permutations(range(3)):
                start(f'mmd-shared-{mode}-{edge}-' + ''.join(map(str, order)), 'shared-endpoint')
                emit('G ' + floats([0, 0, 0]))
                slots = {}
                for i, role in enumerate(order, 1):
                    slots[role] = i
                    body(x=(-1.25, 1.25, 0)[role], mode=mode,
                         mask=0 if edge == 'joint' else -1)
                endpoint = slots[2]
                emit(f'K {endpoint} 1')
                if edge == 'joint':
                    for role in (0, 1):
                        emit(f'J {slots[role]} {endpoint} {role} 0')
                for x in (10, 10.9, 11.8, 20, 20.9):
                    body(x=x)
                pose('M', endpoint, 0, 10.02)
                step()
                step()
                for i in (4, 5, 6):
                    pose('R', i, 30 + i)
                step()
                for i, x in zip((4, 5, 6), (10, 10.9, 11.8)):
                    pose('R', i, x)
                step()
                emit(f'K {endpoint} 0')
                step()
                end()
    return '\n'.join(lines) + '\n', cases
