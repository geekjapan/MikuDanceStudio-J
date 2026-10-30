"""Additional hosted OS controls for literal 82dc. Import and CLI parsing do no OS probes.

Synthetic compiler data is not compiler, CMP, stable Rust, or product acceptance.
--real-os and its internal --worker-output/--fixture entrypoints operate processes and signals
only on the reviewed GHA runtime. --source-only and --upload-gate are read-only checks.
"""
import argparse
import ast
import copy
from typing import NamedTuple
import datetime
import hashlib
import importlib.util
import inspect
import json
import marshal
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import sys
import time
import traceback
import textwrap

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
WAIT_AST = {'wait': '32eb93a7f8a4c09e4ddd6126580dfc68120f54ecc23dcefab06fa156d0b4e427',
            '_wait': 'dbe2e31be45022de935cb0d9fc9c1c33c5b99ef8ea54826342703afce9f605e5'}
CASES = [('baseline', 'baseline', 0, 0)] + [
    (f'{phase}-{first}-{second}', phase, first, second)
    for phase in PHASES for first, second in PAIRS] + [
    (f'caller-{kind}-{sig}', 'caller-' + kind, sig, 0)
    for kind in ('blocked', 'pending') for sig in (2, 15)]
ADAPTERS = ('reviewed_contract', 'verify_tool', 'verify_evidence', 'retain_tool_identity',
            'validate_result', 'Popen-command-only', 'Popen._wait-pass-through')


class HandlerObserver:
    tool_id = 3
    stack_limit = 64

    def __init__(self, owner, handler_code, methods, counts, max_active, followon):
        self.owner, self.handler_code = owner, handler_code
        self.methods, self.counts, self.max_active, self.followon = methods, counts, max_active, followon
        self.started, self.receipted, self.failure = [], 0, None
        self.cancelled_seen = False
        self.monitoring = None
        self.previous_callback = None

    def start(self, code, offset):
        frame = sys._getframe(1)
        matching, depths = None, dict(finish=0, close=0)
        for unused in range(self.stack_limit):
            if frame is None:
                break
            if frame.f_code is code and matching is None:
                matching = frame
            key = next((name for method, name in self.methods.items() if method is frame.f_code), None)
            if key in depths:
                depths[key] += 1
            frame = frame.f_back
        if frame is not None or matching is None:
            self.failure = 'observer stack/frame bound differs'
            return
        if self.cancelled_seen and not self.owner.cancelled:
            self.failure = 'cancellation latch regressed'
        self.cancelled_seen = self.cancelled_seen or self.owner.cancelled
        if code is self.handler_code:
            if (matching.f_locals.get('self') is not self.owner
                    or matching.f_locals.get('signum') not in self.owner.signals
                    or len(self.started) + self.receipted >= 2):
                self.failure = 'observer handler identity/count differs'
                return
            self.started.append((matching, self.owner, matching.f_locals['signum'], self.owner.phase))
        else:
            key = next((name for method, name in self.methods.items() if method is code), None)
            if key is None or (key != 'close' and matching.f_locals.get('self') is not self.owner):
                self.failure = 'observer code differs'
                return
            if not self.followon():
                self.counts[key] += 1
            for name in depths:
                self.max_active[name] = max(self.max_active[name], depths[name])

    def complete(self):
        require(self.failure is None, self.failure or 'observer failed')
        require(not self.cancelled_seen or self.owner.cancelled, 'cancellation latch regressed')
        frame, stack = sys._getframe(1), []
        for unused in range(self.stack_limit):
            if frame is None:
                break
            stack.append(frame)
            frame = frame.f_back
        require(frame is None, 'completion stack bound differs')
        records = []
        while self.started:
            observed, owner, signum, phase = self.started[0]
            require(observed.f_code is self.handler_code and owner is self.owner
                    and observed.f_locals.get('self') is owner
                    and observed.f_locals.get('signum') == signum, 'completion handler identity differs')
            if any(current is observed for current in stack):
                break
            require(owner.cancelled, 'interrupt did not latch cancellation')
            self.cancelled_seen = True
            self.receipted += 1
            records.append(dict(signal=signum, phase=phase, cancelled=True, handler=self.receipted, owner=id(owner)))
            self.started.pop(0)
        return records

    def enable(self):
        require(sys.getprofile() is None and sys.gettrace() is None, 'observer refuses existing profile/trace')
        monitoring = sys.monitoring
        require(all(monitoring.get_tool(tool) is None and monitoring.get_events(tool) == 0
                    for tool in range(6)), 'observer refuses existing monitoring tools/events')
        codes = (self.handler_code, *self.methods)
        require(all(monitoring.get_local_events(self.tool_id, code) == 0 for code in codes),
                'observer refuses existing local events')
        monitoring.use_tool_id(self.tool_id, 'cmp-genuine-handler')
        self.monitoring = monitoring
        try:
            self.previous_callback = monitoring.register_callback(self.tool_id, monitoring.events.PY_START, self.start)
            require(self.previous_callback is None, 'observer refuses existing callback')
            monitoring.set_events(self.tool_id, 0)
            for code in codes:
                monitoring.set_local_events(self.tool_id, code, monitoring.events.PY_START)
            require(monitoring.get_events(self.tool_id) == 0
                    and all(monitoring.get_local_events(self.tool_id, code) == monitoring.events.PY_START
                            for code in codes), 'observer activation scope differs')
        except BaseException:
            self.close()
            raise

    def close(self):
        monitoring = self.monitoring
        if monitoring is None:
            return
        monitoring.set_events(self.tool_id, 0)
        for code in (self.handler_code, *self.methods):
            monitoring.set_local_events(self.tool_id, code, 0)
        monitoring.register_callback(self.tool_id, monitoring.events.PY_START, None)
        require(monitoring.get_events(self.tool_id) == 0
                and all(monitoring.get_local_events(self.tool_id, code) == 0
                        for code in (self.handler_code, *self.methods)), 'observer events remain active')
        if self.previous_callback is not None:
            monitoring.register_callback(self.tool_id, monitoring.events.PY_START, self.previous_callback)
        monitoring.free_tool_id(self.tool_id)
        require(monitoring.get_tool(self.tool_id) is None and sys.getprofile() is None and sys.gettrace() is None,
                'observer runtime restoration differs')
        self.monitoring = None
        self.started.clear()


