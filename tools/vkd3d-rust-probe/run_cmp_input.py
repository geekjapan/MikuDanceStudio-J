"""Hosted actual C-input validation through the unchanged all24 probe.

No compilation happens on import. --acquire uses a new narrowly reviewed current
input artifact, independently of the existing helper/full-admission pin purposes.
"""
import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path, PurePosixPath
import signal
import stat
import subprocess
import sys
import tarfile
import time
import zipfile

from cmp_input import (CONTRACT_SHA256, file_identity, normalize, read_json,
                       regular_tree, require, reviewed_contract, sha)

DIRECTED = {'branch-ps-2_0-1', 'branch-ps-3_0-1'}


def hosted():
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and sys.platform == 'linux',
            'acquisition/compilation is hosted Linux only')


def safe_name(name):
    path = PurePosixPath(name)
    return bool(name) and str(path) == name and not path.is_absolute() and '..' not in path.parts and '\\' not in name


def checked_prepared(raw, contract):
    pin = contract['prepared_artifact']
    require(len(raw) == pin['size'] and sha(raw) == pin['sha256'], 'prepared ZIP identity differs')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        require(archive.namelist() == ['prepared.tar.gz'], 'prepared ZIP inventory differs')
        item = archive.infolist()[0]
        require(stat.S_IFMT(item.external_attr >> 16) in (0, stat.S_IFREG), 'prepared ZIP member mode')
        bundle = archive.read(item)
    require(sha(bundle) == contract['prepared_tar_sha256'], 'prepared TAR identity differs')
    contents = {}
    with tarfile.open(fileobj=io.BytesIO(bundle), mode='r:gz') as archive:
        inventory = {}
        for item in archive.getmembers():
            require(safe_name(item.name) and item.name not in inventory, 'unsafe/duplicate prepared TAR path')
            require(item.isfile() or item.isdir() or item.issym(), 'special prepared TAR member')
            record = {'type': item.type.decode(), 'mode': item.mode, 'size': item.size, 'linkname': item.linkname}
            if item.isfile():
                data = archive.extractfile(item).read()
                record['sha256'] = sha(data)
                contents[item.name] = data
            if item.issym():
                require(safe_name(item.linkname) and '/' not in item.linkname,
                        'prepared TAR link must be a same-directory basename')
            inventory[item.name] = record
        require(inventory == contract['prepared_inventory'], 'complete prepared TAR inventory/modes differ')
        for name, record in inventory.items():
            if record['type'] == '2':
                require(str(PurePosixPath(name).parent / record['linkname']) in contents,
                        'prepared TAR link destination absent')
    return inventory, contents


def acquire(output):
    hosted()
    import urllib.request
    contract = reviewed_contract()
    pin = contract['prepared_artifact']
    require(not output.exists() and not output.is_symlink(), 'acquisition directory must be new')
    output.mkdir(parents=True)
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, message, headers, url):
            redirected = super().redirect_request(request, fp, code, message, headers, url)
            if redirected is not None:
                redirected.remove_header('Authorization')
            return redirected
    opener = urllib.request.build_opener(Redirect())
    base = 'https://api.github.com/repos/geekjapan/MikuDanceStudio-J/actions/artifacts/' + str(pin['id'])
    def fetch(url):
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
            'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
        with opener.open(request, timeout=120) as response:
            return response.read()
    metadata_raw = fetch(base)
    (output / 'current-input-api.json').write_bytes(metadata_raw)
    metadata = read_json(output / 'current-input-api.json')
    require(metadata['id'] == pin['id'] and metadata['name'] == pin['name']
            and metadata['size_in_bytes'] == pin['size'] and metadata['digest'] == 'sha256:' + pin['sha256']
            and metadata['workflow_run']['id'] == pin['run'] and metadata['workflow_run']['head_sha'] == pin['head']
            and metadata['expired'] is False, 'current prepared input API identity/expiry differs')
    raw = fetch(base + '/zip')
    (output / 'current-input.zip').write_bytes(raw)
    inventory, contents = checked_prepared(raw, contract)
    destination = output / 'unpacked'
    destination.mkdir()
    for name, record in inventory.items():
        path = destination / name
        if record['type'] == '5':
            path.mkdir(parents=True, exist_ok=True)
        elif record['type'] == '0':
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents[name])
            path.chmod(record['mode'])
    for name, record in inventory.items():
        if record['type'] == '2':
            (destination / name).symlink_to(record['linkname'])
    (output / 'complete-prepared-inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')


