"""Read the single fixed-target dependency rule emitted by the native compiler."""

TARGET = 'mds-friction-object'


def parse(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 8 * 1024 * 1024:
        raise ValueError('bounded compiler dependency file')
    text = raw.decode('utf-8').replace('\\\r\n', ' ').replace('\\\n', ' ')
    prefix = TARGET + ':'
    if not text.startswith(prefix):
        raise ValueError('fixed dependency target')
    text = text[len(prefix):].rstrip('\r\n')
    words, word = [], []
    i = 0
    while i < len(text):
        c = text[i]
        if c in ' \t':
            if word:
                words.append(''.join(word))
                word = []
        elif c == '\\':
            i += 1
            if i == len(text) or text[i] not in ' \t\\#:':
                raise ValueError('unsupported dependency escape')
            word.append(text[i])
        elif c == '$':
            i += 1
            if i == len(text) or text[i] != '$':
                raise ValueError('dependency variable expansion')
            word.append('$')
        elif ord(c) < 32 or c in ':#' or ord(c) == 127:
            raise ValueError('unsupported dependency syntax')
        else:
            word.append(c)
        i += 1
    if word:
        words.append(''.join(word))
    if not words or len(words) != len(set(words)):
        raise ValueError('nonempty unique dependency paths')
    return words


def validate(bindings, *, required, traced):
    targets = {entry['target'] for entry in bindings}
    if not set(required) <= targets or not set(traced) <= targets:
        raise ValueError('compiler dependencies must cover source, forced headers and include trace')
    return sorted((entry['raw'], entry['target'], entry['sha256']) for entry in bindings)
