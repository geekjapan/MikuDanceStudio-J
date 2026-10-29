"""Additional hosted OS controls for literal 82dc. Import and CLI parsing do no OS probes.

Synthetic compiler data is not compiler, CMP, stable Rust, or product acceptance.
--real-os and its internal --worker-output/--fixture entrypoints operate processes and signals
only on the reviewed GHA runtime. --source-only and --upload-gate are read-only checks.
"""
import argparse
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import sys
import time

SOURCE_COMMIT = '82dc9998fbe5b6ed5b8e9f7182edc17b0c6f818c'
SOURCE_TREE = 'cf2862b301001448dc0e932e87b3a05c8d9246a1'
PREFIX = 'tools/vkd3d-rust-probe/'
FROZEN = {
    'run_cmp_input.py': '4bc65f70cf76d8687be0981f8c47a56b17e238264ed215a266be41d4efec6b15',
    'test_cmp_input.py': '0032f8285ce1c13ea4f4aa05586dc7bbe8c9ccfda7b1e678d584bd99df39320b',
    'cmp_input.py': 'e9001f9baec6c48a67287d33af66055d90e036fca47a3b0c65e502e82730b481',
    'cmp_input_contract.json': '51e155ac7517976290e7d1b5028b51947c685f7cab306558480c8a629d86f8b8',
    'apply_c2rust_patch.py': 'b33777b0b325b82bf4377a4486bc2ec3c2a640948c2e5c967c372c792c08c63f',
    'full_compiler.py': '9df615a9625b828f786cac2cd3548b44184baa3b01f2cb753ea1762b91a0548f',
    'probe.py': '4ef671405f42822e795891f5f8310b82e3f89884894040951abcacba65a7596f',
    'shader_driver.rs': 'd409d1c8c41773b78e8bb2d2a50edf576200977acd37e648a016a8f3529d2dc8',
    'shader_matrix.py': 'e2d2404a5dce85d9676372eefd0648e0b009cb4b50108be4e22dfc4340d6b196',
}
PAIRS = ((2, 2), (15, 15), (2, 15), (15, 2))
PHASES = ('entry', 'working-cleanup', 'published-unblocked', 'published-masked')
CASES = [('baseline', 'baseline', 0, 0)] + [
    (f'{phase}-{first}-{second}', phase, first, second)
    for phase in PHASES for first, second in PAIRS] + [
    (f'caller-{kind}-{sig}', 'caller-' + kind, sig, 0)
    for kind in ('blocked', 'pending') for sig in (2, 15)]
ADAPTERS = ('reviewed_contract', 'verify_tool', 'verify_evidence', 'retain_tool_identity',
            'validate_result', 'Popen-command-only')


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON field')
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=pairs)


def atomic(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.pending')
    require(not temporary.exists() and not path.exists(), 'publication must be new')
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    os.replace(temporary, path)


def inventory(root):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        if '.git' in path.relative_to(root).parts:
            continue
        mode = path.lstat().st_mode
        name = path.relative_to(root).as_posix()
        if stat.S_ISDIR(mode):
            result[name + '/'] = {'mode': stat.S_IMODE(mode)}
        elif stat.S_ISLNK(mode):
            result[name] = {'mode': stat.S_IMODE(mode), 'link': os.readlink(path)}
        else:
            require(stat.S_ISREG(mode), 'special filesystem member')
            raw = path.read_bytes()
            result[name] = {'mode': stat.S_IMODE(mode), 'size': len(raw), 'sha256': digest(raw)}
    return result


def frozen_source(source):
    here = Path(source) / PREFIX
    for name, expected in FROZEN.items():
        require(digest((here / name).read_bytes()) == expected, 'frozen source differs ' + name)
    return dict(FROZEN)


def validate_registry():
    expected = (
        ('baseline', 'baseline', 0, 0),
        ('entry-2-2', 'entry', 2, 2),
        ('entry-15-15', 'entry', 15, 15),
        ('entry-2-15', 'entry', 2, 15),
        ('entry-15-2', 'entry', 15, 2),
        ('working-cleanup-2-2', 'working-cleanup', 2, 2),
        ('working-cleanup-15-15', 'working-cleanup', 15, 15),
        ('working-cleanup-2-15', 'working-cleanup', 2, 15),
        ('working-cleanup-15-2', 'working-cleanup', 15, 2),
        ('published-unblocked-2-2', 'published-unblocked', 2, 2),
        ('published-unblocked-15-15', 'published-unblocked', 15, 15),
        ('published-unblocked-2-15', 'published-unblocked', 2, 15),
        ('published-unblocked-15-2', 'published-unblocked', 15, 2),
        ('published-masked-2-2', 'published-masked', 2, 2),
        ('published-masked-15-15', 'published-masked', 15, 15),
        ('published-masked-2-15', 'published-masked', 2, 15),
        ('published-masked-15-2', 'published-masked', 15, 2),
        ('caller-blocked-2', 'caller-blocked', 2, 0),
        ('caller-blocked-15', 'caller-blocked', 15, 0),
        ('caller-pending-2', 'caller-pending', 2, 0),
        ('caller-pending-15', 'caller-pending', 15, 0),
    )
    require(tuple(CASES) == expected, 'case registry differs')
    return expected


def source_only_check(source):
    frozen_source(source)
    tree = ast.parse((Path(source) / PREFIX / 'run_cmp_input.py').read_text())
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'WrapperRun')
    require({'execute', 'interrupt', 'invoke', '_finish', 'normalize', '_signal_runtime', '_drain_python'}
            <= {node.name for node in owner.body if isinstance(node, ast.FunctionDef)}, 'owner methods missing')
    validate_registry()
    return {'kind': 'source-only; actual 42 OS cases UNRUN', 'frozen': FROZEN, 'cases_per_mode': 21}


