

def complete(raw, inputs, *, native=False, observed=True, mutation=None):
    commands = inputs.splitlines()
    records = [[] for _ in commands]
    for line in raw.decode().splitlines():
        if not line.startswith('Z '): records[int(line.split()[1])].append(line)
    output, live, generation, returned, changed = [], None, 0, -1, False
    motion_case, reset, motion_y = False, False, '00000000'
    for row, (command, lines) in enumerate(zip(commands, records)):
        op = command.split()[0]
        if op == 'H':
            motion_case = command.split()[1] == 'zero-step-motion-and-forces'
            reset = False
        if motion_case and op == 'T':
            reset = True
            motion_y = '41200000'
        if reset and op == 'N' and mutation != 'zero-step-sync':
            motion_y = '411e0000'
        body_lines = []
        for line in lines:
            fields = line.split()
            if fields[0] == 'B' and reset:
                for start in [9, 21, 33]:
                    fields[start:start+12] = ['3f800000', '00000000', '00000000',
                                             '00000000', '3f800000', '00000000',
                                             '00000000', '00000000', '3f800000',
                                             '00000000', '41200000', '00000000']
                fields[43] = motion_y
                line = ' '.join(fields)
            body_lines.append(line)
        lines = body_lines
        state_hash = 0
        if reset:
            state_hash = 1469598103934665603
            for line in lines:
                fields = line.split()
                if fields[0] == 'B':
                    for word in fields[33:45] + ['00000000'] * 3:
                        for byte in bytes.fromhex(word)[::-1]:
                            state_hash = ((state_hash ^ byte) * 1099511628211) & ((1 << 64)-1)
        header = next(line.split() for line in lines if line.startswith('O '))
        bodies = int(header[3])
        if live is not None:
            if observed: output.extend([f'E {row} M- {live}', f'E {row} A- {live}'])
            live = None
        if op == 'H': returned = -1
        active = op == 'N' and bodies >= 2
        if op == 'N':
            returned = 0 if reset else 1
            if observed:
                output.append(f'K {row} 0 0 3f800000 3e000000' if reset else f'K {row} 1 1 3c888889 00000000')
            if active:
                generation += 1
                live = generation
                if observed: output.extend([f'E {row} A+ {live}', f'E {row} M+ {live} 0 1'])
            if observed:
                if not reset: output.append(f'Y {row} P {bodies} {int(active)}')
                if active:
                    members = '1 0' if mutation in {'pair-owner', 'contact-only-union'} and not changed else '2 0 1'
                    if members == '1 0': changed = True
                    output.append(f'Y {row} G 0 {members} 1 0 0')
                    capacity = 3 if mutation in {'workspace-group-reset', 'workspace-step-reset'} and not changed else 2
                    if capacity == 3: changed = True
                    output.append(f'V {row} 0 {capacity}')
                if not reset: output.append(f'Y {row} A')
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
                output.append(f'R {row} {result} {state_hash}')
            if fields[0] == 'B':
                values = ['00000000'] * 36
                if motion_case and (reset or op == 'N'):
                    values[14] = values[20] = 'bf800000'
                if mutation in {'substep-gravity', 'wrong-com', 'force-clear'} and not changed:
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
