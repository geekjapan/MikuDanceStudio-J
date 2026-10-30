"""Validate actual activate call observations against input guards and native pre-wake state."""
from collections import Counter


def worlds(inputs):
    result = {}
    for line in inputs.decode().splitlines():
        fields = line.split()
        case = int(fields[0])
        if fields[1] != 'W':
            continue
        values = iter(map(int, fields[2:]))
        n, split, mode = next(values), next(values), next(values)
        objects = [tuple(next(values) for _ in range(7)) for _ in range(n)]
        for width in (2, 4):
            for _ in range(next(values) * width):
                next(values)
        manifolds = [tuple(next(values) for _ in range(4)) for _ in range(next(values))]
        assert list(values) == []
        result[case] = (split, mode, objects, manifolds)
    return result


def object_state(fields):
    count = int(fields[5])
    assert len(fields) == 6 + count * 6, 'malformed object observer'
    return [tuple(map(int, fields[i:i + 6])) for i in range(6, len(fields), 6)]


def validate_wake(inputs, trace, require_coverage=True):
    cases = worlds(inputs)
    observations = {}
    case = None
    for line in trace.splitlines():
        fields = line.split()
        if fields[0] == 'I':
            case = int(fields[1])
            assert case not in observations, 'duplicate case observer'
            observations[case] = {'start': None, 'calls': []}
        elif fields[:2] == ['O', 'sleep']:
            observations[case]['start'] = object_state(fields)
        elif fields[0] == 'O' and fields[1].startswith('wake'):
            assert fields[1] in ('wake_A_before', 'wake_A_after', 'wake_B_before', 'wake_B_after'), 'unknown wake observer'
            observations[case]['calls'].append((fields[1], *map(int, fields[2:5]), object_state(fields)))
    coverage = Counter()
    for case, (split, mode, objects, manifolds) in cases.items():
        assert case in observations, ('missing case observer', case)
        observed = observations[case]
        state = observed['start']
        assert state is not None or not objects, ('missing pre-wake native state', case)
        state = list(state or [])
        assert len(state) == len(objects)
        for i, snapshot in enumerate(state):
            assert snapshot[0] == i
        expected = []
        for manifold, (a, b, _, _) in enumerate(manifolds):
            if state[a][1] == 2 and state[b][1] == 2:
                continue
            for branch, source, target in [('A', a, b), ('B', b, a)]:
                if not objects[source][1] & 2 or state[source][1] == 2:
                    continue
                expected.append((f'wake_{branch}_before', manifold, source, target, list(state)))
                before = state[target]
                if not objects[target][1] & 3:
                    after = list(before)
                    if before[1] not in (4, 5):
                        after[1] = 1
                    after[5] = 0
                    state[target] = tuple(after)
                expected.append((f'wake_{branch}_after', manifold, source, target, list(state)))
                coverage[f'wake_{branch}'] += 1
                coverage[f'wake_{branch}:split_{split}'] += 1
                coverage[f'wake_{branch}:mode_{mode}'] += 1
                coverage[f'wake_{branch}:source_state_{state[source][1]}'] += 1
                coverage[f'wake_{branch}:target_state_{before[1]}'] += 1
                if before[1] in (4, 5) and not objects[target][1] & 3:
                    coverage[f'wake_{branch}:protected_{before[1]}'] += 1
                if not objects[a][2] or not objects[b][2]:
                    coverage[f'wake_{branch}:no_response'] += 1
                response = int(bool(objects[a][2] and objects[b][2]))
                coverage[f'wake_{branch}:split_{split}:mode_{mode}:target_state_{before[1]}:response_{response}'] += 1
        assert observed['calls'] == expected, ('wake calls/state differ from actual input guards', case, len(observed['calls']), len(expected))
    if require_coverage:
        for branch in ('A', 'B'):
            for dimension in ('', ':split_0', ':split_1', ':mode_0', ':mode_1', ':protected_4', ':protected_5', ':no_response'):
                assert coverage[f'wake_{branch}{dimension}'] > 0, ('missing wake branch coverage', branch, dimension)
    return coverage


def focused_inputs():
    rows = []
    for mode in (0, 1):
        for split in (0, 1):
            for a, b in [((1, 0, 1), (1, 0, 1)), ((2, 2, 1), (2, 0, 1))]:
                rows.append((split, mode, a, b))
            for branch in ('A', 'B'):
                for target_state in (2, 4, 5):
                    for response in (0, 1):
                        a, b = (1, 2, response), (target_state, 0, 1)
                        if branch == 'B':
                            a, b = b, a
                        rows.append((split, mode, a, b))
    result = []
    for case, (split, mode, a, b) in enumerate(rows):
        objects = ' '.join(f'{state} {flags} {response} 1056964608 73 29 1056964608' for state, flags, response in (a, b))
        result.append(f'{case} W 2 {split} {mode} {objects} 0 0 1 0 1 0 0')
    return ('\n'.join(result) + '\n').encode()


def negative_controls(inputs, trace):
    coverage = validate_wake(inputs, trace)
    for branch in ('A', 'B'):
        assert coverage[f'wake_{branch}'] == 24
        for split in (0, 1):
            for mode in (0, 1):
                for state in (2, 4, 5):
                    for response in (0, 1):
                        assert coverage[f'wake_{branch}:split_{split}:mode_{mode}:target_state_{state}:response_{response}'] == 1
    results = {}
    def reject(name, changed):
        try:
            validate_wake(inputs, changed)
        except AssertionError:
            results[name] = 'rejected'
        else:
            raise AssertionError(('invalid wake evidence accepted', name))
    lines = trace.splitlines()
    for branch in ('A', 'B'):
        reject(f'missing-branch-{branch}', '\n'.join(line for line in lines if not line.startswith(f'O wake_{branch}_')))
    # These cases have a manifold but neither actual activate branch is reachable.
    for case, name in [(0, 'dynamic-active-source-guard'), (1, 'both-sleeping-outer-guard')]:
        current = None
        for index, line in enumerate(lines):
            if line.startswith('I '):
                current = int(line.split()[1])
            if current == case and line.startswith('O sleep '):
                fields = line.split()
                for branch, source, target in [('A', 0, 1), ('B', 1, 0)]:
                    fake = f'O wake_{branch}_before 0 {source} {target} ' + ' '.join(fields[5:])
                    reject(f'{name}-{branch}', '\n'.join(lines[:index + 1] + [fake, fake.replace('_before', '_after')] + lines[index + 1:]))
                assert not any(line.startswith('O wake_') for line in lines[index + 1:next((j for j in range(index + 1, len(lines)) if lines[j].startswith('I ')), len(lines))])
                break
    current = None
    zero_cases = Counter()
    for line in lines:
        fields = line.split()
        if fields[0] == 'I':
            current = int(fields[1])
            if current % 14 in (0, 1):
                zero_cases['dynamic-active' if current % 14 == 0 else 'both-sleeping'] += 1
        elif current % 14 in (0, 1):
            assert not line.startswith('O wake_'), ('negative case emitted wake call', current)
    assert zero_cases == {'dynamic-active': 4, 'both-sleeping': 4}
    assert len(results) == 6
    results.update({name + '-zero-calls': f'{count} native cases, zero activate observations' for name, count in zero_cases.items()})
    return results
