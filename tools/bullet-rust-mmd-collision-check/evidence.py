"""Diagnostic command custody. This module does not admit native captures."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    temporary = path.with_name(path.name + '.pending')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(path)


def identity(executable):
    found = shutil.which(str(executable))
    require(found is not None, 'resolved executable ' + str(executable))
    path = Path(found).absolute()
    target = path.resolve(strict=True)
    require(target.is_file(), 'regular executable')
    return {'path': str(path), 'target': str(target), 'sha256': digest(target.read_bytes())}


class Recorder:
    def __init__(self, out, snapshot):
        self.out, self.snapshot = out, snapshot
        self.sources = snapshot()
        self.commands = []
        save(out / 'source-start.json', self.sources)

    def run(self, label, argv, *, cwd, data=None, inputs=(), outputs=()):
        require(label and all(c in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in label), 'command label')
        require(not any(record['label'] == label for record in self.commands), 'unique command label')
        require(self.snapshot() == self.sources, 'fixed sources before ' + label)
        binding = identity(argv[0])
        argv = [binding['path'], *map(str, argv[1:])]
        record = {'label': label, 'argv': argv, 'cwd': str(cwd), 'executable': binding,
                  'stdin_sha256': None if data is None else digest(data),
                  'inputs_before': {str(p): digest(Path(p).read_bytes()) for p in inputs},
                  'outputs': {}, 'pid': None, 'start_utc': utc(), 'end_utc': None,
                  'waited': False, 'streams_closed': False, 'returncode': None}
        self.commands.append(record)
        save(self.out / 'commands.json', self.commands)
        start = time.monotonic()
        stdout_path, stderr_path = (self.out / (label + suffix) for suffix in ('.stdout', '.stderr'))
        with stdout_path.open('xb') as stdout, stderr_path.open('xb') as stderr:
            process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, env={**os.environ, 'VSLANG': '1033'})
            record['pid'] = process.pid
            save(self.out / 'commands.json', self.commands)
            try:
                process.communicate(data, timeout=600)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                record['timeout'] = True
            record.update(returncode=process.returncode, waited=True)
        record.update(end_utc=utc(), seconds=time.monotonic() - start, streams_closed=True,
                      stdout_sha256=digest(stdout_path.read_bytes()), stderr_sha256=digest(stderr_path.read_bytes()))
        record['outputs'] = {str(p): digest(Path(p).read_bytes()) for p in outputs if Path(p).is_file()}
        record['inputs_end'] = {str(p): digest(Path(p).read_bytes()) for p in inputs}
        record['executable_end'] = identity(binding['path'])
        save(self.out / 'commands.json', self.commands)
        require(record['inputs_end'] == record['inputs_before'], 'input preservation ' + label)
        require(record['executable_end'] == binding, 'executable preservation ' + label)
        require(self.snapshot() == self.sources, 'fixed sources after ' + label)
        require(record['returncode'] == 0 and not record.get('timeout'), 'normally exiting command ' + label)
        require(len(record['outputs']) == len(outputs), 'all declared command outputs ' + label)
        return stdout_path.read_bytes()

    def close(self):
        end = self.snapshot()
        save(self.out / 'source-end.json', end)
        require(end == self.sources, 'source before/end preservation')
        require(all(record['waited'] and record['streams_closed'] for record in self.commands), 'all commands waited and closed')


def admit_capture(*args, **kwargs):
    raise ValueError('MMD strict actual-capture admission is not implemented; diagnostic captures are UNADMITTED')
