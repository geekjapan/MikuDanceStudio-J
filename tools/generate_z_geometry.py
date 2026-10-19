"""Generate independent Z-sensitive four-term dot fixtures without GPU feedback."""
import argparse
import json
from pathlib import Path
import random
import struct
from generate_sensitive_depth_matrices import f32, dot, RULES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rng = random.Random(20261005)
    cases = []
    for attempt in range(100000):
        column = [f32(rng.uniform(-.9, .9)) for _ in range(3)]+[f32(rng.uniform(3.5, 4.5))]
        if any(abs(v) < .08 for v in column[:3]):
            continue
        shape = f32(rng.uniform(.86, .97))
        objects = [[-shape, -shape, f32(rng.uniform(.2, 1)), 1.],
                   [-shape, shape, f32(rng.uniform(.2, 1)), 1.],
                   [shape, -shape, f32(rng.uniform(.2, 1)), 1.]]
        outputs = {rule: [dot(p, column, rule) for p in objects] for rule in RULES}
        if len({tuple(z) for z in outputs.values()}) < 3 or outputs['fused'] == outputs['sequential']:
            continue
        if not all(.3 < z/6 < .95 for values in outputs.values() for z in values):
            continue
        matrix = [0.]*16
        matrix[0] = matrix[5] = 6.
        matrix[15] = 6.  # W exact and constant; only Z's arithmetic varies.
        for index, value in zip((2, 6, 10, 14), column):
            matrix[index] = value
        cases.append({'id': len(cases), 'split': 'calibration' if len(cases) < 6 else 'holdout',
            'attempt': attempt, 'matrix': matrix, 'objects': objects, 'cpuZ': outputs})
        if len(cases) == 12:
            break
    if len(cases) != 12:
        raise ValueError('insufficient Z-discriminating fixtures')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(b'ZGEOM001'+struct.pack('<I', 12)+b''.join(
        struct.pack('<28f', *(c['matrix']+[v for p in c['objects'] for v in p])) for c in cases))
    args.output.with_suffix('.json').write_text(json.dumps({'seed': 20261005,
        'selection': 'CPU Z bit discrimination and visible depth only; no GPU measurements.',
        'points': [[36, 46], [20, 42], [28, 44]], 'cases': cases}, indent=2)+'\n')
    print(f'cases=12 calibration=6 holdout=6 output={args.output}')


if __name__ == '__main__':
    main()
