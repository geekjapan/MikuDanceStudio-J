"""Small pure driver checks; no producer, compiler or corpus execution."""
import copy
from pathlib import Path
import unittest

from friction_check import BRANCH, WORKFLOW, Schedule, _resequence, sha, validate_corpus, workflow_identity


class DriverTests(unittest.TestCase):
    def environment(self):
        head = 'a' * 40
        return head, {'GITHUB_ACTIONS': 'true', 'GITHUB_SHA': head, 'GITHUB_EVENT_NAME': 'push',
                      'GITHUB_REF': 'refs/heads/' + BRANCH, 'GITHUB_JOB': 'diagnostic',
                      'GITHUB_REPOSITORY': 'example/project', 'GITHUB_WORKFLOW_SHA': head,
                      'GITHUB_WORKFLOW_REF': 'example/project/' + WORKFLOW + '@refs/heads/' + BRANCH,
                      'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}

    def test_workflow_exact_head_run_job_and_source_bytes(self):
        head, env = self.environment()
        workflow = b'name: initialized synthetic workflow\n'
        raw = workflow_identity(env, head, workflow)
        self.assertIn(f'source {len(workflow)} {sha(workflow)} {WORKFLOW}\n'.encode(), raw)
        for name, value in [('GITHUB_SHA', 'b' * 40), ('GITHUB_WORKFLOW_SHA', 'b' * 40),
                            ('GITHUB_REF', 'refs/heads/main'), ('GITHUB_JOB', 'other'),
                            ('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_RUN_ID', '01'),
                            ('GITHUB_RUN_ATTEMPT', '-1'), ('GITHUB_WORKFLOW_REF', 'other/path')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                workflow_identity({**env, name: value}, head, workflow)

    def synthetic_corpus(self):
        rows, cases = [], []
        for i in range(30):
            name = f'initialized-{i}'
            start = len(rows)
            rows.extend([f'H {name} fixture-injection', 'X'])
            cases.append({'name': name, 'family': 'synthetic', 'start': start, 'end': start + 1,
                          'operations': [{'row': start, 'scope': 'fixture-injection'},
                                         {'row': start + 1, 'scope': 'fixture-injection'}]})
        return '\n'.join(rows) + '\n', cases

    def test_every_case_command_is_bound_once(self):
        inputs, cases = self.synthetic_corpus()
        self.assertEqual(validate_corpus(inputs, cases), inputs.encode())
        for changed in (cases[:-1], cases + cases[:1]):
            with self.assertRaisesRegex(ValueError, '30-case'):
                validate_corpus(inputs, changed)
        for field, value in [('start', True), ('end', 0), ('operations', [])]:
            changed = copy.deepcopy(cases)
            changed[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_corpus(inputs, changed)
        with self.assertRaises(ValueError):
            validate_corpus(inputs + 'X\n', cases)

    def test_structural_peers_do_not_fail_only_on_sequence_numbers(self):
        rows = [['FH', '3', 'native-observed', 'ordinary', 'a' * 64, '2'],
                ['FG', '0', '41', 'STARTUP', 'true', 'true', 'true', 'true'],
                ['O', '0', 'H', '0', '0', '0'], ['FZ', '999', '2', '0']]
        raw = _resequence(rows)
        self.assertIn(b'FG 0 1 STARTUP', raw)
        self.assertIn(b'O 0 H 0 0 0\nFZ 1 2 0\n', raw)
        self.assertEqual(rows[1][2], '41')

    def test_exact_schedule_rejects_missing_output_and_unclosed_process(self):
        class Recorder:
            def __init__(self):
                self.commands, self.files = [], {}

            def bind_tool(self, tool):
                return {'path': str(tool)}

            def write(self, path, raw):
                self.files[path] = raw

            def run(self, label, argv, *, cwd, data, inputs, outputs):
                self.commands.append({'label': label, 'argv': argv, 'cwd': str(cwd),
                                      'stdin_sha256': None if data is None else sha(data),
                                      'inputs_before': dict.fromkeys(map(str, inputs)),
                                      'outputs': dict.fromkeys(map(str, outputs)), 'pid': 42,
                                      'waited': True, 'streams_closed': True, 'returncode': 0})
                return b'initialized output'
        recorder = Recorder()
        schedule = Schedule(recorder, Path('/synthetic'))
        schedule.run('synthetic', ['/synthetic/tool', 'argument'], cwd=Path('/synthetic'),
                     data=b'initialized stdin\n', inputs=[Path('/synthetic/input')], outputs=[Path('/synthetic/output')])
        schedule.check()
        self.assertTrue(recorder.files[Path('/synthetic/schedule.txt')].startswith(b'MMD_FRICTION_SCHEDULE 1\nS '))
        recorder.commands[0]['streams_closed'] = False
        with self.assertRaisesRegex(ValueError, 'closed command'):
            schedule.check()
        recorder.commands[0]['streams_closed'] = True
        recorder.commands[0]['outputs'] = {}
        with self.assertRaisesRegex(ValueError, 'input/output schedule'):
            schedule.check()


if __name__ == '__main__':
    unittest.main()
