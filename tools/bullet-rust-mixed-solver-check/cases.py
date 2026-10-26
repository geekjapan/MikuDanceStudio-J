"""Explicit serialized input order shared by native and Rust consumers."""
import random
import struct


def corpus():
    rng = random.Random(0x275260)
    def f(x):
        return struct.unpack('<I', struct.pack('<f', x))[0]
    identity = [1., 0., 0., 0., 1., 0., 0., 0., 1.]
    lines = []
    for case in range(96):
        variant = case % 48
        count = 8 if variant >= 32 else 3
        words = [f(1 / 60), 260 if case < 48 else 4, count, 2]
        for i in range(count):
            mass = 0. if i == 0 or (variant % 13 == 4 and i == 2) else float(i)
            origin = [i * .125, .45 + i * .05, -.125 * i]
            basis = identity if variant % 4 else [0., -1., 0., 1., 0., 0., 0., 0., 1.]
            velocities = [rng.uniform(-1, 1) for _ in range(6)] if variant % 6 else [0.] * 6
            lf = [.5, 1.25, -0.] if variant % 3 == 0 else [1.] * 3
            af = [1.5, .25, 0.] if variant % 3 == 0 else [1.] * 3
            inertia = [0.] * 3 if variant == 23 else [float(i + 1), float(i + 2), float(i + 3)]
            words += list(map(f, [mass] + inertia + basis + origin + velocities + lf + af))
            words += [int(i == 2 and variant % 7 == 0)]
        joints = [] if variant == 0 else [[i, i + 1] for i in range(1, count - 1)]
        if variant == 1:
            joints = []
        if variant % 9 == 1:
            joints.insert(0, [0, count - 1])
        if variant % 2:
            joints.reverse()
        words += [len(joints)]
        for ji, pair in enumerate(joints):
            words += pair + list(map(f, identity + [0.] * 3 + identity + [0., .125, 0.]))
            for axis in range(6):
                free = variant % 9 == 1 and ji == 0
                lower, upper = (1., -1.) if free or axis > 1 else (-.05, .05)
                spring = not free and axis == 1
                enabled = not free and axis == 3 and (variant % 8 == 3 or variant == 23)
                words += [f(lower), f(upper), int(enabled), f(.125), f(-2. if variant % 8 == 3 else 2.), int(spring), f(.0625), f(3.), f(.5)]
        manifolds = [] if variant == 0 else [[i, 0] for i in range(1, count)]
        if variant % 9 == 1:
            manifolds = [[1, 0]]
        if variant % 5 == 0 and manifolds:
            manifolds.append(manifolds[0][:])
        if variant % 2:
            manifolds.reverse()
        if variant == 7:
            manifolds = [[0, 0]]
        words += [len(manifolds)]
        for mi, pair in enumerate(manifolds):
            n = 0 if variant == 2 else variant % 4 + 1
            threshold = .02 if variant % 5 == 2 else 1e18
            words += pair + [f(threshold), n]
            points = list(range(n))
            if variant % 3 == 1:
                points.reverse()
            for pi in points:
                distance = -1e10 if variant == 15 else [.02, .020000003, .019999998][pi % 3] if variant % 5 == 2 else (.05 if variant % 8 == 4 else -.025 * (pi + 1))
                friction = [-.75, 0., .25, .8][variant % 4]
                # local A/B, world A/B, normal, distance/material/impulses, lifetime/flag/directions.
                values = [float(pi), 0., 0., 0., float(pi), 0., pair[0] * .125 + pi * .05, .425, -.125 * pair[0], pi * .05, 0., 0., 0., 1., 0., distance, friction, .88 if variant % 2 else 0., .2 if variant % 3 else -.1, .125, -.25]
                words += list(map(f, values)) + [2 + variant % 2, variant % 2] + list(map(f, [1., 0., 0., 0., 0., 1.]))
        lines.append(str(case) + '\t' + '\t'.join(f'{w:08x}' for w in words))
    for mode in [260, 4]:
        for excluded in [True, False]:
            words = [f(1 / 60), mode, 3, 2]
            for i in range(3):
                mass = 0. if i == 0 or (not excluded and i == 1) else float(i)
                words += list(map(f, [mass] + [1., 2., 3.] + identity + [i * .125, .5, 0.] + [.125, -.25, .375, 0., 0., 0.] + [1.] * 6))
                words += [int(not excluded and i > 0)]
            words += [0, 1, 1, 2, f(.02), 2]
            for pi in range(2):
                values = [float(pi), 0., 0., 0., float(pi), 0., .125, .5, 0., .25, .5, 0., 0., 1., 0., .020000003 + pi * .001 if excluded else -.025, .5, 0., .2, .125, -.25]
                words += list(map(f, values)) + [2, 0] + list(map(f, [1., 0., 0., 0., 0., 1.]))
            lines.append(str(len(lines)) + '\t' + '\t'.join(f'{w:08x}' for w in words))
    return '\n'.join(lines) + '\n'


def input_records(text):
    result = []
    for line in text.splitlines():
        fields = line.split('\t'); case = int(fields[0]); words = fields[1:]; cursor = 4
        def take(n):
            nonlocal cursor
            value = words[cursor:cursor+n]; cursor += n
            assert len(value) == n
            return value
        def count():
            return int(take(1)[0], 16)
        bodies = [take(29) for _ in range(int(words[2], 16))]
        joints = [take(80) for _ in range(count())]
        manifolds = []
        for _ in range(count()):
            header = take(4)
            manifolds.append((header, [take(29) for _ in range(int(header[3], 16))]))
        assert cursor == len(words)
        result.append((case, int(words[1], 16), bodies, joints, manifolds))
    return result
