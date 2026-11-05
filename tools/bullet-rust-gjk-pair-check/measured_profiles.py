import hashlib
import json
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
VERIFICATION_BASE = 'f6ab4feef335e76d590c3f8a9c5f532dec73ba70'
VERIFICATION_BASE_SHA256 = '4092dd2ca3f1c3018ba144136d5c8c68da2c5d7628ff1b58a1258d23dea159e7'
VERIFICATION_BASE_BLOBS = {
    '.github/workflows/bullet-outer-gjk-host-capture.yml': 'c9b0e3155dd819ad49b0b085c735879e3fa0cf90',
    'rust/crates/mds-bullet/tests/gjk_pair_data/native-x64.tsv': 'a033f5920e953595291bd0bd5b0224ef80faa616',
    'rust/crates/mds-bullet/tests/pure_bullet/gjk_pair.rs': '35fafde6cd1aa3e3a2eae1817fffb644ced576d3',
    **{'tools/bullet-rust-gjk-pair-check/' + path: blob for path, blob in {
        'README.md': 'c353451a3b782cbe191f1d9aa4ec2d91ac666844',
        'check.py': '72925f3bc3801214830d7d2d950c9c589ee9ce7e',
        'measured_profiles.py': '8506a6d9a6d629131c8c76b089fba9623df80c9f',
        'mutations.py': '76cb81ca475a77f62957a86d178fb9462d7d72ff',
        'native-x64-provenance.json': '9fbf529808e40dc9a1599154f1c73c6dcbcf49fc',
        'test_capture.py': 'ce6f861bf82408cad1f10bc425e2ca136adc7ca9',
        'test_measured_profiles.py': 'a4cef940a72d0e0fa8f936adfacbbd9d0c8376ca',
    }.items()},
}
VERIFICATION_LAYER_PATHS = {'tools/bullet-rust-gjk-pair-check/' + path for path in
                            ['README.md', 'check.py', 'measured_profiles.py', 'test_measured_profiles.py']}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical_command(command, root, output):
    root, output = str(root).replace('\\', '/'), str(output).replace('\\', '/')
    return [word.replace('\\', '/').replace(root, '$ROOT').replace(output, '$CAPTURE')
            for word in command]



MANIFEST_PATH = 'tools/bullet-rust-gjk-pair-check/measured-profiles.json'
SUPPLEMENTAL_SHA256 = '9ef6deafdf627e0e8df714ae0038af947127768ca9f5eb2e46d24a27d022c12c'
MACOS_SUPPLEMENTAL_SHA256 = '2e189e3049060b4409f692d3cc94bb4f99cd24651b17fa941cecc7c5caff72a0'
MACOS_CAPTURE_HEAD = '10bfc00bf80178818ca42cf316ed366a4fe435cf'
MACOS_CAPTURE_PROTECTED_SHA256 = '1e930187f12f91991098407bc79a1555735230a20c14272b3f62286fe87f8368'
MACOS_CAPTURE_VERIFICATION_SHA256 = 'e5194fbae277658529c65e7a5bb8f91aa6306f6ca105fc263a06c62952e39819'
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
DISCRETE_WORLD_SHA256 = 'ad4394ab65ef522aa251da2cd91ccfa18afe0a7e63de9ffe1233141e72e8c030'
DISCRETE_WORLD_ADDITIONS = {'rust/crates/mds-bullet/' + path for path in
                            ['src/core/discrete_collision_world.rs', 'tests/discrete_collision_world.rs']}
DISCRETE_WORLD_REPLACEMENTS = {'rust/crates/mds-bullet/src/core/mod.rs'}
MMD_COLLISION_WORLD_SHA256 = '59875b274c0099e5c49d51f76cef60a7af70646b9abdbe2bc3b7fadeb31c93e3'
MMD_COLLISION_WORLD_ADDITIONS = {'rust/crates/mds-bullet/' + path for path in
                                ['src/core/mmd_collision_world.rs', 'tests/mmd_collision_world.rs']}
