import contextlib
import io
import json
from pathlib import Path
import signal
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import probe


class MemoryStream(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.flushes = 0
        self.closed_observed = False

    def flush(self):
        self.flushes += 1

    def close(self):
        self.closed_observed = True


class RunDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.clock = 100.0
        self.output, self.diagnostics = MemoryStream(), MemoryStream()
        self.console, self.stdout = io.StringIO(), io.StringIO()
        self.process = SimpleNamespace(pid=234, returncode=None)
        self.usage = SimpleNamespace(ru_utime=2.0, ru_stime=1.0, ru_maxrss=8)
        self.polls = 0
        self.finish_at = 1
        self.failure = None
        self.path_opens = []
        self.stack.enter_context(contextlib.redirect_stderr(self.console))
        self.stack.enter_context(contextlib.redirect_stdout(self.stdout))
        def opening(path, mode='r', *args, **kwargs):
            self.path_opens.append((str(path), mode))
            if mode == 'w' and path == Path('/evidence/compiler.log'):
                return self.output
            if mode == 'xb' and path == Path('/evidence/events.jsonl'):
                return self.diagnostics
            raise AssertionError('unexpected file access: ' + str(path))
        self.stack.enter_context(patch.object(Path, 'open', opening))
        self.popen = self.stack.enter_context(patch.object(probe.subprocess, 'Popen', return_value=self.process))
        self.wait = self.stack.enter_context(patch.object(probe.os, 'wait4', side_effect=self.wait4))
        self.kill = self.stack.enter_context(patch.object(probe.os, 'killpg'))
        self.stack.enter_context(patch.object(probe.os, 'waitstatus_to_exitcode', side_effect=lambda value: value))
        self.stack.enter_context(patch.object(probe.time, 'monotonic', side_effect=lambda: self.clock))
        self.sleep = self.stack.enter_context(patch.object(probe.time, 'sleep', side_effect=self.advance))
        self.stack.enter_context(patch.object(probe.os, 'getpid', return_value=123))
        self.pgid = self.stack.enter_context(patch.object(probe.os, 'getpgid', return_value=234))
        self.sid = self.stack.enter_context(patch.object(probe.os, 'getsid', return_value=234))
        self.statvfs = self.stack.enter_context(patch.object(probe.os, 'statvfs', return_value=SimpleNamespace(f_bavail=10, f_frsize=4096)))
        self.reader = self.stack.enter_context(patch.object(probe, '_diagnostic_read', side_effect=self.resource_read))
        self.stack.enter_context(patch.object(probe.sys, 'platform', 'linux'))

    def advance(self, seconds):
        self.assertEqual(seconds, 0.05)
        self.clock += seconds

    def wait4(self, pid, flags):
        self.assertEqual(pid, 234)
        if flags == 0:
            return pid, -9, self.usage
        self.assertEqual(flags, probe.os.WNOHANG)
        self.polls += 1
        if self.failure is not None:
            raise self.failure
        return (pid, 0, self.usage) if self.polls >= self.finish_at else (0, 0, None)

    def resource_read(self, path, limit):
        path = str(path)
        if path.endswith('/status'):
            self.assertIn(path, ('/proc/123/status', '/proc/234/status'))
            self.assertEqual(limit, 65536)
            return 'State:\tR\nPPid:\t123\nThreads:\t2\nVmRSS:\t10 kB\nVmHWM:\t20 kB\nSecret:\tno\n'
        if path == '/proc/234/cgroup':
            return '0::/tenant/job\n'
        if path == '/proc/123/mountinfo':
            self.assertEqual(limit, 1048576)
            return '1 2 0:1 /tenant /sys/fs/cgroup rw - cgroup2 cgroup rw\n'
        self.assertIn(path, ['/sys/fs/cgroup/job/' + name for name in
                           ('memory.current', 'memory.peak', 'memory.max', 'memory.events')])
        self.assertEqual(limit, 8192)
        return '42\n'

    def run_loop(self, phase='off', **kwargs):
        settings = None if phase is None else dict(phase=phase, path=Path('/evidence/events.jsonl'))
        return probe.run(['/fixed/compiler', '--fixed'], Path('/evidence/compiler.log'),
                         diagnostics=settings, cwd='/actual/source', **kwargs)

    def records(self):
        return [json.loads(line) for line in self.diagnostics.getvalue().splitlines()]

    def test_default_has_no_new_io_or_output_and_same_receipt(self):
        result = self.run_loop(None, timeout=5)
        self.assertEqual(self.path_opens, [('/evidence/compiler.log', 'w')])
        self.reader.assert_not_called()
        self.pgid.assert_not_called()
        self.sid.assert_not_called()
        self.statvfs.assert_not_called()
        self.assertEqual(self.console.getvalue(), '')
        self.assertEqual(self.stdout.getvalue(), '')
        self.popen.assert_called_once_with(['/fixed/compiler', '--fixed'], stdout=self.output,
            stderr=probe.subprocess.STDOUT, start_new_session=True, cwd='/actual/source')
        self.assertEqual(set(result), {'command', 'exit_code', 'process_exit_code', 'log', 'timed_out',
            'started_utc', 'ended_utc', 'wall_seconds', 'user_cpu_seconds', 'system_cpu_seconds', 'max_rss_bytes'})
        self.assertEqual((result['exit_code'], result['user_cpu_seconds'], result['max_rss_bytes']), (0, 2.0, 8192))
        self.kill.assert_not_called()

    def test_actual_identity_resources_and_distinct_phases(self):
        for phase in ('off', 'on', 'failed-intake'):
            with self.subTest(phase=phase):
                self.diagnostics.seek(0)
                self.diagnostics.truncate()
                self.process.returncode = None
                result = self.run_loop(phase)
                start, finish = self.records()
                self.assertEqual((start['phase'], finish['phase']), (phase, phase))
                self.assertEqual(start['command'], ['/fixed/compiler', '--fixed'])
                self.assertEqual(start['cwd'], '/actual/source')
                self.assertEqual((start['runner_pid'], start['child_pid'], start['observed_child_pgid'], start['observed_child_sid']), (123, 234, 234, 234))
                self.assertEqual(start['resources']['runner'], dict(State='R', PPid='123', Threads='2', VmRSS='10 kB', VmHWM='20 kB'))
                self.assertEqual(start['resources']['cgroup']['path'], '/sys/fs/cgroup/job')
                self.assertIn('whole_cgroup', start['resources']['cgroup']['scope'])
                self.assertEqual(start['resources']['evidence_free_bytes'], 40960)
                self.assertEqual(finish['process_exit_code'], result['process_exit_code'])
                self.assertEqual(finish['wait4_return'], dict(pid=234, status=0))
                self.assertEqual(finish['wait4_resource']['user_cpu_seconds'], 2.0)
        self.assertEqual(self.stdout.getvalue(), '')
        self.assertEqual(self.output.getvalue(), b'')
        self.assertTrue(self.diagnostics.closed_observed)

    def test_samples_flush_at_fifteen_seconds_not_each_poll(self):
        self.finish_at = 650
        self.run_loop()
        records = self.records()
        self.assertEqual([row['event'] for row in records], ['start', 'sample', 'sample', 'finish'])
        self.assertEqual(self.diagnostics.flushes, 4)
        self.assertTrue(all(15 <= b['monotonic'] - a['monotonic'] < 15.1 for a, b in zip(records[:2], records[1:3])))
        self.assertEqual(self.console.getvalue().count('RUN_DIAGNOSTIC '), 4)

    def test_timeout_retains_owned_group_kill_reap_and_124(self):
        self.finish_at = 1000
        result = self.run_loop(timeout=0.1)
        self.kill.assert_called_once_with(234, signal.SIGKILL)
        self.assertEqual(self.wait.call_args.args, (234, 0))
        self.assertEqual((result['exit_code'], result['process_exit_code'], result['timed_out']), (124, -9, True))
        self.assertEqual(self.records()[-1]['process_exit_code'], -9)

    def test_original_exception_propagates_after_owned_cleanup(self):
        for error in (RuntimeError('original'), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                self.process.returncode = None
                self.failure = error
                self.kill.reset_mock()
                with self.assertRaises(type(error)) as raised:
                    self.run_loop()
                self.assertIs(raised.exception, error)
                self.kill.assert_called_once_with(234, signal.SIGKILL)
                self.assertEqual(self.wait.call_args.args, (234, 0))

    def test_initial_read_failure_is_unknown_and_does_not_change_result(self):
        self.reader.side_effect = OSError('unreadable')
        result = self.run_loop()
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(self.records()[0]['resources']['child'], 'UNKNOWN')
        self.assertEqual(self.records()[0]['resources']['cgroup'], 'UNKNOWN')

    def test_initial_write_failure_still_kills_and_reaps_on_timeout(self):
        self.diagnostics.write = Mock(side_effect=OSError('full'))
        self.finish_at = 1000
        result = self.run_loop(timeout=0.1)
        self.assertEqual(result['exit_code'], 124)
        self.kill.assert_called_once_with(234, signal.SIGKILL)
        self.assertEqual(self.wait.call_args.args, (234, 0))
        self.assertEqual(self.diagnostics.write.call_count, 1)
        self.assertEqual(self.console.getvalue(), 'RUN_DIAGNOSTIC UNKNOWN diagnostics_disabled\n')

    def test_caps_disable_once_with_bounded_file(self):
        self.finish_at = 1000
        with patch.object(probe._RunDiagnostics, 'MAX_EVENTS', 2):
            self.run_loop()
        self.assertEqual(len(self.records()), 2)
        self.assertEqual(self.console.getvalue().count('UNKNOWN diagnostics_disabled'), 1)
        self.assertLessEqual(len(self.diagnostics.getvalue()), probe._RunDiagnostics.MAX_BYTES)

    def test_oversize_event_disables_without_polluting_outputs(self):
        with patch.object(probe._RunDiagnostics, 'MAX_EVENT_BYTES', 1):
            self.assertEqual(self.run_loop()['exit_code'], 0)
        self.assertEqual(self.diagnostics.getvalue(), b'')
        self.assertEqual(self.console.getvalue(), 'RUN_DIAGNOSTIC UNKNOWN diagnostics_disabled\n')

    def test_total_byte_cap_and_open_failure_are_inert(self):
        with patch.object(probe._RunDiagnostics, 'MAX_BYTES', 1):
            self.assertEqual(self.run_loop()['exit_code'], 0)
        self.assertEqual(self.diagnostics.getvalue(), b'')
        self.process.returncode = None
        self.finish_at = 1000
        self.console.seek(0)
        self.console.truncate()
        opening = Path.open
        def fail_diagnostics(path, mode='r', *args, **kwargs):
            if mode == 'xb':
                raise OSError('cannot create diagnostics')
            return opening(path, mode, *args, **kwargs)
        with patch.object(Path, 'open', fail_diagnostics):
            result = self.run_loop(timeout=0.1)
        self.assertEqual(result['exit_code'], 124)
        self.kill.assert_called_once_with(234, signal.SIGKILL)
        self.assertEqual(self.console.getvalue(), 'RUN_DIAGNOSTIC UNKNOWN diagnostics_disabled\n')

    def test_unknown_reap_does_not_invent_a_finish_event(self):
        self.failure = RuntimeError('poll failed')
        def broken_reap(pid, flags):
            if flags == 0:
                raise RuntimeError('reap unknown')
            return self.wait4(pid, flags)
        self.wait.side_effect = broken_reap
        with self.assertRaisesRegex(RuntimeError, 'reap unknown'):
            self.run_loop()
        self.assertEqual([row['event'] for row in self.records()], ['start'])
        self.kill.assert_called_once_with(234, signal.SIGKILL)

    def test_unsupported_platform_and_unreadable_filesystem_are_unknown(self):
        self.statvfs.side_effect = OSError('unreadable')
        with patch.object(probe.sys, 'platform', 'unsupported'):
            self.assertEqual(self.run_loop()['exit_code'], 0)
        self.reader.assert_not_called()
        self.assertEqual(self.records()[0]['resources'], dict(runner='UNKNOWN', child='UNKNOWN',
            cgroup='UNKNOWN', evidence_free_bytes='UNKNOWN'))

    def test_mount_root_mapping_baselines_then_refusal_peers(self):
        mount = '1 2 0:1 /tenant /sys/fs/cgroup rw - cgroup2 cgroup rw\n'
        self.assertEqual(probe._diagnostic_cgroup('0::/tenant/job\n', mount), Path('/sys/fs/cgroup/job'))
        self.assertEqual(probe._diagnostic_cgroup('0::/tenant\n', mount), Path('/sys/fs/cgroup'))
        self.assertEqual(probe._diagnostic_cgroup('0::/tenant/job\n', mount.replace('/tenant ', '/ ')), Path('/sys/fs/cgroup/tenant/job'))
        for membership, mounts in [('0::/other/job\n', mount), ('0::/tenant/../outside\n', mount),
                ('0::relative\n', mount), ('0::/tenant/job\n', mount * 2),
                ('0::/tenant/job\n0::/tenant/other\n', mount),
                ('0::/tenant/job\n', mount.replace('/sys/fs/cgroup', '/sys/../arbitrary'))]:
            with self.subTest(membership=membership, mounts=mounts), self.assertRaises(ValueError):
                probe._diagnostic_cgroup(membership, mounts)

    def test_low_level_bounded_reader_refuses_links_kinds_and_oversize(self):
        self.stack.close()
        with patch.object(probe.os, 'open', side_effect=[10, 11, 12]) as opened, \
                patch.object(probe.os, 'close') as closed, \
                patch.object(probe.os, 'fstat', return_value=SimpleNamespace(st_mode=0o100444)), \
                patch.object(probe.os, 'fdopen', return_value=contextlib.nullcontext(io.BytesIO(b'legal'))):
            self.assertEqual(probe._diagnostic_read('/proc/value', 5), 'legal')
            self.assertTrue(opened.call_args.kwargs.get('dir_fd'))
            self.assertEqual(closed.call_count, 3)
        for body, mode in [(b'oversize', 0o100444), (b'ok', 0o020444)]:
            with patch.object(probe.os, 'open', side_effect=[10, 11, 12]), \
                    patch.object(probe.os, 'close'), \
                    patch.object(probe.os, 'fstat', return_value=SimpleNamespace(st_mode=mode)), \
                    patch.object(probe.os, 'fdopen', return_value=contextlib.nullcontext(io.BytesIO(body))), \
                    self.assertRaises(ValueError):
                probe._diagnostic_read('/proc/value', 5)
        with patch.object(probe.os, 'open', side_effect=[10, OSError('symlink refused')]), \
                patch.object(probe.os, 'close') as closed, self.assertRaises(OSError):
            probe._diagnostic_read('/symlink/value', 5)
        closed.assert_called_once_with(10)


if __name__ == '__main__':
    unittest.main()