def validate_completion(event, *, pid, case, owner, signum, phase, ordinal):
    require(type(event) is dict and set(event) == {'kind', 'pid', 'seq', 'case', 'signal', 'phase',
            'cancelled', 'handler', 'owner'}, 'completion schema differs')
    require(event['kind'] == 'handler-return' and event['case'] == case
            and type(event['pid']) is int and event['pid'] == pid
            and type(event['seq']) is int and event['seq'] > 0
            and type(event['owner']) is int and event['owner'] == owner and owner > 0
            and type(event['signal']) is int and event['signal'] == signum
            and event['phase'] == phase and event['cancelled'] is True
            and type(event['handler']) is int and event['handler'] == ordinal, 'completion identity differs')
    return True


def second_readiness(event, first_ack, case, pid):
    name, phase, first, second = case
    first_phase = 'installing' if phase == 'entry' else ('working' if phase == 'working-cleanup' else 'finishing')
    current_phase = 'closing' if phase == 'working-cleanup' else first_phase
    require(type(event) is dict and set(event) == {'kind', 'case', 'pid', 'seq', 'owner', 'phase', 'masked', 'pending'}
            and event.get('kind') == 'ready-second' and event.get('case') == name
            and type(event.get('pid')) is int and event.get('pid') == pid and type(event.get('owner')) is int
            and event.get('phase') == current_phase and event.get('masked') is (phase == 'published-masked')
            and type(event.get('pending')) is list and len(event['pending']) <= 64
            and all(type(value) is int and 1 <= value <= 64 for value in event['pending'])
            and not {2, 15} & set(event['pending']), 'second readiness differs')
    validate_completion(first_ack, pid=pid, case=name, owner=event['owner'], signum=first, phase=first_phase, ordinal=1)
    return phase == 'published-masked'
class SecondAck(NamedTuple):
    count: int
    signals: tuple
    pending: tuple
    pair: tuple
    phase: str
    owner_phase: str
    case: str
    interpreter: tuple


def second_ack_snapshot(events, pending, first, second, phase, owner_phase, case, interpreter):
    signals = tuple(event['signal'] for event in events)
    return SecondAck(len(signals), signals, tuple(pending), (first, second), phase, owner_phase, case, tuple(interpreter))


def second_ack_diagnostic(sample):
    try:
        record = sample._asdict()
        record.update(signals=sample.signals[:8], pending=sample.pending[:64],
                      signals_omitted=max(0, sample.count - 8), pending_omitted=max(0, len(sample.pending) - 64))
        record['interpreter'] = [str(value)[:240] for value in sample.interpreter]
        record['phase'], record['case'] = sample.phase[:64], sample.case[:96]
        record['owner_phase'] = sample.owner_phase[:64]
        raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
        require(len(raw) <= 4096, 'second ACK diagnostic bound exceeded')
        print('SECOND_ACK_FAILURE ' + raw, file=sys.stderr, flush=True)
    except BaseException:
        pass


def observer_definitions(source):
    product_path = Path(source) / PREFIX / 'run_cmp_input.py'
    controller_path = Path(__file__).resolve()
    product_raw, controller_raw = product_path.read_bytes(), controller_path.read_bytes()
    require(digest(product_raw) == FROZEN['run_cmp_input.py'], 'observer fixed product differs')
    product, controller = ast.parse(product_raw), ast.parse(controller_raw)
    owner = next(node for node in product.body if isinstance(node, ast.ClassDef) and node.name == 'WrapperRun')
    methods = {node.name: node for node in owner.body if isinstance(node, ast.FunctionDef)}
    worker = next(node for node in controller.body if isinstance(node, ast.FunctionDef) and node.name == 'worker_body')
    profile = next(node for node in worker.body if isinstance(node, ast.FunctionDef) and node.name == 'profile')
    receipt = dict(product_sha256=digest(product_raw), controller_sha256=digest(controller_raw),
        init_ast_sha256=digest(ast.dump(methods['__init__']).encode()),
        interrupt_ast_sha256=digest(ast.dump(methods['interrupt']).encode()),
        profile_ast_sha256=digest(ast.dump(profile).encode()))
    return methods['__init__'], methods['interrupt'], profile, receipt


