"""Bounded, externally anchored transport of an unchanged hosted facts packet."""
import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import tarfile

MAX_JSON = 8 * 1024 * 1024
MAX_FILE = 512 * 1024 * 1024
MAX_PACKET = 4 * 1024 * 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024 * 1024
MAX_MEMBERS = 32768


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(65536), b''):
            value.update(data)
    return value.hexdigest()


def read_json(path, expected_size=None, expected_sha=None):
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_JSON,
            'JSON byte bound or kind differs')
    size = path.stat().st_size
    with path.open('rb') as stream:
        data = stream.read(MAX_JSON + 1)
    require(len(data) == size and 0 < len(data) <= MAX_JSON, 'JSON byte bound differs')
    if expected_size is not None:
        require(type(expected_size) is int and len(data) == expected_size
                and hashlib.sha256(data).hexdigest() == expected_sha, 'parsed JSON external anchor differs')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    def finite(text):
        value = float(text)
        require(math.isfinite(value), 'nonfinite or overflow JSON number')
        return value
    def invalid(text):
        raise ValueError('nonfinite JSON constant ' + text)
    return json.loads(data, object_pairs_hook=unique, parse_float=finite, parse_constant=invalid)


def relative(name):
    require(type(name) is str and bool(name) and '\\' not in name
            and name == PurePosixPath(name).as_posix()
            and not name.startswith('/')
            and all(part not in ('.', '..') for part in name.split('/')), 'unsafe transport path')
    return name


