import struct


def word(value):
    return f"{struct.unpack('<I', struct.pack('<f', value))[0]:08x}"


def floats(values):
    return ' '.join(word(value) for value in values)


def corpus():
    lines, cases = [], []
    def start(name, scope):
        cases.append({'name': name, 'scope': scope, 'start': len(lines)})
        lines.append('H ' + name + ' ' + scope)
    def end():
        lines.append('X')
        cases[-1]['end'] = len(lines) - 1
    def body(kind=0, x=0, mass=1, kinematic=0, group=1, mask=-1, params=None, rotation=None):
        params = params or [[.75, 0, 0, 0], [.75, .5, .625, 0], [.4, 1, 0, 0], [0, 1, 0, 0]][kind]
        lines.append(f'C {kind} {word(mass)} {kinematic} {group} {mask} ' + floats(params + [x, 0, 0] + (rotation or [0, 0, 0, 1])))
    start('empty', 'public'); lines.extend(['U', 'D']); end()
    for a in range(4):
        for b in range(4):
            start(f'shapes-{a}-{b}', 'injected' if 3 in (a, b) else 'public')
            body(a, mass=0 if a == 3 else 1, group=-1)
            body(b, x=.25, mass=0 if b == 3 else 1, group=-1)
            if 3 in (a, b): lines.extend(['A 0 1', 'A 1 1'])
            lines.extend(['S 0', 'D', 'D', 'D']); end()
    start('raw-transform-sentinels', 'injected')
    body(1, rotation=[.25, .5, -.125, 1]); body(2, x=.25)
    for which, x in [('interpolation', 80), ('motion', -80), ('current', 1)]:
        lines.append('V 0 ' + which + ' ' + floats([x, 0, 0, -.5, .125, .25, 1])); lines.append('S 0')
    lines.extend(['D', 'D']); end()
    start('kinematic-motion-only', 'public')
    body(1, kinematic=1); body(0, x=.25)
    lines.append('T 0 ' + floats([90, 0, 0, .25, .5, -.125, 1])); lines.extend(['S 0', 'D']); end()
    for force in (0, 1):
        for state in range(6):
            start(f'force-{force}-activation-{state}', 'injected')
            body(); body(1, x=.25, mass=0, group=-1)
            lines.extend([f'A 0 {state}', f'A 1 {state}', f'F {force}', 'U', 'D']); end()
    for side, extent in [('below', 499999.9375), ('equal', 499999.96875), ('above', 500000.0)]:
        for flags in (0, 1, 2, 3, -1):
            for state in (1, 4, 5):
                start(f'huge-{side}-flags-{flags}-state-{state}', 'injected')
                body(1, params=[extent, 1, 1, 0]); body(0, x=.25)
                lines.extend([f'I 0 {flags}', f'A 0 {state}', 'S 0', 'U']); end()
    start('filter-rejected', 'public')
    body(group=2, mask=2); body(1, group=1, mask=1); lines.extend(['D', 'D']); end()
    for disabled in (0, 1):
        start(f'joint-disabled-{disabled}', 'public')
        body(); body(1, x=.25); lines.extend([f'J 0 1 {disabled}', 'D', 'D']); end()
    start('no-response-flags-minus-one', 'injected')
    body(); body(1, x=.25, mass=0, group=-1)
    lines.extend(['I 0 4', 'I 1 -1', 'A 1 1', 'D', 'D']); end()
    start('ordered-reuse-fixed-reactivation-shutdown', 'injected')
    for i in range(7): body(i % 3, x=i * .2)
    lines.extend(['D', 'D', 'D', 'D', 'F 0'])
    for i in range(7): lines.append(f'A {i} 2')
    lines.extend(['D', 'D', 'D'])
    for i in (0, 3, 6):
        lines.extend([f'A {i} 1', 'T ' + str(i) + ' ' + floats([20 + i, 0, 0, 0, 0, 0, 1])])
    lines.extend(['D'] * 8)
    for i in (0, 3, 6): lines.append('T ' + str(i) + ' ' + floats([i * .2, 0, 0, 0, 0, 0, 1]))
    lines.extend(['D'] * 4); end()
    return '\n'.join(lines) + '\n', cases
