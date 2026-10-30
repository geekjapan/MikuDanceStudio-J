"""Validate complete dispatcher traces before semantic comparison."""
import re

WORD = re.compile(r'^[0-9a-f]{8}$')


def validate(raw, commands):
    lines = iter(raw.decode('ascii').splitlines())
    for row, command in enumerate(commands.decode('ascii').splitlines()):
        head = next(lines).split()
        assert len(head) == 5 and head[:3] == ['O', str(row), command.split()[0]], head
        pairs, manifolds = map(int, head[3:])
        assert 0 <= pairs <= 28 and 0 <= manifolds <= 4096
        owners = set()
        for index in range(pairs):
            p = next(lines).split()
            assert len(p) == 6 and p[:3] == ['P', str(row), str(index)]
            a, b, owner = map(int, p[3:]);assert 0 <= a < b < 8 and owner >= 0
            if owner: owners.add(owner)
        for index in range(manifolds):
            m = next(lines).split()
            assert len(m) == 9 and m[:3] == ['M', str(row), str(index)]
            assert int(m[3]) > 0 and all(0 <= int(x) < 8 for x in m[4:6])
            assert all(WORD.fullmatch(x) for x in m[6:8])
            count = int(m[8]);assert 0 <= count <= 4
            for point in range(count):
                q = next(lines).split()
                assert q[:4] == ['Q', str(row), str(index), str(point)]
                assert len(q) in [27, 33] and all(WORD.fullmatch(x) for x in q[4:25])
                assert int(q[25]) >= 0 and q[26] in ['0', '1']
                assert len(q) == (33 if q[26] == '1' else 27)
                assert all(WORD.fullmatch(x) for x in q[27:])
        # Body membership comes from N and F commands, independently of trace declarations.
        if row == 0: live = set()
        fields = command.split()
        if fields[0] == 'F': live.clear()
        if fields[0] == 'N': live.add(int(fields[1]))
        for body in sorted(live):
            b = next(lines).split()
            assert len(b) == 12 and b[:3] == ['B', str(row), str(body)]
            assert all(WORD.fullmatch(x) for x in b[3:])
        if fields[0] == 'S':
            for index in range(manifolds):
                alias = next(lines).split()
                assert alias[:3] == ['L', str(row), str(index)] and len(alias) == 4 and alias[3] in ['0', '1']
    assert next(lines).split() == ['Z', str(row + 1)]
    assert next(lines, None) is None
