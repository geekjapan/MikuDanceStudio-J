#!/usr/bin/env python3
"""Inject a real source change after successful capture through check.main/finally."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--legacy-finally', action='store_true')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('objects_check', HERE / 'check.py')
    check = importlib.util.module_from_spec(spec)
    source = (HERE / 'check.py').read_text()
    if args.legacy_finally:
        begin = source.index("        if status['integrity'] != 'PASS':")
        end = source.index('    print(json.dumps(status,indent=2))', begin)
        source = source[:begin] + "        save('status.json',status)\n        assert status['integrity']=='PASS', 'source/include/generated closure changed'\n" + source[end:]
    exec(compile(source, str(HERE / 'check.py'), 'exec'), check.__dict__)
    marker = HERE / 'integrity-injected.txt'
    if marker.exists(): raise RuntimeError('injection marker already exists')
    injected = False
    injection_line = next(i for i,line in enumerate(source.splitlines(),1) if 'after = source_snapshot()' in line)
    def inject(frame, event, arg):
        nonlocal injected
        if frame.f_code.co_name != 'main' or frame.f_code.co_filename != str(HERE / 'check.py'): return None
        if event == 'line' and frame.f_lineno == injection_line:
            status = frame.f_locals.get('status', {})
            if not injected and status.get('status','').startswith('PASS'):
                marker.write_text('real source mutation after successful capture\n'); injected = True
        return inject
    old_argv = sys.argv
    sys.argv = [str(HERE / 'check.py'), '--skip-mutations', '--out-dir', str(args.out_dir)]
    error = None
    try:
        sys.settrace(inject)
        check.main()
    except AssertionError as caught:
        error = str(caught)
    finally:
        sys.settrace(None);sys.argv = old_argv
        if injected: marker.unlink()
    receipt = json.loads((args.out_dir / 'status.json').read_text())
    if not injected or error is None or receipt['integrity'] != 'FAIL':
        raise AssertionError('did not exercise the successful main/finally integrity failure')
    expected = 'PASS_FOCUSED_ONLY' if args.legacy_finally else 'FAIL'
    if receipt['status'] != expected: raise AssertionError(receipt)
    if not args.legacy_finally and receipt.get('error') != 'closure changed: source': raise AssertionError(receipt)
    print(json.dumps({'injected_real_source_change': injected, 'legacy_finally': args.legacy_finally, 'receipt':receipt},indent=2))

if __name__ == '__main__': main()
