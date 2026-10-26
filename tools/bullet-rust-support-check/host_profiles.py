"""Exact frozen native host profiles. Unknown hosts require reviewed captures."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
HOSTS = {('Darwin', 'arm64'): 'macos-arm64', ('Linux', 'x86_64'): 'linux-x64',
         ('Linux', 'aarch64'): 'linux-arm64', ('Windows', 'AMD64'): 'windows-x64'}


def host():
    key = (platform.system(), platform.machine())
    if key not in HOSTS:
        raise ValueError(f'Unsupported host {key}')
    return HOSTS[key]


def fields(kind, words):
    if kind == 'support':
        names = [f'{entry}.{axis}' for entry in ['without-margin', 'with-margin', 'virtual'] for axis in 'xyz']
    elif kind == 'gjk-epa':
        names = []
        position = 1
        for entry in ['distance', 'penetration', 'penetration-margin']:
            if len(words) < position + 2:
                raise ValueError('Incomplete query schema')
            yes, status = words[position:position + 2]
            if yes not in ['0', '1'] or status not in ['0', '1', '2', '3']:
                raise ValueError('Invalid query schema')
            names += [entry + '.success', entry + '.status']
            position += 2
            if yes == '1':
                names += [f'{entry}.{part}.{axis}' for part in ['witness0', 'witness1', 'normal'] for axis in 'xyz']
                names += [entry + '.distance']
                position += 10
        if len(words) <= position or words[position] not in ['0', '1']:
            raise ValueError('Invalid adapter schema')
        names += ['adapter.success'] + [f'adapter.{part}.{axis}' for part in ['witness0', 'witness1', 'normal'] for axis in 'xyz']
    else:
        raise ValueError(f'Unknown profile kind {kind}')
    if len(words) != len(names) + 1:
        raise ValueError('Invalid row width')
    for name, value in zip(names, words[1:]):
        if not name.endswith(('.success', '.status')) and not re.fullmatch('[0-9a-f]{8}', value):
            raise ValueError(f'Invalid float word {value}')
    return names


def rows(data, kind, count, start=0):
    result = []
    for index, line in enumerate(data.decode('ascii').splitlines()):
        words = line.split('\t')
        if words[0] != str(start + index):
            raise ValueError(f'Invalid case ID at row {index}')
        result.append((words, fields(kind, words)))
    if len(result) != count:
        raise ValueError(f'Expected {count} rows, got {len(result)}')
    return result


def differences(left, right, kind, count, start=0):
    diff = []
    for (a, names), (b, other) in zip(rows(left, kind, count, start), rows(right, kind, count, start)):
        if names != other:
            raise ValueError(f'Query schema changed at case {a[0]}')
        diff += [[int(a[0]), name, x, y] for name, x, y in zip(names, a[1:], b[1:]) if x != y]
    return diff


def load(kind='support'):
    directory = HERE if kind == 'support' else ROOT / f'tools/bullet-rust-{kind}-check'
    manifest = json.loads((directory / f'{kind}-profiles.json').read_text())
    base = ROOT / manifest['directory']
    baseline = (base / 'native.tsv').read_bytes()
    for filename, expected in manifest['sha256'].items():
        if hashlib.sha256((base / filename).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Frozen profile hash changed: {filename}')
    for profile in manifest['profiles'].values():
        actual = (base / profile['compact']).read_bytes()
        diff = differences(baseline, actual, kind, manifest['compact_rows'])
        if diff != profile['differences']:
            raise ValueError('Host profile difference inventory changed')
        if any(item[2:] != ['7fc00000', 'ffc00000'] for item in diff):
            raise ValueError('Unreviewed host difference')
        if 'raw' in profile:
            diff = differences((base / 'raw-native.tsv').read_bytes(), (base / profile['raw']).read_bytes(), kind, 9, 6801)
            if diff != profile['raw_differences'] or any(item[2:] != ['7fc00000', 'ffc00000'] for item in diff):
                raise ValueError('Raw host profile difference inventory changed')
    return manifest, base


def capture_text(data, profile, count, expected_hash):
    """Validate reviewed raw transport before comparing its LF fixture."""
    ending = profile.get('line_ending', 'LF')
    if ending == 'CRLF':
        if data.count(b'\r\n') != count or data.count(b'\r') != count or data.count(b'\n') != count or not data.endswith(b'\r\n'):
            raise ValueError('Expected strict CRLF capture transport')
    elif ending == 'LF':
        if b'\r' in data or data.count(b'\n') != count or not data.endswith(b'\n'):
            raise ValueError('Expected strict LF capture transport')
    else:
        raise ValueError(f'Unknown capture line ending {ending}')
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError('Native capture hash differs from reviewed host profile')
    return data.replace(b'\r\n', b'\n') if ending == 'CRLF' else data


def validate_capture(output, kind='support'):
    manifest, base = load(kind)
    native = (output / 'native.tsv').read_bytes()
    observed = (output / 'observed.tsv').read_bytes()
    rows(native, kind, manifest['full_rows'])
    if hashlib.sha256((output / 'inputs.tsv').read_bytes()).hexdigest() != manifest['full_inputs_sha256']:
        raise ValueError('Full input capture differs from reviewed generator')
    if native != (output / 'rust.tsv').read_bytes():
        raise ValueError('Full same-host Rust output differs from native')
    if native != observed:
        raise ValueError('Observation hooks changed native stdout')
    profile = manifest['profiles'].get(host())
    report = {'host': host(), 'source_head': subprocess.check_output(['git', '-C', ROOT, 'rev-parse', 'HEAD'], text=True).strip(),
              'full_rows': manifest['full_rows'], 'native_observed_equal': True,
              'native_sha256': hashlib.sha256(native).hexdigest(), 'full_same_host_rust_equal': True, 'profile_known': profile is not None}
    (output / 'host-profile.json').write_text(json.dumps(report, indent=2) + '\n')
    if profile is None:
        raise ValueError(f'Unreviewed host profile {host()}; capture archived for review')
    if 'raw' in profile:
        raw = b''.join(native.splitlines(keepends=True)[-9:])
        raw_hash = profile.get('raw_sha256', manifest['sha256'][profile['raw']])
        if capture_text(raw, profile, 9, raw_hash) != (base / profile['raw']).read_bytes():
            raise ValueError('Native raw output differs from exact host profile')
    capture_text(native, profile, manifest['full_rows'], profile['full_sha256'])
    prefix = b''.join(native.splitlines(keepends=True)[:manifest['compact_rows']])
    expected = (base / profile['compact']).read_bytes()
    compact_hash = profile.get('compact_sha256', manifest['sha256'][profile['compact']])
    if capture_text(prefix, profile, manifest['compact_rows'], compact_hash) != expected:
        raise ValueError('Native compact output differs from exact host profile')
    return base / profile['compact']


def native_command(command, output, environment):
    """Use the reviewed joint host probe's MSVC CMake flags on Windows x64."""
    if os.name != 'nt':
        return list(map(str, command))
    src = ROOT / 'recipes/bullet275/bullet-src/src'
    shim = ROOT / 'rust/crates/mds-bullet-sys/shim'
    command = list(map(str, command))
    library = output / 'libmds_crtmath.a'
    result = subprocess.run(['rustup', 'run', '1.95.0', 'rustc', '--edition=2021', '--crate-type', 'staticlib', '-O',
                             str(ROOT / 'rust/crates/mds-crtmath/src/lib.rs'), '--print', 'native-static-libs', '-o', str(library)],
                            env=environment, capture_output=True, check=True)
    (output / 'native-static-libs.txt').write_bytes(result.stdout + result.stderr)
    libs = (result.stdout + result.stderr).decode().split('native-static-libs:')[-1].splitlines()[0].split()
    includes = [command[i + 1] for i, value in enumerate(command) if value == '-I' and command[i + 1] != str(shim / 'sse_emu')]
    executable = command[command.index('-o') + 1]
    return ['cl', '/nologo', '/std:c++17', '/O2', '/fp:precise', '/EHsc', '/W0', '/MD', '/DBT_NO_PROFILE=1', '/DWIN32',
            *[f'/I{p}' for p in includes], f'/FI{shim / "det_math.h"}', *[p for p in command if p.endswith('.cpp')],
            str(library), f'/Fe:{executable}', f'/Fo:{output}\\', '/link', '/OPT:REF', *libs]


def compiler_version():
    compiler = os.environ.get('CXX', 'clang++')
    result = subprocess.run([compiler] if os.name == 'nt' else [compiler, '--version'], capture_output=True, text=True)
    return result.stdout + result.stderr