def profiler_observer_control(source):
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and sys.platform == 'linux'
            and sys.implementation.name == 'cpython' and sys.version_info[:3] == (3, 12, 3),
            'observer control requires hosted Linux CPython 3.12.3')
    require(sys.getprofile() is None, 'observer control requires no existing profile')
    init, interrupt, profile, identities = observer_definitions(source)
    namespace = dict(require=require)
    definitions = ast.ClassDef(name='WrapperRun', bases=[], keywords=[], decorator_list=[],
        body=copy.deepcopy([init, interrupt]))
    factory = ast.parse('def make_profile():\n    cancelled_seen = False\n    return profile\n').body[0]
    factory.body.insert(1, copy.deepcopy(profile))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[definitions, factory], type_ignores=[])),
                 '<observer-only-extracted-definitions>', 'exec'), namespace)
    owner = namespace['WrapperRun']()
    owner.phase = 'installing'
    events, sends, nested = [], [], []
    def send(kind, **record):
        sends.append(dict(kind=kind, **record))
        if len(sends) == 1:
            owner.cancelled = False
            owner.interrupt(15, None)
            nested.append(dict(signal=15, cancelled=owner.cancelled, accounted=len(events)))
    namespace.update(wrapper=type('Wrapper', (), {'WrapperRun': namespace['WrapperRun']}), owner=owner,
        signal=type('Signal', (), {'getsignal': staticmethod(lambda sig: owner.interrupt)}),
        channel=type('Channel', (), {'send': staticmethod(send)}), handler_events=events,
        module_file='<unmatched-observer-product-file>', counts={}, active={}, max_active={},
        in_followon=False, wait_code=None, processes=[])
    callback = namespace['make_profile']()
    failure = None
    try:
        sys.setprofile(callback)
        owner.interrupt(2, None)
    except BaseException as error:
        failure = error
    finally:
        sys.setprofile(None)
    report = dict(kind='observer-only; no OS delivery/custody acceptance', source=SOURCE_COMMIT,
        identities=identities, interpreter=dict(implementation=sys.implementation.name, version=sys.version,
        executable=sys.executable, optimize=sys.flags.optimize), outside=list(events), sends=sends, inside=nested,
        error=None if failure is None else dict(type=type(failure).__name__, message=str(failure)[:240]))
    print('PROFILER_OBSERVER_CONTROL ' + json.dumps(report, sort_keys=True), flush=True)
    if failure is not None:
        raise failure
    require(len(events) == len(sends) == len(nested) == 1 and events[0]['signal'] == 2
            and events[0]['cancelled'] is True and nested[0] == dict(signal=15, cancelled=True, accounted=1)
            and owner.cancelled, 'genuine profiler observer counterexample differs')
    return report


def wait_provenance(popen):
    records = {}
    for name, identity in WAIT_AST.items():
        function = getattr(popen, name)
        raw = inspect.getsource(function)
        node = ast.parse(textwrap.dedent(raw)).body[0]
        require(digest(ast.dump(node).encode()) == identity, 'hosted Popen wait AST differs from CPython v3.12.3')
        records[name] = dict(ast_sha256=identity, source_sha256=digest(raw.encode()),
            code_sha256=digest(marshal.dumps(function.__code__)), filename=function.__code__.co_filename,
            firstlineno=function.__code__.co_firstlineno)
    records['module'] = dict(path=subprocess.__file__, sha256=digest(Path(subprocess.__file__).read_bytes()))
    return records


def validate_wait_provenance(records):
    require(type(records) is dict and set(records) == {'wait', '_wait', 'module'}, 'wait provenance schema differs')
    for name, expected in WAIT_AST.items():
        record = records[name]
        require(type(record) is dict and set(record) == {'ast_sha256', 'source_sha256', 'code_sha256', 'filename', 'firstlineno'}
                and record['ast_sha256'] == expected and type(record['firstlineno']) is int and record['firstlineno'] > 0
                and type(record['filename']) is str and Path(record['filename']).is_absolute(), 'wait provenance identity differs')
        for key in ('source_sha256', 'code_sha256'):
            require(type(record[key]) is str and len(record[key]) == 64
                    and all(c in '0123456789abcdef' for c in record[key]), 'wait provenance hash differs')
    module = records['module']
    require(type(module) is dict and set(module) == {'path', 'sha256'}
            and module['path'] == records['wait']['filename'] == records['_wait']['filename']
            and type(module['sha256']) is str and len(module['sha256']) == 64
            and all(c in '0123456789abcdef' for c in module['sha256']), 'wait module provenance differs')
    return True


def observer_methods(wrapper):
    methods = {getattr(wrapper.WrapperRun, name).__code__: key for name, key in (
        ('normalize', 'normalize'), ('invoke', 'invoke'), ('_execute', 'execute_body'), ('_finish', 'finish'))}
    methods[wrapper.close_owned_children.__code__] = 'close'
    return methods


