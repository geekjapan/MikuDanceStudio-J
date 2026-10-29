"""Guarded source/data checks. These synthetic receipts are never real OS acceptance."""
import ast
import builtins
import copy
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]
DENIED = []


def deny_effects(event, args):
    blocked = event in ('subprocess.Popen', 'os.system', 'os.fork', 'os.posix_spawn', 'socket.__new__',
                        'socket.connect', 'socket.bind', 'ctypes.dlopen', 'ctypes.dlsym', 'os.mkdir',
                        'os.remove', 'os.rename', 'os.rmdir', 'os.chmod', 'os.symlink', 'os.link')
    if event == 'open':
        mode, flags = args[1:3]
        blocked = (isinstance(mode, str) and any(letter in mode for letter in 'wax+')) or (
            isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
    if blocked:
        DENIED.append(event)
        raise PermissionError('source/data check denies ' + event)


sys.addaudithook(deny_effects)
spec = importlib.util.spec_from_file_location('os_controls_data_only', HERE / 'check_cmp_82dc_os_controls.py')
controls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)


def legal_case(case, mode='normal', pid=100):
    name, phase, first, second = case
    counts = dict(normalize=0, invoke=0, execute_body=0, popen=0, retain=0, finish=0, close=0)
    receipt = dict(case=name, mode=mode, pid=pid, source=controls.SOURCE_COMMIT, tree=controls.SOURCE_TREE,
        status='PASS', runtime=[3, 12, 3], children=[], writer_none=True, pidfds_closed=True,
        subprocesses_reaped=True, streams_closed=True, caller_restored=True, post_handoff_io=[],
        adapters=list(controls.ADAPTERS), handlers=[], kernel=[], counts=counts, custody=[],
        caller_deliveries=[], refusal_before=None, refusal_after=None)
    receipt.update(native_fds_before={'0': '/dev/null'}, native_fds_after={'0': '/dev/null'})
    events = []
    def event(kind, **data):
        events.append(dict(kind=kind, pid=pid, seq=1 + sum(e['kind'] != 'send' and e['pid'] == pid for e in events), **data))
    if phase == 'baseline':
        counts.update(popen=3, invoke=3, normalize=2)
        receipt['custody'] = [dict(custody_status='clean') for _ in range(3)]
    elif phase.startswith('caller-'):
        pending = phase == 'caller-pending'
        state = dict(mask=[first, 10], pending=[first] if pending else [], handlers={'2': 1, '15': 2})
        receipt.update(refusal_before=state, refusal_after=copy.deepcopy(state), caller_deliveries=[first] if pending else [])
        if pending:
            events.append(dict(kind='send', pid=pid, signal=first))
    else:
        expected = (0, 0) if phase == 'entry' else ((2, 1) if phase == 'working-cleanup' else (3, 2))
        counts.update(popen=expected[0], normalize=expected[1])
        events.append(dict(kind='send', pid=pid, signal=first))
        event('handler-return', signal=first)
        first_phase = 'installing' if phase == 'entry' else ('working' if phase == 'working-cleanup' else 'finishing')
        receipt['handlers'].append(dict(signal=first, phase=first_phase, cancelled=True, owner=7))
        event('ready-second', pending=[])
        events.append(dict(kind='send', pid=pid, signal=second))
        if phase == 'published-masked':
            receipt['kernel'] = [dict(point='second-after-send', pending=[second]),
                dict(point='original-sigtimedwait', requested=[second], consumed=second, pending=[])]
        else:
            event('handler-return', signal=second)
            second_phase = 'installing' if phase == 'entry' else ('closing' if phase == 'working-cleanup' else 'finishing')
            receipt['handlers'].append(dict(signal=second, phase=second_phase, cancelled=True, owner=7))
        if phase == 'working-cleanup':
            events.insert(0, dict(kind='writer-ready', seq=1, pid=200, primary=200, descendant=201,
                                 session=200, descendant_session=201))
            receipt['custody'] = [dict(owned_descendants_reaped=[dict(pid=200, session=200), dict(pid=201, session=201)])]
    event('worker-closed')
    return receipt, events


def legal_index():
    return dict(schema=1, source=controls.SOURCE_COMMIT, tree=controls.SOURCE_TREE, mode='normal', status='PASS',
        closed=True, controller_children=[], streams_closed=True, cases=[dict(case=case[0], pid=100 + i,
        terminal=True, exit=0, owned_closed=True, streams_closed=True, pidfd_closed=True, forced_cleanup=False,
        validated=True) for i, case in enumerate(controls.CASES)])


class SourceDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        controls.source_only_check(SOURCE)
        for mode in ('normal', 'optimized'):
            for case in controls.CASES:
                receipt, events = legal_case(case, mode)
                controls.validate_case(receipt, case, mode, 100, events)
        controls.validate_index(legal_index())

    def test_source_and_complete_legal_receipts_first(self):
        controls.source_only_check(SOURCE)
        self.assertEqual(len(controls.CASES), 21)
        for mode in ('normal', 'optimized'):
            for case in controls.CASES:
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
        receipt['kernel'][1]['consumed'] = None
        with self.assertRaises(ValueError):
            controls.validate_case(receipt, case, 'normal', 100, events)

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

    def test_four_seal_negatives(self):
        original = {'a': {'mode': 292, 'size': 1, 'sha256': controls.digest(b'a')}}
        controls.validate_seal(original, copy.deepcopy(original))
        missing = {}
        extra = dict(original, extra={})
        corrupt = copy.deepcopy(original)
        corrupt['a']['sha256'] = controls.digest(b'b')
        mode = copy.deepcopy(original)
        mode['a']['mode'] = 420
        for candidate in (missing, extra, corrupt, mode):
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
