"""Strict checkpoint grammar. Semantic differences remain inspectable valid rows."""
import json


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, lo=0, hi=(1 << 64) - 1):
    require(type(value) is int and lo <= value <= hi, 'integer width or type')


def vector(value, width, lo=0, hi=(1 << 32) - 1):
    require(type(value) is list and len(value) == width, 'vector width')
    for item in value:
        integer(item, lo, hi)


def validate(raw, inputs, native):
    commands = inputs.splitlines()
    lines = raw.decode('utf-8').splitlines()
    require(len(lines) == len(commands), 'exact checkpoint count')
    rows = []
    history = -1
    for index, (line, command) in enumerate(zip(lines, commands)):
        row = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        require(type(row) is list and len(row) == 13, 'row schema')
        words = command.split()
        if words[0] == 'H':
            history = int(words[1])
        require(row[:3] == [history, index, words[0]], 'checkpoint identity/order')
        vector(row[3], 16)
        require(row[3][11:] == [1, 0, 10, 1, 0], 'default owned immediate policy')
        require(row[3][0] <= 1 and row[3][9] <= 1, 'counter enum width')
        require(type(row[4]) is list and len(row[4]) == 2, 'root membership')
        for root in row[4]:
            if root is not None:
                vector(root, 6)
        require(type(row[5]) is list and len(row[5]) == 3, 'stage membership')
        for stage in row[5]:
            vector(stage, len(stage), 0, 511)
        for field in [6, 7, 9, 10]:
            require(type(row[field]) is list, 'array type')
        for proxy in row[6]:
            require(type(proxy) is list and len(proxy) == 17, 'proxy width')
            vector(proxy[:2], 2)
            vector(proxy[2:4], 2, -32768, 32767)
            integer(proxy[4], 0, 2)
            vector(proxy[5:], 12)
        for pair in row[7]:
            vector(pair, 3)
            require(pair[0] < 512 and pair[1] < 512, 'pair owner width')
        integer(row[8], 0, (1 << 32) - 1)
        vector(row[9], len(row[9]))
        for manifold in row[10]:
            vector(manifold, 3)
            require(manifold[0] < 512 and manifold[1] < 512 and manifold[2] <= 4, 'manifold width')
        require(type(row[11]) is list and len(row[11]) == 2, 'tree counters')
        for leaves, lookahead, path in row[11]:
            integer(leaves, 0, (1 << 32) - 1)
            integer(lookahead, -(1 << 31), (1 << 31) - 1)
            integer(path, 0, (1 << 32) - 1)
        if native:
            require(type(row[12]) is list and len(row[12]) == 2, 'native rank trees')
            for nodes, free in row[12]:
                ranks = []
                for node in nodes:
                    require(type(node) is list and len(node) == 8, 'rank node width')
                    integer(node[0], -1, 511)
                    integer(node[1], 1)
                    vector(node[2:], 6)
                    ranks.append(node[1])
                if free is not None:
                    integer(free, 1)
                    ranks.append(free)
                require(len(set(ranks)) == len(ranks), 'unique actual ranks')
        else:
            require(row[12] is None, 'Rust ranks are private')
        rows.append(row)
    return rows


def bind_inputs(inputs, native_rows):
    lines = []
    for command, row in zip(inputs.splitlines(), native_rows):
        lines.append(command)
        fields = ['B']
        for nodes, free in row[12]:
            fields.append(str(len(nodes)))
            fields.extend(str(value) for node in nodes for value in node)
            fields.append('-' if free is None else str(free))
        lines.append(' '.join(fields))
    return '\n'.join(lines) + '\n'


def differences(native_rows, rust_rows):
    require(len(native_rows) == len(rust_rows), 'comparison count')
    return [i for i, (a, b) in enumerate(zip(native_rows, rust_rows)) if a[:12] != b[:12]]
