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
SUPPLEMENTAL_SHA256 = '9ef6deafdf627e0e8df714ae0038af947127768ca9f5eb2e46d24a27d022c12c'
BRIDGE_SHA256 = 'f210f29ada5dfc664dc70bd738e561f84ce9c11c0db239674596fb557f5c6c63'
REGISTRATION_FORMAT = {
    'kind': 'fixed-registration-leading-lf-removal',
    'parent_head': '32c0959476e3e5e5964f78dad84616caccec6a42',
    'format_head': 'd51054c6c8925c4775d8b73c05357e8fd61eec06',
    'format_tree': '02c2f2d270758051b24a27e930efe6a88f17302f',
    'path': 'rust/crates/mds-bullet/tests/pure_bullet.rs',
    'old_sha256': '448ee12c55dfad95be039dd94f3bc33d223fdacdb3cc9c8497e374cc275f53c0',
    'new_sha256': 'db2ec5f155bf1f7a10654a7c0c263435349ba55c8fe1c5fcfdcc67853fba7157',
}
BROADPHASE_SHA256 = '12aafd16e106fe98db03326b9b354a80f1d3722bfc6e25eaad53fe22dd499c96'
BROADPHASE_ADDITIONS = {'rust/crates/mds-bullet/' + path for path in
                        ['src/core/dbvt_broadphase.rs', 'tests/pure_bullet/dbvt_broadphase.rs']}
HISTORICAL_SHA256 = 'db3da5b75c9c53145e6be0aec4f83264f3a0bbce2a128ea321caf24ae0e7e501'
REPLACEMENTS = {'rust/crates/mds-bullet/' + path for path in
                ['src/core/dbvt.rs', 'src/core/mod.rs', 'tests/pure_bullet.rs']}
ADDITIONS = {'rust/crates/mds-bullet/tests/' + path for path in
             ['pure_bullet/dbvt.rs', *['dbvt_data/' + name for name in
              ['archive-intersect.tsv', 'archive-merge.tsv', 'inline-aabb.tsv',
               'inputs.tsv', 'provenance.json', 'select.tsv']]]}
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
               and not any(ord(c) < 32 or ord(c) == 127 for c in path)
               and ':' not in path and '\\' not in path and all(part not in {'', '.', '..'} for part in path.split('/'))
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
    fields(manifest, {'schema_version', 'status', 'frozen_fixtures', 'profiles', 'verification_sha256', 'source_admission', 'registration_format_admission', 'broadphase_source_admission', 'supplemental_measurements'}, 'manifest')
    schema(type(manifest['schema_version']) is int and manifest['schema_version'] == 6, 'schema_version')
    schema(manifest['status'] == 'reviewed-current-source-expectation-execution-pending', 'status')
    fields(manifest['profiles'], HOSTS, 'profiles')
    fields(manifest['verification_sha256'], HOSTS, 'verification hosts')
    fields(manifest['frozen_fixtures'], {'inputs.tsv', 'native.tsv', 'fallback-inputs.tsv', 'fallback-native.tsv'}, 'fixtures')
    for identity in manifest['frozen_fixtures'].values():
        fields(identity, {'git_blob', 'sha256'}, 'fixture')
        schema(digest(identity['git_blob'], 40) and digest(identity['sha256']), 'fixture identity')
    artifact_ids, job_ids, provenances = set(), set(), set()
    def validate_measurement(measurement, captured_digest, expected_fields):
        fields(measurement, expected_fields, 'measurement')
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
        schema(measurement['capture_source_map_sha256'] == captured_digest, 'captured source digest')
        schema(measurement['provenance_sha256'] == sha(measurement['compiler_provenance'].encode('utf-8')),
               'provenance member digest')

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
            validate_measurement(measurement, captured_digest, MEASUREMENT_FIELDS)
    schema(source_map_digest({name: manifest[name] for name in ['profiles', 'frozen_fixtures']})
           == HISTORICAL_SHA256, 'immutable historical projection')
    admission = manifest['source_admission']
    fields(admission, {'kind', 'reviewed_base_head', 'integration_head', 'integration_tree', 'hosts'}, 'source admission')
    schema(admission['kind'] == 'bounded-dbvt-policy-bridge', 'source admission kind')
    for name in ['reviewed_base_head', 'integration_head', 'integration_tree']:
        schema(digest(admission[name], 40), 'source admission ' + name)
    schema(admission['reviewed_base_head'] == '4d6878ec05e9ec63f4514bdc21ba679f36681fce'
           and admission['integration_head'] == 'c31de92064e960f88c142c7f86e506477f14f8e0'
           and admission['integration_tree'] == '12affc9b9b2b260012a71dfa74644942999116a6',
           'source admission reviewed integration')
    fields(admission['hosts'], HOSTS, 'source admission hosts')
    schema(source_map_digest(admission) == BRIDGE_SHA256, 'immutable source admission')
    schema(manifest['registration_format_admission'] == REGISTRATION_FORMAT, 'fixed registration format admission')
    schema(source_map_digest(manifest['broadphase_source_admission']) == BROADPHASE_SHA256,
           'immutable broadphase source admission')
    for host in HOSTS:
        approved_source_map(manifest, host)
    supplemental = manifest['supplemental_measurements']
    schema(isinstance(supplemental, list) and len(supplemental) == 1, 'one supplemental measurement')
    for measurement in supplemental:
        fields(measurement, MEASUREMENT_FIELDS | {'host', 'captured_verification_sha256'}, 'supplemental measurement')
        schema(measurement['host'] == 'linux-arm64', 'supplemental host')
        captured = measurement['captured_verification_sha256']
        hash_map(captured, 10, 'captured verification')
        schema(set(captured) == verification_paths, 'captured verification paths')
        protected = bridge_protected_source_map(manifest, measurement['host'])
        validate_measurement(measurement, source_map_digest({**protected, **captured}),
                             MEASUREMENT_FIELDS | {'host', 'captured_verification_sha256'})
    schema(source_map_digest(supplemental) == SUPPLEMENTAL_SHA256, 'immutable supplemental projection')
    return manifest