def invoke(command, cwd, log, timeout):
    started = datetime.now(timezone.utc).isoformat()
    begin = time.monotonic()
    with log.open('w') as stream:
        process = subprocess.Popen(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    return {'command': command, 'cwd': str(cwd), 'pid': process.pid, 'started_utc': started,
            'ended_utc': datetime.now(timezone.utc).isoformat(), 'wall_seconds': time.monotonic() - begin,
            'exit_code': process.returncode, 'timed_out': timed_out, 'timeout': timeout,
            'log': str(log), 'log_identity': file_identity(log)}


def validate_result(root, result, contract, opposite):
    require(result['translation_units'] == 24 and result['complete_translation']
            and result['transpile']['exit_code'] == 0 and not result['transpile']['timed_out']
            and len(result['syntax']) == 24
            and all(s['exit_code'] == 0 and not s['timed_out'] for s in result['syntax'])
            and not result['invalid_output_markers'], 'actual all24 translation incomplete')
    raw = regular_tree(root / 'rust-raw')
    require({k: v['sha256'] for k, v in raw.items()} == result['raw_sha256'] and result['raw_preserved'],
            'pristine emitted Rust identity differs')
    working = result['working_source_identity']
    actual = {k: v['sha256'] for k, v in regular_tree(root / 'rust-working').items()}
    emitted = {k: v['sha256'] for k, v in regular_tree(root / 'rust').items()}
    require(working['equal'] and working['original_sha256'] == emitted
            and working['working_sha256'] == actual and emitted == actual,
            'actual compilation copy differs from license-preserved emitted Rust')
    require(result['link']['status'] == 'success' and result['link']['exit_code'] == 0
            and not result['link']['timed_out'], 'generated library/driver link failed')
    corpus = {path.name: {'sha256': sha(path.read_bytes()), 'size': path.stat().st_size}
              for path in (root / 'matrix').glob('*.hlsl')}
    require(corpus == contract['corpus'], 'actual HLSL corpus identity differs')
    comparison = result['runtime_comparison']
    positives, negatives = comparison['cases'], comparison['negative_controls']
    require(len(positives) == 48 and len(negatives) == 2, 'finite matrix count differs')
    require({c['name'] for c in positives + negatives} == set(contract['oracle']), 'finite matrix names differ')
    mismatches = set()
    for case in positives + negatives:
        name = case['name']
        for mode in ('native', 'rust'):
            require(case[mode]['exit_code'] == 0 and not case[mode]['timed_out'], 'matrix process failed ' + name)
        for suffix, expected in contract['oracle'][name].items():
            data = (root / 'matrix' / (name + '.native' + suffix)).read_bytes()
            require(sha(data) == expected['sha256'] and len(data) == expected['size'], 'immutable native oracle differs ' + name)
        require([(root / 'matrix' / (name + '.' + mode + '.status')).read_text()
                 for mode in ('native', 'rust')] == case['return_codes'], 'raw API status differs ' + name)
        native = root / 'matrix' / (name + '.native')
        rust = root / 'matrix' / (name + '.rust')
        require(native.with_suffix(native.suffix + '.diagnostics').read_bytes()
                == rust.with_suffix(rust.suffix + '.diagnostics').read_bytes(), 'raw diagnostics mismatch ' + name)
        if case in positives:
            require(case['return_codes'] == ['0', '0'] and native.stat().st_size and rust.stat().st_size,
                    'positive API status/empty output ' + name)
            equal = native.read_bytes() == rust.read_bytes()
            require(case['status'] == ('success' if equal else 'mismatch'), 'raw comparator status differs')
            if not equal:
                mismatches.add(name)
        else:
            diagnostic = b'E2004' if name == 'missing_float_controls' else b'E5013'
            require(case['return_codes'] == ['-4', '-4'] and case['status'] == 'expected_rejection'
                    and not native.read_bytes() and not rust.read_bytes()
                    and diagnostic in native.with_suffix(native.suffix + '.diagnostics').read_bytes(),
                    'negative API rejection differs ' + name)
    require(mismatches == (DIRECTED if opposite else set()), 'correct/opposite C prediction failed')
    return {'positive_equal': 48 - len(mismatches), 'directed_mismatches': sorted(mismatches),
            'negative_rejections': 2, 'stable_build': result['stable_build'],
            'working_stable_build': result['working_stable_build'], 'diagnostic_only': True,
            'pristine_rust_manifest': raw, 'compilation_copy_manifest': actual,
            'driver_identity': file_identity(root / 'shader-driver'),
            'effective_compile_database': read_json(root / 'compile_commands.json')}


def run(args):
    hosted()
    contract = reviewed_contract()
    root = args.artifacts
    require(not root.exists() and not root.is_symlink(), 'hosted output must be new')
    require(args.target == contract['target'], 'unsupported reviewed target')
    from apply_c2rust_patch import verify_tool, verify_evidence, retain_tool_identity
    tool = args.c2rust.resolve().parent.parent
    require(regular_tree(tool) == contract['tool_manifest'], 'unknown current translator tool manifest')
    verify_tool(tool)
    patch = verify_evidence(tool / 'source-evidence')
    require(patch['patch_sha256'] == contract['compiler_patch_sha256']
            and len(patch['modified_source_sha256']) == contract['compiler_patch_destinations'], 'compiler patch scope differs')
    here = Path(__file__).resolve().parent
    require(all(sha((here / name).read_bytes()) == digest for name, digest in contract['bound_helpers'].items()),
            'frozen probe/comparator/compiler helper differs; new combined contract required')
    root.mkdir(parents=True)
    retain_tool_identity(tool, root)
    host = invoke(['rustc', '+1.95.0', '-vV'], here, root / 'rust-host.log', 30)
    require(host['exit_code'] == 0 and not host['timed_out']
            and '\nhost: ' + args.target + '\n' in (root / 'rust-host.log').read_text(),
            'actual Rust compiler host differs from reviewed target')
    require(not os.environ.get('CARGO_BUILD_TARGET'), 'ambient Cargo target override is not reviewed')
    report = {'status': 'incomplete', 'contract_sha256': CONTRACT_SHA256, 'variants': {},
              'stable_acceptance': 'UNRUN', 'four_target_execution': 'UNRUN',
              'product_integration': 'UNRUN', 'native_callback_Slots_cursor_23exports': 'UNRUN',
              'rust_host': host, 'clang_identity': file_identity(args.clang.resolve()),
              'rust_toolchain': '1.95.0', 'compiler_source_receipt': patch,
              'github': {key: os.environ.get(key) for key in
                         ('GITHUB_SHA', 'GITHUB_REF', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'ImageVersion')},
              'implementation': {name: file_identity(here / name) for name in
                  ('cmp_input.py', 'run_cmp_input.py', 'cmp_input_contract.json')}}
    def checkpoint():
        (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    checkpoint()
    try:
        for name, opposite in (('correct', False), ('opposite', True)):
            boundary = normalize(args.source, args.target, args.native_library, root / (name + '-input'), root,
                                 opposite_control=opposite)
            command = [sys.executable, '-B', str(here / 'probe.py'), '--source', boundary['translation_source'],
                       '--artifacts', str(root / name), '--c2rust', str(args.c2rust.resolve()),
                       '--clang', str(args.clang.resolve()), '--rust-toolchain', '1.95.0',
                       '--all-unit-prototype', '--timeout', '1800', '--build-timeout', '300',
                       '--native-library', boundary['native_library']]
            execution = invoke(command, here, root / (name + '-probe.log'), 3000)
            report['variants'][name] = {'probe': execution, 'boundary': boundary}
            checkpoint()
            result_path = root / name / 'result.json'
            if result_path.is_file():
                result = read_json(result_path)
                report['variants'][name]['actual_builds'] = {mode: result.get(mode) for mode in
                    ('stable_build', 'working_stable_build', 'bootstrap_build', 'prototype_build')}
                checkpoint()
            require(execution['exit_code'] == 0 and not execution['timed_out'], 'actual probe failed ' + name)
            result = read_json(result_path)
            translation_root = Path(boundary['translation_source'])
            domains = {'source': translation_root, 'hdr': translation_root.parent / 'hdr/include',
                       'spv': translation_root.parent / 'spv/include'}
            require({key: regular_tree(path) for key, path in domains.items()} == boundary['normalized_manifests']
                    and regular_tree(root / name / 'source') == boundary['normalized_manifests']['source'],
                    'effective probe translation source domain changed')
            original_root = Path(boundary['original_source'])
            domains = {'source': original_root, 'hdr': original_root.parent / 'hdr/include',
                       'spv': original_root.parent / 'spv/include'}
            require({key: regular_tree(path) for key, path in domains.items()} == boundary['original_manifests']
                    and file_identity(Path(boundary['native_library'])) == boundary['native_identity'],
                    'original source/native oracle changed during probe')
            report['variants'][name]['validation'] = validate_result(root / name, result, contract, opposite)
            checkpoint()
        stable = [v['validation'][mode]['exit_code'] == 0 for v in report['variants'].values()
                  for mode in ('stable_build', 'working_stable_build')]
        report['stable_acceptance'] = 'PASS' if all(stable) else 'FAIL; retained actual stable logs; bootstrap diagnostic only'
        report['status'] = 'finite_cmp_boundary_pass'
    except BaseException as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        actual_stable = [build for v in report['variants'].values()
                         for mode in ('stable_build', 'working_stable_build')
                         if (build := v.get('actual_builds', {}).get(mode))]
        if any(build['exit_code'] != 0 or build['timed_out'] for build in actual_stable):
            report['stable_acceptance'] = 'FAIL; retained actual stable logs; bootstrap diagnostic only'
        elif len(actual_stable) == 4:
            report['stable_acceptance'] = 'PASS'
        checkpoint()
        manifest = regular_tree(root)
        (root / 'output-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquire', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--native-library', type=Path)
    parser.add_argument('--c2rust', type=Path)
    parser.add_argument('--clang', type=Path, default=Path('/usr/bin/clang-18'))
    parser.add_argument('--target', default='x86_64-unknown-linux-gnu')
    parser.add_argument('--artifacts', type=Path)
    args = parser.parse_args()
    if args.acquire:
        require(not any((args.source, args.native_library, args.c2rust, args.artifacts)), 'exclusive acquisition operation')
        acquire(args.acquire)
    else:
        require(all((args.source, args.native_library, args.c2rust, args.artifacts)), 'missing hosted probe paths')
        run(args)


if __name__ == '__main__':
    main()