MMD_COLLISION_WORLD_REPLACEMENTS = {'rust/crates/mds-bullet/src/core/mod.rs'}
MMD_COLLISION_WORLD_FORMAT = {
    'kind': 'fixed-mmd-collision-world-rustfmt-source-only',
    'base_head': '461351137b525475e43add330fd258885956067f',
    'format_head': '6e16debd2b5c8d3b309d60b47bd0badce1e2175c',
    'format_tree': 'e7354fdb6b89e5b56e78a189a032f2d275b42e2e',
    'execution': 'UNRUN',
    'path': 'rust/crates/mds-bullet/tests/mmd_collision_world.rs',
    'mode': '100644',
    'old_blob': 'cd4af6aa929a93c8313ba330acd7a0ab590c3c7d',
    'new_blob': '7b8185f26fcfa4dfdd9817f93c0f5a475aee873a',
    'hosts': {host: {
        'old_sha256': 'e07de6bdf38382ad5b6e417c9134264f95ecff56365aba0ae365af22864f23fd',
        'new_sha256': '8a31d5dbc0e14024762199975064b702268bc8bb4dac7997d4e33b574792ba52',
    } for host in ['macos-arm64', 'linux-arm64', 'linux-x64', 'windows-x64']},
}
DYNAMICS_WORLD_C23_TEST_FORMAT_SHA256 = '795b2906a053fabc3e9728c575bd3372c564abfa52700223da18f8158e03ae5c'
DYNAMICS_WORLD_C23_TEST_FORMAT_REPLACEMENTS = {'rust/crates/mds-bullet/tests/discrete_dynamics_world.rs'}
DYNAMICS_WORLD_C23_REPAIR_SHA256 = '803c1e31e1bfbcfc805f0559c00bbd2f76a0101a76c603d29922150cb39e03ee'
DYNAMICS_WORLD_C23_REPAIR_REPLACEMENTS = {'rust/crates/mds-bullet/' + path for path in
                                           ['src/core/discrete_collision_world.rs', 'tests/discrete_dynamics_world.rs']}
DYNAMICS_WORLD_FORMAT_SHA256 = 'afff937521417b8c762b4c485417b374be72f26499fb71294cc85b741f658128'
DYNAMICS_WORLD_SHA256 = 'a978d073cff65ea0f017924e245697202bf8763eef79895bf1e2b5ee5c407c06'
DYNAMICS_WORLD_ADDITIONS = {'rust/crates/mds-bullet/' + path for path in
                           ['src/core/discrete_dynamics_world.rs', 'tests/discrete_dynamics_world.rs']}
DYNAMICS_WORLD_REPLACEMENTS = {'rust/crates/mds-bullet/src/core/' + path for path in
                             ['mod.rs', 'world_objects.rs', 'discrete_collision_world.rs']}
BROADPHASE_SHA256 = '539ad318be991f1b55770363f2698f08cd86f85280d8b46e0600ec44df32d53d'
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


@lru_cache(maxsize=8)
def git_verification_maps(head, host):
    schema(digest(head, 40) and host in HOSTS, 'current verification context')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(ROOT), *args])
    entries = git('ls-tree', '-r', '-z', head, '--', *sorted(VERIFICATION_BASE_BLOBS)).split(b'\0')
    blobs = {}
    for entry in filter(None, entries):
        metadata, path = entry.decode('ascii').split('\t')
        mode, kind, blob = metadata.split()
        schema(mode == '100644' and kind == 'blob', 'verification regular mode')
        blobs[path] = blob
    schema(set(blobs) == set(VERIFICATION_BASE_BLOBS), 'verification fixed paths')
    schema({p for p in blobs if blobs[p] != VERIFICATION_BASE_BLOBS[p]} <= VERIFICATION_LAYER_PATHS,
           'verification layer scope')
    physical = {}
    for path, blob in blobs.items():
        body = git('cat-file', 'blob', blob)
        if host == 'windows-x64' and '/tests/' not in path:
            body = body.replace(b'\n', b'\r\n')
        physical[path] = sha(body)
    return physical


