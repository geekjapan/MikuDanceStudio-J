"""Hosted legal actual-capture admission followed by bound malformed peers."""
import argparse
import json
import os
from pathlib import Path

from evidence import Capture, admit_capture, actual_peer_controls, read_authority, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--authority', type=Path, required=True)
    parser.add_argument('--authority-size', type=int, required=True)
    parser.add_argument('--authority-sha256', required=True)
    args = parser.parse_args()
    authority = read_authority(args.authority, size=args.authority_size, sha256=args.authority_sha256)
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'actual capture validation is hosted-only')
    import check
    inputs, cases = check.corpus()
    expected = {'authority':authority,'expected_head':os.environ['GITHUB_SHA'],
                'canonical_sources':{p:(check.ROOT/p).read_bytes() for p in check.snapshot()},
                'inputs':inputs,'cases':cases,
                'expected_host':{('Windows','amd64'),('Windows','x86_64'),('Darwin','arm64'),
                                 ('Linux','x86_64'),('Linux','aarch64'),('Linux','arm64')}}
    admit_capture(args.capture,**expected)
    controls = actual_peer_controls(Capture.open(args.capture, expected=authority),**expected)
    print(json.dumps(controls,sort_keys=True))


if __name__ == '__main__':
    main()
