"""Complete field/value comparisons after independent stream validation.

These functions do not provide the missing producer/source/link receipts.
"""
from friction_schema import require
from friction_trace import compare_defined, compare_physical

COMMON = frozenset(('O', 'B', 'P', 'M', 'Q', 'W', 'STATUS'))


def _fresh(mapping, left, right, kind):
    require(left > 0 and right > 0 and left not in mapping and right not in mapping.values(),
            'fresh bijective ' + kind + ' correspondence')
    mapping[left] = right


def _mapped(mapping, value, absent=False):
    if absent and value == 0:
        return 0
    require(value in mapping, 'total independently derived identity correspondence')
    return mapping[value]


def observed_bijection(native, rust):
    require((native.variant, rust.variant) == ('native-observed', 'rust-observed'), 'observed correspondence roles')
    require(native.role == rust.role and native.corpus_sha == rust.corpus_sha, 'observed correspondence role/corpus')
    left = [row for row in native.history if not (row[1] == 'FW' and row[2] == 'DIR1_RAW')]
    right = rust.history
    require(len(left) == len(right), 'full language-specific logical event lengths')
    maps = dict(mid={}, gid={}, tx={}, alg={})
    for a, b in zip(left, right):
        cp, tag, site, av = a
        bp, btag, bsite, bv = b
        require(cp == bp and tag == btag, 'ordered logical checkpoint/event correspondence')
        require(site == bsite or tag == 'FC' and site in ('CTOR_DEFAULT', 'CTOR_GEOMETRIC')
                and bsite == 'RUST_CONTACT_CREATE', 'source-derived language-specific site correspondence')
        if tag == 'FM':
            if site == 'ALLOC':
                _fresh(maps['mid'], av[0], bv[0], 'manifold')
            expected = (_mapped(maps['mid'], av[0]), *av[1:])
        elif tag == 'FC':
            _fresh(maps['gid'], av[0], bv[0], 'constructed contact')
            expected = (maps['gid'][av[0]],)
        elif tag == 'FPY':
            _fresh(maps['gid'], av[1], bv[1], 'copied contact')
            expected = (_mapped(maps['gid'], av[0]), maps['gid'][av[1]], av[2])
        elif tag == 'FI':
            _fresh(maps['gid'], av[4], bv[4], 'inserted contact')
            expected = (_mapped(maps['mid'], av[0]), av[1], _mapped(maps['gid'], av[2], True),
                        _mapped(maps['gid'], av[3]), maps['gid'][av[4]], av[5])
        elif tag == 'FX':
            expected = (_mapped(maps['mid'], av[0], True), av[1], _mapped(maps['gid'], av[2]))
        elif tag == 'FV':
            expected = (_mapped(maps['mid'], av[0]), av[1], av[2], _mapped(maps['gid'], av[3]))
        else:
            require(tag in ('FB', 'FT', 'FW', 'FE'), 'complete known event correspondence')
            if tag == 'FB':
                _fresh(maps['tx'], av[3], bv[3], 'solver transaction')
            expected = (_mapped(maps['mid'], av[0]), av[1], _mapped(maps['gid'], av[2]),
                        _mapped(maps['tx'], av[3], tag == 'FW' and site == 'FIXTURE_W'), *av[4:])
        require(expected == bv, 'complete source-derived logical obligation correspondence at ' + repr((cp, tag, site)))
    ae = [row for row in native.base if row[0] == 'E']
    be = [row for row in rust.base if row[0] == 'E']
    require(len(ae) == len(be), 'full base dispatcher lifecycle lengths')
    for a, b in zip(ae, be):
        require(a[:3] == b[:3] and len(a) == len(b), 'complete ordered base dispatcher lifecycle')
        event, left_id, right_id = a[2], int(a[3]), int(b[3])
        if event == 'A+':
            _fresh(maps['alg'], left_id, right_id, 'algorithm')
        if event in ('A+', 'A-'):
            require(_mapped(maps['alg'], left_id) == right_id, 'complete algorithm lifetime correspondence')
        elif event in ('M+', 'M-'):
            require(_mapped(maps['mid'], left_id) == right_id and a[4:] == b[4:], 'commuting base/sidecar manifold correspondence')
        else:
            require(a == b, 'complete actual base owner/update fields')
    require(len(native.bindings) == len(rust.bindings)
            and tuple(native.bindings) == tuple(rust.bindings), 'total ordered live contact row correspondence')
    for key, (mid, gid) in native.bindings.items():
        require((_mapped(maps['mid'], mid), _mapped(maps['gid'], gid)) == rust.bindings[key],
                'logical generations commute through actual ordered snapshot rows')
    return maps