def current_verification_map(manifest, host):
    schema(source_map_digest(manifest['verification_sha256']) == VERIFICATION_BASE_SHA256,
           'immutable baseline verification')
    head = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']).decode('ascii').strip()
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        schema(head == os.environ.get('GITHUB_SHA'), 'trusted checkout head')
    return git_verification_maps(head, host)


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
    fields(manifest, {'schema_version', 'status', 'frozen_fixtures', 'profiles', 'verification_sha256', 'source_admission', 'registration_format_admission', 'broadphase_source_admission', 'discrete_world_source_admission', 'dynamics_world_source_admission', 'dynamics_world_format_admission', 'dynamics_world_c23_repair_admission', 'dynamics_world_c23_test_format_admission', 'mmd_collision_world_source_admission', 'supplemental_measurements'}, 'manifest')
    schema(type(manifest['schema_version']) is int and manifest['schema_version'] == 13, 'schema_version')
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
    schema(source_map_digest(manifest['discrete_world_source_admission']) == DISCRETE_WORLD_SHA256,
           'immutable discrete world source admission')
    schema(source_map_digest(manifest['dynamics_world_source_admission']) == DYNAMICS_WORLD_SHA256,
           'immutable dynamics world source admission')
    schema(source_map_digest(manifest['dynamics_world_format_admission']) == DYNAMICS_WORLD_FORMAT_SHA256,
           'immutable dynamics world format admission')
    schema(source_map_digest(manifest['dynamics_world_c23_repair_admission']) == DYNAMICS_WORLD_C23_REPAIR_SHA256,
           'immutable dynamics world c23 repair admission')
    schema(source_map_digest(manifest['dynamics_world_c23_test_format_admission']) == DYNAMICS_WORLD_C23_TEST_FORMAT_SHA256,
           'immutable dynamics world c23 test format admission')
    for host in HOSTS:
        approved_source_map(manifest, host)
    supplemental = manifest['supplemental_measurements']
    schema(isinstance(supplemental, list) and len(supplemental) == 2, 'two supplemental measurements')
    for host, measurement in zip(['linux-arm64', 'macos-arm64'], supplemental):
        fields(measurement, MEASUREMENT_FIELDS | {'host', 'captured_verification_sha256'}, 'supplemental measurement')
        schema(measurement['host'] == host, 'ordered supplemental host')
        captured = measurement['captured_verification_sha256']
        hash_map(captured, 10, 'captured verification')
        schema(set(captured) == verification_paths, 'captured verification paths')
        if host == 'macos-arm64':
            schema(measurement['evidence_head'] == MACOS_CAPTURE_HEAD, 'macOS captured source generation')
            schema(source_map_digest(captured) == MACOS_CAPTURE_VERIFICATION_SHA256,
                   'immutable macOS captured verification')
            protected = macos_capture_protected_source_map(manifest)
        else:
            protected = bridge_protected_source_map(manifest, host)
        validate_measurement(measurement, source_map_digest({**protected, **captured}),
                             MEASUREMENT_FIELDS | {'host', 'captured_verification_sha256'})
    schema(source_map_digest(supplemental[:1]) == SUPPLEMENTAL_SHA256, 'immutable supplemental projection')
    schema(source_map_digest(supplemental[1]) == MACOS_SUPPLEMENTAL_SHA256, 'immutable macOS supplemental projection')
    return manifest


