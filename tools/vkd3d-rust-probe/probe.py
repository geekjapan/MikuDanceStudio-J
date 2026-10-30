#!/usr/bin/env python3
"""Probe an already configured vkd3d tree without changing the input tree.

Translated sources retain vkd3d's LGPL-2.1-or-later terms; this script does
not grant a different license to them. Build artifacts belong outside Git.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import time


def _diagnostic_read(path, limit):
    path = Path(path)
    if not path.is_absolute() or any(part in ('.', '..') for part in path.parts[1:]):
        raise ValueError('unsafe diagnostic path')
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        child = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        try:
            if not stat.S_ISREG(os.fstat(child).st_mode):
                raise ValueError('diagnostic file kind')
            with os.fdopen(child, 'rb', closefd=False) as stream:
                raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise ValueError('diagnostic read limit')
            return raw.decode('utf-8', errors='strict')
        finally:
            os.close(child)
    finally:
        os.close(descriptor)


def _diagnostic_cgroup(cgroup, mountinfo):
    memberships = [line[3:] for line in cgroup.splitlines() if line.startswith('0::')]
    if len(memberships) != 1:
        raise ValueError('ambiguous cgroup membership')

    def absolute(value):
        value = re.sub(r'\\(040|011|012|134)', lambda match: chr(int(match[1], 8)), value)
        if not value.startswith('/') or any(p in ('.', '..') for p in value.split('/')):
            raise ValueError('unsafe cgroup path')
        return Path(value)

    member = absolute(memberships[0])
    candidates = []
    for line in mountinfo.splitlines():
        fields = line.split()
        if '-' not in fields:
            raise ValueError('invalid mountinfo')
        separator = fields.index('-')
        if len(fields) <= separator + 3 or separator < 6:
            raise ValueError('invalid mountinfo fields')
        if fields[separator + 1] != 'cgroup2':
            continue
        root, mount = absolute(fields[3]), absolute(fields[4])
        if member == root or root in member.parents:
            candidates.append(mount / member.relative_to(root))
    if len(candidates) != 1:
        raise ValueError('unresolved or ambiguous cgroup mount')
    return candidates[0]


class _RunDiagnostics:
    INTERVAL = 15.0
    MAX_EVENTS = 512
    MAX_BYTES = 2 * 1024 * 1024
    MAX_EVENT_BYTES = 16 * 1024
    PROC_BYTES = 64 * 1024
    MOUNT_BYTES = 1024 * 1024
    SCALAR_BYTES = 8192

    def __init__(self, settings, cwd):
        self.settings = settings
        self.cwd = cwd
        self.stream = None
        self.disabled = False
        self.warned = False
        self.events = self.bytes = 0
        self.next_sample = None

    def _unknown(self, operation):
        try:
            return operation()
        except Exception:
            return 'UNKNOWN'

    def _resources(self, process, log):
        resources = {}
        if sys.platform.startswith('linux'):
            for role, pid in (('runner', os.getpid()), ('child', process.pid)):
                def read_status():
                    text = _diagnostic_read('/proc/%d/status' % pid, self.PROC_BYTES)
                    allowed = {'State', 'PPid', 'Threads', 'VmRSS', 'VmHWM'}
                    return {key: value.strip() for line in text.splitlines() if ':' in line
                            for key, value in [line.split(':', 1)] if key in allowed}
                resources[role] = self._unknown(read_status)
            def read_cgroup():
                root = _diagnostic_cgroup(
                    _diagnostic_read('/proc/%d/cgroup' % process.pid, self.PROC_BYTES),
                    _diagnostic_read('/proc/%d/mountinfo' % os.getpid(), self.MOUNT_BYTES))
                return dict(scope='whole_cgroup_not_command_or_shutdown_actor_proof', path=str(root),
                    values={name: self._unknown(lambda name=name: _diagnostic_read(root / name, self.SCALAR_BYTES).strip())
                            for name in ('memory.current', 'memory.peak', 'memory.max', 'memory.events')})
            resources['cgroup'] = self._unknown(read_cgroup)
        else:
            resources.update(runner='UNKNOWN', child='UNKNOWN', cgroup='UNKNOWN')
        def free_bytes():
            usage = os.statvfs(log.parent)
            return usage.f_bavail * usage.f_frsize
        resources['evidence_free_bytes'] = self._unknown(free_bytes)
        return resources

    def emit(self, event, process, command, log, start, usage=None, reap=None):
        if self.disabled:
            return
        try:
            if self.stream is None:
                if (type(self.settings) is not dict or set(self.settings) != {'phase', 'path'}
                        or type(self.settings['phase']) is not str
                        or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', self.settings['phase'])):
                    raise ValueError('invalid diagnostic settings')
                self.stream = Path(self.settings['path']).open('xb')
            now = time.monotonic()
            record = dict(event=event, phase=self.settings['phase'], utc=datetime.now(timezone.utc).isoformat(),
                monotonic=now, elapsed_seconds=now - start, command=command,
                cwd=str(Path(self.cwd).absolute()) if self.cwd is not None else str(Path.cwd()),
                log=str(log), runner_pid=os.getpid(), child_pid=process.pid,
                observed_child_pgid=self._unknown(lambda: os.getpgid(process.pid)),
                observed_child_sid=self._unknown(lambda: os.getsid(process.pid)),
                resources=self._resources(process, log))
            if event == 'start':
                record['limits'] = dict(interval_seconds=self.INTERVAL, events=self.MAX_EVENTS,
                    total_bytes=self.MAX_BYTES, event_bytes=self.MAX_EVENT_BYTES,
                    proc_read_bytes=self.PROC_BYTES, mountinfo_read_bytes=self.MOUNT_BYTES,
                    scalar_read_bytes=self.SCALAR_BYTES)
            if event == 'finish':
                record['wait4_return'] = reap
                record['process_exit_code'] = process.returncode
                record['wait4_resource'] = dict(user_cpu_seconds=usage.ru_utime,
                    system_cpu_seconds=usage.ru_stime, max_rss=usage.ru_maxrss,
                    max_rss_unit='KiB' if sys.platform.startswith('linux') else 'bytes')
            raw = (json.dumps(record, sort_keys=True) + '\n').encode()
            if (self.events >= self.MAX_EVENTS or len(raw) > self.MAX_EVENT_BYTES
                    or self.bytes + len(raw) > self.MAX_BYTES):
                raise ValueError('diagnostic output limit')
            self.stream.write(raw)
            self.stream.flush()
            self.events += 1
            self.bytes += len(raw)
            print('RUN_DIAGNOSTIC ' + raw.decode().rstrip(), file=sys.stderr, flush=True)
            self.next_sample = now + self.INTERVAL
        except Exception:
            self.disabled = True
            if not self.warned:
                self.warned = True
                try:
                    print('RUN_DIAGNOSTIC UNKNOWN diagnostics_disabled', file=sys.stderr, flush=True)
                except Exception:
                    pass

    def close(self):
        if self.stream is not None:
            try:
                self.stream.close()
            except Exception:
                pass


def run(command, log, *, diagnostics=None, retention_log=None, **kwargs):
    timeout = kwargs.pop("timeout", None)
    started = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    timed_out = False
    with log.open("w") as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=True, **kwargs)
        observer = None
        retention = None
        retention_stream = None
        try:
            if retention_log is not None:
                from diagnose_common_plan_retention import RetentionForwarder
                try:
                    retention_stream = retention_log.open('rb')
                    retention = RetentionForwarder(retention_stream, process.pid)
                except OSError:
                    try:
                        print('RETENTION_DIAGNOSTIC_UNAVAILABLE open', flush=True)
                    except OSError:
                        pass
            if diagnostics is not None:
                observer = _RunDiagnostics(diagnostics, kwargs.get('cwd'))
                observer.emit('start', process, command, log, start)
            while True:
                if retention is not None and time.monotonic() >= retention.next_read:
                    retention.drain()
                pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                if pid:
                    process.returncode = os.waitstatus_to_exitcode(status)
                    if observer is not None:
                        observer.emit('finish', process, command, log, start, usage, dict(pid=pid, status=status))
                    break
                if timeout is not None and time.monotonic() - start >= timeout:
                    timed_out = True
                    break
                if (observer is not None and not observer.disabled
                        and time.monotonic() >= observer.next_sample):
                    observer.emit('sample', process, command, log, start)
                time.sleep(0.05)
        finally:
            try:
                if process.returncode is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    reaped_pid, status, usage = os.wait4(process.pid, 0)
                    process.returncode = os.waitstatus_to_exitcode(status)
                    if observer is not None:
                        observer.emit('finish', process, command, log, start, usage, dict(pid=reaped_pid, status=status))
            finally:
                if retention is not None:
                    retention.drain(final=True)
                if retention_stream is not None:
                    try:
                        retention_stream.close()
                    except OSError:
                        pass
                if observer is not None:
                    observer.close()
    return {"command": command, "exit_code": 124 if timed_out else process.returncode,
            "process_exit_code": process.returncode, "log": str(log), "timed_out": timed_out,
            "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
            "wall_seconds": time.monotonic() - start, "user_cpu_seconds": usage.ru_utime,
            "system_cpu_seconds": usage.ru_stime,
            "max_rss_bytes": usage.ru_maxrss * (1024 if sys.platform.startswith("linux") else 1)}


def outcome(result):
    if any(step.get("timed_out") or step["exit_code"] < 0 for step in result.get("syntax", [])):
        return "incomplete"
    if any(step["exit_code"] for step in result.get("syntax", [])):
        return "syntax_failure"
    translation = result.get("transpile")
    if not translation or translation.get("timed_out") or translation["exit_code"] < 0:
        return "incomplete"
    if translation["exit_code"]:
        return "translation_failure"
    if result.get("invalid_output_markers"):
        return "translation_failure"
    if not result.get("complete_translation"):
        return "incomplete"
    if result.get("translation_only"):
        return "translation_only_success"
    if result.get("all_unit_prototype"):
        if result.get("raw_preserved") is False:
            return "incomplete"
        if result.get("working_copy_failure"):
            return "working_copy_failure"
        builds = [result.get(mode + "_build", {}) for mode in ("stable", "working_stable", "bootstrap", "prototype")]
        if not any(build.get("exit_code") == 0 for build in builds):
            return "incomplete" if any(build.get("timed_out") for build in builds) else "compiler_failure"
        if result.get("link", {}).get("status") != "success":
            return "linker_failure"
        return "prototype_success" if result.get("runtime_comparison", {}).get("status") == "success" else "runtime_unverified"
    for mode in ("stable", "bootstrap", "prototype"):
        build = result.get(mode + "_build")
        if build and build["exit_code"] == 0:
            return "success" if mode == "stable" else "prototype_success"
    if any(result.get(mode + "_build", {}).get("timed_out") for mode in ("stable", "bootstrap", "prototype")):
        return "incomplete"
    return "compiler_failure"


def extern_inventory(sources):
    declared, defined = set(), set()
    by_abi = {}
    for text in sources:
        for abi, block in re.findall(r'(?:unsafe )?extern "([^"\n]+)" \{(.*?)^\}', text, re.M | re.S):
            names = set(re.findall(r'\bfn (\w+)', block))
            names.update(re.findall(r'\bstatic (?:mut )?(\w+)', block))
            declared.update(names)
            by_abi.setdefault(abi, {'declared': set(), 'defined': set()})['declared'].update(names)
        for abi, name in re.findall(r'(?:unsafe )?extern "([^"\n]+)" fn (\w+)', text):
            defined.add(name)
            by_abi.setdefault(abi, {'declared': set(), 'defined': set()})['defined'].add(name)
    return {'declared': sorted(declared), 'defined': sorted(defined),
            'unresolved_declared': sorted(declared - defined),
            'by_abi': {abi: {kind: sorted(names) for kind, names in groups.items()}
                       for abi, groups in sorted(by_abi.items())}}


def compilation_entries(source, original, clang, sources=None):
    if sources is None:
        sources = sorted((source / "libs/vkd3d-shader").glob("*.c"))
        sources += sorted((source / "libs/vkd3d-common").glob("*.c"))
    entries = []
    for path in sources:
        flags = ["-DHAVE_CONFIG_H", "-D_WIN32_WINNT=0x0600", "-std=c99"]
        flags += ["-I" + str(source / p) for p in (".", "include", "include/private", "libs/vkd3d-shader")]
        flags += ["-I" + str(original.parent / p / "include") for p in ("hdr", "spv")]
        if path.parent.name == "vkd3d-shader":
            flags += ["-DLIBVKD3D_SHADER_SOURCE", "-DVKD3D_DEBUG_ENV=VKD3D_SHADER_DEBUG"]
        entries.append({"directory": str(source), "file": str(path),
                        "arguments": [str(clang.resolve()), *flags, "-c", str(path)]})
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--c2rust", type=Path, required=True)
    parser.add_argument("--clang", type=Path, required=True)
    parser.add_argument("--all-unit-prototype", action="store_true")
    parser.add_argument("--closed-format-facts", action="store_true", help="Hosted report-only all24 paired compiler extraction")
    parser.add_argument("--native-library", type=Path)
    parser.add_argument("--translation-only", action="store_true", help="Stop after translation and extern inventory")
    parser.add_argument("--filter", help="Regular expression selecting C translation units")
    parser.add_argument("--timeout", type=int, default=300, help="Seconds per tool invocation")
    parser.add_argument("--build-timeout", type=int, default=120, help="Seconds per Rust build")
    parser.add_argument("--rust-toolchain", default="stable")
    args = parser.parse_args()
    if args.closed_format_facts and (args.filter or args.all_unit_prototype or args.translation_only):
        parser.error("closed format facts require an unfiltered report-only phase")
    if args.all_unit_prototype and args.filter:
        parser.error("all-unit prototype cannot use a unit filter")
    original = args.source.resolve()
    artifacts = args.artifacts.resolve()
    if artifacts == original or original in artifacts.parents:
        parser.error("artifacts must be outside the source tree")
    try:
        args.artifacts.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error("artifacts directory must be new; refusing to reuse existing output")
    source = artifacts / "source"
    # Refuse reuse so old Rust files cannot make a failed translation look complete.
    shutil.copytree(original, source)
    sources = sorted((source / "libs/vkd3d-shader").glob("*.c"))
    sources += sorted((source / "libs/vkd3d-common").glob("*.c"))
    required = {"hlsl.tab.c", "hlsl.yy.c", "hlsl.c", "vkd3d_shader_main.c", "debug.c"}
    assert required <= {p.name for p in sources}
    if args.filter:
        sources = [p for p in sources if re.search(args.filter, str(p))]
        if not sources:
            parser.error("filter matched no C sources")
    if args.all_unit_prototype or args.closed_format_facts:
        from full_compiler import UNITS
        if sorted(str(p.relative_to(source)) for p in sources) != list(UNITS):
            parser.error("configured source differs from exact pinned 24-unit inventory")
    entries = compilation_entries(source, original, args.clang, sources)
    database = artifacts / "compile_commands.json"
    database.write_text(json.dumps(entries, indent=2) + "\n")
    result = {"status": "incomplete", "source": str(original), "translation_units": len(sources),
              "rust_toolchain": args.rust_toolchain,
              "input_sha256": {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sources}}
    for directory in [source / "include", source / "libs", original.parent / "hdr/include", original.parent / "spv/include"]:
        result.setdefault("header_sha256", {}).update({str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                                       for p in sorted(directory.rglob("*.h"))})
    def checkpoint():
        (artifacts / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    checkpoint()
    result["syntax"] = []
    for index, entry in enumerate(entries):
        command = entry["arguments"][:-2] + ["-fsyntax-only", entry["file"]]
        result["syntax"].append(run(command, artifacts / f"syntax-{index:02}.log", cwd=source, timeout=min(args.timeout, 120)))
        checkpoint()
    if any(step["exit_code"] for step in result["syntax"]):
        result["status"] = outcome(result)
        checkpoint()
        return
    if args.closed_format_facts:
        from full_compiler import collect_closed_format_facts
        result["closed_format_facts"] = collect_closed_format_facts(
            args.c2rust.resolve().with_name("c2rust-transpile"), database,
            artifacts / "closed-format-facts", run, result["syntax"])
        result["status"] = result["closed_format_facts"]["status"]
        checkpoint()
        return
    output = artifacts / "rust"
    transpiler = args.c2rust.resolve().with_name("c2rust-transpile")
    result["transpile"] = run([str(transpiler), "--fail-on-error", "--disable-rustfmt", "--edition", "2024",
                               "--emit-build-files", "--emit-variadic-inventory", "--output-dir", str(output), str(database)],
                              artifacts / "transpile.log", cwd=source, timeout=args.timeout)
    checkpoint()
    if output.exists():
        shutil.copytree(output, artifacts / "rust-raw")
        result["raw_sha256"] = {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted(output.rglob("*")) if p.is_file()}
    shutil.copy2(source / "LICENSE", artifacts / "VKD3D-LICENSE")
    result["translated_sources"] = []
    for path in sources:
        matches = list(output.rglob(path.stem.replace(".", "_") + ".rs"))
        if len(matches) == 1:
            translated = matches[0]
            text = path.read_text()
            notices = [comment for comment in re.findall(r'/\*.*?\*/', text, re.S)
                       if re.search(r'copyright|general public license|special exception', comment, re.I)]
            assert notices, f"No license notice found in {path}"
            translated.write_text("\n".join(notices) + "\n" + translated.read_text())
            result["translated_sources"].append(str(path.relative_to(source)))
    result["invalid_output_markers"] = [str(p) for p in output.rglob("*.rs")
                                        if re.search(r'\b(compile_error|unimplemented|todo)\s*!', p.read_text())]
    result["complete_translation"] = (result["transpile"]["exit_code"] == 0
                                      and not result["invalid_output_markers"]
                                      and len(result["translated_sources"]) == len(sources))
    checksum = list(output.rglob("checksum.rs"))
    if len(checksum) == 1:
        module = '#[allow(dead_code, non_camel_case_types, non_upper_case_globals, unused_mut)]\n'
        module += '#[path = ' + json.dumps(str(checksum[0])) + '] pub mod checksum;\n'
        no_std = artifacts / "checksum_no_std.rs"
        no_std.write_text("#![no_std]\n" + module)
        result["checksum_no_std"] = run(["rustc", "+" + args.rust_toolchain, "--edition", "2024", "--crate-type", "rlib",
                                        str(no_std), "-o", str(artifacts / "checksum_no_std.rlib")],
                                       artifacts / "checksum-no-std.log", timeout=args.timeout)
        checks = []
        for data in (b"", b"abc", b"a" * 55, b"a" * 56, b"a" * 64, b"a" * 1000):
            checks.append(f"check(&{list(data)}, &{list(hashlib.md5(data).digest())});")
        harness = artifacts / "checksum_check.rs"
        harness.write_text(module + '''
fn check(data: &[u8], expected: &[u8]) {
    let mut digest = [0u32; 4];
    unsafe { checksum::vkd3d_compute_md5(data.as_ptr().cast(), data.len(),
        digest.as_mut_ptr(), checksum::vkd3d_md5_variant::VKD3D_MD5_STANDARD); }
    let bytes: Vec<u8> = digest.iter().flat_map(|x| x.to_ne_bytes()).collect();
    assert_eq!(bytes, expected);
}
fn main() {''' + "".join(checks) + 'println!("6 MD5 vectors passed");}\n')
        binary = artifacts / "checksum_check"
        result["checksum_check_build"] = run(["rustc", "+" + args.rust_toolchain, "--edition", "2024", str(harness), "-o", str(binary)],
                                              artifacts / "checksum-check-build.log", timeout=args.timeout)
        if result["checksum_check_build"]["exit_code"] == 0:
            result["checksum_check_run"] = run([str(binary)], artifacts / "checksum-check-run.log", timeout=args.timeout)
    result["rust_files"] = [str(p.relative_to(output)) for p in sorted(output.rglob("*.rs"))]
    inventory = extern_inventory(path.read_text() for path in output.rglob("*.rs"))
    (artifacts / "externs.json").write_text(json.dumps(inventory, indent=2) + "\n")
    if args.translation_only:
        result["translation_only"] = True
        result["status"] = outcome(result)
        checkpoint()
        return
    if args.all_unit_prototype and result["complete_translation"] and (output / "Cargo.toml").exists():
        from full_compiler import collect
        shutil.copy2(source / "LICENSE", output / "LICENSE")
        manifest = output / "Cargo.toml"
        manifest.write_text(manifest.read_text().replace("[package]", '[package]\nlicense = "LGPL-2.1-or-later"'))
        try:
            collect(result, args, source, output, entries, artifacts, run, checkpoint)
        finally:
            result["raw_preserved"] = all(
                (artifacts / "rust-raw" / name).is_file()
                and hashlib.sha256((artifacts / "rust-raw" / name).read_bytes()).hexdigest() == expected
                for name, expected in result.get("raw_sha256", {}).items())
            checkpoint()
        result["status"] = outcome(result)
        checkpoint()
        return
    if result["complete_translation"] and (output / "Cargo.toml").exists():
        shutil.copy2(source / "LICENSE", output / "LICENSE")
        manifest = output / "Cargo.toml"
        manifest.write_text(manifest.read_text().replace("[package]", '[package]\nlicense = "LGPL-2.1-or-later"'))
        env = dict(os.environ, CARGO_TARGET_DIR=str(artifacts / "rust-target"))
        env.pop("RUSTC_BOOTSTRAP", None)
        env.pop("RUSTFLAGS", None)
        env.pop("CARGO_ENCODED_RUSTFLAGS", None)
        result["stable_build"] = run(["cargo", "+" + args.rust_toolchain, "build", "--manifest-path", str(output / "Cargo.toml")],
                                      artifacts / "cargo-stable.log", env=env, timeout=args.build_timeout)
        checkpoint()
        if result["stable_build"]["exit_code"]:
            # Toolchain experiment only; never recommend bootstrap for production.
            env["RUSTC_BOOTSTRAP"] = "1"
            result["bootstrap_build"] = run(["cargo", "+" + args.rust_toolchain, "build", "--manifest-path", str(output / "Cargo.toml")],
                                             artifacts / "cargo-bootstrap.log", env=env, timeout=args.build_timeout)
            checkpoint()
            if result["bootstrap_build"]["exit_code"]:
                result["prototype_flags"] = "-Zcrate-attr=feature(stmt_expr_attributes) -Astatic_mut_refs"
                env["RUSTFLAGS"] = result["prototype_flags"]
                result["prototype_build"] = run(["cargo", "+" + args.rust_toolchain, "build", "--manifest-path", str(manifest)],
                                                 artifacts / "cargo-prototype.log", env=env, timeout=args.build_timeout)
    result["status"] = outcome(result)
    checkpoint()
    print(json.dumps({k: v for k, v in result.items() if k not in ("input_sha256", "syntax")}, indent=2))


if __name__ == "__main__":
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"Interrupted by signal {signum}")
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    main()
