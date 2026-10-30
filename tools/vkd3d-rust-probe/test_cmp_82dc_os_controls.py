"""Guarded source/data checks. These synthetic receipts are never real OS acceptance."""
import ast
import builtins
import copy
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]
DENIED = []
DENIED_KERNEL = []
FIXTURE_WRITES = {}
if 'CMP_PHYSICAL_FIXTURE' not in os.environ:
    if os.environ.get('GITHUB_ACTIONS') != 'true' or 'RUNNER_TEMP' not in os.environ:
        raise RuntimeError('provide owned CMP_PHYSICAL_FIXTURE for local source/data checks')
    fixture_root = Path(os.environ['RUNNER_TEMP']) / ('cmp-physical-data-' + str(os.getpid()))
    if fixture_root.exists() or fixture_root.is_symlink():
        raise RuntimeError('hosted inert fixture must be new')
    FIXTURE_WRITES = {str(fixture_root / name): operation for operation, names in (
        ('os.mkdir', ('', '.git', 'nested', 'nested/.git')),
        ('open', ('.git/config', 'nested/.git/hidden', 'file')),
        ('os.symlink', ('link',))) for name in names}


def deny_effects(event, args):
    blocked = event in ('subprocess.Popen', 'os.system', 'os.fork', 'os.posix_spawn', 'socket.__new__',
                        'socket.connect', 'socket.bind', 'ctypes.dlopen', 'ctypes.dlsym', 'os.mkdir',
                        'os.remove', 'os.rename', 'os.rmdir', 'os.chmod', 'os.symlink', 'os.link')
    if event == 'open':
        mode, flags = args[1:3]
        blocked = (isinstance(mode, str) and any(letter in mode for letter in 'wax+')) or (
            isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
    if blocked and FIXTURE_WRITES:
        target = args[1] if event == 'os.symlink' else args[0]
        if FIXTURE_WRITES.get(str(target)) == event:
            if event != 'os.symlink' or args[0] == '../outside-missing':
                return
    if blocked:
        DENIED.append(event)
        raise PermissionError('source/data check denies ' + event)


sys.addaudithook(deny_effects)
def deny_kernel(name):
    def denied(*args, **kwargs):
        DENIED_KERNEL.append(name)
        raise PermissionError('source/data check denies ' + name)
    return denied


for namespace, names in ((signal, ('signal', 'pthread_sigmask', 'sigpending', 'sigtimedwait', 'pidfd_send_signal',
                                   'raise_signal', 'pthread_kill', 'sigwait', 'sigwaitinfo')),
                         (os, ('pidfd_open', 'kill', 'killpg', 'waitpid', 'setsid', 'setpgid', 'set_blocking'))):
    for name in names:
        if hasattr(namespace, name):
            setattr(namespace, name, deny_kernel(name))
sys.setprofile = deny_kernel('sys.setprofile')
sys.settrace = deny_kernel('sys.settrace')
if hasattr(sys, 'monitoring'):
    for name in ('use_tool_id', 'free_tool_id', 'set_events', 'set_local_events', 'register_callback'):
        setattr(sys.monitoring, name, deny_kernel('sys.monitoring.' + name))
if FIXTURE_WRITES:
    fixture_root.mkdir()
    (fixture_root / '.git').mkdir()
    (fixture_root / 'nested').mkdir()
    (fixture_root / 'nested/.git').mkdir()
    for name in ('.git/config', 'nested/.git/hidden', 'file'):
        with (fixture_root / name).open('xb') as stream:
            stream.write(b'inert data')
    (fixture_root / 'link').symlink_to('../outside-missing')
    FIXTURE_WRITES.clear()
    os.environ['CMP_PHYSICAL_FIXTURE'] = str(fixture_root)
spec = importlib.util.spec_from_file_location('os_controls_data_only', HERE / 'check_cmp_82dc_os_controls.py')
controls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)
if DENIED_KERNEL:
    raise RuntimeError('harness import attempted kernel operation')


EXPECTED_CASES = (
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


def legal_case(case, mode='normal', pid=100):
    name, phase, first, second = case
    counts = dict(normalize=0, invoke=0, execute_body=0, popen=0, retain=0, finish=0, close=0)
    receipt = dict(case=name, phase=phase, first=first, second=second, mode=mode, pid=pid,
        source=controls.SOURCE_COMMIT, tree=controls.SOURCE_TREE,
        status='PASS', runtime=[3, 12, 3], children=[], writer_none=True, pidfds_closed=True,
        subprocesses_reaped=True, streams_closed=True, caller_restored=True, post_handoff_io=[],
        observer_closed=True, wait_hook_restored=True,
        adapters=list(controls.ADAPTERS), handlers=[], kernel=[], counts=counts, custody=[],
        caller_deliveries=[], refusal_before=None, refusal_after=None)
    receipt.update(native_fds_before={'0': '/dev/null'}, native_fds_after={'0': '/dev/null'})
    receipt['wait_identity'] = {name: dict(ast_sha256=identity, source_sha256='a' * 64,
        code_sha256='b' * 64, filename='/inert/subprocess.py', firstlineno=1)
        for name, identity in controls.WAIT_AST.items()}
    receipt['wait_identity']['module'] = dict(path='/inert/subprocess.py', sha256='c' * 64)
    events = []
    def event(kind, **data):
        events.append(dict(kind=kind, pid=pid, seq=1 + sum(e['kind'] != 'send' and e['pid'] == pid for e in events), **data))
    def send(sig):
        events.append(dict(kind='send', pid=pid, signal=sig, pidfd_retained=True))
    def handler(sig, owner_phase):
        record = dict(signal=sig, phase=owner_phase, cancelled=True, owner=7, handler=len(receipt['handlers']) + 1)
        receipt['handlers'].append(record)
        event('handler-return', case=name, **record)
    if phase == 'baseline':
        counts.update(popen=3, invoke=3, normalize=2)
        receipt['custody'] = [dict(pid=writer, custody_status='clean') for writer in (200, 201, 202)]
        for writer in (200, 201, 202):
            event('wait-enter', writer=writer, phase='working')
    elif phase.startswith('caller-'):
        pending = phase == 'caller-pending'
        state = dict(mask=[first, 10], pending=[first] if pending else [], handlers={'2': 1, '15': 2})
        receipt.update(refusal_before=state, refusal_after=copy.deepcopy(state), caller_deliveries=[first] if pending else [])
        if pending:
            event('caller-pending-ready', signal=first)
            send(first)
    else:
        expected = (0, 0) if phase == 'entry' else ((2, 1) if phase == 'working-cleanup' else (3, 2))
        counts.update(popen=expected[0], normalize=expected[1])
        first_phase = 'installing' if phase == 'entry' else ('working' if phase == 'working-cleanup' else 'finishing')
        if phase == 'working-cleanup':
            event('wait-enter', writer=200, phase='working')
            event('wait-enter', writer=201, phase='working')
            events.append(dict(kind='writer-ready', seq=1, pid=201, primary=201, descendant=202,
                               session=201, descendant_session=202))
            receipt['custody'] = [dict(pid=200, owned_descendants_reaped=[]),
                dict(pid=201, owned_descendants_reaped=[dict(pid=201, session=201), dict(pid=202, session=202)])]
        else:
            if phase != 'entry':
                for writer in (200, 201, 202):
                    event('wait-enter', writer=writer, phase='working')
                    receipt['custody'].append(dict(pid=writer, custody_status='clean'))
            event('ready-first', phase=first_phase, blocked=phase == 'entry')
        send(first)
        handler(first, first_phase)
        ready_phase = 'closing' if phase == 'working-cleanup' else first_phase
        event('ready-second', phase=ready_phase, masked=phase == 'published-masked', pending=[], owner=7, case=name)
        send(second)
        if phase == 'entry':
            receipt['kernel'].append(dict(point='entry-first', pending=[first]))
        receipt['kernel'].append(dict(point='second-after-send', pending=[second] if phase == 'published-masked' else []))
        if phase == 'published-masked':
            receipt['kernel'].append(dict(point='original-sigtimedwait', requested=[second], consumed=second, pending=[]))
        else:
            handler(second, ready_phase)
    event('worker-closed', case=name, owned_closed=True)
    return receipt, events


def legal_index():
    return dict(schema=1, source=controls.SOURCE_COMMIT, tree=controls.SOURCE_TREE, mode='normal', status='PASS',
        closed=True, controller_children=[], streams_closed=True, cases=[dict(case=case[0], pid=100 + i,
        terminal=True, exit=0, owned_closed=True, streams_closed=True, pidfd_closed=True, forced_cleanup=False,
        validated=True) for i, case in enumerate(EXPECTED_CASES)])


def handoff_ast_fixture():
    harness_path = HERE / 'check_cmp_82dc_os_controls.py'
    product_path = HERE / 'run_cmp_input.py'
    harness = ast.parse(harness_path.read_text())
    product = ast.parse(product_path.read_text())
    worker = next(node for node in harness.body if isinstance(node, ast.FunctionDef) and node.name == 'worker_body')
    nested = {node.name: node for node in worker.body if isinstance(node, ast.FunctionDef)}
    owner_class = next(node for node in product.body if isinstance(node, ast.ClassDef) and node.name == 'WrapperRun')
    reads, events = [], []
    state = dict(text='', error=None, event='open')
    namespace = dict(require=controls.require, sys=sys, handoff=True, module_file=str(product_path),
                     fs_after_handoff=events, os=SimpleNamespace(getpid=lambda: 123))

    class InertPath:
        def __init__(self, name):
            controls.require(name == '/proc/self/task/123/children', 'unexpected child observation identity')
            self.name = name

        def read_text(self):
            reads.append(self.name)
            namespace['audit'](state['event'], (self.name, 'r', 0))
            if state['error'] is not None:
                raise state['error']
            return state['text']

    namespace['Path'] = InertPath
    def execute(nodes, filename):
        tree = ast.fix_missing_locations(ast.Module(body=copy.deepcopy(nodes), type_ignores=[]))
        exec(compile(tree, str(filename), 'exec'), namespace)
    execute([nested['audit']], harness_path)
    execute([node for node in harness.body if isinstance(node, ast.FunctionDef) and node.name == 'children'], harness_path)
    namespace['signal'] = SimpleNamespace(SIGINT=2, SIGTERM=15)
    execute([owner_class] + [node for node in product.body if isinstance(node, ast.FunctionDef)
                            and node.name == 'owned_children'], product_path)
    owner = namespace['WrapperRun']()
    namespace.update(owner=owner, wrapper=SimpleNamespace(WrapperRun=namespace['WrapperRun']))
    attempt = next(node for node in worker.body if isinstance(node, ast.Try))
    closure = next(index for index, node in enumerate(attempt.body) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == 'observed_children' for target in node.targets))
    statements = attempt.body[closure:closure + 2]
    controls.require(ast.unparse(statements[0]) == 'observed_children = children()', 'closure sample differs')
    controls.require(ast.unparse(statements[1]) ==
        "require(not observed_children and owner.writer is None, 'owned closure unproven')", 'closure predicate differs')
    receipt_call = next(node for node in ast.walk(attempt) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name) and node.func.id == 'dict'
                        and any(keyword.arg == 'caller_deliveries' for keyword in node.keywords))
    receipt_children = next(keyword for keyword in receipt_call.keywords if keyword.arg == 'children')
    receipt = ast.Assign(targets=[ast.Name(id='receipt', ctx=ast.Store())],
        value=ast.Call(func=ast.Name(id='dict', ctx=ast.Load()), args=[], keywords=[copy.deepcopy(receipt_children)]))
    def observe():
        execute(statements + [receipt], harness_path)
        return namespace['receipt']
    return SimpleNamespace(namespace=namespace, owner=owner, state=state, reads=reads, events=events,
                           observe=observe, execute=execute, profile=nested['profile'], product_path=product_path,
                           harness_path=harness_path)