def macos_capture_protected_source_map(manifest):
    # Reconstruct the fixed 10bf generation without current verification or later admissions.
    protected = bridge_protected_source_map(manifest, 'macos-arm64')
    protected[REGISTRATION_FORMAT['path']] = REGISTRATION_FORMAT['new_sha256']
    for name in ['broadphase_source_admission', 'discrete_world_source_admission',
                 'dynamics_world_source_admission', 'dynamics_world_format_admission',
                 'dynamics_world_c23_repair_admission', 'dynamics_world_c23_test_format_admission',
                 'mmd_collision_world_source_admission']:
        delta = manifest[name]['hosts']['macos-arm64']
        protected.update({path: identity['new_sha256'] for path, identity in delta['replacements'].items()})
        protected.update(delta.get('additions', {}))
    protected = apply_mmd_collision_format_admission(protected, 'macos-arm64')
    hash_map(protected, 472, 'macOS captured protected source')
    schema(source_map_digest(protected) == MACOS_CAPTURE_PROTECTED_SHA256,
           'immutable macOS captured protected source')
    return protected


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
    schema(type(manifest['schema_version']) is int and manifest['schema_version'] == 13, 'schema_version')
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
    protected = {**protected, **delta['additions']}
    admission = manifest['discrete_world_source_admission']
    fields(admission, {'kind', 'base_head', 'base_tree', 'execution', 'hosts'}, 'discrete world admission')
    schema(admission['kind'] == 'private-discrete-world-source-only'
           and admission['base_head'] == 'c8dc8a387a9d37442a84dbd8a3b81c90898b6d6d'
           and admission['base_tree'] == '58cbf7ede0dc2e22958765d4856e72ed9addc033'
           and admission['execution'] == 'UNRUN', 'fixed discrete world base and execution')
    fields(admission['hosts'], HOSTS, 'discrete world hosts')
    delta = admission['hosts'][host]
    fields(delta, {'replacements', 'additions'}, 'discrete world delta')
    fields(delta['replacements'], DISCRETE_WORLD_REPLACEMENTS, 'discrete world replacements')
    hash_map(delta['additions'], 2, 'discrete world additions')
    schema(set(delta['additions']) == DISCRETE_WORLD_ADDITIONS, 'discrete world addition paths')
    schema(not DISCRETE_WORLD_ADDITIONS & (set(protected) | set(manifest['verification_sha256'][host])),
           'discrete world additions must be absent')
    for path, identity in delta['replacements'].items():
        fields(identity, {'old_sha256', 'new_sha256'}, 'discrete world replacement')
        schema(protected[path] == identity['old_sha256'], 'discrete world old identity')
        schema(digest(identity['new_sha256']) and identity['new_sha256'] != identity['old_sha256'],
               'discrete world new identity')
        protected[path] = identity['new_sha256']
    protected = {**protected, **delta['additions']}
    admission = manifest['dynamics_world_source_admission']
    fields(admission, {'kind', 'base_head', 'base_tree', 'execution', 'hosts'}, 'dynamics world admission')
    schema(admission['kind'] == 'private-dynamics-world-source-only'
           and admission['base_head'] == '816df8133b021359a2684c2ad5fd3666583c7c60'
           and admission['base_tree'] == 'ef7ae5c209fa4cdc5669a3757effe770f8f19df0'
           and admission['execution'] == 'UNRUN', 'fixed dynamics world base and execution')
    fields(admission['hosts'], HOSTS, 'dynamics world hosts')
    delta = admission['hosts'][host]
    fields(delta, {'replacements', 'additions'}, 'dynamics world delta')
    fields(delta['replacements'], DYNAMICS_WORLD_REPLACEMENTS, 'dynamics world replacements')
    hash_map(delta['additions'], len(DYNAMICS_WORLD_ADDITIONS), 'dynamics world additions')
    schema(set(delta['additions']) == DYNAMICS_WORLD_ADDITIONS, 'dynamics world addition paths')
    schema(not DYNAMICS_WORLD_ADDITIONS & (set(protected) | set(manifest['verification_sha256'][host])),
           'dynamics world additions must be absent')
    for path, identity in delta['replacements'].items():
        fields(identity, {'old_sha256', 'new_sha256'}, 'dynamics world replacement')
        schema(protected[path] == identity['old_sha256'], 'dynamics world old identity')
        schema(digest(identity['new_sha256']) and identity['new_sha256'] != identity['old_sha256'],
               'dynamics world new identity')
        protected[path] = identity['new_sha256']
    protected = {**protected, **delta['additions']}
    admission = manifest['dynamics_world_format_admission']
    fields(admission, {'kind', 'base_head', 'base_tree', 'execution', 'hosts'}, 'dynamics world format admission')
    schema(admission['kind'] == 'private-dynamics-world-format-source-only'
           and admission['base_head'] == 'cdfd6d19f2e46a2526f61a4dff49a2065da767ef'
           and admission['base_tree'] == 'b51ac697c13fcddce69ee99ebdae4091698521f7'
           and admission['execution'] == 'UNRUN', 'fixed dynamics world format base and execution')
    fields(admission['hosts'], HOSTS, 'dynamics world format hosts')
    delta = admission['hosts'][host]
    fields(delta, {'replacements'}, 'dynamics world format delta')
    fields(delta['replacements'], DYNAMICS_WORLD_ADDITIONS, 'dynamics world format replacements')
    for path, identity in delta['replacements'].items():
        fields(identity, {'old_sha256', 'new_sha256'}, 'dynamics world format replacement')
        schema(protected[path] == identity['old_sha256'], 'dynamics world format old identity')
        schema(digest(identity['new_sha256']) and identity['new_sha256'] != identity['old_sha256'],
               'dynamics world format new identity')
        protected[path] = identity['new_sha256']
    schema(source_map_digest(admission) == DYNAMICS_WORLD_FORMAT_SHA256,
           'immutable dynamics world format admission')
    admission = manifest['dynamics_world_c23_repair_admission']
    fields(admission, {'kind', 'base_head', 'base_tree', 'execution', 'hosts'}, 'dynamics world c23 repair admission')
    schema(admission['kind'] == 'private-dynamics-world-c23-repair-source-only'
           and admission['base_head'] == 'c23bdf22be1de8a25db62c0be758b8aa93f0cc7e'
           and admission['base_tree'] == '5aa95cc9f23054b68b4a7055d2995a044c74923e'
           and admission['execution'] == 'UNRUN', 'fixed dynamics world c23 repair base and execution')
    fields(admission['hosts'], HOSTS, 'dynamics world c23 repair hosts')
    delta = admission['hosts'][host]
    fields(delta, {'replacements'}, 'dynamics world c23 repair delta')
    fields(delta['replacements'], DYNAMICS_WORLD_C23_REPAIR_REPLACEMENTS, 'dynamics world c23 repair replacements')
    for path, identity in delta['replacements'].items():
        fields(identity, {'old_sha256', 'new_sha256'}, 'dynamics world c23 repair replacement')
        schema(protected[path] == identity['old_sha256'], 'dynamics world c23 repair old identity')
        schema(digest(identity['new_sha256']) and identity['new_sha256'] != identity['old_sha256'],
               'dynamics world c23 repair new identity')
        protected[path] = identity['new_sha256']
    schema(source_map_digest(admission) == DYNAMICS_WORLD_C23_REPAIR_SHA256,
           'immutable dynamics world c23 repair admission')
    schema('dynamics_world_c23_test_format_admission' in manifest, 'required dynamics world c23 test format admission')
    admission = manifest['dynamics_world_c23_test_format_admission']
    fields(admission, {'kind', 'base_head', 'base_tree', 'execution', 'hosts'}, 'dynamics world c23 test format admission')
    schema(admission['kind'] == 'private-dynamics-world-c23-test-format-source-only'
           and admission['base_head'] == '487959db4546d5f71bfafa552f85ccada42073ee'
           and admission['base_tree'] == '5b36d3c3ce0b673ba3d7f78de6b0da320255d4ea'
           and admission['execution'] == 'UNRUN', 'fixed dynamics world c23 test format base and execution')
    fields(admission['hosts'], HOSTS, 'dynamics world c23 test format hosts')
    delta = admission['hosts'][host]
    fields(delta, {'replacements'}, 'dynamics world c23 test format delta')
    fields(delta['replacements'], DYNAMICS_WORLD_C23_TEST_FORMAT_REPLACEMENTS, 'dynamics world c23 test format replacements')
    for path, identity in delta['replacements'].items():
        fields(identity, {'old_sha256', 'new_sha256'}, 'dynamics world c23 test format replacement')
        schema(protected[path] == identity['old_sha256'], 'dynamics world c23 test format old identity')
        schema(digest(identity['new_sha256']) and identity['new_sha256'] != identity['old_sha256'],
               'dynamics world c23 test format new identity')
        protected[path] = identity['new_sha256']
    schema(source_map_digest(admission) == DYNAMICS_WORLD_C23_TEST_FORMAT_SHA256,
           'immutable dynamics world c23 test format admission')
    protected = apply_mmd_collision_admission(manifest, host, protected)
    protected = apply_mmd_collision_format_admission(protected, host)
    return {**protected, **current_verification_map(manifest, host)}


