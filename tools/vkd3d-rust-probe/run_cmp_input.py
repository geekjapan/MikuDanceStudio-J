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
import tomllib
import zipfile

from cmp_input import (CONTRACT_SHA256, admit_inputs, canonical_input, file_identity, normalize, read_json,
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


def owned_children():
    return [int(pid) for pid in Path('/proc/self/task/' + str(os.getpid()) + '/children').read_text().split()]


def preflight_pidfd():
    hosted()
    require(hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'),
            'owned process custody requires Linux pidfd support')
    descriptor = os.pidfd_open(os.getpid())
    try:
        signal.pidfd_send_signal(descriptor, 0)
    finally:
        os.close(descriptor)


class WrapperRun:
    signals = (signal.SIGINT, signal.SIGTERM)

    def __init__(self):
        self.cancelled = False
        self.root = None
        self.phase = 'new'
        self.previous = {}
        self.original_mask = None
        self.writer = None
        self.publication_ready = False

    def interrupt(self, signum, frame):
        first = not self.cancelled
        self.cancelled = True
        if first and self.phase == 'working':
            raise KeyboardInterrupt('Interrupted by signal ' + str(signum))

    def checkpoint(self):
        if self.cancelled:
            raise KeyboardInterrupt('Cancelled wrapper')
        require(self.phase == 'working', 'wrapper is not accepting work')

    def __enter__(self):
        require(self.phase == 'new', 'wrapper owner cannot be reused')
        self.phase = 'admitting'
        try:
            self._signal_runtime()
            require(not set(self.signals) & signal.sigpending(), 'caller cancellation signals already pending')
            self.original_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
            require(not set(self.signals) & self.original_mask, 'caller cancellation signals must be unblocked')
            self.phase = 'installing'
            for signum in self.signals:
                self.previous[signum] = signal.getsignal(signum)
            signal.pthread_sigmask(signal.SIG_BLOCK, self.signals)
            self._drain_python()
            for signum in self.signals:
                signal.signal(signum, self.interrupt)
            self._drain_python()
            signal.pthread_sigmask(signal.SIG_SETMASK, self.original_mask)
            self.phase = 'working'
            self.checkpoint()
        except BaseException as error:
            if self.phase != 'admitting' and self.original_mask is not None:
                self._finish(error)
            else:
                self.phase = 'failed'
                self._revoke('cancelled' if isinstance(error, KeyboardInterrupt) else 'failed')
            raise
        return self

    def __exit__(self, kind, error, traceback):
        self._finish(error)

    def execute(self, args):
        with self:
            self._execute(args)

    def normalize(self, *args, **kwargs):
        self.checkpoint()
        result = normalize(*args, **kwargs)
        self.checkpoint()
        return result

    def _revoke(self, status):
        if self.root is None:
            return
        for name in ('output-manifest.json', 'output-manifest.pending'):
            (self.root / name).unlink(missing_ok=True)
        if self.cancelled:
            (self.root / 'CANCELLED').write_text('Cancelled wrapper; no final output publication.\n')
        for name in ('correct-input', 'opposite-input'):
            directory = self.root / name
            if directory.is_dir():
                ready = directory / 'receipt.json'
                if ready.exists():
                    os.replace(ready, directory / 'receipt.cancelled.json')
                (directory / 'INCOMPLETE').write_text('Unfinished wrapper; input is partial diagnostic data.\n')
        report_path = self.root / 'report.json'
        if report_path.is_file():
            report = read_json(report_path)
            report['status'] = status
            report_path.write_text(json.dumps(report, indent=2) + '\n')

    def _signal_runtime(self):
        hosted()
        require(sys.implementation.name == 'cpython' and sys.version_info[:3] == (3, 12, 3),
                'signal handoff requires reviewed CPython 3.12.3')
        require(len(list(Path('/proc/self/task').iterdir())) == 1,
                'signal handoff requires a single owned thread')

    def _drain_python(self):
        import ctypes
        check = ctypes.pythonapi.PyErr_CheckSignals
        check.argtypes = []
        check.restype = ctypes.c_int
        require(check() == 0, 'queued Python signal dispatch failed')

    def _finish(self, error):
        self.cancelled = self.cancelled or isinstance(error, KeyboardInterrupt)
        self.phase = 'finishing'
        failures = []
        blocked = False
        try:
            self._signal_runtime()
            signal.pthread_sigmask(signal.SIG_BLOCK, self.signals)
            blocked = True
            self._drain_python()
            require(self.writer is None, 'owned writer closure unproven at handoff')
            if error is None and not self.cancelled:
                require(self.root is None or self.publication_ready, 'finite publication incomplete at handoff')
        except BaseException as failure:
            failures.append(failure)
        if self.cancelled or error is not None or failures:
            try:
                self._revoke('cancelled' if self.cancelled else 'failed')
            except BaseException as failure:
                failures.append(failure)
        for signum, handler in self.previous.items():
            try:
                signal.signal(signum, handler)
            except BaseException as failure:
                failures.append(failure)
        if blocked:
            try:
                pending = set(self.signals) & signal.sigpending()
                if pending:
                    self.cancelled = True
                    for signum in pending:
                        require(signal.sigtimedwait({signum}, 0) is not None,
                                'owned pending signal could not be consumed')
            except BaseException as failure:
                failures.append(failure)
        if self.cancelled or error is not None or failures:
            self.phase = 'failed'
            try:
                self._revoke('cancelled' if self.cancelled else 'failed')
            except BaseException as failure:
                failures.append(failure)
        else:
            self.phase = 'completed' if self.root is not None else 'closed'
        try:
            signal.pthread_sigmask(signal.SIG_SETMASK, self.original_mask)
        except BaseException as failure:
            try:
                restored = signal.pthread_sigmask(signal.SIG_BLOCK, set()) == self.original_mask
            except BaseException:
                restored = False
            if self.phase in ('completed', 'closed') and restored:
                raise
            self.phase = 'failed'
            failures.append(failure)
            try:
                self._revoke('cancelled' if self.cancelled else 'failed')
            except BaseException as revoke_failure:
                failures.append(revoke_failure)
        if failures:
            raise BaseExceptionGroup('Wrapper handoff failed', failures)
        if self.cancelled and error is None:
            raise KeyboardInterrupt('Cancelled wrapper before completed handoff')

    def invoke(self, command, cwd, log, timeout):
        self.checkpoint()
        enable_custody()
        self.checkpoint()
        marker = log.parent / 'OWNED_WRITERS_UNPROVEN'
        require(not marker.exists(), 'unclosed earlier writers; refusing another launch')
        marker.write_text('No final manifest or artifact publication until owned children are reaped.\n')
        started = datetime.now(timezone.utc).isoformat()
        begin = time.monotonic()
        process = None
        primary_session = None
        descendants = []
        with log.open('w') as stream:
            timed_out = False
            try:
                self.checkpoint()
                process = subprocess.Popen(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                self.writer = process
                primary_session = os.getsid(process.pid)
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                self.phase = 'closing'
                interrupted = sys.exc_info()[0] is not None
                descendants = close_owned_children(process)
                require(not owned_children(), 'owned writers remain; no final manifest')
                if interrupted or self.cancelled or timed_out or descendants:
                    (log.parent / 'CUSTODY_FAILED').write_text('Closed partial diagnostics only; no final output manifest.\n')
                stream.close()
                contaminated = not timed_out and bool(descendants)
                receipt = {'command': command, 'cwd': str(cwd), 'pid': process.pid if process else None,
                    'started_utc': started, 'ended_utc': datetime.now(timezone.utc).isoformat(),
                    'wall_seconds': time.monotonic() - begin, 'exit_code': process.returncode if process else None,
                    'timed_out': timed_out, 'timeout': timeout, 'cancelled': self.cancelled,
                    'log': str(log), 'log_identity': file_identity(log), 'owned_descendants_reaped': descendants,
                    'owned_writers_closed': True, 'session': primary_session,
                    'custody_status': 'contaminated' if contaminated else 'clean'}
                log.with_suffix(log.suffix + '.custody.json').write_text(json.dumps(receipt, indent=2) + '\n')
                marker.unlink()
                self.writer = None
                self.phase = 'working'
                if self.cancelled:
                    raise KeyboardInterrupt('Cancelled invocation after owned writers closed')
        self.checkpoint()
        return receipt

    def _execute(self, args):
        hosted()
        contract = reviewed_contract()
        root = Path(args.artifacts).absolute()
        require(not root.exists() and not root.is_symlink(), 'hosted output must be new')
        from apply_c2rust_patch import verify_tool, verify_evidence, retain_tool_identity
        c2rust = canonical_input(args.c2rust, 'c2rust')
        tool = c2rust.parent.parent
        admitted = admit_inputs(args.source, args.target, args.native_library, (root,), contract, tool=tool)
        require(c2rust == tool / 'bin/c2rust', 'unreviewed translator entry point')
        verify_tool(tool)
        patch = verify_evidence(tool / 'source-evidence')
        require(patch['patch_sha256'] == contract['compiler_patch_sha256']
                and len(patch['modified_source_sha256']) == contract['compiler_patch_destinations'], 'compiler patch scope differs')
        here = Path(__file__).resolve().parent
        require(all(sha((here / name).read_bytes()) == digest for name, digest in contract['bound_helpers'].items()),
                'frozen probe/comparator/compiler helper differs; new combined contract required')
        require(not os.environ.get('CARGO_BUILD_TARGET'), 'ambient Cargo target override is not reviewed')
        enable_custody()
        self.checkpoint()
        root.mkdir(parents=True)
        self.root = root
        self.checkpoint()
        retain_tool_identity(tool, root)
        host = self.invoke(['rustc', '+1.95.0', '-vV'], here, root / 'rust-host.log', 30)
        require(host['exit_code'] == 0 and not host['timed_out'] and host['custody_status'] == 'clean'
                and '\nhost: ' + args.target + '\n' in (root / 'rust-host.log').read_text(),
                'actual Rust compiler host differs from reviewed target')
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
            self.checkpoint()
            (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        checkpoint()
        try:
            for name, opposite in (('correct', False), ('opposite', True)):
                boundary = self.normalize(admitted.roots['source'], args.target, admitted.native_library, root / (name + '-input'), root,
                                     opposite_control=opposite)
                command = [sys.executable, '-B', str(here / 'probe.py'), '--source', boundary['translation_source'],
                           '--artifacts', str(root / name), '--c2rust', str(args.c2rust.resolve()),
                           '--clang', str(args.clang.resolve()), '--rust-toolchain', '1.95.0',
                           '--all-unit-prototype', '--timeout', '1800', '--build-timeout', '300',
                           '--native-library', boundary['native_library']]
                execution = self.invoke(command, here, root / (name + '-probe.log'), 3000)
                report['variants'][name] = {'probe': execution, 'boundary': boundary}
                checkpoint()
                result_path = root / name / 'result.json'
                if result_path.is_file():
                    result = read_json(result_path)
                    report['variants'][name]['actual_builds'] = {mode: result.get(mode) for mode in
                        ('stable_build', 'working_stable_build', 'bootstrap_build', 'prototype_build')}
                    checkpoint()
                require(execution['exit_code'] == 0 and not execution['timed_out']
                        and execution['custody_status'] == 'clean', 'actual probe failed or custody contaminated ' + name)
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
                        and file_identity(Path(boundary['native_library'])) == boundary['native_identity']
                        and {key: sorted(p.relative_to(path).as_posix() for p in path.rglob('*'))
                             for key, path in domains.items()} == admitted.members
                        and regular_tree(tool) == contract['tool_manifest'],
                        'original source/native oracle changed during probe')
                self.checkpoint()
                report['variants'][name]['validation'] = validate_result(root / name, result, contract, opposite)
                checkpoint()
            stable = [v['validation'][mode]['exit_code'] == 0 for v in report['variants'].values()
                      for mode in ('stable_build', 'working_stable_build')]
            report['stable_acceptance'] = 'PASS' if all(stable) else 'FAIL; retained actual stable logs; bootstrap diagnostic only'
            report['status'] = 'finite_cmp_boundary_pass'
        except BaseException as error:
            report.update(status='cancelled' if isinstance(error, KeyboardInterrupt) or self.cancelled else 'failed',
                          error=str(error))
            raise
        finally:
            self.phase = 'finishing'
            actual_stable = [build for v in report['variants'].values()
                             for mode in ('stable_build', 'working_stable_build')
                             if (build := v.get('actual_builds', {}).get(mode))]
            if any(build['exit_code'] != 0 or build['timed_out'] for build in actual_stable):
                report['stable_acceptance'] = 'FAIL; retained actual stable logs; bootstrap diagnostic only'
            elif len(actual_stable) == 4:
                report['stable_acceptance'] = 'PASS'
            (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            if not self.cancelled and report['status'] == 'finite_cmp_boundary_pass' and not any(
                    (root / marker).exists() for marker in ('OWNED_WRITERS_UNPROVEN', 'CUSTODY_FAILED', 'CANCELLED')):
                manifest = regular_tree(root)
                pending = root / 'output-manifest.pending'
                pending.write_text(json.dumps(manifest, indent=2) + '\n')
                if not self.cancelled:
                    os.replace(pending, root / 'output-manifest.json')
                    self.publication_ready = True


def enable_custody():
    hosted()
    import ctypes
    preflight_pidfd()
    require(not owned_children(), 'owned process custody requires no pre-existing children')
    libc = ctypes.CDLL(None, use_errno=True)
    enabled = ctypes.c_int()
    require(libc.prctl(36, 1, 0, 0, 0) == 0
            and libc.prctl(37, ctypes.byref(enabled), 0, 0, 0) == 0 and enabled.value == 1,
            'Linux child subreaper unavailable; refusing to launch writers')


def close_owned_children(process):
    receipts = []
    deadline = time.monotonic() + 10
    while owned_children():
        require(time.monotonic() < deadline, 'owned descendant cleanup unproven; no final manifest')
        for pid in owned_children():
            try:
                descriptor = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            try:
                require(pid in owned_children(), 'owned child changed before signaling')
                try:
                    session = os.getsid(pid)
                except ProcessLookupError:
                    session = None
                try:
                    signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                ended, status = os.waitpid(pid, os.WNOHANG)
                if ended:
                    code = os.waitstatus_to_exitcode(status)
                    if process is not None and pid == process.pid:
                        process.returncode = code
                    receipts.append({'pid': pid, 'session': session, 'exit_code': code,
                                     'reaped_utc': datetime.now(timezone.utc).isoformat()})
            finally:
                os.close(descriptor)
        time.sleep(0.01)
    require(process is None or process.returncode is not None, 'primary process was not reaped')
    return receipts


def generated_sources(inventory, expected, toml_bytes, lock_bytes, build, manifest_path):
    domain = manifest_path.parent.name
    source = {name: record for name, record in inventory.items() if name != 'Cargo.lock'}
    require({name: record['sha256'] for name, record in source.items()} == expected,
            'generated source inventory differs ' + domain)
    if lock_bytes is None:
        require('Cargo.lock' not in inventory, 'missing build lock bytes ' + domain)
        return source, None
    require('Cargo.lock' in inventory and inventory['Cargo.lock']['sha256'] == sha(lock_bytes)
            and inventory['Cargo.lock']['size'] == len(lock_bytes), 'build lock identity differs ' + domain)
    command = build.get('command', [])
    require(len(command) == 5 and command[:4] == ['cargo', '+1.95.0', 'build', '--manifest-path']
            and Path(command[4]) == manifest_path
            and isinstance(build.get('exit_code'), int) and isinstance(build.get('timed_out'), bool)
            and isinstance(build.get('process_exit_code'), int)
            and build.get('started_utc') and build.get('ended_utc') and build.get('log'),
            'Cargo.lock lacks actual build-stage association ' + domain)
    manifest = tomllib.loads(toml_bytes.decode())
    lock = tomllib.loads(lock_bytes.decode())
    packages = lock.get('package', [])
    require(lock.get('version') == 4 and isinstance(packages, list) and packages,
            'invalid Cargo.lock package inventory ' + domain)
    package = manifest['package']
    own = [item for item in packages if item.get('name') == package['name']
           and item.get('version') == package['version'] and 'source' not in item]
    require(len(own) == 1 and {item.split()[0] for item in own[0].get('dependencies', [])}
            == set(manifest.get('dependencies', {})), 'Cargo.lock dependencies differ ' + domain)
    identities = {(item['name'], item['version']) for item in packages}
    require(len(identities) == len(packages), 'duplicate Cargo.lock package ' + domain)
    for item in packages:
        require(isinstance(item['name'], str) and isinstance(item['version'], str), 'invalid lock package')
        require(all(dep.split()[0] in {p['name'] for p in packages} for dep in item.get('dependencies', [])),
                'Cargo.lock dependency absent ' + domain)
    for name, version in manifest.get('dependencies', {}).items():
        require(isinstance(version, str), 'unreviewed generated dependency requirement')
        lower = version.removeprefix('^').split('.')
        require(1 <= len(lower) <= 3 and all(part.isdecimal() for part in lower),
                'unreviewed generated dependency version')
        precision = len(lower)
        lower = tuple(map(int, lower)) + (0,) * (3 - len(lower))
        pivot = next((i for i, part in enumerate(lower) if part), precision - 1)
        upper = lower[:pivot] + (lower[pivot] + 1,) + (0,) * (2 - pivot)
        candidates = [item for item in packages if item['name'] == name]
        require(len(candidates) == 1, 'ambiguous locked generated dependency ' + name)
        parts = candidates[0]['version'].split('.')
        require(len(parts) == 3 and all(part.isdecimal() for part in parts)
                and lower <= tuple(map(int, parts)) < upper, 'locked generated dependency version differs ' + name)
    return source, {'identity': inventory['Cargo.lock'], 'parsed': lock, 'build_stage': build,
                    'provenance': 'actual Cargo build output; not translation input'}


def generated_trees(root, result):
    emitted = regular_tree(root / 'rust')
    working = result['working_source_identity']
    require(working['equal'] and working['original_sha256'] == {k: v['sha256'] for k, v in emitted.items()},
            'actual compilation copy differs from license-preserved emitted Rust')
    records, locks = {}, {}
    for domain, expected, stage in (
            ('rust-raw', result['raw_sha256'], 'stable_build'),
            ('rust-working', working['working_sha256'], 'working_stable_build')):
        directory = root / domain
        inventory = regular_tree(directory)
        lock = directory / 'Cargo.lock'
        records[domain], locks[domain] = generated_sources(
            inventory, expected, (directory / 'Cargo.toml').read_bytes(),
            lock.read_bytes() if lock.exists() else None, result.get(stage, {}), directory / 'Cargo.toml')
        if locks[domain] is not None:
            build_log = Path(result[stage]['log'])
            require(build_log.parent == root and not build_log.is_symlink() and build_log.is_file(),
                    'build-stage log outside actual result root')
            locks[domain]['build_log_identity'] = file_identity(build_log)
    require(result['raw_preserved'], 'pristine emitted Rust identity differs')
    require(records['rust-working'] == emitted, 'actual compilation copy differs from license-preserved emitted Rust')
    require(all(record['mode'] == emitted[name]['mode'] for name, record in records['rust-raw'].items()),
            'pristine emitted Rust mode differs')
    require((locks['rust-raw'] is None) == (locks['rust-working'] is None), 'raw/working lock availability differs')
    if locks['rust-raw'] is not None:
        require(locks['rust-raw']['identity'] == locks['rust-working']['identity']
                and locks['rust-raw']['parsed'] == locks['rust-working']['parsed'], 'raw/working Cargo.lock differs')
    return records, locks


def validate_result(root, result, contract, opposite):
    require(result['translation_units'] == 24 and result['complete_translation']
            and result['transpile']['exit_code'] == 0 and not result['transpile']['timed_out']
            and len(result['syntax']) == 24
            and all(s['exit_code'] == 0 and not s['timed_out'] for s in result['syntax'])
            and not result['invalid_output_markers'], 'actual all24 translation incomplete')
    generated, locks = generated_trees(root, result)
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
            'pristine_rust_manifest': generated['rust-raw'], 'compilation_copy_manifest': generated['rust-working'],
            'cargo_build_outputs': locks,
            'driver_identity': file_identity(root / 'shader-driver'),
            'effective_compile_database': read_json(root / 'compile_commands.json')}


def run(args):
    WrapperRun().execute(args)


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