def second_ack_fixture(events, pending, *, masked=False, old=False):
    deliver_second = len(events) == 2
    events[:] = [dict(signal=2)]
    tree = ast.parse((HERE / 'check_cmp_82dc_os_controls.py').read_text())
    worker = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'worker_body')
    pause = next(node for node in worker.body if isinstance(node, ast.FunctionDef) and node.name == 'pause_second')
    if old:
        pause.body[-1].orelse = ast.parse("require(len(handler_events) == 2 and not set(owner.signals) & set(pending), 'second handler ACK missing')").body
    factory = ast.parse('def make_pause():\n    second_rendezvous = False\n    return pause_second\n').body[0]
    factory.body.insert(1, copy.deepcopy(pause))
    queries, diagnostics, kernel = [], [], []
    owner = SimpleNamespace(signals=(2, 15), phase='installing')
    def query():
        queries.append(len(queries))
        return set() if len(queries) <= 2 else set(pending)
    def continuation(*args, **kwargs):
        if deliver_second:
            events.append(dict(signal=15))
        return dict(kind='continue')
    namespace = dict(require=controls.require, handler_events=events, first=2, second=15, phase='entry',
        real={'pending': query}, channel=SimpleNamespace(send=lambda *args, **kwargs: None, receive=continuation), owner=owner,
        complete_handlers=lambda: None, state={},
        args=SimpleNamespace(case='entry-2-15'), kernel_events=kernel,
        second_ack_snapshot=controls.second_ack_snapshot, second_ack_diagnostic=diagnostics.append,
        sys=SimpleNamespace(implementation=SimpleNamespace(name='cpython'), version='inert-version',
                            executable='/inert/python', flags=SimpleNamespace(optimize=0)))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[factory], type_ignores=[])), '<inert-second-ack>', 'exec'), namespace)
    return SimpleNamespace(run=lambda: namespace['make_pause']()(masked), queries=queries,
                           diagnostics=diagnostics, kernel=kernel, events=events)


