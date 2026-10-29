"""Inert protocol fixtures. These values are not physics calculations or execution evidence."""


def complete(raw, inputs, *, native=False, observed=True, mutation=None):
    commands = inputs.splitlines()
    records = [[] for _ in commands]
    for line in raw.decode().splitlines():
        if not line.startswith('Z '): records[int(line.split()[1])].append(line)
    output, live, generation, returned, changed = [], None, 0, -1, False
    for row, (command, lines) in enumerate(zip(commands, records)):
        op = command.split()[0]
        header = next(line.split() for line in lines if line.startswith('O '))
        bodies = int(header[3])
        if live is not None:
            if observed: output.extend([f'E {row} M- {live}', f'E {row} A- {live}'])
            live = None
        if op == 'H': returned = -1
        active = op == 'N' and bodies >= 2
        if op == 'N':
            returned = 1
            if observed:
                output.append(f'K {row} 1 1 3c888889 00000000')
            if active:
                generation += 1
                live = generation
                if observed: output.extend([f'E {row} A+ {live}', f'E {row} M+ {live} 0 1'])
            if observed:
                output.append(f'Y {row} P {bodies} {int(active)}')
                if active:
                    members = '1 0' if mutation in {'pair-owner', 'contact-only-union'} and not changed else '2 0 1'
                    if members == '1 0': changed = True
                    output.append(f'Y {row} G 0 {members} 1 0 0')
                    capacity = 3 if mutation in {'workspace-group-reset', 'workspace-step-reset'} and not changed else 2
                    if capacity == 3: changed = True
                    output.append(f'V {row} 0 {capacity}')
                output.append(f'Y {row} A')
        for line in lines:
            fields = line.split()
            if fields[0] == 'O' and active:
                fields[4:6] = ['1', '1']
                line = ' '.join(fields)
            output.append(line)
            if fields[0] == 'O' and op != 'X':
                result = returned
                if op == 'N' and mutation == 'executed-return' and not changed:
                    result = 2; changed = True
                output.append(f'R {row} {result} 0')
            if fields[0] == 'B':
                values = ['00000000'] * 36
                if mutation in {'substep-gravity', 'wrong-com', 'zero-step-sync', 'force-clear'} and not changed:
                    values[20] = '3f800000'; changed = True
                output.append(f'W {row} {fields[2]} -1 -1 ' + ' '.join(values))
        if active:
            g = live if observed else 1
            output.extend([f'P {row} 0 0 1 {g}', f'M {row} 0 {g} {g} 0 1 00000000 00000000 1'])
            values = ['00000000'] * 21
            values[18] = '40000000' if mutation == 'missing-impulse-writeback' and not changed else '3f800000'
            if values[18] == '40000000': changed = True
            output.append(f'Q {row} 0 0 ' + ' '.join(values) + ' 1 0')
    output.append('Z ' + str(len(commands)))
    return ('\n'.join(output) + '\n').encode()