def bridge_protected_source_map(manifest, host):
    profile = manifest['profiles'][host]
    protected = profile['protected_source_sha256']
    verification = profile['measured_verification_sha256']
    delta = manifest['source_admission']['hosts'][host]
    fields(delta, {'replacements', 'additions'}, 'source admission delta')
    for name, paths in [('replacements', REPLACEMENTS), ('additions', ADDITIONS)]:
        hash_map(delta[name], len(paths), 'source admission ' + name)
        schema(set(delta[name]) == paths, 'source admission ' + name + ' paths')
    schema(not REPLACEMENTS & ADDITIONS, 'source admission overlap')
    schema(REPLACEMENTS <= set(protected), 'replacement must exist historically')
    schema(not ADDITIONS & (set(protected) | set(profile['measured_verification_sha256'])
                            | set(verification)), 'addition must be absent historically')
    schema(not (REPLACEMENTS | ADDITIONS) & set(verification), 'source admission verification overlap')
    schema(all(delta['replacements'][path] != protected[path] for path in REPLACEMENTS),
           'replacement must change historical hash')
    return {**protected, **delta['replacements'], **delta['additions']}


def approved_source_map(manifest, host):
    protected = bridge_protected_source_map(manifest, host)
    admission = manifest['registration_format_admission']
    schema(admission == REGISTRATION_FORMAT, 'fixed registration format admission')
    schema(protected[admission['path']] == admission['old_sha256'], 'registration old identity')
    protected[admission['path']] = admission['new_sha256']
    delta = manifest['broadphase_source_admission']['hosts'][host]
    fields(delta, {'replacements', 'additions'}, 'broadphase delta')
    fields(delta['replacements'], REPLACEMENTS, 'broadphase replacements')
    hash_map(delta['additions'], 2, 'broadphase additions')
    schema(set(delta['additions']) == BROADPHASE_ADDITIONS, 'broadphase addition paths')
    schema(not BROADPHASE_ADDITIONS & (set(protected) | set(manifest['verification_sha256'][host])),
           'broadphase additions must be absent')
    for path, identity in delta['replacements'].items():
        fields(identity, {'old_sha256', 'new_sha256'}, 'broadphase replacement')
        schema(protected[path] == identity['old_sha256'], 'broadphase old identity')
        schema(digest(identity['new_sha256']) and identity['new_sha256'] != identity['old_sha256'],
               'broadphase new identity')
        protected[path] = identity['new_sha256']
    return {**protected, **delta['additions'], **manifest['verification_sha256'][host]}


def select_measurement(manifest, host, provenance):
    try:
        provenance = normalize_provenance(provenance)
    except ValueError:
        raise ValueError('Outer GJK compiler or toolchain differs from measured profile') from None
    candidates = manifest['profiles'][host]['measurements'] + [
        measurement for measurement in manifest['supplemental_measurements'] if measurement['host'] == host]
    matches = [measurement for measurement in candidates
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
    expected = approved_source_map(manifest, host_name)
    actual = {p: h for p, h in current.items() if p != 'tools/bullet-rust-gjk-pair-check/measured-profiles.json'}
    if actual != expected:
        raise ValueError('Outer GJK source closure differs from reviewed producer and verification code')
    capture_head = (output / 'source-head.txt').read_bytes()
    if re.fullmatch(rb'[0-9a-f]{40}(?:\n|\r\n)', capture_head) is None:
        raise ValueError('Outer GJK capture source head framing differs')
    capture_head = capture_head[:40].decode('ascii')
    provenance = (output / 'provenance.txt').read_bytes().decode('utf-8')
    measurement = select_measurement(manifest, host_name, provenance)
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
            'measurement_reference': {
                'role': 'supplemental-reference' if 'host' in measurement else 'historical-reference',
                **{name: value for name, value in measurement.items() if name != 'compiler_provenance'}},
            'current_source': {
                'bridge': {name: value for name, value in manifest['source_admission'].items() if name != 'hosts'},
                'registration_format_admission': manifest['registration_format_admission'],
                'broadphase_source_admission': {name: value for name, value in
                    manifest['broadphase_source_admission'].items() if name != 'hosts'},
                'capture_head': capture_head, 'source_sha256': current,
                'source_map_sha256': source_map_digest(actual),
                'status': manifest['status'],
                'verification_manifest_sha256': sha((HERE / 'measured-profiles.json').read_bytes())},
            'approval': 'requires fresh four-host gates and independent review'}
