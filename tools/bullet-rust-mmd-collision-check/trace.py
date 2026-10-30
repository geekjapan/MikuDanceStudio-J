"""Ordered diagnostic trace framing. No capture admission or semantic PASS."""
import re


def require(ok, message):
    if not ok:
        raise ValueError(message)


def visibility(dynamics=False, observed=True):
    tags = {'O', 'B', 'P', 'M', 'Q'}
    if observed:
        tags |= {'E', 'S', 'J'}
    if dynamics:
        tags |= {'W', 'STATUS'}
        if observed:
            tags |= {'R', 'K', 'Y', 'V'}
    return tags


def _checkpoint(records, command, observed, dynamics):
    headers = [r for r in records if r[0] == 'O']
    require(len(headers) == 1, 'one operation snapshot')
    header = headers[0]
    require(len(header) == 6 and header[2] == command.split()[0], 'operation snapshot')
    require(all(re.fullmatch(r'0|[1-9][0-9]*', x) for x in header[3:]), 'snapshot counts')
    bodies, pairs, manifolds = map(int, header[3:])
    for tag, count in [('B', bodies), ('P', pairs), ('M', manifolds)]:
        found = [r for r in records if r[0] == tag]
        require(len(found) == count and [r[2] for r in found] == list(map(str, range(count))), 'ordered complete ' + tag)
    sap = [r for r in records if r[0] == 'S']
    require([r[2] for r in sap] == (['0', '1', '2'] if observed and bodies else []), 'ordered complete SAP axes')
    for manifold in [r for r in records if r[0] == 'M']:
        contacts = [r for r in records if r[0] == 'Q' and r[2] == manifold[2]]
        require(len(contacts) == int(manifold[-1]) and [r[3] for r in contacts] == list(map(str, range(len(contacts)))), 'ordered complete contacts')
    require(all(int(r[2]) < manifolds for r in records if r[0] == 'Q'), 'contact manifold owner')
    if dynamics:
        state = [r for r in records if r[0] == 'W']
        require([r[2] for r in state] == list(map(str, range(bodies))), 'complete initialized dynamics body state')
        for index, record in enumerate(records):
            if record[0] == 'W':
                require(index > 0 and records[index - 1][:3] == ['B', record[1], record[2]], 'dynamics state follows its own body')
        step = command.split()[0] == 'N'
        for tag, count in [('STATUS', int(step)), ('R', int(step and observed)), ('K', int(step and observed))]:
            require(sum(r[0] == tag for r in records) == count, 'explicit dynamics visibility ' + tag)
        require(step or not any(r[0] in {'Y', 'V'} for r in records), 'schedule only during actual step')
        if step:
            status_at = next(i for i, record in enumerate(records) if record[0] == 'STATUS')
            require(status_at < records.index(header), 'genuine shim status precedes snapshot')
        if step and observed:
            clock = next(r for r in records if r[0] == 'K')
            clock_at = records.index(clock)
            return_at = next(i for i, record in enumerate(records) if record[0] == 'R')
            require(clock_at < return_at and return_at + 1 == status_at, 'single actual Bullet return before genuine shim status')
            require(all(clock_at < i < return_at for i, record in enumerate(records) if record[0] in {'Y', 'V'}), 'actual step observations between clock and return')
            schedule = [r for r in records if r[0] in {'Y', 'V'}]
            phase = None
            prepared = solved = groups = workspaces = 0
            for record in schedule:
                if record[0] == 'V':
                    require(phase == 'G', 'workspace follows its actual group')
                    workspaces += 1
                    phase = 'V'
                elif record[2] == 'P':
                    require(phase in {None, 'A'}, 'prepare begins substep')
                    prepared += 1
                    phase = 'P'
                elif record[2] == 'G':
                    require(phase in {'P', 'V'}, 'group within prepared solve')
                    at = 4
                    for limit in (bodies, manifolds, None):
                        count = int(record[at]);at += 1
                        require(count >= 0 and at + count <= len(record), 'complete ordered group indices')
                        require(all(int(v) >= 0 and (limit is None or int(v) < limit) for v in record[at:at+count]), 'live group indices')
                        at += count
                    require(at == len(record), 'exact group width')
                    groups += 1
                    phase = 'G'
                else:
                    require(record[2] == 'A' and phase in {'P', 'V'}, 'allSolved closes prepared groups')
                    solved += 1
                    phase = 'A'
            require(prepared == solved == int(clock[3]) and groups == workspaces and phase in {None, 'A'}, 'complete actual substep schedule')
    return records


