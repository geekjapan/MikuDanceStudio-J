#!/usr/bin/env python3
"""Deterministic float-bit inputs shared by native capture and the Rust fixture."""
import struct


def word(value):
    return f'{struct.unpack("<I", struct.pack("<f", value))[0]:08x}'


def rows():
    dimensions = [
        (0, [0.5, 0, 0, 0]),
        (0, [0.12345679, 0, 0, 0]),
        (0, [0.000001, 0, 0, 0]),
        (0, [8192.125, 0, 0, 0]),
        (1, [1, 2, 3, 0]),
        (1, [0.01, 0.04, 0.040000004, 0]),
        (1, [0.12345679, 2.3456788, 34.56789, 0]),
        (1, [0.000001, 1024.25, 0.75, 0]),
        (2, [0.5, 2, 0, 0]),
        (2, [0.5, 0, 0, 0]),
        (2, [0.000001, 0.000003, 0, 0]),
        (2, [0.12345679, 3.456789, 0, 0]),
        (3, [0, 1, 0, 0]),
        (3, [0.6, 0.8, 0, 1.5]),
        (3, [-0.0001, 0.9999, 0.0002, -12.25]),
        # mds_mmd does not validate dimensions; retain its raw constructor path.
        (0, [0, 0, 0, 0]),
        (1, [0, -0.25, 0.01, 0]),
        (2, [0.25, -0.5, 0, 0]),
    ]
    rotations = [[0, 0, 0, 1], [0, 0, 1, 1], [1, -2, 3, 4],
                 [0.12345679, -0.2345679, 0.3456789, 0.8765432]]
    index = 0
    for kind, params in dimensions:
        for mass in [0, 0.12345679, 7.25, 1024.125]:
            for rotation in rotations:
                values = params + [mass] + [-1.2345679, 0.00001, 123.45679] + rotation
                yield '\t'.join([str(index), str(kind), *map(word, values)])
                index += 1


if __name__ == '__main__':
    print('\n'.join(rows()))
