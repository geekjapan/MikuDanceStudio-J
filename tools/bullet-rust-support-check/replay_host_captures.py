"""Replay audited four-host ZIPs without compiling or altering their captures."""
import argparse
import hashlib
from pathlib import Path
import tempfile
from unittest.mock import patch
import zipfile

import host_profiles as profiles


def replay(directory):
    manifest, _ = profiles.load()
    audit = manifest['four_host_capture']
    for host, receipt in audit['hosts'].items():
        archive = directory / f'{host}.zip'
        if hashlib.sha256(archive.read_bytes()).hexdigest() != receipt['zip_sha256']:
            raise ValueError(f'Artifact ZIP hash changed: {host}')
        with zipfile.ZipFile(archive) as capture, tempfile.TemporaryDirectory() as temp:
            source = capture.read('source-manifest.txt')
            if hashlib.sha256(source).hexdigest() != audit['source_manifest_sha256'] or len(source.splitlines()) != audit['source_blobs']:
                raise ValueError(f'Source manifest changed: {host}')
            if capture.read('source-head.txt').decode().strip() != audit['source_commit']:
                raise ValueError(f'Capture source commit changed: {host}')
            output = Path(temp)
            for name in ['native.tsv', 'observed.tsv', 'rust.tsv', 'inputs.tsv']:
                (output / name).write_bytes(capture.read(f'capture/{name}'))
            with patch.object(profiles, 'host', return_value=host):
                fixture = profiles.validate_capture(output)
                native = (output / 'native.tsv').read_bytes()
                mutants = [native.replace(b'00000000', word, 1) for word in [b'3f800000', b'80000000', b'7f800000', b'ffc00000']]
                mutants += [native.replace(b'\r\n', b'\n'), native.replace(b'\n', b'\r\n', 1),
                            native.replace(b'\r\n', b'\n', 1), native.replace(b'\n', b'\r\r\n'),
                            native[:-1], native + b'\n', native.replace(b'00000000\t', b'', 1)]
                rejected = 0
                for mutant in mutants:
                    if mutant == native:
                        continue
                    for name in ['native.tsv', 'observed.tsv', 'rust.tsv']:
                        (output / name).write_bytes(mutant)
                    try:
                        profiles.validate_capture(output)
                    except ValueError:
                        rejected += 1
                    else:
                        raise AssertionError(f'Accepted altered capture: {host}')
                print(f'{host}: 3377 exact native/observed/Rust rows, {fixture.name}, {rejected} rejected capture mutations')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='Directory containing the four HOST.zip archives')
    replay(parser.parse_args().directory)
