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
        adapters=list(controls.ADAPTERS), handlers=[], kernel=[], counts=counts, custody=[],
        caller_deliveries=[], refusal_before=None, refusal_after=None)
    receipt.update(native_fds_before={'0': '/dev/null'}, native_fds_after={'0': '/dev/null'})
    events = []
    def event(kind, **data):
        events.append(dict(kind=kind, pid=pid, seq=1 + sum(e['kind'] != 'send' and e['pid'] == pid for e in events), **data))
    def send(sig):
        events.append(dict(kind='send', pid=pid, signal=sig, pidfd_retained=True))
    def handler(sig, owner_phase):
        record = dict(signal=sig, phase=owner_phase, cancelled=True, owner=7, handler=len(receipt['handlers']) + 1)
        receipt['handlers'].append(record)
        event('handler-return', **record)
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
        event('ready-second', phase=ready_phase, masked=phase == 'published-masked', pending=[])
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


class SourceDataTests(unittest.TestCase):
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
