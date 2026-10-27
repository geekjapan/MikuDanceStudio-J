"""Source-bound outer GJK measurements, independent of support and GJK/EPA profiles."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical_command(command, root, output):
    root, output = str(root).replace('\\', '/'), str(output).replace('\\', '/')
    return [word.replace('\\', '/').replace(root, '$ROOT').replace(output, '$CAPTURE')
            for word in command]


def validate(output, *, host, inventory, source_hashes, stream, transport):
    manifest = json.loads((HERE / 'measured-profiles.json').read_text())
    profile = manifest['profiles'].get(host())
    if profile is None:
        raise ValueError('Unknown outer GJK measured profile')
    current = source_hashes()
    expected = {**profile['protected_source_sha256'], **manifest['verification_sha256'][host()]}
    expected.pop('tools/bullet-rust-gjk-pair-check/measured-profiles.json', None)
    actual = {p: h for p, h in current.items() if p != 'tools/bullet-rust-gjk-pair-check/measured-profiles.json'}
    if actual != expected:
        raise ValueError('Outer GJK source closure differs from reviewed producer and verification code')
    provenance = (output / 'provenance.txt').read_text()
    if provenance != profile['compiler_provenance'].replace('\r\n', '\n'):
        raise ValueError('Outer GJK compiler or toolchain differs from measured profile')
    for name, expected_command in profile['commands'].items():
        actual_command = json.loads((output / name).read_text())
        if canonical_command(actual_command, ROOT, output) != expected_command:
            raise ValueError(f'Outer GJK effective command drift: {name}')
    fixture = ROOT / 'rust/crates/mds-bullet/tests/gjk_pair_data'
    for name, identity in manifest['frozen_fixtures'].items():
        data = (fixture / name).read_bytes()
        # Git checkout transport is distinct from the normalized fixture identity.
        if sha(data.replace(b'\r\n', b'\n')) != identity['sha256']:
            raise ValueError(f'Frozen fixture drift: {name}')
    normalized = {}
    for path, identity in profile['streams'].items():
        name = Path(path).name
        data = (output / name).read_bytes()
        count = identity['rows']
        if 'inputs' in name:
            text, facts = transport(data, count)
        else:
            text, facts = stream(data, count, 5075 if name.startswith('fallback') else 0)
        if facts != identity:
            raise ValueError(f'Outer GJK raw or normalized capture drift: {name}')
        normalized[name] = text
    for prefix in ['', 'compact-', 'fallback-']:
        if not normalized[prefix + 'native.tsv'] == normalized[prefix + 'observed.tsv'] == normalized[prefix + 'rust.tsv']:
            raise ValueError('Same-host native, observed and Rust words differ')
    default = fixture / ('native-x64.tsv' if host().endswith('x64') else 'native.tsv')
    if default.read_bytes().replace(b'\r\n', b'\n') != normalized['compact-native.tsv']:
        raise ValueError('Default fixture differs from measured compact native')
    diff = inventory((fixture / 'native.tsv').read_bytes(), normalized['compact-native.tsv'], 1800)
    if diff != profile['exact_frozen_compact_differences']:
        raise ValueError('Exact compact difference inventory drift')
    full = json.loads((output / 'full-rust-result.json').read_text())
    if full != {'status': 'passed', 'returncode': 0}:
        raise ValueError('Exact full same-host baseline did not pass')
    return {'host': host(), 'status': 'measured-profile-matched',
            'evidence_head': manifest['evidence_head'], 'artifact_id': profile['artifact_id'],
            'zip_sha256': profile['zip_sha256'], 'source_sha256': current,
            'verification_manifest_sha256': sha((HERE / 'measured-profiles.json').read_bytes()),
            'approval': 'requires fresh four-host gates and independent review'}
