#!/usr/bin/env python3
"""Replay downloaded consumer transports without compiling or running native code."""
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('consumer_check', HERE / 'check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def replay(capture, out, *, directed_marker=False, failure=None, changed_source=False):
    out.mkdir(parents=True, exist_ok=True)
    for path in capture.iterdir():
        if path.is_file():
            shutil.copyfile(path, out / path.name)
    original = json.loads((capture / 'report.json').read_text())
    archive = next(path for path in capture.iterdir() if path.suffix in ('.a', '.lib'))
    assert check.digest(archive) == original['archive']['sha256']
    shutil.copyfile(capture / 'archive-path.txt', out / 'original-archive-path.txt')
    (out / 'archive-path.txt').write_text(str(archive.resolve()))

    def run(argv, output, name, **kwargs):
        if failure and name == failure[0]:
            raise failure[1]
        stdout = (capture / (name + '.stdout')).read_bytes()
        stderr = (capture / (name + '.stderr')).read_bytes()
        code = 101 if name == 'rust-tests' and original['target'] == 'x86_64-pc-windows-msvc' else 0
        if name == 'rust-tests' and directed_marker:
            before = b'assertion `left == right` failed\n  left: [3, 2, 1]\n right: [2, 3, 1]'
            after = before.replace(b'failed\n', b'failed: DBVT_COMPATIBILITY_MISMATCH directed Select native\n')
            assert stdout.count(before) == 1
            stdout = stdout.replace(before, after)
        (out / (name + '.stdout')).write_bytes(stdout)
        return subprocess.CompletedProcess(argv, code, stdout, stderr)

    manifest = check.source_manifest()
    end = dict(manifest, **{'injected-source-change': 'changed'}) if changed_source else manifest
    with mock.patch.object(sys, 'argv', ['check.py', '--out-dir', str(out), '--target', original['target']]), \
            mock.patch.object(check, 'run', side_effect=run), \
            mock.patch.object(check, 'source_manifest', side_effect=[manifest, end]), \
            contextlib.redirect_stdout(io.StringIO()):
        code = check.main()
    report = json.loads((out / 'report.json').read_text())
    for name, expected in report['artifact_sha256'].items():
        assert check.digest(out / name) == expected, name
    assert 'check.log' not in report['artifact_sha256']
    if 'archive' in report:
        assert report['archive']['sha256'] == original['archive']['sha256']
    assert report['source_start_sha256'] == manifest
    assert report['source_sha256'] == end
    return code, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    results = {}
    for host in ('arm', 'x64', 'mac', 'win'):
        code, report = replay(args.artifacts / host, args.out_dir / host)
        expected = ('incomplete', 'not-evaluated', 'validation-gap') if host == 'win' else ('complete', 'PASS', 'compatible')
        assert tuple(report[key] for key in ('observation', 'compatibility', 'classification')) == expected
        assert code == int(host == 'win')
        results[host] = dict(zip(('observation', 'compatibility', 'classification'), expected))
    code, report = replay(args.artifacts / 'win', args.out_dir / 'win-directed-marker', directed_marker=True)
    assert code == 1 and report['observation'] == 'complete' and report['compatibility'] == 'FAIL'
    assert report['comparisons'] == dict(select=False, aabb=False, directed_select=False,
                                       controlled_corpus=True, ordinary_corpus=True, corpus=True)
    results['win-directed-marker'] = {key: report[key] for key in ('observation', 'compatibility', 'comparisons')}
    for name, error in [('compile', RuntimeError('consumer-build exited 1')),
                        ('signal', RuntimeError('consumer-build exited -11')),
                        ('parser', ValueError('malformed capture')),
                        ('configuration', KeyError('TARGET')),
                        ('configuration-shape', TypeError('expected configuration object'))]:
        code, report = replay(args.artifacts / 'mac', args.out_dir / name,
                              failure=('consumer-build', error))
        assert code == 1 and report['classification'] == 'validation-gap'
        assert report['observation'] == 'incomplete' and report['source_unchanged']
        results[name] = report['classification']
    for name, failure in [('source-change', None),
                          ('source-change-on-failure', ('consumer-build', RuntimeError('compile failure')))]:
        code, report = replay(args.artifacts / 'mac', args.out_dir / name,
                              changed_source=True, failure=failure)
        assert code == 1 and report['classification'] == 'validation-gap'
        assert report['observation'] == 'incomplete' and not report['source_unchanged']
        results[name] = report['classification']
    (args.out_dir / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
