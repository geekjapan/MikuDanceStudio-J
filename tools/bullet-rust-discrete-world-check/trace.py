import json
import re
from hooks import require


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'duplicate receipt field')
        value[key] = item
    return value


def decode_json(raw):
    return json.loads(raw, object_pairs_hook=unique_object)


def integer(text, low=0, high=(1 << 64) - 1):
    require(re.fullmatch(r'-?(0|[1-9][0-9]*)', text) is not None, 'canonical integer')
    value = int(text)
    require(low <= value <= high, 'integer range')
    return value


def words(values):
    require(all(re.fullmatch('[0-9a-f]{8}', v) is not None for v in values), 'float word framing')


def validate(raw, inputs, *, native=False, observed=True):
    commands = inputs.splitlines()
    lines = raw.decode('ascii').splitlines()
    require(lines and lines[-1] == 'Z ' + str(len(commands)), 'complete trace terminator')
    rows = [{'events': [], 'bodies': [], 'pairs': [], 'manifolds': [], 'contacts': [], 'trees': []} for _ in commands]
    previous = -1
    for line in lines[:-1]:
        fields = line.split(' ')
        require('' not in fields and len(fields) >= 3, 'strict trace framing')
        kind = fields[0]
        require(kind in {'E', 'O', 'B', 'P', 'M', 'Q', 'T'}, 'known trace record')
        row = integer(fields[1], 0, len(commands) - 1)
        require(previous <= row <= previous + 1, 'ordered contiguous trace rows')
        previous = row
        target = rows[row]
        if kind == 'E':
            require(observed and 'header' not in target, 'events precede snapshot')
            event = fields[2]
            require(event in {'A+', 'A-', 'M+', 'M-', 'U'}, 'known lifetime event')
            require(len(fields) == (6 if event == 'M+' else 4), 'event width')
            values = [integer(v) for v in fields[3:]]
            target['events'].append([event, *values])
        elif kind == 'O':
            require(len(fields) == 7 and 'header' not in target, 'one complete snapshot header')
            require(fields[2] == commands[row].split()[0], 'actual operation binding')
            target['header'] = [fields[2], *[integer(v, 0, 100000) for v in fields[3:]]]
            require(target['header'][-1] in (0, 1), 'force flag boolean')
        else:
            require('header' in target, 'snapshot header precedes records')
            if kind == 'B':
                require(len(fields) == 57, 'initialized body record width')
                require(integer(fields[2]) == len(target['bodies']), 'body registration order')
                integer(fields[3], -1, 7); integer(fields[4], 0, 5)
                integer(fields[5], 1, (1 << 31)-1)
                for field in fields[6:8]: integer(field, -32768, 32767)
                require(integer(fields[8]) == int(fields[2]), 'proxy owner identity')
                words(fields[9:]); target['bodies'].append(fields[3:])
            elif kind == 'P':
                require(len(fields) == 6 and integer(fields[2]) == len(target['pairs']), 'pair order and width')
                target['pairs'].append([integer(v) for v in fields[3:]])
            elif kind == 'M':
                require(len(fields) == 10 and integer(fields[2]) == len(target['manifolds']), 'manifold order and width')
                values = [integer(v) for v in fields[3:7]]
                words(fields[7:9]); integer(fields[9], 0, 4)
                target['manifolds'].append([*values, *fields[7:9], int(fields[9])])
            elif kind == 'Q':
                require(len(fields) in (27, 33), 'contact initialized word width')
                manifold = integer(fields[2], 0, len(target['manifolds']) - 1)
                contact = integer(fields[3], 0, 3)
                require(contact == sum(q[0] == manifold for q in target['contacts']), 'contact order')
                words(fields[4:25]); integer(fields[25], 0, (1 << 31)-1)
                require(fields[26] in ('0', '1') and len(fields) == 27 + 6*int(fields[26]), 'only initialized lateral directions')
                words(fields[27:]); target['contacts'].append([manifold, contact, *fields[4:]])
            else:
                require(native and len(fields) >= 5, 'native tree receipt')
                tree = integer(fields[2], 0, 1); count = integer(fields[3], 0, 100000)
                require(tree == len(target['trees']) and len(fields) == 5 + 8*count, 'tree order and coverage')
                nodes = []
                for start in range(4, 4 + 8*count, 8):
                    owner = integer(fields[start], -1, 100000); address = integer(fields[start+1], 1)
                    words(fields[start+2:start+8]); nodes.append([owner, address, *fields[start+2:start+8]])
                target['trees'].append([nodes, integer(fields[-1])])
    algorithms, manifolds = set(), {}
    next_algorithm = next_manifold = 0
    registered = 0
    scope = None
    for index, (row, command) in enumerate(zip(rows, commands)):
        require('header' in row, 'missing operation snapshot')
        op, bodies, pairs, count, _ = row['header']
        if op == 'H':
            require(not registered and not algorithms and not manifolds, 'new owner starts empty')
            scope = command.split()[2]
        require(op not in {'A', 'I', 'V'} or scope == 'injected', 'explicit generated fixture boundary')
        expected = registered + (op == 'C')
        unregister = []
        for event, *values in row['events']:
            if event == 'A+':
                next_algorithm += 1; require(values[0] == next_algorithm, 'algorithm allocation generation')
                algorithms.add(values[0])
            elif event == 'A-':
                require(values[0] in algorithms, 'synchronous live algorithm release')
                require(all(m[0] != values[0] for m in manifolds.values()), 'manifold released before algorithm free')
                algorithms.remove(values[0])
            elif event == 'M+':
                next_manifold += 1; require(values[0] == next_manifold, 'separate manifold allocation generation')
                require(all(v < expected for v in values[1:]), 'manifold body ownership')
                manifolds[values[0]] = [None, *values[1:]]
            elif event == 'M-':
                require(values[0] in manifolds, 'synchronous live manifold release'); del manifolds[values[0]]
            else:
                require(op == 'X', 'ordinary removal is outside wrapper scope'); unregister.append(values[0])
        if op == 'X':
            if observed: require(unregister == list(range(registered-1, -1, -1)), 'reverse logical unregister')
            require(not algorithms and not manifolds, 'teardown releases all algorithms and manifolds')
            expected = 0
        require(bodies == expected and len(row['bodies']) == bodies and len(row['pairs']) == pairs and len(row['manifolds']) == count, 'complete body/pair/manifold snapshot')
        registered = expected
        seen_pairs = set()
        for a, b, generation in row['pairs']:
            require(a < bodies and b < bodies and a != b and (a, b) not in seen_pairs, 'live ordered pair ownership')
            seen_pairs.add((a, b))
            require(not observed or generation == 0 or generation in algorithms, 'live algorithm generation')
        if observed:
            require({p[2] for p in row['pairs'] if p[2]} == algorithms, 'every algorithm belongs to a pair')
            require({m[0] for m in row['manifolds']} == set(manifolds), 'independent complete manifold ledger')
        for i, manifold in enumerate(row['manifolds']):
            generation, algorithm, a, b, _, _, contacts = manifold
            require(a < bodies and b < bodies, 'manifold bodies')
            require(contacts == sum(q[0] == i for q in row['contacts']), 'complete contact snapshot')
            if observed:
                require(algorithm in algorithms and manifolds[generation][1:] == [a,b], 'manifold owner and lifetime binding')
                manifolds[generation][0] = algorithm
        if native and op != 'X':
            require(len(row['trees']) == 2, 'both actual tree receipts')
            nodes = [node for tree, _ in row['trees'] for node in tree]
            leaves = [n for n in nodes if n[0] >= 0]
            require(sorted(n[0] for n in leaves) == list(range(bodies)), 'each proxy owns one native leaf')
            addresses = [n[1] for n in nodes] + [free for _, free in row['trees'] if free]
            require(len(addresses) == len(set(addresses)), 'disjoint live and cached-free native nodes')
            for node in leaves:
                require(node[2:] == row['bodies'][node[0]][48:], 'leaf volume bound to proxy')
        else:
            require(not row['trees'], 'no fabricated tree receipt')
    require(not registered and not algorithms and not manifolds, 'terminal owner drop complete')
    return rows