def same(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(same(left[key], right[key]) for key in left)
    if type(left) is list:
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
    return left == right


def anchored(path, size, sha256, limit):
    require(type(size) is int and 0 < size <= limit and type(sha256) is str
            and len(sha256) == 64 and all(c in '0123456789abcdef' for c in sha256),
            'external transport anchor required')
    require(path.is_file() and not path.is_symlink() and path.stat().st_size == size,
            'external transport length differs')
    require(digest(path) == sha256, 'external transport digest differs')


def complete_report(report):
    require(type(report) is dict, 'producer report schema differs')
    for key, expected in dict(schema=1, status='complete_coverage', authorization='analysis_only',
                              units=24, symbols=40, incoming_calls=4865, unclassified=5,
                              authentic_job_proof=False).items():
        require(type(report.get(key)) is type(expected) and report[key] == expected,
                'producer report incomplete or mistyped ' + key)


def check_packet(root):
    packet = root / 'evidence/result/closed-format-facts'
    seal = read_json(packet / 'seal.json')
    require(type(seal) is dict and 0 < len(seal) <= 4096, 'packet seal schema differs')
    actual, total = set(), 0
    for path in packet.rglob('*'):
        require(not path.is_symlink(), 'symlink packet member')
        if path.is_dir():
            continue
        name = path.relative_to(packet).as_posix()
        if name == 'seal.json':
            continue
        relative(name)
        require(path.is_file() and name in seal, 'packet membership differs')
        record = seal[name]
        require(type(record) is dict and set(record) == {'bytes', 'sha256'}
                and type(record['bytes']) is int and 0 <= record['bytes'] <= MAX_FILE,
                'packet seal member schema differs')
        require(path.stat().st_size == record['bytes'] and digest(path) == record['sha256'],
                'packet seal member differs')
        actual.add(name)
        total += record['bytes']
        require(total <= MAX_PACKET, 'packet byte bound differs')
    require(actual == seal.keys(), 'packet seal membership differs')
    report = read_json(packet / 'report.json')
    complete_report(report)
    result = read_json(root / 'evidence/result/result.json')
    require(type(result) is dict and result.get('status') == 'complete_coverage'
            and type(result.get('translation_units')) is int and result['translation_units'] == 24
            and same(result.get('closed_format_facts'), report), 'producer result incomplete')
    syntax = result.get('syntax')
    require(type(syntax) is list and len(syntax) == 24, 'producer syntax coverage differs')
    for record in syntax:
        require(type(record) is dict and type(record.get('exit_code')) is int
                and record['exit_code'] == 0 and record.get('timed_out') is False,
                'producer syntax failed or mistyped')
    native = read_json(packet / 'native-files.json')
    require(type(native) is dict and bool(native), 'native file manifest differs')
    for name, sha256 in native.items():
        path = Path(name)
        require(path.is_absolute() and str(path.resolve()) == name and path.is_file()
                and digest(path) == sha256, 'current native source or system header differs')


def pack(root, archive):
    check_packet(root)
    require(not archive.exists() and not archive.is_relative_to(root), 'transport must be new and external')
    count, total = 0, 0
    with tarfile.open(archive, 'x', format=tarfile.PAX_FORMAT) as output:
        for name in ('prepared/work-linux-native', 'tool', 'evidence/result'):
            directory = root / name
            require(directory.is_dir() and not directory.is_symlink(), 'transport source missing')
            for path in [directory, *sorted(directory.rglob('*'))]:
                parts = path.relative_to(directory).parts
                if any(p in ('.libs', '.deps') or p.endswith(('.o', '.lo')) for p in parts):
                    continue
                require(not path.is_symlink() and (path.is_dir() or path.is_file()),
                        'unsupported transport source kind')
                count += 1
                total += path.stat().st_size if path.is_file() else 0
                require(count <= MAX_MEMBERS and total <= MAX_TOTAL
                        and (path.is_dir() or path.stat().st_size <= MAX_FILE), 'transport source bound')
                output.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
    return dict(size=archive.stat().st_size, sha256=digest(archive), namespace=str(root))


def unpack(root, archive, size, sha256, namespace):
    require(str(root) == namespace and root.is_absolute() and root.resolve() == root,
            'original format-facts namespace differs')
    anchored(archive, size, sha256, MAX_TOTAL + MAX_MEMBERS * 2048)
    members, names, total = [], {}, 0
    with archive.open('rb') as raw, tarfile.open(fileobj=HeaderReader(raw), mode='r:') as source:
        for member in source:
            name = relative(member.name)
            require(name not in names and (member.isdir() or member.isfile()) and not member.issparse()
                    and member.mode & ~0o777 == 0, 'duplicate or unsupported TAR member')
            require(name == 'tool' or name.startswith('tool/')
                    or name in ('prepared/work-linux-native', 'evidence/result')
                    or name.startswith(('prepared/work-linux-native/', 'evidence/result/')),
                    'unexpected TAR namespace')
            require(type(member.size) is int and 0 <= member.size <= MAX_FILE
                    and (not member.isdir() or member.size == 0), 'TAR member byte bound')
            total += member.size
            require(total <= MAX_TOTAL and len(members) < MAX_MEMBERS, 'TAR total bound')
            names[name] = member
            members.append(member)
        for name, member in names.items():
            for parent in PurePosixPath(name).parents:
                if str(parent) != '.':
                    require(str(parent) not in names or names[str(parent)].isdir(), 'TAR parent kind conflict')
            destination = root / name
            require(not destination.exists() and not destination.is_symlink(), 'transport destination exists')
            for parent in destination.parents:
                require(not parent.is_symlink(), 'transport parent symlink')
        source.fileobj.metadata = False
        for member in members:
            destination = root / member.name
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as incoming, destination.open('xb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 65536)
                destination.chmod(member.mode)
        for member in reversed(members):
            if member.isdir():
                (root / member.name).chmod(member.mode)
    check_packet(root)


class HeaderReader:
    def __init__(self, stream):
        self.stream = stream
        self.metadata = True
        self.total = 0

    def read(self, size):
        require(0 <= size <= MAX_JSON, 'TAR metadata read bound')
        if self.metadata:
            self.total += size
            require(self.total <= 64 * 1024 * 1024, 'TAR metadata total bound')
        return self.stream.read(size)

    def seek(self, *args):
        return self.stream.seek(*args)

    def tell(self):
        return self.stream.tell()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('pack', 'unpack', 'check', 'handoff', 'report'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--size', type=int)
    parser.add_argument('--sha256')
    parser.add_argument('--namespace')
    args = parser.parse_args()
    if args.mode == 'pack':
        print(json.dumps(pack(args.root, args.archive), sort_keys=True))
    elif args.mode == 'unpack':
        unpack(args.root, args.archive, args.size, args.sha256, args.namespace)
    elif args.mode == 'report':
        complete_report(read_json(args.archive))
    elif args.mode == 'handoff':
        anchored(args.archive, args.size, args.sha256, MAX_JSON)
        value = read_json(args.archive, args.size, args.sha256)
        require(type(value) is dict and set(value) == {'schema', 'kind', 'status', 'authorization',
                'manifest', 'native_files', 'bindings'} and type(value.get('schema')) is int and value['schema'] == 1
                and value.get('kind') == 'c2rust-trusted-full-replay'
                and value.get('status') == 'complete_coverage'
                and value.get('authorization') == 'analysis_only'
                and type(value.get('manifest')) is dict and type(value.get('bindings')) is list
                and len(value['bindings']) == 24 and type(value.get('native_files')) is str,
                'trusted handoff incomplete')
    else:
        check_packet(args.root)


if __name__ == '__main__':
    main()
