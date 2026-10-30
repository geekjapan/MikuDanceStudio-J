"""Parse safe Q plus closed friction records without reading or inventing values."""
import hashlib

from friction_schema import MAX_EVENTS, ROLES, VARIANTS, diagnostic, field, require, tokens, unsigned
from friction_ledger import Ledger
from trace import frames


class Capture:
    def __init__(self, variant, role, corpus_sha):
        self.variant = variant
        self.role = role
        self.corpus_sha = corpus_sha
        self.base = []
        self.directions = {}
        self.physical = {}
        self.bindings = {}
        self.history = []
        self.maxima = {}
        self.closed = 0


def _original_mask(flag, command):
    # This policy requires the original-only writer/callback/schedule source proof.
    return 3 if command.split()[0] == 'W' else int(flag)


def _signed(value, minimum=-2147483648, maximum=2147483647):
    if value.startswith('-'):
        number = -unsigned(value[1:], 1, 2147483648)
    else:
        number = unsigned(value)
    require(minimum <= number <= maximum, 'canonical signed integer range')


def _base_types(row):
    tag = row[0]
    if tag == 'O':
        require(len(row) == 6, 'exact O width')
        for value in row[3:]:
            unsigned(value)
    elif tag == 'B':
        require(len(row) == 66, 'exact B width')
        for index in (2, 3, 5, 8, *range(60, 66)):
            unsigned(row[index])
        unsigned(row[4], 0, 5)
        for value in row[6:8]:
            _signed(value, -32768, 32767)
        for value in row[9:60]:
            field(value, 'w')
    elif tag == 'P':
        require(len(row) == 8, 'exact P width')
        for value in row[2:]:
            unsigned(value)
    elif tag == 'M':
        require(len(row) == 10, 'exact M width')
        for value in row[2:7]:
            unsigned(value)
        for value in row[7:9]:
            field(value, 'w')
        unsigned(row[9], 0, 4)
    elif tag == 'Q':
        require(len(row) == 27, 'exact safe Q width')
        unsigned(row[2])
        unsigned(row[3], 0, 3)
        for value in row[4:25]:
            field(value, 'w')
        unsigned(row[25])
        field(row[26], 'b')
    elif tag == 'S':
        require(len(row) >= 4, 'complete S header')
        unsigned(row[2], 0, 2)
        count = unsigned(row[3])
        require(count <= (len(row) - 4) // 2 and len(row) == 4 + 2 * count, 'exact bounded S width')
        for value in row[4:]:
            unsigned(value)
    elif tag == 'J':
        require(len(row) == 24, 'exact J width')
        unsigned(row[2])
        _signed(row[3])
        for index in (4, 5, *range(6, 24, 3)):
            unsigned(row[index], 0, 1)
        for index in range(6, 24, 3):
            field(row[index + 1], 'w')
            field(row[index + 2], 'w')
    elif tag == 'W':
        require(len(row) == 41, 'exact W width')
        unsigned(row[2])
        _signed(row[3])
        _signed(row[4])
        for value in row[5:]:
            field(value, 'w')
    elif tag in ('STATUS', 'R'):
        require(len(row) == 3, 'exact status/return width')
        unsigned(row[2])
    elif tag == 'K':
        require(len(row) == 6, 'exact K width')
        unsigned(row[2])
        unsigned(row[3])
        field(row[4], 'w')
        field(row[5], 'w')
    elif tag == 'V':
        require(len(row) == 4, 'exact V width')
        unsigned(row[2], 0, 0)
        unsigned(row[3])
    elif tag == 'Y':
        require(len(row) >= 3 and row[2] in ('P', 'G', 'A'), 'known solver schedule site')
        if row[2] == 'A':
            require(len(row) == 3, 'exact allSolved width')
        elif row[2] == 'P':
            require(len(row) == 5, 'exact prepare width')
            unsigned(row[3])
            unsigned(row[4])
        else:
            require(len(row) >= 7, 'complete solver group header')
            _signed(row[3])
            for value in row[4:]:
                unsigned(value)


def parse(raw, inputs, *, variant, role, corpus_sha):
    require(variant in VARIANTS and role in ROLES, 'fixed variant/allocator role')
    require(type(inputs) is str and inputs.endswith('\n'), 'complete command corpus')
    require(hashlib.sha256(inputs.encode('ascii')).hexdigest() == corpus_sha, 'exact corpus identity')
    commands = inputs.splitlines()
    require(commands and len(commands) <= 2147483647, 'bounded nonempty command count')
    observed, rust = variant.endswith('-observed'), variant.startswith('rust-')
    ledger = Ledger(not rust) if observed else None
    capture = Capture(variant, role, corpus_sha)
    rows = iter(tokens(raw))
    header = next(rows)
    require(header == ['FH', '3', variant, role, corpus_sha, str(len(commands))], 'exact first header')
    seq = 0
    cp = 0
    ended = False
    base_end = False
    base_raw = []
    current_q = None
    pending = []
    fs = None
    fl = None
    last_base = None
    last_base_cp = -1
    snapshot_mids = set()
    algorithms, base_manifolds, manifold_owners = set(), {}, {}
    used_algorithms, used_manifolds = set(), set()
    e_update = None
    next_tag = None

    def close_checkpoint(index):
        nonlocal snapshot_mids
        if index < 0:
            return
        require(not pending and fl is None, 'complete contact direction/physical rows')
        if observed:
            require(set(ledger.manifolds) == snapshot_mids, 'complete ordered friction manifold snapshot')
            require(set(base_manifolds) == snapshot_mids, 'base lifecycle and friction manifold snapshot agree')
        if commands[index].split()[0] == 'X' and observed:
            require(not ledger.manifolds and not ledger.points and not ledger.temporary and not ledger.transactions,
                    'command X closes all logical generations')
            require(not algorithms and not base_manifolds and not manifold_owners, 'command X closes base world lifetimes')
        require(e_update is None, 'closed actual AABB update')
        snapshot_mids = set()

    for row in rows:
        require(not ended, 'no trailing data after footer')
        tag = row[0]
        if observed:
            ledger.order(tag, row[3] if tag.startswith('F') and len(row) >= 4 else None)
        if observed and not rust and ledger.pending_added is not None:
            require(tag == 'FG', 'no base/sidecar events between insertion exit and Added precall')
        require(next_tag is None or tag == next_tag, 'immediate combined snapshot order ' + str(next_tag))
        next_tag = None
        if tag == 'FZ':
            require(len(row) == 4 and base_end and not pending and fl is None, 'unique footer after complete base end')
            count, command_count, closed = (unsigned(value) for value in row[1:])
            require(count == seq and command_count == len(commands), 'recomputed footer event/command counts')
            if observed:
                ledger.finish(len(commands))
                require(closed == ledger.closed, 'recomputed closed generation count')
                capture.history = ledger.history
                capture.maxima = ledger.maxima
            else:
                require(closed == 0, 'original has no fabricated generation count')
            capture.closed = closed
            ended = True
            continue
        require(not base_end or tag == 'FG', 'only command-end guard after base end')
        if tag.startswith('F'):
            parsed_tag, at, order, site, values = diagnostic(row)
            require(parsed_tag == tag and order == seq + 1 and order <= MAX_EVENTS, 'contiguous diagnostic sequence')
            require(cp <= at < len(commands), 'ordered bounded diagnostic checkpoint')
            if at != cp:
                close_checkpoint(cp)
                fs = None
                require(at == cp + 1, 'complete checkpoint schedule')
                cp = at
            seq = order
            if not observed:
                require(tag in ('FD', 'FP'), 'original has no fabricated observations')
            if pending:
                expected = pending.pop(0)
                require(tag == expected[0] and values[:3] == expected[1:], 'exact ordered Q/FD/FP correspondence')
                require(current_q is not None, 'direction row has actual Q')
                key = (at, values[0], values[1], values[2])
                if tag == 'FD':
                    state, count = values[3:5]
                    words = values[5:]
                    require(key not in capture.directions, 'one direction row per actual contact/direction')
                    if observed:
                        require(fl is not None, 'observed Q has FL')
                        mask = ledger.points[fl[3]]
                        expected_state = 'D' if mask & values[2] else 'U'
                    else:
                        expected_state = 'D' if _original_mask(current_q[26] == 'true', commands[at]) & values[2] else 'O'
                    require(state == expected_state, 'direction state from independent write obligation/original guarantee')
                    require(state == 'D' and count == 3 and len(words) == 3
                            or state != 'D' and count == 0 and not words, 'exact lawful direction scalar visibility')
                    capture.directions[key] = (state, words)
                else:
                    require(rust and key not in capture.physical, 'one Rust physical triple per contact/direction')
                    capture.physical[key] = values[3:]
                    if key in capture.directions and capture.directions[key][0] == 'D':
                        require(capture.directions[key][1] == capture.physical[key], 'Rust D equals its own physical triple')
                if not pending:
                    current_q = None
                    fl = None
                    if observed and fs is not None and fs[3] < fs[2]:
                        next_tag = 'FL'
                else:
                    next_tag = pending[0][0]
                continue
            require(tag not in ('FD', 'FP'), 'no orphan direction/physical records')
            if tag == 'FG':
                ledger.guard(at, site, values)
            elif tag == 'FS':
                mi, mid, count = values
                require(last_base is not None and last_base[0] == 'M' and last_base[1:3] == [str(at), str(mi)],
                        'FS follows actual M row')
                require(mid == unsigned(last_base[3], 1) and count == unsigned(last_base[-1], 0, 4)
                        and mid not in snapshot_mids and mid in ledger.manifolds,
                        'actual manifold index/count/generation snapshot binding')
                require(len(ledger.manifolds[mid][1]) == count, 'complete live contact count')
                require(ledger.manifolds[mid][0] == tuple(unsigned(value) for value in last_base[5:7]), 'actual ordered manifold body pair')
                ledger.snapshot(mid, list(ledger.manifolds[mid][1]), ledger.manifolds[mid][0])
                snapshot_mids.add(mid)
                fs = (mi, mid, count, 0)
                if count:
                    next_tag = 'FL'
            elif tag == 'FL':
                mi, slot, mid, gid, mask, flag = values
                require(fl is None and fs is not None and (mi, mid) == fs[:2]
                        and slot == fs[3] and slot < fs[2], 'complete increasing FL contact order')
                ledger._binding(mid, slot, gid)
                require(mask == ledger.points[gid], 'snapshot independently reconstructed persistent validity')
                fl = values
                fs = (*fs[:3], fs[3] + 1)
                capture.bindings[(at, mi, slot)] = (mid, gid)
                next_tag = 'Q'
            else:
                require(fl is None, 'FL immediately before actual Q')
                ledger.event(at, tag, site, values)
            continue
        require(not pending and fl is None or tag == 'Q' and fl is not None and not pending,
                'combined output order FL/Q/FD/FP')
        if tag == 'Z':
            require(row == ['Z', str(len(commands))], 'complete base trace end')
            close_checkpoint(cp)
            require(cp == len(commands) - 1, 'all actual command checkpoints present')
            base_end = True
            base_raw.append(' '.join(row))
            continue
        require(len(row) >= 2 and unsigned(row[1]) < len(commands), 'bounded actual base checkpoint')
        at = unsigned(row[1])
        require(at in (cp, cp + 1), 'ordered actual base checkpoint')
        if at != cp:
            close_checkpoint(cp)
            fs = None
            cp = at
        require(at >= last_base_cp, 'nondecreasing actual base checkpoint')
        last_base_cp = at
        _base_types(row)
        if tag == 'Q':
            require(len(row) == 27 and row[26] in ('true', 'false'), 'safe27 Q with actual boolean')
            mi, slot = unsigned(row[2]), unsigned(row[3], 0, 3)
            if observed:
                require(fl is not None and fl[:2] == (mi, slot) and fl[5] == (row[26] == 'true'), 'FL agrees with actual Q and flag')
            current_q = row
            pending = [('FD', mi, slot, 1), ('FD', mi, slot, 2)]
            if rust:
                pending += [('FP', mi, slot, 1), ('FP', mi, slot, 2)]
            next_tag = 'FD'
            # Only the framing adapter sees false; capture.base retains the real flag.
            base_raw.append(' '.join(row[:26] + ['0']))
        else:
            require(tag in ('O', 'B', 'P', 'M', 'E', 'S', 'J', 'W', 'STATUS', 'R', 'K', 'Y', 'V'), 'known base trace tag')
            if tag == 'M' and observed:
                require(fs is None or fs[3] == fs[2], 'previous manifold has all FL rows')
            if tag == 'E':
                require(observed and len(row) >= 4, 'base lifecycle observations only in observed variants')
                event, identity = row[2], unsigned(row[3])
                require(len(row) == (6 if event == 'M+' else 4), 'exact base lifecycle width')
                if event == 'A+':
                    require(identity > 0 and identity not in used_algorithms, 'fresh base algorithm identity')
                    algorithms.add(identity)
                    used_algorithms.add(identity)
                elif event == 'A-':
                    require(identity in algorithms and identity not in manifold_owners.values(), 'release base algorithm after manifolds')
                    algorithms.remove(identity)
                elif event == 'M+':
                    require(identity > 0 and identity not in used_manifolds, 'fresh base manifold identity')
                    base_manifolds[identity] = tuple(unsigned(value) for value in row[4:6])
                    used_manifolds.add(identity)
                elif event == 'M-':
                    require(identity in base_manifolds, 'release live base manifold')
                    del base_manifolds[identity]
                    manifold_owners.pop(identity, None)
                elif event == 'U+':
                    require(e_update is None, 'single base AABB update')
                    e_update = identity
                elif event == 'U-':
                    require(e_update == identity, 'matching actual base AABB update end')
                    e_update = None
                else:
                    require(event == 'U', 'known base lifecycle event')
            elif tag == 'M' and observed:
                require(len(row) == 10, 'complete actual manifold row')
                mid, owner = unsigned(row[3], 1), unsigned(row[4], 1)
                require(mid in base_manifolds and owner in algorithms and base_manifolds[mid] == tuple(unsigned(value) for value in row[5:7]),
                        'actual base manifold algorithm/body binding')
                require(mid not in manifold_owners or manifold_owners[mid] == owner, 'persistent actual base algorithm owner')
                manifold_owners[mid] = owner
                next_tag = 'FS'
            base_raw.append(' '.join(row))
        capture.base.append(tuple(row))
        last_base = row
    require(ended and base_end, 'complete diagnostic/base footer')
    require(fs is None or fs[3] == fs[2], 'last manifold has complete contact rows')
    require(not observed or not algorithms and not base_manifolds and not manifold_owners, 'complete base lifetime closure')
    frames(('\n'.join(base_raw) + '\n').encode('ascii'), inputs, observed=observed, dynamics=True)
    if rust:
        require(set(capture.physical) == set(capture.directions), 'full Rust physical direction coverage')
    else:
        require(not capture.physical, 'no invented native physical values')
    return capture


def compare_physical(original, observed):
    require(original.variant == 'rust-original' and observed.variant == 'rust-observed', 'unchanged/observed Rust roles')
    require(original.role == observed.role and original.corpus_sha == observed.corpus_sha, 'same role/corpus physical comparison')
    require(tuple(original.physical) == tuple(observed.physical), 'full physical key/length/order equality')
    for key in original.physical:
        require(original.physical[key] == observed.physical[key], 'Rust physical numerical difference at ' + repr(key))


def compare_defined(native, rust):
    require(native.variant.startswith('native-') and rust.variant.startswith('rust-'), 'native/Rust value comparison roles')
    require(native.role == rust.role and native.corpus_sha == rust.corpus_sha, 'same role/corpus direction comparison')
    require(tuple(native.directions) == tuple(rust.physical), 'full ordered native/Rust contact/direction coverage')
    for key, (state, words) in native.directions.items():
        if state == 'D':
            require(words == rust.physical[key], 'DEFINED numerical difference at ' + repr(key))
