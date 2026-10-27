"""Source-bound outer GJK measurements, independent of support and GJK/EPA profiles."""
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical_command(command, root, output):
    root, output = str(root).replace('\\', '/'), str(output).replace('\\', '/')
    return [word.replace('\\', '/').replace(root, '$ROOT').replace(output, '$CAPTURE')
            for word in command]



MANIFEST_PATH = 'tools/bullet-rust-gjk-pair-check/measured-profiles.json'
HOSTS = {'macos-arm64', 'linux-arm64', 'linux-x64', 'windows-x64'}
COMMANDS = {'native-command.json', 'effective-native-command.json', 'observed-command.json'}
STREAMS = {'capture/' + prefix + name + '.tsv'
           for prefix in ['', 'compact-', 'fallback-'] for name in ['inputs', 'native', 'observed', 'rust']}
MEASUREMENT_FIELDS = {'compiler_provenance', 'evidence_head', 'run_id', 'job_id', 'artifact_id',
                      'zip_sha256', 'capture_source_map_sha256', 'source_before_sha256',
                      'source_after_sha256', 'provenance_sha256'}


def schema(condition, message):
    if not condition:
        raise ValueError('Outer GJK measured profile schema: ' + message)


def fields(value, expected, label):
    schema(isinstance(value, dict) and set(value) == expected, label + ' fields')


def digest(value, size=64):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{' + str(size) + '}', value) is not None


def source_map_digest(value):
    return sha(json.dumps(value, sort_keys=True).encode('utf-8'))