def monitoring_observer_control(source):
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and sys.platform == 'linux'
            and sys.implementation.name == 'cpython' and sys.version_info[:3] == (3, 12, 3),
            'monitoring control requires hosted Linux CPython 3.12.3')
    wrapper, unused, unused_tool = load_source(source)
    provenance = wait_provenance(subprocess.Popen)
    handler = wrapper.WrapperRun.interrupt
    reports = []
    for phase, signum in (('installing', 2), ('working', 15)):
        owner = wrapper.WrapperRun()
        owner.phase = phase
        observer = HandlerObserver(owner, handler.__code__, observer_methods(wrapper),
            dict.fromkeys(('normalize', 'invoke', 'execute_body', 'finish', 'close'), 0),
            dict(finish=0, close=0), lambda: False)
        raised = False
        try:
            observer.enable()
            try:
                owner.interrupt(signum, None)
            except KeyboardInterrupt:
                raised = True
            require(raised is (phase == 'working'), 'genuine unwind control differs')
            records = observer.complete()
            require(records == [dict(signal=signum, phase=phase, cancelled=True, handler=1, owner=id(owner))]
                    and not observer.started and observer.complete() == [], 'monitoring completion control differs')
            reports.append(dict(phase=phase, signum=signum, unwind=raised, records=records))
        finally:
            observer.close()
        require(observer.monitoring is None and not observer.started, 'monitoring cleanup control differs')
    report = dict(kind='manual genuine-handler observer admission; no OS delivery acceptance', source=SOURCE_COMMIT,
        product_sha256=FROZEN['run_cmp_input.py'], handler_code_sha256=digest(marshal.dumps(handler.__code__)),
        handler_ast_sha256=observer_definitions(source)[3]['interrupt_ast_sha256'],
        controller_sha256=digest(Path(__file__).read_bytes()), wait=provenance,
        interpreter=dict(implementation=sys.implementation.name, version=sys.version,
                         executable=sys.executable, optimize=sys.flags.optimize), controls=reports,
        local_codes=6, global_events=0, callback_ipc=False, profile=False, cleanup=True)
    print('MONITORING_OBSERVER_CONTROL ' + json.dumps(report, sort_keys=True), flush=True)
    return report


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


def inventory(root, *, checkout_git_admin=False):
    result = {}
    def visit(directory):
        for path in sorted(directory.iterdir()):
            name = path.relative_to(root).as_posix()
            if checkout_git_admin and name == '.git':
                continue
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                result[name + '/'] = {'kind': 'directory', 'mode': stat.S_IMODE(mode)}
                visit(path)
            elif stat.S_ISLNK(mode):
                raw = os.fsencode(os.readlink(path))
                result[name] = {'kind': 'symlink', 'mode': stat.S_IMODE(mode),
                                'link': os.fsdecode(raw), 'git_blob': blob_oid(raw)}
            else:
                require(stat.S_ISREG(mode), 'special filesystem member')
                raw = path.read_bytes()
                result[name] = {'kind': 'file', 'mode': stat.S_IMODE(mode), 'size': len(raw),
                                'sha256': digest(raw), 'git_blob': blob_oid(raw)}
    root = Path(root)
    visit(root)
    return result


