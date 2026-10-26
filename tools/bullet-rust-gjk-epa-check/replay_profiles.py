#!/usr/bin/env python3
"""Replay the four reviewed Actions ZIPs and reject altered captures."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bullet-rust-support-check'))
import host_profiles as profiles


def replay(artifacts):
    manifest, base = profiles.load('gjk-epa')
    baseline = None
    receipt = {}
    for host, profile in manifest['profiles'].items():
        measured = profile['measured']
        archive = artifacts / (host + '.zip')
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == measured['artifact_sha256'], host
        with zipfile.ZipFile(archive) as zipped, tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            for name in ['native.tsv', 'observed.tsv', 'rust.tsv', 'inputs.tsv', 'raw-native.tsv', 'raw-rust.tsv']:
                (output / name).write_bytes(zipped.read('capture/' + name))
            assert zipped.read('source-head.txt').decode().strip() == measured['source_commit']
            source = zipped.read('source-manifest.txt')
            assert hashlib.sha256(source).hexdigest() == measured['source_manifest_sha256']
            entries = source.decode().splitlines()
            assert len(entries) == 427
            tree = subprocess.check_output(['git', '-C', str(profiles.ROOT), 'ls-tree', '-r', measured['source_commit']], text=True)
            blobs = {line.split('\t')[1]: line.split()[0:3:2] for line in tree.splitlines()}
            for entry in entries:
                mode, blob, stage_path = entry.split(' ', 2)
                stage, path = stage_path.split('\t')
                assert stage == '0' and blobs[path] == [mode, blob], path
            assert hashlib.sha256(zipped.read('capture/provenance.txt')).hexdigest() == measured['provenance_sha256']
            assert json.loads(zipped.read('capture/effective-native-command.json')) == measured['native_command']
            native = (output / 'native.tsv').read_bytes()
            assert zipped.read('capture/raw-inputs.tsv') == (base / 'raw-inputs.tsv').read_bytes()
            assert b''.join((output / 'inputs.tsv').read_bytes().splitlines(keepends=True)[:1801]) == (base / 'inputs.tsv').read_bytes()
            widths = Counter(len(line.split(b'\t')) for line in native.splitlines())
            assert widths == {27: 4427, 37: 2380, 47: 3}
            assert (output / 'raw-native.tsv').read_bytes() == (output / 'raw-rust.tsv').read_bytes() == b''.join(native.splitlines(keepends=True)[-9:])
            with patch.object(profiles, 'host', return_value=host):
                assert profiles.validate_capture(output, 'gjk-epa') == base / profile['compact']
            normalized = profiles.capture_text(native, profile, 6810, profile['full_sha256'])
            if baseline is None:
                baseline = normalized
            diff = profiles.differences(baseline, normalized, 'gjk-epa', 6810)
            assert diff == profile['differences'] + profile['raw_differences']
            rejected = []
            for name in ['native.tsv', 'observed.tsv', 'rust.tsv', 'inputs.tsv']:
                original = (output / name).read_bytes()
                for word in [b'3f800000', b'80000000', b'7f800000', b'ffc00000']:
                    (output / name).write_bytes(original.replace(b'00000000', word, 1))
                    try:
                        with patch.object(profiles, 'host', return_value=host):
                            profiles.validate_capture(output, 'gjk-epa')
                    except ValueError:
                        rejected.append(name + '/' + word.decode())
                    else:
                        raise AssertionError('Altered capture accepted')
                (output / name).write_bytes(original)
            for word in [b'3f800000', b'80000000', b'7f800000', b'ffc00000']:
                changed = native.replace(b'00000000', word, 1)
                for name in ['native.tsv', 'observed.tsv', 'rust.tsv']:
                    (output / name).write_bytes(changed)
                try:
                    with patch.object(profiles, 'host', return_value=host):
                        profiles.validate_capture(output, 'gjk-epa')
                except ValueError as error:
                    assert 'hash' in str(error)
                    rejected.append('same-host-hash/' + word.decode())
                else:
                    raise AssertionError('Altered same-host capture accepted')
            for name in ['native.tsv', 'observed.tsv', 'rust.tsv']:
                (output / name).write_bytes(native)
            for count, data, digest in [(6810, native, profile['full_sha256']),
                                         (1801, b''.join(native.splitlines(keepends=True)[:1801]), profile['compact_sha256']),
                                         (9, (output / 'raw-native.tsv').read_bytes(), profile['raw_sha256'])]:
                for changed in [data[:-1], data + b'\n', data.replace(b'\r\n', b'\n', 1) if host == 'windows-x64' else data.replace(b'\n', b'\r\n', 1)]:
                    try:
                        profiles.capture_text(changed, profile, count, hashlib.sha256(changed).hexdigest())
                    except ValueError:
                        rejected.append('transport/' + str(count))
                    else:
                        raise AssertionError('Invalid transport accepted even with updated hash')
                for word in [b'3f800000', b'80000000', b'7f800000', b'ffc00000']:
                    changed = data.replace(b'00000000', word, 1)
                    try:
                        profiles.capture_text(changed, profile, count, digest)
                    except ValueError:
                        rejected.append('word-hash/' + str(count) + '/' + word.decode())
                    else:
                        raise AssertionError('Altered capture word accepted')
                try:
                    profiles.capture_text(data, profile, count, '0' * 64)
                except ValueError:
                    rejected.append('hash/' + str(count))
                else:
                    raise AssertionError('Invalid hash accepted')
            with patch.object(profiles, 'host', return_value='unmeasured-host'):
                try:
                    profiles.validate_capture(output, 'gjk-epa')
                except ValueError as error:
                    assert 'Unreviewed' in str(error)
                else:
                    raise AssertionError('Unknown host accepted')
            receipt[host] = {'artifact': measured['artifact'], 'full_rows': len(normalized.splitlines()),
                             'differences': len(diff), 'strict_capture_rejections': rejected,
                             'source_entries': len(entries), 'schema_widths': dict(widths), 'native_observed_rust_equal': True}
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.artifacts_dir)
    args.receipt.write_text(json.dumps(result, indent=2) + '\n')
    print('Four measured ZIPs, exact inventories and altered capture controls passed.')
