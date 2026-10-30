"""Opt-in all24 ON-only observations; never a paired acceptance result."""
import argparse
import json
import os
from pathlib import Path
import shutil
import time

MAX_LINE = 2048
MAX_EVENTS = 4096
MAX_BYTES = 4 * 1024 * 1024
READ_BYTES = 64 * 1024
STAGES = frozenset(('NativeExport', 'NativeMarshal', 'NativeDrop', 'CborDecode', 'CborProcess',
                    'TypedImport', 'NativeIntake', 'UnitRetain', 'PlanCapture', 'SymbolClosure',
                    'PerUnitBind', 'PlanReport', 'Serialization', 'Emit', 'Telemetry'))
COUNT_KEYS = frozenset(('unit_index', 'retained_units', 'cbor_bytes', 'cursor_json_bytes',
                        'source_bytes', 'decls', 'exprs', 'types'))
RECORD_KEYS = frozenset(('schema', 'pid', 'sequence', 'monotonic_ns', 'stage', 'edge', 'status',
                         'rss_kib', 'hwm_kib', 'counts'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate retention key')
        result[key] = value
    return result


def uint(value):
    return type(value) is int and 0 <= value < 2**64


def parse_record(raw, pid, sequence, previous_ns):
    require(type(raw) is bytes and len(raw) <= MAX_LINE and raw.endswith(b'\n'), 'retention line bound')
    record = json.loads(raw, object_pairs_hook=unique,
                        parse_constant=lambda _: require(False, 'nonfinite retention number'))
    require(type(record) is dict and set(record) == RECORD_KEYS, 'retention record schema')
    require(type(record['schema']) is int and record['schema'] == 1, 'retention schema version')
    require(uint(record['pid']) and record['pid'] == pid and pid > 0, 'retention child PID')
    require(uint(record['sequence']) and record['sequence'] == sequence < MAX_EVENTS, 'retention sequence')
    require(uint(record['monotonic_ns']) and record['monotonic_ns'] >= previous_ns, 'retention monotonic time')
    require(type(record['stage']) is str and record['stage'] in STAGES, 'retention stage')
    require(type(record['edge']) is str and record['edge'] in ('Begin', 'End', 'Observation'), 'retention edge')
    require(type(record['status']) is str and record['status'] in ('ok', 'unavailable', 'truncated'), 'retention status')
    require((record['stage'] == 'Telemetry') == (record['edge'] == 'Observation'), 'retention observation shape')
    require(record['status'] != 'truncated' or record['stage'] == 'Telemetry', 'retention truncation shape')
    for key in ('rss_kib', 'hwm_kib'):
        require(record[key] is None or uint(record[key]), 'retention RSS type')
    require(record['status'] != 'ok' or all(record[k] is not None for k in ('rss_kib', 'hwm_kib')),
            'retention RSS unavailable')
    counts = record['counts']
    require(type(counts) is dict and set(counts) == COUNT_KEYS, 'retention counts schema')
    require(all(v is None or uint(v) for v in counts.values()), 'retention count type')
    require(counts['unit_index'] is None or counts['unit_index'] < 24, 'retention unit bound')
    require(counts['retained_units'] is None or counts['retained_units'] <= 24, 'retention retained bound')
    return record


class RetentionForwarder:
    """One owned binary sidecar, bounded reads and partial tail, no child log forwarding."""
    INTERVAL = 0.25

    def __init__(self, stream, pid, emit=print):
        self.stream, self.pid, self.emit = stream, pid, emit
        self.pending = b''
        self.bytes = self.sequence = self.previous_ns = 0
        self.next_read = 0.0
        self.disabled = False

    def unavailable(self):
        if not self.disabled:
            self.disabled = True
            self.pending = b''
            try:
                self.emit('RETENTION_DIAGNOSTIC_UNAVAILABLE sidecar', flush=True)
            except OSError:
                pass

    def drain(self, final=False):
        if self.disabled:
            return
        self.next_read = time.monotonic() + self.INTERVAL
        try:
            # The reader refuses overflow before attempting a larger allocation.
            chunk = self.stream.read(min(READ_BYTES, MAX_BYTES - self.bytes + 1))
            require(type(chunk) is bytes, 'binary retention sidecar')
            self.bytes += len(chunk)
            require(self.bytes <= MAX_BYTES, 'retention byte cap')
            data = self.pending + chunk
            self.pending = b''
            while b'\n' in data:
                raw, data = data.split(b'\n', 1)
                raw += b'\n'
                record = parse_record(raw, self.pid, self.sequence, self.previous_ns)
                self.emit('RETENTION_EVENT ' + raw.decode('utf-8').rstrip('\n'), flush=True)
                self.sequence += 1
                self.previous_ns = record['monotonic_ns']
                if record['status'] == 'truncated':
                    require(not data, 'records after retention truncation')
                    self.disabled = True
                    return
            require(len(data) < MAX_LINE, 'retention partial line cap')
            self.pending = data
            if final:
                if chunk:
                    self.drain(final=True)
                else:
                    require(not self.pending and self.sequence > 0, 'missing or incomplete retention records')
        except (OSError, ValueError, UnicodeError, RecursionError):
            self.unavailable()


def collect(tool, source, clang, output, timeout):
    from full_compiler import UNITS, verify_cursor_tool
    from probe import compilation_entries, run
    from check_common_plan import sha, validate_plan
    verify_cursor_tool(tool)
    require(output != source and source not in output.parents, 'diagnostic output must be outside source')
    require(timeout == 1800, 'diagnostic command ceiling is fixed')
    output.mkdir(parents=True, exist_ok=False)
    original = source.resolve()
    copied = output / 'source'
    shutil.copytree(original, copied)
    entries = compilation_entries(copied, original, clang)
    require(sorted(str(Path(row['file']).relative_to(copied)) for row in entries) == list(UNITS),
            'diagnostic requires complete all24 input')
    database = output / 'compile_commands.json'
    database.write_text(json.dumps(entries, indent=2) + '\n')
    tool_root = tool.parent.parent
    shutil.copytree(tool_root / 'source-evidence', output / 'source-evidence')
    shutil.copy2(tool_root / 'source-receipt.json', output / 'source-receipt.json')
    identity = dict(compiler_sha256=sha(tool.read_bytes()),
                    source_receipt_sha256=sha((output / 'source-receipt.json').read_bytes()),
                    input_sha256={str(Path(row['file']).relative_to(copied)): sha(Path(row['file']).read_bytes()) for row in entries},
                    header_sha256={str(p): sha(p.read_bytes()) for directory in
                        (copied / 'include', copied / 'libs', original.parent / 'hdr/include', original.parent / 'spv/include')
                        for p in sorted(directory.rglob('*.h'))})
    (output / 'input-identity.json').write_text(json.dumps(identity, indent=2) + '\n')
    result = dict(authorization='diagnostic_only', paired_acceptance='UNRUN', status='incomplete')
    summary = output / 'diagnostic.json'
    summary.write_text(json.dumps(result, indent=2) + '\n')
    phase = output / 'retention.jsonl'
    with phase.open('xb'):
        pass
    phase.chmod(0o600)
    command = [str(tool), '--diagnostic-common-plan', '--fail-on-error', '--disable-rustfmt',
               '--edition', '2024', '--emit-build-files', '--output-dir', str(output / 'on'), str(database)]
    result['execution'] = run(command, output / 'on.log', timeout=timeout,
        env=dict(os.environ, MDS_C2RUST_RETENTION_DIAGNOSTICS='1', MDS_C2RUST_RETENTION_LOG=str(phase)),
        retention_log=phase, diagnostics=dict(phase='retention-on', path=output / 'on.diagnostics.jsonl'))
    summary.write_text(json.dumps(result, indent=2) + '\n')
    require(result['execution']['exit_code'] == 0 and not result['execution']['timed_out'], 'ON diagnostic compiler failed')
    result['plan_counts'] = validate_plan(json.loads((output / 'on/closed-variadic-plan.json').read_text()), entries)
    log = (output / 'on.log').read_text()
    for marker in ('COMMON_PLAN_NATIVE_EXPORT ', 'COMMON_PLAN_TYPED_IMPORT ', 'COMMON_PLAN_EMIT '):
        require(log.count(marker) == len(UNITS), 'diagnostic all24 trace differs')
    require(log.count('COMMON_PLAN_CLOSED 24') == 1 and log.index('COMMON_PLAN_CLOSED 24') < log.index('COMMON_PLAN_EMIT '),
            'diagnostic emission preceded complete plan')
    result['status'] = 'diagnostic_completed'
    summary.write_text(json.dumps(result, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('tool', 'source', 'clang', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=1800, choices=[1800])
    args = parser.parse_args()
    collect(args.tool.resolve(), args.source.resolve(), args.clang.resolve(), args.output.resolve(), args.timeout)


if __name__ == '__main__':
    main()