def _snapshot_binding(mapping, left, right):
    if left == 0 or right == 0:
        require(left == right == 0, 'same explicitly absent identity')
    elif left in mapping:
        require(mapping[left] == right, 'consistent actual snapshot identity graph')
    else:
        _fresh(mapping, left, right, 'snapshot row')


def common_fields(left, right, *, observed_maps=None):
    require(left.role == right.role and left.corpus_sha == right.corpus_sha, 'same role/corpus common fields')
    arows = left.base if observed_maps is not None else [row for row in left.base if row[0] in COMMON]
    brows = right.base if observed_maps is not None else [row for row in right.base if row[0] in COMMON]
    require(len(arows) == len(brows), 'full common base row lengths')
    checkpoint = None
    local_mid, local_alg = {}, {}
    for a, b in zip(arows, brows):
        require(a[:2] == b[:2] and len(a) == len(b), 'full ordered common tag/checkpoint/width')
        if checkpoint != a[1]:
            checkpoint = a[1]
            local_mid, local_alg = {}, {}
        if a[0] == 'E':
            require(observed_maps is not None and a[:3] == b[:3] and a[4:] == b[4:], 'every observed lifecycle field')
            if a[2] in ('A+', 'A-', 'M+', 'M-'):
                kind = 'alg' if a[2].startswith('A') else 'mid'
                require(_mapped(observed_maps[kind], int(a[3])) == int(b[3]), 'complete observed lifecycle identity')
            else:
                require(a == b, 'every observed owner/update field')
        elif a[0] == 'P':
            require(a[:-1] == b[:-1], 'every nonidentity pair field')
            if observed_maps is None:
                _snapshot_binding(local_alg, int(a[-1]), int(b[-1]))
            else:
                require(_mapped(observed_maps['alg'], int(a[-1]), True) == int(b[-1]), 'proven observed algorithm identity')
        elif a[0] == 'M':
            require(a[:3] == b[:3] and a[5:] == b[5:], 'every nonidentity manifold field')
            if observed_maps is None:
                _snapshot_binding(local_mid, int(a[3]), int(b[3]))
                _snapshot_binding(local_alg, int(a[4]), int(b[4]))
            else:
                require(_mapped(observed_maps['mid'], int(a[3])) == int(b[3])
                        and _mapped(observed_maps['alg'], int(a[4])) == int(b[4]), 'proven observed manifold/algorithm identities')
        else:
            require(a == b, 'complete common field numerical difference at ' + repr(a[:4]))


def four_variants(native_original, native_observed, rust_original, rust_observed):
    require(tuple(c.variant for c in (native_original, native_observed, rust_original, rust_observed))
            == ('native-original', 'native-observed', 'rust-original', 'rust-observed'), 'four exact independent variants')
    maps = observed_bijection(native_observed, rust_observed)
    common_fields(native_original, native_observed)
    common_fields(rust_original, rust_observed)
    common_fields(native_original, rust_original)
    common_fields(native_observed, rust_observed, observed_maps=maps)
    compare_physical(rust_original, rust_observed)
    compare_defined(native_original, rust_original)
    compare_defined(native_original, rust_observed)
    compare_defined(native_observed, rust_observed)
    require(tuple(native_observed.directions) == tuple(rust_observed.directions), 'all independent logical direction rows')
    for key, (state, words) in native_observed.directions.items():
        require(state == rust_observed.directions[key][0], 'independently derived native-equivalent direction obligation')
    for key, (state, words) in native_original.directions.items():
        if state == 'D':
            require(native_observed.directions[key] == ('D', words), 'every original guaranteed direction remains identical and defined')
    return maps