def comparison(rows, observation=True):
    result = []
    for row in rows:
        value = {k: v for k, v in row.items() if k != 'trees'}
        if not observation:
            value = {**value, 'events': [], 'pairs': [p[:2] + [int(p[2] != 0)] for p in value['pairs']],
                     'manifolds': [[1, 1, *m[2:]] for m in value['manifolds']]}
        result.append(value)
    return result


def bind_inputs(inputs, rows):
    bound = []
    for command, row in zip(inputs.splitlines(), rows):
        bound.append(command)
        if row['trees']:
            fields = ['BIND']
            for nodes, free in row['trees']:
                fields.append(str(len(nodes)))
                fields.extend(str(v) for node in nodes for v in node)
                fields.append(str(free))
            bound.append(' '.join(fields))
    return '\n'.join(bound) + '\n'


def validate_allocator(raw, rows, mode, *, domain):
    records = [decode_json(line) for line in raw.decode().splitlines()]
    require(len(records) == len(rows)+2, 'complete allocator lifetime receipt')
    header = records[0]
    require(set(header) == {'schema','domain','mode','arena_base','slots','stride','node_bytes','raw_node_bytes','node_type_alignment'}, 'allocator header fields')
    require(domain in {'unmodified-control','generated-dbvt-node-sites'} and header['domain']==domain, 'allocator evidence domain')
    require(all(type(header[key]) is int for key in ['schema','arena_base','slots','stride','node_bytes','raw_node_bytes','node_type_alignment']), 'allocator header integer fields')
    require(header['schema'] == 2 and header['mode'] == mode and mode in {'ascending','descending','alternating','ordinary'} and header['slots'] == 65536 and header['stride'] == 128, 'actual allocator mode/layout')
    require((header['node_bytes'],header['node_type_alignment']) in {(56,8),(64,16)} and header['raw_node_bytes'] == header['node_bytes']+23, 'supported original node layout')
    require(header['arena_base'] > 0 and header['arena_base'] % 64 == 0, 'aligned actual allocator arena')
    live, allocation, nodes = {}, 0, {}
    ordinals = {}; counters = [0]*4; node_counts=[0]*4
    sequence=call=generation=world=0
    trees=None; history=[]
    observed=domain=='generated-dbvt-node-sites'
    for index, record in enumerate(records[1:]):
        require(set(record) == {'kind','counters','events','world','trees','node_counters','nodes'} and record['kind'] == (index if index < len(rows) else 'final') and (type(record['kind']) is int if index<len(rows) else True), 'allocator checkpoint identity')
        require(type(record['counters']) is list and len(record['counters']) == 4 and all(type(n) is int and n >= old for n,old in zip(record['counters'],counters)), 'allocator monotonic counters')
        counters = record['counters']
        require(type(record['world']) is int and type(record['trees']) is list and len(record['trees'])==2 and all(type(n) is int and n>0 for n in record['trees']) and len(set(record['trees']))==2, 'genuine world tree binding')
        if index<len(rows) and rows[index].get('header',[''])[0]=='H':
            require(not nodes and record['world']==world+1,'new world generation')
            world=record['world'];trees=record['trees']
        elif trees is None:
            require(record['world']==1,'initial world generation');world=1;trees=record['trees']
        require(record['world']==world and record['trees']==trees,'world tree binding through destruction')
        scoped={}; normalized=[]
        require(type(record['events']) is list,'candidate events array')
        for event in record['events']:
            require(type(event) is dict and mode != 'ordinary' and event['op'] in {'alloc','free'} and event['route'] in {'aligned','raw'}, 'actual allocator event route')
            require(set(event) == ({'op','route','ordinal','pointer','size','alignment','node_call'} if event['op']=='alloc' else {'op','route','ordinal','pointer','node_call'}), 'exact actual allocator event fields')
            require(all(type(event[key]) is int and event[key]>=0 for key in set(event)-{'op','route'}),'allocator event integer fields')
            route=(event['op'],event['route'])
            counter_index={('alloc','raw'):0,('free','raw'):1,('alloc','aligned'):2,('free','aligned'):3}[route]
            require(ordinals.get(route,0)<event['ordinal']<=counters[counter_index], 'actual allocator callback ordinal prefix')
            ordinals[route]=event['ordinal'];ptr=event['pointer']
            require(ptr>0,'actual allocator pointer')
            if event['op'] == 'alloc':
                slot = allocation
                if mode == 'descending': slot = header['slots']-1-allocation
                if mode == 'alternating': slot = allocation//2 if allocation%2 == 0 else header['slots']-1-allocation//2
                require(allocation<header['slots'] and ptr == header['arena_base']+slot*128 and ptr not in live, 'real controlled candidate allocation order')
                allocation += 1
                require(event['size'] == (header['node_bytes'] if event['route'] == 'aligned' else header['raw_node_bytes']), 'actual candidate allocation size')
                require(event['alignment'] == (16 if event['route'] == 'aligned' else 0), 'actual candidate allocation alignment')
                value=(event['route'],ptr if event['route']=='aligned' else ptr+16,allocation)
                live[ptr]=value
            else:
                require(ptr in live and live[ptr][0]==event['route'], 'real free matches prior allocation route')
                value=live.pop(ptr)
            normalized.append((event['op'],event['route'],event['ordinal'],(ptr-header['arena_base'])//128,value[2],event.get('size'),event.get('alignment')))
            if event['node_call']:
                require(observed and event['node_call'] not in scoped,'unique scoped raw callback')
                scoped[event['node_call']]=(event['op'],value[1],value[2])
        require(type(record['nodes']) is list and type(record['node_counters']) is list and len(record['node_counters'])==4, 'typed node receipt arrays')
        for event in record['nodes']:
            require(observed and type(event) is dict and set(event)=={'op','sequence','call','world','tree','pointer','generation'}, 'exact typed node event fields')
            require(all(type(event[key]) is int and event[key]>=0 for key in set(event)-{'op'}),'typed node integer fields')
            op=event['op'];p=event['pointer'];g=event['generation'];t=event['tree']
            require(op in {'alloc','free','reuse','cache'} and event['sequence']==sequence+1 and event['world']==world and t in {0,1}, 'typed sequence world and tree')
            sequence+=1;node_counts[{'alloc':0,'free':1,'reuse':2,'cache':3}[op]]+=1
            raw_generation=None
            if op in {'alloc','free'}:
                require(event['call']==call+1,'monotonic nonnested node call');call+=1
                if mode!='ordinary' and p:
                    require(call in scoped and scoped[call][:2]==(op,p),'typed scoped callback route and aligned pointer')
                    raw_generation=scoped.pop(call)[2]
                else: require(call not in scoped,'null or ordinary node call has no callback')
            else: require(event['call']==0,'cache transition has no allocation call')
            if op=='alloc':
                require(p>0 and p not in nodes and g==generation+1,'fresh node generation')
                generation=g;nodes[p]=(world,t,g,'active',raw_generation)
            elif op=='free' and p==0:
                require(g==0,'null free has no generation')
            else:
                require(p in nodes and nodes[p][:3]==(world,t,g),'live typed node tree and generation')
                entry=nodes[p]
                if op=='free':
                    require(entry[3]=='cached' and (mode=='ordinary' or entry[4]==raw_generation),'cached node physical generation free')
                    del nodes[p]
                elif op=='reuse':
                    require(entry[3]=='cached','cached node reuse');nodes[p]=(*entry[:3],'active',entry[4])
                else:
                    require(entry[3]=='active' and not any(n[1]==t and n[3]=='cached' for n in nodes.values()),'one cached node per tree')
                    nodes[p]=(*entry[:3],'cached',entry[4])
        require(not scoped,'all scoped raw callbacks have typed events')
        require(all(type(n) is int for n in record['node_counters']) and record['node_counters']==node_counts,'complete typed event counters')
        retained={}
        if index<len(rows):
            for t,(tree,free) in enumerate(rows[index]['trees']):
                for node in tree:
                    require(node[1] not in retained,'disjoint typed snapshot nodes');retained[node[1]]=(t,'active')
                if free:
                    require(free not in retained,'disjoint typed cached node');retained[free]=(t,'cached')
            if mode!='ordinary':require(set(retained)<={value[1] for value in live.values()},'original tree/cache backed by live candidates')
            if observed:require({p:(n[1],n[3]) for p,n in nodes.items()}==retained,'proven nodes exhaust actual tree/cache snapshot')
        else:require(not nodes,'all proven nodes freed by final checkpoint')
        if mode=='ordinary':require(counters==[0]*4,'ordinary mode has no raw callbacks')
        history.append((tuple(counters),normalized,tuple(sorted((p-header['arena_base'],*value[::2]) for p,value in live.items()))))
    require(not live and not nodes, 'all candidates and proven nodes freed by owner drop')
    return header,history


def validate_noninterference(control_raw, control, observed_raw, observed, mode):
    a,ah=validate_allocator(control_raw,control,mode,domain='unmodified-control')
    b,bh=validate_allocator(observed_raw,observed,mode,domain='generated-dbvt-node-sites')
    require(comparison(control,False)==comparison(observed,False),'unmodified native observer control '+mode)
    if mode!='ordinary':require(ah==bh,'complete candidate history noninterference '+mode)
    def topology(rows,header):
        result=[]
        for row in rows:
            trees=[]
            for nodes,free in row['trees']:
                if mode=='ordinary':
                    trees.append(([(node[0],*node[2:]) for node in nodes],bool(free)))
                else:
                    trees.append(([(node[0],node[1]-header['arena_base'],*node[2:]) for node in nodes],free-header['arena_base'] if free else None))
            result.append(trees)
        return result
    require(topology(control,a)==topology(observed,b),'tree topology owners volumes and cache noninterference '+mode)


def validate_physical(raw, inputs):
    records = [line.split() for line in raw.decode('ascii').splitlines()]
    cursor = 0
    bodies, joints = 0, []
    for row, command in enumerate(inputs.splitlines()):
        op = command.split()[0]
        if op == 'C': bodies += 1
        if op == 'J':
            require(cursor < len(records), 'physical joint creation receipt')
            entry = records[cursor]; cursor += 1
            require(len(entry)==4 and entry[:3]==['JOINT_CREATE',str(row),str(len(joints))], 'native joint registration identity')
            pointer = integer(entry[3],1)
            require(pointer not in joints,'distinct live native joints');joints.append(pointer)
        if op == 'X':
            expected = [('joint',pointer,-1) for pointer in reversed(joints)] + [('body',None,i) for i in range(bodies-1,-1,-1)]
            for kind,pointer,owner in expected:
                require(cursor<len(records),'complete native physical delete ledger')
                entry=records[cursor];cursor+=1
                require(len(entry)==5 and entry[:3]==['PHYSICAL',str(row),kind], 'reverse native joint-before-body physical delete order')
                actual=integer(entry[3],1)
                require(pointer is None or pointer==actual,'native joint pointer lifetime')
                require(integer(entry[4],-1)==owner,'native physical body owner order')
            bodies=0;joints=[]
    require(cursor==len(records) and not bodies and not joints,'no extra or missing native physical events')
