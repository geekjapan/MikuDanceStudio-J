"""Finite historical CMP sequencing experiment. Never a production acceptance gate."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import shlex
import stat
import subprocess
import sys
import tarfile
import zipfile

HEAD = 'f9c4036b21aa80d7c90b9ce099adbd7054b7f1cd'
RUN = 40470251499
REPO = 'geekjapan/MikuDanceStudio-J'
ARTIFACTS = {
    'all-units': (12719650280, 'ada0c681694217c3b852fe6c31d0826ab871e9731deafbee365d70ced78e0d89'),
    'input': (12718571621, 'e0840d194fcdfbb056b966a342c61b10b3c5dffc01915b2fd869a821a9aec47a'),
}
C_SHA = '8b3aaa79d65011d9f4a3e190a6e4dea4dab80f696f43c7b0c89f3a9147dab41e'
RUST_SHA = '9e85ae03ec8f20975e0910ca34da121e5e7290f675bc34710e5ad2be6b7d0bb6'
BODY_SHA = '81fb9025c723c679065dbe86894bdcaf9b5db7e2047dec713413b0d7fc2edc2c'
INVENTORY_SHA = '0a71e41777830b57ecf439b2a8f89cff7d7bf75c63724b017257caf4b645db63'
LOCK_SHA = 'c90020c8f96c5fbc2e63a9124cf89efb67cf30fa7bf0cd5fdffe0e741e381bff'
LICENSE_SHA = 'dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551'
UNIT = '/home/runner/work/_temp/vkd3d-probe/evidence/result/source/libs/vkd3d-shader/spirv.c'
RUST_PATH = Path('src/vkd3d_shader/spirv.rs')
DIRECTED = {'branch-ps-2_0-1', 'branch-ps-3_0-1'}
TYPE = '''spirv_get_type_id(
                    compiler,
                    vsir_data_type::VSIR_DATA_BOOL,
                    component_count,
                )'''
ZERO = '''spirv_compiler_get_constant_float_vector(
                    compiler,
                    0.0f32,
                    component_count,
                )'''
CALL = '''            condition_id = vkd3d_spirv_build_op_tr2(
                builder,
                &raw mut (*builder).function_stream,
                SpvOp_::SpvOpFOrdGreaterThanEqual,
                ''' + TYPE + ''',
                condition_id,
                ''' + ZERO + ''',
            );'''
C_CALL = '''            condition_id = vkd3d_spirv_build_op_tr2(builder, &builder->function_stream, SpvOpFOrdGreaterThanEqual,
                    spirv_get_type_id(compiler, VSIR_DATA_BOOL, component_count), condition_id,
                    spirv_compiler_get_constant_float_vector(compiler, 0.0f, component_count));'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def manifest(root):
    return {str(p.relative_to(root)): sha(p.read_bytes()) for p in sorted(root.rglob('*')) if p.is_file()}


def safe_name(name):
    path = PurePosixPath(name)
    require(name and not path.is_absolute() and '..' not in path.parts and '\\' not in name,
            'unsafe archive path ' + name)
    return path


def unzip(data, destination):
    records = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            path = safe_name(member.filename)
            key = str(path)
            require(key not in records, 'duplicate ZIP path ' + key)
            mode = member.external_attr >> 16
            require(not stat.S_ISLNK(mode), 'ZIP symlink ' + key)
            content = archive.read(member)
            records[key] = {'sha256': sha(content), 'size': len(content), 'mode': mode}
            target = destination / key
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
    return records


def unpack_input(path, destination):
    records = {}
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            name = str(safe_name(member.name))
            require(name not in records, 'duplicate tar path ' + name)
            require(member.isdir() or member.isfile() or member.issym(), 'unsupported tar member ' + name)
            if member.issym():
                safe_name(str(PurePosixPath(name).parent / member.linkname))
                require(not PurePosixPath(member.linkname).is_absolute(), 'absolute tar link')
                records[name] = {'link': member.linkname}
            elif member.isfile():
                content = archive.extractfile(member).read()
                records[name] = {'sha256': sha(content), 'size': len(content), 'mode': member.mode}
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            else:
                records[name] = {'directory': True}
    return records


def fetch_inputs(destination, run=None):
    def api(endpoint, binary=False):
        command = ['gh', 'api', 'repos/' + REPO + endpoint]
        if run is None:
            result = subprocess.run(command, check=True, stdout=subprocess.PIPE, timeout=120)
            content = result.stdout
        else:
            log = destination / ('api-' + endpoint.strip('/').replace('/', '-') + ('.zip' if binary else '.json'))
            receipt = run(command, log, timeout=120)
            require(receipt['exit_code'] == 0 and not receipt['timed_out'], 'artifact API process failed')
            content = log.read_bytes()
        return content if binary else json.loads(content)
    historical_run = api('/actions/runs/' + str(RUN))
    require(historical_run['head_sha'] == HEAD and historical_run['id'] == RUN and historical_run['run_attempt'] == 1
            and historical_run['repository']['full_name'] == REPO and historical_run['path'] == '.github/workflows/vkd3d-rust-probe.yml',
            'historical run identity differs')
    write_json(destination / 'historical-run.json', historical_run)
    for name, (artifact_id, digest) in ARTIFACTS.items():
        metadata = api('/actions/artifacts/' + str(artifact_id))
        require(metadata['id'] == artifact_id and metadata['name'] == 'vkd3d-probe-' + name
                and not metadata['expired'] and metadata['workflow_run']['id'] == RUN
                and metadata['workflow_run']['head_sha'] == HEAD and metadata['digest'] == 'sha256:' + digest,
                'artifact API identity differs ' + name)
        write_json(destination / (name + '-api.json'), metadata)
        content = api('/actions/artifacts/' + str(artifact_id) + '/zip', True)
        require(len(content) == metadata['size_in_bytes'] and sha(content) == digest, 'artifact bytes differ ' + name)
        (destination / (name + '.zip')).write_bytes(content)
        write_json(destination / (name + '-members.json'), unzip(content, destination / name))
    write_json(destination / 'input-tar-members.json', unpack_input(destination / 'input/prepared.tar.gz', destination / 'prepared-input'))


def unique(items, key, value):
    found = [item for item in items if item.get(key) == value]
    require(len(found) == 1, 'missing or duplicate typed identity ' + str(value))
    return found[0]


def validate_inventory(data):
    require(data['schema'] == 2 and data['authorization'] == 'inventory_only' and data['unit'] == UNIT,
            'wrong typed source unit')
    owner = unique(data['declarations'], 'id', 104190)
    require(owner['definition'] is True and owner['symbol'] == {'static': 'spirv_compiler_emit_movc', 'unit': UNIT}
            and owner['location'].endswith(':7614:1'), 'wrong typed owner')
    parent = unique(data['calls'], 'id', 104281)
    require(parent['owner'] == 104190 and parent['callee'] == {'static': 'vkd3d_spirv_build_op_tr2', 'unit': UNIT}
            and parent['location'].endswith(':7633:28') and len(parent['arguments']) == 6, 'wrong typed parent')
    for slot, node, helper, location in ((3, 104287, 'spirv_get_type_id', ':7634:21'),
                                         (5, 104289, 'spirv_compiler_get_constant_float_vector', ':7635:21')):
        argument = parent['arguments'][slot]
        require(argument['id'] == node and argument['type'] == {
            'canonical': {'kind': 'UInt'}, 'const': False, 'restrict': False, 'volatile': False}, 'wrong UInt child')
        child = unique(data['calls'], 'id', node)
        require(child['owner'] == 104190 and child['callee'] == {'static': helper, 'unit': UNIT}
                and child['location'].endswith(location), 'wrong typed child callee')
    require(len([c for c in data['calls'] if c['owner'] == 104190
                 and c['callee'].get('static') == 'vkd3d_spirv_build_op_tr2']) == 1, 'ambiguous owner call')


def transform(source, inventory, mode):
    require(mode in ('R0', 'Rzero', 'Rtype'), 'unknown finite variant')
    validate_inventory(inventory)
    require(sha(source) == RUST_SHA, 'generated whole-file hash differs')
    text = source.decode()
    start = text.index('unsafe extern "C" fn spirv_compiler_emit_movc(')
    end = text.index('\nunsafe extern', start + 1)
    body = text[start:end]
    require(sha((body.rstrip() + '\n').encode()) == BODY_SHA and body.count(CALL) == 1
            and text.count(CALL) == 1 and body.count('VSIR_OP_CMP.0') == 1, 'movc body/call boundary differs')
    if mode == 'R0':
        return source
    definitions = {
        'zero': '            let cmp_zero_id: uint32_t = ' + ZERO + ';\n',
        'type': '            let cmp_type_id: uint32_t = ' + TYPE + ';\n',
    }
    order = ('zero', 'type') if mode == 'Rzero' else ('type', 'zero')
    replacement = ''.join(definitions[key] for key in order) + CALL.replace(TYPE, 'cmp_type_id').replace(ZERO, 'cmp_zero_id')
    return (text[:start] + body.replace(CALL, replacement) + text[end:]).encode()


def write_variants(original, destination, c_source):
    require(sha(c_source.read_bytes()) == C_SHA, 'C source hash differs')
    inventory_path = original / 'src/vkd3d_shader/spirv.variadic.json'
    require(sha(inventory_path.read_bytes()) == INVENTORY_SHA, 'typed inventory hash differs')
    inventory = json.loads(inventory_path.read_text())
    require(sha((original / 'Cargo.lock').read_bytes()) == LOCK_SHA, 'Cargo.lock differs')
    initial = manifest(original)
    records = {}
    for mode in ('R0', 'Rzero', 'Rtype'):
        target = destination / mode / 'rust'
        shutil.copytree(original, target)
        (target / RUST_PATH).write_bytes(transform((original / RUST_PATH).read_bytes(), inventory, mode))
        actual = manifest(target)
        differences = {k for k in initial.keys() | actual.keys() if initial.get(k) != actual.get(k)}
        require(differences == (set() if mode == 'R0' else {str(RUST_PATH)}), 'variant escaped source boundary')
        records[mode] = {'source_manifest': actual, 'changed_paths': sorted(differences)}
    return records


OBSERVER = r'''
static uint32_t cmp_cached_zero(struct vkd3d_spirv_builder *b, unsigned int n)
{
    struct vkd3d_spirv_declaration key;
    struct rb_entry *entry;
    uint32_t scalar;
    unsigned int i;
    key.op = SpvOpConstant;
    key.parameter_count = 2;
    key.parameters[0] = b->numeric_type_ids[VSIR_DATA_F32][0];
    key.parameters[1] = 0;
    if (!key.parameters[0] || !(entry = rb_get(&b->declarations, &key))) return 0;
    scalar = RB_ENTRY_VALUE(entry, struct vkd3d_spirv_declaration, entry)->id;
    if (n == 1) return scalar;
    key.op = SpvOpConstantComposite;
    key.parameter_count = n + 1;
    key.parameters[0] = b->numeric_type_ids[VSIR_DATA_F32][n - 1];
    for (i = 1; i <= n; ++i) key.parameters[i] = scalar;
    if (!key.parameters[0] || !(entry = rb_get(&b->declarations, &key))) return 0;
    return RB_ENTRY_VALUE(entry, struct vkd3d_spirv_declaration, entry)->id;
}
static void cmp_trace(struct spirv_compiler *compiler, const char *helper, const char *event,
        unsigned int n, uint32_t result)
{
    const char *path = getenv("MDS_CMP_TRACE");
    struct vkd3d_spirv_builder *b = &compiler->spirv_builder;
    FILE *f;
    if (!path || !(f = fopen(path, "a"))) abort();
    fprintf(f, "%s %s %u %u %u %u %u %u %zu %u\n", helper, event, n,
            b->current_id, result, b->numeric_type_ids[VSIR_DATA_BOOL][n - 1],
            b->numeric_type_ids[VSIR_DATA_F32][n - 1], b->type_bool_id, b->global_stream.word_count, cmp_cached_zero(b, n));
    if (fclose(f)) abort();
}
static uint32_t cmp_type(struct spirv_compiler *compiler, enum vsir_data_type type, unsigned int n)
{
    uint32_t result;
    cmp_trace(compiler, "type", "entry", n, 0);
    result = spirv_get_type_id(compiler, type, n);
    cmp_trace(compiler, "type", "return", n, result);
    return result;
}
static uint32_t cmp_zero(struct spirv_compiler *compiler, float value, unsigned int n)
{
    uint32_t result;
    cmp_trace(compiler, "zero", "entry", n, 0);
    result = spirv_compiler_get_constant_float_vector(compiler, value, n);
    cmp_trace(compiler, "zero", "return", n, result);
    return result;
}
'''


def instrument(source):
    require(sha(source) == C_SHA, 'observer source hash differs')
    text = source.decode()
    require(text.count(C_CALL) == 1, 'observer CMP call differs')
    marker = 'static void spirv_compiler_emit_movc('
    require(text.count(marker) == 1, 'observer owner differs')
    return text.replace(marker, OBSERVER + '\n' + marker).replace(
        C_CALL, C_CALL.replace('spirv_get_type_id(', 'cmp_type(').replace(
            'spirv_compiler_get_constant_float_vector(', 'cmp_zero(')).encode()


def verify_trace(paths):
    records = {}
    for path in paths:
        lines = [line.split() for line in path.read_text().splitlines()]
        require(lines and len(lines) % 4 == 0, 'missing/incomplete observer trace')
        groups = []
        for start in range(0, len(lines), 4):
            group = lines[start:start + 4]
            require([row[:2] for row in group] == [['zero', 'entry'], ['zero', 'return'],
                    ['type', 'entry'], ['type', 'return']], 'observer did not observe zero before type')
            require(all(len(row) == 10 and all(v.isdigit() for v in row[2:]) for row in group), 'invalid trace fields')
            require(group[1][4] != '0' and group[3][4] != '0' and group[1][4] != group[3][4], 'invalid returned IDs')
            require(group[1][3] == group[2][3], 'observer state discontinuity')
            require(group[1][9] == group[1][4] and group[3][5] == group[3][4], 'observer returned ID absent from cache')
            groups.append(group)
        records[path.name] = groups
    require(all(any(name.startswith(case + '.native') for name in records) for case in DIRECTED), 'missing directed observer traces')
    return records


def native_files(matrix):
    return {p.name: sha(p.read_bytes()) for p in matrix.iterdir()
            if p.name.endswith(('.native', '.native.status', '.native.diagnostics'))}


def require_baseline(matrix, historical):
    actual, expected = native_files(matrix), native_files(historical)
    require(len(actual) == 150 and actual == expected, 'native 150-file baseline differs')
    return actual


def check_outcome(result, matrix, mode, historical):
    cases = result['cases']
    require(len(cases) == 48 and len({c['name'] for c in cases}) == 48, 'matrix positive coverage differs')
    mismatches = {c['name'] for c in cases if c['status'] != 'success'}
    require(mismatches == (set() if mode == 'Rzero' else DIRECTED), 'unexpected finite variant outcome ' + mode)
    for case in cases:
        require(case['return_codes'] == ['0', '0'] and case['diagnostics_equal']
                and all(case[k]['exit_code'] == 0 for k in ('native', 'rust')), 'positive API/process/diagnostics failure')
        name = case['name']
        if name in mismatches:
            require(case['status'] == 'mismatch' and case['output_sha256'][0] != case['output_sha256'][1], 'wrong-order control is not a byte mismatch')
        if mode in ('R0', 'Rtype'):
            for suffix in ('.rust', '.rust.status', '.rust.diagnostics'):
                require((matrix / (name + suffix)).read_bytes() == (historical / (name + suffix)).read_bytes(), mode + ' did not reproduce original bytes')
    controls = result['negative_controls']
    require({c['name'] for c in controls} == {'missing_float_controls', 'invalid_pixel_semantic'}, 'negative coverage differs')
    for case in controls:
        require(case['status'] == 'expected_rejection' and case['return_codes'] == ['-4', '-4']
                and case['diagnostics_equal'] and all(case[k]['exit_code'] == 0 for k in ('native', 'rust')), 'negative process/API failure')
        expected = b'E2004' if case['name'] == 'missing_float_controls' else b'E5013'
        for side in ('native', 'rust'):
            path = matrix / (case['name'] + '.' + side)
            require(not path.read_bytes() and expected in path.with_suffix(path.suffix + '.diagnostics').read_bytes(), 'negative bytes/diagnostics failure')
    return {'experimental_outcome': 'expected_control_mismatch' if mismatches else 'exact_positive_match',
            'mismatches': sorted(mismatches), 'production_acceptance': False}


def retain_dependencies(source, destination):
    records = {}
    files = sorted(source.rglob('*.Plo')) + sorted(source.rglob('*.Po'))
    require(files, 'missing actual native dependency files')
    destination.mkdir()
    for dependency in files:
        text = dependency.read_text().replace('\\\n', ' ')
        for line in text.splitlines():
            _, separator, values = line.partition(':')
            if not separator:
                continue
            for name in shlex.split(values):
                path = (source / name).resolve()
                require(path.is_file(), 'missing native dependency ' + str(path))
                content = path.read_bytes()
                digest = sha(content)
                records[str(path)] = {'sha256': digest, 'size': len(content),
                                      'dependency_file': str(dependency.relative_to(source))}
                (destination / digest).write_bytes(content)
    require(records, 'empty actual native dependency manifest')
    return records


def execute(root, historical):
    require(subprocess.check_output(['git', '-C', str(historical), 'rev-parse', 'HEAD'], text=True).strip() == HEAD, 'historical checkout differs')
    sys.path.insert(0, str(historical / 'tools/vkd3d-rust-probe'))
    from probe import run
    from full_compiler import stable_env
    from shader_matrix import compare
    commands = []
    def recorded(command, log, **kwargs):
        log.parent.mkdir(parents=True, exist_ok=True)
        cwd = kwargs.get('cwd')
        receipt = run(command, log, **kwargs)
        receipt['cwd'] = str(cwd) if cwd else os.getcwd()
        receipt['timeout_seconds'] = kwargs.get('timeout')
        commands.append(receipt)
        write_json(root / 'commands.json', commands)
        return receipt
    def checked(command, log, **kwargs):
        receipt = recorded(command, log, **kwargs)
        require(receipt['exit_code'] == 0 and not receipt['timed_out'], 'process failed ' + str(log))
        return receipt
    write_json(root / 'job.json', {key: os.environ.get(key) for key in (
        'GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT',
        'GITHUB_WORKFLOW_REF', 'RUNNER_OS', 'RUNNER_ARCH', 'ImageVersion')})
    fetch_inputs(root, recorded)
    actual = root / 'all-units/result'
    require(sha((actual / 'VKD3D-LICENSE').read_bytes()) == LICENSE_SHA, 'retained license differs')
    prepared_source = root / 'prepared-input/prepared/work-linux-native/vkd3d-2.1'
    require(sha((prepared_source / 'libs/vkd3d-shader/spirv.c').read_bytes()) == C_SHA, 'prepared C source differs')
    for path in (actual / 'source').rglob('*'):
        if path.is_file() and (path.suffix == '.h' or path.name in ('LICENSE', 'COPYING')):
            relative = path.relative_to(actual / 'source')
            require((prepared_source / relative).read_bytes() == path.read_bytes(), 'prepared header/license differs ' + str(relative))
    write_json(root / 'variants.json', write_variants(actual / 'rust-working', root / 'variants', actual / 'source/libs/vkd3d-shader/spirv.c'))
    compiler = Path(shutil.which('gcc')).resolve()
    write_json(root / 'compiler.json', {'path': str(compiler), 'sha256': sha(compiler.read_bytes()),
               'identity_scope': 'fresh observed compiler; original executable identity not claimed'})
    for name, command in [('gcc-version', [str(compiler), '--version']), ('gcc-target', [str(compiler), '-dumpmachine']),
                          ('gcc-search', [str(compiler), '-print-search-dirs']), ('packages', ['dpkg-query', '-W']),
                          ('rust-version', ['rustc', '+1.95.0', '-vV']), ('uname', ['uname', '-a'])]:
        checked(command, root / (name + '.log'), timeout=60)
    recipe = historical / 'tools/vkd3d/build.sh'
    write_json(root / 'historical-helper-hashes.json', manifest(historical / 'tools/vkd3d-rust-probe'))
    write_json(root / 'recipe.json', {'sha256': sha(recipe.read_bytes()), 'head': HEAD})
    libraries = {}
    for name in ('fresh', 'observer'):
        out = root / ('native-' + name)
        env = dict(os.environ, MDS_VKD3D_OUT=str(out), CC=str(compiler), MAKEFLAGS='V=1')
        checked(['bash', str(recipe), 'linux-native'], root / (name + '-build.log'), env=env, timeout=900)
        source = out / 'work-linux-native/vkd3d-2.1'
        spirv = source / 'libs/vkd3d-shader/spirv.c'
        require(sha(spirv.read_bytes()) == C_SHA, 'fresh native source differs')
        write_json(root / (name + '-unmodified-files.json'), manifest(out))
        if name == 'observer':
            spirv.write_bytes(instrument(spirv.read_bytes()))
            checked(['make', 'V=1', 'libvkd3d-shader.la'], root / 'observer-rebuild.log', cwd=source, env=env, timeout=600)
            checked(['make', 'V=1', 'install-libLTLIBRARIES', 'lib_LTLIBRARIES=libvkd3d-shader.la'],
                    root / 'observer-install.log', cwd=source, env=env, timeout=120)
        write_json(root / (name + '-dependencies.json'), retain_dependencies(source, root / (name + '-dependency-bytes')))
        libraries[name] = out / 'linux-native/lib/libvkd3d-shader.so.1'
        checked(['ldd', str(libraries[name])], root / (name + '-dependencies.log'), timeout=60)
        write_json(root / (name + '-compiled-files.json'), manifest(out))
    outcomes = {}
    for mode in ('R0', 'Rzero', 'Rtype'):
        directory = root / 'variants' / mode
        project = directory / 'rust'
        target = directory / 'target'
        env = stable_env(target)
        build = ['cargo', '+1.95.0', 'build', '--locked', '--manifest-path', str(project / 'Cargo.toml')]
        stable = recorded(build, directory / 'stable.log', env=env, cwd=project, timeout=600)
        require(stable['exit_code'] != 0 and not stable['timed_out'] and 'E0554' in (directory / 'stable.log').read_text(), 'expected stable E0554 failure missing')
        env['RUSTC_BOOTSTRAP'] = '1'
        checked(build, directory / 'experimental-bootstrap.log', env=env, cwd=project, timeout=600)
        archive = target / 'debug/librust.a'
        require(archive.is_file(), 'missing experimental static library')
        checked(['nm', '--defined-only', str(archive)], directory / 'symbols.log', timeout=60)
        binary = directory / 'shader-driver'
        checked(['rustc', '+1.95.0', '--edition', '2024', str(historical / 'tools/vkd3d-rust-probe/shader_driver.rs'),
                 '-o', str(binary), '-L', 'native=' + str(archive.parent), '-l', 'static=rust', '-l', 'm', '-l', 'pthread', '-l', 'dl'],
                directory / 'link.log', env=stable_env(directory / 'driver-target'), timeout=300)
        checked(['ldd', str(binary)], directory / 'dependencies.log', timeout=60)
        write_json(directory / 'compiled-bindings.json', {'archive_sha256': sha(archive.read_bytes()), 'driver_sha256': sha(binary.read_bytes()),
                   'library_sha256': sha(libraries['fresh'].read_bytes()), 'sources': manifest(project)})
        result = compare(binary, libraries['fresh'], directory, recorded)
        require_baseline(directory / 'matrix', actual / 'matrix')
        outcomes[mode] = check_outcome(result, directory / 'matrix', mode, actual / 'matrix')
        if mode == 'R0':
            observer = root / 'observer-runtime'
            observer.mkdir()
            def observer_run(command, log, **kwargs):
                if command[5] == str(libraries['observer']):
                    kwargs['env'] = dict(os.environ, MDS_CMP_TRACE=str(log.with_suffix('.trace')))
                return recorded(command, log, **kwargs)
            observed = compare(binary, libraries['observer'], observer, observer_run)
            check_outcome(observed, observer / 'matrix', 'R0', actual / 'matrix')
            require_baseline(observer / 'matrix', directory / 'matrix')
            write_json(root / 'observer-traces.json', verify_trace(sorted((observer / 'matrix').glob('*.trace'))))
            write_json(root / 'native-baselines.json', {'fresh': native_files(directory / 'matrix'),
                       'instrumented': native_files(observer / 'matrix'), 'historical': native_files(actual / 'matrix')})
    write_json(root / 'result.json', {'status': 'finite_experiment_completed', 'production_acceptance': False,
               'stable_gate': 'FAIL_E0554', 'variants': outcomes})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--historical', type=Path, required=True)
    args = parser.parse_args()
    root = args.artifacts.resolve()
    root.mkdir(parents=True, exist_ok=False)
    try:
        execute(root, args.historical.resolve())
    except Exception as error:
        write_json(root / 'failure.json', {'status': 'experiment_failed', 'error': str(error), 'production_acceptance': False})
        raise
    finally:
        write_json(root / 'seal.json', manifest(root))


if __name__ == '__main__':
    main()