def blob_oid(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def validate_git_filesystem(listing, files):
    require(listing.endswith(b'\0') and listing != b'\0', 'incomplete Git listing')
    tracked, directories = {}, set()
    for item in listing[:-1].split(b'\0'):
        metadata, name_raw = item.split(b'\t', 1)
        mode, kind, oid = metadata.decode('ascii').split()
        name = os.fsdecode(name_raw)
        parts = name.split('/')
        require(all(part not in ('', '.', '..') for part in parts) and parts[0] != '.git'
                and name not in tracked, 'invalid or duplicate Git path')
        require(kind == 'blob' and mode in ('100644', '100755', '120000')
                and len(oid) == 40 and all(c in '0123456789abcdef' for c in oid), 'unsupported Git member')
        tracked[name] = (mode, oid)
        directories.update('/'.join(parts[:i]) + '/' for i in range(1, len(parts)))
    require(set(files) == set(tracked) | directories, 'complete checkout membership differs')
    for name in directories:
        require(files[name] == {'kind': 'directory', 'mode': 0o755}, 'checkout directory identity differs ' + name)
    for name, (mode, oid) in tracked.items():
        member = files[name]
        require(member.get('kind') == ('symlink' if mode == '120000' else 'file'), 'checkout kind differs ' + name)
        require(member.get('mode') == (0o777 if mode == '120000' else 0o755 if mode == '100755' else 0o644),
                'checkout mode differs ' + name)
        require(member.get('git_blob') == oid, 'checkout blob differs ' + name)
        if mode == '120000':
            require(isinstance(member.get('link'), str) and blob_oid(os.fsencode(member['link'])) == oid,
                    'checkout link differs ' + name)
        else:
            require(type(member.get('size')) is int and member['size'] >= 0
                    and isinstance(member.get('sha256'), str) and len(member['sha256']) == 64,
                    'checkout file identity missing ' + name)
    return True


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


def validate_git_receipt(receipt):
    require(type(receipt.get('pid')) is int and receipt['pid'] > 0
            and isinstance(receipt.get('argv'), list) and receipt['argv']
            and all(isinstance(arg, str) for arg in receipt['argv'])
            and isinstance(receipt.get('cwd'), str) and Path(receipt['cwd']).is_absolute(),
            'Git PID/command receipt missing')
    try:
        start = datetime.datetime.fromisoformat(receipt['start'])
        end = datetime.datetime.fromisoformat(receipt['end'])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('Git UTC receipt missing') from error
    require(start.utcoffset() == end.utcoffset() == datetime.timedelta(0) and start <= end,
            'Git UTC receipt differs')
    require(receipt.get('terminal') is True and type(receipt.get('exit')) is int
            and type(receipt.get('wait')) is int and receipt['exit'] == receipt['wait'] == 0
            and receipt.get('failure') is None, 'Git terminal receipt differs')
    for name in ('stdout', 'stderr'):
        stream = receipt.get('streams', {}).get(name, {})
        require(stream.get('closed') is True and isinstance(stream.get('hex'), str), 'Git stream closure missing')
        try:
            raw = bytes.fromhex(stream['hex'])
        except ValueError as error:
            raise ValueError('Git stream body differs') from error
        require(stream.get('size') == len(raw) and stream.get('sha256') == digest(raw), 'Git stream identity differs')
    return True


def validate_checkout_pair(before, after, expected):
    require((before['head'], before['tree']) == (after['head'], after['tree']) == expected,
            'checkout HEAD/TREE changed')
    require(before['filesystem'] == after['filesystem'], 'checkout filesystem changed')
    return True


def git_identity(root, expected=None, *, receipts):
    commands = []
    receipts = Path(receipts)
    receipts.mkdir()
    def git(*args):
        command = ['git', '-c', 'core.hooksPath=/dev/null', '-C', str(root), *args]
        receipt = dict(argv=command, cwd=str(root), pid=None,
                       start=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       terminal=False, exit=None, wait=None, failure=None, streams={})
        process = None
        stdout = stderr = None
        try:
            process = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=dict(os.environ, GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0'))
            receipt['pid'] = process.pid
            try:
                stdout, stderr = process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                receipt['failure'] = 'timeout; forced termination is failure'
                process.kill()
                stdout, stderr = process.communicate(timeout=5)
            receipt.update(exit=process.returncode, wait=process.wait(timeout=5), terminal=True)
        except BaseException as error:
            receipt['failure'] = type(error).__name__ + ': ' + str(error)
        finally:
            receipt['end'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            if process is not None and receipt['terminal']:
                for name, raw in (('stdout', stdout), ('stderr', stderr)):
                    stream = getattr(process, name)
                    if stream.closed and raw is not None:
                        receipt['streams'][name] = dict(closed=True, size=len(raw), sha256=digest(raw), hex=raw.hex())
            commands.append(receipt)
            atomic(receipts / (str(len(commands)) + '.json'), receipt)
        validate_git_receipt(receipt)
        return stdout
    head = git('rev-parse', 'HEAD').decode().strip()
    raw_commit = git('cat-file', 'commit', head)
    require(hashlib.sha1(b'commit ' + str(len(raw_commit)).encode() + b'\0' + raw_commit).hexdigest() == head,
            'raw commit framing differs')
    require(raw_commit.startswith(b'tree '), 'raw commit tree missing')
    tree = raw_commit.splitlines()[0].decode().removeprefix('tree ')
    raw_tree = git('cat-file', 'tree', tree)
    require(hashlib.sha1(b'tree ' + str(len(raw_tree)).encode() + b'\0' + raw_tree).hexdigest() == tree,
            'raw tree framing differs')
    if expected:
        require((head, tree) == expected, 'literal tested Git identity differs')
    require(not git('status', '--porcelain', '--untracked-files=all'), 'checkout must be clean')
    listing = git('ls-tree', '-rz', '--full-tree', head)
    files = inventory(root, checkout_git_admin=True)
    validate_git_filesystem(listing, files)
    return {'head': head, 'tree': tree, 'raw_commit': raw_commit.decode(),
            'raw_tree_sha256': digest(raw_tree), 'listing_hex': listing.hex(), 'filesystem': files, 'commands': commands}


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


ERROR_STAGES = ('runtime-guard', 'ipc-setup', 'case-selection', 'source-import', 'custody-enable',
                'fixture-setup', 'owner-setup', 'execute', 'validation', 'restoration', 'unavailable')


def failure_sample_record(sample):
    record = dict(count=sample.count, signals=list(sample.signals[:8]), pending=list(sample.pending[:64]),
        pair=list(sample.pair), phase=sample.phase, owner_phase=sample.owner_phase, case=sample.case,
        interpreter=[str(value)[:24] for value in sample.interpreter],
        signals_omitted=max(0, sample.count - 8), pending_omitted=max(0, len(sample.pending) - 64))
    validate_failure_sample(record, sample.case)
    return record


def validate_failure_sample(record, case):
    require(type(record) is dict and set(record) == {'count', 'signals', 'pending', 'pair', 'phase',
        'owner_phase', 'case', 'interpreter', 'signals_omitted', 'pending_omitted'}, 'failure sample schema differs')
    row = next((row for row in CASES if row[0] == case), None)
    require(row is not None and row[3] in (2, 15) and record['case'] == case
            and record['phase'] == row[1] and record['pair'] == list(row[2:]), 'failure sample case/pair differs')
    require(record['owner_phase'] in ('installing', 'closing', 'finishing'), 'failure sample owner phase differs')
    for field in ('count', 'signals_omitted', 'pending_omitted'):
        require(type(record[field]) is int and 0 <= record[field] <= 1000000, 'failure sample count differs')
    for field, bound, allowed in (('signals', 8, (2, 15)), ('pending', 64, range(1, 65)), ('pair', 2, (2, 15))):
        require(type(record[field]) is list and len(record[field]) <= bound
                and all(type(value) is int and value in allowed for value in record[field]), 'failure sample signals differ')
    require(record['pending'] == sorted(set(record['pending']))
            and record['count'] == len(record['signals']) + record['signals_omitted']
            and (record['signals_omitted'] == 0 or len(record['signals']) == 8)
            and (record['pending_omitted'] == 0 or len(record['pending']) == 64), 'failure sample omissions differ')
    require(type(record['interpreter']) is list and len(record['interpreter']) == 4
            and all(type(value) is str and len(value) <= 24 for value in record['interpreter']),
            'failure sample interpreter differs')
    return True


def encode_worker_error(case, pid, seq, stage, exception_type, message, trace, sample=None):
    require(case in [row[0] for row in CASES] and stage in ERROR_STAGES, 'unknown worker error context')
    record = dict(kind='worker-error', schema=1, case=case, pid=pid, seq=seq, stage=stage,
                  exception_type=exception_type[:80], message=message[:400], traceback=trace[:1800],
                  truncated=len(exception_type) > 80 or len(message) > 400 or len(trace) > 1800)
    if sample is not None:
        record['second_ack_failure'] = failure_sample_record(sample)
    while True:
        raw = json.dumps(record, ensure_ascii=True).encode('utf-8') + b'\n'
        if len(raw) < 4096:
            return raw
        field = 'traceback' if record['traceback'] else 'message'
        require(record[field], 'error envelope framing exceeds bound')
        record[field] = record[field][:len(record[field]) // 2]
        record['truncated'] = True


def validate_worker_error(event, case, pid, seq):
    fields = {'kind', 'schema', 'case', 'pid', 'seq', 'stage', 'exception_type', 'message', 'traceback', 'truncated'}
    require(type(event) is dict and set(event) in (fields, fields | {'second_ack_failure'}), 'worker error schema differs')
    if 'second_ack_failure' in event:
        validate_failure_sample(event['second_ack_failure'], case)
    require(event['kind'] == 'worker-error' and type(event['schema']) is int and event['schema'] == 1,
            'worker error kind/schema differs')
    require(event['case'] == case and type(event['pid']) is int and event['pid'] == pid
            and type(event['seq']) is int and event['seq'] == seq and seq > 0, 'worker error identity differs')
    require(type(event['stage']) is str and event['stage'] in ERROR_STAGES and type(event['truncated']) is bool, 'worker error stage differs')
    for field, limit in (('exception_type', 80), ('message', 400), ('traceback', 1800)):
        require(type(event[field]) is str and len(event[field]) <= limit, 'worker error text differs')
    require(event['exception_type'] and len(json.dumps(event, ensure_ascii=True).encode('utf-8') + b'\n') < 4096,
            'worker error exceeds bound')
    return True


def controller_context(mode, case, pid, events, error):
    received = next((event for event in reversed(events)
                     if type(event) is dict and type(event.get('kind')) is str
                     and event['kind'] and event['kind'] != 'send'
                     and all(type(event.get(key)) is int and event[key] > 0 for key in ('seq', 'pid'))), None)
    last = {key: received.get(key) for key in ('kind', 'seq', 'pid')} if received is not None else None
    return dict(mode=mode, case=case, pid=pid, last_received=last,
                error_type=type(error).__name__, message=str(error)[:400],
                worker_stage='unavailable unless received in worker-error')


def diagnostic(label, **data):
    print(json.dumps(dict(diagnostic=label, **data), ensure_ascii=True)[:8192], file=sys.stderr, flush=True)


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

    def receive(self, seconds=5, checkpoint=None):
        deadline = time.monotonic() + seconds
        while b'\n' not in self.buffer:
            if checkpoint is not None:
                checkpoint()
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'rendezvous deadline')
            ready = select.select([self.incoming], [], [], min(remaining, .01) if checkpoint else remaining)[0]
            if not ready:
                require(checkpoint is not None, 'rendezvous deadline')
                continue
            data = os.read(self.incoming, 4096)
            require(data, 'IPC closed before terminal message')
            self.buffer += data
        raw, self.buffer = self.buffer.split(b'\n', 1)
        require(len(raw) < 4096, 'IPC record exceeds atomic pipe bound')
        def pairs(items):
            record = {}
            for key, value in items:
                require(key not in record, 'duplicate IPC field')
                record[key] = value
            return record
        return json.loads(raw, object_pairs_hook=pairs)

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
    channel = Channel(args.input_fd, args.output_fd)
    state = dict(stage='runtime-guard')
    try:
        runtime_guard()
        state['stage'] = 'ipc-setup'
        os.set_blocking(args.output_fd, False)
        state['stage'] = 'case-selection'
        worker_body(args, channel, state)
    except BaseException as failure:
        try:
            os.set_blocking(channel.outgoing, False)
            error = state.get('execute_error', failure)
            stage = 'execute' if 'execute_error' in state else state['stage']
            raw = encode_worker_error(args.case, os.getpid(), channel.serial + 1, stage,
                type(error).__name__, str(error), ''.join(traceback.format_exception(error)), state.get('second_ack_failure'))
            os.write(channel.outgoing, raw)
        except BaseException:
            pass
        raise


def worker_body(args, channel, state):
    case = next(case for case in CASES if case[0] == args.case)
    _, phase, first, second = case
    state['stage'] = 'source-import'
    wrapper, boundary, tool = load_source(args.source_checkout)
    state['stage'] = 'custody-enable'
    wrapper.enable_custody()
    state['stage'] = 'fixture-setup'
    root = Path(args.worker_output)
    root.mkdir()
    contract, product_args = fixture_data(root, boundary)
    fixture_before = inventory(root)
    state['stage'] = 'owner-setup'
    owner = wrapper.WrapperRun()
    real = dict(mask=signal.pthread_sigmask, install=signal.signal, pending=signal.sigpending,
                timedwait=signal.sigtimedwait, replace=os.replace, pidfd=os.pidfd_open, close=os.close,
                popen=subprocess.Popen, wait=subprocess.Popen.wait, low_wait=subprocess.Popen._wait)
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
    method_codes = observer_methods(wrapper)
    observer = HandlerObserver(owner, wrapper.WrapperRun.interrupt.__code__, method_codes,
                               counts, max_active, lambda: in_followon)
    wait_frames = []

    def complete_handlers():
        for record in observer.complete():
            callback = signal.getsignal(record['signal'])
            require(getattr(callback, '__self__', None) is owner
                    and getattr(callback, '__func__', None) is wrapper.WrapperRun.interrupt,
                    'callback owner identity differs')
            handler_events.append(record)
            channel.send('handler-return', case=args.case, **record)

    def low_wait(process, timeout):
        frame = sys._getframe(1)
        require(frame.f_code is real['wait'].__code__ and frame.f_locals.get('self') is process,
                'wait caller identity differs')
        if process in processes and not any(previous is frame for previous in wait_frames):
            require(len(wait_frames) < 3, 'wait frame bound exceeded')
            wait_frames.append(frame)
            channel.send('wait-enter', writer=process.pid, phase=owner.phase)
        return real['low_wait'](process, timeout)

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
        complete_handlers()
        require(len(handler_events) == 1 and first not in real['pending'](), 'first delivery not distinct and completed')
        second_rendezvous = True
        channel.send('ready-second', phase=owner.phase, masked=masked, pending=sorted(real['pending']()), owner=id(owner), case=args.case)
        try:
            instruction = channel.receive(checkpoint=None if masked else complete_handlers)
        except BaseException as error:
            if masked:
                raise
            sample = second_ack_snapshot(handler_events, sorted(real['pending']()), first, second, phase,
                owner.phase, args.case, (sys.implementation.name, sys.version, sys.executable, sys.flags.optimize))
            state['second_ack_failure'] = sample
            second_ack_diagnostic(sample)
            if isinstance(error, ValueError) and str(error) == 'rendezvous deadline':
                require(sample.count == 2 and not set(owner.signals) & set(sample.pending), 'second handler ACK missing')
            raise
        require(instruction['kind'] == 'continue', 'unexpected controller instruction')
        pending = sorted(real['pending']())
        kernel_events.append(dict(point='second-after-send', pending=pending))
        if masked:
            require(second in pending, 'second signal not kernel pending')
        else:
            sample = second_ack_snapshot(handler_events, pending, first, second, phase, owner.phase, args.case,
                (sys.implementation.name, sys.version, sys.executable, sys.flags.optimize))
            completed = sample.count == 2 and not set(owner.signals) & set(sample.pending)
            if not completed:
                state['second_ack_failure'] = sample
                second_ack_diagnostic(sample)
            require(completed, 'second handler ACK missing')

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
            complete_handlers()
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
    refusal_before = refusal_after = None
    exception = None
    try:
        observer.enable()
        wait_identity = wait_provenance(real['popen'])
        real['popen']._wait = low_wait
        if phase.startswith('caller-'):
            real['mask'](signal.SIG_BLOCK, {first})
            if phase == 'caller-pending':
                channel.pause('caller-pending-ready', signal=first)
            def caller_state():
                return {'mask': sorted(real['mask'](signal.SIG_BLOCK, set())), 'pending': sorted(real['pending']()),
                        'handlers': {str(sig): id(signal.getsignal(sig)) for sig in owner.signals}}
            refusal_before = caller_state()
        state['stage'] = 'execute'
        try:
            owner.execute(product_args)
        except (KeyboardInterrupt, ValueError) as error:
            exception = {'type': type(error).__name__, 'message': str(error)}
            expected = 'already pending' if phase == 'caller-pending' else 'must be unblocked'
            if (phase == 'baseline' or (phase.startswith('caller-') and
                    (not isinstance(error, ValueError) or expected not in str(error))) or
                    (not phase.startswith('caller-') and not isinstance(error, KeyboardInterrupt))):
                state['execute_error'] = error
        state['stage'] = 'validation'
        complete_handlers()
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
        observed_children = children()
        require(not observed_children and owner.writer is None, 'owned closure unproven')
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
        observer.close()
        real['popen']._wait = real['low_wait']
        wait_frames.clear()
        atomic(root / 'result.json', dict(case=args.case, mode='optimized' if sys.flags.optimize else 'normal',
            source=SOURCE_COMMIT, tree=SOURCE_TREE, pid=os.getpid(), session=os.getsid(0), phase=phase,
            first=first, second=second, handlers=handler_events, kernel=kernel_events, counts=counts,
            exception=exception, refusal_before=refusal_before, refusal_after=refusal_after,
            caller_deliveries=callers, caller_restored=True, children=observed_children, writer_none=True, pidfds_closed=True,
            subprocesses_reaped=True, streams_closed=True, post_handoff_io=[], commands=commands,
            native_fds_before=fds_before, native_fds_after=fd_snapshot(),
            observer_closed=True, wait_hook_restored=real['popen']._wait is real['low_wait'], wait_identity=wait_identity,
            custody=receipts, adapters=list(ADAPTERS), status='PASS', runtime=list(sys.version_info[:3])))
        channel.send('worker-closed', case=args.case, owned_closed=True)
    finally:
        failure_stage = state['stage']
        state['stage'] = 'restoration'
        try:
            observer.close()
        finally:
            real['popen']._wait = real['low_wait']
            wait_frames.clear()
            subprocess.Popen = real['popen']
            signal.signal, signal.pthread_sigmask, signal.sigtimedwait = real['install'], real['mask'], real['timedwait']
            os.replace, os.pidfd_open = real['replace'], real['pidfd']
            for sig, callback in old_handlers.items():
                real['install'](sig, callback)
            real['mask'](signal.SIG_SETMASK, old_mask)
            state['stage'] = failure_stage


def validate_case(receipt, case, mode, pid, events):
    require(case in validate_registry(), 'case registry differs')
    name, phase, first, second = case
    require(receipt.get('phase') == phase and receipt.get('first') == first and receipt.get('second') == second
            and receipt['case'] == name and receipt['mode'] == mode and receipt['pid'] == pid,
            'case/mode/PID identity differs')
    require(receipt['source'] == SOURCE_COMMIT and receipt['tree'] == SOURCE_TREE, 'receipt source differs')
    require(receipt['status'] == 'PASS' and receipt['runtime'] == [3, 12, 3], 'incomplete case')
    require(receipt['children'] == [] and all(receipt[key] is True for key in
        ('writer_none', 'pidfds_closed', 'subprocesses_reaped', 'streams_closed', 'caller_restored',
         'observer_closed', 'wait_hook_restored'))
        and receipt['post_handoff_io'] == [], 'false closure')
    require(receipt['adapters'] == list(ADAPTERS), 'adapter inventory differs')
    validate_wait_provenance(receipt['wait_identity'])
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
    acks = [{key: value for key, value in event.items() if key not in ('kind', 'pid', 'seq', 'case')}
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
    source_before = git_identity(args.source_checkout, (SOURCE_COMMIT, SOURCE_TREE), receipts=output / 'source-before-git')
    controller_before = git_identity(controller_root, receipts=output / 'controller-before-git')
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
        diagnostic('worker-launch', mode=mode, case=name, argv=command)
        events, held_fd, process, closed = [], None, None, False
        launched_at = time.monotonic()
        with log_path.open('wb') as log:
            try:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log,
                                           pass_fds=(worker_input, worker_output), start_new_session=True)
                diagnostic('worker-started', mode=mode, case=name, pid=process.pid)
                held_fd = os.pidfd_open(process.pid)
                os.close(worker_input)
                os.close(worker_output)
                channel = Channel(incoming, outgoing)
                ready_writer = waiting_writer = None
                first_sent = False
                completions, second_sent = [], False
                serial = 0
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
                    if kind != 'writer-ready':
                        serial += 1
                        require(type(event.get('seq')) is int and event['seq'] == serial, 'IPC missing/duplicate/reordered')
                    if kind == 'worker-error':
                        seq = sum(event['pid'] == process.pid and event['kind'] != 'send' for event in events)
                        validate_worker_error(event, name, process.pid, seq)
                        diagnostic('worker-error', mode=mode, **event)
                        raise ValueError('worker reported failure; owned closure unproven')
                    if kind in ('ready-first', 'caller-pending-ready'):
                        send(first)
                        channel.send('continue')
                    elif kind == 'ready-second':
                        require(first_sent and not second_sent and len(completions) == 1, 'second requested before first completion')
                        masked = second_readiness(event, completions[0], case, process.pid)
                        send(second)
                        second_sent = True
                        if masked:
                            channel.send('continue')
                    elif kind == 'handler-return':
                        ordinal = len(completions) + 1
                        require(first_sent and ordinal <= 2 and (ordinal == 1 or
                                second_sent and phase != 'published-masked'), 'unexpected handler completion')
                        first_phase = 'installing' if phase == 'entry' else ('working' if phase == 'working-cleanup' else 'finishing')
                        ack_phase = 'closing' if ordinal == 2 and phase == 'working-cleanup' else first_phase
                        validate_completion(event, pid=process.pid, case=name,
                            owner=completions[0]['owner'] if completions else event.get('owner'),
                            signum=first if ordinal == 1 else second, phase=ack_phase, ordinal=ordinal)
                        completions.append(event)
                        if ordinal == 2:
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
            except BaseException as error:
                try:
                    diagnostic('worker-failure', **controller_context(mode, name, process.pid if process else None, events, error))
                except Exception:
                    pass
                finally:
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
    source_after = git_identity(args.source_checkout, (SOURCE_COMMIT, SOURCE_TREE), receipts=output / 'source-after-git')
    controller_after = git_identity(controller_root, (controller_before['head'], controller_before['tree']),
                                    receipts=output / 'controller-after-git')
    validate_checkout_pair(source_before, source_after, (SOURCE_COMMIT, SOURCE_TREE))
    validate_checkout_pair(controller_before, controller_after, (os.environ.get('GITHUB_SHA'), controller_before['tree']))
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
    choices.add_argument('--profiler-observer-control', action='store_true')
    choices.add_argument('--monitoring-observer-control', action='store_true')
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
    elif args.profiler_observer_control:
        profiler_observer_control(args.source_checkout)
    elif args.monitoring_observer_control:
        monitoring_observer_control(args.source_checkout)
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
