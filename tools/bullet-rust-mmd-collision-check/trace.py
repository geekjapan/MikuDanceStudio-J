"""Ordered diagnostic trace framing. No capture admission or semantic PASS."""
import re


def require(ok, message):
    if not ok:
        raise ValueError(message)


def _checkpoint(records, command, observed):
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
    return records


def frames(raw, inputs, *, observed=True):
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
                rows.append(_checkpoint(current, commands[len(rows)], observed))
                current = []
            require(words == ['Z', str(len(commands))] and len(rows) == len(commands), 'complete trace end')
            require(position == len(lines) - 1, 'last trace end')
            return rows
        require(words[0] in {'E', 'O', 'B', 'S', 'P', 'M', 'Q', 'J'}, 'known trace row')
        if words[1] == str(len(rows) + 1) and current:
            rows.append(_checkpoint(current, commands[len(rows)], observed))
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
    raise ValueError('missing complete trace end')


def common(rows):
    result = []
    for checkpoint in rows:
        projected = []
        for record in checkpoint:
            if record[0] in {'E', 'S', 'J'}:
                continue
            row = list(record)
            if row[0] == 'P':
                row[-1] = str(int(row[-1] != '0'))
            if row[0] == 'M':
                row[3:5] = ['1', '1']
            projected.append(row)
        result.append(projected)
    return result