def apply_mmd_collision_admission(manifest, host, protected):
    schema('mmd_collision_world_source_admission' in manifest, 'required MMD collision world admission')
    admission = manifest['mmd_collision_world_source_admission']
    fields(admission, {'kind', 'base_head', 'base_tree', 'execution', 'hosts'}, 'MMD collision world admission')
    schema(admission['kind'] == 'private-mmd-collision-world-source-only'
           and admission['base_head'] == 'f6ab4feef335e76d590c3f8a9c5f532dec73ba70'
           and admission['base_tree'] == '005ae1183e9972df56689796cf87589117418e7d'
           and admission['execution'] == 'UNRUN', 'fixed MMD collision world base and execution')
    fields(admission['hosts'], HOSTS, 'MMD collision world hosts')
    delta = admission['hosts'][host]
    fields(delta, {'replacements', 'additions'}, 'MMD collision world delta')
    fields(delta['replacements'], MMD_COLLISION_WORLD_REPLACEMENTS, 'MMD collision world replacements')
    hash_map(delta['additions'], len(MMD_COLLISION_WORLD_ADDITIONS), 'MMD collision world additions')
    schema(set(delta['additions']) == MMD_COLLISION_WORLD_ADDITIONS, 'MMD collision world addition paths')
    schema(not MMD_COLLISION_WORLD_ADDITIONS & (set(protected) | set(manifest['verification_sha256'][host])),
           'MMD collision world additions must be absent')
    for path, identity in delta['replacements'].items():
        fields(identity, {'old_sha256', 'new_sha256'}, 'MMD collision world replacement')
        schema(protected[path] == identity['old_sha256'], 'MMD collision world old identity')
        schema(digest(identity['new_sha256']) and identity['new_sha256'] != identity['old_sha256'],
               'MMD collision world new identity')
        protected[path] = identity['new_sha256']
    schema(source_map_digest(admission) == MMD_COLLISION_WORLD_SHA256,
           'immutable MMD collision world admission')
    return {**protected, **delta['additions']}


