"""Audit DX11 compatibility rebuilds and timestamps without a speed/equivalence tolerance."""
import argparse
import csv
import hashlib
import json
import math
import statistics
from pathlib import Path
from analyze_accessory_isolation import tags
from analyze_model_sampling import require


def read_rows(path):
    with path.open(newline='') as file:
        return list(csv.DictReader(file))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    root = args.evidence
    state = (args.archive/'history_replay.scene_prefix.draw1.state').read_text().splitlines()
    target = tags(next(s for s in state if s.startswith('TARGET ')))
    viewport = tags(next(s for s in state if s.startswith('VIEWPORT ')))
    width, height = int(target['width']), int(target['height'])
    extent = int(viewport['width'])*int(viewport['height'])*4
    final = (args.archive/'history_replay.scene_prefix.final.bgra').read_bytes()
    require(len(final) == extent, 'wrong final captured extent')
    meta = (root/'metadata.txt').read_text().strip()
    require('doubles=1 selected=dx9_measured applicationActivation=0 samples=1' in meta, 'wrong device policy')
    run = tags((root/'summary.txt').read_text())
    wanted = {'complete': '1', 'devices': '2', 'resizesPerDevice': '5', 'boundaries': '520', 'staleRejected': '13260',
              'totalUploads': '286', 'repeats': '3', 'timingSamplesPerMode': '12', 'timingWarmup': '3', 'timedFailureRecovered': '1', 'applicationActivation': '0'}
    require(all(run.get(k) == v for k, v in wanted.items()), 'missing lifecycle completion')
    rows = read_rows(root/'lifecycle.csv')
    require(len(rows) == 520, 'missing boundaries')
    identities, image_hashes, previous = {}, {}, {}
    for i, row in enumerate(rows):
        replacement, resize, boundary = i//260, (i//52)%5, i%52
        phase = f'device{replacement}_resize{resize}'
        require(row['phase'] == phase and int(row['boundary']) == boundary, 'wrong boundary sequence')
        w, h = width+(16*resize if resize%2 else 0), height+(8*resize if resize%2 else 0)
        require((int(row['width']), int(row['height']), int(row['epoch'])) == (w, h, resize+2), 'wrong target or epoch')
        require(int(row['rejected']) == boundary and row['uploads'] == '143' and row['textureUploads'] == '42'
                and row['differentPixels'] == '0', 'incorrect stale/resource/image results')
        identity = int(row['identity'])
        identities.setdefault(replacement, identity)
        require(identities[replacement] == identity and identity != 0, 'identity changed during resize')
        current_hash = int(row['hash'])
        previous.setdefault(boundary, current_hash)
        require(previous[boundary] == current_hash, 'boundary hash changed after rebuild')
        if boundary == 51:
            for suffix in ('', '_repeat1', '_repeat2', '_repeat3'):
                name = phase+suffix+'.bgra'
                data = (root/name).read_bytes()
                require(data == final, 'full image differs after rebuild: '+name)
                image_hashes[name] = hashlib.sha256(data).hexdigest()
    require(identities[0] != identities[1], 'device identity reused after replacement')
    reference_hashes = {}
    for boundary in range(52):
        file = 'history_replay.scene_prefix.final.bgra' if boundary == 51 else f'history_replay.scene_prefix.draw{boundary+1}.before.bgra'
        data = (args.archive/file).read_bytes()
        require(len(data) == extent, 'wrong captured boundary extent')
        value = 14695981039346656037
        for byte in data:
            value = ((value ^ byte)*1099511628211) & ((1 << 64)-1)
        require(value == previous[boundary], 'boundary not supported by actual captured image')
        reference_hashes[str(boundary)] = hashlib.sha256(data).hexdigest()
    samples = read_rows(root/'timing.csv')
    require(len(samples) == 30, 'missing GPU timing samples')
    timing = {}
    for mode in ('default', 'dx9_measured'):
        selected = [s for s in samples if s['mode'] == mode]
        require([int(s['iteration']) for s in selected] == list(range(15)), 'missing/duplicate timing iteration')
        for s in selected:
            require(s['valid'] == '1' and s['disjoint'] == '0' and int(s['frequency']) > 0
                    and int(s['warmup']) == (int(s['iteration']) < 3), 'invalid/disjoint timestamp interval')
            for key in ('gpuMs', 'wholeReplayMs'):
                require(math.isfinite(float(s[key])) and float(s[key]) > 0, 'invalid timing value')
            if mode == 'dx9_measured':
                require(s['differentPixels'] == '0', 'timed compatible draw differs')
        measured = [s for s in selected if s['warmup'] == '0']
        timing[mode] = {key: {'median': statistics.median(float(s[key]) for s in measured),
                            'min': min(float(s[key]) for s in measured), 'max': max(float(s[key]) for s in measured)}
                        for key in ('gpuMs', 'wholeReplayMs')}
        timing[mode]['differentPixels'] = sorted({int(s['differentPixels']) for s in selected})
    result = {'boundaries': 520, 'staleRejected': 13260, 'retainedResourcesPerResize': 143, 'texturesPerDevice': 42,
              'imagesExact': True, 'timestampSamplesPerMode': 12, 'timing': timing,
              'gpuMedianRatio': timing['dx9_measured']['gpuMs']['median']/timing['default']['gpuMs']['median'],
              'applicationActivation': False, 'msaaAcceptance': False,
              'imageSHA256': image_hashes, 'referenceSHA256': reference_hashes}
    if args.compare:
        for name, digest in image_hashes.items():
            require(hashlib.sha256((args.compare/name).read_bytes()).hexdigest() == digest, 'cross-architecture image differs')
        other_rows = read_rows(args.compare/'lifecycle.csv')
        require(len(other_rows) == len(rows), 'different cross-architecture boundary count')
        for a, b in zip(rows, other_rows):
            require(a == b, 'cross-architecture boundary metrics differ')
        result['crossArchitectureImageAndStateExact'] = True
    (root/'analysis.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('imageSHA256', 'referenceSHA256')}, indent=2))


if __name__ == '__main__':
    main()
