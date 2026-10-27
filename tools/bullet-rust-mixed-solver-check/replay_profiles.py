#!/usr/bin/env python3
"""Stream the independently audited ZIPs without extracting their multi-GB traces."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile
from check import hooks
from integrity import producer_paths
from observation import digest, verify
from trace import validate

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = 'bead7792eff1c9442cdbd3fa3aceaaf87fefe5ad'


class Capture:
    def __init__(self, archive, overrides):
        self.archive, self.overrides = archive, overrides

    def __truediv__(self, name):
        return self.overrides / name if (self.overrides / name).is_file() else self.archive / name


def replay(artifacts, hosts=('macarm','linuxarm','linuxx64','windows'), receipt_path=None):
    receipt = {}
    for host in hosts:
        profile = json.loads((HERE / 'profiles' / (host + '-run40411448747.json')).read_text())
        measured = profile['measurement']
        archive = artifacts / (host + '.zip')
        if digest(archive) != measured['zip_sha256']:
            raise ValueError('artifact ZIP digest differs: ' + host)
        with zipfile.ZipFile(archive) as zipped, tempfile.TemporaryDirectory() as temporary:
            original = zipfile.Path(zipped)
            output = Path(temporary)
            def source(name):
                raw = subprocess.check_output(['git', '-C', str(ROOT), 'show', BASE + ':' + name])
                return raw.replace(b'\n', b'\r\n') if host == 'windows' else raw
            recorded = json.loads((original / 'source-sha256.json').read_text())
            recorded = {name.replace('\\', '/'): value for name, value in recorded.items()}
            for name, expected in recorded.items():
                if hashlib.sha256(source(name)).hexdigest() != expected:
                    raise ValueError('archived source differs: ' + name)
            expected_paths = {p.relative_to(ROOT).as_posix() for p in producer_paths(ROOT, lambda p: source(p.relative_to(ROOT).as_posix()).decode())}
            if set(profile['producer_sources']) != expected_paths:
                raise ValueError('incomplete measured producer closure')
            reconstructed = {name: hashlib.sha256(source(name)).hexdigest() for name in expected_paths}
            if reconstructed != profile['producer_sources']:
                raise ValueError('pinned producer source differs')
            # The old 203-entry manifest omitted these files. This is reconstruction, not an archived measurement.
            (output / 'source-sha256.json').write_text(json.dumps(reconstructed))
            if host == 'windows':
                (output / 'compiler-banner.txt').write_bytes(zipped.read('command-002.stderr'))
            solver = 'recipes/bullet275/bullet-src/src/BulletDynamics/ConstraintSolver/btSequentialImpulseConstraintSolver.cpp'
            instrumented = hooks(source(solver).decode().replace('\r\n', '\n')).encode()
            if host == 'windows':instrumented = instrumented.replace(b'\n', b'\r\n')
            if instrumented != zipped.read('btSequentialImpulseConstraintSolver.cpp'):
                raise ValueError('archived observer differs from pinned source hooks')
            fixtures = json.loads((original / 'frozen-fixture-sha256.json').read_text())
            for name, expected in fixtures.items():
                raw = subprocess.check_output(['git', '-C', str(ROOT), 'show', BASE + ':' + name.replace('\\', '/')])
                if hashlib.sha256(raw).hexdigest() != expected:
                    raise ValueError('archived frozen fixture differs')
            capture = Capture(original, output)
            comparison = verify(capture, HERE / 'profiles')
            coverage = validate(original / 'native.trace', original / 'inputs.tsv')
            if validate(original / 'rust.trace', original / 'inputs.tsv') != coverage:
                raise ValueError('native/Rust coverage differs')
            if len((original / 'native.tsv').read_bytes().splitlines()) != 200:
                raise ValueError('stdout solve count differs')
            receipt[host] = {'measurement': measured, 'comparison': comparison, 'coverage': coverage,
                             'archived_source_entries_checked': len(recorded),
                             'reconstructed_producer_entries_checked': len(reconstructed),
                             'fixtures_checked': len(fixtures)}
            if receipt_path is not None:
                previous = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {}
                previous.update(receipt)
                receipt_path.write_text(json.dumps(previous,indent=2)+'\n')
            print(host, comparison['difference_words'], coverage['events'], 'PASS', flush=True)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--hosts', nargs='+', choices=['macarm','linuxarm','linuxx64','windows'], default=['macarm','linuxarm','linuxx64','windows'])
    args = parser.parse_args()
    replay(args.artifacts_dir,args.hosts,args.receipt)