def apply_mmd_collision_format_admission(protected, host):
    admission = MMD_COLLISION_WORLD_FORMAT
    identity = admission['hosts'][host]
    path = admission['path']
    schema(protected.get(path) == identity['old_sha256'], 'MMD collision world format old identity')
    return {**protected, path: identity['new_sha256']}


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
                'discrete_world_source_admission': {name: value for name, value in
                    manifest['discrete_world_source_admission'].items() if name != 'hosts'},
                'dynamics_world_source_admission': {name: value for name, value in
                    manifest['dynamics_world_source_admission'].items() if name != 'hosts'},
                'dynamics_world_format_admission': {name: value for name, value in
                    manifest['dynamics_world_format_admission'].items() if name != 'hosts'},
                'dynamics_world_c23_repair_admission': {name: value for name, value in
                    manifest['dynamics_world_c23_repair_admission'].items() if name != 'hosts'},
                'dynamics_world_c23_test_format_admission': {name: value for name, value in
                    manifest['dynamics_world_c23_test_format_admission'].items() if name != 'hosts'},
                'mmd_collision_world_source_admission': {name: value for name, value in
                    manifest['mmd_collision_world_source_admission'].items() if name != 'hosts'},
                'mmd_collision_world_format_admission': MMD_COLLISION_WORLD_FORMAT,
                'historical_verification_baseline': {
                    'head': VERIFICATION_BASE, 'four_host_map_sha256': VERIFICATION_BASE_SHA256,
                    'physical_sha256': manifest['verification_sha256'][host_name]},
                'capture_head': capture_head, 'source_sha256': current,
                'source_map_sha256': source_map_digest(actual),
                'status': manifest['status'],
                'verification_manifest_sha256': sha((HERE / 'measured-profiles.json').read_bytes())},
            'approval': 'requires fresh four-host gates and independent review'}