class SourceDataTests(unittest.TestCase):
    def test_actual_wait_hook_delegates_once_and_preserves_unwind(self):
        tree = ast.parse((HERE / 'check_cmp_82dc_os_controls.py').read_text())
        worker = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'worker_body')
        hook = next(node for node in worker.body if isinstance(node, ast.FunctionDef) and node.name == 'low_wait')
        wait = lambda: None
        process = SimpleNamespace(pid=123)
        frame = SimpleNamespace(f_code=wait.__code__, f_locals={'self': process})
        sends, invocations = [], []
        def original(child, timeout):
            self.assertIs(child, process)
            invocations.append(timeout)
            if timeout == 2:
                raise KeyboardInterrupt('genuine wait unwind')
            return 17
        namespace = dict(sys=SimpleNamespace(_getframe=lambda depth: frame), require=controls.require,
            real={'wait': wait, 'low_wait': original}, processes=[process], wait_frames=[],
            channel=SimpleNamespace(send=lambda *args, **kwargs: sends.append((args, kwargs))),
            owner=SimpleNamespace(phase='working'))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[hook], type_ignores=[])), '<inert-wait-hook>', 'exec'), namespace)
        self.assertEqual(namespace['low_wait'](process, 1), 17)
        with self.assertRaisesRegex(KeyboardInterrupt, 'genuine wait unwind'):
            namespace['low_wait'](process, 2)
        self.assertEqual(invocations, [1, 2])
        self.assertEqual(sends, [(('wait-enter',), dict(writer=123, phase='working'))])
        frame.f_locals['self'] = object()
        with self.assertRaisesRegex(ValueError, 'wait caller identity differs'):
            namespace['low_wait'](process, 3)
        self.assertEqual(invocations, [1, 2])

    def test_blocked_first_and_caller_pending_do_not_wait_for_handler_ack(self):
        tree = ast.parse((HERE / 'check_cmp_82dc_os_controls.py').read_text())
        controller = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'controller')
        branch = next(node for node in ast.walk(controller) if isinstance(node, ast.If)
                      and ast.unparse(node.test) == "kind in ('ready-first', 'caller-pending-ready')")
        for phase in ('entry', 'caller-pending'):
            sends, instructions = [], []
            exec(compile(ast.fix_missing_locations(ast.Module(body=copy.deepcopy(branch.body), type_ignores=[])),
                         '<inert-blocked-first>', 'exec'), dict(first=2, send=sends.append,
                         channel=SimpleNamespace(send=instructions.append)))
            self.assertEqual((sends, instructions), ([2], ['continue']))

    def test_old_profile_counterexample_has_no_new_completion_evidence(self):
        original = controls.sys
        try:
            owner = SimpleNamespace(cancelled=True, signals=(2, 15))
            controls.sys = SimpleNamespace(_getframe=lambda depth: None)
            observer = controls.HandlerObserver(owner, (lambda: None).__code__, {}, {}, {}, lambda: False)
            self.assertEqual(observer.complete(), [])
            with self.assertRaises(ValueError):
                controls.second_readiness(dict(kind='ready-second', case='entry-2-2', pid=100, seq=4,
                    owner=id(owner), phase='installing', masked=False, pending=[]), None, EXPECTED_CASES[1], 100)
        finally:
            controls.sys = original

    def test_monitoring_mainline_completion_requires_actual_start_identity_exit_and_latch(self):
        code, other = (lambda: None).__code__, (lambda value: value).__code__
        original = controls.sys
        try:
            for mutation in ('legal', 'start-only', 'on-stack', 'not-cancelled', 'owner', 'code', 'signum',
                             'overflow', 'missing-frame', 'changed-code', 'changed-owner', 'changed-signum', 'bound'):
                owner = SimpleNamespace(signals=(2, 15), phase='working', cancelled=False)
                frame = SimpleNamespace(f_code=code, f_locals=dict(self=owner, signum=2), f_back=None)
                current = [frame]
                controls.sys = SimpleNamespace(_getframe=lambda depth: current[0])
                observer = controls.HandlerObserver(owner, code, {}, {}, {}, lambda: False)
                if mutation == 'owner':
                    frame.f_locals['self'] = object()
                if mutation == 'signum':
                    frame.f_locals['signum'] = 10
                if mutation == 'missing-frame':
                    current[0] = SimpleNamespace(f_code=other, f_back=None)
                observer.start(other if mutation == 'code' else code, 0)
                if mutation == 'changed-code':
                    frame.f_code = other
                if mutation == 'changed-owner':
                    frame.f_locals['self'] = object()
                if mutation == 'changed-signum':
                    frame.f_locals['signum'] = 15
                if mutation == 'overflow':
                    observer.start(code, 0)
                    observer.start(code, 0)
                if mutation == 'start-only':
                    self.assertEqual(observer.receipted, 0)
                    continue
                owner.cancelled = mutation != 'not-cancelled'
                if mutation != 'on-stack':
                    current[0] = SimpleNamespace(f_code=other, f_back=None)
                if mutation == 'bound':
                    for unused in range(65):
                        current[0] = SimpleNamespace(f_code=other, f_back=current[0])
                if mutation in ('legal', 'on-stack'):
                    result = observer.complete()
                    self.assertEqual(len(result), int(mutation == 'legal'))
                    if result:
                        self.assertEqual(result[0], dict(signal=2, phase='working', cancelled=True, handler=1, owner=id(owner)))
                        self.assertEqual(observer.started, [])
                        self.assertEqual(observer.complete(), [])
                else:
                    with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                        observer.complete()
        finally:
            controls.sys = original

    def test_monitoring_scope_cleanup_order_and_existing_setup_refusal(self):
        original = controls.sys
        try:
            for preexisting in ('none', 'profile', 'trace', 'tool', 'callback'):
                calls, tools, local, callbacks = [], {}, {}, {}
                old_callback = lambda *args: None
                if preexisting == 'tool':
                    tools[3] = 'other-tool'
                if preexisting == 'callback':
                    callbacks[1] = old_callback
                def register(tool, event, callback):
                    calls.append(('callback', callback))
                    previous = callbacks.get(event)
                    callbacks[event] = callback
                    return previous
                def use(tool, name):
                    calls.append(('use', tool))
                    tools[tool] = name
                def free(tool):
                    calls.append(('free', tool))
                    tools.pop(tool)
                def set_local(tool, code, event):
                    calls.append(('local', code, event))
                    local[code] = event
                monitoring = SimpleNamespace(events=SimpleNamespace(PY_START=1), get_tool=tools.get,
                    get_events=lambda tool: 0, get_local_events=lambda tool, code: local.get(code, 0),
                    use_tool_id=use, free_tool_id=free, register_callback=register,
                    set_events=lambda tool, value: calls.append(('global', value)), set_local_events=set_local)
                controls.sys = SimpleNamespace(monitoring=monitoring, getprofile=lambda: preexisting == 'profile' or None,
                    gettrace=lambda: preexisting == 'trace' or None)
                observer = controls.HandlerObserver(object(), (lambda: None).__code__, {}, {}, {}, lambda: False)
                if preexisting == 'none':
                    observer.enable()
                    self.assertEqual(list(local.values()), [1])
                    observer.close()
                    self.assertEqual(list(local.values()), [0])
                    self.assertIsNone(callbacks[1])
                    self.assertEqual(calls[-1], ('free', 3))
                else:
                    with self.assertRaises(ValueError):
                        observer.enable()
                    if preexisting == 'callback':
                        self.assertIs(callbacks[1], old_callback)
                    else:
                        self.assertEqual(calls, [])
        finally:
            controls.sys = original

    def test_controller_actual_second_branches_require_completion_before_continue(self):
        tree = ast.parse((HERE / 'check_cmp_82dc_os_controls.py').read_text())
        controller = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'controller')
        branches = {kind: next(node for node in ast.walk(controller) if isinstance(node, ast.If)
                    and ast.unparse(node.test) == "kind == '" + kind + "'").body
                    for kind in ('ready-second', 'handler-return')}
        def execute(kind, namespace):
            exec(compile(ast.fix_missing_locations(ast.Module(body=copy.deepcopy(branches[kind]), type_ignores=[])),
                         '<inert-controller-branch>', 'exec'), namespace)
        for case in (EXPECTED_CASES[1], EXPECTED_CASES[5], EXPECTED_CASES[13]):
            receipt, events = legal_case(case)
            first_ack = next(e for e in events if e['kind'] == 'handler-return')
            ready = next(e for e in events if e['kind'] == 'ready-second')
            sends, continuations = [], []
            namespace = dict(require=controls.require, validate_completion=controls.validate_completion,
                second_readiness=controls.second_readiness, first_sent=True, second_sent=False,
                completions=[first_ack], case=case, name=case[0], phase=case[1], first=case[2], second=case[3],
                process=SimpleNamespace(pid=100), send=sends.append,
                channel=SimpleNamespace(send=continuations.append), event=ready)
            execute('ready-second', namespace)
            self.assertEqual(sends, [case[3]])
            masked = case[1] == 'published-masked'
            self.assertEqual(continuations, ['continue'] if masked else [])
            if not masked:
                second_ack = [e for e in events if e['kind'] == 'handler-return'][1]
                for field, wrong in (('pid', 101), ('owner', 8), ('signal', 10), ('handler', 1),
                                     ('case', 'wrong'), ('phase', 'wrong')):
                    namespace['event'] = dict(second_ack, **{field: wrong})
                    with self.subTest(field=field), self.assertRaises(ValueError):
                        execute('handler-return', namespace)
                    self.assertEqual(continuations, [])
                namespace['event'] = second_ack
                execute('handler-return', namespace)
                self.assertEqual(continuations, ['continue'])
                with self.assertRaises(ValueError):
                    execute('handler-return', namespace)
            with self.assertRaises(ValueError):
                execute('ready-second', namespace)

    def test_frozen_failure_sample_encoder_schema_and_parent_branch(self):
        kernel_sample = controls.second_ack_snapshot([dict(signal=2)], [signal.SIGTERM], 2, 15,
            'entry', 'installing', 'entry-2-15', ('cpython', 'v', 'p', 0))
        self.assertIs(kernel_sample.pending[0], signal.SIGTERM)
        encoded = controls.encode_worker_error('entry-2-15', 100, 4, 'execute', 'ValueError', 'failed', 'trace', kernel_sample)
        normalized = json.loads(encoded)
        self.assertTrue(controls.validate_worker_error(normalized, 'entry-2-15', 100, 4))
        self.assertEqual(normalized['second_ack_failure']['pending'], [15])
        self.assertIs(type(normalized['second_ack_failure']['pending'][0]), int)
        self.assertIs(kernel_sample.pending[0], signal.SIGTERM)
        for wrong in (True, '15', 15.0, object()):
            with self.assertRaises(ValueError):
                controls.encode_worker_error('entry-2-15', 100, 4, 'execute', 'ValueError', 'failed', 'trace',
                    kernel_sample._replace(pending=(wrong,)))
        events, pending = [dict(signal=2)], [15]
        sample = controls.second_ack_snapshot(events, pending, 2, 15, 'entry', 'installing', 'entry-2-15',
            ('cpython', '\U0001f600' * 1000, '/inert/python', 0))
        events.append(dict(signal=15))
        pending.clear()
        raw = controls.encode_worker_error('entry-2-15', 100, 4, 'execute', '\U0001f600' * 1000,
            '\U0001f600' * 10000, '\U0001f600' * 10000, sample)
        self.assertLess(len(raw), 4096)
        event = json.loads(raw)
        self.assertTrue(controls.validate_worker_error(event, 'entry-2-15', 100, 4))
        self.assertEqual(event['second_ack_failure']['signals'], [2])
        self.assertEqual(event['second_ack_failure']['pending'], [15])
        for mutate in (lambda r: r.update(extra=1), lambda r: r.update(count=True),
                       lambda r: r.update(pair=[15, 2]), lambda r: r.update(owner_phase='working'),
                       lambda r: r.update(signals=[10]), lambda r: r.update(pending=[15, 15]),
                       lambda r: r.update(signals_omitted=1), lambda r: r.update(interpreter=['x'])):
            malformed = copy.deepcopy(event)
            mutate(malformed['second_ack_failure'])
            with self.assertRaises(ValueError):
                controls.validate_worker_error(malformed, 'entry-2-15', 100, 4)
        tree = ast.parse((HERE / 'check_cmp_82dc_os_controls.py').read_text())
        controller = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'controller')
        branch = next(node for node in ast.walk(controller) if isinstance(node, ast.If)
                      and ast.unparse(node.test) == "kind == 'worker-error'")
        logged = []
        with self.assertRaisesRegex(ValueError, 'owned closure unproven'):
            exec(compile(ast.fix_missing_locations(ast.Module(body=copy.deepcopy(branch.body), type_ignores=[])),
                '<inert-parent-error>', 'exec'), dict(event=event, events=[dict(kind='ready-first', pid=100)] * 3 + [event],
                process=SimpleNamespace(pid=100), name='entry-2-15', mode='normal',
                validate_worker_error=controls.validate_worker_error,
                diagnostic=lambda label, **data: logged.append(data)))
        self.assertEqual(logged[0]['second_ack_failure'], event['second_ack_failure'])

    def test_monitoring_admission_workflow_is_required_before_both_actual_modes(self):
        workflow = (SOURCE / '.github/workflows/vkd3d-cmp-os-controls.yml').read_text()
        self.assertEqual(workflow.count('--monitoring-observer-control'), 2)
        self.assertLess(workflow.index('Hosted code-local monitoring admission'), workflow.index('Actual normal OS controls'))
        self.assertIn("steps.monitoring.outcome == 'success'", workflow)
        tree = ast.parse((HERE / 'check_cmp_82dc_os_controls.py').read_text())
        observer = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'HandlerObserver')
        start = next(node for node in observer.body if isinstance(node, ast.FunctionDef) and node.name == 'start')
        calls = [ast.unparse(node.func) for node in ast.walk(start) if isinstance(node, ast.Call)]
        self.assertFalse(any('channel' in call or 'json' in call or 'select' in call or 'wait' in call for call in calls))
        self.assertNotIn('PY_RETURN', ast.unparse(observer))
        self.assertNotIn('PY_UNWIND', ast.unparse(observer))

    def test_hosted_control_inert_missing_profile_events_refuses_and_restores(self):
        tree = ast.parse((HERE / 'check_cmp_82dc_os_controls.py').read_text())
        control = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'profiler_observer_control')
        registrations, reports = [], []
        inert_sys = SimpleNamespace(platform='linux', implementation=SimpleNamespace(name='cpython'),
            version_info=(3, 12, 3), version='inert-only', executable='/inert/python', flags=SimpleNamespace(optimize=0),
            getprofile=lambda: None, setprofile=registrations.append)
        namespace = dict(ast=ast, copy=copy, require=controls.require, SOURCE_COMMIT=controls.SOURCE_COMMIT,
            observer_definitions=controls.observer_definitions, sys=inert_sys,
            os=SimpleNamespace(environ={'GITHUB_ACTIONS': 'true'}), json=json,
            print=lambda value, **kwargs: reports.append(value))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[control], type_ignores=[])), '<inert-hosted-control>', 'exec'), namespace)
        with self.assertRaisesRegex(ValueError, 'genuine profiler observer counterexample differs'):
            namespace['profiler_observer_control'](SOURCE)
        self.assertEqual(len(registrations), 2)
        self.assertTrue(callable(registrations[0]))
        self.assertIsNone(registrations[1])
        report = json.loads(reports[0].split(' ', 1)[1])
        self.assertEqual((report['outside'], report['inside'], report['sends']), ([], [], []))
        self.assertEqual(report['identities']['product_sha256'], controls.FROZEN['run_cmp_input.py'])

    def test_second_ack_old_code_counterfactual_loses_deciding_evidence(self):
        for old in (False, True):
            fixture = second_ack_fixture([dict(signal=2)], [], old=old)
            with self.assertRaisesRegex(ValueError, '^second handler ACK missing$'):
                fixture.run()
            self.assertEqual(len(fixture.diagnostics), 0 if old else 1)
            self.assertEqual(len(fixture.queries), 3)

    def test_second_ack_snapshot_frozen_and_failure_decision_sampled_once(self):
        events, pending = [dict(signal=2)], []
        sample = controls.second_ack_snapshot(events, pending, 2, 15, 'entry', 'installing', 'entry-2-15', ('cpython', 'v', 'p', 0))
        events.append(dict(signal=15))
        pending.append(15)
        self.assertEqual((sample.count, sample.signals, sample.pending), (1, (2,), ()))
        with self.assertRaises(AttributeError):
            sample.count = 2
        fixture = second_ack_fixture([dict(signal=2)], [])
        with self.assertRaisesRegex(ValueError, '^second handler ACK missing$'):
            fixture.run()
        self.assertEqual(len(fixture.queries), 3)
        self.assertEqual(fixture.diagnostics, [sample._replace(interpreter=('cpython', 'inert-version', '/inert/python', 0))])
        self.assertEqual(fixture.kernel, [dict(point='second-after-send', pending=[])])

    def test_second_ack_pending_failure_and_success_keep_broad_predicate(self):
        for pending in ([], [15]):
            fixture = second_ack_fixture([dict(signal=2), dict(signal=15)], pending)
            if pending:
                with self.assertRaisesRegex(ValueError, '^second handler ACK missing$'):
                    fixture.run()
                self.assertEqual(fixture.diagnostics[0].signals, (2, 15))
                self.assertEqual(fixture.diagnostics[0].pending, (15,))
            else:
                fixture.run()
                self.assertEqual(fixture.diagnostics, [])
            self.assertEqual(len(fixture.queries), 3)

    def test_second_ack_diagnostic_bounds_and_original_failure_survives_output_error(self):
        class Stream:
            def __init__(self, fail=False):
                self.text, self.fail = '', fail
            def write(self, text):
                if self.fail:
                    raise OSError('inert stderr failure')
                self.text += text
            def flush(self):
                pass
        original = controls.sys.stderr
        sample = controls.second_ack_snapshot([dict(signal=2)] * 1000, list(range(1000)), 2, 15,
                                              'p' * 1000, 'p' * 1000, 'c' * 1000, ('v' * 1000,) * 4)
        try:
            stream = Stream()
            controls.sys.stderr = stream
            controls.second_ack_diagnostic(sample)
            self.assertLessEqual(len(stream.text), 4117)
            record = json.loads(stream.text.split(' ', 1)[1])
            self.assertEqual((record['count'], record['signals_omitted'], record['pending_omitted']), (1000, 992, 936))
            tree = ast.parse((HERE / 'check_cmp_82dc_os_controls.py').read_text())
            worker = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'worker_body')
            pause = next(node for node in worker.body if isinstance(node, ast.FunctionDef) and node.name == 'pause_second')
            decision = pause.body[-1].orelse
            controls.sys.stderr = Stream(fail=True)
            worker_state = {}
            with self.assertRaisesRegex(ValueError, '^second handler ACK missing$') as caught:
                exec(compile(ast.fix_missing_locations(ast.Module(body=copy.deepcopy(decision), type_ignores=[])), '<inert-decision>', 'exec'),
                    dict(sample=sample, second_ack_snapshot=lambda *args: sample, handler_events=[], pending=[],
                         state=worker_state,
                         first=2, second=15, phase='entry', owner=SimpleNamespace(signals=(2, 15), phase='installing'),
                         args=SimpleNamespace(case='entry-2-15'), sys=sys, require=controls.require,
                         second_ack_diagnostic=controls.second_ack_diagnostic))
            self.assertIsNone(caught.exception.__cause__)
            self.assertIs(worker_state['second_ack_failure'], sample)
        finally:
            controls.sys.stderr = original

    def test_hosted_observer_extracts_exact_genuine_definitions_without_execution(self):
        init, interrupt, profile, identities = controls.observer_definitions(SOURCE)
        product = ast.parse((HERE / 'run_cmp_input.py').read_text())
        owner = next(node for node in product.body if isinstance(node, ast.ClassDef) and node.name == 'WrapperRun')
        methods = {node.name: node for node in owner.body if isinstance(node, ast.FunctionDef)}
        self.assertEqual(ast.dump(init), ast.dump(methods['__init__']))
        self.assertEqual(ast.dump(interrupt), ast.dump(methods['interrupt']))
        self.assertEqual(identities['product_sha256'], controls.FROZEN['run_cmp_input.py'])
        self.assertEqual(identities['profile_ast_sha256'], controls.digest(ast.dump(profile).encode()))
        control = next(node for node in ast.parse((HERE / 'check_cmp_82dc_os_controls.py').read_text()).body
                       if isinstance(node, ast.FunctionDef) and node.name == 'profiler_observer_control')
        text = ast.unparse(control)
        self.assertIn('sys.setprofile(callback)', text)
        self.assertIn('sys.setprofile(None)', text)
        self.assertIn('owner.interrupt(15, None)', text)
        self.assertIn('owner.interrupt(2, None)', text)
        self.assertNotIn('signal.signal(', text)
        self.assertNotIn('load_source(', text)

    def test_hosted_observer_workflow_before_real_cases_and_both_modes(self):
        workflow = (SOURCE / '.github/workflows/vkd3d-cmp-os-controls.yml').read_text()
        self.assertLess(workflow.index('Hosted genuine profiler observer control'), workflow.index('Actual normal OS controls'))
        self.assertEqual(workflow.count('--profiler-observer-control'), 2)
        observer = workflow.split('- name: Hosted genuine profiler observer control', 1)[1].split('- name: Actual normal OS controls', 1)[0]
        self.assertIn('python3 -B -O ', observer)
        self.assertIn('--source-checkout "$GITHUB_WORKSPACE/source82dc"', observer)
        self.assertEqual(tuple(controls.CASES), EXPECTED_CASES)

    @classmethod
    def setUpClass(cls):
        controls.source_only_check(SOURCE)
        for mode in ('normal', 'optimized'):
            for case in EXPECTED_CASES:
                receipt, events = legal_case(case, mode)
                controls.validate_case(receipt, case, mode, 100, events)
        controls.validate_index(legal_index())

    def test_source_and_complete_legal_receipts_first(self):
        controls.source_only_check(SOURCE)
        self.assertEqual(tuple(controls.CASES), EXPECTED_CASES)
        for mode in ('normal', 'optimized'):
            for case in EXPECTED_CASES:
                receipt, events = legal_case(case, mode)
                self.assertTrue(controls.validate_case(receipt, case, mode, 100, events))
        self.assertTrue(controls.validate_index(legal_index()))

    def test_malformed_receipts_refuse(self):
        case = controls.CASES[1]
        legal, ordered = legal_case(case)
        controls.validate_case(legal, case, 'normal', 100, ordered)
        mutations = [
            lambda r, e: r.update(case='missing'),
            lambda r, e: r.update(mode='optimized'),
            lambda r, e: r.update(pid=101),
            lambda r, e: r.update(source='0' * 40),
            lambda r, e: r.update(status='SKIP'),
            lambda r, e: r.update(children=[123]),
            lambda r, e: r.update(streams_closed=False),
            lambda r, e: r['handlers'].pop(),
            lambda r, e: e.insert(0, e[0]),
            lambda r, e: e.reverse(),
            lambda r, e: e.pop(),
            lambda r, e: e.__setitem__(2, dict(e[2], pending=[case[2]])),
            lambda r, e: e.insert(0, e.pop(3)),
        ]
        for index, mutation in enumerate(mutations):
            receipt, events = copy.deepcopy(legal), copy.deepcopy(ordered)
            mutation(receipt, events)
            with self.subTest(index=index), self.assertRaises((ValueError, StopIteration)):
                controls.validate_case(receipt, case, 'normal', 100, events)

    def test_missing_duplicate_incomplete_false_closure_index(self):
        controls.validate_index(legal_index())
        mutations = [lambda x: x['cases'].pop(), lambda x: x['cases'].append(x['cases'][0]),
            lambda x: x.update(closed=False), lambda x: x.update(cases=[]),
            lambda x: x['cases'][0].update(forced_cleanup=True),
            lambda x: x['cases'][0].update(terminal=False),
            lambda x: x['cases'][0].update(validated=False),
            lambda x: x['cases'][0].update(exit=1), lambda x: x.update(mode='SKIP')]
        for index, mutation in enumerate(mutations):
            candidate = legal_index()
            mutation(candidate)
            with self.subTest(index=index), self.assertRaises(ValueError):
                controls.validate_index(candidate)
        with self.assertRaises((FileNotFoundError, ValueError)):
            controls.upload_gate(HERE / 'no-such-custody-index')

    def test_refusal_consumption_and_masked_callback_claim_refuse(self):
        case = controls.CASES[-1]
        receipt, events = legal_case(case)
        controls.validate_case(receipt, case, 'normal', 100, events)
        receipt['refusal_after']['pending'] = []
        with self.assertRaises(ValueError):
            controls.validate_case(receipt, case, 'normal', 100, events)
        case = next(case for case in controls.CASES if case[1] == 'published-masked')
        receipt, events = legal_case(case)
        controls.validate_case(receipt, case, 'normal', 100, events)
        receipt['kernel'][-1]['consumed'] = None
        with self.assertRaises(ValueError):
            controls.validate_case(receipt, case, 'normal', 100, events)

    def test_complete_ack_transcript_and_delivery_order(self):
        for case in EXPECTED_CASES[1:17]:
            legal, ordered = legal_case(case)
            controls.validate_case(legal, case, 'normal', 100, ordered)
            def second_ack(r, e):
                return next(event for event in reversed(e) if event['kind'] == 'handler-return')
            def move_ready(r, e):
                ready = next(event for event in e if event['kind'] == 'ready-second')
                e.remove(ready)
                e.insert(next(i for i, event in enumerate(e) if event['kind'] == 'handler-return'), ready)
            mutations = [
                ('unknown event', lambda r, e: second_ack(r, e).update(kind='unknown-ack')),
                ('handler transcript differs', lambda r, e: e.remove(second_ack(r, e))),
                ('handler transcript differs', lambda r, e: e.insert(e.index(second_ack(r, e)), dict(second_ack(r, e)))),
                ('handler transcript differs', lambda r, e: second_ack(r, e).update(owner=8)),
                ('handler transcript differs', lambda r, e: second_ack(r, e).update(signal=10)),
                ('handler transcript differs', lambda r, e: second_ack(r, e).update(phase='wrong')),
                ('handler transcript differs', lambda r, e: second_ack(r, e).update(handler=9)),
                ('handler transcript differs', lambda r, e: second_ack(r, e).pop('signal')),
                ('handler transcript differs', lambda r, e: second_ack(r, e).pop('owner')),
                ('handler transcript differs', lambda r, e: second_ack(r, e).pop('phase')),
                ('handler transcript differs', lambda r, e: second_ack(r, e).pop('handler')),
                ('handler transcript differs' if case[1] == 'published-masked' else 'handler owner/phase/latch/ordinal differs',
                 lambda r, e: r['handlers'][-1].update(owner=8)),
                ('handler owner/phase/latch/ordinal differs', lambda r, e: r['handlers'][-1].update(phase='wrong')),
                ('handler owner/phase/latch/ordinal differs', lambda r, e: r['handlers'][-1].update(handler=9)),
                ('handler signal order differs', lambda r, e: r['handlers'][-1].update(signal=10)),
                ('delivery event order differs', move_ready),
                ('delivery event order differs', lambda r, e: e.insert(0, e.pop(next(i for i, v in enumerate(e) if v['kind'] == 'ready-second')))),
                ('delivery event order differs', lambda r, e: e.insert(e.index(next(v for v in e if v['kind'] == 'ready-second')), dict(next(v for v in e if v['kind'] == 'ready-second')))),
                ('second readiness differs', lambda r, e: next(v for v in e if v['kind'] == 'ready-second').update(pending=[case[2]])),
                ('second readiness differs', lambda r, e: next(v for v in e if v['kind'] == 'ready-second').update(phase='working')),
                ('second readiness differs', lambda r, e: next(v for v in e if v['kind'] == 'ready-second').update(masked=case[1] != 'published-masked')),
                ('case/mode/PID identity differs', lambda r, e: r.update(phase='baseline')),
                ('two distinct sends required', lambda r, e: e.insert(e.index(next(v for v in e if v['kind'] == 'send')), dict(kind='send', signal=case[2], pid=100, pidfd_retained=True))),
            ]
            for error, mutate in mutations:
                receipt, events = copy.deepcopy(legal), copy.deepcopy(ordered)
                mutate(receipt, events)
                serial = 0
                for event in events:
                    if event['pid'] == 100 and event['kind'] != 'send':
                        serial += 1
                        event['seq'] = serial
                with self.subTest(case=case[0], error=error), self.assertRaisesRegex(ValueError, error):
                    controls.validate_case(receipt, case, 'normal', 100, events)

    def test_phase_specific_kernel_transcripts(self):
        for case in EXPECTED_CASES:
            legal, ordered = legal_case(case)
            controls.validate_case(legal, case, 'normal', 100, ordered)
            mutations = [lambda r: r['kernel'].append(dict(point='unknown', pending=[]))]
            if legal['kernel']:
                mutations += [lambda r: r['kernel'].pop(),
                              lambda r: r['kernel'].append(copy.deepcopy(r['kernel'][-1]))]
            if case[1] == 'entry':
                mutations += [lambda r: r['kernel'].reverse(),
                              lambda r: r['kernel'][0].update(pending=[])]
            if case[1] == 'published-masked':
                mutations += [lambda r: r['kernel'].reverse(),
                              lambda r: r['kernel'][0].update(pending=[]),
                              lambda r: r['kernel'][1].update(requested=[10]),
                              lambda r: r['kernel'][1].update(consumed=None),
                              lambda r: r['kernel'][1].update(pending=[case[3]])]
            elif legal['kernel']:
                mutations += [lambda r: r['kernel'][-1].update(pending=[case[3]])]
            for index, mutate in enumerate(mutations):
                receipt = copy.deepcopy(legal)
                mutate(receipt)
                with self.subTest(case=case[0], mutation=index), self.assertRaisesRegex(ValueError, 'kernel'):
                    controls.validate_case(receipt, case, 'normal', 100, ordered)
        case = EXPECTED_CASES[5]
        receipt, events = legal_case(case)
        writer = next(event for event in events if event['kind'] == 'writer-ready')
        events.remove(writer)
        events.insert(1, writer)
        self.assertTrue(controls.validate_case(receipt, case, 'normal', 100, events))
        for case in EXPECTED_CASES[1:17]:
            receipt, events = legal_case(case)
            next(event for event in events if event['kind'] == 'ready-second')['pending'] = [10]
            receipt['kernel'][-1]['pending'] = [10]
            self.assertTrue(controls.validate_case(receipt, case, 'normal', 100, events))
        for case in (EXPECTED_CASES[0], EXPECTED_CASES[5], EXPECTED_CASES[9]):
            legal, ordered = legal_case(case)
            def missing(r, e):
                e.remove(next(event for event in e if event['kind'] == 'wait-enter'))
            def extra(r, e):
                e.insert(0, dict(kind='wait-enter', pid=100, writer=200, phase='working'))
            def foreign(r, e):
                next(event for event in e if event['kind'] == 'wait-enter')['writer'] = 999
            for mutate in (missing, extra, foreign):
                receipt, events = copy.deepcopy(legal), copy.deepcopy(ordered)
                mutate(receipt, events)
                serial = 0
                for event in events:
                    if event['pid'] == 100 and event['kind'] != 'send':
                        serial += 1
                        event['seq'] = serial
                with self.assertRaisesRegex(ValueError, 'wait observation differs'):
                    controls.validate_case(receipt, case, 'normal', 100, events)

    def test_independent_exact_registry_and_index(self):
        self.assertEqual(tuple(controls.CASES), EXPECTED_CASES)
        controls.source_only_check(SOURCE)
        controls.validate_index(legal_index())
        mutations = [lambda rows: rows.pop(), lambda rows: rows.append(rows[0]),
            lambda rows: rows.__setitem__(4, ('entry-15-10', 'entry', 15, 10)),
            lambda rows: rows.__setitem__(4, ('entry-15-2', 'entry', 15, 10)),
            lambda rows: rows.__setitem__(4, ('foreign', 'entry', 15, 2)),
            lambda rows: rows.__setitem__(4, ('entry-15-2', 'foreign', 15, 2)),
            lambda rows: rows.__setitem__(4, rows[3]), lambda rows: rows.reverse()]
        original = controls.CASES
        for index, mutate in enumerate(mutations):
            candidate = list(EXPECTED_CASES)
            mutate(candidate)
            controls.CASES = candidate
            try:
                with self.subTest(mutation=index), self.assertRaisesRegex(ValueError, 'case registry differs'):
                    controls.source_only_check(SOURCE)
                followed = legal_index()
                followed['cases'] = [dict(followed['cases'][0], case=case[0]) for case in candidate]
                with self.subTest(index_mutation=index), self.assertRaisesRegex(ValueError, 'case registry differs'):
                    controls.validate_index(followed)
            finally:
                controls.CASES = original
        for mutate in (lambda rows: rows[4].update(case='entry-15-10'),
                       lambda rows: rows[4].update(case='entry-2-15'), lambda rows: rows.reverse()):
            candidate = legal_index()
            mutate(candidate['cases'])
            with self.assertRaises(ValueError):
                controls.validate_index(candidate)

    def test_no_import_time_probes_and_no_owner_patching(self):
        tree = ast.parse((HERE / 'check_cmp_82dc_os_controls.py').read_text())
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                self.fail('top-level function call before CLI selection')
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                self.fail('top-level runtime probe')
        source = (HERE / 'check_cmp_82dc_os_controls.py').read_text()
        self.assertNotIn('patch.object', source)
        self.assertNotIn('wrapper_patches(', source)
        self.assertNotIn('signal_custody_case(', source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    self.assertFalse(isinstance(target, ast.Attribute) and isinstance(target.value, ast.Attribute)
                                     and target.value.attr == 'WrapperRun', 'owner method assignment')

    def test_exact_command_adapter_allows_only_inert_host_and_two_probes(self):
        args = SimpleNamespace(artifacts=Path('/fixture/actual'), target='x86_64-unknown-linux-gnu',
            c2rust=Path('/fixture/tool/bin/c2rust'), clang=Path('/fixture/tool/bin/c2rust'),
            native_library=Path('/fixture/oracle.data'))
        here, script = Path('/tested/tools/vkd3d-rust-probe'), Path('/controller/harness.py')
        result = controls.fixture_command(['rustc', '+1.95.0', '-vV'], here, args, 1, 'baseline', script, True)
        self.assertEqual(result[:4], [sys.executable, '-B', '-O', str(script)])
        for ordinal, name in ((2, 'correct'), (3, 'opposite')):
            command = [sys.executable, '-B', str(here / 'probe.py'), '--source', str(args.artifacts / (name + '-input/source')),
                '--artifacts', str(args.artifacts / name), '--c2rust', str(args.c2rust), '--clang', str(args.clang),
                '--rust-toolchain', '1.95.0', '--all-unit-prototype', '--timeout', '1800', '--build-timeout', '300',
                '--native-library', str(args.native_library)]
            result = controls.fixture_command(command, here, args, ordinal, 'baseline', script, False)
            self.assertIn('probe', result)
            for candidate in (command + ['--extra'], ['sh', '-c', 'false'], command[:-1] + ['/wrong/library']):
                with self.assertRaises(ValueError):
                    controls.fixture_command(candidate, here, args, ordinal, 'baseline', script, False)
        with self.assertRaises(ValueError):
            controls.fixture_command(['rustc', '+1.95.0', '-vV'], here, args, 2, 'baseline', script, False)

    def test_four_actual_effect_denials(self):
        attempts = [lambda: builtins.open(HERE / 'must-not-create', 'w'),
                    lambda: os.mkdir(HERE / 'must-not-mkdir'),
                    lambda: subprocess.Popen([sys.executable, '-B', '-c', 'raise SystemExit(99)']),
                    lambda: socket.socket()]
        start = len(DENIED)
        for attempt in attempts:
            with self.assertRaises(PermissionError):
                attempt()
        self.assertEqual(len(DENIED) - start, 4)

    def test_kernel_apis_are_denied_before_harness_import(self):
        for operation in (lambda: signal.signal(signal.SIGINT, None), lambda: os.kill(os.getpid(), 0)):
            with self.assertRaises(PermissionError):
                operation()

    def test_complete_physical_git_tree_admission(self):
        raw = b'body'
        leaf = dict(kind='file', mode=0o644, size=4, sha256=controls.digest(raw), git_blob=controls.blob_oid(raw))
        target = '../outside-missing'
        link = dict(kind='symlink', mode=0o777, link=target, git_blob=controls.blob_oid(target.encode()))
        listing = (b'100644 blob ' + controls.blob_oid(raw).encode() + b'\tdir/file\0'
                   + b'120000 blob ' + link['git_blob'].encode() + b'\tlink\0')
        original = {'dir/': dict(kind='directory', mode=0o755), 'dir/file': leaf, 'link': link}
        self.assertTrue(controls.validate_git_filesystem(listing, original))
        mutations = [
            lambda x: x.update({'empty/': dict(kind='directory', mode=0o755)}),
            lambda x: x.update({'ignored-cache/': dict(kind='directory', mode=0o755)}),
            lambda x: x.update({'dir/.git/': dict(kind='directory', mode=0o755)}),
            lambda x: x.update({'dir/.git/hidden': dict(leaf)}),
            lambda x: x.pop('dir/'), lambda x: x.pop('dir/file'),
            lambda x: x.update(extra=dict(leaf)),
            lambda x: x['dir/'].update(mode=0o700),
            lambda x: x['dir/'].update(kind='symlink'),
            lambda x: x['dir/file'].update(kind='symlink'),
            lambda x: x['dir/file'].update(mode=0o755),
            lambda x: x['dir/file'].update(git_blob=controls.blob_oid(b'changed')),
            lambda x: x['link'].update(kind='file'),
            lambda x: x['link'].update(link='different'),
            lambda x: x['link'].update(mode=0o644),
        ]
        for index, mutate in enumerate(mutations):
            candidate = copy.deepcopy(original)
            mutate(candidate)
            with self.subTest(mutation=index), self.assertRaises(ValueError):
                controls.validate_git_filesystem(listing, candidate)
        for malformed in (listing[:-1], listing + listing, listing.replace(b'dir/file', b'../file'),
                          listing.replace(b'100644', b'160000')):
            with self.assertRaises(ValueError):
                controls.validate_git_filesystem(malformed, original)

    def test_inventory_keeps_git_members_without_following_links(self):
        fixture = Path(os.environ['CMP_PHYSICAL_FIXTURE'])
        members = controls.inventory(fixture)
        self.assertEqual(set(members), {'.git/', '.git/config', 'nested/', 'nested/.git/',
                                       'nested/.git/hidden', 'link', 'file'})
        self.assertEqual(members['link']['kind'], 'symlink')
        self.assertEqual(members['link']['link'], '../outside-missing')
        self.assertEqual(members['file']['kind'], 'file')
        checkout = controls.inventory(fixture, checkout_git_admin=True)
        self.assertEqual(set(checkout), set(members) - {'.git/', '.git/config'})
        for context in ('packet', 'closed-artifact'):
            with self.subTest(context=context):
                expected = {key: value for key, value in members.items() if '.git' not in key.split('/')}
                with self.assertRaises(ValueError):
                    controls.validate_seal(expected, members)

    def test_controller_exact_head_tree_and_github_sha(self):
        before = dict(head='a' * 40, tree='b' * 40, filesystem={'file': 'same'})
        self.assertTrue(controls.validate_checkout_pair(before, copy.deepcopy(before), ('a' * 40, 'b' * 40)))
        for candidate, expected in ((dict(before, head='c' * 40), ('a' * 40, 'b' * 40)),
                                    (dict(before, tree='c' * 40), ('a' * 40, 'b' * 40)),
                                    (dict(before), ('c' * 40, 'b' * 40)),
                                    (dict(before, filesystem={}), ('a' * 40, 'b' * 40))):
            with self.assertRaises(ValueError):
                controls.validate_checkout_pair(before, candidate, expected)

    def test_git_child_pid_utc_terminal_closed_stream_receipts(self):
        body = b'raw\0Git\xff'
        legal = dict(pid=123, argv=['git', 'cat-file', 'tree', 'a' * 40], cwd='/owned/checkout',
                     start='2026-10-30T00:00:00+00:00', end='2026-10-30T00:00:01+00:00',
                     terminal=True, exit=0, wait=0, failure=None,
                     streams={name: dict(closed=True, size=len(body), sha256=controls.digest(body), hex=body.hex())
                              for name in ('stdout', 'stderr')})
        self.assertTrue(controls.validate_git_receipt(legal))
        mutations = [lambda x: x.pop('pid'), lambda x: x.update(pid=True), lambda x: x.update(pid=0),
            lambda x: x.pop('start'), lambda x: x.update(start='not UTC'),
            lambda x: x.update(end='2026-10-29T00:00:00+00:00'),
            lambda x: x.update(start='2026-10-30T00:00:00'),
            lambda x: x.update(start='2026-10-30T01:00:00+01:00'),
            lambda x: x.update(terminal=False), lambda x: x.update(exit=1),
            lambda x: x.pop('wait'), lambda x: x.update(wait=1), lambda x: x.update(wait=False),
            lambda x: x.update(exit=False), lambda x: x.update(argv='git'), lambda x: x.update(cwd='relative'),
            lambda x: x.update(failure='timeout'), lambda x: x.pop('streams'),
            lambda x: x['streams']['stdout'].update(closed=False),
            lambda x: x['streams']['stderr'].update(closed=False),
            lambda x: x['streams']['stdout'].pop('hex'),
            lambda x: x['streams']['stderr'].update(hex='zz'),
            lambda x: x['streams']['stdout'].update(size=0),
            lambda x: x['streams']['stderr'].update(sha256=controls.digest(b'wrong'))]
        for index, mutate in enumerate(mutations):
            candidate = copy.deepcopy(legal)
            mutate(candidate)
            with self.subTest(mutation=index), self.assertRaises(ValueError):
                controls.validate_git_receipt(candidate)

    def test_bounded_worker_error_envelope(self):
        for stage in controls.ERROR_STAGES:
            raw = controls.encode_worker_error('baseline', 100, 1, stage, 'ValueError', 'failed', 'trace')
            self.assertLess(len(raw), 4096)
            event = json.loads(raw)
            self.assertTrue(controls.validate_worker_error(event, 'baseline', 100, 1))
            self.assertFalse(event['truncated'])
            self.assertEqual(event['message'], 'failed')
        for text in ('x' * 10000, '\u754c' * 10000, '\U0001f600' * 10000):
            raw = controls.encode_worker_error('baseline', 100, 1, 'execute', text, text, text)
            self.assertLess(len(raw), 4096)
            self.assertTrue(raw.endswith(b'\n'))
            event = json.loads(raw)
            self.assertTrue(event['truncated'])
            self.assertTrue(controls.validate_worker_error(event, 'baseline', 100, 1))
        with self.assertRaises(json.JSONDecodeError):
            json.loads(raw[:-2])

    def test_worker_error_malformed_identity_and_closure_refuse(self):
        legal = json.loads(controls.encode_worker_error('baseline', 100, 1, 'execute', 'ValueError', 'failed', 'trace'))
        controls.validate_worker_error(legal, 'baseline', 100, 1)
        mutations = [lambda x: x.pop('traceback'), lambda x: x.update(extra=True),
            lambda x: x.update(kind='worker-closed'), lambda x: x.update(case='entry-2-2'),
            lambda x: x.update(pid=101), lambda x: x.update(pid=True), lambda x: x.update(seq=2),
            lambda x: x.update(seq=True), lambda x: x.update(schema=True), lambda x: x.update(stage='invented'),
            lambda x: x.update(stage=[]), lambda x: x.update(truncated='yes'),
            lambda x: x.update(message='x' * 401), lambda x: x.update(traceback=42),
            lambda x: x.update(exception_type=''), lambda x: x.update(owned_closed=True),
            lambda x: x.update(traceback='\U0001f600' * 1800)]
        for mutate in mutations:
            candidate = copy.deepcopy(legal)
            mutate(candidate)
            with self.assertRaises(ValueError):
                controls.validate_worker_error(candidate, 'baseline', 100, 1)
        receipt, events = legal_case(EXPECTED_CASES[0])
        diagnostic = dict(legal, seq=events[-1]['seq'])
        for candidate in (events[:-1] + [diagnostic], events + [diagnostic]):
            with self.assertRaisesRegex(ValueError, 'unknown event'):
                controls.validate_case(receipt, EXPECTED_CASES[0], 'normal', 100, candidate)

    def test_eof_context_and_worker_source_boundaries(self):
        failure = ValueError('IPC closed before terminal message')
        context = controls.controller_context('normal', 'baseline', 100, [], failure)
        self.assertEqual(context['case'], 'baseline')
        self.assertIsNone(context['last_received'])
        self.assertIn('unavailable', context['worker_stage'])
        event = dict(kind='wait-enter', seq=3, pid=100, writer=200)
        context = controls.controller_context('optimized', 'entry-2-2', 100, [event], failure)
        self.assertEqual(context['last_received'], dict(kind='wait-enter', seq=3, pid=100))
        self.assertEqual(context['message'], 'IPC closed before terminal message')
        send = dict(kind='send', signal=15, pid=100, pidfd_retained=True)
        for history in ([send], [send, dict(send)]):
            context = controls.controller_context('normal', 'baseline', 100, history, failure)
            self.assertIsNone(context['last_received'])
        for kind in ('ready-first', 'ready-second'):
            received = dict(kind=kind, seq=7, pid=101, phase='finishing')
            for outgoing in ([send], [send, dict(send)]):
                for history in ([received] + outgoing, [send, event, send, received] + outgoing):
                    context = controls.controller_context('optimized', 'entry-2-15', 101, history, failure)
                    self.assertEqual(context['last_received'], dict(kind=kind, seq=7, pid=101))
        malformed = [dict(seq=1, pid=100), None, False, 0, 1.5, 'ready-first', [], [event], {},
                     dict(kind=None, seq=1, pid=100), dict(kind=[], seq=1, pid=100),
                     dict(kind='', seq=1, pid=100), dict(kind='ready-first', pid=100),
                     dict(kind='ready-first', seq=True, pid=100), dict(kind='ready-first', seq=1, pid='100'),
                     dict(kind='ready-first', seq=0, pid=100), dict(kind='ready-first', seq=1, pid=-1)]
        for value in malformed:
            for history in ([value], [send, value, send]):
                context = controls.controller_context('normal', 'baseline', 100, history, failure)
                self.assertIsNone(context['last_received'])
            for history in ([event, value], [send, event, send, value, send]):
                context = controls.controller_context('normal', 'baseline', 100, history, failure)
                self.assertEqual(context['last_received'], dict(kind='wait-enter', seq=3, pid=100))
        source = ast.parse((HERE / 'run_cmp_input.py').read_text())
        owner = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == 'WrapperRun')
        methods = {node.name: node for node in owner.body if isinstance(node, ast.FunctionDef)}
        self.assertEqual([arg.arg for arg in methods['__init__'].args.args], ['self'])
        self.assertEqual([arg.arg for arg in methods['execute'].args.args], ['self', 'args'])
        tree = ast.parse((HERE / 'check_cmp_82dc_os_controls.py').read_text())
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        wrapper = functions['worker']
        calls = [ast.unparse(node.func) for node in ast.walk(wrapper) if isinstance(node, ast.Call)]
        self.assertEqual(calls.count('os.write'), 1)
        self.assertNotIn('channel.send', calls)
        self.assertNotIn('select.select', calls)
        self.assertTrue(any(isinstance(node, ast.Raise) and node.exc is None for node in ast.walk(wrapper)))
        body = ast.unparse(functions['worker_body'])
        self.assertIn('wrapper.WrapperRun()', body)
        self.assertIn('owner.execute(product_args)', body)
        self.assertIn("state['stage'] = 'source-import'", body)
        self.assertIn("state['execute_error'] = error", body)

    def test_controller_diagnostic_failure_preserves_cleanup_and_error(self):
        tree = ast.parse((HERE / 'check_cmp_82dc_os_controls.py').read_text())
        controller = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'controller')
        handler = next(node for node in ast.walk(controller) if isinstance(node, ast.ExceptHandler)
                       and isinstance(node.type, ast.Name) and node.type.id == 'BaseException' and node.name == 'error')
        for original in (ValueError('original IPC failure'), KeyboardInterrupt(), SystemExit(7)):
            for stage in ('context', 'serialization', 'stderr'):
                for reporting in (None, ValueError('diagnostic failure'), KeyboardInterrupt(), SystemExit(9)):
                    with self.subTest(original=type(original).__name__, stage=stage, reporting=type(reporting).__name__):
                        calls = []
                        def fail_at(point):
                            calls.append(point)
                            if stage == point and reporting is not None:
                                raise reporting
                        def context(*args):
                            fail_at('context')
                            return {}
                        def diagnostic(*args, **kwargs):
                            fail_at('serialization')
                            fail_at('stderr')
                        def poll():
                            calls.append('poll')
                            return None
                        def kill(fd, sig):
                            self.assertEqual((fd, sig), (10, 9))
                            calls.append('kill')
                        def wait(timeout):
                            self.assertEqual(timeout, 5)
                            calls.append('wait')
                        namespace = dict(controller_context=context, diagnostic=diagnostic, mode='normal', name='baseline',
                            process=SimpleNamespace(pid=100, poll=poll, wait=wait), held_fd=10, events=[], original=original,
                            signal=SimpleNamespace(pidfd_send_signal=kill, SIGKILL=9))
                        attempt = ast.Try(body=[ast.Raise(exc=ast.Name(id='original', ctx=ast.Load()))],
                                          handlers=[copy.deepcopy(handler)], orelse=[], finalbody=[])
                        program = ast.fix_missing_locations(ast.Module(body=[attempt], type_ignores=[]))
                        expected = reporting if isinstance(reporting, (KeyboardInterrupt, SystemExit)) else original
                        with self.assertRaises(type(expected)) as raised:
                            exec(compile(program, '<controller-error-handler>', 'exec'), namespace)
                        self.assertIs(raised.exception, expected)
                        self.assertEqual(calls[-3:], ['poll', 'kill', 'wait'])

    def test_handoff_legal_observation_once_and_receipt_identity(self):
        fixture = handoff_ast_fixture()
        receipt = fixture.observe()
        self.assertEqual(receipt, dict(children=[]))
        self.assertIs(receipt['children'], fixture.namespace['observed_children'])
        self.assertEqual(fixture.reads, ['/proc/self/task/123/children'])
        self.assertEqual(fixture.events, [])
        fixture.state['text'] = '201 202\n'
        self.assertEqual(fixture.namespace['children'](), [201, 202])

    def test_handoff_old_product_reader_refuses_after_legal_baseline(self):
        fixture = handoff_ast_fixture()
        fixture.observe()
        with self.assertRaisesRegex(ValueError, 'wrapper filesystem I/O after confirmed handoff'):
            fixture.namespace['owned_children']()
        self.assertEqual(fixture.events, ['open'])
        fixture.namespace['handoff'] = False
        self.assertEqual(fixture.namespace['owned_children'](), [])

    def test_handoff_nonempty_writer_read_error_and_malformed_pid_refuse(self):
        for text, writer, error, expected in (
                ('201\n', None, None, ValueError), ('', object(), None, ValueError),
                ('', None, OSError('inert read failure'), OSError), ('bad-pid', None, None, ValueError)):
            with self.subTest(text=text, writer=writer, error=error):
                fixture = handoff_ast_fixture()
                fixture.observe()
                fixture.namespace.pop('receipt')
                fixture.state.update(text=text, error=error)
                fixture.owner.writer = writer
                with self.assertRaises(expected):
                    fixture.observe()
                self.assertNotIn('receipt', fixture.namespace)
                self.assertEqual(len(fixture.reads), 2)

    def test_handoff_product_same_path_helper_and_all_audit_events_refuse(self):
        for event in ('open', 'os.rename', 'os.remove', 'os.mkdir', 'os.rmdir', 'os.listdir', 'os.scandir'):
            for helper in ('owned_children', 'children'):
                with self.subTest(event=event, helper=helper):
                    fixture = handoff_ast_fixture()
                    fixture.observe()
                    fixture.state['event'] = event
                    fixture.owner.phase = 'working'
                    fixture.namespace['normalize'] = lambda *args, **kwargs: fixture.namespace[helper]()
                    with self.assertRaisesRegex(ValueError, 'wrapper filesystem I/O after confirmed handoff'):
                        fixture.owner.normalize(None)
                    self.assertEqual(fixture.events, [event])

    def test_handoff_profile_callback_product_io_remains_refused(self):
        fixture = handoff_ast_fixture()
        fixture.observe()
        namespace = fixture.namespace
        owner = fixture.owner
        owner.phase, owner.cancelled = 'working', True
        frame = SimpleNamespace(f_code=namespace['WrapperRun'].interrupt.__code__,
                                f_locals=dict(self=owner, signum=2))
        def send(*args, **kwargs):
            namespace['children']()
        namespace.update(cancelled_seen=False, handler_events=[], channel=SimpleNamespace(send=send),
            signal=SimpleNamespace(getsignal=lambda sig: owner.interrupt), counts={}, active={}, max_active={},
            in_followon=False, wait_code=None, processes=[])
        profile_factory = ast.FunctionDef(name='profile_factory', args=ast.arguments(
            posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=[
                ast.Assign(targets=[ast.Name(id='cancelled_seen', ctx=ast.Store())], value=ast.Constant(False)),
                copy.deepcopy(fixture.profile), ast.Return(value=ast.Name(id='profile', ctx=ast.Load()))],
            decorator_list=[])
        fixture.execute([profile_factory], fixture.harness_path)
        callback = namespace['profile_factory']()
        callback(frame, 'return', None)
        self.assertEqual(fixture.events, [])
        owner.cancelled = False
        def boundary(*args):
            owner.cancelled = True
            callback(frame, 'return', None)
        namespace['normalize'] = boundary
        with self.assertRaisesRegex(ValueError, 'wrapper filesystem I/O after confirmed handoff'):
            owner.normalize(None)
        self.assertEqual(fixture.events, ['open'])

    def test_handoff_genuine_followon_refuses_before_io(self):
        fixture = handoff_ast_fixture()
        fixture.observe()
        fixture.owner.cancelled = True
        for operation in (lambda: fixture.owner.normalize(None), lambda: fixture.owner.invoke([], None, None, 1)):
            with self.assertRaisesRegex(KeyboardInterrupt, 'Cancelled wrapper'):
                operation()
        self.assertEqual(fixture.reads, ['/proc/self/task/123/children'])
        self.assertEqual(fixture.events, [])

    def test_four_seal_negatives(self):
        original = {'a': {'mode': 292, 'size': 1, 'sha256': controls.digest(b'a')}}
        controls.validate_seal(original, copy.deepcopy(original))
        missing = {}
        extra = dict(original, extra={})
        corrupt = copy.deepcopy(original)
        corrupt['a']['sha256'] = controls.digest(b'b')
        mode = copy.deepcopy(original)
        mode['a']['mode'] = 420
        hidden = dict(original, **{'.git/': {'kind': 'directory', 'mode': 0o555}, '.git/hidden': {'size': 1}})
        empty = dict(original, **{'empty/': {'kind': 'directory', 'mode': 0o555}})
        nested_seal = dict(original, **{'nested/': {'kind': 'directory'}, 'nested/seal.json': {}})
        with self.assertRaises(ValueError):
            controls.validate_seal({}, {})
        for candidate in (missing, extra, corrupt, mode, hidden, empty, nested_seal):
            with self.assertRaises(ValueError):
                controls.validate_seal(original, candidate)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--sealed':
        packet = Path(sys.argv[2]).resolve()
        observed = controls.inventory(packet)
        observed.pop('seal.json', None)
        controls.validate_seal(controls.read_json(packet / 'seal.json'), observed)
        sys.argv[1:] = []
    unittest.main(verbosity=2)
