import itertools
import struct


def word(value):
    return f"{struct.unpack('<I', struct.pack('<f', value))[0]:08x}"


def floats(values):
    return ' '.join(word(value) for value in values)


def corpus():
    lines, cases = [], []
    def start(name, scope='public'):
        cases.append({'name': name, 'scope': scope, 'start': len(lines)})
        lines.append('H ' + name + ' ' + scope)
    def end():
        lines.append('X')
        cases[-1]['end'] = len(lines) - 1
    def body(x=0, y=0, mass=1, kinematic=False, radius=.5):
        lines.append(f'C 0 {word(mass)} {int(kinematic)} 1 -1 ' +
                     floats([radius, 0, 0, 0, x, y, 0, 0, 0, 0, 1]))
    def step(dt=1/60, maximum=1, fixed=1/60):
        lines.append(f'N {word(dt)} {maximum} {word(fixed)}')

    start('empty-clock-zero-variable-clamped')
    step(0); step(0); step(.125, 2, .03125); step(0, 0); step(.125, 0); end()
    start('gravity-once-clamped-first-zero')
    body(y=10)
    lines.append('G ' + floats([0, -8, 0]))
    step(0); step(.25, 4, .03125); step(0, 0); step(.125, 0); step(0, 1, 1); end()
    start('continuous-contacts-warmstart')
    body(mass=0); body(y=.9)
    for _ in range(24): step()
    end()
    start('joint-and-contact')
    body(mass=0); body(y=.9); body(y=1.8)
    lines.append('J 1 2 0')
    for _ in range(12): step()
    end()
    start('multiple-islands-retained-workspace', 'injected')
    lines.append('G ' + floats([0, 0, 0]))
    for x, count in [(0, 4), (10, 2), (20, 3)]:
        for i in range(count): body(x=x, y=i*.9)
    lines.extend(['J 0 1 0', 'J 1 2 0', 'J 2 3 0', 'J 4 5 0', 'J 6 7 0'])
    for _ in range(8): step()
    for i in range(4): lines.append(f'A {i} 2')
    for _ in range(3): step()
    end()
    start('kinematic-motion-contact')
    body(mass=0, kinematic=True); body(y=.9)
    for y in [0, .02, -.02, .05, 0]:
        lines.append('T 0 ' + floats([0, y, 0, 0, 0, 0, 1]))
        step(.03125, 0)
    end()
    for order in itertools.permutations(range(3)):
        start('shared-kinematic-registration-' + ''.join(map(str, order)))
        lines.append('G ' + floats([0, 0, 0]))
        slots = {}
        for registered, role in enumerate(order):
            slots[role] = registered
            body(x=(-.9 if role == 0 else .9 if role == 1 else 0), kinematic=role == 2)
        lines.extend([f'J {slots[0]} {slots[2]} 0', f'J {slots[1]} {slots[2]} 0'])
        step(.03125, 0); step(.03125, 0)
        end()
    start('sleep-and-public-wake')
    lines.append('G ' + floats([0, 0, 0]))
    body(y=10)
    for _ in range(10): step(.25, 0)
    lines.append('T 0 ' + floats([0, 9, 0, 0, 0, 0, 1]))
    step(.125, 0); end()
    start('active-gravity-update', 'injected')
    body(); body(x=10)
    lines.extend(['A 0 2', 'G ' + floats([3, -4, 2]), 'A 0 1'])
    step(.125, 0); end()
    start('zero-step-motion-and-forces', 'injected')
    body(y=10)
    lines.extend(['L 0 ' + floats([2, 3, 4, .2, .3, .4]),
                  'FRC 0 ' + floats([4, -3, 2, .5, .75, 1])])
    step(0, 0)
    step(.125, 0)
    step(0, 1, 1)
    lines.append('T 0 ' + floats([0, 10, 0, 0, 0, 0, 1]))
    step(0, 1, 1)
    step(0, 1, 1)
    end()
    start('all-pair-owner-union-without-contacts', 'injected')
    lines.append('G ' + floats([0, 0, 0]))
    body(); body(x=1.02); body(x=2.04)
    lines.extend(['J 0 1 0', 'A 2 2'])
    step(.03125, 0); end()
    return '\n'.join(lines) + '\n', cases