def validate_seal(expected, observed):
    require(bool(expected) and expected == observed, 'packet seal membership/bytes/modes differ')
    return True


def runtime_guard():
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and sys.platform == 'linux', 'real OS requires hosted Linux')
    require(os.environ.get('PYTHONDONTWRITEBYTECODE') == '1' and sys.dont_write_bytecode,
            'all children require PYTHONDONTWRITEBYTECODE=1 and -B')
    require(sys.implementation.name == 'cpython' and sys.version_info[:3] == (3, 12, 3), 'requires CPython 3.12.3')
    require(len(list(Path('/proc/self/task').iterdir())) == 1, 'requires one OS thread')
    require(not children(), 'unrelated children refused')
    require(hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'), 'pidfd unavailable')


def children():
    return [int(value) for value in Path(f'/proc/self/task/{os.getpid()}/children').read_text().split()]


def git_identity(root, expected=None):
    commands = []
    def git(*args):
        command = ['git', '-C', str(root), *args]
        start = time.time_ns()
        value = subprocess.run(command, capture_output=True, check=False)
        commands.append({'argv': command, 'pid_scope': 'synchronous reaped child; communicate streams closed',
                         'start_ns': start, 'end_ns': time.time_ns(), 'exit': value.returncode,
                         'stdout_sha256': digest(value.stdout), 'stderr': value.stderr.decode()})
        require(value.returncode == 0, 'Git identity command failed')
        return value.stdout
    head = git('rev-parse', 'HEAD').decode().strip()
    raw_commit = git('cat-file', 'commit', head)
    require(hashlib.sha1(b'commit ' + str(len(raw_commit)).encode() + b'\0' + raw_commit).hexdigest() == head,
            'raw commit framing differs')
    tree = raw_commit.splitlines()[0].decode().removeprefix('tree ')
    raw_tree = git('cat-file', 'tree', tree)
    require(hashlib.sha1(b'tree ' + str(len(raw_tree)).encode() + b'\0' + raw_tree).hexdigest() == tree,
            'raw tree framing differs')
    if expected:
        require((head, tree) == expected, 'literal tested Git identity differs')
    require(not git('status', '--porcelain', '--untracked-files=all'), 'checkout must be clean')
    listing = git('ls-tree', '-rz', '--full-tree', head)
    files = inventory(root)
    tracked = set()
    for item in listing.split(b'\0'):
        if not item:
            continue
        metadata, name_raw = item.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        name = name_raw.decode()
        tracked.add(name)
        path = Path(root) / name
        require(kind == 'blob', 'submodule unsupported')
        raw = os.readlink(path).encode() if mode == '120000' else path.read_bytes()
        require(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == oid,
                'checkout blob differs ' + name)
        require(mode == '120000' or stat.S_IMODE(path.stat().st_mode) == (0o755 if mode == '100755' else 0o644),
                'checkout mode differs ' + name)
    require({name for name in files if not name.endswith('/')} == tracked, 'complete checkout membership differs')
    return {'head': head, 'tree': tree, 'raw_commit': raw_commit.decode(),
            'raw_tree_sha256': digest(raw_tree), 'filesystem': files, 'commands': commands}


def load_source(source):
    frozen_source(source)
    here = (Path(source) / PREFIX).resolve()
    sys.path.insert(0, str(here))
    import run_cmp_input as wrapper
    import cmp_input as boundary
    import apply_c2rust_patch as tool
    for module in (wrapper, boundary, tool):
        require(Path(module.__file__).resolve().parent == here, 'import origin escaped tested checkout')
    for value in vars(wrapper.WrapperRun).values():
        if hasattr(value, '__code__'):
            require(Path(value.__code__.co_filename).resolve() == here / 'run_cmp_input.py', 'owner code origin differs')
    return wrapper, boundary, tool


def fixture_data(root, boundary):
    contract = copy.deepcopy(boundary.reviewed_contract())
    source = root / 'native/source'
    (source / 'libs/vkd3d-shader').mkdir(parents=True)
    original = (b'static uint32_t spirv_get_type_id(struct spirv_compiler *compiler);\n'
                b'static uint32_t spirv_compiler_get_constant_float_vector(struct spirv_compiler *compiler);\n'
                b'static void spirv_compiler_emit_movc(void)\n{\n'
                + contract['patches']['zero-first']['before'].encode() + b'\n}\n\nstatic void next(void) {}\n')
    (source / boundary.SITE).write_bytes(original)
    (source / 'include').mkdir()
    (source / 'include/config.h').write_text('#define TEST 1\n')
    for name in ('hdr', 'spv'):
        directory = source.parent / name / 'include'
        directory.mkdir(parents=True)
        (directory / 'fixture.h').write_text('\n')
    library = root / 'oracle.data'
    library.write_bytes(b'INERT ORACLE DATA; NEVER EXECUTE')
    tool = root / 'tool'
    (tool / 'bin').mkdir(parents=True)
    (tool / 'bin/c2rust').write_bytes(b'INERT TOOL; NEVER EXECUTE')
    contract.update(source_sha256=boundary.sha(original), source_size=len(original),
                    manifests={'source': boundary.regular_tree(source), **{
                        name: boundary.regular_tree(source.parent / name / 'include') for name in ('hdr', 'spv')}},
                    native_library={key: boundary.file_identity(library)[key] for key in ('sha256', 'size')},
                    tool_manifest=boundary.regular_tree(tool))
    for data in contract['patches'].values():
        data['normalized_sha256'] = boundary.sha(original.replace(data['before'].encode(), data['after'].encode()))
    args = argparse.Namespace(source=source, native_library=library, c2rust=tool / 'bin/c2rust',
                              clang=tool / 'bin/c2rust', target=contract['target'], artifacts=root / 'actual')
    return contract, args


def fixture_command(command, here, product_args, ordinal, phase, script, optimized):
    base = [sys.executable, '-B'] + (['-O'] if optimized else []) + [str(script)]
    if command == ['rustc', '+1.95.0', '-vV']:
        require(ordinal == 1, 'host command out of order')
        return base + ['--fixture', 'host', '--target', product_args.target]
    require(ordinal in (2, 3), 'unexpected probe invocation count')
    variant = ('correct', 'opposite')[ordinal - 2]
    source = product_args.artifacts / (variant + '-input/source')
    output = product_args.artifacts / variant
    expected = [sys.executable, '-B', str(here / 'probe.py'), '--source', str(source), '--artifacts', str(output),
                '--c2rust', str(product_args.c2rust), '--clang', str(product_args.clang),
                '--rust-toolchain', '1.95.0', '--all-unit-prototype', '--timeout', '1800', '--build-timeout', '300',
                '--native-library', str(product_args.native_library)]
    require(command == expected, 'unknown command refused')
    return base + ['--fixture', 'working' if phase == 'working-cleanup' else 'probe',
                   '--fixture-source', str(source), '--fixture-output', str(output)]


def fd_snapshot():
    result = {}
    for path in list(Path('/proc/self/fd').iterdir()):
        try:
            result[path.name] = os.readlink(path)
        except FileNotFoundError:
            pass
    return result


class Channel:
    def __init__(self, incoming, outgoing):
        self.incoming, self.outgoing = incoming, outgoing
        self.buffer = b''
        self.serial = 0

    def send(self, kind, **data):
        self.serial += 1
        raw = json.dumps(dict(kind=kind, seq=self.serial, pid=os.getpid(), **data)).encode() + b'\n'
        require(len(raw) < 4096, 'IPC record exceeds atomic pipe bound')
        require(os.write(self.outgoing, raw) == len(raw), 'short IPC write')

    def receive(self, seconds=5):
        deadline = time.monotonic() + seconds
        while b'\n' not in self.buffer:
            remaining = deadline - time.monotonic()
            require(remaining > 0 and select.select([self.incoming], [], [], remaining)[0], 'rendezvous deadline')
            data = os.read(self.incoming, 4096)
            require(data, 'IPC closed before terminal message')
            self.buffer += data
        raw, self.buffer = self.buffer.split(b'\n', 1)
        return json.loads(raw)

    def pause(self, kind, **data):
        self.send(kind, **data)
        require(self.receive()['kind'] == 'continue', 'unexpected controller instruction')


def fixture_process(args):
    runtime_guard()
    import shutil
    channel = Channel(args.input_fd, args.output_fd)
    if args.fixture == 'host':
        print('\nhost: ' + args.target)
        return
    if args.fixture == 'descendant':
        select.select([], [], [], 24)
        return
    source, output = Path(args.fixture_source), Path(args.fixture_output)
    shutil.copytree(source, output / 'source')
    (output / 'result.json').write_text('{}')
    if args.fixture == 'working':
        command = [sys.executable, '-B'] + (['-O'] if sys.flags.optimize else []) + [str(Path(__file__).resolve()), '--fixture', 'descendant',
                   '--input-fd', str(args.input_fd), '--output-fd', str(args.output_fd)]
        child = subprocess.Popen(command, start_new_session=True, pass_fds=(args.output_fd,))
        channel.send('writer-ready', primary=os.getpid(), descendant=child.pid,
                     session=os.getsid(0), descendant_session=os.getsid(child.pid))
        select.select([], [], [], 24)


def worker(args):
    runtime_guard()
    os.set_blocking(args.output_fd, False)
    channel = Channel(args.input_fd, args.output_fd)
    case = next(case for case in CASES if case[0] == args.case)
    _, phase, first, second = case
    wrapper, boundary, tool = load_source(args.source_checkout)
    wrapper.enable_custody()
    root = Path(args.worker_output)
    root.mkdir()
    contract, product_args = fixture_data(root, boundary)
    fixture_before = inventory(root)
    owner = wrapper.WrapperRun()
    real = dict(mask=signal.pthread_sigmask, install=signal.signal, pending=signal.sigpending,
                timedwait=signal.sigtimedwait, replace=os.replace, pidfd=os.pidfd_open, close=os.close,
                popen=subprocess.Popen)
    wait_code = subprocess.Popen.wait.__code__
    fds_before = fd_snapshot()
    old_mask = real['mask'](signal.SIG_BLOCK, set())
    old_handlers = {sig: signal.getsignal(sig) for sig in owner.signals}
    callers = []
    def caller_int(sig, frame):
        callers.append(sig)
    def caller_term(sig, frame):
        callers.append(sig)
    caller_handlers = {signal.SIGINT: caller_int, signal.SIGTERM: caller_term}
    for sig, callback in caller_handlers.items():
        real['install'](sig, callback)
    original_mask = set(old_mask) | {signal.SIGUSR1}
    real['mask'](signal.SIG_SETMASK, original_mask)
    counts = dict(normalize=0, invoke=0, execute_body=0, popen=0, retain=0, finish=0, close=0)
    descriptors, processes, commands, handler_events, kernel_events, streams = [], [], [], [], [], []
    active, max_active = {'finish': 0, 'close': 0}, {'finish': 0, 'close': 0}
    cancelled_seen = False
    handoff = False
    fs_after_handoff = []
    first_rendezvous = False
    second_rendezvous = False
    in_followon = False
    module_file = str(Path(wrapper.__file__).resolve())

    def profile(frame, event, arg):
        nonlocal cancelled_seen
        if frame.f_code is wrapper.WrapperRun.interrupt.__code__ and frame.f_locals.get('self') is owner:
            if event == 'return':
                sig = frame.f_locals['signum']
                require(owner.cancelled, 'interrupt did not latch cancellation')
                require(signal.getsignal(sig).__self__ is owner, 'callback owner identity differs')
                record = dict(signal=sig, phase=owner.phase, cancelled=owner.cancelled,
                              handler=len(handler_events) + 1, owner=id(owner))
                handler_events.append(record)
                channel.send('handler-return', **record)
        if frame.f_code.co_filename == module_file:
            if event == 'call':
                name = frame.f_code.co_name
                key = {'normalize': 'normalize', 'invoke': 'invoke', '_execute': 'execute_body',
                       '_finish': 'finish', 'close_owned_children': 'close'}.get(name)
                if key:
                    if not in_followon:
                        counts[key] += 1
                    if key in active:
                        active[key] += 1
                        max_active[key] = max(max_active[key], active[key])
            elif event == 'return':
                key = {'_finish': 'finish', 'close_owned_children': 'close'}.get(frame.f_code.co_name)
                if key:
                    active[key] -= 1
        if event == 'call' and frame.f_code is wait_code:
            process = frame.f_locals.get('self')
            if process in processes:
                channel.send('wait-enter', writer=process.pid, phase=owner.phase)
        if cancelled_seen:
            require(owner.cancelled, 'cancellation latch regressed')
        cancelled_seen = cancelled_seen or owner.cancelled

    def audit(event, values):
        if handoff and event in ('open', 'os.rename', 'os.remove', 'os.mkdir', 'os.rmdir', 'os.listdir', 'os.scandir'):
            frame = sys._getframe(1)
            while frame:
                if frame.f_code.co_filename == module_file:
                    fs_after_handoff.append(event)
                    raise ValueError('wrapper filesystem I/O after confirmed handoff')
                frame = frame.f_back
    sys.addaudithook(audit)

    def pause_second(masked=False):
        nonlocal second_rendezvous
        require(len(handler_events) == 1 and first not in real['pending'](), 'first delivery not distinct and completed')
        second_rendezvous = True
        channel.pause('ready-second', phase=owner.phase, masked=masked, pending=sorted(real['pending']()))
        pending = sorted(real['pending']())
        kernel_events.append(dict(point='second-after-send', pending=pending))
        if masked:
            require(second in pending, 'second signal not kernel pending')
        else:
            require(len(handler_events) == 2 and not set(owner.signals) & set(pending), 'second handler ACK missing')

    def install(sig, callback):
        nonlocal first_rendezvous
        result = real['install'](sig, callback)
        if phase == 'entry' and owner.phase == 'installing' and sig == signal.SIGTERM:
            require(set(owner.signals) <= real['mask'](signal.SIG_BLOCK, set()), 'entry owned signals not blocked')
            first_rendezvous = True
            channel.pause('ready-first', phase=owner.phase, blocked=True)
            pending = sorted(real['pending']())
            kernel_events.append(dict(point='entry-first', pending=pending))
            require(first in pending and not handler_events, 'entry first not held pending')
        return result

    def mask(how, signals):
        nonlocal handoff
        result = real['mask'](how, signals)
        if phase == 'entry' and owner.phase == 'installing' and how == signal.SIG_SETMASK and first_rendezvous:
            pause_second()
        if phase == 'published-masked' and owner.phase == 'finishing' and how == signal.SIG_BLOCK and first_rendezvous:
            if not second_rendezvous:
                pause_second(masked=True)
        if owner.phase in ('completed', 'closed') and how == signal.SIG_SETMASK:
            handoff = True
        return result

    def replace(source, destination, *positional, **keywords):
        nonlocal first_rendezvous
        result = real['replace'](source, destination, *positional, **keywords)
        if Path(destination).name == 'output-manifest.json' and phase.startswith('published-'):
            first_rendezvous = True
            channel.pause('ready-first', phase=owner.phase, blocked=False)
            require(len(handler_events) == 1, 'published first handler ACK missing')
            if phase == 'published-unblocked':
                pause_second()
        return result

    def pidfd(pid, flags=0):
        descriptor = real['pidfd'](pid, flags)
        descriptors.append(descriptor)
        if (phase == 'working-cleanup' and owner.phase == 'closing' and pid in wrapper.owned_children()
                and not second_rendezvous):
            pause_second()
        return descriptor

    def timedwait(signals, timeout):
        result = real['timedwait'](signals, timeout)
        kernel_events.append(dict(point='original-sigtimedwait', requested=sorted(signals),
                                  consumed=result.si_signo if result else None, pending=sorted(real['pending']())))
        return result

    def retain(*unused):
        counts['retain'] += 1

    def popen(command, **kwargs):
        counts['popen'] += 1
        require(not owner.cancelled, 'Popen after cancellation')
        require(set(kwargs) == {'cwd', 'stdout', 'stderr', 'start_new_session'}
                and kwargs['start_new_session'] is True and kwargs['stderr'] == subprocess.STDOUT,
                'unexpected Popen options')
        here = Path(wrapper.__file__).resolve().parent
        require(Path(kwargs['cwd']) == here, 'unexpected command cwd')
        translated = fixture_command(command, here, product_args, counts['popen'], phase,
                                     Path(__file__).resolve(), bool(sys.flags.optimize))
        translated += ['--input-fd', str(args.input_fd), '--output-fd', str(args.output_fd)]
        commands.append(dict(original=command, translated=translated))
        streams.append(kwargs['stdout'])
        process = real['popen'](translated, pass_fds=(args.output_fd,), **kwargs)
        processes.append(process)
        return process

    wrapper.reviewed_contract = boundary.reviewed_contract = lambda *unused: contract
    tool.verify_tool = lambda *unused: None
    tool.verify_evidence = lambda *unused: {'patch_sha256': contract['compiler_patch_sha256'],
        'modified_source_sha256': dict.fromkeys(range(contract['compiler_patch_destinations']))}
    tool.retain_tool_identity = retain
    wrapper.validate_result = lambda *unused: {'stable_build': {'exit_code': 101}, 'working_stable_build': {'exit_code': 101}}
    subprocess.Popen = popen
    signal.signal, signal.pthread_sigmask, signal.sigtimedwait = install, mask, timedwait
    os.replace, os.pidfd_open = replace, pidfd
    sys.setprofile(profile)
    refusal_before = refusal_after = None
    exception = None
    try:
        if phase.startswith('caller-'):
            real['mask'](signal.SIG_BLOCK, {first})
            if phase == 'caller-pending':
                channel.pause('caller-pending-ready', signal=first)
            def caller_state():
                return {'mask': sorted(real['mask'](signal.SIG_BLOCK, set())), 'pending': sorted(real['pending']()),
                        'handlers': {str(sig): id(signal.getsignal(sig)) for sig in owner.signals}}
            refusal_before = caller_state()
        try:
            owner.execute(product_args)
        except (KeyboardInterrupt, ValueError) as error:
            exception = {'type': type(error).__name__, 'message': str(error)}
        if phase.startswith('caller-'):
            refusal_after = caller_state()
            require(refusal_before == refusal_after, 'caller state changed on refusal')
            expected = 'already pending' if phase == 'caller-pending' else 'must be unblocked'
            require(exception and exception['type'] == 'ValueError' and expected in exception['message'], 'wrong admission refusal')
            require(not any(counts.values()) and not product_args.artifacts.exists(), 'refusal entered body or wrote output')
            real['mask'](signal.SIG_SETMASK, original_mask)
            require(callers == ([first] if phase == 'caller-pending' else []), 'caller pending delivery differs')
        elif phase == 'baseline':
            require(exception is None and owner.phase == 'completed' and handoff, 'legal baseline failed')
            require((product_args.artifacts / 'output-manifest.json').is_file()
                    and len(list(product_args.artifacts.rglob('receipt.json'))) == 2, 'baseline publication incomplete')
        else:
            require(exception and exception['type'] == 'KeyboardInterrupt' and owner.cancelled, 'cancellation absent')
            require(not (product_args.artifacts / 'output-manifest.json').exists()
                    and not (product_args.artifacts / 'output-manifest.pending').exists()
                    and not list(product_args.artifacts.rglob('receipt.json')), 'cancellation publication remains')
            if phase == 'entry':
                require(not product_args.artifacts.exists(), 'entry cancellation wrote output')
            else:
                require((product_args.artifacts / 'CANCELLED').is_file(), 'cancelled marker absent')
                require(read_json(product_args.artifacts / 'report.json')['status'] == 'cancelled', 'report not cancelled')
                for path in product_args.artifacts.glob('*-input'):
                    require((path / 'INCOMPLETE').is_file(), 'partial input not marked incomplete')
            snapshot = dict(counts)
            in_followon = True
            for operation in (lambda: owner.normalize(None), lambda: owner.invoke([], None, None, 1)):
                try:
                    operation()
                except KeyboardInterrupt:
                    pass
                else:
                    raise ValueError('cancelled follow-on work admitted')
            in_followon = False
            require(snapshot == counts, 'follow-on work reached a body')
        require(not wrapper.owned_children() and owner.writer is None, 'owned closure unproven')
        require(not fs_after_handoff, 'post-handoff wrapper I/O')
        require(all(value <= 1 for value in max_active.values()), 'reentrant close or finish')
        require(real['mask'](signal.SIG_BLOCK, set()) == original_mask, 'caller original mask not restored')
        require(all(signal.getsignal(sig) is callback for sig, callback in caller_handlers.items()), 'caller handlers not restored')
        require(callers == ([first] if phase == 'caller-pending' else []), 'unexpected caller delivery')
        for descriptor in set(descriptors):
            try:
                os.fstat(descriptor)
            except OSError:
                pass
            else:
                raise ValueError('pidfd still open')
        require(all(process.returncode is not None for process in processes), 'unreaped Popen')
        require(all(stream.closed for stream in streams), 'native output stream remains open')
        require(fd_snapshot() == fds_before, 'native descriptor set not restored')
        fixture_after = inventory(root)
        immutable_after = {name: value for name, value in fixture_after.items()
                           if name.startswith(('native/', 'tool/')) or name == 'oracle.data'}
        require(immutable_after == fixture_before, 'fixture bytes/modes/membership changed')
        receipts = [read_json(path) for path in product_args.artifacts.rglob('*.custody.json')]
        require(all(receipt['owned_writers_closed'] for receipt in receipts), 'invocation closure receipt absent')
        if phase == 'working-cleanup':
            require(any(receipt['owned_descendants_reaped'] for receipt in receipts), 'working descendants not reaped')
        atomic(root / 'result.json', dict(case=args.case, mode='optimized' if sys.flags.optimize else 'normal',
            source=SOURCE_COMMIT, tree=SOURCE_TREE, pid=os.getpid(), session=os.getsid(0), phase=phase,
            first=first, second=second, handlers=handler_events, kernel=kernel_events, counts=counts,
            exception=exception, refusal_before=refusal_before, refusal_after=refusal_after,
            caller_deliveries=callers, caller_restored=True, children=[], writer_none=True, pidfds_closed=True,
            subprocesses_reaped=True, streams_closed=True, post_handoff_io=[], commands=commands,
            native_fds_before=fds_before, native_fds_after=fd_snapshot(),
            custody=receipts, adapters=list(ADAPTERS), status='PASS', runtime=list(sys.version_info[:3])))
        channel.send('worker-closed', case=args.case, owned_closed=True)
    finally:
        sys.setprofile(None)
        subprocess.Popen = real['popen']
        signal.signal, signal.pthread_sigmask, signal.sigtimedwait = real['install'], real['mask'], real['timedwait']
        os.replace, os.pidfd_open = real['replace'], real['pidfd']
        for sig, callback in old_handlers.items():
            real['install'](sig, callback)
        real['mask'](signal.SIG_SETMASK, old_mask)


def validate_case(receipt, case, mode, pid, events):
    require(case in validate_registry(), 'case registry differs')
    name, phase, first, second = case
    require(receipt.get('phase') == phase and receipt.get('first') == first and receipt.get('second') == second
            and receipt['case'] == name and receipt['mode'] == mode and receipt['pid'] == pid,
            'case/mode/PID identity differs')
    require(receipt['source'] == SOURCE_COMMIT and receipt['tree'] == SOURCE_TREE, 'receipt source differs')
    require(receipt['status'] == 'PASS' and receipt['runtime'] == [3, 12, 3], 'incomplete case')
    require(receipt['children'] == [] and all(receipt[key] is True for key in
        ('writer_none', 'pidfds_closed', 'subprocesses_reaped', 'streams_closed', 'caller_restored'))
        and receipt['post_handoff_io'] == [], 'false closure')
    require(receipt['adapters'] == list(ADAPTERS), 'adapter inventory differs')
    require(receipt['native_fds_before'] == receipt['native_fds_after'], 'native descriptor identity differs')
    require(all(event.get('kind') in ('send', 'handler-return', 'ready-first', 'ready-second',
                'caller-pending-ready', 'wait-enter', 'writer-ready', 'worker-closed') for event in events), 'unknown event')
    require(all(event['pid'] == pid or (phase == 'working-cleanup' and event['kind'] == 'writer-ready')
                for event in events), 'foreign event identity')
    worker_events = [event for event in events if event['pid'] == pid and event['kind'] != 'send']
    require([event['seq'] for event in worker_events] == list(range(1, len(worker_events) + 1)), 'IPC missing/duplicate/reordered')
    require(worker_events and worker_events[-1]['kind'] == 'worker-closed', 'terminal closure event absent')
    require(worker_events[-1].get('case') == name and worker_events[-1].get('owned_closed') is True,
            'terminal closure event differs')
    sends = [event for event in events if event['kind'] == 'send']
    require(all(event.get('pidfd_retained') is True for event in sends), 'send pidfd identity differs')
    delivery = [event['kind'] for event in events if event['kind'] not in ('wait-enter', 'writer-ready')]
    acks = [{key: value for key, value in event.items() if key not in ('kind', 'pid', 'seq')}
            for event in events if event['kind'] == 'handler-return']
    kernel = receipt['kernel']
    handlers = receipt['handlers']
    counts = receipt['counts']
    waits = [event for event in events if event['kind'] == 'wait-enter']
    writers = [item.get('pid') for item in receipt['custody']]
    require(len(waits) == counts['popen'] == len(writers) == len(set(writers))
            and {event.get('writer') for event in waits} == set(writers)
            and all(isinstance(event.get('writer'), int) and event['writer'] > 0
                    and event.get('phase') == 'working' for event in waits), 'wait observation differs')
    if sends and not phase.startswith('caller-'):
        require(all(events.index(event) < events.index(sends[0]) for event in waits), 'wait after cancellation')
    if phase == 'baseline':
        require(not kernel, 'baseline kernel transcript differs')
        require(delivery == ['worker-closed'], 'delivery event order differs')
        require(not acks and not any(event['kind'] == 'writer-ready' for event in events), 'extra baseline event')
        require(not sends and not handlers and counts['popen'] == 3 and counts['invoke'] == 3
                and counts['normalize'] == 2 and len(receipt['custody']) == 3
                and all(item['custody_status'] == 'clean' for item in receipt['custody']), 'baseline counts differ')
    elif phase.startswith('caller-'):
        require(not kernel, 'refusal kernel transcript differs')
        expected_delivery = ['caller-pending-ready', 'send', 'worker-closed'] if phase == 'caller-pending' else ['worker-closed']
        require(delivery == expected_delivery, 'delivery event order differs')
        require(not acks and not any(event['kind'] in ('wait-enter', 'writer-ready') for event in events), 'extra refusal event')
        if phase == 'caller-pending':
            require(events[0].get('signal') == first, 'caller pending readiness differs')
        require(not handlers and not any(counts.values()) and receipt['refusal_before'] == receipt['refusal_after'],
                'refusal consumed caller state or entered body')
        require(receipt['caller_deliveries'] == ([first] if phase == 'caller-pending' else []), 'caller completion differs')
        require([event['signal'] for event in sends] == ([first] if phase == 'caller-pending' else []), 'refusal delivery differs')
        before = receipt['refusal_before']
        require(first in before['mask'] and (first in before['pending']) == (phase == 'caller-pending'), 'false refusal state')
    else:
        require([event['signal'] for event in sends] == [first, second], 'two distinct sends required')
        require(receipt['caller_deliveries'] == [], 'owner leaked delivery to caller')
        require(len(handlers) == (1 if phase == 'published-masked' else 2), 'handler ACK count differs')
        require([event.get('signal') for event in handlers] == ([first] if phase == 'published-masked' else [first, second]),
                'handler signal order differs')
        expected_phases = ['installing', 'installing'] if phase == 'entry' else (
            ['working', 'closing'] if phase == 'working-cleanup' else
            (['finishing'] if phase == 'published-masked' else ['finishing', 'finishing']))
        require([event.get('phase') for event in handlers] == expected_phases
                and all(set(event) == {'signal', 'phase', 'cancelled', 'handler', 'owner'}
                        and event.get('cancelled') is True and isinstance(event.get('owner'), int) and event['owner'] > 0
                        for event in handlers)
                and [event.get('handler') for event in handlers] == list(range(1, len(handlers) + 1))
                and len({event['owner'] for event in handlers}) == 1, 'handler owner/phase/latch/ordinal differs')
        require(acks == handlers, 'handler transcript differs')
        expected_delivery = ([] if phase == 'working-cleanup' else ['ready-first']) + [
            'send', 'handler-return', 'ready-second', 'send'] + (
            [] if phase == 'published-masked' else ['handler-return']) + ['worker-closed']
        require(delivery == expected_delivery, 'delivery event order differs')
        second_ready = next(event for event in events if event['kind'] == 'ready-second')
        require(not {2, 15} & set(second_ready['pending'])
                and second_ready.get('phase') == ('closing' if phase == 'working-cleanup' else expected_phases[0])
                and second_ready.get('masked') is (phase == 'published-masked'), 'second readiness differs')
        if phase != 'working-cleanup':
            ready = next(event for event in events if event['kind'] == 'ready-first')
            require(ready.get('phase') == expected_phases[0] and ready.get('blocked') is (phase == 'entry'),
                    'first readiness differs')
            require(not any(event['kind'] == 'writer-ready' for event in events), 'extra writer readiness')
        expected_kernel = (['entry-first'] if phase == 'entry' else []) + ['second-after-send'] + (
            ['original-sigtimedwait'] if phase == 'published-masked' else [])
        require([event.get('point') for event in kernel] == expected_kernel, 'kernel event order differs')
        if phase == 'entry':
            require({2, 15} & set(kernel[0]['pending']) == {first}, 'entry kernel pending differs')
        after_send = kernel[1 if phase == 'entry' else 0]
        require({2, 15} & set(after_send['pending']) == ({second} if phase == 'published-masked' else set()),
                'second kernel pending differs')
        if phase == 'published-masked':
            consumed = kernel[-1]
            require(consumed.get('requested') == [second] and consumed.get('consumed') == second
                    and not {2, 15} & set(consumed['pending']), 'kernel consume proof differs')
        expected = (0, 0) if phase == 'entry' else ((2, 1) if phase == 'working-cleanup' else (3, 2))
        require(counts['popen'] == expected[0] and counts['normalize'] == expected[1], 'unexpected work after cancellation')
        if phase == 'working-cleanup':
            writers = [event for event in events if event['kind'] == 'writer-ready']
            require(len(writers) == 1, 'working writer readiness absent/duplicate')
            writer = writers[0]
            first_send = next(i for i, event in enumerate(events) if event['kind'] == 'send')
            require(writer.get('primary') == writer['pid'] == writer.get('session')
                    and writer.get('descendant') == writer.get('descendant_session')
                    and events.index(writer) < first_send
                    and any(event['kind'] == 'wait-enter' and event['writer'] == writer['pid']
                            and event['phase'] == 'working' for event in events[:first_send]),
                    'working writer delivery order differs')
            reaped = [item for custody in receipt['custody'] for item in custody['owned_descendants_reaped']]
            require(any(item['pid'] == writer['primary'] and item['session'] == writer['session'] for item in reaped)
                    and any(item['pid'] == writer['descendant'] and item['session'] == writer['descendant_session']
                            for item in reaped), 'primary/descendant reap identity differs')
    return True


def validate_index(index):
    expected = validate_registry()
    require(index['schema'] == 1 and index['source'] == SOURCE_COMMIT and index['tree'] == SOURCE_TREE, 'index identity differs')
    require(index['closed'] is True and index['controller_children'] == [] and index['streams_closed'] is True,
            'index closure unproven')
    require(index['mode'] in ('normal', 'optimized') and index['cases'], 'empty index cannot authorize upload')
    require(len({case['case'] for case in index['cases']}) == len(index['cases']), 'duplicate index case')
    require(all(case['case'] in {item[0] for item in expected} and case['terminal'] is True
                and case['owned_closed'] is True and case['streams_closed'] is True and case['pidfd_closed'] is True
                and case['forced_cleanup'] is False and isinstance(case['exit'], int) for case in index['cases']),
            'case custody not proved')
    if index['status'] == 'PASS':
        require([case['case'] for case in index['cases']] == [case[0] for case in expected]
                and all(case['exit'] == 0 and case['validated'] is True for case in index['cases']), 'PASS case coverage differs')
    else:
        require(index['status'] == 'FAIL', 'unknown index status')
    return True


def controller(args):
    runtime_guard()
    output = Path(args.real_os)
    require(not output.exists(), 'mode output must be new')
    output.mkdir(parents=True)
    (output / 'OWNED_WRITERS_UNPROVEN').write_text('No upload until explicit final custody index validates.\n')
    controller_root = Path(__file__).resolve().parents[2]
    require(controller_root != args.source_checkout.resolve(), 'controller and tested checkout must be separate')
    source_before = git_identity(args.source_checkout, (SOURCE_COMMIT, SOURCE_TREE))
    controller_before = git_identity(controller_root)
    require(controller_before['head'] == os.environ.get('GITHUB_SHA'), 'controller differs from actual GITHUB_SHA')
    frozen_source(args.source_checkout)
    wrapper, _, _ = load_source(args.source_checkout)
    wrapper.enable_custody()
    atomic(output / 'source-before.json', source_before)
    atomic(output / 'controller-before.json', controller_before)
    mode = 'optimized' if sys.flags.optimize else 'normal'
    index = dict(schema=1, source=SOURCE_COMMIT, tree=SOURCE_TREE, mode=mode, status='FAIL', closed=False,
                 cases=[], controller_children=[], streams_closed=False,
                 github={key: os.environ.get(key) for key in ('GITHUB_SHA', 'GITHUB_REF', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB')})
    deadline = time.monotonic() + 420
    for case in CASES:
        require(time.monotonic() < deadline, 'mode deadline exceeded')
        name, phase, first, second = case
        incoming, worker_output = os.pipe()
        worker_input, outgoing = os.pipe()
        log_path = output / (name + '.stderr')
        command = [sys.executable, '-B'] + (['-O'] if sys.flags.optimize else []) + [str(Path(__file__).resolve()),
            '--source-checkout', str(args.source_checkout), '--worker-output', str(output / name), '--case', name,
            '--input-fd', str(worker_input), '--output-fd', str(worker_output)]
        events, held_fd, process, closed = [], None, None, False
        launched_at = time.monotonic()
        with log_path.open('wb') as log:
            try:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log,
                                           pass_fds=(worker_input, worker_output), start_new_session=True)
                held_fd = os.pidfd_open(process.pid)
                os.close(worker_input)
                os.close(worker_output)
                channel = Channel(incoming, outgoing)
                ready_writer = waiting_writer = None
                first_sent = False
                def send(sig):
                    nonlocal first_sent
                    require(time.monotonic() - launched_at < 25, 'worker deadline')
                    signal.pidfd_send_signal(held_fd, sig)
                    events.append(dict(kind='send', signal=sig, pid=process.pid, pidfd_retained=True))
                    first_sent = True
                while True:
                    event = channel.receive(min(5, 25 - (time.monotonic() - launched_at)))
                    events.append(event)
                    kind = event['kind']
                    require(event['pid'] == process.pid or kind == 'writer-ready', 'foreign IPC PID')
                    if kind in ('ready-first', 'caller-pending-ready'):
                        send(first)
                        channel.send('continue')
                    elif kind == 'ready-second':
                        require(first_sent, 'second requested before first')
                        send(second)
                        channel.send('continue')
                    elif kind == 'writer-ready':
                        require(phase == 'working-cleanup' and event['primary'] == event['pid']
                                and event['session'] == event['pid']
                                and event['descendant_session'] == event['descendant'], 'writer session differs')
                        ready_writer = event['pid']
                    elif kind == 'wait-enter' and phase == 'working-cleanup':
                        waiting_writer = event['writer']
                    elif kind == 'worker-closed':
                        closed = event['owned_closed'] is True
                        break
                    if phase == 'working-cleanup' and ready_writer == waiting_writer and ready_writer and not first_sent:
                        send(first)
                process.wait(timeout=max(0.01, 25 - (time.monotonic() - launched_at)))
            except BaseException:
                if process is not None and held_fd is not None and process.poll() is None:
                    signal.pidfd_send_signal(held_fd, signal.SIGKILL)
                    process.wait(timeout=5)
                raise
            finally:
                if held_fd is not None:
                    os.close(held_fd)
                os.close(incoming)
                os.close(outgoing)
        require(process is not None and process.returncode == 0 and closed and not children(), 'worker closure failed')
        receipt = read_json(output / name / 'result.json')
        valid = False
        error = None
        try:
            validate_case(receipt, case, mode, process.pid, events)
            valid = True
        except ValueError as failure:
            error = str(failure)
        atomic(output / (name + '.ipc.json'), dict(command=command, pid=process.pid, events=events, validation_error=error))
        first_hash = inventory(output / name)
        require(first_hash == inventory(output / name), 'closed task tree changed')
        atomic(output / (name + '.closed-manifest.json'), first_hash)
        index['cases'].append(dict(case=name, pid=process.pid, terminal=True, exit=process.returncode,
            owned_closed=closed, streams_closed=log.closed, pidfd_closed=True, forced_cleanup=False, validated=valid))
        if not valid:
            break
    source_after = git_identity(args.source_checkout, (SOURCE_COMMIT, SOURCE_TREE))
    controller_after = git_identity(controller_root)
    require(source_after['filesystem'] == source_before['filesystem'] and controller_after['filesystem'] == controller_before['filesystem'],
            'source or controller filesystem changed')
    atomic(output / 'source-after.json', source_after)
    atomic(output / 'controller-after.json', controller_after)
    index.update(closed=True, streams_closed=True, controller_children=children())
    if len(index['cases']) == 21 and all(case['validated'] for case in index['cases']):
        index['status'] = 'PASS'
    validate_index(index)
    atomic(output / 'final-custody-index.json', index)
    if index['status'] == 'PASS':
        atomic(output / 'PASS.json', dict(kind='real OS controls; synthetic compiler data only', cases=21, mode=mode))
    require(index['status'] == 'PASS', 'OS controls failed; closed diagnostics retained')


def upload_gate(root):
    root = Path(root)
    indices = []
    for mode in ('normal', 'optimized'):
        directory = root / mode
        if not directory.exists():
            continue
        index = read_json(directory / 'final-custody-index.json')
        validate_index(index)
        require(index['mode'] == mode, 'custody mode differs')
        for closed in index['cases']:
            case = next(case for case in CASES if case[0] == closed['case'])
            ipc = read_json(directory / (case[0] + '.ipc.json'))
            require(ipc['pid'] == closed['pid'], 'custody worker identity differs')
            require(inventory(directory / case[0]) == read_json(directory / (case[0] + '.closed-manifest.json')),
                    'closed worker filesystem changed')
            if closed['validated']:
                validate_case(read_json(directory / case[0] / 'result.json'), case, mode, closed['pid'], ipc['events'])
        indices.append(index)
    require(indices, 'no explicit closure index')
    return indices


def main():
    validate_registry()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-checkout', type=Path)
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument('--source-only', action='store_true')
    choices.add_argument('--real-os', type=Path)
    choices.add_argument('--upload-gate', type=Path)
    choices.add_argument('--worker-output', type=Path)
    choices.add_argument('--fixture', choices=('host', 'probe', 'working', 'descendant'))
    parser.add_argument('--case', choices=[case[0] for case in CASES])
    parser.add_argument('--input-fd', type=int)
    parser.add_argument('--output-fd', type=int)
    parser.add_argument('--fixture-source')
    parser.add_argument('--fixture-output')
    parser.add_argument('--target')
    args = parser.parse_args()
    if args.source_only:
        print(json.dumps(source_only_check(args.source_checkout), sort_keys=True))
    elif args.upload_gate:
        upload_gate(args.upload_gate)
        print('closed=true')
    elif args.fixture:
        fixture_process(args)
    elif args.worker_output:
        worker(args)
    else:
        controller(args)


if __name__ == '__main__':
    main()