def hash_map(value, count, label):
    schema(isinstance(value, dict) and len(value) == count, label + ' count')
    schema(all(isinstance(path, str) and path and not path.startswith('/')
               and '\\' not in path and all(part not in {'', '.', '..'} for part in path.split('/'))
               and digest(identity) for path, identity in value.items()), label + ' identities')
    schema(MANIFEST_PATH not in value, label + ' manifest self-exclusion')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        schema(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def normalize_provenance(value):
    schema(isinstance(value, str) and bool(value) and value.endswith('\n'), 'provenance text')
    normalized = value.replace('\r\n', '\n')
    schema('\r' not in normalized and ('\r\n' not in value or value.count('\r\n') == value.count('\n')),
           'provenance transport')
    return normalized


def load_manifest(path):
    manifest = json.loads(path.read_text(), object_pairs_hook=unique_object)
    fields(manifest, {'schema_version', 'status', 'frozen_fixtures', 'profiles', 'verification_sha256'}, 'manifest')
    schema(type(manifest['schema_version']) is int and manifest['schema_version'] == 2, 'schema_version')
    schema(manifest['status'] == 'reviewed-current-source-expectation-execution-pending', 'status')
    fields(manifest['profiles'], HOSTS, 'profiles')
    fields(manifest['verification_sha256'], HOSTS, 'verification hosts')
    fields(manifest['frozen_fixtures'], {'inputs.tsv', 'native.tsv', 'fallback-inputs.tsv', 'fallback-native.tsv'}, 'fixtures')
    for identity in manifest['frozen_fixtures'].values():
        fields(identity, {'git_blob', 'sha256'}, 'fixture')
        schema(digest(identity['git_blob'], 40) and digest(identity['sha256']), 'fixture identity')
    artifact_ids, job_ids, provenances = set(), set(), set()
    protected_paths = verification_paths = None
    for host, profile in manifest['profiles'].items():
        fields(profile, {'protected_source_sha256', 'measured_verification_sha256', 'commands', 'streams',
                         'exact_frozen_compact_differences', 'measurements'}, 'profile')
        protected = profile['protected_source_sha256']
        historical = profile['measured_verification_sha256']
        current = manifest['verification_sha256'][host]
        hash_map(protected, 457, 'protected source')
        hash_map(historical, 10, 'historical verification')
        hash_map(current, 10, 'current verification')
        schema(not set(protected) & set(current), 'source partition overlap')
        schema(set(historical) == set(current), 'historical verification paths')
        if protected_paths is None:
            protected_paths, verification_paths = set(protected), set(current)
        schema(set(protected) == protected_paths and set(current) == verification_paths, 'host source paths')
        fields(profile['commands'], COMMANDS, 'commands')
        for command in profile['commands'].values():
            schema(isinstance(command, list) and bool(command)
                   and all(isinstance(word, str) and bool(word) for word in command), 'command words')
        fields(profile['streams'], STREAMS, 'streams')
        for name, identity in profile['streams'].items():
            fields(identity, {'rows', 'line_ending', 'raw_sha256', 'lf_sha256'}, 'stream')
            count = 1800 if '/compact-' in name else 6 if '/fallback-' in name else 5081
            schema(type(identity['rows']) is int and identity['rows'] == count, 'stream rows')
            schema(identity['line_ending'] in ['LF', 'CRLF'] and digest(identity['raw_sha256'])
                   and digest(identity['lf_sha256']), 'stream identity')
        differences = [[case, 'query.axis.' + axis, '7fc00000', 'ffc00000']
                       for case in [1252, 1253, 1411] for axis in 'xyz'] if host.endswith('x64') else []
        schema(json.dumps(profile['exact_frozen_compact_differences']) == json.dumps(differences), 'frozen NaN inventory')
        measurements = profile['measurements']
        schema(isinstance(measurements, list) and bool(measurements), 'measurements must be nonempty')
        captured_digest = source_map_digest({**protected, **historical})
        for measurement in measurements:
            fields(measurement, MEASUREMENT_FIELDS, 'measurement')
            provenance = normalize_provenance(measurement['compiler_provenance'])
            schema(provenance not in provenances, 'duplicate normalized provenance')
            provenances.add(provenance)
            for name in ['run_id', 'job_id', 'artifact_id']:
                schema(type(measurement[name]) is int and measurement[name] > 0, name)
            schema(measurement['artifact_id'] not in artifact_ids and measurement['job_id'] not in job_ids,
                   'duplicate artifact or job identity')
            artifact_ids.add(measurement['artifact_id'])
            job_ids.add(measurement['job_id'])
            schema(digest(measurement['evidence_head'], 40), 'evidence_head')
            for name in ['zip_sha256', 'capture_source_map_sha256', 'source_before_sha256',
                         'source_after_sha256', 'provenance_sha256']:
                schema(digest(measurement[name]), name)
            schema(measurement['capture_source_map_sha256'] == captured_digest, 'historical source digest')
            schema(measurement['provenance_sha256'] == sha(measurement['compiler_provenance'].encode('utf-8')),
                   'provenance member digest')
    return manifest


def select_measurement(profile, provenance):
    try:
        provenance = normalize_provenance(provenance)
    except ValueError:
        raise ValueError('Outer GJK compiler or toolchain differs from measured profile') from None
    matches = [measurement for measurement in profile['measurements']
               if provenance == normalize_provenance(measurement['compiler_provenance'])]
    if len(matches) != 1:
        raise ValueError('Outer GJK compiler or toolchain differs from measured profile')
    return matches[0]


def validate(output, *, host, inventory, source_hashes, stream, transport):
    manifest = load_manifest(HERE / 'measured-profiles.json')
    host_name = host()
    profile = manifest['profiles'].get(host_name)
    if profile is None:
        raise ValueError('Unknown outer GJK measured profile')
    current = source_hashes()
    expected = {**profile['protected_source_sha256'], **manifest['verification_sha256'][host_name]}
    expected.pop('tools/bullet-rust-gjk-pair-check/measured-profiles.json', None)
    actual = {p: h for p, h in current.items() if p != 'tools/bullet-rust-gjk-pair-check/measured-profiles.json'}
    if actual != expected:
        raise ValueError('Outer GJK source closure differs from reviewed producer and verification code')
    provenance = (output / 'provenance.txt').read_bytes().decode('utf-8')
    measurement = select_measurement(profile, provenance)
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
    default = fixture / ('native-x64.tsv' if host_name.endswith('x64') else 'native.tsv')
    if default.read_bytes().replace(b'\r\n', b'\n') != normalized['compact-native.tsv']:
        raise ValueError('Default fixture differs from measured compact native')
    diff = inventory((fixture / 'native.tsv').read_bytes(), normalized['compact-native.tsv'], 1800)
    if diff != profile['exact_frozen_compact_differences']:
        raise ValueError('Exact compact difference inventory drift')
    full = json.loads((output / 'full-rust-result.json').read_text())
    if full != {'status': 'passed', 'returncode': 0} or type(full.get('returncode')) is not int:
        raise ValueError('Exact full same-host baseline did not pass')
    return {'host': host_name, 'status': 'measured-profile-matched',
            **{name: value for name, value in measurement.items() if name != 'compiler_provenance'},
            'source_sha256': current, 'current_source_map_sha256': source_map_digest(actual),
            'current_source_status': manifest['status'],
            'verification_manifest_sha256': sha((HERE / 'measured-profiles.json').read_bytes()),
            'approval': 'requires fresh four-host gates and independent review'}
