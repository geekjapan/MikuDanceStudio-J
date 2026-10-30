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



LAYOUT_FIELDS = {'pointer_bytes', 'node_bytes', 'node_alignment', 'node_type_alignment',
                 'node_volume_offset', 'node_parent_offset', 'node_childs_offset', 'raw_node_bytes',
                 'bt_has_aligned_allocator', 'bt_debug_memory_allocations', 'cellos_lv2'}
MACRO_FIELDS = {'bt_has_aligned_allocator', 'bt_debug_memory_allocations', 'cellos_lv2'}


def object_fields(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate receipt field')
        result[key] = value
    return result


def validate_layout(layout):
    require(type(layout) is dict and set(layout) == LAYOUT_FIELDS, 'native layout schema')
    for key in LAYOUT_FIELDS - MACRO_FIELDS:
        integer(layout[key])
    for key in MACRO_FIELDS:
        require(layout[key] is False, 'unknown allocator macro profile')
    require([layout[k] for k in ['pointer_bytes', 'node_alignment', 'node_volume_offset',
                                'node_parent_offset', 'node_childs_offset']] == [8, 16, 0, 32, 40],
            'unknown allocator layout')
    require((layout['node_bytes'], layout['node_type_alignment'], layout['raw_node_bytes'])
            in [(56, 8, 79), (64, 16, 87)], 'unknown native node layout')


def validate_profile(raw, policy):
    profile = json.loads(raw, object_pairs_hook=object_fields,
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    fields = {'pointer_bits', 'prevent_false_update', 'accurate_sleeping', 'margin_bits', 'bt_use_sse', 'win32'}
    require(type(profile) is dict and set(profile) == fields | LAYOUT_FIELDS, 'native profile schema')
    for key in fields - {'bt_use_sse', 'win32'}:
        integer(profile[key])
    require(profile['pointer_bits'] == 64, 'actual 64-bit consumer')
    require(profile['prevent_false_update'] == 0 and profile['accurate_sleeping'] == 0,
            'actual required broadphase compile policy')
    require(profile['margin_bits'] == 1028443341, 'actual native margin 0.05 bits')
    require(policy in ['generic-reference', 'mmd-win64-sse'], 'native profile policy')
    require(type(profile['bt_use_sse']) is bool and type(profile['win32']) is bool, 'native profile macro types')
    require(profile['bt_use_sse'] == (policy == 'mmd-win64-sse'), 'actual consumer SSE macro')
    validate_layout({key: profile[key] for key in LAYOUT_FIELDS})
    return profile


def validate_allocator(raw, rows, mode, profile):
    require(mode in ['ascending', 'descending', 'alternating', 'ordinary'], 'allocator mode')
    require(type(raw) is bytes and raw, 'required allocator receipt')
    records = [json.loads(line, object_pairs_hook=object_fields,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
               for line in raw.decode('utf-8').splitlines()]
    require(len(records) == len(rows) + 2, 'allocator checkpoint count')
    header = records[0]
    fields = {'schema', 'mode', 'hooks', 'arena_base', 'slots', 'stride', 'arena_alignment'} | LAYOUT_FIELDS
    require(type(header) is dict and set(header) == fields, 'allocator header schema')
    for key in fields - {'mode', 'hooks', 'bt_has_aligned_allocator', 'bt_debug_memory_allocations', 'cellos_lv2'}:
        integer(header[key])
    require(header['schema'] == 1 and header['mode'] == mode, 'allocator header identity')
    controlled = mode != 'ordinary'
    require(type(header['hooks']) is bool and header['hooks'] == controlled, 'actual allocator hooks')
    layout = {key: header[key] for key in LAYOUT_FIELDS}
    validate_layout(layout)
    require(layout == {key: profile[key] for key in LAYOUT_FIELDS}, 'allocator header matches native profile')
    require([header[k] for k in ['slots', 'stride', 'arena_alignment']] == [65536, 128, 64],
            'unknown allocator layout')
    base = header['arena_base']
    end = base + 65536 * 128
    require(base > 0 and base % 64 == 0 and end <= (1 << 64) - 1, 'arena pointer bounds/alignment')
    previous = [0, 0, 0, 0]
    live = set()
    cursor = 0
    cached = set()
    reused = False
    for index, record in enumerate(records[1:]):
        trailer = index == len(rows)
        expected = {'kind', 'counters', 'events'} | (set() if trailer else {'identity'})
        require(type(record) is dict and set(record) == expected, 'allocator record schema')
        require(record['kind'] == ('trailer' if trailer else 'checkpoint'), 'allocator record order')
        if not trailer:
            identity = record['identity']
            require(type(identity) is list and len(identity) == 3, 'allocator checkpoint identity')
            integer(identity[0], 0, (1 << 32) - 1)
            integer(identity[1], 0, (1 << 32) - 1)
            require(identity == rows[index][:3], 'allocator checkpoint identity/order')
        counters = record['counters']
        vector(counters, 4, 0, (1 << 64) - 1)
        require(all(a <= b for a, b in zip(previous, counters)), 'allocator counter monotonicity')
        require(counters[1] <= counters[0] and counters[3] <= counters[2], 'allocator free counter bounds')
        require(counters[2:] == [0, 0], 'current profile must use raw callbacks')
        require(type(record['events']) is list, 'allocator events array')
        if not controlled:
            require(counters == [0, 0, 0, 0] and record['events'] == [], 'ordinary callbacks disabled')
        minimum_callback_counts = previous.copy()
        freed = set()
        for event in record['events']:
            require(type(event) is dict and event.get('op') in ['alloc', 'free'], 'allocator event operation')
            alloc = event['op'] == 'alloc'
            require(set(event) == {'op', 'route', 'ordinal', 'pointer'} | ({'size', 'alignment'} if alloc else set()),
                    'allocator event schema')
            require(event['route'] == 'raw', 'actual callback route')
            counter = 0 if alloc else 1
            integer(event['ordinal'], 1)
            require(minimum_callback_counts[counter] < event['ordinal'] <= counters[counter], 'allocator callback ordinal/delta')
            minimum_callback_counts[counter] = event['ordinal']
            pointer = event['pointer']
            integer(pointer, 1)
            if alloc:
                integer(event['size'])
                integer(event['alignment'])
                require(event['size'] == header['raw_node_bytes']
                        and event['alignment'] == 0, 'raw node backing request')
                require(cursor < 65536, 'arena slot exhaustion')
                slot = cursor
                if mode == 'descending':
                    slot = 65535 - cursor
                elif mode == 'alternating':
                    slot = 65535 - cursor // 2 if cursor % 2 else cursor // 2
                require(pointer == base + slot * 128, 'actual allocation slot order')
                require(pointer not in live, 'reissued live arena slot')
                live.add(pointer)
                cursor += 1
            else:
                require(pointer in live, 'unknown or double arena free')
                live.remove(pointer)
                freed.add(pointer + 16)
                minimum_callback_counts[0] = max(minimum_callback_counts[0], minimum_callback_counts[1] + len(live))
                require(minimum_callback_counts[0] <= counters[0], 'allocator counter history')
        require(counters[0] - counters[1] >= len(live), 'allocator counter history')
        if not trailer:
            active = set()
            next_cached = set()
            seen = set()
            for nodes, free in rows[index][12]:
                pointers = [node[1] for node in nodes]
                active.update(pointers)
                if free is not None:
                    pointers.append(free)
                    next_cached.add(free)
                for pointer in pointers:
                    integer(pointer, 1)
                    require(pointer not in seen, 'unique live and cached addresses across trees')
                    seen.add(pointer)
                    if controlled:
                        backing = pointer - 16
                        require(backing in live and base <= backing < end and (backing-base) % 128 == 0
                                and pointer % 16 == 0 and pointer + header['node_bytes'] <= backing + 128,
                                'live/cached node must belong to current arena allocation')
                    else:
                        require(not base <= pointer < end, 'ordinary nodes outside arena')
            reused |= bool((cached - freed) & active)
            cached = next_cached
        previous = counters
    require(not live, 'final arena frees complete')
    require(previous[0] == previous[1] and previous[2] == previous[3], 'final callback balance')
    if controlled:
        require(previous[0] > 0 and cursor > 0, 'actual nonzero raw allocation callbacks')
        require(reused, 'genuine cached-free to live reuse without callback free')
    return {'allocations': cursor, 'cache_reuse': reused, 'checkpoints': len(rows)}
