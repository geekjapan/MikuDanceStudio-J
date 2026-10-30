"""Closed diagnostic wire types. This module grants no source or execution admission."""
import re

VARIANTS = ('native-original', 'native-observed', 'rust-original', 'rust-observed')
ROLES = ('ordinary', 'ascending', 'descending', 'alternating')
MAX_BYTES = 64 * 1024 * 1024
MAX_EVENTS = 1000000
MAX_LINE = 512
MAX_INT = 2147483647
GUARDS = frozenset('STARTUP COMMAND_BEGIN COMMAND_END CTOR_EXIT ADD_ENTER ADD_EXIT '
                   'REPLACE_ENTER REPLACE_EXIT REMOVE_ENTER REMOVE_EXIT CLEAR_ENTER CLEAR_EXIT '
                   'RELEASE_ENTER RELEASE_EXIT USERCACHE_ENTER USERCACHE_EXIT ADDED_PRECALL '
                   'PROCESSED_PRECALL DESTROYED_PRECALL SOLVER_BEGIN SOLVER_END '
                   'FIXTURE_BEGIN FIXTURE_END RESULT_ENTER RESULT_EXIT REFRESH_ENTER REFRESH_EXIT SNAPSHOT'.split())
SITES = {
    'FG': GUARDS,
    'FM': frozenset(('ALLOC', 'CLEAR_BEGIN', 'CLEAR_END', 'RELEASE')),
    'FC': frozenset(('CTOR_DEFAULT', 'CTOR_GEOMETRIC', 'RUST_CONTACT_CREATE')),
    'FPY': frozenset(('POINT_COPY',)),
    'FI': frozenset(('ADD', 'REPLACE', 'EVICT_ADD')),
    'FX': frozenset(('TEMP_END', 'REMOVE', 'CLEAR_POINT', 'RELEASE_POINT')),
    'FV': frozenset(('REMOVE_MOVE',)),
    'FR': frozenset(('REFRESH_BEGIN', 'REFRESH_POINT', 'REFRESH_END')),
    'FB': frozenset(('SOLVER_BEGIN',)),
    'FT': frozenset(('SOLVER_CHOICE',)),
    'FW': frozenset(('DIR1_RAW', 'VELOCITY_DIR1', 'VELOCITY_DIR2', 'PLANE_BOTH',
                     'ANISO_DIR1', 'ANISO_DIR2', 'FIXTURE_W')),
    'FE': frozenset(('VELOCITY_ONE', 'VELOCITY_TWO', 'PLANE_ONE', 'PLANE_TWO', 'CACHED_ONE', 'CACHED_TWO')),
    'FS': frozenset(('SNAPSHOT',)),
    'FL': frozenset(('SNAPSHOT',)),
    'FD': frozenset(('SNAPSHOT',)),
    'FP': frozenset(('RUST_PHYSICAL',)),
}
# Fields after cp, seq and site. z permits zero; i is a nonzero identity.
FIELDS = {
    'FG': 'bbbb', 'FM': 'iuu', 'FC': 'i', 'FPY': 'iim',
    'FI': 'isziim', 'FX': 'zsi', 'FV': 'issi', 'FR': 'iszbb', 'FB': 'isiiub',
    'FT': 'isiibbb', 'FW': 'isizm', 'FE': 'isiimmb',
    'FS': 'uic', 'FL': 'us iimb'.replace(' ', ''),
    'FD': 'usdtc', 'FP': 'usdwww',
}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def unsigned(value, minimum=0, maximum=MAX_INT):
    require(type(value) is str and re.fullmatch(r'0|[1-9][0-9]*', value) is not None,
            'canonical unsigned integer')
    require(len(value) <= 10, 'bounded unsigned integer')
    result = int(value)
    require(minimum <= result <= maximum, 'unsigned integer range')
    return result


def field(value, kind):
    if kind == 'b':
        require(value in ('true', 'false'), 'canonical boolean')
        return value == 'true'
    if kind == 'w':
        require(re.fullmatch('[0-9a-f]{8}', value) is not None, 'raw f32 word')
        return value
    if kind == 't':
        require(value in ('D', 'U', 'O'), 'direction state')
        return value
    minimum = 1 if kind in ('i', 'd') else 0
    maximum = {'s': 3, 'm': 3, 'c': 4, 'd': 2}.get(kind, MAX_INT)
    return unsigned(value, minimum, maximum)


def tokens(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'bounded diagnostic bytes')
    require(raw.endswith(b'\n') and all(value == 10 or 32 <= value <= 126 for value in raw),
            'LF terminated ASCII diagnostic')
    try:
        text = raw.decode('ascii')
    except UnicodeDecodeError as error:
        raise ValueError('ASCII diagnostic') from error
    lines = text.splitlines()
    require(len(lines) <= MAX_EVENTS + 2 + MAX_BYTES // 2, 'bounded combined row count')
    for line in lines:
        row = line.split(' ')
        require(all(row) and all(all(33 <= ord(c) <= 126 for c in word) for word in row),
                'single-space token framing')
        if row[0].startswith('F'):
            require(len(line.encode()) + 1 <= MAX_LINE, 'bounded sidecar line')
        yield row


def diagnostic(row):
    tag = row[0]
    require(tag in FIELDS and len(row) >= 4, 'known diagnostic tag')
    require(row[3] in SITES[tag], 'known site for tag')
    kinds = FIELDS[tag]
    extra = 3 if tag == 'FD' and len(row) >= 9 and row[7] == 'D' else 0
    require(len(row) == 4 + len(kinds) + extra, 'exact diagnostic width ' + tag)
    values = tuple(field(value, kind) for value, kind in zip(row[4:4 + len(kinds)], kinds))
    if tag == 'FR':
        require(not (values[3] and values[4]), 'one actual refresh removal branch')
        if row[3] == 'REFRESH_POINT':
            require(values[2] > 0, 'positive refresh point generation')
        else:
            require(values[1:] == (0, 0, False, False)
                    and all(type(value) is int for value in values[1:3]),
                    'exact refresh BEGIN/END sentinels')
    if tag == 'FD':
        require(values[-1] == (3 if values[-2] == 'D' else 0), 'exact direction value count')
        values += tuple(field(value, 'w') for value in row[4 + len(kinds):])
    return tag, unsigned(row[1]), unsigned(row[2], 1, MAX_EVENTS), row[3], values