def frames(raw, inputs, *, observed=True, dynamics=False):
    require(type(raw) is bytes and 0 < len(raw) <= 64 * 1024 * 1024, 'bounded nonempty trace')
    require(b'\r' not in raw and raw.endswith(b'\n'), 'LF terminated raw trace')
    commands = inputs.splitlines()
    rows, current = [], []
    lines = raw.decode('ascii').splitlines()
    for position, line in enumerate(lines):
        words = line.split(' ')
        require(all(words) and len(words) >= 2, 'trace token framing')
        if words[0] == 'Z':
            if current:
                rows.append(_checkpoint(current, commands[len(rows)], observed, dynamics))
                current = []
            require(words == ['Z', str(len(commands))] and len(rows) == len(commands), 'complete trace end')
            require(position == len(lines) - 1, 'last trace end')
            return rows
        require(words[0] in visibility(dynamics, observed), 'known explicitly visible trace row')
        if words[1] == str(len(rows) + 1) and current:
            rows.append(_checkpoint(current, commands[len(rows)], observed, dynamics))
            current = []
        require(len(rows) < len(commands) and words[1] == str(len(rows)), 'exact ordered checkpoint index')
        current.append(words)
        tag = words[0]
        if tag == 'E':
            require(len(words) in {4, 6} and words[2] in {'A+', 'A-', 'M+', 'M-', 'U', 'U+', 'U-'}, 'event framing')
        elif tag == 'B':
            require(len(words) == 66, 'complete body words and SAP handle indices')
            require(all(re.fullmatch('[0-9a-f]{8}', w) for w in words[9:60]), 'raw body float words')
        elif tag == 'S':
            require(len(words) >= 4 and len(words) == 4 + 2 * int(words[3]), 'complete SAP edges')
        elif tag == 'P':
            require(len(words) == 8, 'complete ordered pair')
        elif tag == 'M':
            require(len(words) == 10, 'complete manifold')
            require(all(re.fullmatch('[0-9a-f]{8}', w) for w in words[7:9]), 'raw manifold float words')
        elif tag == 'Q':
            require(len(words) in {27, 33} and words[26] in {'0', '1'} and len(words) == 27 + 6 * int(words[26]), 'complete contact words')
            require(all(re.fullmatch('[0-9a-f]{8}', w) for w in words[4:25] + words[27:]), 'raw contact float words')
        elif tag == 'J':
            require(len(words) == 24, 'complete joint spring words')
        elif tag == 'W':
            require(len(words) == 41 and all(re.fullmatch('[0-9a-f]{8}', w) for w in words[5:]), 'initialized dynamics words')
            require(all(re.fullmatch(r'-?(0|[1-9][0-9]*)', w) for w in words[2:5]), 'dynamics state indices')
        elif tag in {'STATUS', 'R'}:
            require(len(words) == 3 and re.fullmatch(r'0|[1-9][0-9]*', words[2]), 'genuine status or actual return')
            if tag == 'STATUS':
                require(words[2] == '0', 'successful genuine shim status')
        elif tag == 'K':
            require(len(words) == 6 and all(re.fullmatch(r'0|[1-9][0-9]*', w) for w in words[2:4]) and
                    0 <= int(words[3]) <= int(words[2]) and all(re.fullmatch('[0-9a-f]{8}', w) for w in words[4:]), 'actual clock record')
        elif tag == 'V':
            require(len(words) == 4 and words[2] == '0' and re.fullmatch(r'0|[1-9][0-9]*', words[3]), 'live prefix and capacity without backing-slot reads')
        elif tag == 'Y':
            require((len(words) == 3 and words[2] == 'A') or
                    (len(words) == 5 and words[2] == 'P' and all(w.isdigit() for w in words[3:])) or
                    (len(words) >= 7 and words[2] == 'G' and re.fullmatch(r'-?(0|[1-9][0-9]*)', words[3]) and all(w.isdigit() for w in words[4:])), 'actual solver schedule record')
    raise ValueError('missing complete trace end')


