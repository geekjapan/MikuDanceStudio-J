#!/usr/bin/env python3
"""Capture the current repository Windows CMake target's DBVT reference."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LIBS = ('BulletSoftBody', 'BulletDynamics', 'BulletCollision', 'LinearMath')
TUS = ('btDbvt', 'btDbvtBroadphase', 'btCompoundShape', 'btCompoundCollisionAlgorithm', 'scene_create', 'probe')
LIMIT = 32 * 1024 * 1024
spec = importlib.util.spec_from_file_location('consumer_profile', ROOT / 'tools/bullet-dbvt-consumer-profile/check.py')
consumer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(consumer)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def split_command(text):
    """MSVC response files use the Windows backslash-before-quote rules."""
    args, token, quoted, active, i = [], '', False, False, 0
    while i < len(text):
        ch = text[i]
        if ch.isspace() and not quoted:
            if active:
                args.append(token)
            token, active = '', False
            i += 1
            continue
        active = True
        if ch == '\\':
            end = i
            while end < len(text) and text[end] == '\\':
                end += 1
            count = end - i
            if end < len(text) and text[end] == '"':
                token += '\\' * (count // 2)
                if count % 2:
                    token += '"'
                else:
                    quoted = not quoted
                i = end + 1
            else:
                token += '\\' * count
                i = end
        elif ch == '"':
            quoted = not quoted
            i += 1
        else:
            token += ch
            i += 1
    if quoted:
        raise ValueError('unterminated Windows command quote')
    if active:
        args.append(token)
    return args


def decode(data):
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16'), 'utf-16'
    return data.decode('utf-8-sig'), 'utf-8-sig'


def expand(args, cwd, records, stack=()):
    result = []
    for arg in args:
        if not arg.startswith('@'):
            result.append(arg)
            continue
        path = (cwd / arg[1:]).resolve()
        if path in stack or len(stack) >= 8:
            raise ValueError('recursive response file')
        text, encoding = decode(path.read_bytes())
        records.append(dict(path=str(path), encoding=encoding, sha256=digest(path), content=text))
        result.extend(expand(split_command(text), path.parent, records, (*stack, path)))
    return result


def compiler_environment():
    result = {}
    # Unknown options fail without recording their potentially unrelated values.
    pattern = re.compile(r'^[-/](?:D.+|U.+|I.+|FI.+|std:c\+\+\w+|arch:\w+|fp:\w+|O[bdgistxy12-]+|[Mm][DdTt]d?|EH\w+|Zc:[\w+-]+|favor:\w+|openmp(?::\w+)?|utf-8|nologo)$', re.I)
    for key in ('CL', '_CL_'):
        args = split_command(os.environ.get(key, ''))
        if any(not pattern.fullmatch(arg) for arg in args):
            raise ValueError(f'{key} contains an unrecognized compiler option')
        result[key] = args
    return result


def identity():
    event_path = os.environ.get('GITHUB_EVENT_PATH')
    event = json.loads(Path(event_path).read_text()) if event_path else {}
    pr = event.get('pull_request', {})
    data = {k: os.environ.get(k) for k in ('GITHUB_EVENT_NAME', 'GITHUB_SHA', 'GITHUB_REF',
            'GITHUB_REPOSITORY', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB',
            'RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion')}
    for name, value in (('checkout', subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()),
                        ('pr_head', pr.get('head', {}).get('sha')), ('pr_base', pr.get('base', {}).get('sha'))):
        if value is not None and not re.fullmatch(r'[0-9a-f]{40}', value):
            raise ValueError(f'invalid {name} identity')
        data[name] = value
    if not all(data[k] for k in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB', 'GITHUB_SHA')):
        raise ValueError('missing Actions run identity')
    data['parents'] = subprocess.check_output(['git', 'show', '-s', '--format=%P', 'HEAD'], cwd=ROOT).decode().split()
    data['compiler_environment'] = compiler_environment()
    return data


def windows_job(process):
    """Closing the job kills descendants even when their parent already exited."""
    import ctypes
    from ctypes import wintypes

    class Limits(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                    ('flags', wintypes.DWORD), ('minimum', ctypes.c_size_t),
                    ('maximum', ctypes.c_size_t), ('active', wintypes.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                    ('scheduling', wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [('basic', Limits), ('io', ctypes.c_uint64 * 6),
                    ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                    ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = Extended()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(job, int(process._handle)):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel.CloseHandle(job)
        raise error
    return lambda: kernel.CloseHandle(job)


def windows_resume(process):
    """Popen closes its primary thread handle, so reopen it while still suspended."""
    import ctypes
    from ctypes import wintypes

    class ThreadEntry(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD),
                    ('thread', wintypes.DWORD), ('owner', wintypes.DWORD),
                    ('priority', wintypes.LONG), ('delta', wintypes.LONG),
                    ('flags', wintypes.DWORD)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
    kernel.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
    kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenThread.restype = wintypes.HANDLE
    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel.ResumeThread.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    threads = []
    entry = ThreadEntry()
    entry.size = ctypes.sizeof(entry)
    try:
        if not kernel.Thread32First(snapshot, ctypes.byref(entry)):
            raise ctypes.WinError(ctypes.get_last_error())
        while True:
            if entry.owner == process.pid:
                threads.append(entry.thread)
            if not kernel.Thread32Next(snapshot, ctypes.byref(entry)):
                if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                    raise ctypes.WinError(ctypes.get_last_error())
                break
    finally:
        kernel.CloseHandle(snapshot)
    if len(threads) != 1:
        raise ValueError('suspended child must have exactly one primary thread')
    thread = kernel.OpenThread(0x2, False, threads[0])  # THREAD_SUSPEND_RESUME
    if not thread:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        previous = kernel.ResumeThread(thread)
        if previous == 0xffffffff:
            raise ctypes.WinError(ctypes.get_last_error())
        if previous != 1:
            raise ValueError('child primary thread had an unexpected suspend count')
    finally:
        kernel.CloseHandle(thread)


def stop(process):
    if os.name != 'nt':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def build_lines(value):
    pattern = re.compile(
        r'(?i)(?:\b(?:cl|link|lib)\.exe\b|\b(?:Searching|Found|Loaded)\b.*(?:\.lib|\.obj)|'
        r'\.lib\([^\n]*\.obj\)|\b(?:fatal error|error|warning)\s+(?:[A-Z]+\d+|MSB\d+)|'
        r'\b(?:CMake (?:Error|Warning)|ERROR:|ConanException|BUILD FAILED|Build FAILED)|'
        r'\b(?:could not|cannot|failed to)\b.*(?:build|compile|link|open|find)|^\s*Call Stack|^\s+[^=]+\.cmake:\d+)')
    result, cmake_context = [], 0
    for line in value.decode(errors='replace').splitlines():
        recognized = bool(pattern.search(line))
        context = cmake_context > 0 and line.startswith('  ') and '=' not in line and not re.search(r'(?i)secret|token|password|credential', line)
        if recognized or context:
            result.append(line[:4096])
        cmake_context = 4 if re.search(r'(?i)CMake Error', line) else max(0, cmake_context - 1)
    return result


def run(argv, out, name, *, cwd=ROOT, data=None, timeout=300, build=False, env=None):
    argv = list(map(str, argv))
    save(out / (name + '-command.json'), dict(argv=argv, cwd=str(cwd)))
    start = time.monotonic()
    failure = None
    with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        if data is not None:
            if len(data) > LIMIT:
                raise ValueError(f'{name} exceeded input bound')
            stdin.write(data)
            stdin.seek(0)
        if time.monotonic() - start >= timeout:
            raise ValueError(f'{name} exceeded time bound while preparing input')
        process = subprocess.Popen(argv, cwd=cwd, stdin=stdin, stdout=stdout, stderr=stderr, env=env,
                                   start_new_session=os.name != 'nt', creationflags=0x4 if os.name == 'nt' else 0)
        close_job = None
        try:
            if os.name == 'nt':
                close_job = windows_job(process)
                if time.monotonic() - start >= timeout:
                    raise ValueError(f'{name} exceeded time bound before resuming child')
                windows_resume(process)
            while process.poll() is None:
                if time.monotonic() - start >= timeout:
                    failure = 'time'
                    break
                if max(os.fstat(stdout.fileno()).st_size, os.fstat(stderr.fileno()).st_size) > LIMIT:
                    failure = 'output'
                    break
                time.sleep(min(0.02, max(0, timeout - (time.monotonic() - start))))
        finally:
            try:
                if close_job:
                    close_job()
            finally:
                try:
                    stop(process)
                finally:
                    if os.name == 'nt':
                        process._handle.Close()
        stdout.seek(0); stderr.seek(0)
        outputs = (stdout.read(LIMIT + 1), stderr.read(LIMIT + 1))
    if any(len(value) > LIMIT for value in outputs):
        failure = 'output'
    for suffix, value in zip(('stdout', 'stderr'), outputs):
        value = value[:LIMIT]
        if build:
            lines = build_lines(value)
            value = ('\n'.join(lines) + '\n').encode()
            for line in lines:
                print(line, flush=True)
        (out / (name + '.' + suffix)).write_bytes(value)
    evidence = str(out / (name + '.stdout')) + ' and ' + str(out / (name + '.stderr'))
    if failure:
        raise ValueError(f'{name} exceeded {failure} bound; inspect {evidence}')
    if process.returncode:
        raise RuntimeError(f'{name} exited {process.returncode}; inspect {evidence}')
    return outputs[0]


def tlog_commands(path, *, reads=False):
    text, _ = decode(path.read_bytes())
    records = []
    for line in text.splitlines():
        if line.startswith('^'):
            records.append((line[1:].split('|'), []))
        elif line.strip():
            if not records:
                raise ValueError('command tlog lacks source association')
            if reads:
                records[-1][1].append(line.strip())
            elif records[-1][1]:
                raise ValueError('multiple command lines in one tlog task')
            else:
                records[-1][1].extend(split_command(line))
    return records


def compile_source_index(args, source, cwd):
    operands = []
    skip_next = False
    for index, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg.startswith(('/Tc', '/Tp', '/TC', '/TP', '-Tc', '-Tp', '-TC', '-TP')):
            raise ValueError('unsupported explicit CL source mode')
        if arg in ('/D', '/U', '/I', '/FI', '/Fo', '/Fd', '/Fe', '/Fa', '/Fi', '/Fp', '/Yu', '/Yc'):
            skip_next = True
        elif arg.startswith(('/D', '/U', '/I', '/FI', '/Fo', '/Fd', '/Fe', '/Fa', '/Fi', '/Fp', '/Yu', '/Yc')):
            continue
        elif arg.lower().endswith(('.cpp', '.c', '.cxx', '.cc', '.c++')):
            operands.append(index)
    if len(operands) != 1:
        raise ValueError('actual CL command must contain exactly one source operand')
    index = operands[0]
    if (Path(cwd) / args[index]).resolve() != (Path(cwd) / source).resolve():
        raise ValueError('actual CL source operand does not match caret full path')
    return index


def preprocess_args(args, source, *, cwd=None):
    source_index = compile_source_index(args, source, Path.cwd() if cwd is None else cwd)
    result = []
    skip_next = False
    for index, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg.lower() in ('/fo', '/fd', '/fe', '/fa', '/fi'):
            # /FI is forced include; /Fi is preprocessor output. Preserve case.
            if arg == '/FI':
                result.append(arg)
                continue
            skip_next = True
            continue
        if index == source_index or arg in ('/c', '/E', '/EP', '/P', '/showIncludes') or arg.startswith(('/Fo', '/Fd', '/Fe', '/Fa', '/Fi')):
            continue
        result.append(arg)
    return [*result, '/E', '/showIncludes', args[source_index]]


def policy_flags(args):
    result = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ('/D', '/U', '/FI', '/I'):
            if i + 1 == len(args):
                raise ValueError('compiler option is missing its value')
            arg += args[i + 1]
            i += 1
        if arg.startswith(('/D', '/U')):
            name = arg[2:].split('=', 1)[0]
            if name in ('WIN32', '_WIN32', '_WIN64', 'BT_USE_SSE', 'BT_USE_DOUBLE_PRECISION', 'BT_HAS_ALIGNED_ALLOCATOR') or name.startswith('DBVT_'):
                result.append(arg)
        elif arg.startswith(('/fp:', '/arch:', '/std:', '/FI')):
            result.append(arg)
        i += 1
    return result


def source_manifest():
    paths = ('recipes/bullet275', 'rust/crates/mds-bullet/src/core', 'rust/crates/mds-crtmath',
             'tools/bullet-dbvt-consumer-profile', 'tools/bullet-rust-dbvt-check/math-dependency',
             'tools/bullet-dbvt-cmake-reference', 'profiles', 'CMakeLists.txt', 'conanfile.py',
             '.github/workflows/windows-build.yml', 'rust/Cargo.lock', 'rust/rust-toolchain.toml')
    files = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z', *paths], cwd=ROOT).decode().split('\0')
    return {p: digest(ROOT / p) for p in sorted(files) if p and (ROOT / p).is_file()}


def prepare(out):
    save(out / 'identity.json', identity())
    save(out / 'source-start.json', source_manifest())
    home = Path(os.environ['CONAN_HOME']).resolve()
    if home.exists():
        raise ValueError('CONAN_HOME already exists; a fresh job-owned cache is required')
    if home.parent != Path(os.environ['RUNNER_TEMP']).resolve():
        raise ValueError('CONAN_HOME must be directly inside RUNNER_TEMP')
    run(['conan', 'profile', 'detect', '--force'], out, 'conan-profile')
    common = ['--profile:all', 'profiles/x64', '-s', 'compiler.cppstd=17', '-s', 'build_type=Release', '--build=missing', '--lockfile=']
    run(['conan', 'create', 'recipes/bullet275', *common, '-c', 'tools.build:verbosity=verbose'], out, 'conan-create', build=True, timeout=900)
    graph = run(['conan', 'install', '.', *common, '--output-folder=out/ci', '--format=json'], out, 'conan-install', timeout=600)
    save(out / 'conan-graph.json', json.loads(graph))
    run(['conan', '--version'], out, 'conan-version')
    run(['cmake', '--version'], out, 'cmake-version')
    profile = home / 'profiles/default'
    shutil.copyfile(profile, out / 'conan-default-profile.txt')


def package_paths(graph, out):
    nodes = graph['graph']['nodes']
    matches = [node for node in nodes.values() if str(node.get('ref', '')).startswith('bullet275/2.75#') and node.get('context') == 'host']
    if len(matches) != 1:
        raise ValueError('graph does not resolve exactly one host bullet275 package')
    node = matches[0]
    recipe_ref = str(node['ref']).split('%', 1)[0]
    ref = f"{recipe_ref}:{node['package_id']}#{node['prev']}"
    result = dict(reference=ref)
    for key, folder in (('package', None), ('build', 'build'), ('source', 'source')):
        command = ['conan', 'cache', 'path', ref if key != 'source' else recipe_ref]
        if folder:
            command += ['--folder', folder]
        result[key] = run(command, out, 'conan-path-' + key).decode().strip()
        if not Path(result[key]).is_dir():
            raise ValueError(f'missing resolved {key} directory')
    if node.get('package_folder') and Path(result['package']).resolve() != Path(node['package_folder']).resolve():
        raise ValueError('graph/cache package path differs')
    result['cache_build'], result['cache_source'] = result['build'], result['source']
    result['build'] = str(Path(result['cache_build']) / 'build')
    cache = Path(result['build']) / 'CMakeCache.txt'
    shutil.copyfile(cache, out / 'native-CMakeCache.txt')
    values = {}
    for number, line in enumerate(cache.read_text().splitlines(), 1):
        match = re.fullmatch(r'([^/#][^:=]*):[^=]+=(.*)', line)
        if match:
            key, value = match.groups()
            if key in values and key in ('CMAKE_GENERATOR', 'CMAKE_GENERATOR_PLATFORM', 'CMAKE_HOME_DIRECTORY'):
                raise ValueError(f'duplicate CMake cache key {key} at line {number}')
            values[key] = value
    if values.get('CMAKE_GENERATOR') != 'Visual Studio 17 2022' or values.get('CMAKE_GENERATOR_PLATFORM') != 'x64':
        raise ValueError('native archive generator or architecture differs')
    result['source'] = values['CMAKE_HOME_DIRECTORY']
    if not Path(result['source']).resolve().is_relative_to(Path(result['cache_build']).resolve()):
        raise ValueError('actual native source is outside resolved build cache')
    result['graph_folders'] = {key: node.get(key) for key in ('package_folder', 'build_folder', 'source_folder')}
    save(out / 'resolved-package.json', result)
    return result


def capture_build_tree(folder, out, label):
    copied = []
    for pattern in ('**/CL.command.1.tlog', '**/CL.read.1.tlog', '**/Lib.command.1.tlog', '**/Lib-link.command.1.tlog', '**/Lib-link.read.1.tlog',
                    '**/link.command.1.tlog', '**/link.read.1.tlog', '**/*.vcxproj', '**/CMakeCXXCompiler.cmake',
                    '**/CMakeCache.txt', '**/conan_toolchain.cmake'):
        for path in folder.glob(pattern):
            if not path.is_file():
                continue
            dest = out / label / path.relative_to(folder)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
            copied.append(str(dest.relative_to(out)))
    if not copied:
        raise ValueError(f'no build metadata for {label}')
    return copied


def archives(paths):
    result = {}
    for name in LIBS:
        package = Path(paths['package']) / 'lib' / (name + '.lib')
        build = Path(paths['build']) / name / 'Release' / (name + '.lib')
        if digest(package) != digest(build):
            raise ValueError(f'build/package archive differs for {name}')
        result[name] = dict(package=str(package.resolve()), build=str(build.resolve()), sha256=digest(package))
    return result


def option(args, prefix):
    values = []
    for i, arg in enumerate(args):
        if arg.startswith(prefix):
            values.append(arg[len(prefix):] or (args[i + 1] if i + 1 < len(args) else ''))
    if len(values) != 1 or not values[0]:
        raise ValueError(f'missing or ambiguous {prefix} output option')
    return values[0]


def archive_members(path):
    data = Path(path).read_bytes()
    if not data.startswith(b'!<arch>\n'):
        raise ValueError('not a COFF archive')
    offset, names, result = 8, b'', []
    while offset < len(data):
        header = data[offset:offset + 60]
        if len(header) != 60 or header[58:60] != b'`\n':
            raise ValueError('malformed archive header')
        size = int(header[48:58])
        if size < 0:
            raise ValueError('negative archive member size')
        body = data[offset + 60:offset + 60 + size]
        if len(body) != size:
            raise ValueError('truncated archive member')
        name = header[:16].decode('ascii').strip()
        if name == '//':
            names = body
        elif name != '/':
            if re.fullmatch(r'/[0-9]+', name):
                index = int(name[1:])
                if index >= len(names) or (index and names[index - 1] not in (0, 10)):
                    raise ValueError('invalid archive long-name offset')
                tail = names[index:]
                name = re.split(b'\x00|/\n', tail, maxsplit=1)[0].decode('utf-8')
            else:
                name = name.rstrip('/')
            result.append(dict(name=name, sha256=hashlib.sha256(body).hexdigest()))
        offset += 60 + size + size % 2
    if offset != len(data):
        raise ValueError('invalid archive alignment')
    return result


def compile_record(folder, name, out):
    matches = []
    for path in folder.glob('**/CL.command.1.tlog'):
        for sources, args in tlog_commands(path):
            for source in sources:
                if Path(source).stem.lower() == name.lower():
                    if len(sources) != 1:
                        raise ValueError('actual CL caret must identify exactly one source')
                    matches.append((path, source, args))
    if len(matches) != 1:
        raise ValueError(f'expected one actual compile command for {name}, found {len(matches)}')
    tlog, source, args = matches[0]
    cwd = next((p for p in tlog.parents if list(p.glob('*.vcxproj'))), None)
    if cwd is None or not cwd.is_relative_to(folder):
        raise ValueError(f'unresolved MSBuild project directory for {name}')
    source = (cwd / source).resolve()
    if not source.is_file():
        raise ValueError(f'actual {name} source is missing')
    responses = []
    args = expand(args, cwd, responses)
    compile_source_index(args, source, cwd)
    output = option(args, '/Fo')
    obj = (cwd / output).resolve()
    if output.endswith(('\\', '/')) or obj.is_dir():
        obj = obj / (source.stem + '.obj')
    if not obj.is_file():
        raise ValueError(f'actual {name} compiler output is missing: {obj}')
    return dict(argv=args, source=str(source), source_sha256=digest(source), cwd=str(cwd),
                tlog=str(tlog), responses=responses, object=str(obj), object_sha256=digest(obj))


def archive_commands(native, out, libs):
    result = {}
    compiles = {name: compile_record(native, name, out) for name in ('btDbvt', 'btDbvtBroadphase')}
    for name in LIBS:
        project = native / name
        logs = [p for p in project.glob('**/*.command.1.tlog') if p.name.lower() in ('lib.command.1.tlog', 'lib-link.command.1.tlog')]
        if len(logs) != 1:
            raise ValueError(f'missing or ambiguous actual librarian command for {name}')
        _, encoding = decode(logs[0].read_bytes())
        tasks = tlog_commands(logs[0])
        if len(tasks) != 1:
            raise ValueError(f'ambiguous actual librarian task for {name}')
        records = []
        args = expand(tasks[0][1], project, records)
        if (project / option(args, '/OUT:')).resolve() != Path(libs[name]['build']).resolve():
            raise ValueError(f'librarian output does not match resolved {name} archive')
        inputs = [(project / arg).resolve() for arg in args if arg.lower().endswith('.obj')]
        if not inputs or any(not obj.is_file() for obj in inputs):
            raise ValueError(f'librarian {name} has missing object inputs')
        if len(set(inputs)) != len(inputs):
            raise ValueError(f'librarian {name} repeats object inputs')
        entry = dict(tlog=str(logs[0]), argv=args, cwd=str(project), encoding=encoding, responses=records,
                     inputs={str(obj): digest(obj) for obj in inputs}, archive_sha256=digest(libs[name]['build']))
        if name == 'BulletCollision':
            members = archive_members(libs[name]['build'])
            association = {}
            for stem, record in compiles.items():
                obj = Path(record['object'])
                same_name = [item for item in inputs if item.name.lower() == obj.name.lower()]
                if same_name != [obj]:
                    raise ValueError(f'librarian input does not uniquely match {stem} compiler output')
                matching = [m for m in members if Path(m['name'].replace('\\', '/')).name.lower() == obj.name.lower()]
                if len(matching) != 1 or (project / matching[0]['name'].replace('\\', '/')).resolve() != obj:
                    raise ValueError(f'archive member path does not uniquely match {stem} librarian input')
                if matching[0]['sha256'] != record['object_sha256']:
                    raise ValueError(f'archive member bytes differ from {stem} compiler output')
                association[stem] = dict(compile=record, member=matching[0])
                dest = out / 'archives' / obj.name
                dest.parent.mkdir(exist_ok=True)
                shutil.copyfile(obj, dest)
            entry['dbvt_objects'] = association
        result[name] = entry
    save(out / 'archive-commands.json', result)
    return result


def link_proof(build, label, out, libs):
    target = 'dbvt_cmake_reference' if label == 'probe' else 'MikuDanceStudio'
    candidates = [p for p in build.glob('**/link.command.1.tlog')
                  if any(part.lower() == target.lower() + '.dir' for part in p.relative_to(build).parts)]
    if len(candidates) != 1:
        raise ValueError(f'ambiguous actual {label} link command')
    tlog = candidates[0]
    records = tlog_commands(tlog)
    if len(records) != 1:
        raise ValueError(f'ambiguous actual {label} linker task')
    sources, args = records[0]
    responses = []
    expanded = expand(args, build, responses)
    exe = (build / option(expanded, '/OUT:')).resolve()
    map_path = (build / option(expanded, '/MAP:')).resolve()
    if exe != (build / 'Release' / (target + '.exe')).resolve() or not exe.is_file():
        raise ValueError(f'{label} linker output is not the exact target executable')
    if not map_path.is_relative_to(build.resolve()) or not map_path.is_file():
        raise ValueError(f'{label} target-specific map is missing')
    normalized = [arg.replace('\\', '/').lower() for arg in expanded]
    read_records = tlog_commands(tlog.with_name('link.read.1.tlog'), reads=True)
    if len(read_records) != 1 or [s.lower() for s in read_records[0][0]] != [s.lower() for s in sources]:
        raise ValueError(f'{label} linker read task does not match command task')
    reads = [arg.replace('\\', '/').lower() for arg in read_records[0][1]]
    for name, entry in libs.items():
        path = entry['package'].replace('\\', '/').lower()
        for values in (normalized, reads):
            matches = [v for v in values if v.endswith('/' + name.lower() + '.lib') or v == name.lower() + '.lib']
            if matches != [path]:
                raise ValueError(f'{label} did not uniquely link/read resolved {name} archive')
        if digest(entry['package']) != entry['sha256']:
            raise ValueError(f'{label} archive bytes changed')
    text = map_path.read_text(errors='strict')
    if not text.splitlines() or text.splitlines()[0].strip().lower() != target.lower():
        raise ValueError(f'{label} map target identity differs')
    for member in ('btDbvt', 'btDbvtBroadphase'):
        pattern = r'(?im)^.*\sBulletCollision(?:\.lib)?:' + member + r'\.obj\s*$'
        if not re.search(pattern, text):
            raise ValueError(f'{label} target map lacks unambiguous archive member {member}')
    probe_compile = None
    if label == 'probe':
        probe_compile = compile_record(build, 'probe', out)
        obj = Path(probe_compile['object'])
        inputs = [(build / arg).resolve() for arg in expanded if arg.lower().endswith('.obj')]
        read_objects = [(build / arg).resolve() for arg in read_records[0][1] if arg.lower().endswith('.obj')]
        if inputs.count(obj) != 1 or read_objects.count(obj) != 1:
            raise ValueError('probe compiler output is not the exact linker input/read object')
    shutil.copyfile(map_path, out / (label + '-link.map'))
    proof = dict(tlog=str(tlog), argv=expanded, responses=responses, libraries=libs,
                 executable=str(exe), executable_sha256=digest(exe), map=str(map_path), map_sha256=digest(map_path),
                 members=['btDbvt.obj', 'btDbvtBroadphase.obj'], probe_compile=probe_compile)
    save(out / (label + '-link.json'), proof)
    return proof


def developer_environment(compiler, out, name):
    compiler = Path(compiler)
    vs = next((parent for parent in compiler.parents if (parent / 'Common7/Tools/VsDevCmd.bat').is_file()), None)
    if vs is None:
        raise ValueError('cannot resolve compiler developer environment')
    script = out / 'compiler-environment.py'
    script.write_text('import json, os\nprint(json.dumps({k:os.environ.get(k, "") for k in ("INCLUDE", "LIB", "LIBPATH", "PATH")}))\n')
    command = 'call "' + str(vs / 'Common7/Tools/VsDevCmd.bat') + '" -no_logo -arch=x64 -host_arch=x64 >nul && "' + sys.executable + '" "' + str(script) + '"'
    result = subprocess.run(['cmd.exe', '/d', '/s', '/c', command], capture_output=True, timeout=30, check=True)
    environment = json.loads(result.stdout.decode())
    save(out / (name + '-replay-include-paths.json'), environment['INCLUDE'].split(';'))
    msbuild = vs / 'MSBuild/Current/Bin/MSBuild.exe'
    if not (out / 'msbuild-version.stdout').is_file():
        run([msbuild, '/version', '/nologo'], out, 'msbuild-version', timeout=30)
    return dict(os.environ, **environment)


def capture_tu(folder, name, out):
    record = compile_record(folder, name, out)
    tlog, source, cwd = Path(record['tlog']), Path(record['source']), Path(record['cwd'])
    args = record['argv']
    compilers = list(folder.glob('**/CMakeCXXCompiler.cmake'))
    values = set()
    for path in compilers:
        found = re.search(r'set\(CMAKE_CXX_COMPILER "([^"]+)"\)', path.read_text())
        if found:
            values.add(found[1])
    if len(values) != 1:
        raise ValueError(f'unresolved compiler for {name}')
    compiler = values.pop()
    build_name = 'app-build' if name == 'scene_create' else 'probe-build' if name == 'probe' else 'conan-create'
    command_log = ''.join((out / (build_name + '.' + stream)).read_text() for stream in ('stdout', 'stderr'))
    if compiler.replace('\\', '/').lower() not in command_log.replace('\\', '/').lower():
        raise ValueError(f'{name} compiler path lacks actual build command evidence')
    save(out / (name + '-actual-command.json'), dict(record, compiler=compiler, compiler_sha256=digest(compiler)))
    # /Bv with /E reports the version while preserving the actual TU flags.
    argv = [compiler, *preprocess_args(args, source, cwd=cwd), '/Bv']
    run(argv, out, name + '-preprocess', cwd=cwd, timeout=90, env=developer_environment(compiler, out, name))
    text = (out / (name + '-preprocess.stdout')).read_text(errors='strict')
    profile, extracts = consumer.classify(text, cpp=name == 'btDbvt')
    save(out / (name + '-branches.json'), dict(profile=profile, extracts=extracts))
    headers = set()
    for line in text.splitlines():
        found = re.match(r'\s*#(?:line)?\s+\d+\s+"([^"]+)"', line)
        if found and Path(found[1]).is_file():
            headers.add(Path(found[1]))
    for stream in ('stdout', 'stderr'):
        for line in (out / (name + '-preprocess.' + stream)).read_text(errors='replace').splitlines():
            found = re.search(r'Note: including file:\s*(.+)', line)
            if found and Path(found[1].strip()).is_file():
                headers.add(Path(found[1].strip()))
    if not any(p.name.lower() == 'btdbvt.h' for p in headers):
        raise ValueError(f'missing actual header closure for {name}')
    readlog = tlog.with_name('CL.read.1.tlog')
    read_tasks = [(sources, reads) for sources, reads in tlog_commands(readlog, reads=True)
                  if any((cwd / item).resolve() == source for item in sources)]
    if len(read_tasks) != 1 or len(read_tasks[0][0]) != 1:
        raise ValueError(f'{name} requires exactly one matching CL read task')
    actual_headers = {str((cwd / item).resolve()).lower() for item in read_tasks[0][1]
                      if Path(item).suffix.lower() in ('.h', '.hpp', '.hxx', '.inl') and (cwd / item).is_file()}
    replay_headers = {str(p.resolve()).lower() for p in headers}
    if not actual_headers or not actual_headers <= replay_headers:
        raise ValueError(f'{name} replay does not cover actual compiler header reads')
    save(out / (name + '-closure.json'), {str(p): digest(p) for p in sorted(headers)})
    return profile


def validate_closure(out, paths):
    root = ROOT / 'recipes/bullet275/bullet-src/src'
    actual = {}
    for name in TUS:
        command = json.loads((out / (name + '-actual-command.json')).read_text())
        actual[command['source']] = command['source_sha256']
        actual.update(json.loads((out / (name + '-closure.json')).read_text()))
    association = {}
    for filename, sha in actual.items():
        path = Path(filename)
        for prefix in (Path(paths['source']) / 'bullet-src/src', Path(paths['package']) / 'include'):
            try:
                relative = path.relative_to(prefix)
            except ValueError:
                continue
            original = root / relative
            if not original.is_file() or original.read_bytes().replace(b'\r\n', b'\n') != path.read_bytes().replace(b'\r\n', b'\n'):
                raise ValueError(f'actual native source differs from checkout: {relative}')
            association[filename] = dict(checkout=str(original.relative_to(ROOT)), actual_sha256=sha, checkout_sha256=digest(original))
    if not all(any(Path(path).name.lower() == name.lower() + '.cpp' for path in association) for name in TUS[:4]):
        raise ValueError('incomplete native source association')
    save(out / 'native-source-association.json', association)
    return association


def input_words():
    base = [0, 0, 0, 0x3f800000, 0x3f800000, 0x3f800000]
    cases = [base + base, base + [0x3f800000, 0, 0, 0x40000000, 0x3f800000, 0x3f800000], base + [0x40000000] * 6]
    for bits in (0, 0x80000000, 0x7fc00001, 0x7fc00002):
        for operand in range(2):
            for lane in range(6):
                pair = base + base
                pair[operand * 6 + lane] = bits
                cases.append(pair)
    return cases


def rows(data, width):
    lines = data.decode('ascii').splitlines()
    if len(lines) != 51:
        raise ValueError('incomplete runtime capture')
    result = []
    for index, line in enumerate(lines):
        if not re.fullmatch(r'[0-9]+(?:,[0-9]+)*', line):
            raise ValueError('malformed runtime words')
        words = list(map(int, line.split(',')))
        if len(words) != width + 1 or words[0] != index or any(w > 0xffffffff for w in words):
            raise ValueError('runtime words outside schema')
        result.append(words[1:])
    return result


RUST_DRIVER = r'''
#[path = "DBVT"] mod dbvt;
#[path = "PAIR_CACHE"] mod pair_cache;
use dbvt_math as math;
use std::io::{self, Read};
fn main() {
    if std::env::args().nth(1).as_deref() == Some("select") {
        let mut tree = dbvt::Dbvt::new();
        for (i, p) in [[0.5, 8388608.0, 0.5], [1.0, 8388608.0, 0.0], [0.0; 3]].into_iter().enumerate() {
            tree.insert(pair_cache::ProxyKey(i as u32 + 1), dbvt::Aabb { min: math::Vec3(p), max: math::Vec3(p) });
        }
        tree.collide_volume(dbvt::Aabb { min: math::Vec3([-1.0; 3]), max: math::Vec3([2.0, 8388609.0, 2.0]) }, |key| print!("{},", key.0));
        println!();
        return;
    }
    let mut input = String::new(); io::stdin().read_to_string(&mut input).unwrap();
    let words: Vec<u32> = input.split_whitespace().map(|s| s.parse().unwrap()).collect();
    assert_eq!(words.len(), 51 * 12);
    for (id, row) in words.chunks_exact(12).enumerate() {
        let bounds: Vec<_> = row.chunks_exact(6).map(|v| dbvt::Aabb {
            min: math::Vec3(std::array::from_fn(|i| f32::from_bits(v[i]))),
            max: math::Vec3(std::array::from_fn(|i| f32::from_bits(v[i+3]))) }).collect();
        let (a, b) = (bounds[0], bounds[1]);
        print!("{},{}", id, a.intersects(b) as u32);
        for v in [a.merge(b), b.merge(a)] { for f in v.min.0.into_iter().chain(v.max.0) { print!(",{}", f.to_bits()); } }
        println!();
    }
}
'''


def rust_probe(out, data):
    folder = out / 'rust-driver'
    folder.mkdir()
    core = ROOT / 'rust/crates/mds-bullet/src/core'
    source = RUST_DRIVER.replace('DBVT', (core / 'dbvt.rs').as_posix()).replace('PAIR_CACHE', (core / 'pair_cache.rs').as_posix())
    (folder / 'main.rs').write_text(source)
    dependency = (ROOT / 'tools/bullet-rust-dbvt-check/math-dependency').as_posix()
    (folder / 'Cargo.toml').write_text('[package]\nname="cmake-dbvt-rust-reference"\nversion="0.0.0"\nedition="2021"\n[workspace]\n[dependencies]\ndbvt-math={path=' + json.dumps(dependency) + '}\n[[bin]]\nname="cmake-dbvt-rust-reference"\npath="main.rs"\n')
    run(['rustup', 'run', '1.95.0', 'rustc', '-Vv'], out, 'rust-version', cwd=ROOT / 'rust')
    run(['rustup', 'run', '1.95.0', 'cargo', 'build', '--release', '--manifest-path', folder / 'Cargo.toml'], out, 'rust-build', cwd=ROOT / 'rust', timeout=600)
    exe = folder / 'target/release/cmake-dbvt-rust-reference.exe'
    shutil.copyfile(exe, out / 'cmake-dbvt-rust-reference.exe')
    save(out / 'rust-binary.json', dict(path=str(exe), sha256=digest(exe), source='rust-driver/main.rs',
         source_sha256=digest(folder / 'main.rs'), build_command='rust-build-command.json', version='rust-version.stdout'))
    return run([exe, 'select'], out, 'rust-select', timeout=10), rows(run([exe, 'aabb'], out, 'rust-aabb', data=data, timeout=10), 13)


def comparison_report(selected, aabb, merged, intersected, rust_selected, rust):
    comparisons = dict(select=selected.splitlines() == rust_selected.splitlines(),
        inline_aabb=aabb == rust, archive_merge=merged == [row[7:13] + row[1:7] for row in rust],
        archive_intersect=intersected == [[row[0]] for row in rust])
    return dict(observation='complete', compatibility='PASS' if all(comparisons.values()) else 'FAIL',
        classification='compatible' if all(comparisons.values()) else 'compatibility-mismatch',
        archive_merge_columns=['insert_A_then_B__Merge_B_A', 'insert_B_then_A__Merge_A_B'],
        comparisons=comparisons, different_cases=dict(
            inline_aabb=[i for i in range(51) if aabb[i] != rust[i]],
            archive_merge=[i for i in range(51) if merged[i] != rust[i][7:13] + rust[i][1:7]],
            archive_intersect=[i for i in range(51) if intersected[i] != [rust[i][0]]]))


def measure(out):
    report = dict(observation='incomplete', compatibility='not-evaluated', classification='validation-gap', reference='current repository Windows CMake target, not a shipped MMD binary')
    try:
        report['identity'] = json.loads((out / 'identity.json').read_text())
        if report['identity'] != identity():
            raise ValueError('checkout or event identity changed')
        paths = package_paths(json.loads((out / 'conan-graph.json').read_text()), out)
        libs = archives(paths)
        report['archives_before'] = libs
        for name, entry in libs.items():
            dest = out / 'archives' / (name + '.lib')
            dest.parent.mkdir(exist_ok=True)
            shutil.copyfile(entry['package'], dest)
        native, app, probe = Path(paths['build']), ROOT / 'out/ci/build', ROOT / 'out/ci/dbvt-probe'
        toolchain = app / 'generators/conan_toolchain.cmake'
        capture_build_tree(native, out, 'native-build-metadata')
        report['librarian_commands'] = archive_commands(native, out, libs)
        report['archive_objects'] = report['librarian_commands']['BulletCollision']['dbvt_objects']
        capture_build_tree(app, out, 'app-build-metadata')
        run(['cmake', '-S', HERE, '-B', probe, '-G', 'Visual Studio 17 2022', '-A', 'x64', f'-DCMAKE_TOOLCHAIN_FILE={toolchain}'], out, 'probe-configure')
        run(['cmake', '--build', probe, '--config', 'Release', '--parallel', '4', '--', '/verbosity:normal', '/clp:ShowCommandLine'], out, 'probe-build', build=True, timeout=300)
        capture_build_tree(probe, out, 'probe-build-metadata')
        report['links'] = {label: link_proof(folder, label, out, libs) for label, folder in (('app', app), ('probe', probe))}
        profiles = {name: capture_tu(app if name == 'scene_create' else probe if name == 'probe' else native, name, out) for name in TUS}
        report['profiles'] = profiles
        report['source_association'] = validate_closure(out, paths)
        environment = report['identity']['compiler_environment']
        flags = {name: policy_flags([*environment['CL'], *json.loads((out / (name + '-actual-command.json')).read_text())['argv'], *environment['_CL_']]) for name in TUS}
        report['ordered_dbvt_policy_flags'] = flags
        if any(value != flags['btDbvt'] for value in flags.values()):
            raise ValueError('actual TUs differ in ordered DBVT, FP, architecture, standard, or forced-include flags')
        inline = [{k: v for k, v in profile.items() if not k.endswith('_local')} for profile in profiles.values()]
        if any(profile != inline[0] for profile in inline):
            raise ValueError('actual translation units disagree on inline DBVT policy')
        data = ('\n'.join(' '.join(map(str, case)) for case in input_words()) + '\n').encode()
        (out / 'aabb-inputs.tsv').write_bytes(data)
        exe = probe / 'Release/dbvt_cmake_reference.exe'
        app_exe = app / 'Release/MikuDanceStudio.exe'
        control_exe = probe / 'Release/dbvt_insert_order_control.exe'
        report['binaries'] = {str(p): digest(p) for p in (exe, app_exe, control_exe)}
        for label, binary in (('probe', exe), ('app', app_exe)):
            if report['binaries'][str(binary)] != report['links'][label]['executable_sha256']:
                raise ValueError(f'{label} binary changed after target link association')
        probe_command = json.loads((out / 'probe-actual-command.json').read_text())
        if probe_command['object_sha256'] != report['links']['probe']['probe_compile']['object_sha256']:
            raise ValueError('probe object changed after target link association')
        shutil.copyfile(exe, out / 'dbvt_cmake_reference.exe')
        shutil.copyfile(control_exe, out / 'dbvt_insert_order_control.exe')
        run([control_exe], out, 'native-insert-order-control', timeout=10)
        selected = run([exe, 'select'], out, 'archive-select', timeout=10)
        consumer.validate_select(selected)
        aabb = rows(run([exe, 'aabb'], out, 'probe-inline-aabb', data=data, timeout=10), 13)
        merged = rows(run([exe, 'archive-merge'], out, 'archive-merge', data=data, timeout=10), 12)
        intersected = rows(run([exe, 'archive-intersect'], out, 'archive-intersect', data=data, timeout=10), 1)
        if any(row[0] not in (0, 1) for row in aabb + intersected):
            raise ValueError('invalid Intersect boolean')
        rust_selected, rust = rust_probe(out, data)
        consumer.validate_select(rust_selected)
        report['rust_binary'] = json.loads((out / 'rust-binary.json').read_text())
        if digest(report['rust_binary']['path']) != report['rust_binary']['sha256']:
            raise ValueError('Rust executable changed during observation')
        if any(digest(p) != sha for p, sha in report['binaries'].items()):
            raise ValueError('native executable changed during observation')
        for name in TUS:
            closure = json.loads((out / (name + '-closure.json')).read_text())
            if any(digest(Path(p)) != sha for p, sha in closure.items()):
                raise ValueError(f'{name} header closure changed during observation')
            command = json.loads((out / (name + '-actual-command.json')).read_text())
            if digest(Path(command['source'])) != command['source_sha256']:
                raise ValueError(f'{name} source changed during observation')
        report['archives_after'] = archives(paths)
        if report['archives_after'] != libs:
            raise ValueError('archives changed during probe')
        report.update(comparison_report(selected, aabb, merged, intersected, rust_selected, rust))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        report['failure'] = str(error)
    finally:
        report['source_sha256'] = source_manifest()
        start = json.loads((out / 'source-start.json').read_text()) if (out / 'source-start.json').is_file() else None
        if report['source_sha256'] != start:
            report.update(observation='incomplete', compatibility='not-evaluated', classification='validation-gap', failure='protected source changed or start manifest missing')
        report['artifact_sha256'] = {str(p.relative_to(out)): digest(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'report.json' and 'target' not in p.relative_to(out).parts}
        report['artifact_hash_exclusions'] = ['report.json (written after manifest)', 'rust-driver/target (build scratch; executed binary copied and hashed separately)', 'no open log files are included; run() closes streams before finalization']
        save(out / 'report.json', report)
        print(json.dumps({key: report[key] for key in ('observation', 'compatibility', 'classification')}))
    return 0 if report['observation'] == 'complete' and report['compatibility'] == 'PASS' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('mode', choices=('prepare', 'record-build', 'measure'))
    parser.add_argument('--out-dir', type=Path, required=True)
    argv = sys.argv[1:]
    boundary = argv.index('--build-command') if '--build-command' in argv else len(argv)
    command = argv[boundary + 1:]
    args = parser.parse_args(argv[:boundary])
    out = args.out_dir.resolve(); out.mkdir(parents=True, exist_ok=True)
    if args.mode == 'prepare':
        prepare(out)
        return 0
    if args.mode == 'record-build':
        if not command:
            raise ValueError('missing build command')
        run(command, out, 'app-build', build=True, timeout=900)
        return 0
    return measure(out)


if __name__ == '__main__':
    sys.exit(main())