def common(rows, *, dynamics=False):
    result = []
    for checkpoint in rows:
        projected = []
        for record in checkpoint:
            if record[0] in (visibility(dynamics, True) - visibility(dynamics, False)):
                continue
            row = list(record)
            if row[0] == 'P':
                row[-1] = str(int(row[-1] != '0'))
            if row[0] == 'M':
                row[3:5] = ['1', '1']
            projected.append(row)
        result.append(projected)
    return result


def semantic_projection(checkpoint, field):
    tags = {'sap': {'S'}, 'bodies': {'B'}, 'manifolds': {'P', 'M', 'Q'}, 'events': {'E'},
            'step-return': {'R'}, 'dynamics': {'W'}, 'schedule': {'Y'}, 'workspace': {'V'}}
    body_fields = {'activation': [4], 'filter': [6, 7], 'restitution': [47], 'mass-flags': [3, 45],
                   'current-transform': list(range(9, 21)), 'interpolation-velocity': list(range(54, 60)),
                   'motion-state': list(range(33, 45))}
    if field == 'forces':
        return [record[2:3] + record[33:39] for record in checkpoint if record[0] == 'W']
    if field in body_fields:
        return [[record[2], *[record[index] for index in body_fields[field]]]
                for record in checkpoint if record[0] == 'B']
    if field in {'manifold-bodies', 'dispatch-order'}:
        return [record[5:7] for record in checkpoint if record[0] == 'M']
    require(field in tags, 'known directed semantic field')
    return [record for record in checkpoint if record[0] in tags[field]]


def validate_lifetimes(rows):
    algorithms, manifolds, owners = set(), {}, {}
    next_algorithm = next_manifold = 0
    for checkpoint in rows:
        update = None
        header = next(record for record in checkpoint if record[0] == 'O')
        body_count = int(header[3])
        for record in checkpoint:
            if record[0] != 'E':
                continue
            require(len(record) == (6 if record[2] == 'M+' else 4), 'exact lifecycle event fields')
            event, generation = record[2], int(record[3])
            if event == 'A+':
                require(generation == next_algorithm + 1 and generation not in algorithms, 'fresh algorithm generation')
                next_algorithm = generation
                algorithms.add(generation)
            elif event == 'A-':
                require(generation in algorithms and generation not in owners.values(), 'release algorithm after owned manifolds')
                algorithms.remove(generation)
            elif event == 'M+':
                require(generation == next_manifold + 1 and generation not in manifolds, 'fresh manifold generation')
                next_manifold = generation
                bodies = tuple(map(int, record[4:6]))
                require(len(bodies) == 2 and bodies[0] != bodies[1]
                        and all(0 <= body < body_count for body in bodies), 'live manifold body owners')
                manifolds[generation] = bodies
            elif event == 'M-':
                require(generation in manifolds, 'release existing manifold generation')
                del manifolds[generation]
                owners.pop(generation, None)
            elif event == 'U+':
                require(update is None and 0 <= generation < body_count, 'single live AABB update')
                update = generation
            elif event == 'U-':
                require(update == generation, 'matching synchronous AABB update end')
                update = None
            else:
                require(event == 'U' and generation >= 0, 'proxy unregister event')
        require(update is None, 'closed AABB update checkpoint')
        current = [record for record in checkpoint if record[0] == 'M']
        require(len(current) == len(manifolds) and {int(record[3]) for record in current} == set(manifolds),
                'complete live manifold snapshot')
        for record in current:
            generation, owner = int(record[3]), int(record[4])
            require(owner in algorithms and tuple(map(int, record[5:7])) == manifolds[generation], 'manifold algorithm/body identity')
            require(generation not in owners or owners[generation] == owner, 'persistent manifold owner generation')
            owners[generation] = owner
        require(len(set(owners.values())) == len(owners), 'one manifold per supported algorithm')
        pairs = [record for record in checkpoint if record[0] == 'P']
        pair_algorithms = [int(record[-1]) for record in pairs if record[-1] != '0']
        require(len(set(pair_algorithms)) == len(pair_algorithms) and set(pair_algorithms) <= algorithms,
                'live distinct pair algorithms')
        if header[2] == 'X':
            require(not algorithms and not manifolds and not owners, 'complete algorithm/manifold teardown')
    require(not algorithms and not manifolds and not owners, 'closed full trace lifetime ledger')
    return {'algorithm_generations': next_algorithm, 'manifold_generations': next_manifold}
